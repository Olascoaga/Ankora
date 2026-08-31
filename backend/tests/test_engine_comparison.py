"""Vina/AutoDock4 side-by-side comparison (ADR-015 item 4).

Only rankings are compared. `DOCKING_POLICY.md` forbids merging the two engines'
scores, so nothing here produces a combined or consensus number.
"""

from datetime import UTC, datetime

import pytest

from ankora_backend.domain.errors import AnkoraDomainError
from ankora_backend.schemas.autodock4 import (
    AutoDock4BatchLigandResult,
    AutoDock4BatchParameters,
    AutoDock4BatchRecord,
    AutoDock4BatchRequest,
    AutoDock4ClusterResult,
    AutoDock4JobPhase,
    AutoDock4JobStatus,
    AutoDock4ToolIdentity,
)
from ankora_backend.schemas.docking import (
    DockingJobPhase,
    DockingJobStatus,
    DockingPoseArtifact,
    DockingPoseResult,
    VinaBatchDockingParameters,
    VinaBatchDockingRecord,
    VinaBatchDockingRequest,
    VinaBatchLigandResult,
)
from ankora_backend.schemas.provenance import ToolIdentity
from ankora_backend.services.engine_comparison import EngineComparisonService, _spearman

RECEPTOR = "receptor-1"
SITE = "site-1"
LIBRARY = "library-1"
FILTER_RUN = "filter-1"
MANIFEST = "c" * 64


def _vina_entry(index: int, score: float | None) -> VinaBatchLigandResult:
    poses = (
        []
        if score is None
        else [
            DockingPoseResult(
                mode=1,
                affinity_kcal_mol=score,
                rmsd_lower_bound_angstrom=0,
                rmsd_upper_bound_angstrom=0,
                artifact=DockingPoseArtifact(
                    artifact_id=f"vina-pose-{index}",
                    mode=1,
                    filename="pose_1.pdbqt",
                    format="pdbqt",
                    sha256=str(index).rjust(64, "0"),
                    size_bytes=100,
                    content_url=f"/vina/{index}",
                ),
            )
        ]
    )
    return VinaBatchLigandResult(
        ligand_id=f"ligand-{index}",
        source_index=index,
        name=f"Compound {index}",
        canonical_smiles="CC",
        status=(
            DockingJobStatus.COMPLETED if score is not None else DockingJobStatus.FAILED
        ),
        phase=DockingJobPhase.COMPLETE,
        poses=poses,
    )


def _autodock4_entry(index: int, energy: float | None) -> AutoDock4BatchLigandResult:
    clusters = (
        []
        if energy is None
        else [
            AutoDock4ClusterResult(
                cluster_rank=1,
                lowest_binding_energy_kcal_mol=energy,
                mean_binding_energy_kcal_mol=energy,
                run_count=4,
                representative_run=1,
                runs=[1, 2, 3, 4],
            )
        ]
    )
    return AutoDock4BatchLigandResult(
        ligand_id=f"ligand-{index}",
        source_index=index,
        name=f"Compound {index}",
        canonical_smiles="CC",
        status=(
            AutoDock4JobStatus.COMPLETED
            if energy is not None
            else AutoDock4JobStatus.FAILED
        ),
        phase=AutoDock4JobPhase.COMPLETE,
        clusters=clusters,
    )


