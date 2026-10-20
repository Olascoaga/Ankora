"""Compute redocking metrics from poses an engine already produced (M7).

Nothing here docks anything. Redocking validation measures results that already
exist and carry their own provenance, which is what lets a verdict be attached
to a specific configuration rather than to a program in the abstract.
"""

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib import import_module
from pathlib import Path
from typing import Any

from ankora_backend.adapters.chemistry.redocking_rmsd import (
    DEFAULT_RMSD_THRESHOLD_ANGSTROM,
    PoseRmsd,
    in_place_rmsd,
    load_pose,
    load_reference,
)
from ankora_backend.domain.errors import AnkoraDomainError
from ankora_backend.persistence.artifact_store import StructureArtifactStore
from ankora_backend.persistence.autodock4_store import AutoDock4JobStore
from ankora_backend.persistence.autodock_gpu_store import AutoDockGpuJobStore
from ankora_backend.persistence.docking_store import DockingArtifactStore
from ankora_backend.persistence.ligand_store import LigandArtifactStore
from ankora_backend.persistence.receptor_store import ReceptorArtifactStore
from ankora_backend.persistence.redocking_store import RedockingValidationStore
from ankora_backend.schemas.ligands import LigandRecord, LigandSource
from ankora_backend.schemas.provenance import ProvenanceEvent, ToolIdentity
from ankora_backend.schemas.redocking import (
    RedockingMetrics,
    RedockingOutcome,
    RedockingPose,
    RedockingReferenceOption,
    RedockingReferencePage,
    RedockingRunRecord,
    RedockingValidationRequest,
)

_STAGE = "redocking_validation"

TOP_N = 5
"""`best_top5` is the documented measure; a scientist rarely inspects more."""


def summarize(
    measured: list[PoseRmsd],
    *,
    threshold_angstrom: float = DEFAULT_RMSD_THRESHOLD_ANGSTROM,
) -> tuple[RedockingMetrics, list[RedockingPose]]:
    """Turn per-pose RMSDs into the two verdicts and the numbers behind them.

    `measured` must be in the engine's own ranking order: rank 1 is the pose the
    engine put first, which is the only thing `ranking_success` can be about.
    """
    if not measured:
        raise AnkoraDomainError(
            code="REDOCKING_NO_POSES",
            stage=_STAGE,
            message="This docking result has no poses to validate.",
            status_code=422,
            details={},
        )
    if threshold_angstrom <= 0:
        raise AnkoraDomainError(
            code="REDOCKING_THRESHOLD_INVALID",
            stage=_STAGE,
            message="An RMSD threshold must be greater than zero.",
            status_code=422,
            details={"threshold_angstrom": threshold_angstrom},
        )

    ordered = sorted(measured, key=lambda pose: pose.rank)
    rmsds = [pose.rmsd_angstrom for pose in ordered]

    top1 = rmsds[0]
    best_top5 = min(rmsds[:TOP_N])
    best_overall = min(rmsds)
    recovered = [pose for pose in ordered if pose.recovered(threshold_angstrom)]
    first_recovering = recovered[0].rank if recovered else None

    # Two verdicts, never one. The reference case recovered the pose to 0.490 A
    # and still ranked a wrong pose first; a single pass/fail would have had to
    # lie about one of those.
    sampling_success = bool(recovered)
    ranking_success = top1 <= threshold_angstrom

    if ranking_success:
        outcome = RedockingOutcome.RECOVERED_AND_RANKED
    elif sampling_success:
        outcome = RedockingOutcome.RECOVERED_BUT_MISRANKED
    else:
        outcome = RedockingOutcome.NOT_RECOVERED

    metrics = RedockingMetrics(
        threshold_angstrom=threshold_angstrom,
        pose_count=len(ordered),
        top1_rmsd_angstrom=top1,
        best_top5_rmsd_angstrom=best_top5,
        best_overall_rmsd_angstrom=best_overall,
        first_recovering_rank=first_recovering,
        recovered_pose_count=len(recovered),
        sampling_success=sampling_success,
        ranking_success=ranking_success,
        outcome=outcome,
    )
    poses = [
        RedockingPose(
            run=pose.run,
            rank=pose.rank,
            binding_energy_kcal_mol=pose.binding_energy_kcal_mol,
            rmsd_angstrom=pose.rmsd_angstrom,
            recovered=pose.recovered(threshold_angstrom),
        )
        for pose in ordered
    ]
    return metrics, poses


