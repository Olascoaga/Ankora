"""Validated, cancellable AutoDock Vina jobs for ligands and libraries."""

import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path

from ankora_backend.adapters.engines.vina import (
    VinaInstallation,
    build_vina_arguments,
    execute_vina,
    parse_vina_poses,
    probe_vina,
)
from ankora_backend.domain.errors import AnkoraDomainError
from ankora_backend.persistence.binding_site_store import BindingSiteArtifactStore
from ankora_backend.persistence.docking_store import DockingArtifactStore
from ankora_backend.persistence.ligand_store import LigandArtifactStore
from ankora_backend.persistence.receptor_store import ReceptorArtifactStore
from ankora_backend.schemas.binding_sites import BindingBox, BindingSiteRecord
from ankora_backend.schemas.docking import (
    DockingBatchCancelResponse,
    DockingCancelResponse,
    DockingExecutionEvidence,
    DockingFailure,
    DockingJobPhase,
    DockingJobStatus,
    DockingPoseArtifact,
    DockingPoseResult,
    VinaBatchDockingRecord,
    VinaBatchDockingRequest,
    VinaBatchLigandResult,
    VinaBatchProgress,
    VinaDockingJobRecord,
    VinaDockingParameters,
    VinaDockingRequest,
)
from ankora_backend.schemas.ligand_library_preparation import LigandPreparationStatus
from ankora_backend.schemas.provenance import ProvenanceEvent, ToolIdentity
from ankora_backend.schemas.receptors import (
    ReceptorOutputArtifact,
    ReceptorOutputStage,
    ReceptorPreparationStatus,
)


@dataclass(frozen=True)
class _BatchWorkItem:
    ligand_id: str
    ligand_path: Path


