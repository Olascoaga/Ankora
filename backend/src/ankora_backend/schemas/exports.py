"""Everything this project has sent out of Ankora (workflow step 8).

Exports were written to be found again — a campaign bundle, a publication
figure and a ligand-receptor complex each record where they came from — but
nothing could enumerate them. A read model over the three kinds closes that,
the same way the result catalog closed it for campaigns.

Two boundaries the shapes enforce:

* **A listing carries no payloads.** A bundle holds a results table, a ZIP and
  recorded evidence; an entry carries names, sizes and provenance, and the
  files stay behind their own request.
* **A file written outside the project is named, not offered.** A figure saved
  into a manuscript folder is not Ankora's to serve, and a download link that
  404s is worse than no link.
"""

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from ankora_backend.schemas.results_catalog import ReproducibilityAssessment


class ConsensusReproducibilityMetadata(BaseModel):
    """Typed reproducibility metadata recorded on ADR-030 consensus export bundles (D7-012)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    status: Literal["deterministic_rank_space_consensus"] = "deterministic_rank_space_consensus"
    reference_panel_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    tie_policy: str | None = None
    failure_policy: str | None = None
    note: str | None = None


class ExportKind(StrEnum):
    CAMPAIGN = "campaign"
    CONSENSUS = "consensus"
    FIGURE = "figure"
    POSE_COMPLEX = "pose_complex"


class ExportFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    filename: str = Field(min_length=1)
    size_bytes: int = Field(ge=0)
    # Null when the file lives in a folder the scientist chose: the project
    # recorded that it was written, and has no claim to hand it back.
    content_url: str | None = None


class ExportEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    export_id: str = Field(min_length=1)
    kind: ExportKind
    exported_at: datetime
    title: str = Field(min_length=1)
    """What this is, in the reader's terms rather than an identifier."""

    subtitle: str = ""
    # What it came from, so an export is never an orphan file.
    catalog_id: str | None = None
    source_kind: str | None = None
    source_id: str | None = None
    display_name: str | None = Field(default=None, min_length=1, max_length=80)
    input_identity_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    bundle_identity_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    archive_filename: str | None = None
    analysis_id: str | None = None
    ligand_id: str | None = None
    # New campaign manifests carry comparison evidence; consensus manifests carry
    # deterministic rank-space metadata (D7-012). The boolean remains readable only
    # so pre-assessment exports can still be catalogued.
    reproducibility: ReproducibilityAssessment | ConsensusReproducibilityMetadata | None = None
    bitwise_reproducible: bool | None = None

    directory: str = Field(min_length=1)
    """Where the payload was written."""

    ankora_export_format: int | None = Field(default=None, ge=1)
    outside_project: bool = False
    files: list[ExportFile] = Field(default_factory=list)


class ExportPage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entries: list[ExportEntry] = Field(default_factory=list)
    total: int = Field(ge=0)
    offset: int = Field(ge=0)
    limit: int = Field(ge=1)


class CampaignExportResponse(BaseModel):
    """Typed receipt returned by POST /api/v1/exports/campaigns (D7-005)."""

    model_config = ConfigDict(extra="forbid")

    exported_at: datetime
    source_kind: str = Field(min_length=1)
    source_id: str = Field(min_length=1)
    export_id: str = Field(min_length=1)
    catalog_id: str = Field(min_length=1)
    display_name: str | None = None
    input_identity_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    bundle_identity_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    archive_filename: str = Field(min_length=1)
    engine: str = Field(min_length=1)
    engine_version: str = Field(min_length=1)
    reproducibility: ReproducibilityAssessment
    row_count: int = Field(ge=0)
    interaction_analysis_count: int = Field(ge=0)
    figure_count: int = Field(ge=0)
    redocking_validation_count: int = Field(ge=0)
    directory: str = Field(min_length=1)
    outside_project: bool = False
    record_directory: str = Field(min_length=1)
    files: list[str] = Field(default_factory=list)
    stale: bool = False
    stale_reasons: list[str] = Field(default_factory=list)


class ConsensusExportResponse(BaseModel):
    """Typed receipt returned by POST /api/v1/consensus/runs/{consensus_id}/export (D7-004)."""

    model_config = ConfigDict(extra="forbid")

    exported_at: datetime
    ankora_export_format: Literal[5, 6]
    source_kind: Literal["consensus_run"] = "consensus_run"
    source_id: str = Field(min_length=1)
    export_id: str = Field(min_length=1)
    catalog_id: str = Field(min_length=1)
    display_name: str | None = None
    input_identity_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    bundle_identity_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    archive_filename: str = Field(min_length=1)
    variant_id: str = Field(min_length=1)
    row_count: int = Field(ge=0)
    full_profile_count: int = Field(ge=0)
    partial_or_unscored_count: int = Field(ge=0)
    pose_quality_count: int = Field(ge=0)
    interaction_rule_evaluation_count: int = Field(ge=0)
    directory: str = Field(min_length=1)
    outside_project: bool = False
    record_directory: str = Field(min_length=1)
    files: list[str] = Field(default_factory=list)
    stale: bool = False
    stale_reasons: list[str] = Field(default_factory=list)