def _vina_batch(
    scores: list[float | None], *, receptor: str = RECEPTOR, site: str = SITE,
    manifest: str = MANIFEST,
) -> VinaBatchDockingRecord:
    return VinaBatchDockingRecord(
        batch_id="vina-batch",
        status=DockingJobStatus.COMPLETED,
        phase=DockingJobPhase.COMPLETE,
        created_at=datetime.now(UTC),
        request=VinaBatchDockingRequest(
            receptor_id=receptor,
            binding_site_id=site,
            library_id=LIBRARY,
            filter_run_id=FILTER_RUN,
            parameters=VinaBatchDockingParameters(),
            acknowledge_inputs_and_scoring=True,
        ),
        tool=ToolIdentity(name="AutoDock Vina", version="1.2.7"),
        receptor_output_artifact_id="receptor-pdbqt",
        receptor_sha256="b" * 64,
        selection_manifest_artifact_id="manifest",
        selection_manifest_sha256=manifest,
        selected_count=len(scores),
        worker_count=1,
        threads_per_ligand=1,
        completed_count=len(scores),
        succeeded_count=sum(1 for s in scores if s is not None),
        failed_count=sum(1 for s in scores if s is None),
        canceled_count=0,
        entries=[_vina_entry(i, s) for i, s in enumerate(scores)],
    )


def _autodock4_batch(
    energies: list[float | None], *, receptor: str = RECEPTOR, site: str = SITE,
    manifest: str = MANIFEST,
) -> AutoDock4BatchRecord:
    return AutoDock4BatchRecord(
        batch_id="ad4-batch",
        status=AutoDock4JobStatus.COMPLETED,
        phase=AutoDock4JobPhase.COMPLETE,
        created_at=datetime.now(UTC),
        request=AutoDock4BatchRequest(
            receptor_id=receptor,
            binding_site_id=site,
            map_set_id="map-set-1",
            library_id=LIBRARY,
            filter_run_id=FILTER_RUN,
            parameters=AutoDock4BatchParameters(),
            acknowledge_inputs_and_scoring=True,
        ),
        autodock4=AutoDock4ToolIdentity(
            tool=ToolIdentity(name="AutoDock", version="4.2.6"),
            executable_path="synthetic",
            sha256="1" * 64,
            max_torsions=32,
            max_atoms=2048,
            max_maps=16,
        ),
        receptor_id=receptor,
        binding_site_id=site,
        map_set_id="map-set-1",
        map_set_identity_key="f" * 64,
        selection_manifest_sha256=manifest,
        selected_count=len(energies),
        worker_count=1,
        completed_count=len(energies),
        succeeded_count=sum(1 for e in energies if e is not None),
        failed_count=sum(1 for e in energies if e is None),
        entries=[_autodock4_entry(i, e) for i, e in enumerate(energies)],
    )


class _Stores:
    def __init__(self, vina: VinaBatchDockingRecord, ad4: AutoDock4BatchRecord) -> None:
        self._vina = vina
        self._ad4 = ad4

    def load_batch_record(self, batch_id: str) -> VinaBatchDockingRecord:
        assert batch_id == self._vina.batch_id
        return self._vina

    def load_batch(self, batch_id: str) -> AutoDock4BatchRecord:
        assert batch_id == self._ad4.batch_id
        return self._ad4


def _service(
    vina: VinaBatchDockingRecord, ad4: AutoDock4BatchRecord
) -> EngineComparisonService:
    stores = _Stores(vina, ad4)
    return EngineComparisonService(
        docking_store=stores,  # type: ignore[arg-type]
        autodock4_store=stores,  # type: ignore[arg-type]
    )


def test_each_engine_keeps_its_own_score_and_its_own_rank() -> None:
    """The two columns are never combined: there is no consensus number."""
    vina = _vina_batch([-7.0, -9.0, -8.0])
    ad4 = _autodock4_batch([-4.0, -6.0, -5.0])

    comparison = _service(vina, ad4).compare(
        vina_batch_id="vina-batch", autodock4_batch_id="ad4-batch"
    )

    assert [row.vina_rank for row in comparison.rows] == [3, 1, 2]
    assert [row.autodock4_rank for row in comparison.rows] == [3, 1, 2]
    assert [row.vina_best_score_kcal_mol for row in comparison.rows] == [-7.0, -9.0, -8.0]
    assert [row.autodock4_best_energy_kcal_mol for row in comparison.rows] == [
        -4.0, -6.0, -5.0,
    ]
    assert all(row.rank_difference == 0 for row in comparison.rows)
    assert comparison.docked_by_both_count == 3
    # The contract exposes no combined field at all.
    assert "consensus" not in comparison.model_dump_json()


