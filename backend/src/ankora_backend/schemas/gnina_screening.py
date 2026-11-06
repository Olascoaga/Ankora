"""Typed contract for a GNINA library screening campaign (screening plan step 1).

This module is **contracts only**. It describes what a campaign and its entries
are allowed to say about themselves; it starts nothing, stores nothing and
verifies nothing. Persistence, orchestration and the localhost API are separate
work items of `docs/validation/GNINA_SCREENING_PLAN.md`.

**A campaign entry is a reference, not a result.** When an entry completes it
retains the identity of the GNINA single job that produced the work -
`gnina_job_id` - and nothing else about the outcome. There is deliberately no
CNNscore, no CNNaffinity, no minimized affinity and no pose on this model. The
single job already owns its poses, its raw outputs, its command, its device and
its execution evidence under the invariants in `schemas/gnina.py`; copying any
of that here would create a second, unverifiable account of a scientific result
that could drift from the job it came from. A reader wanting scores loads the
referenced job.

**A recorded link is not a verified link.** Holding a `gnina_job_id` says only
that a campaign claims that job as its attempt for that molecule. It does not
establish that the job exists, that it ran against this campaign's receptor,
box, tool build or settings, or that it published poses. Checking those is the
job of the storage layer and of the screening-evidence verifier
(`services/gnina_screening_evidence.py`), which re-reads the preserved inputs
and hashes. Nothing in this module may be read as that verification.

**Selection order is the campaign's order.** `entries` is the applied filter
selection in the order it was selected, and that order is authoritative on its
own. `source_index` is library provenance, is absent whenever the library record
could not be resolved, and is never used to sort or renumber entries - a
campaign over a reordered or sparsely indexed selection is still exactly the
campaign the scientist applied.

**Two entries may share a `source_index`.** One library row can yield several
prepared chemical states - distinct protonation microstates of one compound -
and docking two of them is a legitimate selection of two ligands. Duplicate
`ligand_id` is rejected because that would be the same prepared state selected
twice; duplicate `source_index` is not.

There is deliberately no concurrency setting. The existing GNINA service runs
one job at a time, so `worker_count` is pinned to one and recorded as a fact of
the campaign rather than offered as a knob, until bounded CPU and GPU
scheduling is implemented and tested.
"""

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ankora_backend.schemas.binding_sites import BindingBox
from ankora_backend.schemas.docking import DockingFailure, DockingJobPhase, DockingJobStatus
from ankora_backend.schemas.gnina import GninaDockingParameters, GninaToolIdentity
from ankora_backend.schemas.provenance import ProvenanceEvent
from ankora_backend.schemas.warnings import StructuredWarning

# An entry in one of these states will not change again without a new attempt.
TERMINAL_ENTRY_STATES = frozenset(
    {
        DockingJobStatus.COMPLETED,
        DockingJobStatus.FAILED,
        DockingJobStatus.CANCELED,
    }
)

# A campaign in one of these states has stopped doing work.
TERMINAL_CAMPAIGN_STATES = frozenset(
    {
        DockingJobStatus.COMPLETED,
        DockingJobStatus.FAILED,
        DockingJobStatus.CANCELED,
    }
)

# Phases that can only be reached once a GNINA single job exists.
_PHASES_REQUIRING_A_JOB = frozenset(
    {
        DockingJobPhase.DOCKING,
        DockingJobPhase.PARSING_POSES,
    }
)


class GninaScreeningPreflightCode(StrEnum):
    """Stable reasons a selected molecule never reached the engine.

    These are campaign-level refusals recorded against the entry, decided
    before any GNINA process existed. They are failures rather than silent
    omissions: every selected molecule stays represented in selection order,
    so a scientist reading a finished campaign can see that a selection of 40
    docked 37 and why the other three did not.
    """

    LIBRARY_RECORD_MISSING = "GNINA_SCREENING_LIBRARY_RECORD_MISSING"
    LIGAND_NOT_PREPARED = "GNINA_SCREENING_LIGAND_NOT_PREPARED"
    LIGAND_INPUT_STALE = "GNINA_SCREENING_LIGAND_INPUT_STALE"


