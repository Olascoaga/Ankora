"""Create-only coupled pose-plausibility and dual MMFF94s strain service (M3)."""

from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

from ankora_backend.adapters.quality.conformational_strain import evaluate_dual_mmff94s_strain
from ankora_backend.adapters.quality.flex_sidechain_geometry import evaluate_flex_sidechain_geometry
from ankora_backend.adapters.quality.posebusters_adapter import (
    evaluate_posebusters_dock,
    load_receptor_mol_from_pdb,
    reconstruct_ligand_mol_from_pose,
)
from ankora_backend.domain.errors import AnkoraDomainError
from ankora_backend.persistence.pose_quality_store import PoseQualityStore
from ankora_backend.schemas.pose_quality import PoseQualityRecord, PoseQualityRequest
from ankora_backend.schemas.provenance import ProvenanceEvent, ToolIdentity
from ankora_backend.schemas.receptors import ReceptorFlexMode
from ankora_backend.schemas.v02_contracts import (
    DiagnosticStatus,
    PoseAssessment,
    PoseComplexIdentity,
    PoseDiagnosticCheck,
)
from ankora_backend.schemas.warnings import StructuredWarning, WarningCode
from ankora_backend.services.pose_interactions import PoseInteractionService

_STAGE = "pose_quality_assessment"


