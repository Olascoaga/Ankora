"""Single-ligand GNINA jobs. Scientific output is not published before validation."""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

from ankora_backend.adapters.engines.gnina import (
    GninaInstallation,
    build_gnina_arguments,
    execute_gnina,
    parse_gnina_pdbqt,
    probe_gnina,
    require_matching_topology,
)
from ankora_backend.domain.errors import AnkoraDomainError
from ankora_backend.persistence.binding_site_store import BindingSiteArtifactStore
from ankora_backend.persistence.gnina_store import GninaJobStore
from ankora_backend.persistence.ligand_store import LigandArtifactStore
from ankora_backend.persistence.receptor_store import ReceptorArtifactStore
from ankora_backend.schemas.docking import (
    DockingCancelResponse,
    DockingFailure,
    DockingJobPhase,
    DockingJobStatus,
)
from ankora_backend.schemas.gnina import (
    GninaDockingRequest,
    GninaExecutionEvidence,
    GninaJobRecord,
    GninaPoseArtifact,
    GninaPoseResult,
    GninaToolIdentity,
)
from ankora_backend.schemas.receptors import ReceptorOutputStage, ReceptorPreparationStatus
from ankora_backend.schemas.work_recovery import WorkKind
from ankora_backend.services.execution_freshness import require_current_inputs
from ankora_backend.services.gnina_gpu_observer import GninaGpuObserver
from ankora_backend.services.resource_arbiter import (
    ResourceArbiter,
    ResourceClaim,
    ResourceLease,
    ResourceRequestCanceled,
)
from ankora_backend.services.work_leases import WorkLeaseManager


def _failure(code: str, message: str, **details: object) -> AnkoraDomainError:
    return AnkoraDomainError(
        code=code, stage="gnina_docking", message=message, details=details, status_code=422
    )


def _verified_bytes(path: Path, expected: str, kind: str) -> bytes:
    try:
        content = path.read_bytes()
    except OSError as error:
        raise _failure(
            "GNINA_INPUT_UNREADABLE", "A required input could not be read.", input_kind=kind
        ) from error
    if sha256(content).hexdigest() != expected:
        raise _failure(
            "GNINA_INPUT_CHANGED", "A required input no longer matches its record.", input_kind=kind
        )
    return content


