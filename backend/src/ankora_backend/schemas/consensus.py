"""Frozen contracts for ADR-030 rank-space consensus prioritization (PC-Q, PC-ECR, PC-L2)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from ankora_backend.schemas.calibration import PairedBootstrapDelta
from ankora_backend.schemas.provenance import ProvenanceEvent, ToolIdentity
from ankora_backend.schemas.receptors import ReceptorFlexSpec
from ankora_backend.schemas.rescoring import AutoDock4RescoreBackend
from ankora_backend.schemas.v02_contracts import (
    PoseComplexIdentity,
    RankingArtifact,
    ScoringFamily,
    ScoringFunctionId,
    canonical_contract_sha256,
)
from ankora_backend.schemas.warnings import StructuredWarning

type NonBlankStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
type Sha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
type SourceEngine = Literal["vina", "autodock4", "autodock_gpu", "gnina"]

#: Frozen exponential consensus decay parameter per ADR-030 §2.
FROZEN_ECR_TAU = 0.05

#: Default complete-linkage joint (ligand, flex) clustering diameter per ADR-030 E3 & ADR-032 E8.
DEFAULT_CLUSTER_RMSD_THRESHOLD_ANGSTROM = 2.0

_REFERENCE_PANEL_SCHEMA = "ankora.consensus.reference_panel.v1"


class ConsensusVariantId(StrEnum):
    """Published, fixed-weight PC-Q variant identifiers (ADR-030 §1.5)."""

    PCQ_CORE_V1 = "pcq-core-v1"
    PCQ_NEURAL_V1 = "pcq-neural-v1"


class PoseClusterMemberSummary(BaseModel):
    """One docked pose complex assigned to a complete-linkage pose cluster."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    pose_id: NonBlankStr
    source_engine: SourceEngine
    primary_rank_order: int = Field(ge=1)
    pose_complex: PoseComplexIdentity
    canonical_coordinate_sha256: Sha256


class PoseClusterSummary(BaseModel):
    """One complete-linkage (<= 2.0 A) joint (ligand, flex) cluster and its E3 medoid."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    cluster_id: NonBlankStr
    medoid_pose_id: NonBlankStr
    medoid_pose_complex: PoseComplexIdentity
    medoid_canonical_coordinate_sha256: Sha256
    member_count: int = Field(ge=1)
    max_intra_cluster_rmsd_angstrom: float = Field(ge=0.0, allow_inf_nan=False)
    best_primary_rank_order: int = Field(ge=1)
    search_engines_present: tuple[SourceEngine, ...] = Field(min_length=1)
    members: tuple[PoseClusterMemberSummary, ...] = Field(min_length=1)


class ReferencePanelEntry(BaseModel):
    """One retained medoid's verified native scores inside a hash-locked reference panel."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    parent_compound_id: NonBlankStr
    parent_state_id: NonBlankStr
    cluster_id: NonBlankStr
    pose_complex: PoseComplexIdentity
    scores_by_function: dict[ScoringFunctionId, float]

    @model_validator(mode="after")
    def validate_finite_scores(self) -> Self:
        if not self.scores_by_function:
            raise ValueError("ReferencePanelEntry requires at least one scoring function value")
        for fn, val in self.scores_by_function.items():
            if val != val or val in (float("inf"), float("-inf")):
                raise ValueError(f"Score for {fn.value} must be finite")
        return self


def compute_reference_panel_sha256(
    *,
    receptor_flex_spec: ReceptorFlexSpec,
    binding_box_sha256: str,
    autogrid_map_set_sha256: str | None,
    enabled_functions: Sequence[ScoringFunctionId],
    k_max: int,
    entries: Sequence[ReferencePanelEntry],
    executable_sha256s: Mapping[str, str],
) -> str:
    """Compute an order-invariant canonical SHA-256 for a ReferencePanelArtifact (E1)."""
    canonical_entries = sorted(
        (
            {
                "parent_compound_id": item.parent_compound_id,
                "parent_state_id": item.parent_state_id,
                "cluster_id": item.cluster_id,
                "pose_complex_sha256": item.pose_complex.complex_identity_sha256,
                "scores": {
                    fn.value: round(float(val), 10)
                    for fn, val in sorted(
                        item.scores_by_function.items(), key=lambda pair: pair[0].value
                    )
                },
            }
            for item in entries
        ),
        key=lambda row: (
            str(row["parent_compound_id"]),
            str(row["cluster_id"]),
            str(row["pose_complex_sha256"]),
        ),
    )
    payload: dict[str, object] = {
        "schema": _REFERENCE_PANEL_SCHEMA,
        "receptor_mode": receptor_flex_spec.mode.value,
        "receptor_rigid_sha256": receptor_flex_spec.receptor_rigid_sha256,
        "receptor_flex_sha256": receptor_flex_spec.receptor_flex_sha256,
        "flex_locators": list(receptor_flex_spec.canonical_flex_locators()),
        "binding_box_sha256": binding_box_sha256,
        "autogrid_map_set_sha256": autogrid_map_set_sha256,
        "enabled_functions": sorted(fn.value for fn in enabled_functions),
        "k_max": k_max,
        "executable_sha256s": dict(sorted(executable_sha256s.items())),
        "entries": canonical_entries,
    }
    return canonical_contract_sha256(payload)


