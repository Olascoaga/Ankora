"""Audit D7 regression tests for typed export response models and OpenAPI schemas."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from ankora_backend.api.app import create_app
from ankora_backend.schemas.exports import (
    CampaignExportResponse,
    ConsensusExportResponse,
    ConsensusReproducibilityMetadata,
    ExportEntry,
    ExportKind,
)
from pydantic import ValidationError

SHA_A = "a" * 64
SHA_B = "b" * 64


def test_openapi_exposes_typed_export_response_schemas() -> None:
    schema = create_app().openapi()
    paths = schema["paths"]

    campaign_post = paths["/api/v1/exports/campaigns"]["post"]
    campaign_201 = campaign_post["responses"]["201"]["content"]["application/json"]["schema"]
    assert campaign_201.get("$ref") == "#/components/schemas/CampaignExportResponse"

    consensus_post = paths["/api/v1/consensus/runs/{consensus_id}/export"]["post"]
    consensus_201 = consensus_post["responses"]["201"]["content"]["application/json"]["schema"]
    assert consensus_201.get("$ref") == "#/components/schemas/ConsensusExportResponse"

    components = schema["components"]["schemas"]
    campaign_props = components["CampaignExportResponse"]["properties"]
    assert "redocking_validation_count" in campaign_props
    assert "stale" in campaign_props
    assert "stale_reasons" in campaign_props

    consensus_props = components["ConsensusExportResponse"]["properties"]
    assert consensus_props["ankora_export_format"]["enum"] == [5, 6]
    assert "stale" in consensus_props
    assert "stale_reasons" in consensus_props


def test_campaign_export_response_validates_strict_fields() -> None:
    payload: dict[str, Any] = {
        "exported_at": datetime.now(UTC).isoformat(),
        "source_kind": "vina_batch",
        "source_id": "batch-1",
        "export_id": "exp-1",
        "catalog_id": "vina_batch:batch-1",
        "display_name": "Synthetic campaign",
        "input_identity_sha256": SHA_A,
        "bundle_identity_sha256": SHA_B,
        "archive_filename": "Ankora_bundle.zip",
        "engine": "AutoDock Vina",
        "engine_version": "1.2.7",
        "reproducibility": {
            "status": "not_assessed",
            "protocol": "ankora-reproducibility-v1",
            "scope": "parsed scientific outputs and retained pose-artifact bytes",
            "input_fingerprint_sha256": SHA_A,
            "executions": [],
        },
        "row_count": 3,
        "interaction_analysis_count": 1,
        "figure_count": 0,
        "redocking_validation_count": 2,
        "directory": "/tmp/exp-1",
        "outside_project": False,
        "record_directory": "/tmp/exp-1",
        "files": ["manifest.json", "Ankora_bundle.zip"],
        "stale": True,
        "stale_reasons": ["Upstream receptor changed"],
    }
    parsed = CampaignExportResponse.model_validate(payload)
    assert parsed.redocking_validation_count == 2
    assert parsed.stale is True
    assert parsed.stale_reasons == ["Upstream receptor changed"]

    with pytest.raises(ValidationError):
        CampaignExportResponse.model_validate({**payload, "unexpected_field": 1})


@pytest.mark.parametrize("export_format", [5, 6])
def test_consensus_export_response_accepts_v5_and_v6(export_format: int) -> None:
    payload: dict[str, Any] = {
        "exported_at": datetime.now(UTC).isoformat(),
        "ankora_export_format": export_format,
        "source_kind": "consensus_run",
        "source_id": "cons-1",
        "export_id": "exp-cons-1",
        "catalog_id": "consensus_run:cons-1",
        "display_name": "Synthetic consensus",
        "input_identity_sha256": SHA_A,
        "bundle_identity_sha256": SHA_B,
        "archive_filename": "Ankora_consensus.zip",
        "variant_id": "pcq-core-v1",
        "row_count": 5,
        "full_profile_count": 4,
        "partial_or_unscored_count": 1,
        "pose_quality_count": 2,
        "interaction_rule_evaluation_count": 1,
        "directory": "/tmp/exp-cons-1",
        "outside_project": False,
        "record_directory": "/tmp/exp-cons-1",
        "files": ["manifest.json", "Ankora_consensus.zip"],
        "stale": False,
        "stale_reasons": [],
    }
    parsed = ConsensusExportResponse.model_validate(payload)
    assert parsed.ankora_export_format == export_format

    with pytest.raises(ValidationError):
        ConsensusExportResponse.model_validate({**payload, "ankora_export_format": 4})


def test_export_entry_accepts_consensus_reproducibility_metadata() -> None:
    entry = ExportEntry(
        export_id="exp-cons-2",
        kind=ExportKind.CONSENSUS,
        exported_at=datetime.now(UTC),
        title="Synthetic consensus export",
        subtitle="4/5 parents full-profile",
        catalog_id="consensus_run:cons-1",
        source_kind="consensus_run",
        source_id="cons-1",
        input_identity_sha256=SHA_A,
        bundle_identity_sha256=SHA_B,
        archive_filename="Ankora_consensus.zip",
        reproducibility=ConsensusReproducibilityMetadata(
            reference_panel_sha256=SHA_A,
            tie_policy="average_rank",
            failure_policy="no_imputation",
        ),
        directory="/tmp/exp-cons-2",
        ankora_export_format=6,
    )
    assert isinstance(entry.reproducibility, ConsensusReproducibilityMetadata)
    assert entry.reproducibility.status == "deterministic_rank_space_consensus"
