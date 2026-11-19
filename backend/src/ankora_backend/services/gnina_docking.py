"""Single-ligand GNINA jobs. Scientific output is not published before validation."""

from __future__ import annotations

import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

from ankora_backend.adapters.engines.gnina import (
    GninaInstallation,
    GninaPdbqtPose,
    _linux_host,
    build_gnina_arguments,
    execute_gnina,
    execute_gnina_local_only,
    pair_gnina_flex_models,
    parse_gnina_local_only_pdbqt,
    parse_gnina_pdbqt,
    probe_gnina,
    require_matching_topology,
    resolve_cnn_model_identity,
)
from ankora_backend.domain.errors import AnkoraDomainError
from ankora_backend.execution.cancellable_subprocess import CancellableToolExecution
from ankora_backend.persistence.binding_site_store import BindingSiteArtifactStore
from ankora_backend.persistence.gnina_screening_store import GninaScreeningStore
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
    GninaCnnVsSource,
    GninaDockingRequest,
    GninaExecutionEvidence,
    GninaJobRecord,
    GninaLocalRefinementRecord,
    GninaLocalRefinementRequest,
    GninaPoseArtifact,
    GninaPoseResult,
    GninaToolIdentity,
    is_canonical_uuid,
)
from ankora_backend.schemas.receptors import (
    ReceptorFlexMode,
    ReceptorOutputArtifact,
    ReceptorOutputStage,
    ReceptorPreparationStatus,
    ResidueLocator,
)
from ankora_backend.schemas.v02_contracts import PoseComplexIdentity
from ankora_backend.schemas.warnings import StructuredWarning, WarningCode
from ankora_backend.schemas.work_recovery import WorkKind
from ankora_backend.services.execution_freshness import require_current_inputs
from ankora_backend.services.gnina_gpu_observer import GninaGpuObserver, single_gpu_identity
from ankora_backend.services.project_dependencies import ProjectDependencyService
from ankora_backend.services.resource_arbiter import (
    ResourceArbiter,
    ResourceClaim,
    ResourceLease,
    ResourceRequestCanceled,
    gnina_claim,
)
from ankora_backend.services.work_leases import WorkLeaseManager


def _failure(code: str, message: str, **details: object) -> AnkoraDomainError:
    return AnkoraDomainError(
        code=code, stage="gnina_docking", message=message, details=details, status_code=422
    )


def _verified_bytes(path: Path, expected: str | None, kind: str) -> bytes:
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


@dataclass(frozen=True, slots=True)
class GninaReceptorInputs:
    rigid: ReceptorOutputArtifact
    rigid_bytes: bytes
    flex: ReceptorOutputArtifact | None
    flex_bytes: bytes | None
    flex_residues: list[ResidueLocator]
    warnings: list[StructuredWarning]

    @property
    def mode(self) -> ReceptorFlexMode:
        return ReceptorFlexMode.SIDECHAIN_FLEX if self.flex else ReceptorFlexMode.RIGID


def resolve_gnina_receptor_inputs(
    store: ReceptorArtifactStore, receptor_id: str
) -> GninaReceptorInputs:
    """Bind GNINA to the exact prepared receptor or to both members of its Meeko split."""
    receptor = store.load_record(receptor_id)
    if receptor.status is not ReceptorPreparationStatus.DOCKING_READY:
        raise _failure("GNINA_RECEPTOR_NOT_READY", "The receptor is not docking ready.")
    outputs = {item.stage: item for item in receptor.outputs}
    spec = getattr(receptor, "flex_spec", None)
    if spec is None or spec.mode is ReceptorFlexMode.RIGID:
        rigid = outputs.get(ReceptorOutputStage.PDBQT)
        if rigid is None:
            raise _failure("GNINA_RECEPTOR_PDBQT_MISSING", "The receptor has no PDBQT output.")
        content = _verified_bytes(
            store.content_path(receptor_id, rigid.artifact_id),
            rigid.sha256,
            "receptor",
        )
        return GninaReceptorInputs(rigid, content, None, None, [], [])

    rigid = outputs.get(ReceptorOutputStage.PDBQT_RIGID)
    flex = outputs.get(ReceptorOutputStage.PDBQT_FLEX)
    if rigid is None or flex is None:
        raise _failure("GNINA_RECEPTOR_PDBQT_MISSING", "The prepared receptor split is incomplete.")
    if rigid.sha256 != spec.receptor_rigid_sha256 or flex.sha256 != spec.receptor_flex_sha256:
        raise _failure("GNINA_INPUT_CHANGED", "The receptor split does not match its flex spec.")
    return GninaReceptorInputs(
        rigid,
        _verified_bytes(
            store.content_path(receptor_id, rigid.artifact_id), rigid.sha256, "receptor"
        ),
        flex,
        _verified_bytes(
            store.content_path(receptor_id, flex.artifact_id),
            flex.sha256,
            "receptor_flex",
        ),
        list(spec.flex_residues),
        [
            warning
            for warning in getattr(receptor, "warnings", [])
            if warning.code == WarningCode.DOCKING_FLEXRES_DOF_HIGH
        ],
    )


