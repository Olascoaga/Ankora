"""AutoDock4 CPU single-ligand docking against an immutable AutoGrid map set."""

import os
import shutil
import threading
import time
from collections import defaultdict
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

from ankora_backend.adapters.engines.autodock4_job import (
    ParsedAutoDock4Log,
    log_reports_success,
    parse_autodock4_log,
    render_autodock4_dpf,
)
from ankora_backend.adapters.engines.autodock4_runner import (
    DOCKING_LOG_FILENAME,
    DOCKING_PARAMETER_FILENAME,
    LIGAND_FILENAME,
    AutoDock4Installation,
    execute_autodock4_cancellable,
    probe_autodock4,
    validate_ligand_against_autodock4_limits,
)
from ankora_backend.domain.errors import AnkoraDomainError
from ankora_backend.persistence.autodock4_store import AutoDock4JobStore
from ankora_backend.persistence.autogrid_store import AutoGridMapStore
from ankora_backend.persistence.binding_site_store import BindingSiteArtifactStore
from ankora_backend.persistence.ligand_store import LigandArtifactStore
from ankora_backend.persistence.receptor_store import ReceptorArtifactStore
from ankora_backend.schemas.autodock4 import (
    AutoDock4BatchLigandResult,
    AutoDock4BatchProgress,
    AutoDock4BatchRecord,
    AutoDock4BatchRequest,
    AutoDock4CancelResponse,
    AutoDock4ClusterResult,
    AutoDock4DockingJobRecord,
    AutoDock4DockingRequest,
    AutoDock4ExecutionEvidence,
    AutoDock4Failure,
    AutoDock4JobPhase,
    AutoDock4JobStatus,
    AutoDock4PoseArtifact,
    AutoDock4RunResult,
)
from ankora_backend.schemas.autogrid import AutoGridMapKind, AutoGridMapSetRecord
from ankora_backend.schemas.binding_sites import BindingSiteRecord
from ankora_backend.schemas.ligand_library_preparation import LigandPreparationStatus
from ankora_backend.schemas.provenance import ProvenanceEvent
from ankora_backend.schemas.receptors import (
    ReceptorOutputArtifact,
)
from ankora_backend.schemas.warnings import StructuredWarning
from ankora_backend.schemas.work_recovery import WorkKind
from ankora_backend.services.autodock_inputs import (
    ordered_atom_types,
    resolve_receptor_and_site,
    resolve_selected_chemical_state,
    torsional_degrees_of_freedom,
    validate_map_set_applies,
)
from ankora_backend.services.resource_arbiter import (
    ResourceArbiter,
    ResourceLease,
    ResourceRequestCanceled,
    autodock4_claim,
)
from ankora_backend.services.work_leases import WorkLeaseManager

_STAGE = "autodock4_docking"


@dataclass(frozen=True, slots=True)
class _PreparedDocking:
    request: AutoDock4DockingRequest
    installation: AutoDock4Installation
    map_set: AutoGridMapSetRecord
    ligand_path: Path
    ligand_sha256: str
    ligand_atom_types: tuple[str, ...]
    atom_count: int
    torsional_degrees_of_freedom: int
    about: tuple[float, float, float]
    binding_site: BindingSiteRecord
    warnings: list[StructuredWarning]


class _JobCanceled(Exception):
    def __init__(self, *, execution: AutoDock4ExecutionEvidence) -> None:
        super().__init__("AutoDock4 docking was canceled")
        self.execution = execution