class VinaDockingService:
    """Owns the Vina schedulers and their cancellation signals.

    Single-ligand jobs serialize through the service executor. A library job
    fans out verified prepared ligands through a bounded inner pool while
    dividing the explicit total CPU budget between its Vina processes.
    """

    def __init__(
        self,
        *,
        docking_store: DockingArtifactStore,
        receptor_store: ReceptorArtifactStore,
        binding_site_store: BindingSiteArtifactStore,
        ligand_store: LigandArtifactStore,
    ) -> None:
        self._docking_store = docking_store
        self._receptor_store = receptor_store
        self._binding_site_store = binding_site_store
        self._ligand_store = ligand_store
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ankora-vina")
        self._cancel_events: dict[str, threading.Event] = {}
        self._active_batch_ids: set[str] = set()
        self._batch_start_lock = threading.Lock()
        self._lock = threading.RLock()

    @classmethod
    def from_environment(cls) -> "VinaDockingService":
        return cls(
            docking_store=DockingArtifactStore.from_environment(),
            receptor_store=ReceptorArtifactStore.from_environment(),
            binding_site_store=BindingSiteArtifactStore.from_environment(),
            ligand_store=LigandArtifactStore.from_environment(),
        )

    def start(self, request: VinaDockingRequest) -> VinaDockingJobRecord:
        installation = probe_vina()
        receptor_output, receptor_path, ligand_path, binding_site = self._validate_inputs(
            request
        )
        job_id = self._docking_store.new_job_id()
        output_path = self._docking_store.output_path(job_id, "vina_poses.pdbqt")
        command = [
            installation.executable,
            *build_vina_arguments(
                receptor_path=receptor_path,
                ligand_path=ligand_path,
                output_path=output_path,
                box=binding_site.box,
                parameters=request.parameters,
            ),
        ]
        record = VinaDockingJobRecord(
            job_id=job_id,
            status=DockingJobStatus.QUEUED,
            phase=DockingJobPhase.QUEUED,
            created_at=datetime.now(UTC),
            request=request,
            tool=ToolIdentity(name="AutoDock Vina", version=installation.version),
            receptor_output_artifact_id=receptor_output.artifact_id,
            receptor_sha256=receptor_output.sha256,
            ligand_sha256=self._sha256_file(ligand_path),
            command=command,
        )
        self._docking_store.create_job(record)
        cancel_event = threading.Event()
        with self._lock:
            self._cancel_events[job_id] = cancel_event
        self._executor.submit(
            self._run,
            job_id,
            installation,
            receptor_path,
            ligand_path,
            output_path,
            binding_site.box,
            cancel_event,
        )
        return record

    def get(self, job_id: str) -> VinaDockingJobRecord:
        return self._docking_store.load_record(job_id)

    def cancel(self, job_id: str) -> DockingCancelResponse:
        with self._lock:
            record = self._docking_store.load_record(job_id)
            if record.status in {
                DockingJobStatus.CANCELED,
                DockingJobStatus.COMPLETED,
                DockingJobStatus.FAILED,
            }:
                return DockingCancelResponse(job_id=job_id, status=record.status)
            cancel_event = self._cancel_events.get(job_id)
            if cancel_event is None:
                raise AnkoraDomainError(
                    code="DOCKING_JOB_NOT_ACTIVE",
                    stage="vina_docking",
                    message="The docking job is not active in this Ankora session.",
                    status_code=409,
                    details={"job_id": job_id, "status": record.status.value},
                )
            cancel_event.set()
            requested = record.model_copy(
                update={"status": DockingJobStatus.CANCEL_REQUESTED}
            )
            self._docking_store.update_record(requested)
        return DockingCancelResponse(
            job_id=job_id, status=DockingJobStatus.CANCEL_REQUESTED
        )

    def pose_content_path(self, job_id: str, artifact_id: str) -> Path:
        return self._docking_store.pose_content_path(job_id, artifact_id)

    def start_batch(self, request: VinaBatchDockingRequest) -> VinaBatchDockingRecord:
        with self._batch_start_lock:
            existing = self._active_batch()
            if existing is not None:
                if existing.request == request:
                    return existing
                raise AnkoraDomainError(
                    code="DOCKING_BATCH_ALREADY_ACTIVE",
                    stage="vina_docking",
                    message=(
                        "Another virtual-screening docking campaign is already active."
                    ),
                    status_code=409,
                    details={"active_batch_id": existing.batch_id},
                )
            return self._create_batch(request)

    def _create_batch(
        self, request: VinaBatchDockingRequest
    ) -> VinaBatchDockingRecord:
        installation = probe_vina()
        receptor_output, receptor_path, binding_site = self._validate_receptor_and_site(
            request.receptor_id, request.binding_site_id
        )
        filter_run = self._ligand_store.load_filter_run(
            request.library_id, request.filter_run_id
        )
        if filter_run.artifact.library_id != request.library_id:
            raise self._input_error(
                "DOCKING_LIBRARY_FILTER_MISMATCH",
                "The applied filter selection belongs to a different ligand library.",
                {
                    "library_id": request.library_id,
                    "filter_library_id": filter_run.artifact.library_id,
                },
            )
        manifest_path = self._ligand_store.filter_run_content_path(
            request.library_id, request.filter_run_id
        )
        self._verify_hash(
            manifest_path, filter_run.artifact.sha256, "selection_manifest"
        )
        if not filter_run.selected_ligand_ids:
            raise self._input_error(
                "DOCKING_LIBRARY_SELECTION_EMPTY",
                "The applied ligand selection contains no molecules to dock.",
                {"filter_run_id": request.filter_run_id},
            )

        library = self._ligand_store.load_library_record(request.library_id)
        preparation = self._ligand_store.load_preparation_status(request.library_id)
        ligands = {
            entry.ligand.artifact.ligand_id: (entry.record_index, entry.ligand)
            for entry in library.entries
            if entry.ligand is not None
        }
        now = datetime.now(UTC)
        entries: list[VinaBatchLigandResult] = []
        ready_paths: dict[str, Path] = {}
        for ligand_id in filter_run.selected_ligand_ids:
            source = ligands.get(ligand_id)
            status = preparation.entries.get(ligand_id)
            if source is None:
                entries.append(
                    self._unavailable_batch_entry(
                        ligand_id=ligand_id,
                        source_index=len(entries),
                        name="Unavailable library molecule",
                        message=(
                            "The selected molecule is absent from its immutable "
                            "library record."
                        ),
                        code="DOCKING_LIBRARY_LIGAND_MISSING",
                        completed_at=now,
                    )
                )
                continue
            source_index, ligand = source
            preparation_energy = (
                status.final_energy_kcal_mol if status is not None else None
            )
            if (
                status is None
                or status.status is not LigandPreparationStatus.PREPARED
                or status.pdbqt_preparation_id is None
            ):
                entries.append(
                    self._unavailable_batch_entry(
                        ligand_id=ligand_id,
                        source_index=source_index,
                        name=ligand.inspection.name,
                        canonical_smiles=ligand.inspection.canonical_smiles,
                        molecular_weight_g_mol=(
                            ligand.inspection.molecular_weight_g_mol
                        ),
                        preparation_energy_kcal_mol=preparation_energy,
                        message=(
                            "This selected molecule has no completed Meeko PDBQT preparation."
                        ),
                        code="DOCKING_LIGAND_NOT_PREPARED",
                        completed_at=now,
                    )
                )
                continue
            try:
                pdbqt = self._ligand_store.load_pdbqt_record(
                    ligand_id, status.pdbqt_preparation_id
                )
                ligand_path = self._ligand_store.pdbqt_content_path(
                    ligand_id, status.pdbqt_preparation_id
                )
                self._verify_hash(ligand_path, pdbqt.artifact.sha256, "ligand")
                if preparation_energy is None:
                    preparation_energy = self._ligand_store.load_conformer_record(
                        ligand_id, pdbqt.artifact.conformer_id
                    ).minimization.final_energy_kcal_mol
            except AnkoraDomainError as error:
                entries.append(
                    self._unavailable_batch_entry(
                        ligand_id=ligand_id,
                        source_index=source_index,
                        name=ligand.inspection.name,
                        canonical_smiles=ligand.inspection.canonical_smiles,
                        molecular_weight_g_mol=(
                            ligand.inspection.molecular_weight_g_mol
                        ),
                        preparation_energy_kcal_mol=preparation_energy,
                        message=error.message,
                        code=error.code,
                        completed_at=now,
                    )
                )
                continue
            entries.append(
                VinaBatchLigandResult(
                    ligand_id=ligand_id,
                    source_index=source_index,
                    name=ligand.inspection.name,
                    canonical_smiles=ligand.inspection.canonical_smiles,
                    molecular_weight_g_mol=ligand.inspection.molecular_weight_g_mol,
                    preparation_energy_kcal_mol=preparation_energy,
                    ligand_preparation_id=status.pdbqt_preparation_id,
                    ligand_sha256=pdbqt.artifact.sha256,
                    status=DockingJobStatus.QUEUED,
                    phase=DockingJobPhase.QUEUED,
                )
            )
            ready_paths[ligand_id] = ligand_path

        if not ready_paths:
            raise self._input_error(
                "DOCKING_LIBRARY_NOT_READY",
                "None of the selected molecules has a verified prepared PDBQT artifact.",
                {
                    "selected_count": len(filter_run.selected_ligand_ids),
                    "filter_run_id": request.filter_run_id,
                },
            )

        worker_count = min(request.parameters.parallel_ligands, len(ready_paths))
        threads_per_ligand = max(
            1, request.parameters.total_cpu_threads // worker_count
        )
        batch_id = self._docking_store.new_batch_id()
        execution_parameters = self._batch_execution_parameters(
            request, threads_per_ligand
        )
        work_items: list[_BatchWorkItem] = []
        for index, entry in enumerate(entries):
            prepared_path = ready_paths.get(entry.ligand_id)
            if prepared_path is None:
                continue
            output_path = self._docking_store.batch_output_path(
                batch_id, entry.ligand_id, "vina_poses.pdbqt"
            )
            command = [
                installation.executable,
                *build_vina_arguments(
                    receptor_path=receptor_path,
                    ligand_path=prepared_path,
                    output_path=output_path,
                    box=binding_site.box,
                    parameters=execution_parameters,
                ),
            ]
            entries[index] = entry.model_copy(update={"command": command})
            work_items.append(
                _BatchWorkItem(ligand_id=entry.ligand_id, ligand_path=prepared_path)
            )

        failed_count = sum(
            entry.status is DockingJobStatus.FAILED for entry in entries
        )
        record = VinaBatchDockingRecord(
            batch_id=batch_id,
            status=DockingJobStatus.QUEUED,
            phase=DockingJobPhase.QUEUED,
            created_at=now,
            request=request,
            tool=ToolIdentity(name="AutoDock Vina", version=installation.version),
            receptor_output_artifact_id=receptor_output.artifact_id,
            receptor_sha256=receptor_output.sha256,
            selection_manifest_artifact_id=filter_run.artifact.filter_run_id,
            selection_manifest_sha256=filter_run.artifact.sha256,
            selected_count=len(entries),
            worker_count=worker_count,
            threads_per_ligand=threads_per_ligand,
            completed_count=failed_count,
            succeeded_count=0,
            failed_count=failed_count,
            canceled_count=0,
            entries=entries,
        )
        self._docking_store.create_batch(record)
        cancel_event = threading.Event()
        with self._lock:
            self._cancel_events[batch_id] = cancel_event
            self._active_batch_ids.add(batch_id)
        self._executor.submit(
            self._run_batch,
            batch_id,
            installation,
            receptor_path,
            binding_site.box,
            work_items,
            execution_parameters,
            cancel_event,
        )
        return record

    def latest_batch(
        self, *, library_id: str, receptor_id: str, binding_site_id: str
    ) -> VinaBatchDockingRecord:
        matching = [
            record
            for record in self._docking_store.list_batch_records()
            if record.request.library_id == library_id
            and record.request.receptor_id == receptor_id
            and record.request.binding_site_id == binding_site_id
        ]
        if not matching:
            raise AnkoraDomainError(
                code="DOCKING_BATCH_HISTORY_EMPTY",
                stage="docking_storage",
                message="No docking campaign is available for these exact inputs.",
                status_code=404,
                details={
                    "library_id": library_id,
                    "receptor_id": receptor_id,
                    "binding_site_id": binding_site_id,
                },
            )
        with self._lock:
            active_ids = set(self._active_batch_ids)
        active = [
            record
            for record in matching
            if record.batch_id in active_ids
            and record.status
            not in {
                DockingJobStatus.CANCELED,
                DockingJobStatus.COMPLETED,
                DockingJobStatus.FAILED,
            }
        ]
        successful = [record for record in matching if record.succeeded_count > 0]
        candidates = active or successful or matching
        return max(
            candidates,
            key=lambda record: (record.created_at, record.batch_id),
        )

    def get_batch(self, batch_id: str) -> VinaBatchDockingRecord:
        return self._docking_store.load_batch_record(batch_id)

    def get_batch_progress(
        self, batch_id: str, *, after_revision: int
    ) -> VinaBatchProgress:
        """Return only ligand rows changed after the caller's last revision."""

        record = self._docking_store.load_batch_record(batch_id)
        return VinaBatchProgress(
            batch_id=record.batch_id,
            status=record.status,
            phase=record.phase,
            revision=record.revision,
            started_at=record.started_at,
            completed_at=record.completed_at,
            selected_count=record.selected_count,
            worker_count=record.worker_count,
            threads_per_ligand=record.threads_per_ligand,
            completed_count=record.completed_count,
            succeeded_count=record.succeeded_count,
            failed_count=record.failed_count,
            canceled_count=record.canceled_count,
            entries=[
                entry for entry in record.entries if entry.revision > after_revision
            ],
            failure=record.failure,
            provenance=record.provenance,
        )

    def cancel_batch(self, batch_id: str) -> DockingBatchCancelResponse:
        with self._lock:
            record = self._docking_store.load_batch_record(batch_id)
            if record.status in {
                DockingJobStatus.CANCELED,
                DockingJobStatus.COMPLETED,
                DockingJobStatus.FAILED,
            }:
                return DockingBatchCancelResponse(
                    batch_id=batch_id, status=record.status
                )
            cancel_event = self._cancel_events.get(batch_id)
            if cancel_event is None:
                raise AnkoraDomainError(
                    code="DOCKING_BATCH_NOT_ACTIVE",
                    stage="vina_docking",
                    message="The docking batch is not active in this Ankora session.",
                    status_code=409,
                    details={"batch_id": batch_id, "status": record.status.value},
                )
            cancel_event.set()
            self._docking_store.update_batch_record(
                record.model_copy(
                    update={
                        "status": DockingJobStatus.CANCEL_REQUESTED,
                        "revision": record.revision + 1,
                    }
                )
            )
        return DockingBatchCancelResponse(
            batch_id=batch_id, status=DockingJobStatus.CANCEL_REQUESTED
        )

    def batch_pose_content_path(
        self, batch_id: str, ligand_id: str, artifact_id: str
    ) -> Path:
        return self._docking_store.batch_pose_content_path(
            batch_id, ligand_id, artifact_id
        )

    def _run_batch(
        self,
        batch_id: str,
        installation: VinaInstallation,
        receptor_path: Path,
        box: BindingBox,
        work_items: list[_BatchWorkItem],
        parameters: VinaDockingParameters,
        cancel_event: threading.Event,
    ) -> None:
        try:
            if cancel_event.is_set():
                self._finish_batch(batch_id, canceled=True)
                return
            with self._lock:
                record = self._docking_store.load_batch_record(batch_id)
                self._docking_store.update_batch_record(
                    record.model_copy(
                        update={
                            "status": DockingJobStatus.RUNNING,
                            "phase": DockingJobPhase.DOCKING,
                            "started_at": datetime.now(UTC),
                            "revision": record.revision + 1,
                        }
                    )
                )
            with ThreadPoolExecutor(
                max_workers=record.worker_count,
                thread_name_prefix=f"ankora-vina-batch-{batch_id[:8]}",
            ) as workers:
                futures = [
                    workers.submit(
                        self._run_batch_item,
                        batch_id,
                        installation,
                        receptor_path,
                        box,
                        item,
                        parameters,
                        cancel_event,
                    )
                    for item in work_items
                ]
                for future in futures:
                    future.result()
            self._finish_batch(batch_id, cancel_event.is_set())
        except Exception as error:  # pragma: no cover - final supervisor containment
            with self._lock:
                record = self._docking_store.load_batch_record(batch_id)
                self._docking_store.update_batch_record(
                    record.model_copy(
                        update={
                            "status": DockingJobStatus.FAILED,
                            "phase": DockingJobPhase.COMPLETE,
                            "completed_at": datetime.now(UTC),
                            "revision": record.revision + 1,
                            "failure": DockingFailure(
                                code="VINA_BATCH_INTERNAL_ERROR",
                                message="Ankora could not complete the docking batch.",
                                details={"reason": str(error)},
                            ),
                        }
                    )
                )
        finally:
            self._forget(batch_id)

    def _run_batch_item(
        self,
        batch_id: str,
        installation: VinaInstallation,
        receptor_path: Path,
        box: BindingBox,
        item: _BatchWorkItem,
        parameters: VinaDockingParameters,
        cancel_event: threading.Event,
    ) -> None:
        entry = self._batch_entry(batch_id, item.ligand_id)
        if cancel_event.is_set():
            self._finish_batch_entry_canceled(batch_id, entry, None)
            return
        running = entry.model_copy(
            update={
                "status": DockingJobStatus.RUNNING,
                "phase": DockingJobPhase.DOCKING,
                "started_at": datetime.now(UTC),
            }
        )
        self._update_batch_entry(batch_id, running)
        output_path = self._docking_store.batch_output_path(
            batch_id, item.ligand_id, "vina_poses.pdbqt"
        )
        try:
            execution = execute_vina(
                installation=installation,
                receptor_path=receptor_path,
                ligand_path=item.ligand_path,
                output_path=output_path,
                box=box,
                parameters=parameters,
                cancel_event=cancel_event,
            )
            evidence = DockingExecutionEvidence(
                command=execution.command,
                exit_code=execution.exit_code,
                stdout=execution.stdout,
                stderr=execution.stderr,
                timed_out=execution.timed_out,
                canceled=execution.canceled,
            )
            self._docking_store.write_batch_text(
                batch_id, item.ligand_id, "stdout.log", execution.stdout
            )
            self._docking_store.write_batch_text(
                batch_id, item.ligand_id, "stderr.log", execution.stderr
            )
            if execution.canceled:
                self._finish_batch_entry_canceled(batch_id, running, evidence)
            elif execution.timed_out:
                self._finish_batch_entry_failed(
                    batch_id,
                    running,
                    evidence,
                    "VINA_TIMEOUT",
                    "AutoDock Vina exceeded the per-ligand execution time limit.",
                    {"timeout_minutes": parameters.timeout_minutes},
                )
            elif execution.exit_code != 0:
                self._finish_batch_entry_failed(
                    batch_id,
                    running,
                    evidence,
                    "VINA_EXECUTION_FAILED",
                    "AutoDock Vina did not complete this ligand calculation.",
                    {"exit_code": execution.exit_code},
                )
            elif not output_path.is_file():
                self._finish_batch_entry_failed(
                    batch_id,
                    running,
                    evidence,
                    "VINA_OUTPUT_MISSING",
                    "AutoDock Vina completed without producing this ligand's pose file.",
                    {},
                )
            else:
                self._finish_batch_entry_completed(
                    batch_id, running, output_path.read_bytes(), evidence
                )
        except AnkoraDomainError as error:
            current = self._batch_entry(batch_id, item.ligand_id)
            self._finish_batch_entry_failed(
                batch_id,
                current,
                current.execution,
                error.code,
                error.message,
                error.details,
            )
        except Exception as error:  # pragma: no cover - final worker containment
            current = self._batch_entry(batch_id, item.ligand_id)
            self._finish_batch_entry_failed(
                batch_id,
                current,
                current.execution,
                "VINA_JOB_INTERNAL_ERROR",
                "Ankora could not complete this ligand docking job.",
                {"reason": str(error)},
            )

    def _finish_batch_entry_completed(
        self,
        batch_id: str,
        entry: VinaBatchLigandResult,
        content: bytes,
        evidence: DockingExecutionEvidence,
    ) -> None:
        parsed = parse_vina_poses(content)
        poses: list[DockingPoseResult] = []
        for pose in parsed:
            artifact_id = f"{batch_id}-{entry.ligand_id}-pose-{pose.mode}"
            filename = f"pose_{pose.mode}.pdbqt"
            self._docking_store.write_batch_bytes(
                batch_id, entry.ligand_id, filename, pose.content
            )
            artifact = DockingPoseArtifact(
                artifact_id=artifact_id,
                mode=pose.mode,
                filename=filename,
                format="pdbqt",
                sha256=sha256(pose.content).hexdigest(),
                size_bytes=len(pose.content),
                content_url=(
                    f"/docking/batches/{batch_id}/ligands/{entry.ligand_id}"
                    f"/poses/{artifact_id}/content"
                ),
            )
            poses.append(
                DockingPoseResult(
                    mode=pose.mode,
                    affinity_kcal_mol=pose.affinity_kcal_mol,
                    rmsd_lower_bound_angstrom=pose.rmsd_lower_bound_angstrom,
                    rmsd_upper_bound_angstrom=pose.rmsd_upper_bound_angstrom,
                    artifact=artifact,
                )
            )
        completed_at = datetime.now(UTC)
        batch = self._docking_store.load_batch_record(batch_id)
        provenance = ProvenanceEvent(
            event_id=f"vina-batch-{batch_id}-{entry.ligand_id}",
            event_type="vina_library_ligand_completed",
            timestamp=completed_at,
            input_artifacts=[
                batch.receptor_output_artifact_id,
                batch.request.binding_site_id,
                entry.ligand_preparation_id or entry.ligand_id,
            ],
            output_artifacts=[pose.artifact.artifact_id for pose in poses],
            tool=batch.tool,
            parameters={
                **batch.request.parameters.model_dump(mode="json"),
                "threads_for_this_ligand": batch.threads_per_ligand,
            },
            command=evidence.command,
        )
        self._update_batch_entry(
            batch_id,
            entry.model_copy(
                update={
                    "status": DockingJobStatus.COMPLETED,
                    "phase": DockingJobPhase.COMPLETE,
                    "completed_at": completed_at,
                    "execution": evidence,
                    "poses": poses,
                    "provenance": provenance,
                }
            ),
        )

    def _finish_batch_entry_canceled(
        self,
        batch_id: str,
        entry: VinaBatchLigandResult,
        evidence: DockingExecutionEvidence | None,
    ) -> None:
        self._update_batch_entry(
            batch_id,
            entry.model_copy(
                update={
                    "status": DockingJobStatus.CANCELED,
                    "phase": DockingJobPhase.COMPLETE,
                    "completed_at": datetime.now(UTC),
                    "execution": evidence,
                }
            ),
        )

    def _finish_batch_entry_failed(
        self,
        batch_id: str,
        entry: VinaBatchLigandResult,
        evidence: DockingExecutionEvidence | None,
        code: str,
        message: str,
        details: dict[str, object],
    ) -> None:
        self._update_batch_entry(
            batch_id,
            entry.model_copy(
                update={
                    "status": DockingJobStatus.FAILED,
                    "phase": DockingJobPhase.COMPLETE,
                    "completed_at": datetime.now(UTC),
                    "execution": evidence,
                    "failure": DockingFailure(
                        code=code, message=message, details=details
                    ),
                }
            ),
        )

    def _finish_batch(self, batch_id: str, canceled: bool) -> None:
        with self._lock:
            record = self._docking_store.load_batch_record(batch_id)
            next_revision = record.revision + 1
            entries = [
                entry.model_copy(
                    update={
                        "status": DockingJobStatus.CANCELED,
                        "phase": DockingJobPhase.COMPLETE,
                        "completed_at": datetime.now(UTC),
                        "revision": next_revision,
                    }
                )
                if canceled
                and entry.status
                not in {
                    DockingJobStatus.COMPLETED,
                    DockingJobStatus.FAILED,
                    DockingJobStatus.CANCELED,
                }
                else entry
                for entry in record.entries
            ]
            counts = self._batch_counts(entries)
            completed_at = datetime.now(UTC)
            provenance = ProvenanceEvent(
                event_id=f"vina-library-docking-{batch_id}",
                event_type=(
                    "vina_library_docking_canceled"
                    if canceled
                    else "vina_library_docking_completed"
                ),
                timestamp=completed_at,
                input_artifacts=[
                    record.receptor_output_artifact_id,
                    record.request.binding_site_id,
                    record.selection_manifest_artifact_id,
                ],
                output_artifacts=[
                    pose.artifact.artifact_id
                    for entry in entries
                    for pose in entry.poses
                ],
                tool=record.tool,
                parameters={
                    **record.request.parameters.model_dump(mode="json"),
                    "worker_count": record.worker_count,
                    "threads_per_ligand": record.threads_per_ligand,
                },
            )
            self._docking_store.update_batch_record(
                record.model_copy(
                    update={
                        "status": (
                            DockingJobStatus.CANCELED
                            if canceled
                            else DockingJobStatus.COMPLETED
                        ),
                        "phase": DockingJobPhase.COMPLETE,
                        "completed_at": completed_at,
                        "entries": entries,
                        "provenance": provenance,
                        "revision": next_revision,
                        **counts,
                    }
                )
            )

    def _update_batch_entry(
        self, batch_id: str, updated: VinaBatchLigandResult
    ) -> None:
        with self._lock:
            record = self._docking_store.load_batch_record(batch_id)
            next_revision = record.revision + 1
            entries = list(record.entries)
            index = next(
                (
                    position
                    for position, entry in enumerate(entries)
                    if entry.ligand_id == updated.ligand_id
                ),
                None,
            )
            if index is None:
                raise self._input_error(
                    "DOCKING_BATCH_LIGAND_NOT_FOUND",
                    "The docking batch no longer contains its selected ligand.",
                    {"batch_id": batch_id, "ligand_id": updated.ligand_id},
                )
            entries[index] = updated.model_copy(
                update={"revision": next_revision}
            )
            self._docking_store.update_batch_record(
                record.model_copy(
                    update={
                        "entries": entries,
                        "revision": next_revision,
                        **self._batch_counts(entries),
                    }
                )
            )

    def _batch_entry(self, batch_id: str, ligand_id: str) -> VinaBatchLigandResult:
        record = self._docking_store.load_batch_record(batch_id)
        entry = next(
            (item for item in record.entries if item.ligand_id == ligand_id), None
        )
        if entry is None:
            raise self._input_error(
                "DOCKING_BATCH_LIGAND_NOT_FOUND",
                "The docking batch does not contain the requested ligand.",
                {"batch_id": batch_id, "ligand_id": ligand_id},
            )
        return entry

    @staticmethod
    def _batch_counts(entries: list[VinaBatchLigandResult]) -> dict[str, int]:
        succeeded = sum(
            entry.status is DockingJobStatus.COMPLETED for entry in entries
        )
        failed = sum(entry.status is DockingJobStatus.FAILED for entry in entries)
        canceled = sum(
            entry.status is DockingJobStatus.CANCELED for entry in entries
        )
        return {
            "completed_count": succeeded + failed + canceled,
            "succeeded_count": succeeded,
            "failed_count": failed,
            "canceled_count": canceled,
        }

    @staticmethod
    def _unavailable_batch_entry(
        *,
        ligand_id: str,
        source_index: int,
        name: str,
        message: str,
        code: str,
        completed_at: datetime,
        canonical_smiles: str | None = None,
        molecular_weight_g_mol: float | None = None,
        preparation_energy_kcal_mol: float | None = None,
    ) -> VinaBatchLigandResult:
        return VinaBatchLigandResult(
            ligand_id=ligand_id,
            source_index=source_index,
            name=name,
            canonical_smiles=canonical_smiles,
            molecular_weight_g_mol=molecular_weight_g_mol,
            preparation_energy_kcal_mol=preparation_energy_kcal_mol,
            status=DockingJobStatus.FAILED,
            phase=DockingJobPhase.COMPLETE,
            completed_at=completed_at,
            failure=DockingFailure(code=code, message=message),
        )

    @staticmethod
    def _batch_execution_parameters(
        request: VinaBatchDockingRequest, threads_per_ligand: int
    ) -> VinaDockingParameters:
        parameters = request.parameters
        return VinaDockingParameters(
            cpu_threads=threads_per_ligand,
            seed=parameters.seed,
            exhaustiveness=parameters.exhaustiveness,
            num_modes=parameters.num_modes,
            min_rmsd_angstrom=parameters.min_rmsd_angstrom,
            energy_range_kcal_mol=parameters.energy_range_kcal_mol,
            timeout_minutes=parameters.timeout_minutes_per_ligand,
        )

    def shutdown(self) -> None:
        with self._lock:
            for event in self._cancel_events.values():
                event.set()
        self._executor.shutdown(wait=True, cancel_futures=True)

    def _validate_inputs(
        self, request: VinaDockingRequest
    ) -> tuple[ReceptorOutputArtifact, Path, Path, BindingSiteRecord]:
        receptor_output, receptor_path, binding_site = self._validate_receptor_and_site(
            request.receptor_id, request.binding_site_id
        )

        ligand_preparation = self._ligand_store.load_pdbqt_record(
            request.ligand_id, request.ligand_preparation_id
        )
        if ligand_preparation.artifact.ligand_id != request.ligand_id:
            raise self._input_error(
                "DOCKING_LIGAND_PREPARATION_MISMATCH",
                "The ligand PDBQT preparation belongs to a different ligand.",
                {"ligand_id": request.ligand_id},
            )
        ligand_path = self._ligand_store.pdbqt_content_path(
            request.ligand_id, request.ligand_preparation_id
        )
        self._verify_hash(ligand_path, ligand_preparation.artifact.sha256, "ligand")
        return receptor_output, receptor_path, ligand_path, binding_site

    def _validate_receptor_and_site(
        self, receptor_id: str, binding_site_id: str
    ) -> tuple[ReceptorOutputArtifact, Path, BindingSiteRecord]:
        receptor = self._receptor_store.load_record(receptor_id)
        if receptor.status is not ReceptorPreparationStatus.DOCKING_READY:
            raise self._input_error(
                "DOCKING_RECEPTOR_NOT_READY",
                "Docking requires a receptor in docking-ready status.",
                {"receptor_id": receptor_id, "status": receptor.status.value},
            )
        receptor_output = next(
            (item for item in receptor.outputs if item.stage is ReceptorOutputStage.PDBQT),
            None,
        )
        if receptor_output is None:
            raise self._input_error(
                "DOCKING_RECEPTOR_PDBQT_MISSING",
                "The selected receptor has no preserved PDBQT output.",
                {"receptor_id": receptor_id},
            )
        receptor_path = self._receptor_store.content_path(
            receptor_id, receptor_output.artifact_id
        )
        self._verify_hash(receptor_path, receptor_output.sha256, "receptor")

        binding_site = self._binding_site_store.load_record(binding_site_id)
        if binding_site.receptor_id != receptor_id or binding_site.stale:
            raise self._input_error(
                "DOCKING_BINDING_SITE_INVALID",
                "The binding site is stale or belongs to a different receptor.",
                {
                    "binding_site_id": binding_site_id,
                    "binding_site_receptor_id": binding_site.receptor_id,
                    "requested_receptor_id": receptor_id,
                    "stale": binding_site.stale,
                },
            )
        return receptor_output, receptor_path, binding_site

    def _run(
        self,
        job_id: str,
        installation: VinaInstallation,
        receptor_path: Path,
        ligand_path: Path,
        output_path: Path,
        box: BindingBox,
        cancel_event: threading.Event,
    ) -> None:
        record = self._docking_store.load_record(job_id)
        if cancel_event.is_set():
            self._finish_canceled(record, None)
            self._forget(job_id)
            return
        started = datetime.now(UTC)
        running = record.model_copy(
            update={
                "status": DockingJobStatus.RUNNING,
                "phase": DockingJobPhase.DOCKING,
                "started_at": started,
            }
        )
        self._docking_store.update_record(running)
        try:
            execution = execute_vina(
                installation=installation,
                receptor_path=receptor_path,
                ligand_path=ligand_path,
                output_path=output_path,
                box=box,
                parameters=record.request.parameters,
                cancel_event=cancel_event,
            )
            evidence = DockingExecutionEvidence(
                command=execution.command,
                exit_code=execution.exit_code,
                stdout=execution.stdout,
                stderr=execution.stderr,
                timed_out=execution.timed_out,
                canceled=execution.canceled,
            )
            self._docking_store.write_text(job_id, "stdout.log", execution.stdout)
            self._docking_store.write_text(job_id, "stderr.log", execution.stderr)
            if execution.canceled:
                self._finish_canceled(running, evidence)
            elif execution.timed_out:
                self._finish_failed(
                    running,
                    evidence,
                    "VINA_TIMEOUT",
                    "AutoDock Vina exceeded the explicit execution time limit.",
                    {"timeout_minutes": record.request.parameters.timeout_minutes},
                )
            elif execution.exit_code != 0:
                self._finish_failed(
                    running,
                    evidence,
                    "VINA_EXECUTION_FAILED",
                    "AutoDock Vina did not complete the docking calculation.",
                    {"exit_code": execution.exit_code},
                )
            elif not output_path.is_file():
                self._finish_failed(
                    running,
                    evidence,
                    "VINA_OUTPUT_MISSING",
                    "AutoDock Vina completed without producing its pose file.",
                    {},
                )
            else:
                parsing = running.model_copy(
                    update={"phase": DockingJobPhase.PARSING_POSES, "execution": evidence}
                )
                self._docking_store.update_record(parsing)
                self._finish_completed(parsing, output_path.read_bytes(), evidence)
        except AnkoraDomainError as error:
            current = self._docking_store.load_record(job_id)
            self._finish_failed(
                current,
                current.execution,
                error.code,
                error.message,
                error.details,
            )
        except Exception as error:  # pragma: no cover - final worker containment
            current = self._docking_store.load_record(job_id)
            self._finish_failed(
                current,
                current.execution,
                "VINA_JOB_INTERNAL_ERROR",
                "Ankora could not complete the docking job.",
                {"reason": str(error)},
            )
        finally:
            self._forget(job_id)

    def _finish_completed(
        self,
        record: VinaDockingJobRecord,
        content: bytes,
        evidence: DockingExecutionEvidence,
    ) -> None:
        parsed = parse_vina_poses(content)
        poses: list[DockingPoseResult] = []
        for pose in parsed:
            artifact_id = f"{record.job_id}-pose-{pose.mode}"
            filename = f"pose_{pose.mode}.pdbqt"
            self._docking_store.write_bytes(record.job_id, filename, pose.content)
            artifact = DockingPoseArtifact(
                artifact_id=artifact_id,
                mode=pose.mode,
                filename=filename,
                format="pdbqt",
                sha256=sha256(pose.content).hexdigest(),
                size_bytes=len(pose.content),
                content_url=f"/docking/jobs/{record.job_id}/poses/{artifact_id}/content",
            )
            poses.append(
                DockingPoseResult(
                    mode=pose.mode,
                    affinity_kcal_mol=pose.affinity_kcal_mol,
                    rmsd_lower_bound_angstrom=pose.rmsd_lower_bound_angstrom,
                    rmsd_upper_bound_angstrom=pose.rmsd_upper_bound_angstrom,
                    artifact=artifact,
                )
            )
        completed_at = datetime.now(UTC)
        provenance = ProvenanceEvent(
            event_id=f"vina-docking-{record.job_id}",
            event_type="vina_docking_completed",
            timestamp=completed_at,
            input_artifacts=[
                record.receptor_output_artifact_id,
                record.request.binding_site_id,
                record.request.ligand_preparation_id,
            ],
            output_artifacts=[pose.artifact.artifact_id for pose in poses],
            tool=record.tool,
            parameters=record.request.parameters.model_dump(mode="json"),
            command=evidence.command,
        )
        completed = record.model_copy(
            update={
                "status": DockingJobStatus.COMPLETED,
                "phase": DockingJobPhase.COMPLETE,
                "completed_at": completed_at,
                "execution": evidence,
                "poses": poses,
                "provenance": provenance,
            }
        )
        with self._lock:
            self._docking_store.update_record(completed)

    def _finish_canceled(
        self,
        record: VinaDockingJobRecord,
        evidence: DockingExecutionEvidence | None,
    ) -> None:
        canceled = record.model_copy(
            update={
                "status": DockingJobStatus.CANCELED,
                "phase": DockingJobPhase.COMPLETE,
                "completed_at": datetime.now(UTC),
                "execution": evidence,
            }
        )
        with self._lock:
            self._docking_store.update_record(canceled)

    def _finish_failed(
        self,
        record: VinaDockingJobRecord,
        evidence: DockingExecutionEvidence | None,
        code: str,
        message: str,
        details: dict[str, object],
    ) -> None:
        failed = record.model_copy(
            update={
                "status": DockingJobStatus.FAILED,
                "phase": DockingJobPhase.COMPLETE,
                "completed_at": datetime.now(UTC),
                "execution": evidence,
                "failure": DockingFailure(code=code, message=message, details=details),
            }
        )
        with self._lock:
            self._docking_store.update_record(failed)

    def _forget(self, job_id: str) -> None:
        with self._lock:
            self._cancel_events.pop(job_id, None)
            self._active_batch_ids.discard(job_id)

    def _active_batch(self) -> VinaBatchDockingRecord | None:
        with self._lock:
            active_ids = tuple(self._active_batch_ids)
        for batch_id in active_ids:
            record = self._docking_store.load_batch_record(batch_id)
            if record.status not in {
                DockingJobStatus.CANCELED,
                DockingJobStatus.COMPLETED,
                DockingJobStatus.FAILED,
            }:
                return record
        return None

    @staticmethod
    def _sha256_file(path: Path) -> str:
        return sha256(path.read_bytes()).hexdigest()

    @classmethod
    def _verify_hash(cls, path: Path, expected: str, kind: str) -> None:
        actual = cls._sha256_file(path)
        if actual != expected:
            raise cls._input_error(
                "DOCKING_INPUT_HASH_MISMATCH",
                "A docking input no longer matches its immutable artifact record.",
                {"input": kind, "expected_sha256": expected, "actual_sha256": actual},
            )

    @staticmethod
    def _input_error(
        code: str, message: str, details: dict[str, object]
    ) -> AnkoraDomainError:
        return AnkoraDomainError(
            code=code,
            stage="docking_configuration",
            message=message,
            status_code=422,
            details=details,
        )
