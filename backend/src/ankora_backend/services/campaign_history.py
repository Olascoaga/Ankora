"""List the screening campaigns a project has on disk, for either engine.

Reconnecting to the most recent campaign is not enough on its own: a project
accumulates campaigns, and the scientist has to be able to open an earlier one
- the run with more exhaustiveness, the one over a different selection, the one
from last week - rather than only the newest.

Both engines are served from here so the two histories cannot drift apart in
what they report. Nothing in this module compares the engines: each history is
listed on its own, and a summary's best number is always shown next to the
engine that produced it.

A campaign belongs to a search space, not to the record that happened to define
it. Confirming the same pocket twice writes two binding-site records with
identical boxes, so matching on the record id alone would hide a scientist's
own campaigns from their own history. This module therefore matches on the
receptor and the box - the same scientific identity the map-set validation
uses - and flags a campaign whose site record differs so the reuse stays
visible rather than silent.
"""

from ankora_backend.domain.errors import AnkoraDomainError
from ankora_backend.persistence.autodock4_store import AutoDock4JobStore
from ankora_backend.persistence.binding_site_store import BindingSiteArtifactStore
from ankora_backend.persistence.docking_store import DockingArtifactStore
from ankora_backend.schemas.autodock4 import (
    AutoDock4BatchRecord,
    AutoDock4JobStatus,
)
from ankora_backend.schemas.binding_sites import BindingBox
from ankora_backend.schemas.campaign_history import (
    CampaignEngine,
    CampaignHistory,
    CampaignSummary,
)
from ankora_backend.schemas.docking import (
    DockingJobStatus,
    VinaBatchDockingRecord,
)

# A record left in one of these states was still in flight when it was last
# written. It is what the store knows, not a live process check: a campaign
# interrupted by a crash keeps the status it had when the process died.
_UNFINISHED = {"queued", "running", "cancel_requested"}


class CampaignHistoryService:
    def __init__(
        self,
        *,
        docking_store: DockingArtifactStore,
        autodock4_store: AutoDock4JobStore,
        binding_site_store: BindingSiteArtifactStore,
    ) -> None:
        self._docking_store = docking_store
        self._autodock4_store = autodock4_store
        self._binding_site_store = binding_site_store

    @classmethod
    def from_environment(cls) -> "CampaignHistoryService":
        return cls(
            docking_store=DockingArtifactStore.from_environment(),
            autodock4_store=AutoDock4JobStore.from_environment(),
            binding_site_store=BindingSiteArtifactStore.from_environment(),
        )

    def vina_history(
        self, *, receptor_id: str, binding_site_id: str
    ) -> CampaignHistory:
        box = self._box_of(binding_site_id)
        summaries = [
            _summarize_vina(
                record,
                same_site_record=record.request.binding_site_id == binding_site_id,
            )
            for record in self._docking_store.list_batch_records()
            if record.request.receptor_id == receptor_id
            and self._searches_same_space(record.request.binding_site_id, box)
        ]
        return CampaignHistory(
            engine=CampaignEngine.AUTODOCK_VINA,
            receptor_id=receptor_id,
            binding_site_id=binding_site_id,
            campaigns=_newest_first(summaries),
        )

    def autodock4_history(
        self, *, receptor_id: str, binding_site_id: str
    ) -> CampaignHistory:
        box = self._box_of(binding_site_id)
        summaries = [
            _summarize_autodock4(
                record,
                same_site_record=record.binding_site_id == binding_site_id,
            )
            for record in self._autodock4_store.list_batches()
            if record.receptor_id == receptor_id
            and self._searches_same_space(record.binding_site_id, box)
        ]
        return CampaignHistory(
            engine=CampaignEngine.AUTODOCK4,
            receptor_id=receptor_id,
            binding_site_id=binding_site_id,
            campaigns=_newest_first(summaries),
        )


    def _box_of(self, binding_site_id: str) -> BindingBox:
        return self._binding_site_store.load_record(binding_site_id).box

    def _searches_same_space(
        self, candidate_site_id: str, box: BindingBox
    ) -> bool:
        """Whether a campaign's site is the same search space as this one.

        The same pocket confirmed twice produces two records carrying one box,
        and a campaign run against either of them searched the same space.
        """
        try:
            return self._box_of(candidate_site_id) == box
        except AnkoraDomainError:
            # A campaign whose site record is gone cannot be shown to search
            # this space, so it is left out rather than assumed compatible.
            return False


def _newest_first(summaries: list[CampaignSummary]) -> list[CampaignSummary]:
    # The batch id breaks ties so two campaigns created in the same clock tick
    # keep a stable order between calls.
    return sorted(
        summaries, key=lambda item: (item.created_at, item.batch_id), reverse=True
    )


def _summarize_vina(
    record: VinaBatchDockingRecord, *, same_site_record: bool
) -> CampaignSummary:
    best: float | None = None
    best_name: str | None = None
    for entry in record.entries:
        if entry.status is not DockingJobStatus.COMPLETED or not entry.poses:
            continue
        # Vina orders its own poses best first, so mode 1 scores the molecule.
        score = entry.poses[0].affinity_kcal_mol
        if best is None or score < best:
            best, best_name = score, entry.name
    return CampaignSummary(
        batch_id=record.batch_id,
        engine=CampaignEngine.AUTODOCK_VINA,
        engine_version=record.tool.version,
        status=record.status.value,
        is_running=record.status.value in _UNFINISHED,
        created_at=record.created_at,
        completed_at=record.completed_at,
        receptor_id=record.request.receptor_id,
        binding_site_id=record.request.binding_site_id,
        same_site_record=same_site_record,
        library_id=record.request.library_id,
        filter_run_id=record.request.filter_run_id,
        selection_manifest_sha256=record.selection_manifest_sha256,
        selected_count=record.selected_count,
        succeeded_count=record.succeeded_count,
        failed_count=record.failed_count,
        canceled_count=record.canceled_count,
        best_result_kcal_mol=best,
        best_ligand_name=best_name,
    )


def _summarize_autodock4(
    record: AutoDock4BatchRecord, *, same_site_record: bool
) -> CampaignSummary:
    best: float | None = None
    best_name: str | None = None
    for entry in record.entries:
        if entry.status is not AutoDock4JobStatus.COMPLETED or not entry.clusters:
            continue
        # AutoDock ranks cluster 1 best, so its lowest energy scores the molecule.
        energy = min(
            cluster.lowest_binding_energy_kcal_mol for cluster in entry.clusters
        )
        if best is None or energy < best:
            best, best_name = energy, entry.name
    return CampaignSummary(
        batch_id=record.batch_id,
        engine=CampaignEngine.AUTODOCK4,
        engine_version=record.autodock4.tool.version,
        status=record.status.value,
        is_running=record.status.value in _UNFINISHED,
        created_at=record.created_at,
        completed_at=record.completed_at,
        receptor_id=record.receptor_id,
        binding_site_id=record.binding_site_id,
        same_site_record=same_site_record,
        library_id=record.request.library_id,
        filter_run_id=record.request.filter_run_id,
        selection_manifest_sha256=record.selection_manifest_sha256,
        selected_count=record.selected_count,
        succeeded_count=record.succeeded_count,
        failed_count=record.failed_count,
        canceled_count=record.canceled_count,
        best_result_kcal_mol=best,
        best_ligand_name=best_name,
    )