class AutoDock4DockingService:
    """Runs one AutoDock4 job at a time against an already-generated map set."""

    def __init__(
        self,
        *,
        job_store: AutoDock4JobStore,
        map_store: AutoGridMapStore,
        ligand_store: LigandArtifactStore,
        receptor_store: ReceptorArtifactStore,
        binding_site_store: BindingSiteArtifactStore,
        lease_manager: WorkLeaseManager | None = None,
        resource_arbiter: ResourceArbiter | None = None,
    ) -> None:
        self._job_store = job_store
        self._map_store = map_store
        self._ligand_store = ligand_store
        self._receptor_store = receptor_store
        self._binding_site_store = binding_site_store
        self._leases = lease_manager
        self._resources = resource_arbiter
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ankora-autodock4")
        self._cancel_events: dict[str, threading.Event] = {}
        self._lock = threading.RLock()
        self._batch_lock = threading.Lock()
        self._batch_write_lock = threading.RLock()
        self._active_batch_id: str | None = None

    @classmethod
    def from_environment(
        cls,
        *,
        lease_manager: WorkLeaseManager | None = None,
        resource_arbiter: ResourceArbiter | None = None,
    ) -> "AutoDock4DockingService":
        return cls(
            job_store=AutoDock4JobStore.from_environment(),
            map_store=AutoGridMapStore.from_environment(),
            ligand_store=LigandArtifactStore.from_environment(),
            receptor_store=ReceptorArtifactStore.from_environment(),
            binding_site_store=BindingSiteArtifactStore.from_environment(),
            lease_manager=lease_manager,
            resource_arbiter=resource_arbiter,
        )

    def start(self, request: AutoDock4DockingRequest) -> AutoDock4DockingJobRecord:
        if not request.acknowledge_inputs_and_scoring:
            raise self._input_error(
                "AUTODOCK4_CONFIRMATION_REQUIRED",
                (
                    "Confirm the exact receptor, map set, ligand, and search "
                    "settings before docking."
                ),
                {},
            )
        prepared = self._prepare(request)
        now = datetime.now(UTC)
        job_id = self._job_store.new_job_id()
        record = AutoDock4DockingJobRecord(
            job_id=job_id,
            status=AutoDock4JobStatus.QUEUED,
            phase=AutoDock4JobPhase.QUEUED,
            created_at=now,
            request=request,
            autodock4=prepared.installation.identity(),
            receptor_id=request.receptor_id,
            binding_site_id=request.binding_site_id,
            map_set_id=prepared.map_set.map_set_id,
            map_set_identity_key=prepared.map_set.identity_key,
            ligand_sha256=prepared.ligand_sha256,
            ligand_atom_types=list(prepared.ligand_atom_types),
            ligand_atom_count=prepared.atom_count,
            torsional_degrees_of_freedom=prepared.torsional_degrees_of_freedom,
            warnings=prepared.warnings,
        )
        self._job_store.create_job(record)
        cancel_event = threading.Event()
        with self._lock:
            self._cancel_events[job_id] = cancel_event
        self._executor.submit(self._run, job_id, prepared, cancel_event)
        return record

    def get(self, job_id: str) -> AutoDock4DockingJobRecord:
        return self._job_store.load_job(job_id)

    def pose_content_path(self, job_id: str, artifact_id: str) -> Path:
        return self._job_store.pose_content_path(job_id, artifact_id)

    def cancel(self, job_id: str) -> AutoDock4CancelResponse:
        with self._lock:
            record = self._job_store.load_job(job_id)
            if record.status in {
                AutoDock4JobStatus.CANCELED,
                AutoDock4JobStatus.COMPLETED,
                AutoDock4JobStatus.FAILED,
            }:
                return AutoDock4CancelResponse(job_id=job_id, status=record.status)
            cancel_event = self._cancel_events.get(job_id)
            if cancel_event is None:
                raise AnkoraDomainError(
                    code="AUTODOCK4_JOB_NOT_ACTIVE",
                    stage=_STAGE,
                    message="This docking job is not active in the current Ankora session.",
                    status_code=409,
                    details={"job_id": job_id, "status": record.status.value},
                )
            cancel_event.set()
            self._job_store.update_job(
                record.model_copy(update={"status": AutoDock4JobStatus.CANCEL_REQUESTED})
            )
        return AutoDock4CancelResponse(job_id=job_id, status=AutoDock4JobStatus.CANCEL_REQUESTED)

    def shutdown(self) -> None:
        with self._lock:
            for event in self._cancel_events.values():
                event.set()
        self._executor.shutdown(wait=True, cancel_futures=True)

    def has_active_work(self) -> bool:
        with self._lock:
            return bool(self._cancel_events)

    def _run(
        self,
        job_id: str,
        prepared: _PreparedDocking,
        cancel_event: threading.Event,
    ) -> None:
        resource_lease: ResourceLease | None = None
        if self._leases is not None:
            self._leases.acquire(WorkKind.AUTODOCK4_JOB, job_id)
        record = self._job_store.load_job(job_id)
        if self._resources is not None:
            try:
                resource_lease = self._resources.acquire(
                    autodock4_claim(job_id, concurrent_processes=1, ligand_count=1),
                    cancel_event=cancel_event,
                )
            except ResourceRequestCanceled:
                self._finish(record, status=AutoDock4JobStatus.CANCELED)
                if self._leases is not None:
                    self._leases.release(WorkKind.AUTODOCK4_JOB, job_id)
                self._forget(job_id)
                return
            except AnkoraDomainError as error:
                self._finish(
                    record,
                    status=AutoDock4JobStatus.FAILED,
                    failure=AutoDock4Failure(
                        code=error.code,
                        message=error.message,
                        details=dict(error.details),
                    ),
                )
                if self._leases is not None:
                    self._leases.release(WorkKind.AUTODOCK4_JOB, job_id)
                self._forget(job_id)
                return
        if cancel_event.is_set():
            self._finish(record, status=AutoDock4JobStatus.CANCELED)
            if resource_lease is not None:
                resource_lease.release()
            if self._leases is not None:
                self._leases.release(WorkKind.AUTODOCK4_JOB, job_id)
            self._forget(job_id)
            return
        running = record.model_copy(
            update={
                "status": AutoDock4JobStatus.RUNNING,
                "phase": AutoDock4JobPhase.DOCKING,
                "started_at": datetime.now(UTC),
            }
        )
        self._job_store.update_job(running)
        try:
            self._execute(running, prepared, cancel_event)
        except _JobCanceled as canceled:
            self._finish(
                running,
                status=AutoDock4JobStatus.CANCELED,
                execution=canceled.execution,
            )
        except AnkoraDomainError as error:
            self._finish(
                running,
                status=AutoDock4JobStatus.FAILED,
                failure=AutoDock4Failure(
                    code=error.code, message=error.message, details=dict(error.details)
                ),
            )
        finally:
            if resource_lease is not None:
                resource_lease.release()
            if self._leases is not None:
                self._leases.release(WorkKind.AUTODOCK4_JOB, job_id)
            self._forget(job_id)

    def _execute(
        self,
        record: AutoDock4DockingJobRecord,
        prepared: _PreparedDocking,
        cancel_event: threading.Event,
    ) -> None:
        job_id = record.job_id
        job_directory = self._job_store.job_directory(job_id)
        self._require_ascii_job_directory(job_directory)
        self._stage_inputs(job_directory, prepared)

        dpf = render_autodock4_dpf(
            ligand_filename=LIGAND_FILENAME,
            map_prefix=_map_prefix(prepared.map_set),
            ligand_atom_types=prepared.ligand_atom_types,
            about=prepared.about,
            torsional_degrees_of_freedom=prepared.torsional_degrees_of_freedom,
            seed=(
                prepared.request.parameters.seed_1,
                prepared.request.parameters.seed_2,
            ),
            ga_runs=prepared.request.parameters.ga_runs,
            ga_population_size=prepared.request.parameters.ga_population_size,
            ga_energy_evaluations=prepared.request.parameters.ga_energy_evaluations,
            ga_generations=prepared.request.parameters.ga_generations,
            cluster_rmsd_tolerance_angstrom=(
                prepared.request.parameters.cluster_rmsd_tolerance_angstrom
            ),
        )
        (job_directory / DOCKING_PARAMETER_FILENAME).write_text(dpf, encoding="ascii", newline="\n")

        started = time.monotonic()
        execution = execute_autodock4_cancellable(
            installation=prepared.installation,
            job_directory=job_directory,
            timeout_seconds=prepared.request.parameters.timeout_minutes * 60,
            cancel_event=cancel_event,
        )
        duration = time.monotonic() - started
        log_path = job_directory / DOCKING_LOG_FILENAME
        document = (
            log_path.read_text(encoding="utf-8", errors="replace") if log_path.is_file() else ""
        )
        successful = log_reports_success(document)
        evidence = AutoDock4ExecutionEvidence(
            command=execution.command,
            exit_code=execution.exit_code,
            stdout=execution.stdout,
            stderr=execution.stderr,
            duration_seconds=duration,
            successful_completion_logged=successful,
            canceled=execution.canceled,
            timed_out=execution.timed_out,
        )
        self._job_store.update_job(
            record.model_copy(
                update={
                    "command": execution.command,
                    "dpf_sha256": sha256(dpf.encode("ascii")).hexdigest(),
                    "execution": evidence,
                }
            )
        )
        if execution.canceled:
            raise _JobCanceled(execution=evidence)
        if execution.timed_out:
            raise self._input_error(
                "AUTODOCK4_EXECUTION_TIMED_OUT",
                "AutoDock4 exceeded the configured timeout; its raw log is preserved.",
                {
                    "timeout_minutes": prepared.request.parameters.timeout_minutes,
                    **evidence.model_dump(mode="json"),
                },
            )
        if execution.exit_code != 0 or not successful:
            raise self._input_error(
                "AUTODOCK4_EXECUTION_FAILED",
                "AutoDock4 did not complete successfully; its raw log is preserved.",
                evidence.model_dump(mode="json"),
            )

        self._job_store.update_job(
            record.model_copy(
                update={
                    "phase": AutoDock4JobPhase.PARSING_RESULTS,
                    "command": execution.command,
                    "dpf_sha256": sha256(dpf.encode("ascii")).hexdigest(),
                    "execution": evidence,
                }
            )
        )
        parsed = parse_autodock4_log(document)
        runs, clusters = self._persist_results(job_id, parsed)
        completed_at = datetime.now(UTC)
        self._job_store.update_job(
            record.model_copy(
                update={
                    "status": AutoDock4JobStatus.COMPLETED,
                    "phase": AutoDock4JobPhase.COMPLETE,
                    "completed_at": completed_at,
                    "command": execution.command,
                    "dpf_sha256": sha256(dpf.encode("ascii")).hexdigest(),
                    "execution": evidence,
                    "runs": runs,
                    "clusters": clusters,
                    "provenance": ProvenanceEvent(
                        event_id=f"autodock4-docking-{job_id}",
                        event_type="autodock4_docking_completed",
                        timestamp=completed_at,
                        input_artifacts=[
                            prepared.map_set.map_set_id,
                            prepared.binding_site.binding_site_id,
                            prepared.request.ligand_preparation_id,
                        ],
                        output_artifacts=[item.artifact.artifact_id for item in runs],
                        tool=prepared.installation.identity().tool,
                        parameters={
                            **prepared.request.parameters.model_dump(mode="json"),
                            "map_set_identity_key": prepared.map_set.identity_key,
                            "ligand_atom_types": list(prepared.ligand_atom_types),
                            "autodock4_sha256": prepared.installation.sha256,
                        },
                        command=execution.command,
                    ),
                }
            )
        )

    def _persist_results(
        self, job_id: str, parsed: ParsedAutoDock4Log
    ) -> tuple[list[AutoDock4RunResult], list[AutoDock4ClusterResult]]:
        ranking = {row.run: row for row in parsed.ranking}
        runs: list[AutoDock4RunResult] = []
        for pose in sorted(parsed.poses, key=lambda item: item.run):
            row = ranking[pose.run]
            artifact_id = str(uuid4())
            filename = f"run_{pose.run}.pdbqt"
            self._job_store.write_pose(job_id, filename, pose.content)
            runs.append(
                AutoDock4RunResult(
                    run=pose.run,
                    cluster_rank=row.cluster_rank,
                    sub_rank=row.sub_rank,
                    binding_energy_kcal_mol=row.binding_energy_kcal_mol,
                    cluster_rmsd_angstrom=row.cluster_rmsd_angstrom,
                    reference_rmsd_angstrom=row.reference_rmsd_angstrom,
                    artifact=AutoDock4PoseArtifact(
                        artifact_id=artifact_id,
                        run=pose.run,
                        filename=filename,
                        format="pdbqt",
                        sha256=sha256(pose.content).hexdigest(),
                        size_bytes=len(pose.content),
                        content_url=(
                            f"/docking/autodock4/jobs/{job_id}/poses/{artifact_id}/content"
                        ),
                    ),
                )
            )
        members: dict[int, list[int]] = defaultdict(list)
        for row in sorted(parsed.ranking, key=lambda item: (item.cluster_rank, item.sub_rank)):
            members[row.cluster_rank].append(row.run)
        clusters = [
            AutoDock4ClusterResult(
                cluster_rank=cluster.cluster_rank,
                lowest_binding_energy_kcal_mol=cluster.lowest_binding_energy_kcal_mol,
                mean_binding_energy_kcal_mol=cluster.mean_binding_energy_kcal_mol,
                run_count=cluster.run_count,
                representative_run=cluster.representative_run,
                runs=members[cluster.cluster_rank],
            )
            for cluster in parsed.clusters
        ]
        return runs, clusters

    def _stage_inputs(self, job_directory: Path, prepared: _PreparedDocking) -> None:
        self._stage_directory(job_directory, prepared.map_set, prepared.ligand_path)

    def _stage_directory(
        self, job_directory: Path, map_set: AutoGridMapSetRecord, ligand_path: Path
    ) -> None:
        """Place the ligand and the map set beside the job's relative filenames.

        Maps are hard-linked rather than copied: a map set is tens to hundreds
        of megabytes and AutoDock only ever reads it, so a link costs no disk
        and cannot alter the immutable original. Copying is the fallback when a
        link is impossible, such as across volumes.
        """
        shutil.copyfile(ligand_path, job_directory / LIGAND_FILENAME)
        source_directory = self._map_store.map_set_directory(map_set.map_set_id)
        for artifact in map_set.artifacts:
            if artifact.kind in {
                AutoGridMapKind.GRID_PARAMETER_FILE,
                AutoGridMapKind.GRID_LOG,
                AutoGridMapKind.RECEPTOR,
            }:
                continue
            source = source_directory / artifact.filename
            destination = job_directory / artifact.filename
            try:
                os.link(source, destination)
            except OSError:
                shutil.copyfile(source, destination)

    def _prepare(self, request: AutoDock4DockingRequest) -> _PreparedDocking:
        installation = probe_autodock4()
        map_set = self._map_store.load_record(request.map_set_id)
        receptor_output, binding_site = self._validate_receptor_and_site(request)
        warnings = self._validate_map_set_applies(
            map_set, receptor_output=receptor_output, binding_site=binding_site
        )

        pdbqt = self._ligand_store.load_pdbqt_record(
            request.ligand_id, request.ligand_preparation_id
        )
        ligand_path = self._ligand_store.pdbqt_content_path(
            request.ligand_id, request.ligand_preparation_id
        )
        self._verify_hash(ligand_path, pdbqt.artifact.sha256)
        document = ligand_path.read_text(encoding="utf-8", errors="replace")
        atom_types = _ordered_atom_types(document)
        atom_lines = [
            line for line in document.splitlines() if line.startswith(("ATOM  ", "HETATM"))
        ]

        available = {
            artifact.atom_type
            for artifact in map_set.artifacts
            if artifact.kind is AutoGridMapKind.AFFINITY
        }
        missing = sorted(set(atom_types) - available)
        if missing:
            raise self._input_error(
                "AUTODOCK4_LIGAND_TYPES_NOT_IN_MAP_SET",
                (
                    "This ligand uses atom types the selected map set does not "
                    "cover. Generate a map set that includes them."
                ),
                {
                    "missing_atom_types": missing,
                    "map_set_atom_types": sorted(value for value in available if value is not None),
                },
            )
        validate_ligand_against_autodock4_limits(
            installation,
            atom_count=len(atom_lines),
            torsional_degrees_of_freedom=_torsdof(document),
            map_count=len(available) + 2,
        )
        return _PreparedDocking(
            request=request,
            installation=installation,
            map_set=map_set,
            ligand_path=ligand_path,
            ligand_sha256=pdbqt.artifact.sha256,
            ligand_atom_types=atom_types,
            atom_count=len(atom_lines),
            torsional_degrees_of_freedom=_torsdof(document),
            about=_centroid(atom_lines),
            binding_site=binding_site,
            warnings=warnings,
        )

    # --- library campaigns ---

    def start_batch(self, request: AutoDock4BatchRequest) -> AutoDock4BatchRecord:
        """Dock a whole applied selection against one shared map set.

        Every molecule runs its own complete AutoDock4 process, so the clusters
        reported are the ones AutoDock produced, not anything Ankora recomputed.
        Because the 4.2.6 build is single-threaded, this pool is the entire CPU
        budget and there is no inner thread count to coordinate with.
        """
        if not request.acknowledge_inputs_and_scoring:
            raise self._input_error(
                "AUTODOCK4_CONFIRMATION_REQUIRED",
                (
                    "Confirm the exact receptor, map set, selection, and search "
                    "settings before docking."
                ),
                {},
            )
        with self._batch_lock:
            if self._active_batch_id is not None:
                raise AnkoraDomainError(
                    code="AUTODOCK4_BATCH_ALREADY_ACTIVE",
                    stage=_STAGE,
                    message="Another AutoDock4 campaign is already running.",
                    status_code=409,
                    details={"active_batch_id": self._active_batch_id},
                )
            record = self._create_batch(request)
            self._active_batch_id = record.batch_id
        cancel_event = threading.Event()
        with self._lock:
            self._cancel_events[record.batch_id] = cancel_event
        self._executor.submit(self._run_batch, record.batch_id, cancel_event)
        return record

    def latest_batch(
        self, *, receptor_id: str, binding_site_id: str, filter_run_id: str
    ) -> AutoDock4BatchRecord:
        """Reconnect to a persisted campaign for these exact inputs.

        Prefers one that actually produced results, so a later empty or failed
        attempt does not hide a usable campaign.
        """
        matching = [
            record
            for record in self._job_store.list_batches()
            if record.receptor_id == receptor_id
            and record.binding_site_id == binding_site_id
            and record.request.filter_run_id == filter_run_id
        ]
        if not matching:
            raise AnkoraDomainError(
                code="AUTODOCK4_BATCH_HISTORY_EMPTY",
                stage=_STAGE,
                message="No AutoDock4 campaign is available for these exact inputs.",
                status_code=404,
                details={
                    "receptor_id": receptor_id,
                    "binding_site_id": binding_site_id,
                    "filter_run_id": filter_run_id,
                },
            )
        with self._batch_lock:
            active_id = self._active_batch_id
        active = [record for record in matching if record.batch_id == active_id]
        successful = [record for record in matching if record.succeeded_count > 0]
        candidates = active or successful or matching
        return max(candidates, key=lambda record: (record.created_at, record.batch_id))

    def get_batch(self, batch_id: str) -> AutoDock4BatchRecord:
        return self._job_store.load_batch(batch_id)

    def get_batch_progress(self, batch_id: str, after_revision: int) -> AutoDock4BatchProgress:
        summary = self._job_store.load_batch_summary(batch_id)
        payload = {
            key: value
            for key, value in summary.items()
            if key in AutoDock4BatchProgress.model_fields
        }
        payload["running_ligand_ids"] = self._job_store.batch_ligand_ids_with_status(
            batch_id, AutoDock4JobStatus.RUNNING.value
        )
        return AutoDock4BatchProgress.model_validate(payload)

    def cancel_batch(self, batch_id: str) -> AutoDock4CancelResponse:
        with self._lock:
            record = self._job_store.load_batch_overview(batch_id)
            if record.status in {
                AutoDock4JobStatus.CANCELED,
                AutoDock4JobStatus.COMPLETED,
                AutoDock4JobStatus.FAILED,
            }:
                return AutoDock4CancelResponse(job_id=batch_id, status=record.status)
            cancel_event = self._cancel_events.get(batch_id)
            if cancel_event is None:
                raise AnkoraDomainError(
                    code="AUTODOCK4_JOB_NOT_ACTIVE",
                    stage=_STAGE,
                    message="This campaign is not active in the current Ankora session.",
                    status_code=409,
                    details={"batch_id": batch_id, "status": record.status.value},
                )
            cancel_event.set()
            self._job_store.update_batch(
                record.model_copy(
                    update={
                        "status": AutoDock4JobStatus.CANCEL_REQUESTED,
                        "revision": record.revision + 1,
                    }
                ),
                changed_entries=[],
            )
        return AutoDock4CancelResponse(job_id=batch_id, status=AutoDock4JobStatus.CANCEL_REQUESTED)

    def batch_pose_content_path(self, batch_id: str, ligand_id: str, artifact_id: str) -> Path:
        return self._job_store.batch_pose_content_path(batch_id, ligand_id, artifact_id)

    def _create_batch(self, request: AutoDock4BatchRequest) -> AutoDock4BatchRecord:
        installation = probe_autodock4()
        map_set = self._map_store.load_record(request.map_set_id)
        receptor_output, binding_site = self._validate_receptor_and_site(request)
        warnings = self._validate_map_set_applies(
            map_set, receptor_output=receptor_output, binding_site=binding_site
        )
        filter_run = self._ligand_store.load_filter_run(request.library_id, request.filter_run_id)
        if not filter_run.selected_ligand_ids:
            raise self._input_error(
                "AUTODOCK4_SELECTION_EMPTY",
                "The applied ligand selection contains no molecules to dock.",
                {"filter_run_id": request.filter_run_id},
            )
        library = self._ligand_store.load_library_record(request.library_id)
        preparation = self._ligand_store.load_preparation_status(request.library_id)
        indexed = {
            entry.ligand.artifact.ligand_id: (entry.record_index, entry.ligand)
            for entry in library.entries
            if entry.ligand is not None
        }
        covered = {
            artifact.atom_type
            for artifact in map_set.artifacts
            if artifact.kind is AutoGridMapKind.AFFINITY
        }
        now = datetime.now(UTC)
        entries: list[AutoDock4BatchLigandResult] = []
        for ligand_id in filter_run.selected_ligand_ids:
            source = indexed.get(ligand_id)
            if source is None:
                entries.append(
                    self._unavailable_entry(
                        ligand_id,
                        len(entries),
                        "Unavailable library molecule",
                        "The selected molecule is absent from its library record.",
                        "AUTODOCK4_LIBRARY_LIGAND_MISSING",
                        now,
                    )
                )
                continue
            source_index, ligand = source
            try:
                state = resolve_selected_chemical_state(
                    ligand_id=ligand_id,
                    ligand=ligand,
                    filter_run=filter_run,
                    ligand_store=self._ligand_store,
                    stage=_STAGE,
                    code_prefix="AUTODOCK4",
                )
            except AnkoraDomainError as error:
                entries.append(
                    self._unavailable_entry(
                        ligand_id,
                        source_index,
                        ligand.inspection.name,
                        error.message,
                        error.code,
                        now,
                        parent_compound_id=ligand_id,
                    )
                )
                continue
            status = preparation.entries.get(ligand_id)
            if (
                status is None
                or status.status is not LigandPreparationStatus.PREPARED
                or status.pdbqt_preparation_id is None
            ):
                entries.append(
                    self._unavailable_entry(
                        ligand_id,
                        source_index,
                        state.inspection.name,
                        "This molecule has no completed Meeko PDBQT preparation.",
                        "AUTODOCK4_LIGAND_NOT_PREPARED",
                        now,
                        canonical_smiles=state.inspection.canonical_smiles,
                        molecular_weight_g_mol=state.inspection.molecular_weight_g_mol,
                        parent_compound_id=state.parent_compound_id,
                        chemical_state_id=state.state_id,
                        chemical_state_formal_charge=state.inspection.formal_charge,
                    )
                )
                continue
            if status.chemical_state_id != state.state_id:
                entries.append(
                    self._unavailable_entry(
                        ligand_id,
                        source_index,
                        state.inspection.name,
                        (
                            "The prepared PDBQT belongs to a different or unrecorded "
                            "chemical state than the applied selection manifest."
                        ),
                        "AUTODOCK4_PREPARATION_STATE_MISMATCH",
                        now,
                        canonical_smiles=state.inspection.canonical_smiles,
                        molecular_weight_g_mol=(state.inspection.molecular_weight_g_mol),
                        parent_compound_id=state.parent_compound_id,
                        chemical_state_id=state.state_id,
                        chemical_state_formal_charge=state.inspection.formal_charge,
                    )
                )
                continue
            try:
                pdbqt = self._ligand_store.load_pdbqt_record(ligand_id, status.pdbqt_preparation_id)
                path = self._ligand_store.pdbqt_content_path(ligand_id, status.pdbqt_preparation_id)
                self._verify_hash(path, pdbqt.artifact.sha256)
                document = path.read_text(encoding="utf-8", errors="replace")
                atom_types = _ordered_atom_types(document)
            except (AnkoraDomainError, ValueError) as error:
                entries.append(
                    self._unavailable_entry(
                        ligand_id,
                        source_index,
                        state.inspection.name,
                        str(getattr(error, "message", error)),
                        "AUTODOCK4_LIGAND_UNAVAILABLE",
                        now,
                        canonical_smiles=state.inspection.canonical_smiles,
                        molecular_weight_g_mol=state.inspection.molecular_weight_g_mol,
                        parent_compound_id=state.parent_compound_id,
                        chemical_state_id=state.state_id,
                        chemical_state_formal_charge=state.inspection.formal_charge,
                    )
                )
                continue
            missing = sorted(set(atom_types) - covered)
            if missing:
                entries.append(
                    self._unavailable_entry(
                        ligand_id,
                        source_index,
                        state.inspection.name,
                        (
                            "This molecule uses atom types the selected map set "
                            f"does not cover: {', '.join(missing)}."
                        ),
                        "AUTODOCK4_LIGAND_TYPES_NOT_IN_MAP_SET",
                        now,
                        canonical_smiles=state.inspection.canonical_smiles,
                        molecular_weight_g_mol=state.inspection.molecular_weight_g_mol,
                        ligand_preparation_id=status.pdbqt_preparation_id,
                        ligand_sha256=pdbqt.artifact.sha256,
                        ligand_atom_types=list(atom_types),
                        parent_compound_id=state.parent_compound_id,
                        chemical_state_id=state.state_id,
                        chemical_state_formal_charge=state.inspection.formal_charge,
                    )
                )
                continue
            entries.append(
                AutoDock4BatchLigandResult(
                    ligand_id=ligand_id,
                    parent_compound_id=state.parent_compound_id,
                    chemical_state_id=state.state_id,
                    chemical_state_formal_charge=state.inspection.formal_charge,
                    source_index=source_index,
                    name=state.inspection.name,
                    canonical_smiles=state.inspection.canonical_smiles,
                    molecular_weight_g_mol=state.inspection.molecular_weight_g_mol,
                    ligand_preparation_id=status.pdbqt_preparation_id,
                    ligand_sha256=pdbqt.artifact.sha256,
                    ligand_atom_types=list(atom_types),
                    status=AutoDock4JobStatus.QUEUED,
                    phase=AutoDock4JobPhase.QUEUED,
                )
            )
        runnable = sum(1 for entry in entries if entry.status is AutoDock4JobStatus.QUEUED)
        worker_count = max(1, min(request.parameters.parallel_ligands, runnable or 1))
        record = AutoDock4BatchRecord(
            batch_id=self._job_store.new_batch_id(),
            status=AutoDock4JobStatus.QUEUED,
            phase=AutoDock4JobPhase.QUEUED,
            created_at=now,
            request=request,
            autodock4=installation.identity(),
            receptor_id=request.receptor_id,
            binding_site_id=request.binding_site_id,
            map_set_id=map_set.map_set_id,
            map_set_identity_key=map_set.identity_key,
            selection_manifest_sha256=filter_run.artifact.sha256,
            selected_count=len(entries),
            worker_count=worker_count,
            failed_count=sum(1 for entry in entries if entry.status is AutoDock4JobStatus.FAILED),
            completed_count=sum(
                1 for entry in entries if entry.status is AutoDock4JobStatus.FAILED
            ),
            entries=entries,
            warnings=warnings,
        )
        self._job_store.create_batch(record)
        return record

    @staticmethod
    def _unavailable_entry(
        ligand_id: str,
        source_index: int,
        name: str,
        message: str,
        code: str,
        completed_at: datetime,
        *,
        canonical_smiles: str | None = None,
        molecular_weight_g_mol: float | None = None,
        ligand_preparation_id: str | None = None,
        ligand_sha256: str | None = None,
        ligand_atom_types: list[str] | None = None,
        parent_compound_id: str | None = None,
        chemical_state_id: str | None = None,
        chemical_state_formal_charge: int | None = None,
    ) -> AutoDock4BatchLigandResult:
        """An unusable molecule stays a visible row rather than disappearing."""
        return AutoDock4BatchLigandResult(
            ligand_id=ligand_id,
            parent_compound_id=parent_compound_id,
            chemical_state_id=chemical_state_id,
            chemical_state_formal_charge=chemical_state_formal_charge,
            source_index=source_index,
            name=name,
            canonical_smiles=canonical_smiles,
            molecular_weight_g_mol=molecular_weight_g_mol,
            ligand_preparation_id=ligand_preparation_id,
            ligand_sha256=ligand_sha256,
            ligand_atom_types=ligand_atom_types or [],
            status=AutoDock4JobStatus.FAILED,
            phase=AutoDock4JobPhase.COMPLETE,
            completed_at=completed_at,
            failure=AutoDock4Failure(code=code, message=message),
        )

    def _run_batch(self, batch_id: str, cancel_event: threading.Event) -> None:
        resource_lease: ResourceLease | None = None
        if self._leases is not None:
            self._leases.acquire(WorkKind.AUTODOCK4_BATCH, batch_id)
        try:
            record = self._job_store.load_batch(batch_id)
            if self._resources is not None:
                resource_lease = self._resources.acquire(
                    autodock4_claim(
                        batch_id,
                        concurrent_processes=record.worker_count,
                        ligand_count=sum(
                            entry.status is AutoDock4JobStatus.QUEUED for entry in record.entries
                        ),
                    ),
                    cancel_event=cancel_event,
                )
            self._update_batch(
                batch_id,
                lambda current: current.model_copy(
                    update={
                        "status": AutoDock4JobStatus.RUNNING,
                        "phase": AutoDock4JobPhase.DOCKING,
                        "started_at": datetime.now(UTC),
                    }
                ),
            )
            pending = [
                entry for entry in record.entries if entry.status is AutoDock4JobStatus.QUEUED
            ]
            if pending:
                with ThreadPoolExecutor(
                    max_workers=record.worker_count,
                    thread_name_prefix="ankora-autodock4-batch",
                ) as pool:
                    list(
                        pool.map(
                            lambda entry: self._run_batch_entry(
                                batch_id, entry.ligand_id, cancel_event
                            ),
                            pending,
                        )
                    )
            self._update_batch(
                batch_id,
                lambda current: current.model_copy(
                    update={
                        "status": (
                            AutoDock4JobStatus.CANCELED
                            if cancel_event.is_set()
                            else AutoDock4JobStatus.COMPLETED
                        ),
                        "phase": AutoDock4JobPhase.COMPLETE,
                        "completed_at": datetime.now(UTC),
                    }
                ),
            )
        except ResourceRequestCanceled:
            self._update_batch(
                batch_id,
                lambda current: current.model_copy(
                    update={
                        "status": AutoDock4JobStatus.CANCELED,
                        "phase": AutoDock4JobPhase.COMPLETE,
                        "completed_at": datetime.now(UTC),
                    }
                ),
            )
        except AnkoraDomainError as error:
            failure = AutoDock4Failure(
                code=error.code,
                message=error.message,
                details=dict(error.details),
            )
            self._update_batch(
                batch_id,
                lambda current: current.model_copy(
                    update={
                        "status": AutoDock4JobStatus.FAILED,
                        "phase": AutoDock4JobPhase.COMPLETE,
                        "completed_at": datetime.now(UTC),
                        "failure": failure,
                    }
                ),
            )
        finally:
            if resource_lease is not None:
                resource_lease.release()
            if self._leases is not None:
                self._leases.release(WorkKind.AUTODOCK4_BATCH, batch_id)
            self._forget(batch_id)
            with self._batch_lock:
                self._active_batch_id = None

    def _run_batch_entry(
        self, batch_id: str, ligand_id: str, cancel_event: threading.Event
    ) -> None:
        """One molecule's complete AutoDock4 job. A failure stays on this row."""
        if cancel_event.is_set():
            self._finish_entry(batch_id, ligand_id, status=AutoDock4JobStatus.CANCELED)
            return
        batch = self._job_store.load_batch_overview(batch_id)
        entry = self._job_store.load_batch_entry(batch_id, ligand_id)
        if entry is None:
            raise self._input_error(
                "AUTODOCK4_BATCH_LIGAND_NOT_FOUND",
                "The AutoDock4 campaign no longer contains its selected ligand.",
                {"batch_id": batch_id, "ligand_id": ligand_id},
            )
        if entry.ligand_preparation_id is None:
            # A queued entry always carries one; a bare assert would vanish
            # under `python -O` and fail far less clearly downstream.
            self._finish_entry(
                batch_id,
                ligand_id,
                status=AutoDock4JobStatus.FAILED,
                failure=AutoDock4Failure(
                    code="AUTODOCK4_LIGAND_NOT_PREPARED",
                    message="This molecule has no recorded PDBQT preparation.",
                ),
            )
            return
        self._update_entry(
            batch_id,
            ligand_id,
            lambda current: current.model_copy(
                update={
                    "status": AutoDock4JobStatus.RUNNING,
                    "phase": AutoDock4JobPhase.DOCKING,
                    "started_at": datetime.now(UTC),
                }
            ),
        )
        try:
            map_set = self._map_store.load_record(batch.map_set_id)
            ligand_path = self._ligand_store.pdbqt_content_path(
                ligand_id, entry.ligand_preparation_id
            )
            directory = self._job_store.batch_ligand_directory(batch_id, ligand_id)
            self._require_ascii_job_directory(directory)
            document = ligand_path.read_text(encoding="utf-8", errors="replace")
            atom_lines = [
                line for line in document.splitlines() if line.startswith(("ATOM  ", "HETATM"))
            ]
            self._stage_directory(directory, map_set, ligand_path)
            dpf = render_autodock4_dpf(
                ligand_filename=LIGAND_FILENAME,
                map_prefix=_map_prefix(map_set),
                ligand_atom_types=_ordered_atom_types(document),
                about=_centroid(atom_lines),
                torsional_degrees_of_freedom=_torsdof(document),
                seed=(
                    batch.request.parameters.seed_1,
                    batch.request.parameters.seed_2,
                ),
                ga_runs=batch.request.parameters.ga_runs,
                ga_population_size=batch.request.parameters.ga_population_size,
                ga_energy_evaluations=batch.request.parameters.ga_energy_evaluations,
                ga_generations=batch.request.parameters.ga_generations,
                cluster_rmsd_tolerance_angstrom=(
                    batch.request.parameters.cluster_rmsd_tolerance_angstrom
                ),
            )
            (directory / DOCKING_PARAMETER_FILENAME).write_text(dpf, encoding="ascii", newline="\n")
            started = time.monotonic()
            execution = execute_autodock4_cancellable(
                installation=probe_autodock4(),
                job_directory=directory,
                timeout_seconds=batch.request.parameters.timeout_minutes * 60,
                cancel_event=cancel_event,
            )
            log_path = directory / DOCKING_LOG_FILENAME
            log = (
                log_path.read_text(encoding="utf-8", errors="replace") if log_path.is_file() else ""
            )
            evidence = AutoDock4ExecutionEvidence(
                command=execution.command,
                exit_code=execution.exit_code,
                stdout=execution.stdout,
                stderr=execution.stderr,
                duration_seconds=time.monotonic() - started,
                successful_completion_logged=log_reports_success(log),
                canceled=execution.canceled,
                timed_out=execution.timed_out,
            )
            if execution.canceled:
                self._finish_entry(
                    batch_id,
                    ligand_id,
                    status=AutoDock4JobStatus.CANCELED,
                    execution=evidence,
                    command=execution.command,
                )
                return
            if execution.exit_code != 0 or not evidence.successful_completion_logged:
                self._finish_entry(
                    batch_id,
                    ligand_id,
                    status=AutoDock4JobStatus.FAILED,
                    execution=evidence,
                    command=execution.command,
                    failure=AutoDock4Failure(
                        code=(
                            "AUTODOCK4_EXECUTION_TIMED_OUT"
                            if execution.timed_out
                            else "AUTODOCK4_EXECUTION_FAILED"
                        ),
                        message=(
                            "AutoDock4 did not complete successfully for this "
                            "molecule; its raw log is preserved."
                        ),
                        details={"exit_code": execution.exit_code},
                    ),
                )
                return
            parsed = parse_autodock4_log(log)
            runs, clusters = self._persist_batch_results(batch_id, ligand_id, parsed)
            completed_at = datetime.now(UTC)
            self._finish_entry(
                batch_id,
                ligand_id,
                status=AutoDock4JobStatus.COMPLETED,
                execution=evidence,
                command=execution.command,
                dpf_sha256=sha256(dpf.encode("ascii")).hexdigest(),
                runs=runs,
                clusters=clusters,
                provenance=ProvenanceEvent(
                    event_id=f"autodock4-batch-{batch_id}-{ligand_id}",
                    event_type="autodock4_library_ligand_completed",
                    timestamp=completed_at,
                    input_artifacts=[
                        batch.map_set_id,
                        batch.binding_site_id,
                        entry.ligand_preparation_id,
                    ],
                    output_artifacts=[item.artifact.artifact_id for item in runs],
                    tool=batch.autodock4.tool,
                    parameters=batch.request.parameters.model_dump(mode="json"),
                    command=execution.command,
                ),
            )
        except AnkoraDomainError as error:
            self._finish_entry(
                batch_id,
                ligand_id,
                status=AutoDock4JobStatus.FAILED,
                failure=AutoDock4Failure(
                    code=error.code, message=error.message, details=dict(error.details)
                ),
            )

    def _persist_batch_results(
        self, batch_id: str, ligand_id: str, parsed: ParsedAutoDock4Log
    ) -> tuple[list[AutoDock4RunResult], list[AutoDock4ClusterResult]]:
        ranking = {row.run: row for row in parsed.ranking}
        runs: list[AutoDock4RunResult] = []
        for pose in sorted(parsed.poses, key=lambda item: item.run):
            row = ranking[pose.run]
            artifact_id = str(uuid4())
            filename = f"run_{pose.run}.pdbqt"
            self._job_store.write_batch_pose(batch_id, ligand_id, filename, pose.content)
            runs.append(
                AutoDock4RunResult(
                    run=pose.run,
                    cluster_rank=row.cluster_rank,
                    sub_rank=row.sub_rank,
                    binding_energy_kcal_mol=row.binding_energy_kcal_mol,
                    cluster_rmsd_angstrom=row.cluster_rmsd_angstrom,
                    reference_rmsd_angstrom=row.reference_rmsd_angstrom,
                    artifact=AutoDock4PoseArtifact(
                        artifact_id=artifact_id,
                        run=pose.run,
                        filename=filename,
                        format="pdbqt",
                        sha256=sha256(pose.content).hexdigest(),
                        size_bytes=len(pose.content),
                        content_url=(
                            f"/docking/autodock4/batches/{batch_id}/ligands/"
                            f"{ligand_id}/poses/{artifact_id}/content"
                        ),
                    ),
                )
            )
        members: dict[int, list[int]] = defaultdict(list)
        for row in sorted(parsed.ranking, key=lambda item: (item.cluster_rank, item.sub_rank)):
            members[row.cluster_rank].append(row.run)
        clusters = [
            AutoDock4ClusterResult(
                cluster_rank=cluster.cluster_rank,
                lowest_binding_energy_kcal_mol=cluster.lowest_binding_energy_kcal_mol,
                mean_binding_energy_kcal_mol=cluster.mean_binding_energy_kcal_mol,
                run_count=cluster.run_count,
                representative_run=cluster.representative_run,
                runs=members[cluster.cluster_rank],
            )
            for cluster in parsed.clusters
        ]
        return runs, clusters

    def _finish_entry(
        self,
        batch_id: str,
        ligand_id: str,
        *,
        status: AutoDock4JobStatus,
        execution: AutoDock4ExecutionEvidence | None = None,
        command: list[str] | None = None,
        dpf_sha256: str | None = None,
        runs: list[AutoDock4RunResult] | None = None,
        clusters: list[AutoDock4ClusterResult] | None = None,
        failure: AutoDock4Failure | None = None,
        provenance: ProvenanceEvent | None = None,
    ) -> None:
        self._update_entry(
            batch_id,
            ligand_id,
            lambda current: current.model_copy(
                update={
                    "status": status,
                    "phase": AutoDock4JobPhase.COMPLETE,
                    "completed_at": datetime.now(UTC),
                    "execution": execution or current.execution,
                    "command": command or current.command,
                    "dpf_sha256": dpf_sha256 or current.dpf_sha256,
                    "runs": runs if runs is not None else current.runs,
                    "clusters": clusters if clusters is not None else current.clusters,
                    "failure": failure,
                    "provenance": provenance or current.provenance,
                }
            ),
        )

    def _update_entry(
        self,
        batch_id: str,
        ligand_id: str,
        change: "Callable[[AutoDock4BatchLigandResult], AutoDock4BatchLigandResult]",
    ) -> None:
        with self._batch_write_lock:
            current = self._job_store.load_batch_entry(batch_id, ligand_id)
            if current is None:
                raise self._input_error(
                    "AUTODOCK4_BATCH_LIGAND_NOT_FOUND",
                    "The AutoDock4 campaign no longer contains its selected ligand.",
                    {"batch_id": batch_id, "ligand_id": ligand_id},
                )
            self._job_store.update_batch_entry(batch_id, change(current))

    def _update_batch(
        self,
        batch_id: str,
        change: "Callable[[AutoDock4BatchRecord], AutoDock4BatchRecord]",
    ) -> None:
        """Serialize every batch mutation: workers finish concurrently."""
        with self._batch_write_lock:
            current = self._job_store.load_batch(batch_id)
            updated = change(current)
            self._job_store.update_batch(
                updated.model_copy(update={"revision": current.revision + 1}),
                changed_entries=[],
            )

    def _validate_receptor_and_site(
        self, request: AutoDock4DockingRequest | AutoDock4BatchRequest
    ) -> tuple[ReceptorOutputArtifact, BindingSiteRecord]:
        return resolve_receptor_and_site(
            receptor_id=request.receptor_id,
            binding_site_id=request.binding_site_id,
            receptor_store=self._receptor_store,
            binding_site_store=self._binding_site_store,
            stage=_STAGE,
            code_prefix="AUTODOCK4",
        )

    def _validate_map_set_applies(
        self,
        map_set: AutoGridMapSetRecord,
        *,
        receptor_output: ReceptorOutputArtifact,
        binding_site: BindingSiteRecord,
    ) -> list[StructuredWarning]:
        return validate_map_set_applies(
            map_set,
            receptor_output=receptor_output,
            binding_site=binding_site,
            stage=_STAGE,
            code_prefix="AUTODOCK4",
        )

    def _finish(
        self,
        record: AutoDock4DockingJobRecord,
        *,
        status: AutoDock4JobStatus,
        execution: AutoDock4ExecutionEvidence | None = None,
        failure: AutoDock4Failure | None = None,
    ) -> None:
        current = self._job_store.load_job(record.job_id)
        self._job_store.update_job(
            current.model_copy(
                update={
                    "status": status,
                    "phase": AutoDock4JobPhase.COMPLETE,
                    "completed_at": datetime.now(UTC),
                    "execution": execution or current.execution,
                    "failure": failure,
                }
            )
        )

    def _forget(self, job_id: str) -> None:
        with self._lock:
            self._cancel_events.pop(job_id, None)

    @staticmethod
    def _require_ascii_job_directory(job_directory: Path) -> None:
        if not str(job_directory).isascii():
            raise AnkoraDomainError(
                code="AUTODOCK4_DATA_DIRECTORY_NOT_ASCII",
                stage=_STAGE,
                message=(
                    "AutoDock4 4.2.6 requires an ASCII-only working path. Set "
                    "ANKORA_DATA_DIR to a directory without accented or "
                    "non-Latin characters."
                ),
                status_code=422,
                details={"job_directory": str(job_directory)},
            )

    @staticmethod
    def _verify_hash(path: Path, expected: str) -> None:
        digest = sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        if digest.hexdigest() != expected:
            raise AnkoraDomainError(
                code="AUTODOCK4_INPUT_HASH_MISMATCH",
                stage=_STAGE,
                message="The prepared ligand no longer matches its stored hash.",
                status_code=422,
                details={"path": path.name, "expected_sha256": expected},
            )

    @staticmethod
    def _input_error(code: str, message: str, details: dict[str, object]) -> AnkoraDomainError:
        return AnkoraDomainError(
            code=code, stage=_STAGE, message=message, status_code=422, details=details
        )


def _map_prefix(map_set: AutoGridMapSetRecord) -> str:
    field = next(item for item in map_set.artifacts if item.kind is AutoGridMapKind.FIELD)
    return field.filename.removesuffix(".maps.fld")


_ordered_atom_types = ordered_atom_types
_torsdof = torsional_degrees_of_freedom


def _centroid(atom_lines: list[str]) -> tuple[float, float, float]:
    coordinates = [
        (float(line[30:38]), float(line[38:46]), float(line[46:54])) for line in atom_lines
    ]
    count = len(coordinates)
    return (
        sum(item[0] for item in coordinates) / count,
        sum(item[1] for item in coordinates) / count,
        sum(item[2] for item in coordinates) / count,
    )
