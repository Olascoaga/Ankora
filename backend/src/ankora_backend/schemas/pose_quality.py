"""Schemas for create-only coupled pose-plausibility and strain records (M3)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from ankora_backend.adapters.quality.conformational_strain import (
    DEFAULT_CONFORMER_BUDGET,
    DEFAULT_CONFORMER_SEED,
    DEFAULT_STRAIN_FLAG_THRESHOLD_KCAL_MOL,
)
from ankora_backend.schemas.pose_interactions import PoseReference
from ankora_backend.schemas.provenance import ProvenanceEvent
from ankora_backend.schemas.v02_contracts import PoseAssessment
from ankora_backend.schemas.warnings import StructuredWarning


class PoseQualityRequest(BaseModel):
    """Explicit opt-in request to assess one exact saved pose."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    include_strain: bool = True
    conformer_seed: int = Field(default=DEFAULT_CONFORMER_SEED, ge=1, le=2_147_483_647)
    conformer_budget: int = Field(default=DEFAULT_CONFORMER_BUDGET, ge=1, le=200)
    strain_flag_threshold_kcal_mol: float = Field(
        default=DEFAULT_STRAIN_FLAG_THRESHOLD_KCAL_MOL,
        gt=0.0,
        le=500.0,
    )


class PoseQualityRecord(BaseModel):
    """Immutable create-only physical plausibility and strain assessment record."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    assessment_id: str = Field(min_length=1)
    created_at: datetime
    catalog_id: str = Field(min_length=1)
    engine_key: str = Field(min_length=1)
    record_id: str = Field(min_length=1)
    engine_label: str = Field(min_length=1)
    ligand_id: str = Field(min_length=1)
    ligand_preparation_id: str = Field(min_length=1)
    conformer_id: str = Field(min_length=1)
    conformer_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    parent_state_id: str = Field(min_length=1)
    receptor_id: str = Field(min_length=1)
    docking_receptor_artifact_id: str = Field(min_length=1)
    docking_receptor_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    analysis_receptor_artifact_id: str = Field(min_length=1)
    analysis_receptor_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    materialized_coupled_receptor_sha256: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )
    pose: PoseReference
    posebusters_version: str = Field(min_length=1)
    assessment: PoseAssessment
    passed_count: int = Field(ge=0)
    failed_count: int = Field(ge=0)
    not_applicable_count: int = Field(ge=0)
    not_evaluable_count: int = Field(ge=0)
    warnings: list[StructuredWarning] = Field(default_factory=list)
    provenance: ProvenanceEvent
