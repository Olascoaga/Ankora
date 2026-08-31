"""Compare a Vina campaign and an AutoDock4 campaign over the same selection.

Only rankings are compared. The two engines' scores are on different scales and
are never merged, averaged, or turned into a consensus number.
"""

from datetime import UTC, datetime

from ankora_backend.domain.errors import AnkoraDomainError
from ankora_backend.persistence.autodock4_store import AutoDock4JobStore
from ankora_backend.persistence.docking_store import DockingArtifactStore
from ankora_backend.schemas.autodock4 import (
    AutoDock4BatchLigandResult,
    AutoDock4BatchRecord,
    AutoDock4JobStatus,
)
from ankora_backend.schemas.docking import (
    DockingJobStatus,
    VinaBatchDockingRecord,
)
from ankora_backend.schemas.engine_comparison import (
    EngineComparison,
    EngineComparisonRow,
    RankAgreement,
)

_STAGE = "engine_comparison"
DEFAULT_TOP_N = 20


class EngineComparisonService:
    def __init__(
        self,
        *,
        docking_store: DockingArtifactStore,
        autodock4_store: AutoDock4JobStore,
    ) -> None:
        self._docking_store = docking_store
        self._autodock4_store = autodock4_store

    @classmethod
    def from_environment(cls) -> "EngineComparisonService":
        return cls(
            docking_store=DockingArtifactStore.from_environment(),
            autodock4_store=AutoDock4JobStore.from_environment(),
        )

    def compare_latest(
        self,
        *,
        receptor_id: str,
        binding_site_id: str,
        filter_run_id: str,
        top_n: int = DEFAULT_TOP_N,
    ) -> EngineComparison:
        """Compare the persisted campaigns for these inputs.

        Campaigns outlive the session that ran them, so a comparison must be
        resolvable from what is on disk rather than only from what the
        interface happens to remember.
        """
        vina = self._latest_vina(receptor_id, binding_site_id, filter_run_id)
        autodock4 = self._latest_autodock4(receptor_id, binding_site_id, filter_run_id)
        return self._build(vina, autodock4, top_n)

    def compare(
        self, *, vina_batch_id: str, autodock4_batch_id: str, top_n: int = DEFAULT_TOP_N
    ) -> EngineComparison:
        vina = self._docking_store.load_batch_record(vina_batch_id)
        autodock4 = self._autodock4_store.load_batch(autodock4_batch_id)
        return self._build(vina, autodock4, top_n)

    def _latest_vina(
        self, receptor_id: str, binding_site_id: str, filter_run_id: str
    ) -> VinaBatchDockingRecord:
        matching = [
            record
            for record in self._docking_store.list_batch_records()
            if record.request.receptor_id == receptor_id
            and record.request.binding_site_id == binding_site_id
            and record.request.filter_run_id == filter_run_id
            and record.succeeded_count > 0
        ]
        if not matching:
            raise self._missing_campaign("AutoDock Vina", receptor_id, binding_site_id)
        return max(matching, key=lambda record: (record.created_at, record.batch_id))

    def _latest_autodock4(
        self, receptor_id: str, binding_site_id: str, filter_run_id: str
    ) -> AutoDock4BatchRecord:
        matching = [
            record
            for record in self._autodock4_store.list_batches()
            if record.receptor_id == receptor_id
            and record.binding_site_id == binding_site_id
            and record.request.filter_run_id == filter_run_id
            and record.succeeded_count > 0
        ]
        if not matching:
            raise self._missing_campaign("AutoDock4", receptor_id, binding_site_id)
        return max(matching, key=lambda record: (record.created_at, record.batch_id))

    @staticmethod
    def _missing_campaign(
        engine: str, receptor_id: str, binding_site_id: str
    ) -> AnkoraDomainError:
        return AnkoraDomainError(
            code="ENGINE_COMPARISON_CAMPAIGN_MISSING",
            stage=_STAGE,
            message=(
                f"No completed {engine} campaign exists for this receptor and "
                "binding site. Run it before comparing the two engines."
            ),
            status_code=404,
            details={
                "missing_engine": engine,
                "receptor_id": receptor_id,
                "binding_site_id": binding_site_id,
            },
        )

    def _build(
        self,
        vina: VinaBatchDockingRecord,
        autodock4: AutoDock4BatchRecord,
        top_n: int,
    ) -> EngineComparison:
        self._require_same_experiment(vina, autodock4)

        vina_scores = {
            entry.ligand_id: entry.poses[0].affinity_kcal_mol
            for entry in vina.entries
            if entry.status is DockingJobStatus.COMPLETED and entry.poses
        }
        autodock4_scores = {
            entry.ligand_id: energy
            for entry in autodock4.entries
            if entry.status is AutoDock4JobStatus.COMPLETED
            and (energy := _best_energy(entry)) is not None
        }
        vina_ranks = _ranks(vina_scores)
        autodock4_ranks = _ranks(autodock4_scores)

        identity = {
            entry.ligand_id: entry for entry in autodock4.entries
        }
        rows: list[EngineComparisonRow] = []
        for entry in sorted(vina.entries, key=lambda item: item.source_index):
            ligand_id = entry.ligand_id
            partner = identity.get(ligand_id)
            vina_rank = vina_ranks.get(ligand_id)
            autodock4_rank = autodock4_ranks.get(ligand_id)
            both = vina_rank is not None and autodock4_rank is not None
            difference = (
                abs(vina_rank - autodock4_rank)
                if vina_rank is not None and autodock4_rank is not None
                else None
            )
            rows.append(
                EngineComparisonRow(
                    ligand_id=ligand_id,
                    source_index=entry.source_index,
                    name=entry.name,
                    canonical_smiles=entry.canonical_smiles,
                    vina_best_score_kcal_mol=vina_scores.get(ligand_id),
                    vina_rank=vina_rank,
                    autodock4_best_energy_kcal_mol=autodock4_scores.get(ligand_id),
                    autodock4_rank=autodock4_rank,
                    autodock4_top_cluster_run_count=(
                        _top_cluster_run_count(partner) if partner is not None else None
                    ),
                    rank_difference=difference,
                    docked_by_both=both,
                )
            )

        both_ids = set(vina_scores) & set(autodock4_scores)
        vina_top = _top_ids(vina_ranks, top_n)
        autodock4_top = _top_ids(autodock4_ranks, top_n)
        shared_top = vina_top & autodock4_top
        return EngineComparison(
            generated_at=datetime.now(UTC),
            receptor_id=vina.request.receptor_id,
            binding_site_id=vina.request.binding_site_id,
            library_id=vina.request.library_id,
            filter_run_id=vina.request.filter_run_id,
            selection_manifest_sha256=vina.selection_manifest_sha256,
            vina_batch_id=vina.batch_id,
            vina_version=vina.tool.version,
            autodock4_batch_id=autodock4.batch_id,
            autodock4_version=autodock4.autodock4.tool.version,
            selected_count=len(rows),
            docked_by_both_count=len(both_ids),
            vina_only_count=len(set(vina_scores) - set(autodock4_scores)),
            autodock4_only_count=len(set(autodock4_scores) - set(vina_scores)),
            docked_by_neither_count=sum(
                1
                for row in rows
                if row.vina_rank is None and row.autodock4_rank is None
            ),
            agreement=RankAgreement(
                comparable_count=len(both_ids),
                spearman_rho=_spearman(
                    {k: vina_scores[k] for k in both_ids},
                    {k: autodock4_scores[k] for k in both_ids},
                ),
                top_n=top_n,
                top_n_overlap=len(shared_top),
                top_n_shared_ligand_ids=sorted(shared_top),
            ),
            rows=rows,
        )

    @staticmethod
    def _require_same_experiment(
        vina: VinaBatchDockingRecord, autodock4: AutoDock4BatchRecord
    ) -> None:
        """Two campaigns are only comparable over the same inputs.

        Comparing rankings from different receptors, search spaces, or
        selections would produce a plausible-looking table that means nothing.
        """
        mismatches: dict[str, object] = {}
        if vina.request.receptor_id != autodock4.receptor_id:
            mismatches["receptor_id"] = [
                vina.request.receptor_id,
                autodock4.receptor_id,
            ]
        if vina.request.binding_site_id != autodock4.binding_site_id:
            mismatches["binding_site_id"] = [
                vina.request.binding_site_id,
                autodock4.binding_site_id,
            ]
        if vina.selection_manifest_sha256 != autodock4.selection_manifest_sha256:
            mismatches["selection_manifest_sha256"] = [
                vina.selection_manifest_sha256,
                autodock4.selection_manifest_sha256,
            ]
        if mismatches:
            raise AnkoraDomainError(
                code="ENGINE_COMPARISON_INPUTS_DIFFER",
                stage=_STAGE,
                message=(
                    "These two campaigns did not dock the same selection into "
                    "the same search space, so their rankings are not comparable."
                ),
                status_code=422,
                details=mismatches,
            )


