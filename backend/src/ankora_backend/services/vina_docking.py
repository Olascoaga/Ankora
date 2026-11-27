"""Validated, cancellable AutoDock Vina jobs for ligands and libraries."""

import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path

from ankora_backend.adapters.engines.vina_v02 import (
    VinaInstallation,
    build_vina_arguments,
    build_vina_local_only_arguments,
    execute_vina,
    execute_vina_local_only,
    parse_vina_local_only_output,
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
    VinaLocalRefinementRecord,
    VinaLocalRefinementRequest,
)
from ankora_backend.schemas.ligand_library_preparation import LigandPreparationStatus
from ankora_backend.schemas.provenance import ProvenanceEvent, ToolIdentity
from ankora_backend.schemas.receptors import (
    ReceptorFlexMode,
    ReceptorOutputArtifact,
    ReceptorOutputStage,
    ReceptorPreparationRecord,
    ReceptorPreparationStatus,
)
from ankora_backend.schemas.v02_contracts import PoseComplexIdentity
from ankora_backend.schemas.warnings import StructuredWarning, WarningCode
from ankora_backend.schemas.work_recovery import WorkKind
from ankora_backend.services.autodock_inputs import resolve_selected_chemical_state
from ankora_backend.services.execution_freshness import require_current_inputs
from ankora_backend.services.project_dependencies import ProjectDependencyService
from ankora_backend.services.resource_arbiter import (
    ResourceArbiter,
    ResourceLease,
    ResourceRequestCanceled,
    vina_claim,
)
from ankora_backend.services.work_leases import WorkLeaseManager

_LOG = logging.getLogger(__name__)
VINA_SEARCH_VOLUME_WARNING_ANGSTROM3 = 27_000.0


def _search_space_warnings(
    *, binding_site: BindingSiteRecord, exhaustiveness: int
) -> list[StructuredWarning]:
    box = binding_site.box
    volume = box.size_x * box.size_y * box.size_z
    if volume <= VINA_SEARCH_VOLUME_WARNING_ANGSTROM3:
        return []
    return [
        StructuredWarning(
            code=WarningCode.DOCKING_SEARCH_SPACE_LARGE,
            stage="vina_docking",
            message=(
                "The AutoDock Vina search-space volume exceeds 27,000 A^3; "
                "sampling may be insufficient at the selected exhaustiveness."
            ),
            details={
                "binding_site_id": binding_site.binding_site_id,
                "binding_site_source": binding_site.decisions.source.value,
                "volume_angstrom3": volume,
                "warning_threshold_angstrom3": (VINA_SEARCH_VOLUME_WARNING_ANGSTROM3),
                "volume_to_threshold_ratio": (volume / VINA_SEARCH_VOLUME_WARNING_ANGSTROM3),
                "selected_exhaustiveness": exhaustiveness,
                "parameters_changed_by_ankora": False,
            },
        )
    ]