class GninaScreeningSelection(BaseModel):
    """The immutable identity of the applied filter selection being docked.

    Frozen because this is what makes two campaigns comparable or not. The
    filter run alone is not enough - two runs can select the same molecules -
    so the selection is pinned by the manifest artifact and its hash. Rewriting
    any of it on a live campaign would silently change what the campaign claims
    to have screened, so the model refuses the assignment outright.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    library_id: str = Field(min_length=1)
    filter_run_id: str = Field(min_length=1)
    manifest_artifact_id: str = Field(min_length=1)
    manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class GninaScreeningRequest(BaseModel):
    """What the scientist asked for, with GNINA's own settings.

    The parameters are the single-job parameters unchanged. GNINA settings stay
    GNINA-specific, and one campaign applies one search protocol to every
    molecule, so there is nothing campaign-shaped to add - including `compute`,
    which stays an explicit choice because discovering a GPU does not authorize
    a silent fallback.
    """

    model_config = ConfigDict(extra="forbid", revalidate_instances="always")

    receptor_id: str = Field(min_length=1)
    binding_site_id: str = Field(min_length=1)
    library_id: str = Field(min_length=1)
    filter_run_id: str = Field(min_length=1)
    parameters: GninaDockingParameters
    acknowledge_inputs_and_scoring: bool = False

    @model_validator(mode="after")
    def require_explicit_acknowledgement(self) -> "GninaScreeningRequest":
        if not self.acknowledge_inputs_and_scoring:
            raise ValueError("acknowledge_inputs_and_scoring must be true before screening")
        return self


class GninaScreeningEntry(BaseModel):
    """One selected molecule's place in the campaign, and its attempt so far.

    Carries identity and lifecycle only. See the module docstring for why no
    score or pose appears here.
    """

    model_config = ConfigDict(extra="forbid", revalidate_instances="always")

    # The exact prepared ligand state selected. Unique within a campaign.
    ligand_id: str = Field(min_length=1)
    chemical_state_id: str | None = None
    # Library provenance, absent when the library record could not be
    # resolved. Never used to order entries.
    source_index: int | None = Field(default=None, ge=0)
    name: str | None = Field(default=None, min_length=1)
    ligand_preparation_id: str | None = Field(default=None, min_length=1)
    ligand_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    conformer_id: str | None = Field(default=None, min_length=1)
    conformer_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    status: DockingJobStatus
    phase: DockingJobPhase
    # The GNINA single job claimed as this molecule's attempt. Recorded, not
    # verified; absent while queued and absent for a preflight failure.
    gnina_job_id: str | None = Field(default=None, min_length=1)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    failure: DockingFailure | None = None
    revision: int = Field(default=0, ge=0)

    @property
    def is_terminal(self) -> bool:
        return self.status in TERMINAL_ENTRY_STATES

    @property
    def is_preflight_failure(self) -> bool:
        """A refusal recorded before any GNINA job existed for this molecule."""
        return self.status is DockingJobStatus.FAILED and self.gnina_job_id is None

    @model_validator(mode="after")
    def keep_lifecycle_and_identity_consistent(self) -> "GninaScreeningEntry":
        if (self.failure is not None) != (self.status is DockingJobStatus.FAILED):
            raise ValueError(
                "a screening entry carries a failure exactly when its status is 'failed'"
            )
        if self.status is DockingJobStatus.COMPLETED:
            if self.gnina_job_id is None:
                raise ValueError("a completed screening entry must retain its GNINA single-job id")
            if self.phase is not DockingJobPhase.COMPLETE:
                raise ValueError("a completed screening entry must be in the 'complete' phase")
            # A campaign cannot have docked a molecule whose library record and
            # prepared state it never resolved.
            if self.source_index is None:
                raise ValueError("a completed screening entry requires its library 'source_index'")
            if (
                self.chemical_state_id is None
                or self.ligand_preparation_id is None
                or self.ligand_sha256 is None
                or self.conformer_id is None
                or self.conformer_sha256 is None
            ):
                raise ValueError(
                    "a completed screening entry requires its chemical state, preparation "
                    "and conformer identities and hashes"
                )
        elif self.phase is DockingJobPhase.COMPLETE and not self.is_terminal:
            raise ValueError("only a terminal screening entry may be in the 'complete' phase")
        if self.status is DockingJobStatus.QUEUED and self.phase is not DockingJobPhase.QUEUED:
            raise ValueError("a queued screening entry must be in the 'queued' phase")
        if self.phase in _PHASES_REQUIRING_A_JOB and self.gnina_job_id is None:
            raise ValueError(f"phase '{self.phase.value}' requires a GNINA single-job id")
        # Resolution precedes execution: an unresolved molecule cannot be the
        # one currently docking.
        if self.source_index is None and self.status in {
            DockingJobStatus.RUNNING,
            DockingJobStatus.CANCEL_REQUESTED,
        }:
            raise ValueError("a screening entry without a library 'source_index' cannot be running")
        if self.completed_at is not None and not self.is_terminal:
            raise ValueError("only a terminal screening entry may record 'completed_at'")
        if self.is_terminal and self.completed_at is None:
            raise ValueError("a terminal screening entry must record its completion time")
        return self


class GninaScreeningProgress(BaseModel):
    """A campaign's header without its entries, for incremental storage and polling.

    A campaign is polled while it runs and its entry list only grows, so the
    poll target deliberately carries no entries at all: the counts and the
    revision are what a progress indicator needs, and resending every entry on
    every poll would make the cheap question expensive. A caller that wants the
    entries loads the record.
    """

    model_config = ConfigDict(extra="forbid")

    campaign_id: str = Field(min_length=1)
    engine: Literal["gnina"] = "gnina"
    status: DockingJobStatus
    phase: DockingJobPhase
    revision: int = Field(ge=0)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    selected_count: int = Field(ge=1)
    completed_count: int = Field(ge=0)
    succeeded_count: int = Field(ge=0)
    failed_count: int = Field(ge=0)
    canceled_count: int = Field(ge=0)

    @model_validator(mode="after")
    def keep_counts_bounded(self) -> "GninaScreeningProgress":
        tally = self.succeeded_count + self.failed_count + self.canceled_count
        if tally != self.completed_count:
            raise ValueError(
                "completed_count must equal succeeded_count + failed_count + canceled_count"
            )
        if self.completed_count > self.selected_count:
            raise ValueError("completed_count cannot exceed selected_count")
        if self.status in TERMINAL_CAMPAIGN_STATES:
            if (
                self.completed_count != self.selected_count
                or self.phase is not DockingJobPhase.COMPLETE
            ):
                raise ValueError("terminal progress must account for all selected entries")
            if self.completed_at is None:
                raise ValueError("terminal progress must record its completion time")
            if self.status is DockingJobStatus.COMPLETED and (
                self.succeeded_count == 0 or self.canceled_count != 0
            ):
                raise ValueError("completed progress requires success and no canceled entries")
        return self


class GninaScreeningCampaignRecord(BaseModel):
    """A whole campaign: one selection, one receptor and site, one GNINA build.

    Validation here is about internal contradictions. The record is refused
    when it disagrees with itself - a count that does not match the entries it
    summarizes, a selection pinned to a different library than the request
    asked for, one prepared ligand selected twice, one single job claimed by
    two molecules, or a finished campaign that still says a molecule is
    docking. None of that checks the campaign against the engine, the library
    or the filesystem; see the module docstring.
    """

    model_config = ConfigDict(extra="forbid")

    campaign_id: str = Field(min_length=1)
    engine: Literal["gnina"] = "gnina"
    status: DockingJobStatus
    phase: DockingJobPhase
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    request: GninaScreeningRequest
    tool: GninaToolIdentity
    selection: GninaScreeningSelection
    receptor_output_artifact_id: str = Field(min_length=1)
    receptor_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    box: BindingBox
    # One job at a time, recorded as a fact of the run rather than a setting.
    worker_count: int = Field(default=1, ge=1, le=1)
    selected_count: int = Field(ge=1)
    completed_count: int = Field(default=0, ge=0)
    succeeded_count: int = Field(default=0, ge=0)
    failed_count: int = Field(default=0, ge=0)
    canceled_count: int = Field(default=0, ge=0)
    # The applied selection, in selection order.
    entries: list[GninaScreeningEntry] = Field(min_length=1)
    warnings: list[StructuredWarning] = Field(default_factory=list)
    failure: DockingFailure | None = None
    provenance: ProvenanceEvent | None = None
    revision: int = Field(default=0, ge=0)

    @property
    def selected_ligand_ids(self) -> tuple[str, ...]:
        """The selection in selection order, independent of `source_index`."""
        return tuple(entry.ligand_id for entry in self.entries)

    def progress(self) -> GninaScreeningProgress:
        """The header a poller should receive, derived rather than tracked twice."""
        return GninaScreeningProgress(
            campaign_id=self.campaign_id,
            status=self.status,
            phase=self.phase,
            revision=self.revision,
            started_at=self.started_at,
            completed_at=self.completed_at,
            selected_count=self.selected_count,
            completed_count=self.completed_count,
            succeeded_count=self.succeeded_count,
            failed_count=self.failed_count,
            canceled_count=self.canceled_count,
        )

    @model_validator(mode="after")
    def reject_internal_contradictions(self) -> "GninaScreeningCampaignRecord":
        if self.selection.library_id != self.request.library_id:
            raise ValueError("the pinned selection and the request name different libraries")
        if self.selection.filter_run_id != self.request.filter_run_id:
            raise ValueError("the pinned selection and the request name different filter runs")
        if self.selected_count != len(self.entries):
            raise ValueError("selected_count must equal the number of recorded entries")

        ligand_ids = {entry.ligand_id for entry in self.entries}
        if len(ligand_ids) != len(self.entries):
            raise ValueError("a prepared ligand state cannot be selected twice in one campaign")
        job_ids = [entry.gnina_job_id for entry in self.entries if entry.gnina_job_id is not None]
        if len(set(job_ids)) != len(job_ids):
            raise ValueError("one GNINA single job cannot be the attempt for two molecules")

        tallies = {
            DockingJobStatus.COMPLETED: self.succeeded_count,
            DockingJobStatus.FAILED: self.failed_count,
            DockingJobStatus.CANCELED: self.canceled_count,
        }
        for state, recorded in tallies.items():
            observed = sum(1 for entry in self.entries if entry.status is state)
            if observed != recorded:
                raise ValueError(
                    f"recorded count for '{state.value}' entries disagrees with the entries"
                )
        if self.completed_count != sum(tallies.values()):
            raise ValueError(
                "completed_count must equal succeeded_count + failed_count + canceled_count"
            )

        if self.status in TERMINAL_CAMPAIGN_STATES:
            if any(
                entry.status in {DockingJobStatus.RUNNING, DockingJobStatus.CANCEL_REQUESTED}
                for entry in self.entries
            ):
                raise ValueError(
                    f"a '{self.status.value}' campaign cannot still have a molecule docking"
                )
            if not all(entry.is_terminal for entry in self.entries):
                raise ValueError("a terminal campaign cannot still have pending work")
            if self.status is DockingJobStatus.COMPLETED and self.succeeded_count == 0:
                raise ValueError("a campaign with no successful jobs cannot be completed")
            if self.status is DockingJobStatus.COMPLETED and self.canceled_count:
                raise ValueError("a completed campaign cannot contain canceled entries")
            if self.phase is not DockingJobPhase.COMPLETE:
                raise ValueError("a terminal campaign must be in the 'complete' phase")
            if self.completed_at is None:
                raise ValueError("a terminal campaign must record its completion time")
        return self
