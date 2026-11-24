"""One-directional two-axis external benchmark evaluator (ADR-031, Python 3.12 stdlib only).

Consumes Ankora ONLY through cryptographically verified `Export v4` / `Export v5`
bundles (`scripts/verify_export_bundle.py`) and consumes pinned external platform
CSV outputs alongside their recorded SHA-256 digests.

Never imports `ankora_backend` or any third-party package; runs cleanly under `python -S`.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import io
import json
import math
import random
import sys
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType
from typing import Any

_THIS_DIR = Path(__file__).resolve().parent
if str(_THIS_DIR) not in sys.path:
    sys.path.insert(0, str(_THIS_DIR))

from protocol_manifest import (
    INSUFFICIENT_EVIDENCE_TEXT,
    ComparisonProtocolManifest,
    ProtocolManifestError,
    canonical_json_sha256,
)

REPO_ROOT = _THIS_DIR.parents[1]
VERIFIER_PATH = REPO_ROOT / "scripts" / "verify_export_bundle.py"


class ComparisonEvaluationError(ValueError):
    """Raised when inputs fail integrity verification or denominator invariants."""


def _load_bundle_verifier() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "ankora_verify_export_bundle", VERIFIER_PATH
    )
    if spec is None or spec.loader is None:
        raise ComparisonEvaluationError(
            f"Unable to load bundle verifier at {VERIFIER_PATH}"
        )
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True, slots=True)
class ParentScoreRecord:
    """Normalized observation for one parent compound on one platform and axis."""

    parent_id: str
    scored: bool
    oriented_score: float | None
    failure_code: str | None = None
    posebusters_pass: bool | None = None


def _read_bundle_file(bundle_path: Path, rel_path: str) -> bytes:
    if bundle_path.is_file():
        with zipfile.ZipFile(bundle_path, mode="r") as zf:
            return zf.read(rel_path)
    return (bundle_path / rel_path).read_bytes()


def load_ankora_export_scores(
    bundle_path: Path,
    *,
    score_column: str,
    higher_is_better: bool,
) -> tuple[dict[str, ParentScoreRecord], dict[str, Any]]:
    """Verify an Ankora Export v4/v5 bundle and extract per-parent scores + PoseBusters flags."""
    verifier = _load_bundle_verifier()
    try:
        verification = verifier.verify_bundle(bundle_path)
    except Exception as err:
        raise ComparisonEvaluationError(
            f"Ankora export bundle failed verification ({bundle_path.name}): {err}"
        ) from err

    manifest = json.loads(
        _read_bundle_file(bundle_path, "manifest.json").decode("utf-8")
    )
    csv_text = _read_bundle_file(bundle_path, "results.csv").decode("utf-8")
    reader = csv.DictReader(io.StringIO(csv_text))
    if reader.fieldnames is None:
        raise ComparisonEvaluationError("Ankora export results.csv has no header")
    if score_column not in reader.fieldnames:
        raise ComparisonEvaluationError(
            f"Ankora export results.csv is missing declared score column {score_column!r}; "
            f"available: {reader.fieldnames}"
        )

    # Extract optional M3 PoseBusters pass/fail status by ligand/parent from Export v5 evidence.
    pb_status_by_ligand: dict[str, bool] = {}
    recorded_evidence = manifest.get("recorded_evidence") or {}
    for item in recorded_evidence.get("pose_quality_assessments") or []:
        lig_id = item.get("ligand_id")
        overall = item.get("overall_status")
        if isinstance(lig_id, str) and overall in {"pass", "fail"}:
            # Conservative aggregation if multiple assessments exist for one ligand:
            # mark True only if at least one selected/recorded assessment passes.
            pb_status_by_ligand[lig_id] = pb_status_by_ligand.get(lig_id, False) or (
                overall == "pass"
            )

    row_kind = verification["row_kind"]
    records: dict[str, ParentScoreRecord] = {}
    for row in reader:
        if row_kind == "consensus_parent":
            parent_id = (row.get("parent_compound_id") or "").strip()
            tier = (row.get("tier") or "").strip()
            raw_val = (row.get(score_column) or "").strip()
            codes = (row.get("failure_or_exclusion_codes") or "").strip() or None
            if not parent_id:
                continue
            if tier == "full_profile" and raw_val:
                val = float(raw_val)
                oriented = val if higher_is_better else -val
                records[parent_id] = ParentScoreRecord(
                    parent_id=parent_id,
                    scored=True,
                    oriented_score=oriented,
                    failure_code=None,
                    posebusters_pass=pb_status_by_ligand.get(parent_id),
                )
            else:
                records[parent_id] = ParentScoreRecord(
                    parent_id=parent_id,
                    scored=False,
                    oriented_score=None,
                    failure_code=codes or "PARTIAL_OR_UNSCORED",
                    posebusters_pass=pb_status_by_ligand.get(parent_id),
                )
        else:
            parent_id = (
                row.get("parent_compound_id")
                or row.get("ligand_id")
                or row.get("molecule")
                or ""
            ).strip()
            status = (row.get("status") or "completed").strip()
            raw_val = (row.get(score_column) or "").strip()
            fcode = (row.get("failure_code") or "").strip() or None
            if not parent_id:
                continue
            if status == "completed" and raw_val:
                val = float(raw_val)
                oriented = val if higher_is_better else -val
                # Keep best oriented score per parent if multiple microstates appear
                prev = records.get(parent_id)
                if (
                    prev is None
                    or not prev.scored
                    or (
                        prev.oriented_score is not None
                        and oriented > prev.oriented_score
                    )
                ):
                    records[parent_id] = ParentScoreRecord(
                        parent_id=parent_id,
                        scored=True,
                        oriented_score=oriented,
                        failure_code=None,
                        posebusters_pass=pb_status_by_ligand.get(parent_id),
                    )
            elif parent_id not in records:
                records[parent_id] = ParentScoreRecord(
                    parent_id=parent_id,
                    scored=False,
                    oriented_score=None,
                    failure_code=fcode or f"STATUS_{status.upper()}",
                    posebusters_pass=pb_status_by_ligand.get(parent_id),
                )

    return records, verification


def load_external_scores_csv(
    csv_path: Path,
    *,
    score_column: str,
    higher_is_better: bool,
    expected_sha256: str | None = None,
) -> tuple[dict[str, ParentScoreRecord], str]:
    """Load pinned external platform outputs (e.g., DockM8) and verify raw SHA-256."""
    if not csv_path.is_file():
        raise ComparisonEvaluationError(f"External scores CSV not found: {csv_path}")
    observed_sha = _sha256_file(csv_path)
    if expected_sha256 is not None and observed_sha != expected_sha256:
        raise ComparisonEvaluationError(
            f"External output SHA-256 mismatch for {csv_path.name}: "
            f"expected {expected_sha256}, observed {observed_sha}"
        )

    csv_text = csv_path.read_text(encoding="utf-8")
    reader = csv.DictReader(io.StringIO(csv_text))
    if reader.fieldnames is None or "parent_compound_id" not in reader.fieldnames:
        raise ComparisonEvaluationError(
            f"External scores CSV {csv_path.name} requires a 'parent_compound_id' column"
        )
    if score_column not in reader.fieldnames:
        raise ComparisonEvaluationError(
            f"External scores CSV {csv_path.name} is missing score column {score_column!r}"
        )

    records: dict[str, ParentScoreRecord] = {}
    for row in reader:
        parent_id = (row.get("parent_compound_id") or "").strip()
        if not parent_id:
            continue
        status = (row.get("status") or "scored").strip().lower()
        raw_val = (row.get(score_column) or "").strip()
        fcode = (row.get("failure_code") or "").strip() or None
        raw_pb = (row.get("posebusters_pass") or "").strip().lower()
        pb_flag: bool | None = (
            True
            if raw_pb in {"true", "1", "pass", "yes"}
            else False
            if raw_pb in {"false", "0", "fail", "no"}
            else None
        )
        if status in {"scored", "completed", "ok"} and raw_val:
            val = float(raw_val)
            oriented = val if higher_is_better else -val
            records[parent_id] = ParentScoreRecord(
                parent_id=parent_id,
                scored=True,
                oriented_score=oriented,
                failure_code=None,
                posebusters_pass=pb_flag,
            )
        else:
            records[parent_id] = ParentScoreRecord(
                parent_id=parent_id,
                scored=False,
                oriented_score=None,
                failure_code=fcode or f"EXTERNAL_{status.upper()}",
                posebusters_pass=pb_flag,
            )
    return records, observed_sha


def _tie_aware_rank_groups(
    parent_ids: tuple[str, ...],
    records: dict[str, ParentScoreRecord],
    *,
    require_posebusters_pass: bool = False,
) -> tuple[list[list[str]], int, int]:
    """Group all denominator parents descending by oriented score; failures tie dead last."""
    score_buckets: dict[float, list[str]] = {}
    failed_bucket: list[str] = []
    scored_count = 0

    for pid in parent_ids:
        rec = records.get(pid)
        usable = rec is not None and rec.scored and rec.oriented_score is not None
        if (
            usable
            and require_posebusters_pass
            and rec is not None
            and rec.posebusters_pass is False
        ):
            usable = False
        if usable and rec is not None and rec.oriented_score is not None:
            scored_count += 1
            score_buckets.setdefault(rec.oriented_score, []).append(pid)
        else:
            failed_bucket.append(pid)

    groups = [score_buckets[key] for key in sorted(score_buckets, reverse=True)]
    if failed_bucket:
        groups.append(failed_bucket)
    return groups, scored_count, len(failed_bucket)


def compute_tie_aware_enrichment(
    *,
    parent_ids: tuple[str, ...],
    active_set: frozenset[str],
    records: dict[str, ParentScoreRecord],
    bedroc_alpha: float = 20.0,
    top_fraction: float = 0.01,
    require_posebusters_pass: bool = False,
) -> dict[str, Any]:
    """Compute exact tie-aware BEDROC_alpha, EF_x%, ROC-AUC, PR-AUC, and failure census."""
    n_total = len(parent_ids)
    n_active = sum(1 for pid in parent_ids if pid in active_set)
    n_inactive = n_total - n_active
    if n_total == 0 or n_active == 0 or n_inactive == 0:
        raise ComparisonEvaluationError(
            "Denominator must contain at least 1 active and 1 inactive"
        )

    groups, scored_count, failed_count = _tie_aware_rank_groups(
        parent_ids, records, require_posebusters_pass=require_posebusters_pass
    )

    # BEDROC (Truchon & Bayly 2007) using exact tie-group average exponential weight
    weighted_sum = 0.0
    pos = 0
    roc_area = 0.0
    pr_area = 0.0
    tp_so_far = 0
    fp_so_far = 0

    top_k = max(1, math.ceil(top_fraction * n_total))
    expected_top_hits = 0.0

    for group in groups:
        g_size = len(group)
        g_act = sum(1 for pid in group if pid in active_set)
        g_inact = g_size - g_act

        # Exact expected BEDROC exponential sum over uniform permutations within tie group
        if g_act > 0:
            exp_sum = sum(
                math.exp(-bedroc_alpha * ((pos + offset + 1) / n_total))
                for offset in range(g_size)
            )
            weighted_sum += g_act * (exp_sum / g_size)

        # Expected active hits inside top_k
        overlap_start = pos
        overlap_end = min(pos + g_size, top_k)
        if overlap_end > overlap_start and g_act > 0:
            expected_top_hits += g_act * ((overlap_end - overlap_start) / g_size)

        # Exact tie-aware ROC-AUC (Mann-Whitney U / trapezoid)
        roc_area += g_act * (n_inactive - fp_so_far - 0.5 * g_inact)

        # Tie-aware step-interpolated PR-AUC (average precision across group ranks)
        if g_act > 0:
            for k in range(1, g_act + 1):
                tp_k = tp_so_far + k
                fp_k = fp_so_far + (k * g_inact / g_act)
                pr_area += tp_k / (tp_k + fp_k)

        tp_so_far += g_act
        fp_so_far += g_inact
        pos += g_size

    # BEDROC (Truchon & Bayly 2007, Eq. 18 & 36) using exact discrete RIE normalization
    # matching ankora_backend.services.screening_benchmark._bedroc to <= 1e-12.
    ra = n_active / n_total
    alpha = bedroc_alpha
    normalization = (-math.expm1(-alpha)) / n_total / math.expm1(alpha / n_total)
    rie = weighted_sum / (n_active * normalization) if normalization > 0.0 else 0.0
    rie_max = (-math.expm1(-alpha * ra)) / (ra * -math.expm1(-alpha))
    rie_min = math.expm1(alpha * ra) / (ra * math.expm1(alpha))
    bedroc = (rie - rie_min) / (rie_max - rie_min) if rie_max > rie_min else 0.0
    bedroc = max(0.0, min(1.0, bedroc))

    roc_auc = roc_area / (n_active * n_inactive)
    pr_auc = pr_area / n_active
    enrichment_factor = (expected_top_hits / top_k) / ra

    scored_actives = 0
    failed_actives = 0
    scored_inactives = 0
    failed_inactives = 0
    pb_evaluated = 0
    pb_passed = 0
    for pid in parent_ids:
        rec = records.get(pid)
        is_act = pid in active_set
        is_scored = rec is not None and rec.scored and rec.oriented_score is not None
        if rec is not None and rec.posebusters_pass is not None:
            pb_evaluated += 1
            if rec.posebusters_pass:
                pb_passed += 1
        if (
            require_posebusters_pass
            and rec is not None
            and rec.posebusters_pass is False
        ):
            is_scored = False
        if is_act:
            if is_scored:
                scored_actives += 1
            else:
                failed_actives += 1
        else:
            if is_scored:
                scored_inactives += 1
            else:
                failed_inactives += 1

    return {
        "total_parents": n_total,
        "active_count": n_active,
        "inactive_count": n_inactive,
        "scored_count": scored_count,
        "failed_count": failed_count,
        "scored_active_count": scored_actives,
        "failed_active_count": failed_actives,
        "scored_inactive_count": scored_inactives,
        "failed_inactive_count": failed_inactives,
        "bedroc_alpha": bedroc_alpha,
        "bedroc": bedroc,
        "top_fraction": top_fraction,
        "top_k": top_k,
        "expected_active_hits_top_k": expected_top_hits,
        "enrichment_factor": enrichment_factor,
        "roc_auc": roc_auc,
        "pr_auc": pr_auc,
        "posebusters_evaluated_count": pb_evaluated,
        "posebusters_passed_count": pb_passed,
        "posebusters_pass_rate": (pb_passed / pb_evaluated)
        if pb_evaluated > 0
        else None,
        "require_posebusters_pass": require_posebusters_pass,
    }


def paired_parent_bootstrap_delta(
    *,
    parent_ids: tuple[str, ...],
    active_set: frozenset[str],
    ankora_records: dict[str, ParentScoreRecord],
    external_records: dict[str, ParentScoreRecord],
    bedroc_alpha: float = 20.0,
    top_fraction: float = 0.01,
    replicates: int = 2000,
    seed: int = 20261120,
    confidence_level: float = 0.95,
    require_posebusters_pass: bool = False,
) -> dict[str, Any]:
    """Paired parent-compound bootstrap for delta = BEDROC(Ankora) - BEDROC(External)."""
    ank_point = compute_tie_aware_enrichment(
        parent_ids=parent_ids,
        active_set=active_set,
        records=ankora_records,
        bedroc_alpha=bedroc_alpha,
        top_fraction=top_fraction,
        require_posebusters_pass=require_posebusters_pass,
    )
    ext_point = compute_tie_aware_enrichment(
        parent_ids=parent_ids,
        active_set=active_set,
        records=external_records,
        bedroc_alpha=bedroc_alpha,
        top_fraction=top_fraction,
        require_posebusters_pass=require_posebusters_pass,
    )
    point_delta = ank_point["bedroc"] - ext_point["bedroc"]

    rng = random.Random(seed)
    n = len(parent_ids)
    deltas: list[float] = []
    for _ in range(replicates):
        # Stratified-safe check: resample parents with replacement; skip degenerate single-class draws
        sample_indices = [rng.randrange(n) for _ in range(n)]
        sample_pids = tuple(
            f"r{idx}_{parent_ids[s]}" for idx, s in enumerate(sample_indices)
        )
        sample_actives = frozenset(
            sample_pids[idx]
            for idx, s in enumerate(sample_indices)
            if parent_ids[s] in active_set
        )
        if not sample_actives or len(sample_actives) == n:
            continue
        sample_ank = {
            sample_pids[idx]: ankora_records[parent_ids[s]]
            for idx, s in enumerate(sample_indices)
            if parent_ids[s] in ankora_records
        }
        sample_ext = {
            sample_pids[idx]: external_records[parent_ids[s]]
            for idx, s in enumerate(sample_indices)
            if parent_ids[s] in external_records
        }
        a_m = compute_tie_aware_enrichment(
            parent_ids=sample_pids,
            active_set=sample_actives,
            records=sample_ank,
            bedroc_alpha=bedroc_alpha,
            top_fraction=top_fraction,
            require_posebusters_pass=require_posebusters_pass,
        )
        e_m = compute_tie_aware_enrichment(
            parent_ids=sample_pids,
            active_set=sample_actives,
            records=sample_ext,
            bedroc_alpha=bedroc_alpha,
            top_fraction=top_fraction,
            require_posebusters_pass=require_posebusters_pass,
        )
        deltas.append(a_m["bedroc"] - e_m["bedroc"])

    if not deltas:
        raise ComparisonEvaluationError(
            "Bootstrap produced zero non-degenerate replicates"
        )

    deltas.sort()
    mean_delta = sum(deltas) / len(deltas)
    variance = (
        sum((d - mean_delta) ** 2 for d in deltas) / (len(deltas) - 1)
        if len(deltas) > 1
        else 0.0
    )
    se = math.sqrt(variance)
    tail = (1.0 - confidence_level) / 2.0
    lo_idx = max(0, min(len(deltas) - 1, math.floor(tail * (len(deltas) - 1))))
    hi_idx = max(0, min(len(deltas) - 1, math.ceil((1.0 - tail) * (len(deltas) - 1))))
    ci_lower = deltas[lo_idx]
    ci_upper = deltas[hi_idx]

    if ci_lower > 0.0:
        verdict = "ankora_preferred"
        verdict_text = (
            f"Ankora preferred on primary BEDROC_{int(bedroc_alpha)} "
            f"(delta {point_delta:+.4f}, 95% CI [{ci_lower:+.4f}, {ci_upper:+.4f}])."
        )
    elif ci_upper < 0.0:
        verdict = "external_preferred"
        verdict_text = (
            f"External platform preferred on primary BEDROC_{int(bedroc_alpha)} "
            f"(delta {point_delta:+.4f}, 95% CI [{ci_lower:+.4f}, {ci_upper:+.4f}])."
        )
    else:
        verdict = "insufficient_evidence_to_prefer_over_baseline"
        verdict_text = INSUFFICIENT_EVIDENCE_TEXT

    return {
        "ankora": ank_point,
        "external": ext_point,
        "point_delta_bedroc": point_delta,
        "bootstrap_se": se,
        "ci_lower": ci_lower,
        "ci_upper": ci_upper,
        "confidence_level": confidence_level,
        "valid_replicates": len(deltas),
        "bootstrap_seed": seed,
        "within_one_se": abs(point_delta) <= se,
        "verdict": verdict,
        "verdict_text": verdict_text,
    }


def evaluate_axis(
    *,
    axis_name: str,
    protocol: ComparisonProtocolManifest,
    ankora_bundle_path: Path,
    external_csv_path: Path,
    external_expected_sha256: str | None = None,
) -> dict[str, Any]:
    ankora_records, ankora_verification = load_ankora_export_scores(
        ankora_bundle_path,
        score_column=protocol.ankora_score_column,
        higher_is_better=protocol.ankora_higher_is_better,
    )
    external_records, external_sha = load_external_scores_csv(
        external_csv_path,
        score_column=protocol.external_score_column,
        higher_is_better=protocol.external_higher_is_better,
        expected_sha256=external_expected_sha256,
    )

    parent_ids = protocol.split.all_parent_ids
    active_set = protocol.split.active_set

    unfiltered = paired_parent_bootstrap_delta(
        parent_ids=parent_ids,
        active_set=active_set,
        ankora_records=ankora_records,
        external_records=external_records,
        bedroc_alpha=protocol.bedroc_alpha,
        top_fraction=protocol.top_fraction,
        replicates=protocol.bootstrap_replicates,
        seed=protocol.bootstrap_seed,
        confidence_level=protocol.confidence_level,
        require_posebusters_pass=False,
    )

    has_any_pb = any(
        r.posebusters_pass is not None for r in ankora_records.values()
    ) or any(r.posebusters_pass is not None for r in external_records.values())
    posebusters_stratified = (
        paired_parent_bootstrap_delta(
            parent_ids=parent_ids,
            active_set=active_set,
            ankora_records=ankora_records,
            external_records=external_records,
            bedroc_alpha=protocol.bedroc_alpha,
            top_fraction=protocol.top_fraction,
            replicates=protocol.bootstrap_replicates,
            seed=protocol.bootstrap_seed + 1,
            confidence_level=protocol.confidence_level,
            require_posebusters_pass=True,
        )
        if has_any_pb
        else None
    )

    return {
        "axis": axis_name,
        "ankora_bundle_verification": ankora_verification,
        "external_csv_sha256": external_sha,
        "primary_comparison": unfiltered,
        "posebusters_stratified_comparison": posebusters_stratified,
    }


def evaluate_two_axis_comparison(
    *,
    protocol: ComparisonProtocolManifest,
    ankora_controlled: Path | None,
    external_controlled: Path | None,
    ankora_end_to_end: Path | None,
    external_end_to_end: Path | None,
) -> dict[str, Any]:
    """Run ADR-031 two-axis comparison; refuses admissible verdict if either axis is omitted."""
    axes_results: dict[str, Any] = {}
    if ankora_controlled is not None and external_controlled is not None:
        axes_results["controlled"] = evaluate_axis(
            axis_name="controlled",
            protocol=protocol,
            ankora_bundle_path=ankora_controlled,
            external_csv_path=external_controlled,
            external_expected_sha256=protocol.external_platform.raw_output_sha256s.get(
                "controlled"
            ),
        )
    if ankora_end_to_end is not None and external_end_to_end is not None:
        axes_results["end_to_end"] = evaluate_axis(
            axis_name="end_to_end",
            protocol=protocol,
            ankora_bundle_path=ankora_end_to_end,
            external_csv_path=external_end_to_end,
            external_expected_sha256=protocol.external_platform.raw_output_sha256s.get(
                "end_to_end"
            ),
        )

    both_present = "controlled" in axes_results and "end_to_end" in axes_results
    admissibility_status = (
        "ADMISSIBLE_TWO_AXIS_COMPARISON"
        if both_present
        else "INCOMPLETE_SINGLE_AXIS_NOT_ADMISSIBLE"
    )
    body: dict[str, Any] = {
        "schema_version": 1,
        "evaluated_at": datetime.now(UTC).isoformat(),
        "adr": "ADR-031",
        "protocol_id": protocol.protocol_id,
        "protocol_sha256": protocol.protocol_sha256,
        "target_id": protocol.target_id,
        "split_identity_sha256": protocol.split.split_identity_sha256,
        "ankora_platform": protocol.ankora_platform.to_dict(),
        "external_platform": protocol.external_platform.to_dict(),
        "admissible_comparison": both_present,
        "admissibility_status": admissibility_status,
        "mandatory_publication_of_negative_and_null_results": True,
        "axes": axes_results,
    }
    report_sha = canonical_json_sha256(body)
    return {**body, "report_sha256": report_sha}


def render_comparison_markdown(report: dict[str, Any]) -> str:
    """Render an auditable Markdown comparison summary including negative/null outcomes."""
    lines = [
        f"# External Comparison Report — `{report['protocol_id']}` (`{report['target_id']}`)",
        "",
        "- **Governance:** `ADR-031` (mandatory two-axis evaluation & negative/null publication)",
        f"- **Admissibility:** `{report['admissibility_status']}`",
        f"- **Protocol SHA-256:** `{report['protocol_sha256']}`",
        f"- **Split Identity SHA-256:** `{report['split_identity_sha256']}`",
        f"- **Ankora Platform:** `{report['ankora_platform']['platform_name']} {report['ankora_platform']['version']}` (`{report['ankora_platform']['artifact_digest'][:16]}...`)",
        f"- **External Platform:** `{report['external_platform']['platform_name']} {report['external_platform']['version']}` (`{report['external_platform']['artifact_digest'][:16]}...`)",
        f"- **Report SHA-256:** `{report['report_sha256']}`",
        "",
    ]
    if not report["admissible_comparison"]:
        lines.extend(
            [
                (
                    "> **NOT ADMISSIBLE FOR PUBLICATION (`ADR-031 §2`):** Both `controlled` and "
                    "`end_to_end` axes are mandatory before any platform comparison verdict is admissible."
                ),
                "",
            ]
        )

    for axis_key in ("controlled", "end_to_end"):
        axis = report["axes"].get(axis_key)
        if not axis:
            continue
        prim = axis["primary_comparison"]
        ank = prim["ankora"]
        ext = prim["external"]
        lines.extend(
            [
                f"## Axis: `{axis_key}`",
                "",
                f"- **Primary verdict:** {prim['verdict_text']}",
                (
                    "- **Paired parent-bootstrap Δ BEDROC_20 (Ankora − External):** "
                    f"`{prim['point_delta_bedroc']:+.4f}` (95% CI `[{prim['ci_lower']:+.4f}, "
                    f"{prim['ci_upper']:+.4f}]`, SE `{prim['bootstrap_se']:.4f}`, "
                    f"`{prim['valid_replicates']}` replicates)"
                ),
                "",
                "| Platform | BEDROC_20 | EF_1% | ROC-AUC | PR-AUC | Scored / Total | Failed Actives / Inactives |",
                "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
                f"| Ankora | {ank['bedroc']:.4f} | {ank['enrichment_factor']:.2f} | {ank['roc_auc']:.4f} | {ank['pr_auc']:.4f} | {ank['scored_count']}/{ank['total_parents']} | {ank['failed_active_count']}/{ank['failed_inactive_count']} |",
                f"| External | {ext['bedroc']:.4f} | {ext['enrichment_factor']:.2f} | {ext['roc_auc']:.4f} | {ext['pr_auc']:.4f} | {ext['scored_count']}/{ext['total_parents']} | {ext['failed_active_count']}/{ext['failed_inactive_count']} |",
                "",
            ]
        )
        pb = axis.get("posebusters_stratified_comparison")
        if pb:
            lines.extend(
                [
                    "### PoseBusters Physical-Validity Stratified Enrichment",
                    "",
                    f"- **Stratified verdict (physically valid poses only):** {pb['verdict_text']}",
                    (
                        f"- **Ankora valid BEDROC_20:** `{pb['ankora']['bedroc']:.4f}` "
                        f"(pass rate: `{pb['ankora']['posebusters_passed_count']}/{pb['ankora']['posebusters_evaluated_count']}`)"
                    ),
                    (
                        f"- **External valid BEDROC_20:** `{pb['external']['bedroc']:.4f}` "
                        f"(pass rate: `{pb['external']['posebusters_passed_count']}/{pb['external']['posebusters_evaluated_count']}`)"
                    ),
                    "",
                ]
            )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--ankora-controlled", type=Path, default=None)
    parser.add_argument("--external-controlled", type=Path, default=None)
    parser.add_argument("--ankora-end-to-end", type=Path, default=None)
    parser.add_argument("--external-end-to-end", type=Path, default=None)
    parser.add_argument("--output-json", type=Path, default=None)
    parser.add_argument("--output-markdown", type=Path, default=None)
    args = parser.parse_args(argv)

    try:
        raw = json.loads(args.protocol.read_text(encoding="utf-8"))
        protocol = ComparisonProtocolManifest.from_dict(raw)
        report = evaluate_two_axis_comparison(
            protocol=protocol,
            ankora_controlled=args.ankora_controlled,
            external_controlled=args.external_controlled,
            ankora_end_to_end=args.ankora_end_to_end,
            external_end_to_end=args.external_end_to_end,
        )
    except (
        OSError,
        json.JSONDecodeError,
        ProtocolManifestError,
        ComparisonEvaluationError,
    ) as err:
        print(f"COMPARISON EVALUATION FAILED: {err}", file=sys.stderr)
        return 1

    if args.output_json is not None:
        args.output_json.parent.mkdir(parents=True, exist_ok=True)
        args.output_json.write_text(
            json.dumps(report, indent=2) + "\n", encoding="utf-8"
        )
    if args.output_markdown is not None:
        args.output_markdown.parent.mkdir(parents=True, exist_ok=True)
        args.output_markdown.write_text(
            render_comparison_markdown(report), encoding="utf-8"
        )

    print(
        f"COMPARISON RECORDED: {report['protocol_id']} "
        f"[{report['admissibility_status']}] sha256={report['report_sha256'][:12]}..."
    )
    return 0 if report["admissible_comparison"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