def test_identical_orderings_agree_perfectly_and_reversed_ones_disagree() -> None:
    agreeing = _service(
        _vina_batch([-7.0, -9.0, -8.0]), _autodock4_batch([-4.0, -6.0, -5.0])
    ).compare(vina_batch_id="vina-batch", autodock4_batch_id="ad4-batch")
    opposed = _service(
        _vina_batch([-7.0, -9.0, -8.0]), _autodock4_batch([-6.0, -4.0, -5.0])
    ).compare(vina_batch_id="vina-batch", autodock4_batch_id="ad4-batch")

    assert agreeing.agreement.spearman_rho == 1.0
    assert opposed.agreement.spearman_rho == -1.0
    assert opposed.rows[0].rank_difference == 2


def test_spearman_matches_hand_computed_and_scipy_values() -> None:
    """Ranks (1,2,3,4,5) against (2,1,4,3,5): differences are -1,+1,-1,+1,0, so
    sum d^2 = 4 and rho = 1 - (6*4)/(5*24) = 0.8.

    These expectations were also cross-checked against `scipy.stats.spearmanr`,
    including the tie case, which is what the average-rank handling exists for.
    """
    assert _spearman(
        {"a": 1.0, "b": 2.0, "c": 3.0, "d": 4.0, "e": 5.0},
        {"a": 2.0, "b": 1.0, "c": 4.0, "d": 3.0, "e": 5.0},
    ) == 0.8
    assert _spearman(
        {"a": 1.0, "b": 2.0, "c": 3.0}, {"a": 3.0, "b": 2.0, "c": 1.0}
    ) == -1.0
    # Two molecules tied on the left, resolved by average ranks.
    assert _spearman(
        {"a": 1.0, "b": 2.0, "c": 2.0, "d": 4.0},
        {"a": 2.0, "b": 1.0, "c": 3.0, "d": 4.0},
    ) == 0.6325


def test_fewer_than_three_shared_molecules_reports_no_coefficient() -> None:
    """Two points always correlate perfectly; that is an artefact, not a signal."""
    comparison = _service(
        _vina_batch([-7.0, -9.0, None]), _autodock4_batch([-4.0, -6.0, None])
    ).compare(vina_batch_id="vina-batch", autodock4_batch_id="ad4-batch")

    assert comparison.agreement.comparable_count == 2
    assert comparison.agreement.spearman_rho is None


def test_a_molecule_only_one_engine_docked_is_counted_but_not_ranked_against() -> None:
    comparison = _service(
        _vina_batch([-7.0, -9.0, -8.0]), _autodock4_batch([-4.0, -6.0, None])
    ).compare(vina_batch_id="vina-batch", autodock4_batch_id="ad4-batch")

    assert comparison.vina_only_count == 1
    assert comparison.autodock4_only_count == 0
    assert comparison.docked_by_both_count == 2
    lonely = comparison.rows[2]
    assert lonely.vina_rank is not None
    assert lonely.autodock4_rank is None
    assert lonely.rank_difference is None
    assert lonely.docked_by_both is False


def test_top_n_overlap_reports_which_molecules_both_engines_favour() -> None:
    comparison = _service(
        _vina_batch([-9.0, -8.0, -7.0, -6.0]),
        _autodock4_batch([-6.0, -3.0, -5.0, -4.0]),
    ).compare(vina_batch_id="vina-batch", autodock4_batch_id="ad4-batch", top_n=2)

    assert comparison.agreement.top_n == 2
    # Vina's top two are ligands 0 and 1; AutoDock4's are 0 and 2.
    assert comparison.agreement.top_n_overlap == 1
    assert comparison.agreement.top_n_shared_ligand_ids == ["ligand-0"]


