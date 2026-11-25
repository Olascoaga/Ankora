"""Create-only service for declarative ProLIF pharmacophoric rules & Tanimoto IFP (M4).

Every rule set is validated against the prepared receptor's protonated PDB and
sealed by a canonical SHA-256 (`rule_set_identity_sha256`). Every pose evaluation
executes `ProLIF 2.2.1` directly against the deterministically materialized
coupled `PoseComplex` (`ADR-032 E8`) and never mutates parent pose bytes.
"""

from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

from ankora_backend.adapters.interactions.pharmacophore_rules import (
    evaluate_rule_set_against_contacts,
    extract_receptor_residues_from_pdb,
    fingerprint_from_contacts,
    fingerprint_from_explicit_bits,
    validate_residues_against_receptor,
)
from ankora_backend.adapters.interactions.prolif_adapter import ProlifInteractionAdapter
from ankora_backend.domain.errors import AnkoraDomainError
from ankora_backend.persistence.interaction_rules_store import (
    InteractionRuleEvaluationStore,
    InteractionRuleSetStore,
)
from ankora_backend.persistence.pose_interaction_store import PoseInteractionStore
from ankora_backend.persistence.receptor_store import ReceptorArtifactStore
from ankora_backend.schemas.interaction_rules import (
    CreateInteractionRuleSetRequest,
    EvaluateInteractionRulesRequest,
    IfpSourceKind,
    InteractionFingerprint,
    InteractionRuleEvaluationRecord,
    InteractionRuleSetRecord,
    compute_rule_set_identity_sha256,
)
from ankora_backend.schemas.pose_interactions import InteractionContact, InteractionProfile
from ankora_backend.schemas.provenance import ProvenanceEvent, ToolIdentity
from ankora_backend.schemas.receptors import ReceptorFlexMode, ReceptorOutputStage, ResidueLocator
from ankora_backend.schemas.v02_contracts import PoseComplexIdentity
from ankora_backend.services.pose_interactions import PoseInteractionService, VerifiedPoseInputs

_STAGE = "interaction_rules"


