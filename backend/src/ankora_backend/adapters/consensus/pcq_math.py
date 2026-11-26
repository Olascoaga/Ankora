"""Exact ADR-030 mathematics: parent-weighted quantiles, PC-Q, D_ic, PC-ECR, and gated PC-L2.

Zero new dependencies: runs exclusively on already-locked `numpy==2.5.2` and
`scipy==1.18.0` (`scipy.optimize.minimize` with bounded `L-BFGS-B`).
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib import import_module
from math import exp, sqrt
from typing import Any
from uuid import uuid4

from ankora_backend.domain.errors import AnkoraDomainError
from ankora_backend.schemas.calibration import (
    INSUFFICIENT_EVIDENCE_TEXT,
    CalibrationRunRecord,
    PairedBootstrapDelta,
)
from ankora_backend.schemas.consensus import (
    FROZEN_ECR_TAU,
    ConsensusParentDetail,
    ConsensusParentInput,
    ConsensusVariantId,
    MedoidConsensusBreakdown,
    PcL2ModelArtifact,
    ReferencePanelArtifact,
    ReferencePanelEntry,
    compute_reference_panel_sha256,
)
from ankora_backend.schemas.provenance import ToolIdentity
from ankora_backend.schemas.receptors import ReceptorFlexSpec
from ankora_backend.schemas.screening_benchmark import (
    ScoreDirection,
    ScreeningBenchmarkObservation,
)
from ankora_backend.schemas.v02_contracts import (
    PoseComplexIdentity,
    RankingArtifact,
    RankingEntry,
    RankingMethod,
    ScoringFamily,
    ScoringFunctionId,
)
from ankora_backend.schemas.warnings import StructuredWarning, WarningCode
from ankora_backend.services.protocol_calibration import paired_parent_bootstrap_delta

_STAGE = "consensus_math"

#: Fixed orientation constants d_j (+1 higher is better, -1 lower is better).
ORIENTATION_BY_FUNCTION: dict[ScoringFunctionId, float] = {
    ScoringFunctionId.VINA: -1.0,
    ScoringFunctionId.VINARDO: -1.0,
    ScoringFunctionId.AUTODOCK4: -1.0,
    ScoringFunctionId.GNINA_MINIMIZED_AFFINITY: -1.0,
    ScoringFunctionId.GNINA_CNN_SCORE: 1.0,
    ScoringFunctionId.GNINA_CNN_AFFINITY: 1.0,
    ScoringFunctionId.GNINA_CNN_VS: 1.0,
}

FAMILY_BY_FUNCTION: dict[ScoringFunctionId, ScoringFamily] = {
    ScoringFunctionId.VINA: ScoringFamily.VINA_VINARDO,
    ScoringFunctionId.VINARDO: ScoringFamily.VINA_VINARDO,
    ScoringFunctionId.AUTODOCK4: ScoringFamily.AUTODOCK4,
    ScoringFunctionId.GNINA_CNN_SCORE: ScoringFamily.GNINA_NEURAL,
    ScoringFunctionId.GNINA_CNN_AFFINITY: ScoringFamily.GNINA_NEURAL,
    ScoringFunctionId.GNINA_CNN_VS: ScoringFamily.GNINA_NEURAL,
    ScoringFunctionId.GNINA_MINIMIZED_AFFINITY: ScoringFamily.GNINA_NEURAL,
}

#: Published, non-tunable block weights W_b per ADR-030 §1.5.
CORE_BLOCK_WEIGHTS: dict[ScoringFamily, float] = {
    ScoringFamily.VINA_VINARDO: 0.5,
    ScoringFamily.AUTODOCK4: 0.5,
}
NEURAL_BLOCK_WEIGHTS: dict[ScoringFamily, float] = {
    ScoringFamily.VINA_VINARDO: 1.0 / 3.0,
    ScoringFamily.AUTODOCK4: 1.0 / 3.0,
    ScoringFamily.GNINA_NEURAL: 1.0 / 3.0,
}

HIGH_DISAGREEMENT_WARNING_THRESHOLD = 25.0
#: Minimum reference-panel parent count before emitting ADR-033 §2.3 quantile-resolution warning.
SMALL_PANEL_WARNING_THRESHOLD = 50
_UPPER_TAIL_SATURATION_THRESHOLD = 99.9999


@dataclass(frozen=True)
class ConsensusComputationOutput:
    """Complete two-tier ADR-030 outputs ready for immutable persistence."""

    block_weights: dict[ScoringFamily, float]
    within_block_weights: dict[ScoringFunctionId, float]
    ranking: RankingArtifact
    core_ranking: RankingArtifact | None
    ecr_ranking: RankingArtifact
    parent_details: tuple[ConsensusParentDetail, ...]
    warnings: tuple[StructuredWarning, ...]


def resolve_variant_weights(
    *,
    variant_id: ConsensusVariantId,
    enabled_functions: Sequence[ScoringFunctionId],
) -> tuple[dict[ScoringFamily, float], dict[ScoringFunctionId, float]]:
    """Validate enabled functions against ADR-030 block membership and return fixed weights."""
    unique_fns = tuple(dict.fromkeys(enabled_functions))
    if len(unique_fns) != len(enabled_functions):
        raise _math_error(
            "CONSENSUS_DUPLICATE_FUNCTION",
            "Enabled scoring functions must be unique.",
        )
    by_family: dict[ScoringFamily, list[ScoringFunctionId]] = {}
    for fn in unique_fns:
        by_family.setdefault(FAMILY_BY_FUNCTION[fn], []).append(fn)

    block_weights = (
        dict(NEURAL_BLOCK_WEIGHTS)
        if variant_id is ConsensusVariantId.PCQ_NEURAL_V1
        else dict(CORE_BLOCK_WEIGHTS)
    )
    required_families = set(block_weights)
    present_families = set(by_family)
    if present_families != required_families:
        raise _math_error(
            "CONSENSUS_VARIANT_FAMILY_MISMATCH",
            f"Variant '{variant_id.value}' requires exact scoring families "
            f"{sorted(f.value for f in required_families)}, got "
            f"{sorted(f.value for f in present_families)}.",
            required_families=sorted(f.value for f in required_families),
            present_families=sorted(f.value for f in present_families),
        )

    within_block: dict[ScoringFunctionId, float] = {}
    for family, fns in by_family.items():
        if family is ScoringFamily.AUTODOCK4 and len(fns) != 1:
            raise _math_error(
                "CONSENSUS_AUTODOCK4_BLOCK_INVALID",
                "The autodock4 family block accepts exactly one scoring function (autodock4).",
            )
        weight = 1.0 / float(len(fns))
        for fn in fns:
            within_block[fn] = weight
    return block_weights, within_block


def build_reference_panel(
    *,
    receptor_id: str,
    binding_site_id: str,
    receptor_flex_spec: ReceptorFlexSpec,
    binding_box_sha256: str,
    autogrid_map_set_sha256: str | None,
    enabled_functions: Sequence[ScoringFunctionId],
    k_max: int,
    parents: Sequence[ConsensusParentInput],
    tool_identities: Sequence[ToolIdentity] = (),
    executable_sha256s: Mapping[str, str] | None = None,
    panel_id: str | None = None,
    created_at: datetime | None = None,
) -> ReferencePanelArtifact:
    """Build a hash-locked ReferencePanelArtifact (ADR-030 E1) from full-profile medoids."""
    enabled_set = set(enabled_functions)
    entries: list[ReferencePanelEntry] = []
    for parent in parents:
        for medoid in parent.medoids:
            if enabled_set.issubset(medoid.scores_by_function):
                entries.append(
                    ReferencePanelEntry(
                        parent_compound_id=parent.parent_compound_id,
                        parent_state_id=parent.parent_state_id,
                        cluster_id=medoid.cluster_id,
                        pose_complex=medoid.pose_complex,
                        scores_by_function={
                            fn: float(medoid.scores_by_function[fn]) for fn in enabled_functions
                        },
                    )
                )
    if not entries:
        raise _math_error(
            "CONSENSUS_REFERENCE_PANEL_EMPTY",
            "Cannot build a ReferencePanelArtifact without at least one full-profile medoid.",
        )

    unique_parents = {entry.parent_compound_id for entry in entries}
    exec_map = dict(executable_sha256s or {})
    panel_sha = compute_reference_panel_sha256(
        receptor_flex_spec=receptor_flex_spec,
        binding_box_sha256=binding_box_sha256,
        autogrid_map_set_sha256=autogrid_map_set_sha256,
        enabled_functions=enabled_functions,
        k_max=k_max,
        entries=entries,
        executable_sha256s=exec_map,
    )
    return ReferencePanelArtifact(
        panel_id=panel_id or str(uuid4()),
        created_at=created_at or datetime.now(UTC),
        receptor_id=receptor_id,
        binding_site_id=binding_site_id,
        receptor_flex_spec=receptor_flex_spec,
        binding_box_sha256=binding_box_sha256,
        autogrid_map_set_sha256=autogrid_map_set_sha256,
        enabled_functions=tuple(enabled_functions),
        tool_identities=tuple(tool_identities),
        executable_sha256s=exec_map,
        k_max=k_max,
        total_panel_parents=len(unique_parents),
        entries=tuple(entries),
        reference_panel_sha256=panel_sha,
    )


@dataclass(frozen=True, slots=True)
class _RankingRow:
    """One full-profile row pairing a ranking method's score with its OWN winning medoid."""

    detail: ConsensusParentDetail
    score_value: float
    pose_complex: PoseComplexIdentity
    percentile: float | None
    inter_family_disagreement: float
    search_convergence_count: int
    search_engine_count: int


