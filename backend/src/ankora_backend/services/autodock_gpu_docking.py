"""One AutoDock-GPU job at a time, against an already-generated map set.

**One at a time is a measurement, not a convention.** Running two AutoDock-GPU
processes concurrently against one device made a twenty-ligand workload *slower*
- 26.9 s against 23.1 s - because they contend for the same GPU. The CPU engine
parallelises across ligands because it has sixteen cores and a single-threaded
executable; this engine has one device, and feeding it from more than one
process only adds contention. So the executor holds exactly one worker.

Everything else mirrors the CPU service deliberately: the same input
validation, drawn from `autodock_inputs` so the two cannot drift; the same
create-only pose artifacts; the same cancellation contract. What differs is
what the tool itself forced - the verdict comes from stdout because the exit
code is zero either way, and every record carries the backend, the device, and
the statement that a repeat will not reproduce it.
"""

import os
import shutil
import threading
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

from ankora_backend.adapters.engines.autodock4_job import (
    ParsedAutoDock4Log,
    parse_autodock4_log,
)
from ankora_backend.adapters.engines.autodock_gpu import (
    DOCKING_LOG_FILENAME,
    LIGAND_FILENAME,
    AutoDockGpuInstallation,
    build_arguments,
    execute_autodock_gpu_cancellable,
    probe_autodock_gpu,
    require_device,
    run_reports_success,
)
from ankora_backend.domain.errors import AnkoraDomainError
from ankora_backend.persistence.autodock_gpu_store import AutoDockGpuJobStore
from ankora_backend.persistence.autogrid_store import AutoGridMapStore
from ankora_backend.persistence.binding_site_store import BindingSiteArtifactStore
from ankora_backend.persistence.ligand_store import LigandArtifactStore
from ankora_backend.persistence.receptor_store import ReceptorArtifactStore
from ankora_backend.schemas.autodock4 import AutoDock4PoseArtifact
from ankora_backend.schemas.autodock_gpu import (
    AutoDockClusterResult,
    AutoDockFailure,
    AutoDockGpuBatchLigandResult,
    AutoDockGpuBatchProgress,
    AutoDockGpuBatchRecord,
    AutoDockGpuBatchRequest,
    AutoDockGpuCancelResponse,
    AutoDockGpuDockingJobRecord,
    AutoDockGpuDockingRequest,
    AutoDockGpuExecutionEvidence,
    AutoDockGpuToolIdentity,
    AutoDockJobPhase,
    AutoDockJobStatus,
    AutoDockRunResult,
)
from ankora_backend.schemas.autogrid import AutoGridMapKind, AutoGridMapSetRecord
from ankora_backend.schemas.binding_sites import BindingSiteRecord
from ankora_backend.schemas.provenance import ProvenanceEvent, ToolIdentity
from ankora_backend.schemas.warnings import StructuredWarning, WarningCode
from ankora_backend.services.autodock_inputs import (
    SelectedMolecule,
    ordered_atom_types,
    resolve_receptor_and_site,
    resolve_selection,
    torsional_degrees_of_freedom,
    validate_map_set_applies,
)

_STAGE = "autodock_gpu_docking"
_CODE_PREFIX = "AUTODOCK_GPU"
_FILELIST_NAME = "campaign.lst"

# Stated on every job rather than left in a docstring: six repeats of one seed
# on one machine produced six different ranking tables, spanning 0.13 kcal/mol.
_NOT_REPRODUCIBLE = StructuredWarning(
    code=WarningCode.DOCKING_BACKEND_NOT_REPRODUCIBLE,
    message=(
        "AutoDock-GPU does not reproduce a run from its seed. Repeating this "
        "job with these exact inputs will give slightly different energies and "
        "a different cluster structure. The AutoDock4 CPU backend is "
        "bit-identical across repeats if an exactly reproducible result is "
        "required."
    ),
    stage=_STAGE,
    details={"measured_spread_kcal_mol": 0.13, "repeats": 6},
    recoverable=True,
)


@dataclass(frozen=True, slots=True)
class _PreparedDocking:
    request: AutoDockGpuDockingRequest
    installation: AutoDockGpuInstallation
    device_name: str
    map_set: AutoGridMapSetRecord
    field_filename: str
    ligand_path: Path
    ligand_sha256: str
    ligand_atom_types: tuple[str, ...]
    atom_count: int
    torsional_degrees_of_freedom: int
    binding_site: BindingSiteRecord
    warnings: list[StructuredWarning]


class _JobCanceled(Exception):
    def __init__(self, *, execution: AutoDockGpuExecutionEvidence) -> None:
        super().__init__("AutoDock-GPU docking was canceled")
        self.execution = execution