class GninaDockingService:
    def __init__(
        self,
        *,
        store: GninaJobStore,
        receptors: ReceptorArtifactStore,
        sites: BindingSiteArtifactStore,
        ligands: LigandArtifactStore,
        leases: WorkLeaseManager,
        resources: ResourceArbiter,
        enable_experimental_cuda: bool = False,
    ) -> None:
        self._store = store
        self._receptors = receptors
        self._sites = sites
        self._ligands = ligands
        self._leases = leases
        self._resources = resources
        self._enable_experimental_cuda = enable_experimental_cuda
        self._lock = threading.RLock()
        self._events: dict[str, threading.Event] = {}
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ankora-gnina")

    @classmethod
    def from_environment(
        cls,
        *,
        leases: WorkLeaseManager,
        resources: ResourceArbiter,
        enable_experimental_cuda: bool = False,
    ) -> GninaDockingService:
        return cls(
            store=GninaJobStore.from_environment(),
            receptors=ReceptorArtifactStore.from_environment(),
            sites=BindingSiteArtifactStore.from_environment(),
            ligands=LigandArtifactStore.from_environment(),
            leases=leases,
            resources=resources,
            enable_experimental_cuda=enable_experimental_cuda,
        )

    def start(self, request: GninaDockingRequest) -> GninaJobRecord:
        # CUDA remains gated until independent, process-specific GPU observation is wired in.
        if request.parameters.compute == "cuda" and not self._enable_experimental_cuda:
            raise _failure(
                "GNINA_CUDA_VERIFICATION_UNAVAILABLE",
                "GNINA CUDA execution is not enabled until GPU evidence is verified.",
            )
        require_current_inputs(request, binding_site_store=self._sites, ligand_store=self._ligands)
        receptor = self._receptors.load_record(request.receptor_id)
        if receptor.status is not ReceptorPreparationStatus.DOCKING_READY:
            raise _failure("GNINA_RECEPTOR_NOT_READY", "The receptor is not docking ready.")
        output = next(
            (item for item in receptor.outputs if item.stage is ReceptorOutputStage.PDBQT), None
        )
        if output is None:
            raise _failure("GNINA_RECEPTOR_PDBQT_MISSING", "The receptor has no PDBQT output.")
        site = self._sites.load_record(request.binding_site_id)
        if site.receptor_id != request.receptor_id or site.stale:
            raise _failure("GNINA_BINDING_SITE_INVALID", "The binding site is stale or mismatched.")
        preparation = self._ligands.load_pdbqt_record(
            request.ligand_id, request.ligand_preparation_id
        )
        if preparation.artifact.ligand_id != request.ligand_id:
            raise _failure("GNINA_LIGAND_MISMATCH", "The prepared ligand does not match.")
        conformer = self._ligands.load_conformer_record(
            request.ligand_id, preparation.artifact.conformer_id
        )
        if conformer.artifact.ligand_id != request.ligand_id:
            raise _failure("GNINA_CONFORMER_MISMATCH", "The prepared conformer does not match.")
        inputs = (
            _verified_bytes(
                self._receptors.content_path(request.receptor_id, output.artifact_id),
                output.sha256,
                "receptor",
            ),
            _verified_bytes(
                self._ligands.pdbqt_content_path(request.ligand_id, request.ligand_preparation_id),
                preparation.artifact.sha256,
                "ligand",
            ),
            _verified_bytes(
                self._ligands.conformer_content_path(
                    request.ligand_id, preparation.artifact.conformer_id
                ),
                conformer.artifact.sha256,
                "conformer",
            ),
        )
        installation = probe_gnina()
        job_id = self._store.new_job_id()
        claim = self._claim(job_id, request)
        self._resources.validate(claim)
        directory = self._store.job_directory(job_id)
        receptor_path, ligand_path = directory / "receptor.pdbqt", directory / "ligand.pdbqt"
        output_path = directory / "raw_poses.pdbqt"
        command = [
            installation.executable,
            *build_gnina_arguments(
                receptor_path=receptor_path,
                ligand_path=ligand_path,
                output_path=output_path,
                box=site.box,
                parameters=request.parameters,
            ),
        ]
        record = GninaJobRecord(
            job_id=job_id,
            status=DockingJobStatus.QUEUED,
            phase=DockingJobPhase.QUEUED,
            created_at=datetime.now(UTC),
            request=request,
            tool=GninaToolIdentity(
                version=installation.version, sha256=installation.sha256, architecture="x86_64"
            ),
            box=site.box,
            receptor_output_artifact_id=output.artifact_id,
            receptor_sha256=output.sha256,
            ligand_sha256=preparation.artifact.sha256,
            conformer_sha256=conformer.artifact.sha256,
            command=command,
        )
        self._store.create_job(record)
        try:
            for name, content in zip(
                ("receptor.pdbqt", "ligand.pdbqt", "conformer.sdf"), inputs, strict=True
            ):
                self._store.write_artifact(job_id, name, content)
            event = threading.Event()
            with self._lock:
                self._events[job_id] = event
                self._executor.submit(self._run, job_id, installation, event)
        except Exception as error:
            with self._lock:
                self._events.pop(job_id, None)
            self._finish(
                job_id,
                DockingJobStatus.FAILED,
                failure=DockingFailure(
                    code="GNINA_START_FAILED",
                    message="GNINA job could not be queued.",
                    details={"exception": type(error).__name__},
                ),
            )
            raise
        return record

    @staticmethod
    def _claim(job_id: str, request: GninaDockingRequest) -> ResourceClaim:
        return ResourceClaim(
            workload="gnina_job",
            owner_id=job_id,
            cpu_threads=request.parameters.cpu_threads,
            gpu_slots=1 if request.parameters.compute == "cuda" else 0,
            memory_bytes=2 * 1024**3,
            disk_bytes=64 * 1024**2,
        )

    def get(self, job_id: str) -> GninaJobRecord:
        return self._store.load_job(job_id)

    def pose_content_path(self, job_id: str, artifact_id: str) -> Path:
        return self._store.pose_content_path(job_id, artifact_id)

    def cancel(self, job_id: str) -> DockingCancelResponse:
        with self._lock:
            record = self._store.load_job(job_id)
            if record.status in {
                DockingJobStatus.COMPLETED,
                DockingJobStatus.FAILED,
                DockingJobStatus.CANCELED,
            }:
                return DockingCancelResponse(job_id=job_id, status=record.status)
            event = self._events.get(job_id)
            if event is None:
                raise _failure("GNINA_JOB_NOT_ACTIVE", "This GNINA job is not active.")
            event.set()
            self._store.update_job(
                record.model_copy(update={"status": DockingJobStatus.CANCEL_REQUESTED})
            )
            return DockingCancelResponse(job_id=job_id, status=DockingJobStatus.CANCEL_REQUESTED)

    def has_active_work(self) -> bool:
        with self._lock:
            return bool(self._events)

    def shutdown(self) -> None:
        self._executor.shutdown(wait=True)

    def _finish(self, job_id: str, status: DockingJobStatus, **updates: object) -> None:
        with self._lock:
            record = self._store.load_job(job_id)
            self._store.update_job(
                record.model_copy(
                    update={
                        "status": status,
                        "phase": DockingJobPhase.COMPLETE,
                        "completed_at": datetime.now(UTC),
                        **updates,
                    }
                )
            )

    def _run(self, job_id: str, installation: GninaInstallation, event: threading.Event) -> None:
        resource: ResourceLease | None = None
        evidence: GninaExecutionEvidence | None = None
        acquired = False
        try:
            self._leases.acquire(WorkKind.GNINA_JOB, job_id)
            acquired = True
            record = self._store.load_job(job_id)
            resource = self._resources.acquire(
                self._claim(job_id, record.request), cancel_event=event
            )
            with self._lock:
                record = self._store.load_job(job_id)
                if event.is_set():
                    self._finish(job_id, DockingJobStatus.CANCELED)
                    return
                self._store.update_job(
                    record.model_copy(
                        update={
                            "status": DockingJobStatus.RUNNING,
                            "phase": DockingJobPhase.DOCKING,
                            "started_at": datetime.now(UTC),
                        }
                    )
                )
            require_current_inputs(
                record.request, binding_site_store=self._sites, ligand_store=self._ligands
            )
            directory = self._store.job_directory(job_id)
            receptor_path, ligand_path = directory / "receptor.pdbqt", directory / "ligand.pdbqt"
            _verified_bytes(receptor_path, record.receptor_sha256, "receptor")
            _verified_bytes(ligand_path, record.ligand_sha256, "ligand")
            conformer = _verified_bytes(
                directory / "conformer.sdf", record.conformer_sha256, "conformer"
            )
            output_path = directory / "raw_poses.pdbqt"
            observer = None
            if record.request.parameters.compute == "cuda":
                observer = GninaGpuObserver(Path(installation.executable), directory)
                observer.start()
            try:
                execution = execute_gnina(
                    installation=installation,
                    receptor_path=receptor_path,
                    ligand_path=ligand_path,
                    output_path=output_path,
                    box=record.box,
                    parameters=record.request.parameters,
                    cancel_event=event,
                )
            finally:
                if observer is not None:
                    observer.stop()
            evidence = GninaExecutionEvidence(
                command=execution.command,
                exit_code=execution.exit_code,
                stdout=execution.stdout,
                stderr=execution.stderr,
                timed_out=execution.timed_out,
                canceled=execution.canceled,
                gpu_process_observed=observer is not None and observer.observation is not None,
                gpu_observation=observer.observation if observer is not None else None,
            )
            self._store.write_artifact(job_id, "stdout.log", execution.stdout.encode("utf-8"))
            self._store.write_artifact(job_id, "stderr.log", execution.stderr.encode("utf-8"))
            if execution.canceled or event.is_set():
                self._finish(job_id, DockingJobStatus.CANCELED, execution=evidence)
                return
            if execution.timed_out or execution.exit_code != 0:
                raise _failure(
                    "GNINA_EXECUTION_FAILED",
                    "GNINA did not complete successfully.",
                    exit_code=execution.exit_code,
                    timed_out=execution.timed_out,
                )
            if record.request.parameters.compute == "cuda" and not evidence.gpu_process_observed:
                raise _failure(
                    "GNINA_GPU_EXECUTION_UNVERIFIED",
                    "GNINA completed, but its process was not observed on a GPU.",
                )
            _verified_bytes(receptor_path, record.receptor_sha256, "receptor")
            _verified_bytes(ligand_path, record.ligand_sha256, "ligand")
            _verified_bytes(directory / "conformer.sdf", record.conformer_sha256, "conformer")
            if not output_path.is_file():
                raise _failure("GNINA_OUTPUT_MISSING", "GNINA did not produce a pose file.")
            raw = output_path.read_bytes()
            parsed = parse_gnina_pdbqt(raw)
            for pose in parsed:
                require_matching_topology(pose, conformer)
            results = []
            for pose in parsed:
                name = f"pose_{pose.mode}.pdbqt"
                self._store.write_artifact(job_id, name, pose.pdbqt)
                results.append(
                    GninaPoseResult(
                        mode=pose.mode,
                        minimized_affinity_kcal_mol=pose.minimized_affinity_kcal_mol,
                        cnn_score=pose.cnn_score,
                        cnn_affinity=pose.cnn_affinity,
                        artifact=GninaPoseArtifact(
                            artifact_id=str(uuid4()),
                            mode=pose.mode,
                            filename=name,
                            sha256=sha256(pose.pdbqt).hexdigest(),
                            size_bytes=len(pose.pdbqt),
                        ),
                    )
                )
            with self._lock:
                if event.is_set():
                    self._finish(job_id, DockingJobStatus.CANCELED, execution=evidence)
                else:
                    self._finish(
                        job_id, DockingJobStatus.COMPLETED, execution=evidence, poses=results
                    )
        except ResourceRequestCanceled:
            self._finish(job_id, DockingJobStatus.CANCELED)
        except Exception as error:  # noqa: BLE001 - terminal records must survive worker failures
            code = (
                error.code if isinstance(error, AnkoraDomainError) else "GNINA_UNEXPECTED_FAILURE"
            )
            message = (
                error.message
                if isinstance(error, AnkoraDomainError)
                else "GNINA job failed unexpectedly."
            )
            details: dict[str, object] = (
                error.details
                if isinstance(error, AnkoraDomainError)
                else {"exception": type(error).__name__}
            )
            self._finish(
                job_id,
                DockingJobStatus.FAILED,
                execution=evidence,
                failure=DockingFailure(code=code, message=message, details=details),
            )
        finally:
            try:
                if resource is not None:
                    resource.release()
            finally:
                try:
                    if acquired:
                        self._leases.release(WorkKind.GNINA_JOB, job_id)
                finally:
                    with self._lock:
                        self._events.pop(job_id, None)
