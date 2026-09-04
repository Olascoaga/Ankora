"""The project-level result catalog (M6).

A **read model**, never a second scientific truth. Every entry references the
authoritative record that produced it by id and hash; nothing here copies a
pose, rewrites a log, or recomputes a number.

Two boundaries the shapes enforce:

* **A listing carries no results.** A completed campaign record is megabytes of
  poses, and the real project holds 25 MiB across nine of them. A catalog page
  is identity and counts; compounds are a separate, paginated request, and poses
  stay with the engine-native endpoints that own them.
* **Nothing is ordered across engines.** Default order is newest first. Ordering
  a mixed list by "best score" would rank a Vina score against an AutoDock4
  binding energy, which `DOCKING_POLICY.md` forbids and which no column here
  makes possible.
"""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ResultMode(StrEnum):
    SINGLE_LIGAND = "single_ligand"
    SCREENING = "screening"


class ScoringFamily(StrEnum):
    """What produced the number, which is what may never be merged."""

    VINA = "vina"
    AUTODOCK4 = "autodock4"


class ReproducibilityStatus(StrEnum):
    """What exact recorded repeats established for one protocol fingerprint."""

    MEASURED_REPRODUCIBLE = "measured_reproducible"
    MEASURED_VARIABLE = "measured_variable"
    NOT_ASSESSED = "not_assessed"


class ReproducibilityExecution(BaseModel):
    model_config = ConfigDict(extra="forbid")

    catalog_id: str = Field(min_length=1)
    output_fingerprint_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class ReproducibilityAssessment(BaseModel):
    """A comparison result, never an engine-level assumption.

    The input fingerprint groups only the same engine/backend, exact recorded
    inputs, tool identity, and protocol. Output fingerprints cover parsed
    scientific values plus retained pose-artifact byte hashes; logs and timing
    are deliberately outside this scope.
    """

    model_config = ConfigDict(extra="forbid")

    status: ReproducibilityStatus = ReproducibilityStatus.NOT_ASSESSED
    protocol: str = "ankora-reproducibility-v1"
    scope: str = "parsed scientific outputs and retained pose-artifact bytes"
    input_fingerprint_sha256: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )
    executions: list[ReproducibilityExecution] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_measured_evidence(self) -> "ReproducibilityAssessment":
        fingerprints = {
            execution.output_fingerprint_sha256 for execution in self.executions
        }
        if self.status is ReproducibilityStatus.NOT_ASSESSED:
            return self
        if self.input_fingerprint_sha256 is None or len(self.executions) < 2:
            raise ValueError("A measured status requires two exact comparable executions.")
        if (
            self.status is ReproducibilityStatus.MEASURED_REPRODUCIBLE
            and len(fingerprints) != 1
        ):
            raise ValueError("Measured reproducibility requires equal output fingerprints.")
        if (
            self.status is ReproducibilityStatus.MEASURED_VARIABLE
            and len(fingerprints) < 2
        ):
            raise ValueError("Measured variability requires different output fingerprints.")
        return self


class CatalogEntry(BaseModel):
    """One durable experiment, described without any of its results.

    Enough identity to make cross-experiment interpretation an explicit act
    rather than an accident: the spec requires that a reader can always tell
    which receptor, which box, which selection and which executable.
    """

    model_config = ConfigDict(extra="forbid")

    catalog_id: str = Field(min_length=1)
    """`{engine_key}:{record_id}` - stable, and it names its own source."""

    engine_key: str = Field(min_length=1)
    record_id: str = Field(min_length=1)
    mode: ResultMode
    scoring_family: ScoringFamily
    # Two backends of one scoring family are still two executions.
    backend: str | None = None
    engine_label: str = Field(min_length=1)
    """What the interface shows: `AutoDock4 4.2.6 · CPU`."""

    engine_version: str = Field(min_length=1)
    executable_sha256: str | None = None
    device_name: str | None = None
    reproducibility: ReproducibilityAssessment = Field(
        default_factory=ReproducibilityAssessment
    )

    status: str = Field(min_length=1)
    created_at: datetime
    completed_at: datetime | None = None

    receptor_id: str = Field(min_length=1)
    binding_site_id: str = Field(min_length=1)
    box: dict[str, float] = Field(default_factory=dict)
    map_set_id: str | None = None
    map_set_identity_key: str | None = None

    library_id: str | None = None
    filter_run_id: str | None = None
    selection_manifest_sha256: str | None = None
    ligand_id: str | None = None

    selected_count: int = Field(ge=0)
    succeeded_count: int = Field(ge=0)
    failed_count: int = Field(ge=0)
    canceled_count: int = Field(ge=0)
    # This engine's own best number, only ever meaningful beside `engine_label`.
    best_result_kcal_mol: float | None = None
    best_molecule: str | None = None


class CatalogPage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entries: list[CatalogEntry] = Field(default_factory=list)
    total: int = Field(ge=0)
    offset: int = Field(ge=0)
    limit: int = Field(ge=1)


class TrashResultCampaignsRequest(BaseModel):
    """One explicit, bounded removal operation over complete result records."""

    model_config = ConfigDict(extra="forbid")

    catalog_ids: list[str] = Field(min_length=1, max_length=100)
    acknowledge_removal: bool = False


class TrashedResultCampaign(BaseModel):
    model_config = ConfigDict(extra="forbid")

    catalog_id: str = Field(min_length=1)
    engine_label: str = Field(min_length=1)
    status: str = Field(min_length=1)


class TrashResultCampaignsResponse(BaseModel):
    """What left the active project catalog and what followed it to Trash."""

    model_config = ConfigDict(extra="forbid")

    operation_id: str = Field(min_length=1)
    trashed_at: datetime
    campaigns: list[TrashedResultCampaign] = Field(min_length=1)
    interaction_analysis_count: int = Field(ge=0)
    redocking_validation_count: int = Field(ge=0)
    exports_preserved: bool = True
    recoverable: bool = True


class CompoundRow(BaseModel):
    """One molecule inside one experiment, in that engine's own terms."""

    model_config = ConfigDict(extra="forbid")

    ligand_id: str = Field(min_length=1)
    parent_compound_id: str | None = None
    chemical_state_id: str | None = None
    chemical_state_formal_charge: int | None = None
    # Manifest order, kept as its own column so user sorting never destroys it.
    source_index: int = Field(ge=0)
    name: str = Field(min_length=1)
    canonical_smiles: str | None = None
    molecular_weight_g_mol: float | None = None
    status: str = Field(min_length=1)
    failure_code: str | None = None
    best_result_kcal_mol: float | None = None
    # Vina counts poses; AutoDock counts clusters and the population of the top
    # one. The spec forbids fabricating either shape for the other engine.
    pose_count: int | None = None
    cluster_count: int | None = None
    top_cluster_runs: int | None = None


class CompoundPage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    catalog_id: str = Field(min_length=1)
    engine_label: str = Field(min_length=1)
    value_label: str = Field(min_length=1)
    """What the engine's own column is called, so it is never just "score"."""

    rows: list[CompoundRow] = Field(default_factory=list)
    total: int = Field(ge=0)
    offset: int = Field(ge=0)
    limit: int = Field(ge=1)