@dataclass(frozen=True, slots=True)
class _CoreMedoidScore:
    """Core-family consensus metrics evaluated independently of optional neural scoring."""

    cluster_id: str
    pose_complex: PoseComplexIdentity
    canonical_coordinate_sha256: str
    pcq_core_score: float
    inter_family_disagreement: float
    search_convergence_count: int
    search_engine_count: int


def _scores_tied(score_a: float, score_b: float) -> bool:
    """Scale-invariant score equality check (safe across [0, 100] and 1e-15 PC-ECR scales)."""
    return math.isclose(score_a, score_b, rel_tol=1e-12, abs_tol=0.0)


def _select_best_medoid[T](
    items: Sequence[T],
    score_fn: Callable[[T], float],
    hash_fn: Callable[[T], str],
) -> T:
    """Select highest-scoring medoid with scale-invariant E3 coordinate-hash tie-breaking."""
    best_score = max(score_fn(item) for item in items)
    tied = [item for item in items if _scores_tied(score_fn(item), best_score)]
    return min(tied, key=hash_fn)


def parent_weighted_midrank_quantile(
    *,
    panel: ReferencePanelArtifact,
    scoring_function: ScoringFunctionId,
    raw_score: float,
) -> float:
    """Evaluate exact ADR-030 §1.3 parent-weighted midrank empirical CDF q_j(d_j * s) in [0, 1]."""
    numeric_raw = float(raw_score)
    if not math.isfinite(numeric_raw):
        raise _math_error(
            "CONSENSUS_NON_FINITE_SCORE",
            f"Non-finite score for {scoring_function.value}: {raw_score!r}.",
            scoring_function=scoring_function.value,
        )
    d_j = ORIENTATION_BY_FUNCTION[scoring_function]
    x = d_j * numeric_raw

    by_parent: dict[str, list[float]] = {}
    for entry in panel.entries:
        panel_val = float(entry.scores_by_function[scoring_function])
        if not math.isfinite(panel_val):
            raise _math_error(
                "CONSENSUS_NON_FINITE_SCORE",
                f"Reference panel contains non-finite score for {scoring_function.value}.",
                scoring_function=scoring_function.value,
                parent_compound_id=entry.parent_compound_id,
            )
        by_parent.setdefault(entry.parent_compound_id, []).append(d_j * panel_val)

    n_r = float(len(by_parent))
    total = 0.0
    for values in by_parent.values():
        k_l = float(len(values))
        parent_sum = 0.0
        for val in values:
            if abs(val - x) <= 1e-12:
                parent_sum += 0.5
            elif val < x:
                parent_sum += 1.0
        total += parent_sum / k_l
    return min(1.0, max(0.0, total / n_r))


