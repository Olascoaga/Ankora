"""Redocking validation contracts (M7).

Redocking asks whether a configuration recovers a known crystallographic pose.
It reports **two separate verdicts**, because on the project's own reference
case they disagreed: AutoDock4 found the 7AQF/RV2 pose to 0.490 A and then
ranked a wrong pose above it, so a single pass/fail would have called a working
search a failure, or a broken ranking a success.

* **Sampling success** - some pose recovered the reference. The search can find
  it.
* **Ranking success** - the pose the engine put first recovered the reference.
  The scoring function can pick it.

A pass means only that the evaluated configuration recovered the reference pose
under the stated threshold. It is not a statement about the engine in general,
about other targets, or about affinity.
"""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from ankora_backend.schemas.provenance import ProvenanceEvent
from ankora_backend.schemas.warnings import StructuredWarning


class RedockingOutcome(StrEnum):
    """What a run demonstrated, never collapsed into one word."""

    RECOVERED_AND_RANKED = "recovered_and_ranked"
    """The top pose recovered the reference. Both verdicts pass."""

    RECOVERED_BUT_MISRANKED = "recovered_but_misranked"
    """The reference pose was found but something else was ranked above it."""

    NOT_RECOVERED = "not_recovered"
    """No pose reached the threshold. The search did not find it."""


class RedockingPose(BaseModel):
    """One docked pose measured against the reference."""

    model_config = ConfigDict(extra="forbid")

    run: int = Field(ge=1)
    rank: int = Field(ge=1)
    binding_energy_kcal_mol: float
    rmsd_angstrom: float = Field(ge=0)
    recovered: bool


class RedockingMetrics(BaseModel):
    """The measures `REDOCKING_VALIDATION.md` asks for.

    Every RMSD here is computed **in place**: the pose is never superimposed on
    the reference first. Superimposing answers "is this the same shape", which a
    wrong binding mode passes easily - measured at 1.330 A for a pose actually
    sitting 10.717 A away.
    """

    model_config = ConfigDict(extra="forbid")

    threshold_angstrom: float = Field(gt=0)
    pose_count: int = Field(ge=1)
    top1_rmsd_angstrom: float = Field(ge=0)
    best_top5_rmsd_angstrom: float = Field(ge=0)
    best_overall_rmsd_angstrom: float = Field(ge=0)
    # The rank of the first pose that reached the threshold, or None when none
    # did. This is how far down a scientist would have had to look.
    first_recovering_rank: int | None = Field(default=None, ge=1)
    recovered_pose_count: int = Field(ge=0)
    sampling_success: bool
    ranking_success: bool
    outcome: RedockingOutcome


class RedockingRunRecord(BaseModel):
    """One validation of one docking result against one reference pose."""

    model_config = ConfigDict(extra="forbid")

    validation_id: str = Field(min_length=1)
    created_at: datetime
    reference_case: str | None = None
    """The documented case this reproduces, when it is one of them."""

    receptor_id: str = Field(min_length=1)
    binding_site_id: str = Field(min_length=1)
    # What was validated, and which engine produced it. A redocking result is
    # about a configuration, not about a program in the abstract.
    source_kind: str = Field(pattern=r"^(autodock4_job|autodock_gpu_job|vina_job)$")
    source_id: str = Field(min_length=1)
    engine: str = Field(min_length=1)
    engine_version: str = Field(min_length=1)
    bitwise_reproducible: bool
    # The crystallographic pose, read from the immutable original rather than
    # from anything Ankora derived.
    reference_ligand_id: str = Field(min_length=1)
    reference_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    reference_heavy_atom_count: int = Field(ge=1)
    metrics: RedockingMetrics
    poses: list[RedockingPose] = Field(min_length=1)
    warnings: list[StructuredWarning] = Field(default_factory=list)
    provenance: ProvenanceEvent | None = None


class RedockingValidationRequest(BaseModel):
    """Validate one docking result against one crystallographic pose.

    The reference is named by ligand rather than uploaded: it has to be a pose
    Ankora already preserved untouched, so the thing being validated against is
    itself traceable.
    """

    model_config = ConfigDict(extra="forbid")

    source_kind: str = Field(
        pattern=r"^(autodock4_job|autodock_gpu_job|vina_job)$"
    )
    source_id: str = Field(min_length=1)
    reference_ligand_id: str = Field(min_length=1)
    threshold_angstrom: float = Field(default=2.0, gt=0, le=20)
    reference_case: str | None = None
