"""Preregistered comparison protocol manifest contracts (ADR-031, stdlib-only).

Strictly outside `ankora_backend`: zero product imports, zero third-party dependencies.
Enforces pinned external platform identity (rejecting "latest"), mandatory two-axis
declaration (`controlled` + `end_to_end`), disjoint parent-compound active/inactive
sets, and order-invariant canonical SHA-256 sealing prior to evaluating Confirmation.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any

SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
REQUIRED_AXES = ("controlled", "end_to_end")
INSUFFICIENT_EVIDENCE_TEXT = "Insufficient evidence to prefer over baseline"


class ProtocolManifestError(ValueError):
    """Raised when a comparison protocol manifest violates ADR-031 governance."""


def canonical_json_sha256(payload: dict[str, Any]) -> str:
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _require_non_blank(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ProtocolManifestError(f"{label} must be a non-empty string")
    return value.strip()


def _require_sha256(value: Any, label: str) -> str:
    text = _require_non_blank(value, label)
    if not SHA256_RE.match(text):
        raise ProtocolManifestError(
            f"{label} must be a 64-character lowercase SHA-256 hex digest"
        )
    return text


@dataclass(frozen=True, slots=True)
class PinnedPlatformIdentity:
    """Exact version and digest pinning for a platform under comparison (ADR-031 §1)."""

    platform_name: str
    version: str
    artifact_digest: str
    raw_output_sha256s: dict[str, str]
    notes: str = ""

    def __post_init__(self) -> None:
        name = _require_non_blank(self.platform_name, "platform_name")
        version = _require_non_blank(self.version, f"{name}.version")
        if version.lower() in {
            "latest",
            "main",
            "master",
            "head",
            "unpinned",
            "unknown",
        }:
            raise ProtocolManifestError(
                f"ADR-031 §1 forbids unpinned platform version {version!r} for {name}"
            )
        digest = _require_non_blank(self.artifact_digest, f"{name}.artifact_digest")
        if digest.lower() in {"latest", "none", "unknown"}:
            raise ProtocolManifestError(
                f"ADR-031 §1 forbids unpinned artifact_digest {digest!r} for {name}"
            )
        if not isinstance(self.raw_output_sha256s, dict):
            raise ProtocolManifestError(
                f"{name}.raw_output_sha256s must be an object mapping"
            )
        for key, val in self.raw_output_sha256s.items():
            _require_non_blank(key, f"{name}.raw_output_sha256s key")
            _require_sha256(val, f"{name}.raw_output_sha256s[{key}]")

    def to_dict(self) -> dict[str, Any]:
        return {
            "platform_name": self.platform_name.strip(),
            "version": self.version.strip(),
            "artifact_digest": self.artifact_digest.strip(),
            "raw_output_sha256s": dict(sorted(self.raw_output_sha256s.items())),
            "notes": self.notes.strip(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PinnedPlatformIdentity:
        return cls(
            platform_name=str(data.get("platform_name", "")),
            version=str(data.get("version", "")),
            artifact_digest=str(data.get("artifact_digest", "")),
            raw_output_sha256s=dict(data.get("raw_output_sha256s") or {}),
            notes=str(data.get("notes", "")),
        )


@dataclass(frozen=True, slots=True)
class SplitMembershipSpec:
    """Frozen parent + Bemis-Murcko Confirmation denominator (ADR-031 §3)."""

    split_identity_sha256: str
    grouping_strategy: str
    active_parent_ids: tuple[str, ...]
    inactive_parent_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        _require_sha256(self.split_identity_sha256, "split_identity_sha256")
        if self.grouping_strategy != "parent_and_murcko_scaffold":
            raise ProtocolManifestError(
                "ADR-031 §3 requires grouping_strategy == 'parent_and_murcko_scaffold'"
            )
        actives = tuple(
            _require_non_blank(p, "active_parent_id") for p in self.active_parent_ids
        )
        inactives = tuple(
            _require_non_blank(p, "inactive_parent_id")
            for p in self.inactive_parent_ids
        )
        if not actives or not inactives:
            raise ProtocolManifestError(
                "Confirmation denominator requires at least one active and one inactive parent"
            )
        if len(set(actives)) != len(actives) or len(set(inactives)) != len(inactives):
            raise ProtocolManifestError(
                "Duplicate parent IDs inside Confirmation split"
            )
        overlap = set(actives) & set(inactives)
        if overlap:
            raise ProtocolManifestError(
                f"Active and inactive parent IDs overlap: {sorted(overlap)[:5]}"
            )

    @property
    def all_parent_ids(self) -> tuple[str, ...]:
        return tuple(sorted((*self.active_parent_ids, *self.inactive_parent_ids)))

    @property
    def active_set(self) -> frozenset[str]:
        return frozenset(self.active_parent_ids)

    def to_dict(self) -> dict[str, Any]:
        return {
            "split_identity_sha256": self.split_identity_sha256,
            "grouping_strategy": self.grouping_strategy,
            "active_parent_ids": sorted(self.active_parent_ids),
            "inactive_parent_ids": sorted(self.inactive_parent_ids),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SplitMembershipSpec:
        return cls(
            split_identity_sha256=str(data.get("split_identity_sha256", "")),
            grouping_strategy=str(data.get("grouping_strategy", "")),
            active_parent_ids=tuple(data.get("active_parent_ids") or ()),
            inactive_parent_ids=tuple(data.get("inactive_parent_ids") or ()),
        )


@dataclass(frozen=True, slots=True)
class ComparisonProtocolManifest:
    """Preregistered, hash-sealed two-axis external comparison protocol (ADR-031)."""

    protocol_id: str
    target_id: str
    preregistered_at: str
    ankora_platform: PinnedPlatformIdentity
    external_platform: PinnedPlatformIdentity
    split: SplitMembershipSpec
    ankora_score_column: str = "pcq_score"
    ankora_higher_is_better: bool = True
    external_score_column: str = "score"
    external_higher_is_better: bool = True
    primary_metric: str = "bedroc_20"
    bedroc_alpha: float = 20.0
    top_fraction: float = 0.01
    bootstrap_replicates: int = 2000
    bootstrap_seed: int = 20261120
    confidence_level: float = 0.95
    axes_declared: tuple[str, ...] = REQUIRED_AXES
    schema_version: int = 1
    protocol_sha256: str = ""

    def __post_init__(self) -> None:
        _require_non_blank(self.protocol_id, "protocol_id")
        _require_non_blank(self.target_id, "target_id")
        _require_non_blank(self.preregistered_at, "preregistered_at")
        if self.schema_version != 1:
            raise ProtocolManifestError("schema_version must be 1")
        if self.primary_metric != "bedroc_20":
            raise ProtocolManifestError(
                "ADR-031 §3 fixes primary_metric == 'bedroc_20' (no post-hoc substitution)"
            )
        if self.bedroc_alpha <= 0:
            raise ProtocolManifestError("bedroc_alpha must be > 0")
        if not (0.0 < self.top_fraction <= 1.0):
            raise ProtocolManifestError("top_fraction must be in (0, 1]")
        if self.bootstrap_replicates < 100:
            raise ProtocolManifestError("bootstrap_replicates must be >= 100")
        if not (0.5 < self.confidence_level < 1.0):
            raise ProtocolManifestError("confidence_level must be in (0.5, 1.0)")
        if set(self.axes_declared) != set(REQUIRED_AXES):
            raise ProtocolManifestError(
                "ADR-031 §2 requires declaring both axes: 'controlled' and 'end_to_end'"
            )
        expected_sha = self.compute_protocol_sha256()
        if not self.protocol_sha256:
            object.__setattr__(self, "protocol_sha256", expected_sha)
        elif self.protocol_sha256 != expected_sha:
            raise ProtocolManifestError(
                f"protocol_sha256 mismatch: expected {expected_sha}, observed {self.protocol_sha256}"
            )

    def _canonical_body(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "protocol_id": self.protocol_id.strip(),
            "target_id": self.target_id.strip(),
            "preregistered_at": self.preregistered_at.strip(),
            "primary_metric": self.primary_metric,
            "bedroc_alpha": self.bedroc_alpha,
            "top_fraction": self.top_fraction,
            "bootstrap_replicates": self.bootstrap_replicates,
            "bootstrap_seed": self.bootstrap_seed,
            "confidence_level": self.confidence_level,
            "axes_declared": sorted(self.axes_declared),
            "ankora_score_column": self.ankora_score_column.strip(),
            "ankora_higher_is_better": self.ankora_higher_is_better,
            "external_score_column": self.external_score_column.strip(),
            "external_higher_is_better": self.external_higher_is_better,
            "ankora_platform": self.ankora_platform.to_dict(),
            "external_platform": self.external_platform.to_dict(),
            "split": self.split.to_dict(),
        }

    def compute_protocol_sha256(self) -> str:
        return canonical_json_sha256(self._canonical_body())

    def to_dict(self) -> dict[str, Any]:
        return {
            **self._canonical_body(),
            "protocol_sha256": self.protocol_sha256,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ComparisonProtocolManifest:
        return cls(
            schema_version=int(data.get("schema_version", 1)),
            protocol_id=str(data.get("protocol_id", "")),
            target_id=str(data.get("target_id", "")),
            preregistered_at=str(data.get("preregistered_at", "")),
            ankora_platform=PinnedPlatformIdentity.from_dict(
                dict(data.get("ankora_platform") or {})
            ),
            external_platform=PinnedPlatformIdentity.from_dict(
                dict(data.get("external_platform") or {})
            ),
            split=SplitMembershipSpec.from_dict(dict(data.get("split") or {})),
            ankora_score_column=str(data.get("ankora_score_column", "pcq_score")),
            ankora_higher_is_better=bool(data.get("ankora_higher_is_better", True)),
            external_score_column=str(data.get("external_score_column", "score")),
            external_higher_is_better=bool(data.get("external_higher_is_better", True)),
            primary_metric=str(data.get("primary_metric", "bedroc_20")),
            bedroc_alpha=float(data.get("bedroc_alpha", 20.0)),
            top_fraction=float(data.get("top_fraction", 0.01)),
            bootstrap_replicates=int(data.get("bootstrap_replicates", 2000)),
            bootstrap_seed=int(data.get("bootstrap_seed", 20261120)),
            confidence_level=float(data.get("confidence_level", 0.95)),
            axes_declared=tuple(data.get("axes_declared") or ()),
            protocol_sha256=str(data.get("protocol_sha256", "")),
        )