def _pose_result(
    pose: GninaPdbqtPose,
    flex: bytes | None,
    *,
    receptor_sha256: str,
    pose_base_url: str,
    include_content_url: bool = False,
) -> GninaPoseResult:
    artifact_id = str(uuid4())
    url = f"{pose_base_url}/{artifact_id}"
    digest = sha256(pose.pdbqt).hexdigest()
    flex_digest = sha256(flex).hexdigest() if flex is not None else None
    complex_digest = None
    if flex_digest is not None:
        complex_digest = PoseComplexIdentity(
            mode=ReceptorFlexMode.SIDECHAIN_FLEX,
            receptor_rigid_sha256=receptor_sha256,
            pose_flex_sidechains_sha256=flex_digest,
            ligand_pose_sha256=digest,
        ).complex_identity_sha256
    cnn_vs = pose.cnn_vs
    cnn_vs_source: GninaCnnVsSource = "engine_emitted"
    if cnn_vs is None:
        cnn_vs = pose.cnn_score * pose.cnn_affinity
        cnn_vs_source = "derived_from_recorded_axes"
    return GninaPoseResult(
        mode=pose.mode,
        minimized_affinity_kcal_mol=pose.minimized_affinity_kcal_mol,
        cnn_score=pose.cnn_score,
        cnn_affinity=pose.cnn_affinity,
        cnn_vs=cnn_vs,
        cnn_vs_source=cnn_vs_source,
        cnn_affinity_variance=pose.cnn_affinity_variance,
        artifact=GninaPoseArtifact(
            artifact_id=artifact_id,
            mode=pose.mode,
            filename=f"pose_{pose.mode}.pdbqt",
            sha256=digest,
            size_bytes=len(pose.pdbqt),
            content_url=f"{url}/content" if include_content_url else None,
            flex_filename=f"pose_{pose.mode}_flex.pdbqt" if flex_digest is not None else None,
            pose_flex_sidechains_sha256=flex_digest,
            flex_content_url=f"{url}/flex" if flex_digest is not None else None,
            pose_complex_identity_sha256=complex_digest,
        ),
    )


def _run_with_evidence(
    installation: GninaInstallation,
    directory: Path,
    cuda_device: int | None,
    run: Callable[[], CancellableToolExecution],
) -> GninaExecutionEvidence:
    observer = None
    requested_gpu_uuid = None
    if cuda_device is not None:
        requested_gpu_uuid = single_gpu_identity(cuda_device)
        observer = GninaGpuObserver(Path(installation.executable), directory)
        observer.start()
    try:
        execution = run()
    finally:
        if observer is not None:
            observer.stop()
    return GninaExecutionEvidence(
        command=execution.command,
        exit_code=execution.exit_code,
        stdout=execution.stdout,
        stderr=execution.stderr,
        timed_out=execution.timed_out,
        canceled=execution.canceled,
        gpu_process_observed=observer is not None and observer.observation is not None,
        gpu_observation=observer.observation if observer is not None else None,
        requested_gpu_uuid=requested_gpu_uuid,
        observed_gpu_uuid=observer.gpu_uuid if observer is not None else None,
    )


