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

from pydantic import BaseModel, ConfigDict, Field

from ankora_backend.schemas.results_catalog import ReproducibilityAssessment


class ExportKind(StrEnum):
    CAMPAIGN = "campaign"
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
    analysis_id: str | None = None
    ligand_id: str | None = None
    # New campaign manifests carry comparison evidence. The boolean remains
    # readable only so pre-assessment exports can still be catalogued; it is
    # never promoted into a measured claim.
    reproducibility: ReproducibilityAssessment | None = None
    bitwise_reproducible: bool | None = None

    directory: str = Field(min_length=1)
    """Where the payload was written."""

    outside_project: bool = False
    files: list[ExportFile] = Field(default_factory=list)


class ExportPage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entries: list[ExportEntry] = Field(default_factory=list)
    total: int = Field(ge=0)
    offset: int = Field(ge=0)
    limit: int = Field(ge=1)
