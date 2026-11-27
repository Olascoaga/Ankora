"""Regression tests for Unit 4 (D5-007, D5-018, D7-012):
- Explicit root binding and failure warning for campaign methods.md rendering (D5-007).
- Missing analog library/selection/search/catalog warnings and wired M2/M3/M4 methods (D5-018).
- ExportCatalogService preserving consensus deterministic reproducibility metadata (D7-012).

All records and manifests in this module are explicitly labelled synthetic fixtures.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from ankora_backend.schemas.exports import ConsensusReproducibilityMetadata, ExportKind
from ankora_backend.services.campaign_export import (
    _methods_markdown,
    collect_analog_expansion_evidence,
)
from ankora_backend.services.export_catalog import ExportCatalogService


def test_d5_007_methods_markdown_binds_explicit_root_and_returns_warning_on_failure(
    tmp_path: Path,
) -> None:
    """D5-007: _methods_markdown uses explicit root (ignoring process env) and returns
    a structured methods_report_unavailable warning when rendering fails."""
    missing_batch = str(uuid4())
    markdown, warning = _methods_markdown(tmp_path, "default", "vina_batch", missing_batch)
    assert markdown is None
    assert warning is not None
    assert warning["kind"] == "methods_report_unavailable"
    assert warning["identity"] == f"vina_batch:{missing_batch}"


def test_d5_018_analog_evidence_reports_missing_library_and_records(tmp_path: Path) -> None:
    """D5-018: Missing analog library emits structured collection_warning instead of silent drop."""
    export_dir = tmp_path / "export_out"
    export_dir.mkdir(parents=True)
    missing_lib = str(uuid4())
    artifacts, prov, warnings, _, _, _ = collect_analog_expansion_evidence(
        root=tmp_path,
        binding_site_id=None,
        library_id=missing_lib,
        export_directory=export_dir,
    )
    assert artifacts == []
    assert prov is None
    assert any(
        w["kind"] == "analog_library_unreadable" and w["identity"] == missing_lib
        for w in warnings
    )


def test_d7_012_export_catalog_preserves_consensus_reproducibility_metadata(
    tmp_path: Path,
) -> None:
    """D7-012: ExportCatalogService preserves deterministic_rank_space_consensus metadata
    instead of silently dropping it to None via ValidationError."""
    export_id = str(uuid4())
    cons_id = str(uuid4())
    panel_sha = "a" * 64
    exp_dir = tmp_path / "projects" / "default" / "exports" / export_id
    exp_dir.mkdir(parents=True)
    manifest_payload = {
        "exported_at": datetime(2026, 11, 26, 18, 0, tzinfo=UTC).isoformat(),
        "ankora_export_format": 5,
        "source_kind": "consensus_run",
        "source_id": cons_id,
        "engine": {"name": "Ankora PC-Q", "version": "0.2.0"},
        "counts": {"total_parents": 10, "full_profile": 9, "partial_or_unscored": 1},
        "reproducibility": {
            "status": "deterministic_rank_space_consensus",
            "reference_panel_sha256": panel_sha,
            "tie_policy": "E3_canonical_coordinate_sha256",
            "failure_policy": "E6_no_imputation_retained_denominator",
            "note": "Deterministic rank-space aggregation over frozen reference panel.",
        },
        "bundle": {
            "export_id": export_id,
            "catalog_id": f"consensus_run:{cons_id}",
            "display_name": "Synthetic Consensus Export",
            "input_identity_sha256": "b" * 64,
            "bundle_identity_sha256": "c" * 64,
            "archive_filename": "Ankora_consensus_bundle.zip",
        },
    }
    (exp_dir / "manifest.json").write_text(json.dumps(manifest_payload), encoding="utf-8")

    catalog = ExportCatalogService(root=tmp_path)
    page = catalog.list_exports(kind=ExportKind.CONSENSUS)
    assert len(page.entries) == 1
    entry = page.entries[0]
    assert isinstance(entry.reproducibility, ConsensusReproducibilityMetadata)
    assert entry.reproducibility.status == "deterministic_rank_space_consensus"
    assert entry.reproducibility.reference_panel_sha256 == panel_sha
    assert entry.reproducibility.tie_policy == "E3_canonical_coordinate_sha256"