@dataclass(frozen=True, slots=True)
class _ValidatedSource:
    """What a verdict needs from whichever engine produced the poses."""

    runs: list[Any]
    receptor_id: str
    binding_site_id: str
    engine_name: str
    engine_version: str
    bitwise_reproducible: bool
    warnings: list[Any]
    status: str


class RedockingValidationService:
    """Validate a docking result that already exists, and record the verdict."""

    def __init__(
        self,
        *,
        store: RedockingValidationStore,
        ligand_store: LigandArtifactStore,
        docking_store: DockingArtifactStore,
        autodock4_store: AutoDock4JobStore,
        autodock_gpu_store: AutoDockGpuJobStore,
        receptor_store: ReceptorArtifactStore,
        structure_store: StructureArtifactStore,
    ) -> None:
        self._store = store
        self._ligand_store = ligand_store
        self._docking_store = docking_store
        self._autodock4_store = autodock4_store
        self._autodock_gpu_store = autodock_gpu_store
        self._receptor_store = receptor_store
        self._structure_store = structure_store

    @classmethod
    def from_environment(cls) -> "RedockingValidationService":
        return cls(
            store=RedockingValidationStore.from_environment(),
            ligand_store=LigandArtifactStore.from_environment(),
            docking_store=DockingArtifactStore.from_environment(),
            autodock4_store=AutoDock4JobStore.from_environment(),
            autodock_gpu_store=AutoDockGpuJobStore.from_environment(),
            receptor_store=ReceptorArtifactStore.from_environment(),
            structure_store=StructureArtifactStore.from_environment(),
        )

    def references(
        self,
        source_kind: str,
        source_id: str,
        *,
        offset: int = 0,
        limit: int = 100,
    ) -> RedockingReferencePage:
        source = self._load_source(source_kind, source_id)
        self._require_complete(source)
        options = []
        for record in self._ligand_store.list_crystallographic_records():
            if not self._reference_matches_frame(record, source.receptor_id):
                continue
            artifact = record.artifact
            if artifact.source_structure_id is None or artifact.locator is None:
                continue
            options.append(
                RedockingReferenceOption(
                    ligand_id=artifact.ligand_id,
                    name=record.inspection.name,
                    source_structure_id=artifact.source_structure_id,
                    locator=artifact.locator,
                    heavy_atom_count=record.inspection.heavy_atom_count,
                    sha256=artifact.sha256,
                )
            )
        return RedockingReferencePage(
            references=options[offset : offset + limit],
            total=len(options),
            offset=offset,
            limit=limit,
        )

    def _reference_matches_frame(self, record: LigandRecord, receptor_id: str) -> bool:
        if (
            record.artifact.source is not LigandSource.CRYSTALLOGRAPHIC
            or record.artifact.source_structure_id is None
            or record.artifact.locator is None
            or not record.inspection.has_3d_coordinates
        ):
            return False
        receptor = self._receptor_store.load_record(receptor_id)
        if receptor.source_artifact_id == record.artifact.source_structure_id:
            return True
        # Separate imports of the exact same original share a frame. Do not
        # infer congruence from a PDB name, ligand name, or molecular similarity.
        expected = self._structure_store.load_record(receptor.source_artifact_id)
        observed = self._structure_store.load_record(record.artifact.source_structure_id)
        return expected.artifact.sha256 == observed.artifact.sha256

    @staticmethod
    def _require_complete(source: _ValidatedSource) -> None:
        if source.status != "completed":
            raise AnkoraDomainError(
                code="REDOCKING_SOURCE_NOT_COMPLETE",
                stage=_STAGE,
                status_code=409,
                message="Select a completed single-ligand docking result before validating.",
                details={"status": source.status},
            )

    @staticmethod
    def _verified_bytes(path: Path, digest: str, size: int) -> bytes:
        try:
            content = path.read_bytes()
        except OSError as error:
            raise AnkoraDomainError(
                code="REDOCKING_INPUT_UNAVAILABLE",
                stage=_STAGE,
                status_code=422,
                message="A preserved validation input is unavailable; no verdict was saved.",
                details={"filename": path.name},
            ) from error
        if len(content) != size or hashlib.sha256(content).hexdigest() != digest:
            raise AnkoraDomainError(
                code="REDOCKING_INPUT_HASH_MISMATCH",
                stage=_STAGE,
                status_code=409,
                message="A preserved reference or pose changed; no verdict was saved.",
                details={"filename": path.name, "expected_sha256": digest},
            )
        return content

    def validate(self, request: RedockingValidationRequest) -> RedockingRunRecord:
        source = self._load_source(request.source_kind, request.source_id)
        self._require_complete(source)
        if not source.runs:
            raise AnkoraDomainError(
                code="REDOCKING_NO_POSES",
                stage=_STAGE,
                message="This docking result has no poses to validate.",
                status_code=422,
                details={"source_id": request.source_id},
            )
        reference_record = self._ligand_store.load_record(request.reference_ligand_id)
        if not self._reference_matches_frame(reference_record, source.receptor_id):
            raise AnkoraDomainError(
                code="REDOCKING_REFERENCE_FRAME_MISMATCH",
                stage=_STAGE,
                status_code=422,
                message=(
                    "Choose an original crystallographic ligand from the same source "
                    "structure as this result's receptor. Prepared conformers are not references."
                ),
                details={
                    "reference_ligand_id": request.reference_ligand_id,
                    "receptor_id": source.receptor_id,
                },
            )
        self._verified_bytes(
            self._ligand_store.content_path(request.reference_ligand_id),
            reference_record.artifact.sha256,
            reference_record.artifact.size_bytes,
        )
        reference = load_reference(self._ligand_store.content_path(request.reference_ligand_id))

        # The engine's own order is the only order `ranking_success` can mean.
        ranked = (
            sorted(source.runs, key=lambda pose: pose.mode)
            if request.source_kind == "vina_job"
            else sorted(source.runs, key=lambda run: (run.cluster_rank, run.sub_rank))
        )
        measured: list[PoseRmsd] = []
        for rank, result in enumerate(ranked, start=1):
            path = self._pose_path(request, result.artifact.filename)
            document = self._verified_bytes(
                path,
                result.artifact.sha256,
                result.artifact.size_bytes,
            ).decode("utf-8", errors="replace")
            pose = load_pose(document, reference)
            measured.append(
                PoseRmsd(
                    run=(result.mode if request.source_kind == "vina_job" else result.run),
                    rank=rank,
                    binding_energy_kcal_mol=(
                        result.affinity_kcal_mol
                        if request.source_kind == "vina_job"
                        else result.binding_energy_kcal_mol
                    ),
                    rmsd_angstrom=in_place_rmsd(pose, reference),
                )
            )

        metrics, poses = summarize(measured, threshold_angstrom=request.threshold_angstrom)
        created_at = datetime.now(UTC)
        validation_id = self._store.new_validation_id()
        record = RedockingRunRecord(
            validation_id=validation_id,
            created_at=created_at,
            reference_case=request.reference_case,
            receptor_id=source.receptor_id,
            binding_site_id=source.binding_site_id,
            source_kind=request.source_kind,
            source_id=request.source_id,
            engine=source.engine_name,
            engine_version=source.engine_version,
            bitwise_reproducible=source.bitwise_reproducible,
            reference_ligand_id=request.reference_ligand_id,
            reference_sha256=reference_record.artifact.sha256,
            reference_heavy_atom_count=reference.GetNumAtoms(),
            metrics=metrics,
            poses=poses,
            warnings=list(source.warnings),
            provenance=ProvenanceEvent(
                event_id=f"redocking-{validation_id}",
                event_type="redocking_validated",
                timestamp=created_at,
                input_artifacts=[request.source_id, request.reference_ligand_id],
                output_artifacts=[validation_id],
                tool=ToolIdentity(name="RDKit", version=_rdkit_version()),
                parameters={
                    "threshold_angstrom": request.threshold_angstrom,
                    "rmsd": "symmetry-aware heavy-atom, computed in place",
                    "engine": source.engine_name,
                    "engine_version": source.engine_version,
                    "bitwise_reproducible": source.bitwise_reproducible,
                    "pose_sha256": [result.artifact.sha256 for result in ranked],
                    "reference_frame": "same immutable source structure (or byte-identical import)",
                },
                command=[],
            ),
        )
        self._store.create(record)
        return record

    def get(self, validation_id: str) -> RedockingRunRecord:
        return self._store.load(validation_id)

    def list_runs(self) -> list[RedockingRunRecord]:
        return self._store.list_runs()

    def _load_source(self, source_kind: str, source_id: str) -> _ValidatedSource:
        if source_kind == "vina_job":
            vina_job = self._docking_store.load_record(source_id)
            return _ValidatedSource(
                runs=list(vina_job.poses),
                receptor_id=vina_job.request.receptor_id,
                binding_site_id=vina_job.request.binding_site_id,
                engine_name=vina_job.tool.name,
                engine_version=vina_job.tool.version,
                bitwise_reproducible=True,
                warnings=list(vina_job.warnings),
                status=vina_job.status,
            )
        if source_kind == "autodock_gpu_job":
            gpu_job = self._autodock_gpu_store.load_job(source_id)
            return _ValidatedSource(
                runs=list(gpu_job.runs),
                receptor_id=gpu_job.receptor_id,
                binding_site_id=gpu_job.binding_site_id,
                engine_name=gpu_job.autodock_gpu.tool.name,
                engine_version=gpu_job.autodock_gpu.tool.version,
                bitwise_reproducible=gpu_job.bitwise_reproducible,
                warnings=list(gpu_job.warnings),
                status=gpu_job.status,
            )
        if source_kind != "autodock4_job":
            raise AnkoraDomainError(
                code="REDOCKING_SOURCE_UNSUPPORTED",
                stage=_STAGE,
                status_code=422,
                message="Validation accepts individual Vina, AutoDock4 CPU or GPU results.",
                details={"source_kind": source_kind},
            )
        cpu_job = self._autodock4_store.load_job(source_id)
        return _ValidatedSource(
            runs=list(cpu_job.runs),
            receptor_id=cpu_job.receptor_id,
            binding_site_id=cpu_job.binding_site_id,
            engine_name=cpu_job.autodock4.tool.name,
            engine_version=cpu_job.autodock4.tool.version,
            # AutoDock4 on the CPU repeats a seed bit-identically; measured.
            bitwise_reproducible=True,
            warnings=list(cpu_job.warnings),
            status=cpu_job.status,
        )

    def _pose_path(self, request: RedockingValidationRequest, filename: str) -> Path:
        if request.source_kind == "vina_job":
            return self._docking_store.output_path(request.source_id, filename)
        store: AutoDock4JobStore | AutoDockGpuJobStore = (
            self._autodock_gpu_store
            if request.source_kind == "autodock_gpu_job"
            else self._autodock4_store
        )
        return store.output_path(request.source_id, filename)


def _rdkit_version() -> str:
    return str(import_module("rdkit").__version__)