class ReferencePanelArtifact(BaseModel):
    """Hash-locked empirical distribution against which parent-weighted quantiles are defined."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    panel_id: NonBlankStr
    created_at: datetime
    receptor_id: NonBlankStr
    binding_site_id: NonBlankStr
    receptor_flex_spec: ReceptorFlexSpec
    binding_box_sha256: Sha256
    autogrid_map_set_sha256: Sha256 | None = None
    enabled_functions: tuple[ScoringFunctionId, ...] = Field(min_length=2)
    tool_identities: tuple[ToolIdentity, ...] = ()
    executable_sha256s: dict[str, str] = Field(default_factory=dict)
    k_max: int = Field(ge=1)
    total_panel_parents: int = Field(ge=1)
    entries: tuple[ReferencePanelEntry, ...] = Field(min_length=1)
    reference_panel_sha256: Sha256

    @model_validator(mode="after")
    def validate_panel_integrity(self) -> Self:
        parent_ids = {entry.parent_compound_id for entry in self.entries}
        if len(parent_ids) != self.total_panel_parents:
            raise ValueError("total_panel_parents must equal the unique parent count in entries")
        enabled_set = set(self.enabled_functions)
        for entry in self.entries:
            if not enabled_set.issubset(entry.scores_by_function):
                raise ValueError(
                    f"Panel entry {entry.parent_compound_id}/{entry.cluster_id} is missing "
                    "one or more enabled scoring functions"
                )
        expected = compute_reference_panel_sha256(
            receptor_flex_spec=self.receptor_flex_spec,
            binding_box_sha256=self.binding_box_sha256,
            autogrid_map_set_sha256=self.autogrid_map_set_sha256,
            enabled_functions=self.enabled_functions,
            k_max=self.k_max,
            entries=self.entries,
            executable_sha256s=self.executable_sha256s,
        )
        if self.reference_panel_sha256 != expected:
            raise ValueError("reference_panel_sha256 must match canonical panel digest")
        return self


class MedoidConsensusBreakdown(BaseModel):
    """Per-medoid Pose-First breakdown (Q_icb, S_ic, D_ic, and separate-scale PC-ECR)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    cluster_id: NonBlankStr
    medoid_pose_id: NonBlankStr
    pose_complex: PoseComplexIdentity
    canonical_coordinate_sha256: Sha256
    member_count: int = Field(ge=1)
    max_intra_cluster_rmsd_angstrom: float = Field(ge=0.0, allow_inf_nan=False)
    search_engines_present: tuple[SourceEngine, ...] = Field(min_length=1)
    search_convergence_count: int = Field(ge=1)
    search_engine_count: int = Field(ge=1)
    native_scores: dict[ScoringFunctionId, float]
    function_quantiles: dict[ScoringFunctionId, float]
    block_quantiles: dict[ScoringFamily, float]
    pcq_score: float = Field(ge=0.0, le=100.0, allow_inf_nan=False)
    pcq_core_score: float = Field(ge=0.0, le=100.0, allow_inf_nan=False)
    inter_family_disagreement: float = Field(ge=0.0, le=100.0, allow_inf_nan=False)
    pc_ecr_score: float = Field(gt=0.0, allow_inf_nan=False)