class AutoDockGpuDockingService:
    def __init__(
        self,
        *,
        job_store: AutoDockGpuJobStore,
        map_store: AutoGridMapStore,
        ligand_store: LigandArtifactStore,
        receptor_store: ReceptorArtifactStore,
        binding_site_store: BindingSiteArtifactStore,
    ) -> None:
        self._job_store = job_store
        self._map_store = map_store
        self._ligand_store = ligand_store
        self._receptor_store = receptor_store
        self._binding_site_store = binding_site_store
        # One device, one worker. See the module docstring for the measurement.
        self._executor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="ankora-autodock-gpu"
        )
        self._cancel_events: dict[str, threading.Event] = {}
        self._lock = threading.RLock()
        self._batch_lock = threading.Lock()
        self._active_batch_id: str | None = None

    @classmethod
    def from_environment(cls) -> "AutoDockGpuDockingService":
        return cls(
            job_store=AutoDockGpuJobStore.from_environment(),
            map_store=AutoGridMapStore.from_environment(),
            ligand_store=LigandArtifactStore.from_environment(),
            receptor_store=ReceptorArtifactStore.from_environment(),
            binding_site_store=BindingSiteArtifactStore.from_environment(),
        )

    def start(self, request: AutoDockGpuDockingRequest) -> AutoDockGpuDockingJobRecord:
        if not request.acknowledge_inputs_and_scoring:
            raise self._input_error(
                f"{_CODE_PREFIX}_CONFIRMATION_REQUIRED",
                (
                    "Confirm the exact receptor, map set, ligand, and search "
                    "settings before docking."
                ),
                {},
            )
        prepared = self._prepare(request)
        job_id = self._job_store.new_job_id()
        record = AutoDockGpuDockingJobRecord(
            job_id=job_id,
            status=AutoDockJobStatus.QUEUED,
            phase=AutoDockJobPhase.QUEUED,
            created_at=datetime.now(UTC),
            request=request,
            autodock_gpu=self._identity(prepared),
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

    def get(self, job_id: str) -> AutoDockGpuDockingJobRecord:
        return self._job_store.load_job(job_id)

    def pose_content_path(self, job_id: str, artifact_id: str) -> Path:
        return self._job_store.pose_content_path(job_id, artifact_id)

    def cancel(self, job_id: str) -> AutoDockGpuCancelResponse:
        with self._lock:
            record = self._job_store.load_job(job_id)
            if record.status in {
                AutoDockJobStatus.CANCELED,
                AutoDockJobStatus.COMPLETED,
                AutoDockJobStatus.FAILED,
            }:
                return AutoDockGpuCancelResponse(job_id=job_id, status=record.status)
            cancel_event = self._cancel_events.get(job_id)
            if cancel_event is None:
                raise AnkoraDomainError(
                    code=f"{_CODE_PREFIX}_JOB_NOT_ACTIVE",
                    stage=_STAGE,
                    message=(
                        "This docking job is not active in the current Ankora session."
                    ),
                    status_code=409,
                    details={"job_id": job_id, "status": record.status.value},
                )
            cancel_event.set()
            self._job_store.update_job(
                record.model_copy(update={"status": AutoDockJobStatus.CANCEL_REQUESTED})
            )
        return AutoDockGpuCancelResponse(
            job_id=job_id, status=AutoDockJobStatus.CANCEL_REQUESTED
        )

    def shutdown(self) -> None:
        with self._lock:
            for event in self._cancel_events.values():
                event.set()
        self._executor.shutdown(wait=True, cancel_futures=True)

    # --- execution ---------------------------------------------------------

    def _run(
        self,
        job_id: str,
        prepared: _PreparedDocking,
        cancel_event: threading.Event,
    ) -> None:
        record = self._job_store.load_job(job_id)
        if cancel_event.is_set():
            self._finish(record, status=AutoDockJobStatus.CANCELED)
            self._forget(job_id)
            return
        running = record.model_copy(
            update={
                "status": AutoDockJobStatus.RUNNING,
                "phase": AutoDockJobPhase.DOCKING,
                "started_at": datetime.now(UTC),
            }
        )
        self._job_store.update_job(running)
        try:
            self._execute(running, prepared, cancel_event)
        except _JobCanceled as canceled:
            self._finish(
                running,
                status=AutoDockJobStatus.CANCELED,
                execution=canceled.execution,
            )
        except AnkoraDomainError as error:
            self._finish(
                running,
                status=AutoDockJobStatus.FAILED,
                failure=AutoDockFailure(
                    code=error.code, message=error.message, details=dict(error.details)
                ),
            )
        finally:
            self._forget(job_id)

    def _execute(
        self,
        record: AutoDockGpuDockingJobRecord,
        prepared: _PreparedDocking,
        cancel_event: threading.Event,
    ) -> None:
        job_id = record.job_id
        job_directory = self._job_store.job_directory(job_id)
        self._require_ascii_job_directory(job_directory)
        self._stage_inputs(job_directory, prepared)

        parameters = prepared.request.parameters
        arguments = build_arguments(
            field_filename=prepared.field_filename,
            device_number=parameters.device_number,
            runs=parameters.runs,
            seed=parameters.seed,
            heuristics=parameters.heuristics,
            autostop=parameters.autostop,
            energy_evaluations=(
                None if parameters.heuristics else parameters.energy_evaluations
            ),
            population_size=parameters.population_size,
            local_search_method=parameters.local_search_method.value,
            cluster_rmsd_tolerance_angstrom=parameters.cluster_rmsd_tolerance_angstrom,
        )

        started = time.monotonic()
        execution = execute_autodock_gpu_cancellable(
            installation=prepared.installation,
            job_directory=job_directory,
            arguments=arguments,
            timeout_seconds=parameters.timeout_minutes * 60,
            cancel_event=cancel_event,
        )
        duration = time.monotonic() - started
        # The verdict is in what the tool printed, never in its exit code.
        reported_success = run_reports_success(execution.stdout)
        evidence = AutoDockGpuExecutionEvidence(
            command=execution.command,
            exit_code=execution.exit_code,
            stdout=execution.stdout,
            stderr=execution.stderr,
            duration_seconds=duration,
            success_reported_on_stdout=reported_success,
            canceled=execution.canceled,
            timed_out=execution.timed_out,
        )
        self._job_store.update_job(
            record.model_copy(
                update={"command": execution.command, "execution": evidence}
            )
        )
        if execution.canceled:
            raise _JobCanceled(execution=evidence)
        if execution.timed_out:
            raise self._input_error(
                f"{_CODE_PREFIX}_EXECUTION_TIMED_OUT",
                "AutoDock-GPU exceeded the configured timeout; its output is preserved.",
                {
                    "timeout_minutes": parameters.timeout_minutes,
                    **evidence.model_dump(mode="json"),
                },
            )
        log_path = job_directory / DOCKING_LOG_FILENAME
        if not reported_success or not log_path.is_file():
            raise self._input_error(
                f"{_CODE_PREFIX}_EXECUTION_FAILED",
                "AutoDock-GPU did not report a successful run; its output is preserved.",
                evidence.model_dump(mode="json"),
            )

        self._job_store.update_job(
            record.model_copy(
                update={
                    "phase": AutoDockJobPhase.PARSING_RESULTS,
                    "command": execution.command,
                    "execution": evidence,
                }
            )
        )
        parsed = parse_autodock4_log(
            log_path.read_text(encoding="utf-8", errors="replace")
        )
        runs, clusters = self._persist_results(job_id, parsed)
        completed_at = datetime.now(UTC)
        self._job_store.update_job(
            record.model_copy(
                update={
                    "status": AutoDockJobStatus.COMPLETED,
                    "phase": AutoDockJobPhase.COMPLETE,
                    "completed_at": completed_at,
                    "command": execution.command,
                    "execution": evidence,
                    "runs": runs,
                    "clusters": clusters,
                    "provenance": ProvenanceEvent(
                        event_id=f"autodock-gpu-docking-{job_id}",
                        event_type="autodock_gpu_docking_completed",
                        timestamp=completed_at,
                        input_artifacts=[
                            prepared.map_set.map_set_id,
                            prepared.binding_site.binding_site_id,
                            prepared.request.ligand_preparation_id,
                        ],
                        output_artifacts=[item.artifact.artifact_id for item in runs],
                        tool=ToolIdentity(
                            name="AutoDock-GPU", version=prepared.installation.version
                        ),
                        parameters={
                            **parameters.model_dump(mode="json"),
                            "map_set_identity_key": prepared.map_set.identity_key,
                            "ligand_atom_types": list(prepared.ligand_atom_types),
                            "autodock_gpu_sha256": prepared.installation.sha256,
                            "device_name": prepared.device_name,
                            "bitwise_reproducible": False,
                        },
                        command=execution.command,
                    ),
                }
            )
        )

    def _persist_results(
        self, job_id: str, parsed: ParsedAutoDock4Log
    ) -> tuple[list[AutoDockRunResult], list[AutoDockClusterResult]]:
        ranking = {row.run: row for row in parsed.ranking}
        runs: list[AutoDockRunResult] = []
        for pose in sorted(parsed.poses, key=lambda item: item.run):
            row = ranking[pose.run]
            artifact_id = str(uuid4())
            filename = f"run_{pose.run}.pdbqt"
            self._job_store.write_pose(job_id, filename, pose.content)
            runs.append(
                AutoDockRunResult(
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
                            f"/docking/autodock-gpu/jobs/{job_id}"
                            f"/poses/{artifact_id}/content"
                        ),
                    ),
                )
            )
        members: dict[int, list[int]] = defaultdict(list)
        for row in sorted(
            parsed.ranking, key=lambda item: (item.cluster_rank, item.sub_rank)
        ):
            members[row.cluster_rank].append(row.run)
        clusters = [
            AutoDockClusterResult(
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

    # --- inputs ------------------------------------------------------------

    def _prepare(self, request: AutoDockGpuDockingRequest) -> _PreparedDocking:
        installation = probe_autodock_gpu(
            device_number=request.parameters.device_number
        )
        device_name = require_device(installation)
        map_set = self._map_store.load_record(request.map_set_id)
        receptor_output, binding_site = resolve_receptor_and_site(
            receptor_id=request.receptor_id,
            binding_site_id=request.binding_site_id,
            receptor_store=self._receptor_store,
            binding_site_store=self._binding_site_store,
            stage=_STAGE,
            code_prefix=_CODE_PREFIX,
        )
        warnings = validate_map_set_applies(
            map_set,
            receptor_output=receptor_output,
            binding_site=binding_site,
            stage=_STAGE,
            code_prefix=_CODE_PREFIX,
        )
        # Every GPU job carries the reproducibility statement, always.
        warnings = [*warnings, _NOT_REPRODUCIBLE]

        pdbqt = self._ligand_store.load_pdbqt_record(
            request.ligand_id, request.ligand_preparation_id
        )
        ligand_path = self._ligand_store.pdbqt_content_path(
            request.ligand_id, request.ligand_preparation_id
        )
        document = ligand_path.read_text(encoding="utf-8", errors="replace")
        atom_types = ordered_atom_types(document)
        atom_lines = [
            line
            for line in document.splitlines()
            if line.startswith(("ATOM  ", "HETATM"))
        ]
        available = {
            artifact.atom_type
            for artifact in map_set.artifacts
            if artifact.kind is AutoGridMapKind.AFFINITY
        }
        missing = sorted(set(atom_types) - available)
        if missing:
            raise self._input_error(
                f"{_CODE_PREFIX}_LIGAND_TYPES_NOT_IN_MAP_SET",
                (
                    "This ligand uses atom types the selected map set does not "
                    "cover. Generate a map set that includes them."
                ),
                {
                    "missing_atom_types": missing,
                    "map_set_atom_types": sorted(
                        value for value in available if value is not None
                    ),
                },
            )
        return _PreparedDocking(
            request=request,
            installation=installation,
            device_name=device_name,
            map_set=map_set,
            field_filename=_field_filename(map_set),
            ligand_path=ligand_path,
            ligand_sha256=pdbqt.artifact.sha256,
            ligand_atom_types=atom_types,
            atom_count=len(atom_lines),
            torsional_degrees_of_freedom=torsional_degrees_of_freedom(document),
            binding_site=binding_site,
            warnings=warnings,
        )

    def _identity(self, prepared: _PreparedDocking) -> AutoDockGpuToolIdentity:
        return AutoDockGpuToolIdentity(
            tool=ToolIdentity(
                name="AutoDock-GPU", version=prepared.installation.version
            ),
            executable_path=prepared.installation.executable,
            sha256=prepared.installation.sha256,
            architecture=prepared.installation.architecture,
            build=prepared.installation.build,
            device_number=prepared.request.parameters.device_number,
            device_name=prepared.device_name,
        )

    def _stage_inputs(self, job_directory: Path, prepared: _PreparedDocking) -> None:
        """Hard-link the maps rather than copy them; the tool only reads them."""
        shutil.copyfile(prepared.ligand_path, job_directory / LIGAND_FILENAME)
        source_directory = self._map_store.map_set_directory(prepared.map_set.map_set_id)
        for artifact in prepared.map_set.artifacts:
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

    # --- lifecycle ---------------------------------------------------------

    def _finish(
        self,
        record: AutoDockGpuDockingJobRecord,
        *,
        status: AutoDockJobStatus,
        execution: AutoDockGpuExecutionEvidence | None = None,
        failure: AutoDockFailure | None = None,
    ) -> None:
        # Reload rather than copy the caller's record: `_execute` writes the
        # execution evidence to the store as it goes, and a failed or canceled
        # run must keep that raw output rather than lose it to a stale copy.
        current = self._job_store.load_job(record.job_id)
        self._job_store.update_job(
            current.model_copy(
                update={
                    "status": status,
                    "phase": AutoDockJobPhase.COMPLETE,
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
        """AutoDock-GPU reads relative filenames from an ASCII-safe directory."""
        try:
            str(job_directory).encode("ascii")
        except UnicodeEncodeError as error:
            raise AnkoraDomainError(
                code=f"{_CODE_PREFIX}_JOB_PATH_NOT_ASCII",
                stage=_STAGE,
                message=(
                    "The Ankora data directory contains characters AutoDock-GPU "
                    "cannot read. Move the project to an ASCII-only path."
                ),
                status_code=422,
                details={"job_directory": str(job_directory)},
            ) from error

    @staticmethod
    def _input_error(
        code: str, message: str, details: dict[str, object]
    ) -> AnkoraDomainError:
        return AnkoraDomainError(
            code=code, stage=_STAGE, message=message, status_code=422, details=details
        )

    # --- library campaigns -------------------------------------------------

    def start_batch(self, request: AutoDockGpuBatchRequest) -> AutoDockGpuBatchRecord:
        """Dock a whole applied selection in one AutoDock-GPU invocation.

        The tool takes a file list and docks every molecule in it against maps
        it loads once. That measured 1.4x faster than one process per molecule,
        and running two such processes at once measured slower than one, so a
        campaign is exactly one process and only one campaign runs at a time.
        """
        if not request.acknowledge_inputs_and_scoring:
            raise self._input_error(
                f"{_CODE_PREFIX}_CONFIRMATION_REQUIRED",
                (
                    "Confirm the exact receptor, map set, selection, and search "
                    "settings before docking."
                ),
                {},
            )
        with self._batch_lock:
            if self._active_batch_id is not None:
                raise AnkoraDomainError(
                    code=f"{_CODE_PREFIX}_CAMPAIGN_ALREADY_RUNNING",
                    stage=_STAGE,
                    message=(
                        "One GPU campaign runs at a time: the device is shared "
                        "and a second process only slows the first down."
                    ),
                    status_code=409,
                    details={"active_batch_id": self._active_batch_id},
                )
            record, prepared = self._create_batch(request)
            self._active_batch_id = record.batch_id
        cancel_event = threading.Event()
        with self._lock:
            self._cancel_events[record.batch_id] = cancel_event
        self._executor.submit(self._run_batch, record.batch_id, prepared, cancel_event)
        return record

    def get_batch(self, batch_id: str) -> AutoDockGpuBatchRecord:
        return self._job_store.load_batch(batch_id)

    def get_batch_progress(self, batch_id: str) -> AutoDockGpuBatchProgress:
        record = self._job_store.load_batch(batch_id)
        return AutoDockGpuBatchProgress(
            batch_id=record.batch_id,
            status=record.status,
            revision=record.revision,
            selected_count=record.selected_count,
            completed_count=record.completed_count,
            succeeded_count=record.succeeded_count,
            failed_count=record.failed_count,
            canceled_count=record.canceled_count,
        )

    def cancel_batch(self, batch_id: str) -> AutoDockGpuCancelResponse:
        with self._lock:
            record = self._job_store.load_batch(batch_id)
            if record.status in {
                AutoDockJobStatus.CANCELED,
                AutoDockJobStatus.COMPLETED,
                AutoDockJobStatus.FAILED,
            }:
                return AutoDockGpuCancelResponse(job_id=batch_id, status=record.status)
            event = self._cancel_events.get(batch_id)
            if event is None:
                raise AnkoraDomainError(
                    code=f"{_CODE_PREFIX}_CAMPAIGN_NOT_ACTIVE",
                    stage=_STAGE,
                    message="This campaign is not active in the current Ankora session.",
                    status_code=409,
                    details={"batch_id": batch_id, "status": record.status.value},
                )
            event.set()
            self._job_store.update_batch(
                record.model_copy(
                    update={
                        "status": AutoDockJobStatus.CANCEL_REQUESTED,
                        "revision": record.revision + 1,
                    }
                )
            )
        return AutoDockGpuCancelResponse(
            job_id=batch_id, status=AutoDockJobStatus.CANCEL_REQUESTED
        )

    def latest_batch(
        self, *, receptor_id: str, binding_site_id: str, filter_run_id: str
    ) -> AutoDockGpuBatchRecord:
        matching = [
            record
            for record in self._job_store.list_batches()
            if record.receptor_id == receptor_id
            and record.binding_site_id == binding_site_id
            and record.request.filter_run_id == filter_run_id
        ]
        if not matching:
            raise AnkoraDomainError(
                code=f"{_CODE_PREFIX}_BATCH_HISTORY_EMPTY",
                stage=_STAGE,
                message="No AutoDock-GPU campaign is available for these exact inputs.",
                status_code=404,
                details={
                    "receptor_id": receptor_id,
                    "binding_site_id": binding_site_id,
                    "filter_run_id": filter_run_id,
                },
            )
        successful = [record for record in matching if record.succeeded_count > 0]
        return max(
            successful or matching,
            key=lambda record: (record.created_at, record.batch_id),
        )

    def batch_pose_content_path(
        self, batch_id: str, ligand_id: str, artifact_id: str
    ) -> Path:
        return self._job_store.batch_pose_content_path(batch_id, ligand_id, artifact_id)

    def _create_batch(
        self, request: AutoDockGpuBatchRequest
    ) -> tuple[AutoDockGpuBatchRecord, "_PreparedCampaign"]:
        installation = probe_autodock_gpu(
            device_number=request.parameters.device_number
        )
        device_name = require_device(installation)
        map_set = self._map_store.load_record(request.map_set_id)
        receptor_output, binding_site = resolve_receptor_and_site(
            receptor_id=request.receptor_id,
            binding_site_id=request.binding_site_id,
            receptor_store=self._receptor_store,
            binding_site_store=self._binding_site_store,
            stage=_STAGE,
            code_prefix=_CODE_PREFIX,
        )
        warnings = validate_map_set_applies(
            map_set,
            receptor_output=receptor_output,
            binding_site=binding_site,
            stage=_STAGE,
            code_prefix=_CODE_PREFIX,
        )
        warnings = [*warnings, _NOT_REPRODUCIBLE]
        selection = resolve_selection(
            library_id=request.library_id,
            filter_run_id=request.filter_run_id,
            map_set=map_set,
            ligand_store=self._ligand_store,
            stage=_STAGE,
            code_prefix=_CODE_PREFIX,
        )
        filter_run = self._ligand_store.load_filter_run(
            request.library_id, request.filter_run_id
        )
        entries = [
            AutoDockGpuBatchLigandResult(
                ligand_id=molecule.ligand_id,
                source_index=molecule.source_index,
                name=molecule.name,
                canonical_smiles=molecule.canonical_smiles,
                molecular_weight_g_mol=molecule.molecular_weight_g_mol,
                ligand_preparation_id=molecule.preparation_id,
                ligand_sha256=molecule.sha256,
                ligand_atom_types=list(molecule.atom_types),
                status=(
                    AutoDockJobStatus.QUEUED
                    if molecule.runnable
                    else AutoDockJobStatus.FAILED
                ),
                phase=(
                    AutoDockJobPhase.QUEUED
                    if molecule.runnable
                    else AutoDockJobPhase.COMPLETE
                ),
                completed_at=None if molecule.runnable else datetime.now(UTC),
                failure=(
                    None
                    if molecule.runnable
                    else AutoDockFailure(
                        code=molecule.unavailable_code or "",
                        message=molecule.unavailable_reason or "",
                    )
                ),
            )
            for molecule in selection
        ]
        runnable = [m for m in selection if m.runnable]
        if not runnable:
            raise self._input_error(
                f"{_CODE_PREFIX}_NO_RUNNABLE_MOLECULES",
                "No molecule in this selection can be docked against this map set.",
                {"selected_count": len(selection)},
            )
        record = AutoDockGpuBatchRecord(
            batch_id=self._job_store.new_batch_id(),
            status=AutoDockJobStatus.QUEUED,
            phase=AutoDockJobPhase.QUEUED,
            created_at=datetime.now(UTC),
            request=request,
            autodock_gpu=AutoDockGpuToolIdentity(
                tool=ToolIdentity(name="AutoDock-GPU", version=installation.version),
                executable_path=installation.executable,
                sha256=installation.sha256,
                architecture=installation.architecture,
                build=installation.build,
                device_number=request.parameters.device_number,
                device_name=device_name,
            ),
            receptor_id=request.receptor_id,
            binding_site_id=request.binding_site_id,
            map_set_id=map_set.map_set_id,
            map_set_identity_key=map_set.identity_key,
            selection_manifest_sha256=filter_run.artifact.sha256,
            selected_count=len(entries),
            failed_count=len(entries) - len(runnable),
            completed_count=len(entries) - len(runnable),
            entries=entries,
            warnings=warnings,
        )
        self._job_store.create_batch(record)
        return record, _PreparedCampaign(
            installation=installation,
            map_set=map_set,
            field_filename=_field_filename(map_set),
            binding_site=binding_site,
            molecules=runnable,
        )

    def _run_batch(
        self,
        batch_id: str,
        prepared: "_PreparedCampaign",
        cancel_event: threading.Event,
    ) -> None:
        try:
            self._execute_batch(batch_id, prepared, cancel_event)
        except AnkoraDomainError as error:
            current = self._job_store.load_batch(batch_id)
            self._job_store.update_batch(
                current.model_copy(
                    update={
                        "status": AutoDockJobStatus.FAILED,
                        "phase": AutoDockJobPhase.COMPLETE,
                        "completed_at": datetime.now(UTC),
                        "failure": AutoDockFailure(
                            code=error.code,
                            message=error.message,
                            details=dict(error.details),
                        ),
                        "revision": current.revision + 1,
                    }
                )
            )
        finally:
            with self._batch_lock:
                self._active_batch_id = None
            self._forget(batch_id)

    def _execute_batch(
        self,
        batch_id: str,
        prepared: "_PreparedCampaign",
        cancel_event: threading.Event,
    ) -> None:
        work = self._job_store.batch_work_directory(batch_id)
        self._require_ascii_job_directory(work)
        record = self._job_store.load_batch(batch_id)
        parameters = record.request.parameters

        # One staged directory, one file list, one invocation.
        self._stage_maps(work, prepared.map_set)
        tags: dict[str, SelectedMolecule] = {}
        listed = [prepared.field_filename]
        for index, molecule in enumerate(prepared.molecules, start=1):
            tag = f"m{index}"
            tags[tag] = molecule
            assert molecule.path is not None
            shutil.copyfile(molecule.path, work / f"{tag}.pdbqt")
            listed += [f"{tag}.pdbqt", tag]
        (work / _FILELIST_NAME).write_text(
            "\n".join(listed) + "\n", encoding="ascii", newline="\n"
        )

        arguments = build_arguments(
            field_filename=prepared.field_filename,
            device_number=parameters.device_number,
            runs=parameters.runs,
            seed=parameters.seed,
            heuristics=parameters.heuristics,
            autostop=parameters.autostop,
            energy_evaluations=(
                None if parameters.heuristics else parameters.energy_evaluations
            ),
            population_size=parameters.population_size,
            local_search_method=parameters.local_search_method.value,
            cluster_rmsd_tolerance_angstrom=parameters.cluster_rmsd_tolerance_angstrom,
        )
        # A file list replaces the single ligand and its output name.
        arguments = _as_filelist_arguments(arguments)

        self._job_store.update_batch(
            record.model_copy(
                update={
                    "status": AutoDockJobStatus.RUNNING,
                    "phase": AutoDockJobPhase.DOCKING,
                    "started_at": datetime.now(UTC),
                    "command": arguments,
                    "revision": record.revision + 1,
                }
            )
        )
        # AutoDock-GPU writes each molecule's log as it finishes, so progress is
        # read from the directory while the single process is still running.
        watcher = threading.Thread(
            target=self._watch_progress,
            args=(batch_id, work, len(prepared.molecules), cancel_event),
            daemon=True,
        )
        watcher.start()

        started = time.monotonic()
        execution = execute_autodock_gpu_cancellable(
            installation=prepared.installation,
            job_directory=work,
            arguments=arguments,
            timeout_seconds=parameters.timeout_minutes * 60,
            cancel_event=cancel_event,
        )
        duration = time.monotonic() - started
        watcher.join(timeout=2)
        evidence = AutoDockGpuExecutionEvidence(
            command=execution.command,
            exit_code=execution.exit_code,
            stdout=execution.stdout,
            stderr=execution.stderr,
            duration_seconds=duration,
            success_reported_on_stdout=run_reports_success(execution.stdout),
            canceled=execution.canceled,
            timed_out=execution.timed_out,
        )
        # Whatever finished before a cancellation or a failure is still real
        # work, so results are collected either way.
        self._collect_batch(batch_id, work, tags, evidence)

    def _watch_progress(
        self,
        batch_id: str,
        work: Path,
        total: int,
        cancel_event: threading.Event,
    ) -> None:
        seen = 0
        while not cancel_event.is_set():
            done = sum(1 for path in work.glob("m*.dlg"))
            if done != seen:
                seen = done
                current = self._job_store.load_batch(batch_id)
                if current.status is not AutoDockJobStatus.RUNNING:
                    return
                unavailable = current.selected_count - total
                self._job_store.update_batch(
                    current.model_copy(
                        update={
                            "completed_count": unavailable + done,
                            "revision": current.revision + 1,
                        }
                    )
                )
            if done >= total:
                return
            time.sleep(0.5)

    def _collect_batch(
        self,
        batch_id: str,
        work: Path,
        tags: dict[str, SelectedMolecule],
        evidence: AutoDockGpuExecutionEvidence,
    ) -> None:
        record = self._job_store.load_batch(batch_id)
        results: dict[str, AutoDockGpuBatchLigandResult] = {
            entry.ligand_id: entry for entry in record.entries
        }
        succeeded = 0
        for tag, molecule in tags.items():
            log = work / f"{tag}.dlg"
            entry = results[molecule.ligand_id]
            if not log.is_file():
                results[molecule.ligand_id] = entry.model_copy(
                    update={
                        "status": (
                            AutoDockJobStatus.CANCELED
                            if evidence.canceled
                            else AutoDockJobStatus.FAILED
                        ),
                        "phase": AutoDockJobPhase.COMPLETE,
                        "completed_at": datetime.now(UTC),
                        "failure": AutoDockFailure(
                            code=f"{_CODE_PREFIX}_MOLECULE_NOT_DOCKED",
                            message=(
                                "The campaign ended before this molecule was docked."
                            ),
                        ),
                        "revision": entry.revision + 1,
                    }
                )
                continue
            parsed = parse_autodock4_log(
                log.read_text(encoding="utf-8", errors="replace")
            )
            runs, clusters = self._persist_batch_results(
                batch_id, molecule.ligand_id, parsed
            )
            succeeded += 1
            results[molecule.ligand_id] = entry.model_copy(
                update={
                    "status": AutoDockJobStatus.COMPLETED,
                    "phase": AutoDockJobPhase.COMPLETE,
                    "completed_at": datetime.now(UTC),
                    "clusters": clusters,
                    "runs": runs,
                    "revision": entry.revision + 1,
                }
            )
        entries = [results[entry.ligand_id] for entry in record.entries]
        canceled = sum(
            1 for entry in entries if entry.status is AutoDockJobStatus.CANCELED
        )
        failed = sum(1 for entry in entries if entry.status is AutoDockJobStatus.FAILED)
        completed_at = datetime.now(UTC)
        status = (
            AutoDockJobStatus.CANCELED
            if evidence.canceled
            else AutoDockJobStatus.COMPLETED
        )
        self._job_store.update_batch(
            record.model_copy(
                update={
                    "status": status,
                    "phase": AutoDockJobPhase.COMPLETE,
                    "completed_at": completed_at,
                    "execution": evidence,
                    "entries": entries,
                    "completed_count": len(entries),
                    "succeeded_count": succeeded,
                    "failed_count": failed,
                    "canceled_count": canceled,
                    "revision": record.revision + 1,
                    "provenance": ProvenanceEvent(
                        event_id=f"autodock-gpu-campaign-{batch_id}",
                        event_type="autodock_gpu_campaign_completed",
                        timestamp=completed_at,
                        input_artifacts=[record.map_set_id, record.binding_site_id],
                        output_artifacts=[batch_id],
                        tool=ToolIdentity(
                            name="AutoDock-GPU",
                            version=record.autodock_gpu.tool.version,
                        ),
                        parameters={
                            **record.request.parameters.model_dump(mode="json"),
                            "map_set_identity_key": record.map_set_identity_key,
                            "device_name": record.autodock_gpu.device_name,
                            "bitwise_reproducible": False,
                            "invocations": 1,
                        },
                        command=evidence.command,
                    ),
                }
            )
        )

    def _persist_batch_results(
        self, batch_id: str, ligand_id: str, parsed: ParsedAutoDock4Log
    ) -> tuple[list[AutoDockRunResult], list[AutoDockClusterResult]]:
        ranking = {row.run: row for row in parsed.ranking}
        runs: list[AutoDockRunResult] = []
        for pose in sorted(parsed.poses, key=lambda item: item.run):
            row = ranking[pose.run]
            artifact_id = str(uuid4())
            filename = f"run_{pose.run}.pdbqt"
            self._job_store.write_batch_pose(
                batch_id, ligand_id, filename, pose.content
            )
            runs.append(
                AutoDockRunResult(
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
                            f"/docking/autodock-gpu/batches/{batch_id}"
                            f"/ligands/{ligand_id}/poses/{artifact_id}/content"
                        ),
                    ),
                )
            )
        members: dict[int, list[int]] = defaultdict(list)
        for row in sorted(
            parsed.ranking, key=lambda item: (item.cluster_rank, item.sub_rank)
        ):
            members[row.cluster_rank].append(row.run)
        clusters = [
            AutoDockClusterResult(
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

    def _stage_maps(self, work: Path, map_set: AutoGridMapSetRecord) -> None:
        source_directory = self._map_store.map_set_directory(map_set.map_set_id)
        for artifact in map_set.artifacts:
            if artifact.kind in {
                AutoGridMapKind.GRID_PARAMETER_FILE,
                AutoGridMapKind.GRID_LOG,
                AutoGridMapKind.RECEPTOR,
            }:
                continue
            destination = work / artifact.filename
            if destination.exists():
                continue
            source = source_directory / artifact.filename
            try:
                os.link(source, destination)
            except OSError:
                shutil.copyfile(source, destination)

def _field_filename(map_set: AutoGridMapSetRecord) -> str:
    """The `.fld` descriptor is what `--ffile` consumes."""
    field = next(
        item for item in map_set.artifacts if item.kind is AutoGridMapKind.FIELD
    )
    return field.filename

@dataclass(frozen=True, slots=True)
class _PreparedCampaign:
    installation: AutoDockGpuInstallation
    map_set: AutoGridMapSetRecord
    field_filename: str
    binding_site: BindingSiteRecord
    molecules: list[SelectedMolecule]


def _as_filelist_arguments(arguments: list[str]) -> list[str]:
    """Swap the single-ligand flags for the file list the campaign staged.

    `build_arguments` is the one place the search protocol is written out, so a
    campaign reuses it rather than composing a second, divergent command line.
    """
    result: list[str] = []
    skip = False
    for value in arguments:
        if skip:
            skip = False
            continue
        if value in {"--lfile", "--resnam"}:
            skip = True
            continue
        result.append(value)
    return [*result, "--filelist", _FILELIST_NAME]