def compute_pc_ecr_from_block_quantiles(
    *,
    block_quantiles: Mapping[ScoringFamily, float],
    block_weights: Mapping[ScoringFamily, float],
    n_panel_parents: int,
    tau: float = FROZEN_ECR_TAU,
) -> float:
    """Compute exact Palacio-Rodriguez (2019) ECR kernel at frozen tau = 0.05 (ADR-030 §2).

    `sigma = tau * N_panel`, `r_b = 1 + (1 - Q_b) * (N_panel - 1) in [1, N_panel]`,
    `PC-ECR = (1 / sigma) * sum_b W_b * exp(-r_b / sigma)`.
    Lives strictly on its own `1/sigma` exponential scale (`E5`), never rescaled to `0–100`.
    """
    sigma = tau * float(max(1, n_panel_parents))
    span = float(max(0, n_panel_parents - 1))
    total = 0.0
    for family, weight in block_weights.items():
        q_b = block_quantiles[family]
        rank_pos = 1.0 + (1.0 - q_b) * span
        total += weight * exp(-rank_pos / sigma)
    return total / sigma


def _build_two_tier_ranking(
    *,
    method: RankingMethod,
    reference_panel_sha256: str,
    full_rows: Sequence[_RankingRow],
    partial_rows: Sequence[ConsensusParentDetail],
    tie_policy: str,
    failure_policy: str,
) -> RankingArtifact:
    # Sort full-profile parents descending by raw score (no fixed decimal rounding that would
    # collapse small PC-ECR values at large N_panel); group scale-relative ties deterministically.
    sorted_raw = sorted(
        full_rows,
        key=lambda item: (-item.score_value, item.detail.parent_compound_id),
    )
    ordered_full: list[tuple[int, _RankingRow]] = []
    idx = 0
    total_full = len(sorted_raw)
    while idx < total_full:
        anchor_score = sorted_raw[idx].score_value
        end = idx + 1
        while end < total_full and _scores_tied(sorted_raw[end].score_value, anchor_score):
            end += 1
        bucket = sorted(sorted_raw[idx:end], key=lambda item: item.detail.parent_compound_id)
        rank = idx + 1
        for row in bucket:
            ordered_full.append((rank, row))
        idx = end

    entries: list[RankingEntry] = []
    for rank, row in ordered_full:
        detail = row.detail
        entries.append(
            RankingEntry(
                parent_compound_id=detail.parent_compound_id,
                parent_state_id=detail.parent_state_id,
                tier="full_profile",
                rank=rank,
                score_value=row.score_value,
                percentile=row.percentile,
                inter_family_disagreement=row.inter_family_disagreement,
                search_convergence_count=row.search_convergence_count,
                search_engine_count=row.search_engine_count,
                selected_pose_complex=row.pose_complex,
                failure_or_exclusion_codes=(),
            )
        )

    for detail in sorted(partial_rows, key=lambda item: item.parent_compound_id):
        codes = detail.failure_or_exclusion_codes or ("CONSENSUS_PARTIAL_OR_UNSCORED",)
        entries.append(
            RankingEntry(
                parent_compound_id=detail.parent_compound_id,
                parent_state_id=detail.parent_state_id,
                tier="partial_or_unscored",
                rank=None,
                score_value=None,
                percentile=None,
                inter_family_disagreement=None,
                search_convergence_count=detail.search_convergence_count,
                search_engine_count=detail.search_engine_count,
                selected_pose_complex=None,
                failure_or_exclusion_codes=codes,
            )
        )

    return RankingArtifact(
        method=method,
        reference_panel_sha256=reference_panel_sha256,
        tie_policy=tie_policy,
        failure_policy=failure_policy,
        total_parents=len(entries),
        full_profile_count=len(ordered_full),
        partial_or_unscored_count=len(partial_rows),
        entries=tuple(entries),
    )