class PcL2ModelArtifact(BaseModel):
    """Strictly convex non-negative L2 logistic model gated on locked Confirmation (ADR-030 §3)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    reference_panel_sha256: Sha256
    calibration_id: NonBlankStr
    split_identity_sha256: Sha256
    selection_identity_sha256: Sha256 | None = None
    confirmation_identity_sha256: Sha256 | None = None
    feature_functions: tuple[ScoringFunctionId, ...] = Field(min_length=2)
    l2_regularization: float = Field(gt=0.0, allow_inf_nan=False)
    solver_name: Literal["scipy.optimize.L-BFGS-B"] = "scipy.optimize.L-BFGS-B"
    intercept: float = Field(allow_inf_nan=False)
    weights: dict[ScoringFunctionId, float]
    converged: Literal[True] = True
    iterations: int = Field(ge=1)
    final_objective: float = Field(allow_inf_nan=False)
    promoted: bool
    promotion_verdict_text: NonBlankStr
    confirmation_deltas_vs_single_engines: dict[str, PairedBootstrapDelta] = Field(
        default_factory=dict
    )

    @model_validator(mode="after")
    def validate_non_negative_weights(self) -> Self:
        for fn in self.feature_functions:
            if fn not in self.weights:
                raise ValueError(f"PC-L2 weight missing for {fn.value}")
            if self.weights[fn] < -1e-12:
                raise ValueError(f"PC-L2 weight for {fn.value} must be non-negative")
        return self


class ConsensusParentDetail(BaseModel):
    """Auditable per-parent consensus summary linking molecule-second score to medoid c*."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    parent_compound_id: NonBlankStr
    parent_state_id: NonBlankStr
    tier: Literal["full_profile", "partial_or_unscored"]
    rotatable_bond_count: int | None = Field(default=None, ge=0)
    total_input_poses: int = Field(ge=0)
    total_clusters_found: int = Field(ge=0)
    retained_cluster_count: int = Field(ge=0)
    truncated_by_k_max: bool = False
    selected_medoid_cluster_id: str | None = None
    selected_pose_complex: PoseComplexIdentity | None = None
    pcq_score: float | None = Field(default=None, ge=0.0, le=100.0, allow_inf_nan=False)
    pcq_core_score: float | None = Field(default=None, ge=0.0, le=100.0, allow_inf_nan=False)
    pc_ecr_score: float | None = Field(default=None, gt=0.0, allow_inf_nan=False)
    pc_ecr_selected_cluster_id: str | None = None
    pc_l2_score: float | None = Field(default=None, allow_inf_nan=False)
    inter_family_disagreement: float | None = Field(
        default=None, ge=0.0, le=100.0, allow_inf_nan=False
    )
    search_convergence_count: int | None = Field(default=None, ge=0)
    search_engine_count: int | None = Field(default=None, ge=1)
    medoids: tuple[MedoidConsensusBreakdown, ...] = ()
    failure_or_exclusion_codes: tuple[NonBlankStr, ...] = ()


class ConsensusPoseScoreInput(BaseModel):
    """One pre-clustered medoid with verified same-geometry scores across functions.

    Used by direct structured consensus calls when scores were already computed via
    `PoseRescoringService` (`--score_only`) or recorded in deterministic tests.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    cluster_id: NonBlankStr
    medoid_pose_id: NonBlankStr
    pose_complex: PoseComplexIdentity
    canonical_coordinate_sha256: Sha256
    member_count: int = Field(default=1, ge=1)
    max_intra_cluster_rmsd_angstrom: float = Field(default=0.0, ge=0.0, allow_inf_nan=False)
    search_engines_present: tuple[SourceEngine, ...] = Field(min_length=1)
    scores_by_function: dict[ScoringFunctionId, float] = Field(default_factory=dict)
    missing_or_failed_codes: tuple[NonBlankStr, ...] = ()


class ConsensusParentInput(BaseModel):
    """Structured parent entry supplied to consensus scoring."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    parent_compound_id: NonBlankStr
    parent_state_id: NonBlankStr
    rotatable_bond_count: int | None = Field(default=None, ge=0)
    total_input_poses: int = Field(default=0, ge=0)
    total_clusters_found: int = Field(default=0, ge=0)
    truncated_by_k_max: bool = False
    medoids: tuple[ConsensusPoseScoreInput, ...] = ()
    failure_or_exclusion_codes: tuple[NonBlankStr, ...] = ()


class CreateStructuredConsensusRequest(BaseModel):
    """Run opt-in PC-Q + PC-ECR consensus over verified pose-first observations."""

    model_config = ConfigDict(extra="forbid")

    name: NonBlankStr
    variant_id: ConsensusVariantId
    receptor_id: NonBlankStr
    binding_site_id: NonBlankStr
    receptor_flex_spec: ReceptorFlexSpec
    binding_box_sha256: Sha256
    autogrid_map_set_sha256: Sha256
    enabled_functions: tuple[ScoringFunctionId, ...] = Field(min_length=2)
    k_max: int = Field(ge=1)
    rmsd_threshold_angstrom: float = Field(
        default=DEFAULT_CLUSTER_RMSD_THRESHOLD_ANGSTROM, gt=0.0, le=5.0, allow_inf_nan=False
    )
    search_engine_count: int = Field(ge=1)
    parents: tuple[ConsensusParentInput, ...] = Field(min_length=1)
    reference_panel_id: str | None = None
    tool_identities: tuple[ToolIdentity, ...] = ()
    executable_sha256s: dict[str, str] = Field(default_factory=dict)


