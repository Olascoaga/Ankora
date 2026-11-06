"""Cross-platform *diagnostic* comparison of the frozen primary Vina metrics.

This is not a verifier. ``verify_primary_metrics_manifest`` remains the only
strict check and still requires exact reproduction. This module answers a
narrower question for a host where that strict check fails: after the same
identity and upstream-evidence checks, do the recomputed metrics differ from the
frozen manifest only in BEDROC floating-point leaves, by at most a fixed, tiny
amount? Its result is never acceptance, strict verification or evidence of
scientific equivalence, and the cause of any difference is not established here.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from ankora_backend.validation.screening_benchmark_primary_metrics import (
    SCHEMA_VERSION,
    _digest,
    compute_primary_metrics,
)
from ankora_backend.validation.screening_benchmark_vina_execution import (
    verify_vina_campaign_manifest,
)

# A fixed absolute diagnostic bound (2**-52), never a scientific threshold. It is
# not a fixed number of units in the last place: BEDROC values near zero have far
# smaller spacing, so the same bound spans many more ULP there. The six Linux
# differences observed for the current frozen manifest were 1-4 ULP of their own
# values, at most 8.326672684688674e-17 (3 * 2**-55); that observation applies to
# those six entries only, not to BEDROC values in general.
DIAGNOSTIC_BEDROC_ABSOLUTE_TOLERANCE = 2.0**-52
# The only eligible leaves: exact known schema paths with canonical non-negative indices.
_BEDROC_LEAF_PATH = re.compile(
    r"estimate\."
    r"(?:targets\[(?:0|[1-9][0-9]*)\]\.(?:point\.bedroc|intervals\.bedroc\.(?:lower|upper))"
    r"|macro_point\.bedroc"
    r"|macro_intervals\.bedroc\.(?:lower|upper))"
)
DIAGNOSTIC_SCOPE = (
    "Diagnostic comparison only: not strict verification, not acceptance and not "
    "evidence of scientific equivalence. The cause of any difference is not established."
)
Classification = Literal[
    "identical",
    "bounded_bedroc_float_differences_only",
    "exact_discrepancy",
]


class PrimaryMetricsDiagnosticError(ValueError):
    """The comparison cannot be made: identity, structure or numbers are invalid."""


@dataclass(frozen=True)
class FloatDifference:
    path: str
    recorded: float
    recomputed: float
    absolute_difference: float


@dataclass(frozen=True)
class PrimaryMetricsDiagnostic:
    manifest_file_sha256: str
    recorded_manifest_sha256: str
    recomputed_manifest_sha256: str
    tolerance: float
    bounded_bedroc_differences: tuple[FloatDifference, ...]
    exact_discrepancies: tuple[str, ...]
    classification: Classification
    scope: str = field(default=DIAGNOSTIC_SCOPE)


def diagnose_primary_metrics_manifest(
    path: Path,
    *,
    expected_file_sha256: str,
    primary_result_path: Path,
    primary_plan_path: Path,
) -> PrimaryMetricsDiagnostic:
    """Compare a frozen manifest with metrics recomputed from strictly verified evidence.

    ``expected_file_sha256`` only proves that the bytes are the ones the caller
    chose. Trust therefore depends on selecting it independently (for example
    from a reviewed record), never by hashing the file being diagnosed.
    """

    if not _is_sha256(expected_file_sha256):
        raise PrimaryMetricsDiagnosticError("The anchor must be a lowercase SHA-256.")
    try:
        content = path.read_bytes()
    except OSError as error:
        raise PrimaryMetricsDiagnosticError(f"Could not read {path.name}.") from error
    file_sha256 = hashlib.sha256(content).hexdigest()
    if file_sha256 != expected_file_sha256:
        raise PrimaryMetricsDiagnosticError(
            "The manifest bytes do not match the caller-supplied SHA-256 anchor."
        )
    recorded = _strict_json_object(content)
    if recorded.get("schema_version") != SCHEMA_VERSION:
        raise PrimaryMetricsDiagnosticError("Unsupported primary metric manifest schema.")
    recorded_sha256 = recorded.get("manifest_sha256")
    unsigned = {key: value for key, value in recorded.items() if key != "manifest_sha256"}
    if not isinstance(recorded_sha256, str) or _digest(unsigned) != recorded_sha256:
        raise PrimaryMetricsDiagnosticError(
            "The manifest content differs from its recorded manifest_sha256."
        )
    _require_finite(recorded, "recorded")

    # The existing strict upstream verification; any failure propagates unchanged.
    source = verify_vina_campaign_manifest(
        primary_result_path, plan_manifest_path=primary_plan_path
    )
    for key, source_key in (
        ("source_primary_vina_result_manifest_sha256", "manifest_sha256"),
        ("source_vina_campaign_plan_sha256", "source_vina_campaign_plan_sha256"),
    ):
        if recorded.get(key) != source.get(source_key):
            raise PrimaryMetricsDiagnosticError(
                f"The manifest's {key} does not name the verified source evidence."
            )
    recomputed = compute_primary_metrics(source)
    _require_finite(recomputed, "recomputed")

    bounded: list[FloatDifference] = []
    exact: list[str] = []
    _compare(
        {key: value for key, value in recorded.items() if key != "manifest_sha256"},
        {key: value for key, value in recomputed.items() if key != "manifest_sha256"},
        "",
        bounded,
        exact,
    )
    recomputed_sha256 = recomputed["manifest_sha256"]
    if not bounded and not exact and recomputed_sha256 != recorded_sha256:
        exact.append("manifest_sha256: equal content with a different digest")
    classification: Classification
    if exact:
        classification = "exact_discrepancy"
    elif bounded:
        classification = "bounded_bedroc_float_differences_only"
    else:
        classification = "identical"
    return PrimaryMetricsDiagnostic(
        manifest_file_sha256=file_sha256,
        recorded_manifest_sha256=recorded_sha256,
        recomputed_manifest_sha256=recomputed_sha256,
        tolerance=DIAGNOSTIC_BEDROC_ABSOLUTE_TOLERANCE,
        bounded_bedroc_differences=tuple(bounded),
        exact_discrepancies=tuple(exact),
        classification=classification,
    )


def is_bedroc_float_leaf(path: str) -> bool:
    """True only for the six known BEDROC point/interval schema paths in ``estimate``."""
    return _BEDROC_LEAF_PATH.fullmatch(path) is not None


def _compare(
    recorded: Any,
    recomputed: Any,
    path: str,
    bounded: list[FloatDifference],
    exact: list[str],
) -> None:
    if type(recorded) is not type(recomputed):
        raise PrimaryMetricsDiagnosticError(
            f"{path or '<root>'}: type {type(recorded).__name__} differs from "
            f"recomputed {type(recomputed).__name__}."
        )
    if isinstance(recorded, dict):
        if set(recorded) != set(recomputed):
            missing = sorted(set(recomputed) - set(recorded))
            extra = sorted(set(recorded) - set(recomputed))
            raise PrimaryMetricsDiagnosticError(
                f"{path or '<root>'}: missing fields {missing}, extra fields {extra}."
            )
        for key in sorted(recorded):
            _compare(
                recorded[key], recomputed[key], f"{path}.{key}" if path else key, bounded, exact
            )
        return
    if isinstance(recorded, list):
        if len(recorded) != len(recomputed):
            raise PrimaryMetricsDiagnosticError(
                f"{path}: {len(recorded)} recorded items, {len(recomputed)} recomputed."
            )
        for index, (left, right) in enumerate(zip(recorded, recomputed, strict=True)):
            _compare(left, right, f"{path}[{index}]", bounded, exact)
        return
    if recorded == recomputed:
        return
    if isinstance(recorded, float) and is_bedroc_float_leaf(path):
        difference = abs(recorded - recomputed)
        if difference <= DIAGNOSTIC_BEDROC_ABSOLUTE_TOLERANCE:
            bounded.append(FloatDifference(path, recorded, recomputed, difference))
            return
    exact.append(f"{path}: recorded {recorded!r}, recomputed {recomputed!r}")


def _strict_json_object(content: bytes) -> dict[str, Any]:
    def reject_constant(name: str) -> Any:
        raise PrimaryMetricsDiagnosticError(f"Non-finite JSON number {name} is not allowed.")

    def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        keys = [key for key, _ in pairs]
        if len(keys) != len(set(keys)):
            raise PrimaryMetricsDiagnosticError("Duplicate JSON object keys are not allowed.")
        return dict(pairs)

    try:
        value = json.loads(
            content.decode("utf-8"),
            parse_constant=reject_constant,
            object_pairs_hook=unique_object,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise PrimaryMetricsDiagnosticError("The manifest is not valid UTF-8 JSON.") from error
    if not isinstance(value, dict):
        raise PrimaryMetricsDiagnosticError("The manifest must be a JSON object.")
    return value


def _require_finite(value: Any, label: str, path: str = "") -> None:
    if isinstance(value, float) and not math.isfinite(value):
        raise PrimaryMetricsDiagnosticError(f"{label} {path}: non-finite number.")
    if isinstance(value, dict):
        for key, item in value.items():
            _require_finite(item, label, f"{path}.{key}" if path else key)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _require_finite(item, label, f"{path}[{index}]")


def _is_sha256(value: str) -> bool:
    return len(value) == 64 and all(character in "0123456789abcdef" for character in value)