@dataclass(frozen=True, slots=True)
class _DockingReceptor:
    record: ReceptorPreparationRecord
    rigid_output: ReceptorOutputArtifact
    rigid_path: Path
    flex_output: ReceptorOutputArtifact | None
    flex_path: Path | None

    @property
    def flex_mode(self) -> ReceptorFlexMode:
        spec = self.record.flex_spec
        return spec.mode if spec is not None else ReceptorFlexMode.RIGID


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
        lease_manager: WorkLeaseManager | None = None,
        resource_arbiter: ResourceArbiter | None = None,
    ) -> None:
        self._docking_store = docking_store
        self._receptor_store = receptor_store
        self._binding_site_store = binding_site_store
        self._ligand_store = ligand_store
        self._leases = lease_manager
        self._resources = resource_arbiter
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ankora-vina")
        self._cancel_events: dict[str, threading.Event] = {}
        self._active_batch_ids: set[str] = set()
        self._batch_start_lock = threading.Lock()
        self._lock = threading.RLock()

    @classmethod
    def from_environment(
        cls,
        *,
        lease_manager: WorkLeaseManager | None = None,
        resource_arbiter: ResourceArbiter | None = None,
    ) -> "VinaDockingService":
        return cls(
            docking_store=DockingArtifactStore.from_environment(),
            receptor_store=ReceptorArtifactStore.from_environment(),
            binding_site_store=BindingSiteArtifactStore.from_environment(),
            ligand_store=LigandArtifactStore.from_environment(),
            lease_manager=lease_manager,
            resource_arbiter=resource_arbiter,
        )

    def start(self, request: VinaDockingRequest) -> VinaDockingJobRecord:
        installation = probe_vina()
        docking_receptor, ligand_path, binding_site = self._validate_inputs(request)
        receptor_output = docking_receptor.rigid_output
        receptor_path = docking_receptor.rigid_path
        flex_output = docking_receptor.flex_output
        flex_path = docking_receptor.flex_path
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
                flex_receptor_path=flex_path,
            ),
        ]
        warnings = [
            *_search_space_warnings(
                binding_site=binding_site,
                exhaustiveness=request.parameters.exhaustiveness,
            ),
            *(
                warning
                for warning in docking_receptor.record.warnings
                if warning.code is WarningCode.DOCKING_FLEXRES_DOF_HIGH
            ),
        ]
        flex_spec = docking_receptor.record.flex_spec
        record = VinaDockingJobRecord(
            job_id=job_id,
            status=DockingJobStatus.QUEUED,
            phase=DockingJobPhase.QUEUED,
            created_at=datetime.now(UTC),
            request=request,
            tool=ToolIdentity(name="AutoDock Vina", version=installation.version),
            receptor_output_artifact_id=receptor_output.artifact_id,
            receptor_sha256=receptor_output.sha256,
            receptor_flex_mode=docking_receptor.flex_mode,
            receptor_flex_output_artifact_id=(
                flex_output.artifact_id if flex_output is not None else None
            ),
            receptor_flex_sha256=flex_output.sha256 if flex_output is not None else None,
            flex_residues=list(flex_spec.flex_residues) if flex_spec is not None else [],
            ligand_sha256=self._sha256_file(ligand_path),
            command=command,
            warnings=warnings,
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
            flex_path,
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
            requested = record.model_copy(update={"status": DockingJobStatus.CANCEL_REQUESTED})
            self._docking_store.update_record(requested)
        return DockingCancelResponse(job_id=job_id, status=DockingJobStatus.CANCEL_REQUESTED)

    def pose_content_path(self, job_id: str, artifact_id: str) -> Path:
        return self._docking_store.pose_content_path(job_id, artifact_id)

    def pose_flex_content_path(self, job_id: str, artifact_id: str) -> Path | None:
        return self._docking_store.pose_flex_content_path(job_id, artifact_id)

    def get_refinement(self, refinement_id: str) -> VinaLocalRefinementRecord:
        return self._docking_store.load_refinement_record(refinement_id)

    def refinement_pose_content_path(self, refinement_id: str, artifact_id: str) -> Path:
        return self._docking_store.refinement_pose_content_path(refinement_id, artifact_id)

    def refinement_pose_flex_content_path(
        self, refinement_id: str, artifact_id: str
    ) -> Path | None:
        return self._docking_store.refinement_pose_flex_content_path(refinement_id, artifact_id)

    def refine_pose_local_only(
        self, request: VinaLocalRefinementRequest
    ) -> VinaLocalRefinementRecord:
        """Create-only derivative `--local_only` pose refinement (ADR-005 / ADR-032 §1.5).

        Never mutates or overwrites the parent docking job or parent pose artifact.
        Authoritative energies are parsed from Vina stdout (ADR-032 Addendum A4).
        """
        installation = probe_vina()
        parent_job = self._docking_store.load_record(request.parent_job_id)
        if parent_job.status is not DockingJobStatus.COMPLETED:
            raise self._input_error(
                "VINA_REFINEMENT_PARENT_INCOMPLETE",
                "Local refinement requires a completed parent Vina docking job.",
                {"parent_job_id": request.parent_job_id, "status": parent_job.status.value},
            )
        parent_pose = next(
            (
                item
                for item in parent_job.poses
                if item.artifact.artifact_id == request.parent_pose_artifact_id
            ),
            None,
        )
        if parent_pose is None:
            raise self._input_error(
                "VINA_REFINEMENT_POSE_NOT_FOUND",
                "The requested pose does not belong to the parent Vina docking job.",
                {
                    "parent_job_id": request.parent_job_id,
                    "parent_pose_artifact_id": request.parent_pose_artifact_id,
                },
            )

        require_current_inputs(
            parent_job.request,
            binding_site_store=self._binding_site_store,
            ligand_store=self._ligand_store,
        )
        ProjectDependencyService.for_project_root(
            self._binding_site_store.project_root
        ).require_current({parent_job.job_id, request.parent_pose_artifact_id})

        docking_receptor, binding_site = self._validate_receptor_and_site(
            parent_job.request.receptor_id, parent_job.request.binding_site_id
        )
        if docking_receptor.rigid_output.sha256 != parent_job.receptor_sha256:
            raise self._input_error(
                "DOCKING_INPUT_HASH_MISMATCH",
                "The receptor no longer matches the parent docking job's recorded hash.",
                {
                    "expected_sha256": parent_job.receptor_sha256,
                    "actual_sha256": docking_receptor.rigid_output.sha256,
                },
            )

        parent_pose_path = self._docking_store.pose_content_path(
            parent_job.job_id, parent_pose.artifact.artifact_id
        )
        self._verify_hash(parent_pose_path, parent_pose.artifact.sha256, "parent_pose")

        parent_flex_path: Path | None = None
        parent_flex_sha256 = parent_pose.artifact.pose_flex_sidechains_sha256
        is_flex = parent_job.receptor_flex_mode is ReceptorFlexMode.SIDECHAIN_FLEX
        if is_flex:
            parent_flex_path = self._docking_store.pose_flex_content_path(
                parent_job.job_id, parent_pose.artifact.artifact_id
            )
            if parent_flex_path is None or parent_flex_sha256 is None:
                raise self._input_error(
                    "VINA_REFINEMENT_FLEX_POSE_MISSING",
                    "A sidechain_flex parent pose requires preserved moved side-chain coordinates.",
                    {"parent_pose_artifact_id": parent_pose.artifact.artifact_id},
                )
            self._verify_hash(parent_flex_path, parent_flex_sha256, "parent_pose_flex")

        refinement_id = self._docking_store.new_refinement_id()
        self._docking_store.create_refinement_dir(refinement_id)
        output_path = self._docking_store.refinement_output_path(
            refinement_id, "vina_local_only_out.pdbqt"
        )
        command = [
            installation.executable,
            *build_vina_local_only_arguments(
                receptor_path=docking_receptor.rigid_path,
                ligand_path=parent_pose_path,
                output_path=output_path,
                box=binding_site.box,
                cpu_threads=request.cpu_threads,
                seed=request.seed,
                scoring=request.scoring,
                flex_receptor_path=parent_flex_path,
            ),
        ]
        execution = execute_vina_local_only(
            installation=installation,
            receptor_path=docking_receptor.rigid_path,
            ligand_path=parent_pose_path,
            output_path=output_path,
            box=binding_site.box,
            cpu_threads=request.cpu_threads,
            seed=request.seed,
            scoring=request.scoring,
            timeout_minutes=request.timeout_minutes,
            cancel_event=threading.Event(),
            flex_receptor_path=parent_flex_path,
        )
        self._docking_store.write_refinement_text(refinement_id, "stdout.log", execution.stdout)
        self._docking_store.write_refinement_text(refinement_id, "stderr.log", execution.stderr)
        evidence = DockingExecutionEvidence(
            command=execution.command,
            exit_code=execution.exit_code,
            stdout=execution.stdout,
            stderr=execution.stderr,
            timed_out=execution.timed_out,
            canceled=execution.canceled,
        )
        if execution.exit_code != 0 or not output_path.is_file():
            raise AnkoraDomainError(
                code="VINA_LOCAL_REFINEMENT_FAILED",
                stage="vina_local_refinement",
                message="AutoDock Vina --local_only refinement did not complete successfully.",
                status_code=422,
                details={
                    "refinement_id": refinement_id,
                    "exit_code": execution.exit_code,
                    "command": command,
                    "stderr": execution.stderr,
                },
            )
        parsed = parse_vina_local_only_output(
            stdout=execution.stdout,
            output_pdbqt=output_path.read_bytes(),
            expect_flex_sidechains=is_flex,
        )
        pose_artifact_id = f"{refinement_id}-pose-1"
        self._docking_store.write_refinement_bytes(
            refinement_id, "pose_1.pdbqt", parsed.ligand_content
        )
        lig_sha256 = sha256(parsed.ligand_content).hexdigest()
        flex_filename: str | None = None
        flex_sha256: str | None = None
        flex_content_url: str | None = None
        if parsed.flex_sidechains_content is not None:
            flex_filename = "pose_1_flex.pdbqt"
            self._docking_store.write_refinement_bytes(
                refinement_id, flex_filename, parsed.flex_sidechains_content
            )
            flex_sha256 = sha256(parsed.flex_sidechains_content).hexdigest()
            flex_content_url = (
                f"/docking/refinements/{refinement_id}/poses/{pose_artifact_id}/flex"
            )
        complex_identity = PoseComplexIdentity(
            mode=parent_job.receptor_flex_mode,
            receptor_rigid_sha256=parent_job.receptor_sha256,
            pose_flex_sidechains_sha256=flex_sha256,
            ligand_pose_sha256=lig_sha256,
        )
        refined_pose = DockingPoseArtifact(
            artifact_id=pose_artifact_id,
            mode=1,
            filename="pose_1.pdbqt",
            format="pdbqt",
            sha256=lig_sha256,
            size_bytes=len(parsed.ligand_content),
            content_url=f"/docking/refinements/{refinement_id}/poses/{pose_artifact_id}/content",
            flex_filename=flex_filename,
            pose_flex_sidechains_sha256=flex_sha256,
            flex_content_url=flex_content_url,
            pose_complex_identity_sha256=complex_identity.complex_identity_sha256,
        )
        created_at = datetime.now(UTC)
        tool = ToolIdentity(name="AutoDock Vina", version=installation.version)
        provenance = ProvenanceEvent(
            event_id=f"vina-local-refinement-{refinement_id}",
            event_type="vina_local_refinement_completed",
            timestamp=created_at,
            input_artifacts=[
                parent_job.receptor_output_artifact_id,
                parent_job.request.binding_site_id,
                parent_pose.artifact.artifact_id,
            ],
            output_artifacts=[pose_artifact_id],
            tool=tool,
            parameters={
                **request.model_dump(mode="json"),
                "authoritative_energy_source": "vina_stdout",
                "stripped_nul_line_count": parsed.stripped_nul_line_count,
                "unbound_system_energy_kcal_mol": parsed.energy.unbound_system_energy_kcal_mol,
            },
            command=evidence.command,
        )
        record = VinaLocalRefinementRecord(
            refinement_id=refinement_id,
            created_at=created_at,
            parent_job_id=parent_job.job_id,
            parent_pose_artifact_id=parent_pose.artifact.artifact_id,
            parent_pose_sha256=parent_pose.artifact.sha256,
            parent_pose_flex_sha256=parent_flex_sha256,
            receptor_id=parent_job.request.receptor_id,
            binding_site_id=parent_job.request.binding_site_id,
            ligand_id=parent_job.request.ligand_id,
            ligand_preparation_id=parent_job.request.ligand_preparation_id,
            receptor_output_artifact_id=parent_job.receptor_output_artifact_id,
            receptor_sha256=parent_job.receptor_sha256,
            receptor_flex_mode=parent_job.receptor_flex_mode,
            flex_residues=list(parent_job.flex_residues),
            scoring=request.scoring,
            tool=tool,
            command=evidence.command,
            estimated_free_energy_kcal_mol=parsed.energy.estimated_free_energy_kcal_mol,
            intermolecular_kcal_mol=parsed.energy.intermolecular_kcal_mol,
            total_internal_kcal_mol=parsed.energy.total_internal_kcal_mol,
            torsional_free_energy_kcal_mol=parsed.energy.torsional_free_energy_kcal_mol,
            unbound_system_energy_kcal_mol=parsed.energy.unbound_system_energy_kcal_mol,
            refined_pose=refined_pose,
            execution=evidence,
            provenance=provenance,
        )
        self._docking_store.write_refinement_record(record)
        return record

    def start_batch(self, request: VinaBatchDockingRequest) -> VinaBatchDockingRecord:
        with self._batch_start_lock:
            existing = self._active_batch()
            if existing is not None:
                if existing.request == request:
                    return existing
                raise AnkoraDomainError(
                    code="DOCKING_BATCH_ALREADY_ACTIVE",
                    stage="vina_docking",
                    message=("Another virtual-screening docking campaign is already active."),
                    status_code=409,
                    details={"active_batch_id": existing.batch_id},
                )
            return self._create_batch(request)

    def _create_batch(self, request: VinaBatchDockingRequest) -> VinaBatchDockingRecord:
        require_current_inputs(
            request, binding_site_store=self._binding_site_store, ligand_store=self._ligand_store,
        )
        installation = probe_vina()
        docking_receptor, binding_site = self._validate_receptor_and_site(
            request.receptor_id, request.binding_site_id
        )
        receptor_output = docking_receptor.rigid_output
        receptor_path = docking_receptor.rigid_path
        flex_output = docking_receptor.flex_output
        flex_path = docking_receptor.flex_path
        filter_run = self._ligand_store.load_filter_run(request.library_id, request.filter_run_id)
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
        self._verify_hash(manifest_path, filter_run.artifact.sha256, "selection_manifest")
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
                            "The selected molecule is absent from its immutable library record."
                        ),
                        code="DOCKING_LIBRARY_LIGAND_MISSING",
                        completed_at=now,
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
                    stage="vina_docking",
                    code_prefix="DOCKING",
                )
            except AnkoraDomainError as error:
                entries.append(
                    self._unavailable_batch_entry(
                        ligand_id=ligand_id,
                        parent_compound_id=ligand_id,
                        source_index=source_index,
                        name=ligand.inspection.name,
                        message=error.message,
                        code=error.code,
                        completed_at=now,
                    )
                )
                continue
            preparation_initial_energy = (
                status.initial_energy_kcal_mol if status is not None else None
            )
            preparation_energy = status.final_energy_kcal_mol if status is not None else None
            if (
                status is None
                or status.status is not LigandPreparationStatus.PREPARED
                or status.pdbqt_preparation_id is None
            ):
                entries.append(
                    self._unavailable_batch_entry(
                        ligand_id=ligand_id,
                        parent_compound_id=state.parent_compound_id,
                        chemical_state_id=state.state_id,
                        chemical_state_formal_charge=state.inspection.formal_charge,
                        source_index=source_index,
                        name=state.inspection.name,
                        canonical_smiles=state.inspection.canonical_smiles,
                        molecular_weight_g_mol=(state.inspection.molecular_weight_g_mol),
                        preparation_initial_energy_kcal_mol=(preparation_initial_energy),
                        preparation_energy_kcal_mol=preparation_energy,
                        message=(
                            "This selected molecule has no completed Meeko PDBQT preparation."
                        ),
                        code="DOCKING_LIGAND_NOT_PREPARED",
                        completed_at=now,
                    )
                )
                continue
            if status.chemical_state_id != state.state_id:
                entries.append(
                    self._unavailable_batch_entry(
                        ligand_id=ligand_id,
                        parent_compound_id=state.parent_compound_id,
                        chemical_state_id=state.state_id,
                        chemical_state_formal_charge=state.inspection.formal_charge,
                        source_index=source_index,
                        name=state.inspection.name,
                        canonical_smiles=state.inspection.canonical_smiles,
                        molecular_weight_g_mol=(state.inspection.molecular_weight_g_mol),
                        preparation_initial_energy_kcal_mol=(preparation_initial_energy),
                        preparation_energy_kcal_mol=preparation_energy,
                        message=(
                            "The prepared PDBQT belongs to a different or unrecorded "
                            "chemical state than the applied selection manifest."
                        ),
                        code="DOCKING_PREPARATION_STATE_MISMATCH",
                        completed_at=now,
                    )
                )
                continue
            try:
                pdbqt = self._ligand_store.load_pdbqt_record(ligand_id, status.pdbqt_preparation_id)
                ligand_path = self._ligand_store.pdbqt_content_path(
                    ligand_id, status.pdbqt_preparation_id
                )
                self._verify_hash(ligand_path, pdbqt.artifact.sha256, "ligand")
                if preparation_initial_energy is None or preparation_energy is None:
                    conformer = self._ligand_store.load_conformer_record(
                        ligand_id, pdbqt.artifact.conformer_id
                    )
                    preparation_initial_energy = (
                        preparation_initial_energy
                        if preparation_initial_energy is not None
                        else conformer.minimization.initial_energy_kcal_mol
                    )
                    preparation_energy = (
                        preparation_energy
                        if preparation_energy is not None
                        else conformer.minimization.final_energy_kcal_mol
                    )
            except AnkoraDomainError as error:
                entries.append(
                    self._unavailable_batch_entry(
                        ligand_id=ligand_id,
                        parent_compound_id=state.parent_compound_id,
                        chemical_state_id=state.state_id,
                        chemical_state_formal_charge=state.inspection.formal_charge,
                        source_index=source_index,
                        name=state.inspection.name,
                        canonical_smiles=state.inspection.canonical_smiles,
                        molecular_weight_g_mol=(state.inspection.molecular_weight_g_mol),
                        preparation_initial_energy_kcal_mol=(preparation_initial_energy),
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
                    parent_compound_id=state.parent_compound_id,
                    chemical_state_id=state.state_id,
                    chemical_state_formal_charge=state.inspection.formal_charge,
                    source_index=source_index,
                    name=state.inspection.name,
                    canonical_smiles=state.inspection.canonical_smiles,
                    molecular_weight_g_mol=state.inspection.molecular_weight_g_mol,
                    preparation_initial_energy_kcal_mol=(preparation_initial_energy),
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
        threads_per_ligand = max(1, request.parameters.total_cpu_threads // worker_count)
        batch_id = self._docking_store.new_batch_id()
        execution_parameters = self._batch_execution_parameters(request, threads_per_ligand)
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
                    flex_receptor_path=flex_path,
                ),
            ]
            entries[index] = entry.model_copy(update={"command": command})
            work_items.append(_BatchWorkItem(ligand_id=entry.ligand_id, ligand_path=prepared_path))

        failed_count = sum(entry.status is DockingJobStatus.FAILED for entry in entries)
        flex_spec = docking_receptor.record.flex_spec
        batch_warnings = [
            *_search_space_warnings(
                binding_site=binding_site,
                exhaustiveness=request.parameters.exhaustiveness,
            ),
            *(
                warning
                for warning in docking_receptor.record.warnings
                if warning.code is WarningCode.DOCKING_FLEXRES_DOF_HIGH
            ),
        ]
        record = VinaBatchDockingRecord(
            batch_id=batch_id,
            status=DockingJobStatus.QUEUED,
            phase=DockingJobPhase.QUEUED,
            created_at=now,
            request=request,
            tool=ToolIdentity(name="AutoDock Vina", version=installation.version),
            receptor_output_artifact_id=receptor_output.artifact_id,
            receptor_sha256=receptor_output.sha256,
            receptor_flex_mode=docking_receptor.flex_mode,
            receptor_flex_output_artifact_id=(
                flex_output.artifact_id if flex_output is not None else None
            ),
            receptor_flex_sha256=flex_output.sha256 if flex_output is not None else None,
            flex_residues=list(flex_spec.flex_residues) if flex_spec is not None else [],
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
            warnings=batch_warnings,
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
            flex_path,
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

    def get_batch_progress(self, batch_id: str, *, after_revision: int) -> VinaBatchProgress:
        """Return only ligand rows changed after the caller's last revision."""

        summary = self._docking_store.load_batch_summary(batch_id)
        payload = {
            key: value for key, value in summary.items() if key in VinaBatchProgress.model_fields
        }
        payload["entries"] = self._docking_store.load_batch_entries_after_revision(
            batch_id, after_revision
        )
        return VinaBatchProgress.model_validate(payload)

    def cancel_batch(self, batch_id: str) -> DockingBatchCancelResponse:
        with self._lock:
            record = self._docking_store.load_batch_overview(batch_id)
            if record.status in {
                DockingJobStatus.CANCELED,
                DockingJobStatus.COMPLETED,
                DockingJobStatus.FAILED,
            }:
                return DockingBatchCancelResponse(batch_id=batch_id, status=record.status)
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
                ),
                changed_entries=[],
            )
        return DockingBatchCancelResponse(
            batch_id=batch_id, status=DockingJobStatus.CANCEL_REQUESTED
        )

    def batch_pose_content_path(self, batch_id: str, ligand_id: str, artifact_id: str) -> Path:
        return self._docking_store.batch_pose_content_path(batch_id, ligand_id, artifact_id)

    def batch_pose_flex_content_path(
        self, batch_id: str, ligand_id: str, artifact_id: str
    ) -> Path | None:
        return self._docking_store.batch_pose_flex_content_path(batch_id, ligand_id, artifact_id)

    def _run_batch(
        self,
        batch_id: str,
        installation: VinaInstallation,
        receptor_path: Path,
        flex_receptor_path: Path | None,
        box: BindingBox,
        work_items: list[_BatchWorkItem],
        parameters: VinaDockingParameters,
        cancel_event: threading.Event,
    ) -> None:
        resource_lease: ResourceLease | None = None
        lease_acquired = False
        try:
            if self._leases is not None:
                self._leases.acquire(WorkKind.VINA_BATCH, batch_id)
                lease_acquired = True
            record = self._docking_store.load_batch_overview(batch_id)
            if self._resources is not None:
                resource_lease = self._resources.acquire(
                    vina_claim(
                        batch_id,
                        cpu_threads=(record.worker_count * parameters.cpu_threads),
                        concurrent_processes=record.worker_count,
                        ligand_count=len(work_items),
                    ),
                    cancel_event=cancel_event,
                )
            if cancel_event.is_set():
                self._finish_batch(batch_id, canceled=True)
                return
            require_current_inputs(
                record.request,
                binding_site_store=self._binding_site_store,
                ligand_store=self._ligand_store,
            )
            with self._lock:
                record = self._docking_store.load_batch_overview(batch_id)
                self._docking_store.update_batch_record(
                    record.model_copy(
                        update={
                            "status": DockingJobStatus.RUNNING,
                            "phase": DockingJobPhase.DOCKING,
                            "started_at": datetime.now(UTC),
                            "revision": record.revision + 1,
                        }
                    ),
                    changed_entries=[],
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
                        flex_receptor_path,
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
        except ResourceRequestCanceled:
            self._finish_batch(batch_id, canceled=True)
        except AnkoraDomainError as error:
            self._fail_batch_safely(batch_id, error.code, error.message, dict(error.details))
        except Exception as error:  # pragma: no cover - final supervisor containment
            self._fail_batch_safely(
                batch_id,
                "VINA_BATCH_INTERNAL_ERROR",
                "Ankora could not complete the docking batch.",
                {"reason": str(error)},
            )
        finally:
            if resource_lease is not None:
                resource_lease.release()
            if lease_acquired and self._leases is not None:
                try:
                    self._leases.release(WorkKind.VINA_BATCH, batch_id)
                except OSError as error:
                    _LOG.warning(
                        "Failed releasing work lease for Vina batch %s: %s", batch_id, error
                    )
            self._forget(batch_id)

    def _fail_batch_safely(
        self, batch_id: str, code: str, message: str, details: dict[str, object]
    ) -> None:
        try:
            with self._lock:
                record = self._docking_store.load_batch_overview(batch_id)
                self._docking_store.update_batch_record(
                    record.model_copy(
                        update={
                            "status": DockingJobStatus.FAILED,
                            "phase": DockingJobPhase.COMPLETE,
                            "completed_at": datetime.now(UTC),
                            "revision": record.revision + 1,
                            "failure": DockingFailure(
                                code=code,
                                message=message,
                                details=details,
                            ),
                        }
                    ),
                    changed_entries=[],
                )
        except Exception:
            _LOG.exception(
                "Could not persist Vina batch %s failure (%s)", batch_id, code
            )

    def _run_batch_item(
        self,
        batch_id: str,
        installation: VinaInstallation,
        receptor_path: Path,
        flex_receptor_path: Path | None,
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
        evidence: DockingExecutionEvidence | None = None
        try:
            execution = execute_vina(
                installation=installation,
                receptor_path=receptor_path,
                ligand_path=item.ligand_path,
                output_path=output_path,
                box=box,
                parameters=parameters,
                cancel_event=cancel_event,
                flex_receptor_path=flex_receptor_path,
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
                evidence or current.execution,
                error.code,
                error.message,
                error.details,
            )
        except Exception as error:  # pragma: no cover - final worker containment
            current = self._batch_entry(batch_id, item.ligand_id)
            self._finish_batch_entry_failed(
                batch_id,
                current,
                evidence or current.execution,
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
        batch = self._docking_store.load_batch_overview(batch_id)
        is_flex = batch.receptor_flex_mode is ReceptorFlexMode.SIDECHAIN_FLEX
        parsed = parse_vina_poses(content, expect_flex_sidechains=is_flex)
        poses: list[DockingPoseResult] = []
        for pose in parsed:
            artifact_id = f"{batch_id}-{entry.ligand_id}-pose-{pose.mode}"
            filename = f"pose_{pose.mode}.pdbqt"
            self._docking_store.write_batch_bytes(batch_id, entry.ligand_id, filename, pose.content)
            lig_sha = sha256(pose.content).hexdigest()
            flex_filename: str | None = None
            flex_sha: str | None = None
            flex_url: str | None = None
            complex_sha: str | None = None
            if pose.flex_sidechains_content is not None:
                flex_filename = f"pose_{pose.mode}_flex.pdbqt"
                self._docking_store.write_batch_bytes(
                    batch_id, entry.ligand_id, flex_filename, pose.flex_sidechains_content
                )
                flex_sha = sha256(pose.flex_sidechains_content).hexdigest()
                flex_url = (
                    f"/docking/batches/{batch_id}/ligands/{entry.ligand_id}"
                    f"/poses/{artifact_id}/flex"
                )
                complex_sha = PoseComplexIdentity(
                    mode=ReceptorFlexMode.SIDECHAIN_FLEX,
                    receptor_rigid_sha256=batch.receptor_sha256,
                    pose_flex_sidechains_sha256=flex_sha,
                    ligand_pose_sha256=lig_sha,
                ).complex_identity_sha256
            artifact = DockingPoseArtifact(
                artifact_id=artifact_id,
                mode=pose.mode,
                filename=filename,
                format="pdbqt",
                sha256=lig_sha,
                size_bytes=len(pose.content),
                content_url=(
                    f"/docking/batches/{batch_id}/ligands/{entry.ligand_id}"
                    f"/poses/{artifact_id}/content"
                ),
                flex_filename=flex_filename,
                pose_flex_sidechains_sha256=flex_sha,
                flex_content_url=flex_url,
                pose_complex_identity_sha256=complex_sha,
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
            warnings=batch.warnings,
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
                    "failure": DockingFailure(code=code, message=message, details=details),
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
                    pose.artifact.artifact_id for entry in entries for pose in entry.poses
                ],
                tool=record.tool,
                parameters={
                    **record.request.parameters.model_dump(mode="json"),
                    "worker_count": record.worker_count,
                    "threads_per_ligand": record.threads_per_ligand,
                },
                warnings=record.warnings,
            )
            changed_entries = [entry for entry in entries if entry.revision == next_revision]
            self._docking_store.update_batch_record(
                record.model_copy(
                    update={
                        "status": (
                            DockingJobStatus.CANCELED if canceled else DockingJobStatus.COMPLETED
                        ),
                        "phase": DockingJobPhase.COMPLETE,
                        "completed_at": completed_at,
                        "entries": entries,
                        "provenance": provenance,
                        "revision": next_revision,
                        **counts,
                    }
                ),
                changed_entries=changed_entries,
            )

    def _update_batch_entry(self, batch_id: str, updated: VinaBatchLigandResult) -> None:
        with self._lock:
            if self._docking_store.load_batch_entry(batch_id, updated.ligand_id) is None:
                raise self._input_error(
                    "DOCKING_BATCH_LIGAND_NOT_FOUND",
                    "The docking batch no longer contains its selected ligand.",
                    {"batch_id": batch_id, "ligand_id": updated.ligand_id},
                )
            self._docking_store.update_batch_entry(batch_id, updated)

    def _batch_entry(self, batch_id: str, ligand_id: str) -> VinaBatchLigandResult:
        entry = self._docking_store.load_batch_entry(batch_id, ligand_id)
        if entry is None:
            raise self._input_error(
                "DOCKING_BATCH_LIGAND_NOT_FOUND",
                "The docking batch does not contain the requested ligand.",
                {"batch_id": batch_id, "ligand_id": ligand_id},
            )
        return entry

    @staticmethod
    def _batch_counts(entries: list[VinaBatchLigandResult]) -> dict[str, int]:
        succeeded = sum(entry.status is DockingJobStatus.COMPLETED for entry in entries)
        failed = sum(entry.status is DockingJobStatus.FAILED for entry in entries)
        canceled = sum(entry.status is DockingJobStatus.CANCELED for entry in entries)
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
        parent_compound_id: str | None = None,
        chemical_state_id: str | None = None,
        chemical_state_formal_charge: int | None = None,
        canonical_smiles: str | None = None,
        molecular_weight_g_mol: float | None = None,
        preparation_initial_energy_kcal_mol: float | None = None,
        preparation_energy_kcal_mol: float | None = None,
    ) -> VinaBatchLigandResult:
        return VinaBatchLigandResult(
            ligand_id=ligand_id,
            parent_compound_id=parent_compound_id,
            chemical_state_id=chemical_state_id,
            chemical_state_formal_charge=chemical_state_formal_charge,
            source_index=source_index,
            name=name,
            canonical_smiles=canonical_smiles,
            molecular_weight_g_mol=molecular_weight_g_mol,
            preparation_initial_energy_kcal_mol=(preparation_initial_energy_kcal_mol),
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
            sampling_protocol=parameters.sampling_protocol,
            scoring=parameters.scoring,
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

    def has_active_work(self) -> bool:
        with self._lock:
            return bool(self._cancel_events)

    def _validate_inputs(
        self, request: VinaDockingRequest
    ) -> tuple[_DockingReceptor, Path, BindingSiteRecord]:
        require_current_inputs(
            request, binding_site_store=self._binding_site_store, ligand_store=self._ligand_store,
        )
        docking_receptor, binding_site = self._validate_receptor_and_site(
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
        return docking_receptor, ligand_path, binding_site

    def _validate_receptor_and_site(
        self, receptor_id: str, binding_site_id: str
    ) -> tuple[_DockingReceptor, BindingSiteRecord]:
        receptor = self._receptor_store.load_record(receptor_id)
        if receptor.status is not ReceptorPreparationStatus.DOCKING_READY:
            raise self._input_error(
                "DOCKING_RECEPTOR_NOT_READY",
                "Docking requires a receptor in docking-ready status.",
                {"receptor_id": receptor_id, "status": receptor.status.value},
            )
        spec = receptor.flex_spec
        flex_output: ReceptorOutputArtifact | None = None
        flex_path: Path | None = None
        if spec is not None and spec.mode is ReceptorFlexMode.SIDECHAIN_FLEX:
            receptor_output = next(
                (
                    item
                    for item in receptor.outputs
                    if item.stage is ReceptorOutputStage.PDBQT_RIGID
                ),
                None,
            )
            if receptor_output is None:
                raise self._input_error(
                    "DOCKING_RECEPTOR_PDBQT_MISSING",
                    "The flexible receptor has no preserved rigid PDBQT split output.",
                    {"receptor_id": receptor_id},
                )
            if receptor_output.sha256 != spec.receptor_rigid_sha256:
                raise self._input_error(
                    "DOCKING_INPUT_HASH_MISMATCH",
                    "The rigid receptor split does not match its recorded flex spec hash.",
                    {
                        "expected_sha256": spec.receptor_rigid_sha256,
                        "actual_sha256": receptor_output.sha256,
                    },
                )
            flex_output = next(
                (item for item in receptor.outputs if item.stage is ReceptorOutputStage.PDBQT_FLEX),
                None,
            )
            if flex_output is None:
                raise self._input_error(
                    "DOCKING_RECEPTOR_PDBQT_MISSING",
                    "The flexible receptor has no preserved flexible PDBQT split output.",
                    {"receptor_id": receptor_id},
                )
            if flex_output.sha256 != spec.receptor_flex_sha256:
                raise self._input_error(
                    "DOCKING_INPUT_HASH_MISMATCH",
                    "The flexible side-chain split does not match its recorded flex spec hash.",
                    {
                        "expected_sha256": spec.receptor_flex_sha256,
                        "actual_sha256": flex_output.sha256,
                    },
                )
            flex_path = self._receptor_store.content_path(receptor_id, flex_output.artifact_id)
            self._verify_hash(flex_path, flex_output.sha256, "receptor_flex")
        else:
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
        receptor_path = self._receptor_store.content_path(receptor_id, receptor_output.artifact_id)
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
        return (
            _DockingReceptor(
                record=receptor,
                rigid_output=receptor_output,
                rigid_path=receptor_path,
                flex_output=flex_output,
                flex_path=flex_path,
            ),
            binding_site,
        )

    def _run(
        self,
        job_id: str,
        installation: VinaInstallation,
        receptor_path: Path,
        flex_receptor_path: Path | None,
        ligand_path: Path,
        output_path: Path,
        box: BindingBox,
        cancel_event: threading.Event,
    ) -> None:
        resource_lease: ResourceLease | None = None
        lease_acquired = False
        record: VinaDockingJobRecord | None = None
        try:
            if self._leases is not None:
                self._leases.acquire(WorkKind.VINA_JOB, job_id)
                lease_acquired = True
            record = self._docking_store.load_record(job_id)
            if self._resources is not None:
                resource_lease = self._resources.acquire(
                    vina_claim(
                        job_id,
                        cpu_threads=record.request.parameters.cpu_threads,
                        concurrent_processes=1,
                        ligand_count=1,
                    ),
                    cancel_event=cancel_event,
                )
            if cancel_event.is_set():
                self._finish_canceled(record, None)
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
            record = running
            require_current_inputs(
                record.request,
                binding_site_store=self._binding_site_store,
                ligand_store=self._ligand_store,
            )
            execution = execute_vina(
                installation=installation,
                receptor_path=receptor_path,
                ligand_path=ligand_path,
                output_path=output_path,
                box=box,
                parameters=record.request.parameters,
                cancel_event=cancel_event,
                flex_receptor_path=flex_receptor_path,
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
        except ResourceRequestCanceled:
            current = self._safe_load_record(job_id, fallback=record)
            if current is not None:
                self._finish_canceled(current, current.execution)
        except AnkoraDomainError as error:
            current = self._safe_load_record(job_id, fallback=record)
            if current is not None:
                self._finish_failed(
                    current,
                    current.execution,
                    error.code,
                    error.message,
                    dict(error.details),
                )
        except Exception as error:  # pragma: no cover - final worker containment
            current = self._safe_load_record(job_id, fallback=record)
            if current is not None:
                self._finish_failed(
                    current,
                    current.execution,
                    "VINA_JOB_INTERNAL_ERROR",
                    "Ankora could not complete the docking job.",
                    {"reason": str(error)},
                )
        finally:
            if resource_lease is not None:
                resource_lease.release()
            if lease_acquired and self._leases is not None:
                try:
                    self._leases.release(WorkKind.VINA_JOB, job_id)
                except OSError as error:
                    _LOG.warning("Failed releasing work lease for Vina job %s: %s", job_id, error)
            self._forget(job_id)

    def _safe_load_record(
        self, job_id: str, *, fallback: VinaDockingJobRecord | None
    ) -> VinaDockingJobRecord | None:
        try:
            return self._docking_store.load_record(job_id)
        except Exception:
            _LOG.exception("Could not reload Vina job %s during error recovery", job_id)
            return fallback

    def _finish_completed(
        self,
        record: VinaDockingJobRecord,
        content: bytes,
        evidence: DockingExecutionEvidence,
    ) -> None:
        is_flex = record.receptor_flex_mode is ReceptorFlexMode.SIDECHAIN_FLEX
        parsed = parse_vina_poses(content, expect_flex_sidechains=is_flex)
        poses: list[DockingPoseResult] = []
        for pose in parsed:
            artifact_id = f"{record.job_id}-pose-{pose.mode}"
            filename = f"pose_{pose.mode}.pdbqt"
            self._docking_store.write_bytes(record.job_id, filename, pose.content)
            lig_sha = sha256(pose.content).hexdigest()
            flex_filename: str | None = None
            flex_sha: str | None = None
            flex_url: str | None = None
            complex_sha: str | None = None
            if pose.flex_sidechains_content is not None:
                flex_filename = f"pose_{pose.mode}_flex.pdbqt"
                self._docking_store.write_bytes(
                    record.job_id, flex_filename, pose.flex_sidechains_content
                )
                flex_sha = sha256(pose.flex_sidechains_content).hexdigest()
                flex_url = f"/docking/jobs/{record.job_id}/poses/{artifact_id}/flex"
                complex_sha = PoseComplexIdentity(
                    mode=ReceptorFlexMode.SIDECHAIN_FLEX,
                    receptor_rigid_sha256=record.receptor_sha256,
                    pose_flex_sidechains_sha256=flex_sha,
                    ligand_pose_sha256=lig_sha,
                ).complex_identity_sha256
            artifact = DockingPoseArtifact(
                artifact_id=artifact_id,
                mode=pose.mode,
                filename=filename,
                format="pdbqt",
                sha256=lig_sha,
                size_bytes=len(pose.content),
                content_url=f"/docking/jobs/{record.job_id}/poses/{artifact_id}/content",
                flex_filename=flex_filename,
                pose_flex_sidechains_sha256=flex_sha,
                flex_content_url=flex_url,
                pose_complex_identity_sha256=complex_sha,
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
        input_artifacts = [
            record.receptor_output_artifact_id,
            *(
                [record.receptor_flex_output_artifact_id]
                if record.receptor_flex_output_artifact_id is not None
                else []
            ),
            record.request.binding_site_id,
            record.request.ligand_preparation_id,
        ]
        provenance = ProvenanceEvent(
            event_id=f"vina-docking-{record.job_id}",
            event_type="vina_docking_completed",
            timestamp=completed_at,
            input_artifacts=input_artifacts,
            output_artifacts=[pose.artifact.artifact_id for pose in poses],
            tool=record.tool,
            parameters=record.request.parameters.model_dump(mode="json"),
            warnings=record.warnings,
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
            record = self._docking_store.load_batch_overview(batch_id)
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
    def _input_error(code: str, message: str, details: dict[str, object]) -> AnkoraDomainError:
        return AnkoraDomainError(
            code=code,
            stage="docking_configuration",
            message=message,
            status_code=422,
            details=details,
        )