def compute_pcq_and_ecr_consensus(
    *,
    variant_id: ConsensusVariantId,
    enabled_functions: Sequence[ScoringFunctionId],
    reference_panel: ReferencePanelArtifact,
    parents: Sequence[ConsensusParentInput],
    search_engine_count: int,
    panel_unique_scaffolds: int | None = None,
) -> ConsensusComputationOutput:
    """Evaluate Pose-First, Molecule-Second PC-Q, D_ic, and separate-scale PC-ECR (ADR-030)."""
    block_weights, within_block_weights = resolve_variant_weights(
        variant_id=variant_id,
        enabled_functions=enabled_functions,
    )
    enabled_set = set(enabled_functions)
    if not enabled_set.issubset(reference_panel.enabled_functions):
        raise _math_error(
            "CONSENSUS_REFERENCE_PANEL_MISMATCH",
            "ReferencePanelArtifact does not cover all requested scoring functions.",
            panel_functions=[f.value for f in reference_panel.enabled_functions],
            requested_functions=[f.value for f in enabled_functions],
        )

    # Core-block weights are ALWAYS computed alongside pcq-neural-v1 per ADR-030 §1.
    core_functions = tuple(
        fn
        for fn in enabled_functions
        if FAMILY_BY_FUNCTION[fn] in {ScoringFamily.VINA_VINARDO, ScoringFamily.AUTODOCK4}
    )
    core_block_weights, core_within_weights = resolve_variant_weights(
        variant_id=ConsensusVariantId.PCQ_CORE_V1,
        enabled_functions=core_functions,
    )

    core_set = set(core_functions)
    seen_parents: set[str] = set()
    parent_details: list[ConsensusParentDetail] = []
    full_pcq_rows: list[_RankingRow] = []
    full_core_rows: list[_RankingRow] = []
    full_ecr_rows: list[_RankingRow] = []
    partial_rows: list[ConsensusParentDetail] = []
    partial_core_rows: list[ConsensusParentDetail] = []
    high_disagreement_parents: list[str] = []

    for parent in parents:
        if parent.parent_compound_id in seen_parents:
            raise _math_error(
                "CONSENSUS_DUPLICATE_PARENT",
                f"Duplicate parent_compound_id '{parent.parent_compound_id}' in consensus input.",
                parent_compound_id=parent.parent_compound_id,
            )
        seen_parents.add(parent.parent_compound_id)

        breakdowns: list[MedoidConsensusBreakdown] = []
        core_breakdowns: list[_CoreMedoidScore] = []
        collected_failure_codes: list[str] = list(parent.failure_or_exclusion_codes)

        for medoid in parent.medoids:
            conv_count = min(len(medoid.search_engines_present), search_engine_count)
            core_fn_quantiles: dict[ScoringFunctionId, float] | None = None
            if core_set.issubset(medoid.scores_by_function):
                core_fn_quantiles = {
                    fn: parent_weighted_midrank_quantile(
                        panel=reference_panel,
                        scoring_function=fn,
                        raw_score=medoid.scores_by_function[fn],
                    )
                    for fn in core_functions
                }
                core_block_q = {
                    family: sum(
                        core_within_weights[fn] * core_fn_quantiles[fn]
                        for fn in core_functions
                        if FAMILY_BY_FUNCTION[fn] is family
                    )
                    for family in core_block_weights
                }
                pcq_core_score = 100.0 * sum(
                    core_block_weights[family] * core_block_q[family]
                    for family in core_block_weights
                )
                mean_core_q = pcq_core_score / 100.0
                core_disagreement = 100.0 * sqrt(
                    max(
                        0.0,
                        sum(
                            core_block_weights[family]
                            * ((core_block_q[family] - mean_core_q) ** 2)
                            for family in core_block_weights
                        ),
                    )
                )
                core_breakdowns.append(
                    _CoreMedoidScore(
                        cluster_id=medoid.cluster_id,
                        pose_complex=medoid.pose_complex,
                        canonical_coordinate_sha256=medoid.canonical_coordinate_sha256,
                        pcq_core_score=pcq_core_score,
                        inter_family_disagreement=core_disagreement,
                        search_convergence_count=conv_count,
                        search_engine_count=search_engine_count,
                    )
                )

            if not enabled_set.issubset(medoid.scores_by_function):
                missing = sorted(
                    f"MISSING_FAMILY_{FAMILY_BY_FUNCTION[fn].value.upper()}_{fn.value.upper()}"
                    for fn in enabled_set - set(medoid.scores_by_function)
                )
                collected_failure_codes.extend(medoid.missing_or_failed_codes or missing)
                continue

            fn_quantiles: dict[ScoringFunctionId, float] = {
                fn: (
                    core_fn_quantiles[fn]
                    if core_fn_quantiles is not None and fn in core_fn_quantiles
                    else parent_weighted_midrank_quantile(
                        panel=reference_panel,
                        scoring_function=fn,
                        raw_score=medoid.scores_by_function[fn],
                    )
                )
                for fn in enabled_functions
            }
            block_quantiles: dict[ScoringFamily, float] = {}
            for family in block_weights:
                family_fns = [fn for fn in enabled_functions if FAMILY_BY_FUNCTION[fn] is family]
                block_quantiles[family] = sum(
                    within_block_weights[fn] * fn_quantiles[fn] for fn in family_fns
                )

            pcq_score = 100.0 * sum(
                block_weights[family] * block_quantiles[family] for family in block_weights
            )
            mean_block_q = pcq_score / 100.0
            disagreement = 100.0 * sqrt(
                max(
                    0.0,
                    sum(
                        block_weights[family] * ((block_quantiles[family] - mean_block_q) ** 2)
                        for family in block_weights
                    ),
                )
            )

            medoid_core_score = core_breakdowns[-1].pcq_core_score
            pc_ecr_score = compute_pc_ecr_from_block_quantiles(
                block_quantiles=block_quantiles,
                block_weights=block_weights,
                n_panel_parents=reference_panel.total_panel_parents,
                tau=FROZEN_ECR_TAU,
            )

            breakdowns.append(
                MedoidConsensusBreakdown(
                    cluster_id=medoid.cluster_id,
                    medoid_pose_id=medoid.medoid_pose_id,
                    pose_complex=medoid.pose_complex,
                    canonical_coordinate_sha256=medoid.canonical_coordinate_sha256,
                    member_count=medoid.member_count,
                    max_intra_cluster_rmsd_angstrom=medoid.max_intra_cluster_rmsd_angstrom,
                    search_engines_present=medoid.search_engines_present,
                    search_convergence_count=conv_count,
                    search_engine_count=search_engine_count,
                    native_scores={
                        fn: float(medoid.scores_by_function[fn]) for fn in enabled_functions
                    },
                    function_quantiles=fn_quantiles,
                    block_quantiles=block_quantiles,
                    pcq_score=pcq_score,
                    pcq_core_score=medoid_core_score,
                    inter_family_disagreement=disagreement,
                    pc_ecr_score=pc_ecr_score,
                )
            )

        best_core_independent = (
            _select_best_medoid(
                core_breakdowns,
                score_fn=lambda item: item.pcq_core_score,
                hash_fn=lambda item: item.canonical_coordinate_sha256,
            )
            if core_breakdowns
            else None
        )

        if not breakdowns:
            unique_codes = tuple(dict.fromkeys(collected_failure_codes)) or (
                "CONSENSUS_NO_FULL_PROFILE_MEDOID",
            )
            detail = ConsensusParentDetail(
                parent_compound_id=parent.parent_compound_id,
                parent_state_id=parent.parent_state_id,
                tier="partial_or_unscored",
                rotatable_bond_count=parent.rotatable_bond_count,
                total_input_poses=parent.total_input_poses,
                total_clusters_found=parent.total_clusters_found,
                retained_cluster_count=len(parent.medoids),
                truncated_by_k_max=parent.truncated_by_k_max,
                pcq_core_score=(
                    best_core_independent.pcq_core_score
                    if best_core_independent is not None
                    else None
                ),
                failure_or_exclusion_codes=unique_codes,
            )
            parent_details.append(detail)
            partial_rows.append(detail)
            if best_core_independent is not None:
                full_core_rows.append(
                    _RankingRow(
                        detail=detail,
                        score_value=best_core_independent.pcq_core_score,
                        pose_complex=best_core_independent.pose_complex,
                        percentile=best_core_independent.pcq_core_score,
                        inter_family_disagreement=best_core_independent.inter_family_disagreement,
                        search_convergence_count=best_core_independent.search_convergence_count,
                        search_engine_count=best_core_independent.search_engine_count,
                    )
                )
            else:
                partial_core_rows.append(detail)
            continue

        # Molecule-second reduction: S_i = max_{c <= K_max} S_ic, E3 tie-break by lowest coord hash
        best_pcq = _select_best_medoid(
            breakdowns,
            score_fn=lambda m: m.pcq_score,
            hash_fn=lambda m: m.canonical_coordinate_sha256,
        )
        assert best_core_independent is not None
        best_ecr = _select_best_medoid(
            breakdowns,
            score_fn=lambda m: m.pc_ecr_score,
            hash_fn=lambda m: m.canonical_coordinate_sha256,
        )
        if best_pcq.inter_family_disagreement >= HIGH_DISAGREEMENT_WARNING_THRESHOLD:
            high_disagreement_parents.append(parent.parent_compound_id)

        detail = ConsensusParentDetail(
            parent_compound_id=parent.parent_compound_id,
            parent_state_id=parent.parent_state_id,
            tier="full_profile",
            rotatable_bond_count=parent.rotatable_bond_count,
            total_input_poses=parent.total_input_poses,
            total_clusters_found=parent.total_clusters_found,
            retained_cluster_count=len(parent.medoids),
            truncated_by_k_max=parent.truncated_by_k_max,
            selected_medoid_cluster_id=best_pcq.cluster_id,
            selected_pose_complex=best_pcq.pose_complex,
            pcq_score=best_pcq.pcq_score,
            pcq_core_score=best_core_independent.pcq_core_score,
            pc_ecr_score=best_ecr.pc_ecr_score,
            pc_ecr_selected_cluster_id=best_ecr.cluster_id,
            inter_family_disagreement=best_pcq.inter_family_disagreement,
            search_convergence_count=best_pcq.search_convergence_count,
            search_engine_count=best_pcq.search_engine_count,
            medoids=tuple(breakdowns),
            failure_or_exclusion_codes=(),
        )
        parent_details.append(detail)
        full_pcq_rows.append(
            _RankingRow(
                detail=detail,
                score_value=best_pcq.pcq_score,
                pose_complex=best_pcq.pose_complex,
                percentile=best_pcq.pcq_score,
                inter_family_disagreement=best_pcq.inter_family_disagreement,
                search_convergence_count=best_pcq.search_convergence_count,
                search_engine_count=best_pcq.search_engine_count,
            )
        )
        full_core_rows.append(
            _RankingRow(
                detail=detail,
                score_value=best_core_independent.pcq_core_score,
                pose_complex=best_core_independent.pose_complex,
                percentile=best_core_independent.pcq_core_score,
                inter_family_disagreement=best_core_independent.inter_family_disagreement,
                search_convergence_count=best_core_independent.search_convergence_count,
                search_engine_count=best_core_independent.search_engine_count,
            )
        )
        full_ecr_rows.append(
            _RankingRow(
                detail=detail,
                score_value=best_ecr.pc_ecr_score,
                pose_complex=best_ecr.pose_complex,
                percentile=None,
                inter_family_disagreement=best_ecr.inter_family_disagreement,
                search_convergence_count=best_ecr.search_convergence_count,
                search_engine_count=best_ecr.search_engine_count,
            )
        )

    primary_method = (
        RankingMethod.PC_Q_NEURAL_V1
        if variant_id is ConsensusVariantId.PCQ_NEURAL_V1
        else RankingMethod.PC_Q_CORE_V1
    )
    tie_policy = "competition_rank_on_equal_score_e3_coordinate_hash_medoid_tie_break"
    failure_policy = "e6_two_tier_partial_or_unscored_retained_in_denominator_no_imputation"

    ranking = _build_two_tier_ranking(
        method=primary_method,
        reference_panel_sha256=reference_panel.reference_panel_sha256,
        full_rows=full_pcq_rows,
        partial_rows=partial_rows,
        tie_policy=tie_policy,
        failure_policy=failure_policy,
    )
    core_ranking = (
        _build_two_tier_ranking(
            method=RankingMethod.PC_Q_CORE_V1,
            reference_panel_sha256=reference_panel.reference_panel_sha256,
            full_rows=full_core_rows,
            partial_rows=partial_core_rows,
            tie_policy=tie_policy,
            failure_policy=failure_policy,
        )
        if variant_id is ConsensusVariantId.PCQ_NEURAL_V1
        else None
    )
    ecr_ranking = _build_two_tier_ranking(
        method=RankingMethod.PC_ECR_V1,
        reference_panel_sha256=reference_panel.reference_panel_sha256,
        full_rows=full_ecr_rows,
        partial_rows=partial_rows,
        tie_policy=tie_policy,
        failure_policy=failure_policy,
    )

    warnings: list[StructuredWarning] = []
    if partial_rows:
        warnings.append(
            StructuredWarning(
                code=WarningCode.CONSENSUS_PARTIAL_PROFILE_RETAINED,
                stage=_STAGE,
                message=(
                    f"{len(partial_rows)} of {len(parent_details)} parent compound(s) lacked "
                    "a complete multi-family profile and were retained in the "
                    "`partial_or_unscored` tier without score imputation (ADR-030 E6)."
                ),
                details={
                    "partial_or_unscored_parents": [
                        item.parent_compound_id for item in partial_rows
                    ]
                },
            )
        )
    if high_disagreement_parents:
        warnings.append(
            StructuredWarning(
                code=WarningCode.CONSENSUS_HIGH_INTER_FAMILY_DISAGREEMENT,
                stage=_STAGE,
                message=(
                    f"{len(high_disagreement_parents)} full-profile parent(s) show high "
                    f"inter-family disagreement (D_ic >= {HIGH_DISAGREEMENT_WARNING_THRESHOLD:g})."
                ),
                details={"parent_compound_ids": high_disagreement_parents},
            )
        )

    is_small_panel = reference_panel.total_panel_parents < SMALL_PANEL_WARNING_THRESHOLD
    is_monoscaffold_panel = (
        panel_unique_scaffolds is not None
        and panel_unique_scaffolds <= 1
        and reference_panel.total_panel_parents >= 2
    )
    if is_small_panel or is_monoscaffold_panel:
        n_panel = reference_panel.total_panel_parents
        quantile_step = round(100.0 / float(n_panel), 4)
        full_count = len(full_pcq_rows)
        saturated_parents = [
            row.detail.parent_compound_id
            for row in full_pcq_rows
            if row.score_value >= _UPPER_TAIL_SATURATION_THRESHOLD
        ]
        saturation_fraction = (
            round(float(len(saturated_parents)) / float(full_count), 4) if full_count > 0 else 0.0
        )
        reasons: list[str] = []
        if is_small_panel:
            reasons.append(
                f"total_panel_parents={n_panel} < {SMALL_PANEL_WARNING_THRESHOLD} "
                f"(quantile step resolution {quantile_step:g}%)"
            )
        if is_monoscaffold_panel:
            reasons.append(
                f"congeneric single-scaffold reference panel "
                f"(panel_unique_scaffolds={panel_unique_scaffolds})"
            )
        warnings.append(
            StructuredWarning(
                code=WarningCode.CONSENSUS_SMALL_OR_CONGENERIC_PANEL,
                stage=_STAGE,
                message=(
                    "Reference panel has limited empirical quantile resolution ("
                    + "; ".join(reasons)
                    + "). Interpret PC-Q scores cautiously (ADR-033 §2.3)."
                ),
                details={
                    "total_panel_parents": n_panel,
                    "small_panel_threshold": SMALL_PANEL_WARNING_THRESHOLD,
                    "quantile_step_resolution": quantile_step,
                    "upper_tail_saturated_parents": saturated_parents,
                    "upper_tail_saturation_fraction": saturation_fraction,
                    "panel_unique_scaffolds": panel_unique_scaffolds,
                },
            )
        )

    return ConsensusComputationOutput(
        block_weights=block_weights,
        within_block_weights=within_block_weights,
        ranking=ranking,
        core_ranking=core_ranking,
        ecr_ranking=ecr_ranking,
        parent_details=tuple(parent_details),
        warnings=tuple(warnings),
    )