class CampaignSourceRef(BaseModel):
    """Reference to one saved campaign/job contributing docked poses to consensus."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    catalog_id: NonBlankStr


class CreateCampaignConsensusRequest(BaseModel):
    """Run end-to-end Pose-First consensus directly over saved Ankora campaign(s) / job(s).

    Clusters all saved poses per parent compound at `<= rmsd_threshold_angstrom`
    in joint `(ligand, flex)` space (`E3`/`E8`), caps at explicit `k_max` (`E2`),
    cross-scores each retained medoid in place via `--score_only` (`E4`/`E7`),
    locks a `ReferencePanelArtifact` (`E1`, or reuses `reference_panel_id`), and
    emits immutable two-tier `PC-Q` + `PC-ECR` rankings (`E5`/`E6`).
    """

    model_config = ConfigDict(extra="forbid")

    name: NonBlankStr
    variant_id: ConsensusVariantId
    sources: tuple[CampaignSourceRef, ...] = Field(min_length=1)
    autogrid_map_set_id: NonBlankStr
    autodock4_backend: AutoDock4RescoreBackend = AutoDock4RescoreBackend.AUTODOCK4_EPDB
    include_vinardo: bool = True
    gnina_function: ScoringFunctionId = ScoringFunctionId.GNINA_CNN_VS
    k_max: int = Field(ge=1)
    rmsd_threshold_angstrom: float = Field(
        default=DEFAULT_CLUSTER_RMSD_THRESHOLD_ANGSTROM, gt=0.0, le=5.0, allow_inf_nan=False
    )
    reference_panel_id: str | None = None


class ConsensusRunRecord(BaseModel):
    """Immutable create-only ADR-030 consensus prioritization artifact."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    consensus_id: NonBlankStr
    created_at: datetime
    name: NonBlankStr
    variant_id: ConsensusVariantId
    k_max: int = Field(ge=1)
    rmsd_threshold_angstrom: float = Field(gt=0.0, le=5.0, allow_inf_nan=False)
    ecr_tau: float = Field(default=FROZEN_ECR_TAU, ge=FROZEN_ECR_TAU, le=FROZEN_ECR_TAU)
    receptor_id: NonBlankStr
    binding_site_id: NonBlankStr
    receptor_flex_spec: ReceptorFlexSpec
    binding_box_sha256: Sha256
    autogrid_map_set_sha256: Sha256
    source_catalog_ids: tuple[NonBlankStr, ...] = ()
    enabled_functions: tuple[ScoringFunctionId, ...] = Field(min_length=2)
    block_weights: dict[ScoringFamily, float]
    within_block_weights: dict[ScoringFunctionId, float]
    reference_panel: ReferencePanelArtifact
    ranking: RankingArtifact
    core_ranking: RankingArtifact | None = None
    ecr_ranking: RankingArtifact
    pc_l2_model: PcL2ModelArtifact | None = None
    pc_l2_ranking: RankingArtifact | None = None
    parent_details: tuple[ConsensusParentDetail, ...] = Field(min_length=1)
    warnings: tuple[StructuredWarning, ...] = ()
    provenance: ProvenanceEvent

    @model_validator(mode="after")
    def validate_variant_core_pair(self) -> Self:
        if self.variant_id is ConsensusVariantId.PCQ_NEURAL_V1 and self.core_ranking is None:
            raise ValueError(
                "pcq-neural-v1 consensus records must always record pcq-core-v1 alongside"
            )
        if self.ranking.reference_panel_sha256 != self.reference_panel.reference_panel_sha256:
            raise ValueError("ranking.reference_panel_sha256 must match reference_panel")
        if self.ecr_ranking.reference_panel_sha256 != self.reference_panel.reference_panel_sha256:
            raise ValueError("ecr_ranking.reference_panel_sha256 must match reference_panel")
        return self


class FitPcL2Request(BaseModel):
    """Fit a create-only strictly convex PC-L2 derivative against a Calibration run (ADR-030 §3)."""

    model_config = ConfigDict(extra="forbid")

    calibration_id: NonBlankStr
    l2_regularization: float = Field(default=1.0, gt=0.0, allow_inf_nan=False)


class ConsensusRunListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    runs: tuple[ConsensusRunRecord, ...] = ()