@pytest.mark.parametrize(
    ("field", "vina_kwargs", "ad4_kwargs"),
    [
        ("receptor_id", {"receptor": "other-receptor"}, {}),
        ("binding_site_id", {"site": "other-site"}, {}),
        ("selection_manifest_sha256", {"manifest": "a" * 64}, {}),
    ],
)
def test_campaigns_over_different_inputs_are_refused(
    field: str, vina_kwargs: dict[str, str], ad4_kwargs: dict[str, str]
) -> None:
    """Comparing different experiments would look plausible and mean nothing."""
    service = _service(
        _vina_batch([-7.0, -9.0, -8.0], **vina_kwargs),  # type: ignore[arg-type]
        _autodock4_batch([-4.0, -6.0, -5.0], **ad4_kwargs),  # type: ignore[arg-type]
    )

    with pytest.raises(AnkoraDomainError) as failure:
        service.compare(vina_batch_id="vina-batch", autodock4_batch_id="ad4-batch")

    assert failure.value.code == "ENGINE_COMPARISON_INPUTS_DIFFER"
    assert field in failure.value.details


class _HistoryStores:
    """Stores that only expose persisted history, never session state."""

    def __init__(
        self,
        vina: list[VinaBatchDockingRecord],
        ad4: list[AutoDock4BatchRecord],
    ) -> None:
        self._vina = vina
        self._ad4 = ad4

    def list_batch_records(self) -> list[VinaBatchDockingRecord]:
        return self._vina

    def list_batches(self) -> list[AutoDock4BatchRecord]:
        return self._ad4


def _history_service(
    vina: list[VinaBatchDockingRecord], ad4: list[AutoDock4BatchRecord]
) -> EngineComparisonService:
    stores = _HistoryStores(vina, ad4)
    return EngineComparisonService(
        docking_store=stores,  # type: ignore[arg-type]
        autodock4_store=stores,  # type: ignore[arg-type]
    )


def test_a_comparison_is_resolved_from_persisted_campaigns() -> None:
    """Campaigns outlive the session that ran them, so the comparison must be
    findable from disk rather than only from what an interface remembers."""
    comparison = _history_service(
        [_vina_batch([-7.0, -9.0, -8.0])], [_autodock4_batch([-4.0, -6.0, -5.0])]
    ).compare_latest(
        receptor_id=RECEPTOR, binding_site_id=SITE, filter_run_id=FILTER_RUN
    )

    assert comparison.vina_batch_id == "vina-batch"
    assert comparison.autodock4_batch_id == "ad4-batch"
    assert comparison.docked_by_both_count == 3


def test_resolution_names_the_engine_whose_campaign_is_missing() -> None:
    with pytest.raises(AnkoraDomainError) as failure:
        _history_service([_vina_batch([-7.0, -9.0, -8.0])], []).compare_latest(
            receptor_id=RECEPTOR, binding_site_id=SITE, filter_run_id=FILTER_RUN
        )

    assert failure.value.code == "ENGINE_COMPARISON_CAMPAIGN_MISSING"
    assert failure.value.details["missing_engine"] == "AutoDock4"

    with pytest.raises(AnkoraDomainError) as other:
        _history_service([], [_autodock4_batch([-4.0, -6.0, -5.0])]).compare_latest(
            receptor_id=RECEPTOR, binding_site_id=SITE, filter_run_id=FILTER_RUN
        )

    assert other.value.details["missing_engine"] == "AutoDock Vina"


def test_a_campaign_for_other_inputs_is_not_silently_used() -> None:
    """A campaign against a different binding site must not be picked up just
    because it is the only one on disk."""
    with pytest.raises(AnkoraDomainError) as failure:
        _history_service(
            [_vina_batch([-7.0, -9.0, -8.0], site="other-site")],
            [_autodock4_batch([-4.0, -6.0, -5.0])],
        ).compare_latest(
            receptor_id=RECEPTOR, binding_site_id=SITE, filter_run_id=FILTER_RUN
        )

    assert failure.value.details["missing_engine"] == "AutoDock Vina"