def _best_energy(entry: AutoDock4BatchLigandResult) -> float | None:
    """AutoDock ranks cluster 1 best, so its lowest energy scores the molecule."""
    if not entry.clusters:
        return None
    return min(cluster.lowest_binding_energy_kcal_mol for cluster in entry.clusters)


def _top_cluster_run_count(entry: AutoDock4BatchLigandResult) -> int | None:
    top = next(
        (cluster for cluster in entry.clusters if cluster.cluster_rank == 1), None
    )
    return top.run_count if top is not None else None


def _ranks(scores: dict[str, float]) -> dict[str, int]:
    """Rank 1 is the most favourable, ties broken by ligand id for stability."""
    ordered = sorted(scores.items(), key=lambda item: (item[1], item[0]))
    return {ligand_id: index for index, (ligand_id, _) in enumerate(ordered, start=1)}


def _top_ids(ranks: dict[str, int], top_n: int) -> set[str]:
    return {ligand_id for ligand_id, rank in ranks.items() if rank <= top_n}


def _spearman(left: dict[str, float], right: dict[str, float]) -> float | None:
    """Spearman's rank correlation between two independent orderings.

    Uses average ranks for ties, which is what makes the coefficient defined
    when several molecules share a score. Returns None below three molecules,
    where the value would be an artefact rather than a weak signal.
    """
    shared = sorted(set(left) & set(right))
    if len(shared) < 3:
        return None
    left_ranks = _average_ranks([left[key] for key in shared])
    right_ranks = _average_ranks([right[key] for key in shared])
    count = len(shared)
    mean = (count + 1) / 2
    numerator: float = sum(
        (a - mean) * (b - mean) for a, b in zip(left_ranks, right_ranks, strict=True)
    )
    left_spread: float = sum((a - mean) ** 2 for a in left_ranks)
    right_spread: float = sum((b - mean) ** 2 for b in right_ranks)
    if left_spread == 0 or right_spread == 0:
        # Every molecule tied on one side: no ordering to correlate against.
        return None
    rho = numerator / (left_spread * right_spread) ** 0.5
    return round(float(rho), 4)


def _average_ranks(values: list[float]) -> list[float]:
    order = sorted(range(len(values)), key=lambda index: values[index])
    ranks = [0.0] * len(values)
    position = 0
    while position < len(order):
        end = position
        while end + 1 < len(order) and values[order[end + 1]] == values[order[position]]:
            end += 1
        average = (position + end) / 2 + 1
        for index in range(position, end + 1):
            ranks[order[index]] = average
        position = end + 1
    return ranks