class InteractionRulesService:
    """Manage sealed pharmacophoric InteractionRuleSets and coupled pose evaluations."""

    def __init__(
        self,
        *,
        receptor_store: ReceptorArtifactStore,
        interaction_service: PoseInteractionService,
        interaction_store: PoseInteractionStore,
        rule_set_store: InteractionRuleSetStore,
        evaluation_store: InteractionRuleEvaluationStore,
        adapter: ProlifInteractionAdapter | None = None,
    ) -> None:
        self._receptors = receptor_store
        self._interactions = interaction_service
        self._interaction_store = interaction_store
        self._rule_sets = rule_set_store
        self._evaluations = evaluation_store
        self._adapter = adapter or ProlifInteractionAdapter()

    @classmethod
    def from_environment(cls, project_id: str | None = None) -> InteractionRulesService:
        return cls(
            receptor_store=ReceptorArtifactStore.from_environment(),
            interaction_service=PoseInteractionService.from_environment(),
            interaction_store=PoseInteractionStore.from_environment(project_id=project_id),
            rule_set_store=InteractionRuleSetStore.from_environment(project_id=project_id),
            evaluation_store=InteractionRuleEvaluationStore.from_environment(project_id=project_id),
        )

    def list_rule_sets(self, *, receptor_id: str | None = None) -> list[InteractionRuleSetRecord]:
        return self._rule_sets.list_all(receptor_id=receptor_id)

    def get_rule_set(self, rule_set_id: str) -> InteractionRuleSetRecord:
        return self._rule_sets.load(rule_set_id)

    def create_rule_set(
        self, request: CreateInteractionRuleSetRequest
    ) -> InteractionRuleSetRecord:
        receptor_record = self._receptors.load_record(request.receptor_id)
        analysis_output = next(
            (
                item
                for item in receptor_record.outputs
                if item.stage is ReceptorOutputStage.PROTONATED_PDB
            ),
            None,
        )
        if analysis_output is None:
            raise _failure(
                "INTERACTION_RULE_RECEPTOR_FORMAT_UNAVAILABLE",
                "This prepared receptor has no protonated PDB representation for rule validation.",
            )
        receptor_path = self._receptors.content_path(
            request.receptor_id, analysis_output.artifact_id
        )
        _verify_file_sha256(receptor_path, analysis_output.sha256, "analysis receptor")

        receptor_residues = extract_receptor_residues_from_pdb(receptor_path)
        all_locators: list[ResidueLocator] = [
            target.residue for clause in request.clauses for target in clause.targets
        ]
        if request.reference_bits is not None:
            all_locators.extend(bit.residue for bit in request.reference_bits)
        validate_residues_against_receptor(
            receptor_residues=receptor_residues,
            locators=all_locators,
        )

        input_artifacts: list[str] = [analysis_output.artifact_id]
        reference_ifp: InteractionFingerprint | None = None
        if request.reference_pose is not None:
            ref_verified = self._interactions.resolve_verified_pose_inputs(
                request.reference_pose.catalog_id,
                request.reference_pose.ligand_id,
                request.reference_pose.pose_artifact_id,
            )
            if ref_verified.analysis_output.sha256 != analysis_output.sha256:
                raise _failure(
                    "INTERACTION_RULE_RECEPTOR_MISMATCH",
                    "The selected reference pose belongs to a different prepared receptor.",
                    details={
                        "rule_set_receptor_sha256": analysis_output.sha256,
                        "reference_pose_receptor_sha256": ref_verified.analysis_output.sha256,
                    },
                )
            ref_contacts = self._run_prolif_on_coupled_pose(
                verified=ref_verified,
                profile=request.profile,
            )
            ref_pose_complex = _pose_complex_for(ref_verified)
            reference_ifp = fingerprint_from_contacts(
                ref_contacts,
                profile=request.profile,
                source_kind=IfpSourceKind.POSE_ANALYSIS,
                source_catalog_id=request.reference_pose.catalog_id,
                source_ligand_id=request.reference_pose.ligand_id,
                source_pose_artifact_id=request.reference_pose.pose_artifact_id,
                source_pose_complex_sha256=ref_pose_complex.complex_identity_sha256,
            )
            input_artifacts.append(ref_verified.resolved.pose.artifact_id)
        elif request.reference_bits is not None:
            reference_ifp = fingerprint_from_explicit_bits(
                request.reference_bits,
                profile=request.profile,
            )

        rule_set_identity = compute_rule_set_identity_sha256(
            receptor_protonated_sha256=analysis_output.sha256,
            profile=request.profile,
            clauses=request.clauses,
            reference_fingerprint_sha256=(
                reference_ifp.fingerprint_sha256 if reference_ifp is not None else None
            ),
            min_tanimoto_similarity=request.min_tanimoto_similarity,
        )

        created_at = datetime.now(UTC)
        rule_set_id = self._rule_sets.new_rule_set_id()
        detector = ToolIdentity(name="ProLIF", version=self._adapter.version())
        provenance = ProvenanceEvent(
            event_id=str(uuid4()),
            event_type="interaction_rule_set_created",
            timestamp=created_at,
            input_artifacts=input_artifacts,
            output_artifacts=[rule_set_id],
            tool=detector,
            parameters={
                "receptor_id": request.receptor_id,
                "receptor_protonated_sha256": analysis_output.sha256,
                "rule_set_identity_sha256": rule_set_identity,
                "clause_count": len(request.clauses),
                "has_reference_ifp": reference_ifp is not None,
                "min_tanimoto_similarity": request.min_tanimoto_similarity,
                "profile": request.profile.model_dump(mode="json"),
            },
        )
        record = InteractionRuleSetRecord(
            rule_set_id=rule_set_id,
            created_at=created_at,
            name=request.name,
            description=request.description,
            receptor_id=request.receptor_id,
            receptor_protonated_artifact_id=analysis_output.artifact_id,
            receptor_protonated_sha256=analysis_output.sha256,
            profile=request.profile,
            clauses=request.clauses,
            reference_ifp=reference_ifp,
            min_tanimoto_similarity=request.min_tanimoto_similarity,
            rule_set_identity_sha256=rule_set_identity,
            provenance=provenance,
        )
        self._rule_sets.create(record)
        return record

    def list_pose_evaluations(
        self, catalog_id: str, ligand_id: str, pose_artifact_id: str
    ) -> list[InteractionRuleEvaluationRecord]:
        self._interactions.resolve_verified_pose_inputs(catalog_id, ligand_id, pose_artifact_id)
        return self._evaluations.list_for_pose(catalog_id, ligand_id, pose_artifact_id)

    def evaluate_pose(
        self,
        catalog_id: str,
        ligand_id: str,
        pose_artifact_id: str,
        request: EvaluateInteractionRulesRequest,
    ) -> InteractionRuleEvaluationRecord:
        rule_set = self._rule_sets.load(request.rule_set_id)
        verified = self._interactions.resolve_verified_pose_inputs(
            catalog_id, ligand_id, pose_artifact_id
        )
        resolved = verified.resolved
        if verified.analysis_output.sha256 != rule_set.receptor_protonated_sha256:
            raise _failure(
                "INTERACTION_RULE_RECEPTOR_MISMATCH",
                "This InteractionRuleSet was sealed for a different prepared receptor.",
                details={
                    "rule_set_id": rule_set.rule_set_id,
                    "rule_set_receptor_sha256": rule_set.receptor_protonated_sha256,
                    "pose_receptor_sha256": verified.analysis_output.sha256,
                },
            )

        interaction_analysis_id: str | None = None
        if request.analysis_id is not None:
            existing = self._interaction_store.load(request.analysis_id)
            expected_coupled = (
                verified.materialized.sha256 if verified.materialized is not None else None
            )
            if (
                existing.catalog_id != catalog_id
                or existing.ligand_id != ligand_id
                or existing.pose.artifact_id != pose_artifact_id
                or existing.pose.sha256 != resolved.pose.sha256
                or existing.analysis_receptor_sha256 != verified.analysis_output.sha256
                or existing.materialized_coupled_receptor_sha256 != expected_coupled
                or existing.profile != rule_set.profile
            ):
                raise _failure(
                    "INTERACTION_RULE_ANALYSIS_MISMATCH",
                    "The supplied interaction analysis record does not match this pose complex "
                    "and rule-set ProLIF profile.",
                    details={"analysis_id": request.analysis_id},
                )
            contacts: list[InteractionContact] = list(existing.contacts)
            detector = existing.detector
            interaction_analysis_id = existing.analysis_id
        else:
            contacts = self._run_prolif_on_coupled_pose(
                verified=verified,
                profile=rule_set.profile,
            )
            detector = ToolIdentity(name="ProLIF", version=self._adapter.version())

        pose_complex = _pose_complex_for(verified)
        outcome = evaluate_rule_set_against_contacts(
            rule_set=rule_set,
            contacts=contacts,
            source_analysis_id=interaction_analysis_id,
            source_catalog_id=catalog_id,
            source_ligand_id=ligand_id,
            source_pose_artifact_id=pose_artifact_id,
            source_pose_complex_sha256=pose_complex.complex_identity_sha256,
        )

        created_at = datetime.now(UTC)
        evaluation_id = self._evaluations.new_evaluation_id()
        input_artifacts = [
            rule_set.rule_set_id,
            resolved.docking_receptor_artifact_id,
            verified.analysis_output.artifact_id,
            verified.preparation.artifact.preparation_id,
            verified.conformer.artifact.conformer_id,
            resolved.pose.artifact_id,
        ]
        if interaction_analysis_id is not None:
            input_artifacts.append(interaction_analysis_id)

        parameters: dict[str, object] = {
            "catalog_id": catalog_id,
            "rule_set_id": rule_set.rule_set_id,
            "rule_set_identity_sha256": rule_set.rule_set_identity_sha256,
            "pose_complex_mode": pose_complex.mode.value,
            "pose_complex_identity_sha256": pose_complex.complex_identity_sha256,
            "profile": rule_set.profile.model_dump(mode="json"),
        }
        if verified.materialized is not None:
            parameters["materialized_coupled_receptor_sha256"] = verified.materialized.sha256

        provenance = ProvenanceEvent(
            event_id=str(uuid4()),
            event_type="interaction_rules_evaluated",
            timestamp=created_at,
            input_artifacts=input_artifacts,
            output_artifacts=[evaluation_id],
            tool=detector,
            parameters=parameters,
            warnings=list(outcome.warnings),
        )
        record = InteractionRuleEvaluationRecord(
            evaluation_id=evaluation_id,
            created_at=created_at,
            rule_set_id=rule_set.rule_set_id,
            rule_set_name=rule_set.name,
            rule_set_identity_sha256=rule_set.rule_set_identity_sha256,
            catalog_id=catalog_id,
            engine_key=resolved.engine_key,
            record_id=resolved.record_id,
            engine_label=resolved.engine_label,
            ligand_id=ligand_id,
            ligand_preparation_id=resolved.ligand_preparation_id,
            conformer_id=verified.conformer.artifact.conformer_id,
            conformer_sha256=verified.conformer.artifact.sha256,
            receptor_id=resolved.receptor_id,
            docking_receptor_artifact_id=resolved.docking_receptor_artifact_id,
            docking_receptor_sha256=resolved.docking_receptor_sha256,
            analysis_receptor_artifact_id=verified.analysis_output.artifact_id,
            analysis_receptor_sha256=verified.analysis_output.sha256,
            materialized_coupled_receptor_sha256=(
                verified.materialized.sha256 if verified.materialized is not None else None
            ),
            pose=resolved.pose,
            pose_complex=pose_complex,
            interaction_analysis_id=interaction_analysis_id,
            detector=detector,
            profile=rule_set.profile,
            pose_ifp=outcome.pose_ifp,
            contacts=tuple(contacts),
            overall_status=outcome.overall_status,
            clause_results=outcome.clause_results,
            passed_clause_count=outcome.passed_clause_count,
            failed_clause_count=outcome.failed_clause_count,
            tanimoto=outcome.tanimoto,
            mutated_original_pose=False,
            warnings=outcome.warnings,
            provenance=provenance,
        )
        self._evaluations.create(record)
        return record

    def _run_prolif_on_coupled_pose(
        self,
        *,
        verified: VerifiedPoseInputs,
        profile: InteractionProfile,
    ) -> list[InteractionContact]:
        resolved = verified.resolved
        before_pose_sha = sha256(resolved.pose_path.read_bytes()).hexdigest()
        before_flex_sha = (
            sha256(resolved.pose_flex_path.read_bytes()).hexdigest()
            if resolved.pose_flex_path is not None and resolved.pose_flex_path.is_file()
            else None
        )

        if verified.materialized is not None:
            with TemporaryDirectory(prefix="ankora-coupled-prolif-rules-") as temp_dir:
                coupled_path = Path(temp_dir) / "coupled_receptor.pdb"
                coupled_path.write_text(
                    verified.materialized.pdb_text, encoding="utf-8", newline="\n"
                )
                contacts, _ = self._adapter.analyze(
                    pose_path=resolved.pose_path,
                    conformer_path=verified.conformer_path,
                    receptor_path=coupled_path,
                    profile=profile,
                )
        else:
            contacts, _ = self._adapter.analyze(
                pose_path=resolved.pose_path,
                conformer_path=verified.conformer_path,
                receptor_path=verified.receptor_path,
                profile=profile,
            )

        after_pose_sha = sha256(resolved.pose_path.read_bytes()).hexdigest()
        after_flex_sha = (
            sha256(resolved.pose_flex_path.read_bytes()).hexdigest()
            if resolved.pose_flex_path is not None and resolved.pose_flex_path.is_file()
            else None
        )
        if after_pose_sha != before_pose_sha or after_flex_sha != before_flex_sha:
            raise AnkoraDomainError(
                code="INTERACTION_RULE_IMMUTABILITY_VIOLATION",
                stage=_STAGE,
                message="Original pose artifact bytes changed unexpectedly during rule evaluation.",
                status_code=500,
            )
        return contacts