def fit_and_gate_pc_l2(
    *,
    calibration: CalibrationRunRecord,
    reference_panel: ReferencePanelArtifact,
    feature_functions: Sequence[ScoringFunctionId],
    parent_details_by_id: Mapping[str, ConsensusParentDetail],
    l2_regularization: float = 1.0,
) -> tuple[PcL2ModelArtifact, RankingArtifact, tuple[StructuredWarning, ...]]:
    """Fit strictly convex non-negative L2 logistic model on Calibration & gate on Confirmation.

    Per ADR-030 §3:
    1. Consumes ONLY the per-function quantiles at each parent's frozen PC-Q-selected
       medoid c* (never re-docks or re-selects poses).
    2. Fits strictly on `calibration_parent_ids` via bounded `scipy.optimize.L-BFGS-B`
       with non-negativity constraints `w_j >= 0` and L2 penalty `l2_regularization > 0`.
       Non-convergence fails closed (`422 CONSENSUS_PCL2_NON_CONVERGENT`).
    3. Evaluates paired parent bootstrap `Delta BEDROC_20` on `confirmation_parent_ids`
       against EVERY admitted single function (`feature_functions`).
    4. Promotes (`promoted = True`) ONLY if `ci_lower > 0` against every single function;
       otherwise records `promoted = False` and verbatim `"Insufficient evidence to prefer
       over baseline"` plus warning `CONSENSUS_PCL2_UNPROMOTED`.
    """
    if l2_regularization <= 0.0:
        raise _math_error(
            "CONSENSUS_PCL2_REGULARIZATION_INVALID",
            "PC-L2 L2 regularization strength must be strictly positive for strict convexity.",
            l2_regularization=l2_regularization,
        )
    if len(feature_functions) < 2:
        raise _math_error(
            "CONSENSUS_PCL2_FEATURES_INVALID",
            "PC-L2 requires at least two scoring function quantile features.",
        )

    np: Any = import_module("numpy")
    optimize: Any = import_module("scipy.optimize")

    split = calibration.split
    active_by_parent = {c.parent_id: c.is_active for c in split.compounds}

    x_cal_rows: list[list[float]] = []
    y_cal_vals: list[float] = []
    for pid in split.calibration_parent_ids:
        detail = parent_details_by_id.get(pid)
        if detail is None or detail.tier != "full_profile" or not detail.selected_medoid_cluster_id:
            continue
        selected = next(
            (m for m in detail.medoids if m.cluster_id == detail.selected_medoid_cluster_id),
            None,
        )
        if selected is None:
            continue
        x_cal_rows.append([float(selected.function_quantiles[fn]) for fn in feature_functions])
        y_cal_vals.append(1.0 if active_by_parent[pid] else -1.0)

    if len(x_cal_rows) < 4 or len(set(y_cal_vals)) < 2:
        raise _math_error(
            "CONSENSUS_PCL2_INSUFFICIENT_CALIBRATION_DATA",
            "PC-L2 requires both active and inactive full-profile parents on Calibration.",
            usable_calibration_parents=len(x_cal_rows),
        )

    x_cal = np.asarray(x_cal_rows, dtype=np.float64)
    y_cal = np.asarray(y_cal_vals, dtype=np.float64)
    n_samples, n_features = x_cal.shape
    lam = float(l2_regularization)

    def _objective_and_grad(params: Any) -> tuple[float, Any]:
        intercept = float(params[0])
        weights = params[1:]
        margins = y_cal * (intercept + x_cal @ weights)
        # Numerically stable log(1 + exp(-margin))
        loss_vec = np.logaddexp(0.0, -margins)
        obj = float(np.mean(loss_vec) + 0.5 * lam * float(np.dot(weights, weights)))
        # Gradient of mean(log(1 + exp(-m))) w.r.t. m is -sigmoid(-m) / n
        neg_prob = -1.0 / (1.0 + np.exp(np.clip(margins, -500.0, 500.0)))
        coeff = (neg_prob * y_cal) / float(n_samples)
        grad = np.empty_like(params)
        grad[0] = float(np.sum(coeff))
        grad[1:] = (x_cal.T @ coeff) + lam * weights
        return obj, grad

    x0 = np.zeros(n_features + 1, dtype=np.float64)
    bounds: list[tuple[float | None, float | None]] = [(None, None)] + [
        (0.0, None) for _ in range(n_features)
    ]
    res = optimize.minimize(
        _objective_and_grad,
        x0,
        method="L-BFGS-B",
        jac=True,
        bounds=bounds,
        options={"ftol": 1e-12, "gtol": 1e-10, "maxiter": 500},
    )
    if not bool(res.success):
        raise _math_error(
            "CONSENSUS_PCL2_NON_CONVERGENT",
            "PC-L2 strictly convex L-BFGS-B optimization did not converge; no PC-L2 score emitted.",
            solver_message=str(res.message),
            iterations=int(res.nit),
        )

    intercept_val = float(res.x[0])
    weight_map: dict[ScoringFunctionId, float] = {
        fn: max(0.0, float(res.x[idx + 1])) for idx, fn in enumerate(feature_functions)
    }

    # Score every parent at its frozen PC-Q-selected medoid c* (higher linear predictor = better).
    # Single-engine Confirmation baselines use each engine's OWN best medoid max_c q_fn(c) so no
    # single engine is handicapped at PC-Q's c* (D2-006 / ADR-030 §3).
    pcl2_scores_by_parent: dict[str, float | None] = {}
    pcq_scores_by_parent: dict[str, float | None] = {}
    single_scores_by_fn: dict[ScoringFunctionId, dict[str, float | None]] = {
        fn: {} for fn in feature_functions
    }
    full_pcl2_rows: list[_RankingRow] = []
    partial_pcl2_rows: list[ConsensusParentDetail] = []

    for pid, detail in parent_details_by_id.items():
        if detail.tier != "full_profile" or not detail.selected_medoid_cluster_id:
            pcl2_scores_by_parent[pid] = None
            pcq_scores_by_parent[pid] = None
            for fn in feature_functions:
                single_scores_by_fn[fn][pid] = None
            partial_pcl2_rows.append(detail)
            continue
        selected = next(
            m for m in detail.medoids if m.cluster_id == detail.selected_medoid_cluster_id
        )
        linear_score = intercept_val + sum(
            weight_map[fn] * float(selected.function_quantiles[fn]) for fn in feature_functions
        )
        pcl2_scores_by_parent[pid] = linear_score
        pcq_scores_by_parent[pid] = detail.pcq_score
        for fn in feature_functions:
            single_scores_by_fn[fn][pid] = max(
                float(medoid.function_quantiles[fn]) for medoid in detail.medoids
            )
        full_pcl2_rows.append(
            _RankingRow(
                detail=detail,
                score_value=linear_score,
                pose_complex=selected.pose_complex,
                percentile=None,
                inter_family_disagreement=selected.inter_family_disagreement,
                search_convergence_count=selected.search_convergence_count,
                search_engine_count=selected.search_engine_count,
            )
        )

    # Gate on locked Confirmation split (ADR-030 §3 & ADR-031 §3):
    # 1. Split must NOT be confirmation_underpowered.
    # 2. Must beat EVERY admitted single scoring function (at its own best medoid) with
    #    paired parent bootstrap 95% CI strictly above 0.
    # 3. Under 1-SE parsimony, fitted PC-L2 must strictly beat unfitted PC-Q (ci_lower > 0).
    conf_parents = tuple(split.confirmation_parent_ids)

    def _to_benchmark_rows(
        score_map: Mapping[str, float | None],
    ) -> list[ScreeningBenchmarkObservation]:
        rows: list[ScreeningBenchmarkObservation] = []
        for pid in conf_parents:
            detail = parent_details_by_id.get(pid)
            state_id = detail.parent_state_id if detail is not None else f"{pid}-missing"
            val = score_map.get(pid)
            if val is None:
                code = (
                    detail.failure_or_exclusion_codes[0]
                    if detail is not None and detail.failure_or_exclusion_codes
                    else "CONSENSUS_PARTIAL_OR_UNSCORED"
                )
                rows.append(
                    ScreeningBenchmarkObservation(
                        parent_id=pid,
                        is_active=active_by_parent[pid],
                        score=None,
                        state_id=state_id,
                        failure_code=code,
                    )
                )
            else:
                rows.append(
                    ScreeningBenchmarkObservation(
                        parent_id=pid,
                        is_active=active_by_parent[pid],
                        score=val,
                        state_id=state_id,
                        failure_code=None,
                    )
                )
        return rows

    pcl2_conf_rows = _to_benchmark_rows(pcl2_scores_by_parent)
    pcq_conf_rows = _to_benchmark_rows(pcq_scores_by_parent)
    delta_vs_pcq = paired_parent_bootstrap_delta(
        candidate_protocol_id="pc_l2_v1",
        reference_protocol_id="pc_q",
        split_name="confirmation",
        candidate_observations=pcl2_conf_rows,
        reference_observations=pcq_conf_rows,
        candidate_direction=ScoreDirection.HIGHER_IS_BETTER,
        reference_direction=ScoreDirection.HIGHER_IS_BETTER,
        policy=split.policy,
    )
    deltas: dict[str, PairedBootstrapDelta] = {}
    all_beat = True
    for fn in feature_functions:
        fn_conf_rows = _to_benchmark_rows(single_scores_by_fn[fn])
        delta = paired_parent_bootstrap_delta(
            candidate_protocol_id="pc_l2_v1",
            reference_protocol_id=fn.value,
            split_name="confirmation",
            candidate_observations=pcl2_conf_rows,
            reference_observations=fn_conf_rows,
            candidate_direction=ScoreDirection.HIGHER_IS_BETTER,
            reference_direction=ScoreDirection.HIGHER_IS_BETTER,
            policy=split.policy,
        )
        deltas[fn.value] = delta
        if delta.ci_lower <= 0.0:
            all_beat = False

    promoted = (
        (not split.confirmation_underpowered)
        and all_beat
        and delta_vs_pcq.ci_lower > 0.0
        and len(deltas) == len(feature_functions)
    )
    verdict_text = (
        "Promoted: PC-L2 paired parent bootstrap Delta BEDROC_20 strictly exceeds 0 "
        "against unfitted PC-Q and every admitted single scoring function on locked Confirmation."
        if promoted
        else INSUFFICIENT_EVIDENCE_TEXT
    )
    warnings: list[StructuredWarning] = []
    if not promoted:
        warnings.append(
            StructuredWarning(
                code=WarningCode.CONSENSUS_PCL2_UNPROMOTED,
                stage=_STAGE,
                message=(
                    f"PC-L2 did not clear the locked Confirmation promotion gate: {verdict_text}."
                ),
                details={
                    "confirmation_underpowered": bool(split.confirmation_underpowered),
                    "delta_vs_pcq": {
                        "point_delta": delta_vs_pcq.point_delta,
                        "ci_lower": delta_vs_pcq.ci_lower,
                    },
                    "deltas": {
                        fn: {"point_delta": d.point_delta, "ci_lower": d.ci_lower}
                        for fn, d in deltas.items()
                    },
                },
            )
        )

    model = PcL2ModelArtifact(
        reference_panel_sha256=reference_panel.reference_panel_sha256,
        calibration_id=calibration.calibration_id,
        split_identity_sha256=split.split_identity_sha256,
        selection_identity_sha256=(
            calibration.calibration_selection.selection_identity_sha256
            if calibration.calibration_selection is not None
            else None
        ),
        confirmation_identity_sha256=(
            calibration.confirmation_evaluation.confirmation_identity_sha256
            if calibration.confirmation_evaluation is not None
            else None
        ),
        feature_functions=tuple(feature_functions),
        l2_regularization=lam,
        intercept=intercept_val,
        weights=weight_map,
        converged=True,
        iterations=int(res.nit),
        final_objective=float(res.fun),
        promoted=promoted,
        promotion_verdict_text=verdict_text,
        confirmation_deltas_vs_single_engines=deltas,
        confirmation_delta_vs_pcq=delta_vs_pcq,
    )
    ranking = _build_two_tier_ranking(
        method=RankingMethod.PC_L2_V1,
        reference_panel_sha256=reference_panel.reference_panel_sha256,
        full_rows=full_pcl2_rows,
        partial_rows=partial_pcl2_rows,
        tie_policy="competition_rank_on_equal_score_e3_coordinate_hash_medoid_tie_break",
        failure_policy="e6_two_tier_partial_or_unscored_retained_in_denominator_no_imputation",
    )
    return model, ranking, tuple(warnings)


def _math_error(code: str, message: str, **details: object) -> AnkoraDomainError:
    return AnkoraDomainError(
        code=code,
        stage=_STAGE,
        message=message,
        status_code=422,
        details=details,
    )