def _require_execution_success(evidence: GninaExecutionEvidence, *, cuda: bool) -> None:
    if evidence.timed_out or evidence.canceled or evidence.exit_code != 0:
        raise _failure(
            "GNINA_EXECUTION_FAILED", "GNINA did not complete successfully.",
            exit_code=evidence.exit_code, timed_out=evidence.timed_out, canceled=evidence.canceled,
        )
    if cuda and not evidence.gpu_process_observed:
        raise _failure(
            "GNINA_GPU_EXECUTION_UNVERIFIED",
            "GNINA completed, but its process was not observed on a GPU.",
        )
    if cuda and evidence.observed_gpu_uuid != evidence.requested_gpu_uuid:
        raise _failure(
            "GNINA_GPU_DEVICE_MISMATCH", "The observed GPU differs from the selected device."
        )


def _pair_flex(
    poses: list[GninaPdbqtPose], raw_path: Path, template: bytes,
) -> tuple[bytes, ...]:
    if not raw_path.is_file():
        raise _failure("GNINA_OUTPUT_MISSING", "GNINA did not produce its flexible side-chain PDB.")
    return pair_gnina_flex_models(
        poses,
        gnina_flex_pdb_text=raw_path.read_bytes().decode("utf-8"),
        meeko_flex_template_pdbqt=template.decode("utf-8"),
    )


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
        screening_store: GninaScreeningStore | None = None,
    ) -> None:
        self._store = store
        self._receptors = receptors
        self._sites = sites
        self._ligands = ligands
        self._leases = leases
        self._resources = resources
        self._enable_experimental_cuda = enable_experimental_cuda
        self._screening_store = screening_store
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
            screening_store=GninaScreeningStore.from_environment(),
        )

    def start(
        self,
        request: GninaDockingRequest,
        *,
        screening_campaign_id: str | None = None,
    ) -> GninaJobRecord:
        """Create and launch one GNINA job.

        `screening_campaign_id` is an internal backend parameter, not part of
        the HTTP request model: it is keyword-only and defaults to `None`, so
        ordinary callers behave exactly as before. A screening orchestrator
        passes the campaign it is working for, and the id is written into the
        initial queued record before anything is submitted.
        """
        if not _linux_host():
            raise _failure("GNINA_LINUX_ONLY", "GNINA is available only in the Linux edition.")
        # CUDA remains gated until independent, process-specific GPU observation is wired in.
        if request.parameters.compute == "cuda" and not self._enable_experimental_cuda:
            raise _failure(
                "GNINA_CUDA_VERIFICATION_UNAVAILABLE",
                "GNINA CUDA execution is not enabled until GPU evidence is verified.",
            )
        # Refused before any input is read, so a malformed link never reaches a
        # durable record and no job is created under an unusable correlation.
        if screening_campaign_id is not None and not is_canonical_uuid(screening_campaign_id):
            raise _failure(
                "GNINA_SCREENING_CAMPAIGN_ID_INVALID",
                "The screening campaign identifier is not a canonical UUID.",
            )
        require_current_inputs(request, binding_site_store=self._sites, ligand_store=self._ligands)
        receptor = resolve_gnina_receptor_inputs(self._receptors, request.receptor_id)
        output = receptor.rigid
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
            receptor.rigid_bytes,
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
        cnn_model_identity = resolve_cnn_model_identity(
            request.parameters.cnn_model, binary_sha256=installation.sha256
        )
        job_id = self._store.new_job_id()
        claim = self._claim(job_id, request)
        self._resources.validate(claim)
        directory = self._store.job_directory(job_id)
        receptor_path, ligand_path = directory / "receptor.pdbqt", directory / "ligand.pdbqt"
        output_path = directory / "raw_poses.pdbqt"
        flex_path = directory / "receptor_flex.pdbqt" if receptor.flex is not None else None
        out_flex_path = directory / "raw_flex.pdb" if flex_path is not None else None
        command = [
            installation.executable,
            *build_gnina_arguments(
                receptor_path=receptor_path,
                ligand_path=ligand_path,
                output_path=output_path,
                box=site.box,
                parameters=request.parameters,
                flex_receptor_path=flex_path,
                out_flex_path=out_flex_path,
            ),
        ]
        record = GninaJobRecord(
            job_id=job_id,
            screening_campaign_id=screening_campaign_id,
            status=DockingJobStatus.QUEUED,
            phase=DockingJobPhase.QUEUED,
            created_at=datetime.now(UTC),
            request=request,
            tool=GninaToolIdentity(
                version=installation.version, sha256=installation.sha256, architecture="x86_64"
            ),
            cnn_model_identity=cnn_model_identity,
            box=site.box,
            receptor_output_artifact_id=output.artifact_id,
            receptor_sha256=output.sha256,
            receptor_flex_mode=receptor.mode,
            receptor_flex_output_artifact_id=receptor.flex.artifact_id if receptor.flex else None,
            receptor_flex_sha256=receptor.flex.sha256 if receptor.flex else None,
            flex_residues=receptor.flex_residues,
            warnings=receptor.warnings,
            ligand_sha256=preparation.artifact.sha256,
            conformer_sha256=conformer.artifact.sha256,
            command=command,
        )
        if screening_campaign_id is not None:
            if self._screening_store is None:
                raise _failure(
                    "GNINA_SCREENING_STORE_UNAVAILABLE",
                    "A screening job requires its project campaign store.",
                )
            self._screening_store.assert_can_start_job(record)
        self._store.create_job(record)
        try:
            for name, content in zip(
                ("receptor.pdbqt", "ligand.pdbqt", "conformer.sdf"), inputs, strict=True
            ):
                self._store.write_artifact(job_id, name, content)
            if receptor.flex_bytes is not None:
                self._store.write_artifact(job_id, "receptor_flex.pdbqt", receptor.flex_bytes)
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
        return gnina_claim(job_id, request.parameters)

    def get(self, job_id: str) -> GninaJobRecord:
        return self._store.load_job(job_id)

    def pose_content_path(self, job_id: str, artifact_id: str) -> Path:
        return self._store.pose_content_path(job_id, artifact_id)

    def pose_flex_content_path(self, job_id: str, artifact_id: str) -> Path | None:
        return self._store.pose_flex_content_path(job_id, artifact_id)

    def get_refinement(self, refinement_id: str) -> GninaLocalRefinementRecord:
        return self._store.load_refinement(refinement_id)

    def refinement_pose_content_path(self, refinement_id: str, artifact_id: str) -> Path:
        return self._store.refinement_pose_content_path(refinement_id, artifact_id)

    def refinement_pose_flex_content_path(
        self, refinement_id: str, artifact_id: str
    ) -> Path | None:
        return self._store.refinement_pose_flex_content_path(refinement_id, artifact_id)

    def refine_pose_local_only(
        self, request: GninaLocalRefinementRequest
    ) -> GninaLocalRefinementRecord:
        """Run explicit local minimization against the verified parent coordinates."""
        if not _linux_host():
            raise _failure("GNINA_LINUX_ONLY", "GNINA is available only in the Linux edition.")
        cuda = request.compute == "cuda"
        if cuda and not self._enable_experimental_cuda:
            raise _failure("GNINA_CUDA_VERIFICATION_UNAVAILABLE", "GNINA CUDA is not enabled.")
        parent = self._store.load_job(request.parent_job_id)
        if parent.status is not DockingJobStatus.COMPLETED:
            raise _failure("GNINA_REFINEMENT_PARENT_INCOMPLETE", "The parent job is not complete.")
        require_current_inputs(
            parent.request, binding_site_store=self._sites, ligand_store=self._ligands
        )
        ProjectDependencyService.for_project_root(self._sites.project_root).require_current(
            {parent.job_id, request.parent_pose_artifact_id}
        )
        pose = next(
            (
                item.artifact
                for item in parent.poses
                if item.artifact.artifact_id == request.parent_pose_artifact_id
            ),
            None,
        )
        if pose is None:
            raise _failure(
                "GNINA_REFINEMENT_POSE_NOT_FOUND",
                "The pose is absent from the parent job.",
            )
        receptor = _verified_bytes(
            self._store.output_path(parent.job_id, "receptor.pdbqt"),
            parent.receptor_sha256,
            "receptor",
        )
        conformer = _verified_bytes(
            self._store.output_path(parent.job_id, "conformer.sdf"),
            parent.conformer_sha256,
            "conformer",
        )
        ligand = _verified_bytes(
            self._store.pose_content_path(parent.job_id, pose.artifact_id),
            pose.sha256,
            "parent_pose",
        )
        # GNINA's ligand-input path takes a flat PDBQT and echoes input REMARK lines
        # verbatim into --out. Strip the model envelope and prior parent score REMARKs
        # on the staging copy so --local_only output records only its own fresh scores,
        # while retaining the complete original parent artifact untouched.
        stale_remarks = {
            b"minimizedAffinity",
            b"minimizedRMSD",
            b"CNNscore",
            b"CNNaffinity",
            b"CNN_VS",
            b"CNNaffinity_variance",
        }
        staged_lines: list[bytes] = []
        for line in ligand.splitlines(keepends=True):
            words = line.strip().split(maxsplit=2)
            if words and words[0] in {b"MODEL", b"ENDMDL"}:
                continue
            if len(words) >= 2 and words[0] == b"REMARK" and words[1] in stale_remarks:
                continue
            staged_lines.append(line)
        ligand = b"".join(staged_lines)
        flex = None
        if parent.receptor_flex_mode is ReceptorFlexMode.SIDECHAIN_FLEX:
            path = self._store.pose_flex_content_path(parent.job_id, pose.artifact_id)
            if path is None:
                raise _failure(
                    "GNINA_REFINEMENT_FLEX_POSE_MISSING",
                    "The parent pose has no flex output.",
                )
            flex = _verified_bytes(path, pose.pose_flex_sidechains_sha256, "parent_pose_flex")

        installation = probe_gnina()
        cnn_model = resolve_cnn_model_identity(request.cnn_model, binary_sha256=installation.sha256)
        refinement_id = self._store.new_refinement_id()
        event = threading.Event()
        claim = gnina_claim(refinement_id, request)
        self._resources.validate(claim)
        with self._lock:
            self._events[refinement_id] = event
        try:
            resource = self._resources.acquire(claim, cancel_event=event)
            try:
                directory = self._store.create_refinement_dir(refinement_id)
                receptor_path = self._store.write_refinement_artifact(
                    refinement_id, "receptor.pdbqt", receptor
                )
                ligand_path = self._store.write_refinement_artifact(
                    refinement_id, "ligand.pdbqt", ligand
                )
                flex_path = None
                out_flex_path = None
                if flex is not None and pose.flex_filename is not None:
                    # Use a staging name distinct from the derivative pose's output.
                    flex_path = self._store.write_refinement_artifact(
                        refinement_id, f"parent_{pose.flex_filename}", flex
                    )
                    out_flex_path = directory / "raw_local_flex.pdb"
                output_path = directory / "raw_local_pose.pdbqt"
                evidence = _run_with_evidence(
                    installation,
                    directory,
                    request.device_index if cuda else None,
                    lambda: execute_gnina_local_only(
                        installation=installation,
                        receptor_path=receptor_path,
                        ligand_path=ligand_path,
                        output_path=output_path,
                        box=parent.box,
                        parameters=request,
                        cancel_event=event,
                        flex_receptor_path=flex_path,
                        out_flex_path=out_flex_path,
                    ),
                )
                self._store.write_refinement_artifact(
                    refinement_id, "stdout.log", evidence.stdout.encode("utf-8")
                )
                self._store.write_refinement_artifact(
                    refinement_id, "stderr.log", evidence.stderr.encode("utf-8")
                )
                _require_execution_success(evidence, cuda=cuda)
            finally:
                resource.release()
            if not output_path.is_file():
                raise _failure(
                    "GNINA_OUTPUT_MISSING",
                    "GNINA local refinement produced no ligand pose.",
                )
            parsed = parse_gnina_local_only_pdbqt(output_path.read_bytes())
            require_matching_topology(parsed, conformer)
            moved = None
            if out_flex_path is not None and flex is not None:
                moved = _pair_flex([parsed], out_flex_path, flex)[0]
            result = _pose_result(
                parsed,
                moved,
                receptor_sha256=parent.receptor_sha256,
                pose_base_url=f"/docking/gnina/refinements/{refinement_id}/poses",
                include_content_url=True,
            )
            self._store.write_refinement_artifact(
                refinement_id, result.artifact.filename, parsed.pdbqt
            )
            if moved is not None and result.artifact.flex_filename is not None:
                self._store.write_refinement_artifact(
                    refinement_id, result.artifact.flex_filename, moved
                )
            record = GninaLocalRefinementRecord(
                refinement_id=refinement_id,
                created_at=datetime.now(UTC),
                parent_job_id=parent.job_id,
                parent_pose_artifact_id=pose.artifact_id,
                parent_pose_sha256=pose.sha256,
                parent_pose_flex_sha256=pose.pose_flex_sidechains_sha256,
                receptor_id=parent.request.receptor_id,
                binding_site_id=parent.request.binding_site_id,
                ligand_id=parent.request.ligand_id,
                ligand_preparation_id=parent.request.ligand_preparation_id,
                receptor_output_artifact_id=parent.receptor_output_artifact_id,
                receptor_sha256=parent.receptor_sha256,
                receptor_flex_mode=parent.receptor_flex_mode,
                flex_residues=parent.flex_residues,
                tool=GninaToolIdentity(version=installation.version, sha256=installation.sha256,
                                       architecture="x86_64"),
                cnn_model_identity=cnn_model,
                command=evidence.command,
                minimized_affinity_kcal_mol=result.minimized_affinity_kcal_mol,
                cnn_score=result.cnn_score,
                cnn_affinity=result.cnn_affinity,
                cnn_vs=result.cnn_vs,
                cnn_vs_source=result.cnn_vs_source,
                cnn_affinity_variance=result.cnn_affinity_variance,
                refined_pose=result.artifact,
                execution=evidence,
            )
            self._store.save_refinement(record)
            return record
        finally:
            with self._lock:
                self._events.pop(refinement_id, None)

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
            flex_path = None
            out_flex_path = None
            template = None
            if record.receptor_flex_mode is ReceptorFlexMode.SIDECHAIN_FLEX:
                flex_path = directory / "receptor_flex.pdbqt"
                out_flex_path = directory / "raw_flex.pdb"
                template = _verified_bytes(flex_path, record.receptor_flex_sha256, "receptor_flex")
            parameters = record.request.parameters
            evidence = _run_with_evidence(
                installation,
                directory,
                parameters.device_index if parameters.compute == "cuda" else None,
                lambda: execute_gnina(
                    installation=installation,
                    receptor_path=receptor_path,
                    ligand_path=ligand_path,
                    output_path=output_path,
                    box=record.box,
                    parameters=parameters,
                    cancel_event=event,
                    flex_receptor_path=flex_path,
                    out_flex_path=out_flex_path,
                ),
            )
            self._store.write_artifact(job_id, "stdout.log", evidence.stdout.encode("utf-8"))
            self._store.write_artifact(job_id, "stderr.log", evidence.stderr.encode("utf-8"))
            if evidence.canceled or event.is_set():
                self._finish(job_id, DockingJobStatus.CANCELED, execution=evidence)
                return
            _require_execution_success(evidence, cuda=parameters.compute == "cuda")
            if flex_path is not None:
                _verified_bytes(flex_path, record.receptor_flex_sha256, "receptor_flex")
            _verified_bytes(receptor_path, record.receptor_sha256, "receptor")
            _verified_bytes(ligand_path, record.ligand_sha256, "ligand")
            _verified_bytes(directory / "conformer.sdf", record.conformer_sha256, "conformer")
            if not output_path.is_file():
                raise _failure("GNINA_OUTPUT_MISSING", "GNINA did not produce a pose file.")
            raw = output_path.read_bytes()
            parsed = parse_gnina_pdbqt(raw)
            for pose in parsed:
                require_matching_topology(pose, conformer)
            moved: tuple[bytes | None, ...] = (None,) * len(parsed)
            if template is not None and out_flex_path is not None:
                moved = _pair_flex(parsed, out_flex_path, template)
            results = []
            for pose, flex in zip(parsed, moved, strict=True):
                result = _pose_result(
                    pose, flex, receptor_sha256=record.receptor_sha256,
                    pose_base_url=f"/docking/gnina/jobs/{job_id}/poses",
                )
                self._store.write_artifact(job_id, result.artifact.filename, pose.pdbqt)
                if flex is not None and result.artifact.flex_filename is not None:
                    self._store.write_artifact(job_id, result.artifact.flex_filename, flex)
                results.append(result)
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