def _pose_complex_for(verified: VerifiedPoseInputs) -> PoseComplexIdentity:
    resolved = verified.resolved
    if verified.materialized is not None and resolved.pose.pose_flex_sidechains_sha256:
        return PoseComplexIdentity(
            mode=ReceptorFlexMode.SIDECHAIN_FLEX,
            receptor_rigid_sha256=resolved.docking_receptor_sha256,
            pose_flex_sidechains_sha256=resolved.pose.pose_flex_sidechains_sha256,
            ligand_pose_sha256=resolved.pose.sha256,
        )
    return PoseComplexIdentity(
        mode=ReceptorFlexMode.RIGID,
        receptor_rigid_sha256=resolved.docking_receptor_sha256,
        pose_flex_sidechains_sha256=None,
        ligand_pose_sha256=resolved.pose.sha256,
    )


def _verify_file_sha256(path: Path, expected: str, label: str) -> None:
    try:
        actual = sha256(path.read_bytes()).hexdigest()
    except OSError as error:
        raise _failure(
            "INTERACTION_RULE_ARTIFACT_MISSING",
            f"The recorded {label} file is no longer available on disk.",
        ) from error
    if actual != expected:
        raise _failure(
            "INTERACTION_RULE_ARTIFACT_MODIFIED",
            f"The {label} file on disk no longer matches its recorded SHA-256 hash.",
            details={"expected_sha256": expected, "actual_sha256": actual},
        )


def _failure(
    code: str, message: str, *, details: dict[str, object] | None = None
) -> AnkoraDomainError:
    return AnkoraDomainError(
        code=code,
        stage=_STAGE,
        message=message,
        status_code=422,
        details=details,
    )