class PoseQualityService:
    """Assess physical plausibility and conformational strain of one exact saved pose.

    Every assessment is create-only and read-only on docking outputs: poses are
    annotated and warned, never silently deleted or rescored.
    """

    def __init__(
        self,
        *,
        interaction_service: PoseInteractionService,
        quality_store: PoseQualityStore,
    ) -> None:
        self._interactions = interaction_service
        self._store = quality_store

    @classmethod
    def from_environment(cls, project_id: str | None = None) -> PoseQualityService:
        return cls(
            interaction_service=PoseInteractionService.from_environment(),
            quality_store=PoseQualityStore.from_environment(project_id=project_id),
        )

    def list_assessments(
        self, catalog_id: str, ligand_id: str, pose_artifact_id: str
    ) -> list[PoseQualityRecord]:
        self._interactions.resolve_verified_pose_inputs(catalog_id, ligand_id, pose_artifact_id)
        return self._store.list_for_pose(catalog_id, ligand_id, pose_artifact_id)

    def assess(
        self,
        catalog_id: str,
        ligand_id: str,
        pose_artifact_id: str,
        request: PoseQualityRequest,
    ) -> PoseQualityRecord:
        verified = self._interactions.resolve_verified_pose_inputs(
            catalog_id, ligand_id, pose_artifact_id
        )
        resolved = verified.resolved
        before_pose_sha = sha256(resolved.pose_path.read_bytes()).hexdigest()
        before_flex_sha = (
            sha256(resolved.pose_flex_path.read_bytes()).hexdigest()
            if resolved.pose_flex_path is not None and resolved.pose_flex_path.is_file()
            else None
        )

        ligand_mol, canonical_smiles = reconstruct_ligand_mol_from_pose(
            pose_path=resolved.pose_path,
            conformer_path=verified.conformer_path,
        )

        flex_checks: tuple[PoseDiagnosticCheck, ...] = ()
        if verified.materialized is not None:
            crystal_pdb_text = verified.receptor_path.read_text(encoding="utf-8")
            with TemporaryDirectory(prefix="ankora-coupled-posebusters-") as temp_dir:
                coupled_path = Path(temp_dir) / "coupled_receptor.pdb"
                coupled_path.write_text(
                    verified.materialized.pdb_text, encoding="utf-8", newline="\n"
                )
                receptor_mol = load_receptor_mol_from_pdb(coupled_path)
            pb_eval = evaluate_posebusters_dock(
                ligand_mol=ligand_mol,
                receptor_mol=receptor_mol,
                ligand_canonical_smiles=canonical_smiles,
            )
            flex_residues = (
                verified.receptor_record.flex_spec.flex_residues
                if verified.receptor_record.flex_spec is not None
                else ()
            )
            flex_checks = evaluate_flex_sidechain_geometry(
                crystal_receptor_pdb=crystal_pdb_text,
                coupled_receptor_pdb=verified.materialized.pdb_text,
                flex_residues=flex_residues,
            )
        else:
            receptor_mol = load_receptor_mol_from_pdb(verified.receptor_path)
            pb_eval = evaluate_posebusters_dock(
                ligand_mol=ligand_mol,
                receptor_mol=receptor_mol,
                ligand_canonical_smiles=canonical_smiles,
            )

        all_checks: list[PoseDiagnosticCheck] = [*pb_eval.checks, *flex_checks]
        warnings: list[StructuredWarning] = []
        parent_state_id = resolved.ligand_preparation_id
        strain_diagnostic = None

        if request.include_strain:
            strain_result = evaluate_dual_mmff94s_strain(
                ligand_mol=ligand_mol,
                parent_state_id=parent_state_id,
                conformer_seed=request.conformer_seed,
                conformer_budget=request.conformer_budget,
                strain_flag_threshold_kcal_mol=request.strain_flag_threshold_kcal_mol,
            )
            strain_diagnostic = strain_result.diagnostic
            all_checks.append(strain_result.check)
            warnings.extend(strain_result.warnings)

        # Verify zero mutation on immutable parent pose artifacts.
        after_pose_sha = sha256(resolved.pose_path.read_bytes()).hexdigest()
        after_flex_sha = (
            sha256(resolved.pose_flex_path.read_bytes()).hexdigest()
            if resolved.pose_flex_path is not None and resolved.pose_flex_path.is_file()
            else None
        )
        if after_pose_sha != before_pose_sha or after_flex_sha != before_flex_sha:
            raise AnkoraDomainError(
                code="POSE_QUALITY_IMMUTABILITY_VIOLATION",
                stage=_STAGE,
                message="Original pose artifact bytes changed unexpectedly during assessment.",
                status_code=500,
            )

        if verified.materialized is not None and resolved.pose.pose_flex_sidechains_sha256:
            pose_complex = PoseComplexIdentity(
                mode=ReceptorFlexMode.SIDECHAIN_FLEX,
                receptor_rigid_sha256=resolved.docking_receptor_sha256,
                pose_flex_sidechains_sha256=resolved.pose.pose_flex_sidechains_sha256,
                ligand_pose_sha256=resolved.pose.sha256,
            )
        else:
            pose_complex = PoseComplexIdentity(
                mode=ReceptorFlexMode.RIGID,
                receptor_rigid_sha256=resolved.docking_receptor_sha256,
                pose_flex_sidechains_sha256=None,
                ligand_pose_sha256=resolved.pose.sha256,
            )

        passed_count = sum(1 for c in all_checks if c.status is DiagnosticStatus.PASS)
        failed_ids = [c.check_id for c in all_checks if c.status is DiagnosticStatus.FAIL]
        not_applicable_count = sum(
            1 for c in all_checks if c.status is DiagnosticStatus.NOT_APPLICABLE
        )
        not_evaluable_ids = [
            c.check_id for c in all_checks if c.status is DiagnosticStatus.NOT_EVALUABLE
        ]

        if failed_ids:
            overall_status = DiagnosticStatus.FAIL
            warnings.append(
                StructuredWarning(
                    code=WarningCode.POSE_QUALITY_CHECKS_FAILED,
                    stage=_STAGE,
                    message=(
                        f"{len(failed_ids)} physical plausibility check(s) failed for this pose "
                        "complex. Pose is retained and flagged, never silently deleted."
                    ),
                    details={"failed_check_ids": failed_ids},
                )
            )
        elif not_evaluable_ids:
            overall_status = DiagnosticStatus.NOT_EVALUABLE
            warnings.append(
                StructuredWarning(
                    code=WarningCode.POSE_QUALITY_NOT_EVALUABLE,
                    stage=_STAGE,
                    message=(
                        f"{len(not_evaluable_ids)} diagnostic check(s) were not evaluable "
                        "for this pose."
                    ),
                    details={"not_evaluable_check_ids": not_evaluable_ids},
                )
            )
        elif passed_count > 0:
            overall_status = DiagnosticStatus.PASS
        else:
            overall_status = DiagnosticStatus.NOT_APPLICABLE

        assessment = PoseAssessment(
            pose_complex=pose_complex,
            overall_status=overall_status,
            checks=tuple(all_checks),
            strain=strain_diagnostic,
            mutated_original_pose=False,
        )

        created_at = datetime.now(UTC)
        assessment_id = self._store.new_assessment_id()
        tool = ToolIdentity(name="PoseBusters", version=pb_eval.tool_version)
        parameters: dict[str, object] = {
            "catalog_id": catalog_id,
            "posebusters_config": "dock",
            "include_strain": request.include_strain,
            "conformer_seed": request.conformer_seed,
            "conformer_budget": request.conformer_budget,
            "strain_flag_threshold_kcal_mol": request.strain_flag_threshold_kcal_mol,
            "pose_complex_mode": pose_complex.mode.value,
            "pose_complex_identity_sha256": pose_complex.complex_identity_sha256,
        }
        if verified.materialized is not None:
            parameters["materialized_coupled_receptor_sha256"] = verified.materialized.sha256

        provenance = ProvenanceEvent(
            event_id=str(uuid4()),
            event_type="pose_quality_assessed",
            timestamp=created_at,
            input_artifacts=[
                resolved.docking_receptor_artifact_id,
                verified.analysis_output.artifact_id,
                verified.preparation.artifact.preparation_id,
                verified.conformer.artifact.conformer_id,
                resolved.pose.artifact_id,
            ],
            output_artifacts=[assessment_id],
            tool=tool,
            parameters=parameters,
            warnings=warnings,
        )

        record = PoseQualityRecord(
            assessment_id=assessment_id,
            created_at=created_at,
            catalog_id=catalog_id,
            engine_key=resolved.engine_key,
            record_id=resolved.record_id,
            engine_label=resolved.engine_label,
            ligand_id=ligand_id,
            ligand_preparation_id=resolved.ligand_preparation_id,
            conformer_id=verified.conformer.artifact.conformer_id,
            conformer_sha256=verified.conformer.artifact.sha256,
            parent_state_id=parent_state_id,
            receptor_id=resolved.receptor_id,
            docking_receptor_artifact_id=resolved.docking_receptor_artifact_id,
            docking_receptor_sha256=resolved.docking_receptor_sha256,
            analysis_receptor_artifact_id=verified.analysis_output.artifact_id,
            analysis_receptor_sha256=verified.analysis_output.sha256,
            materialized_coupled_receptor_sha256=(
                verified.materialized.sha256 if verified.materialized is not None else None
            ),
            pose=resolved.pose,
            posebusters_version=pb_eval.tool_version,
            assessment=assessment,
            passed_count=passed_count,
            failed_count=len(failed_ids),
            not_applicable_count=not_applicable_count,
            not_evaluable_count=len(not_evaluable_ids),
            warnings=warnings,
            provenance=provenance,
        )
        self._store.create(record)
        return record
