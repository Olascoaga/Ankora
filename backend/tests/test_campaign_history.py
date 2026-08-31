"""Recovering earlier campaigns, for either engine.

A campaign outlives the session that launched it, and a project accumulates
more than one. These tests fix what the history is allowed to show: campaigns
that searched the same space, newest first, described without their results.
"""

from datetime import UTC, datetime, timedelta

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
from ankora_backend.schemas.binding_sites import BindingBox
from ankora_backend.schemas.campaign_history import CampaignEngine
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
from ankora_backend.services.campaign_history import CampaignHistoryService

RECEPTOR = "receptor-1"
SITE = "site-1"
# A second record for the very same pocket: confirming a site twice writes two
# records carrying one box.
SITE_TWIN = "site-1-twin"
OTHER_SITE = "site-2"
LIBRARY = "library-1"
FILTER_RUN = "filter-1"
MANIFEST = "c" * 64
BASE_TIME = datetime(2026, 8, 20, 12, 0, tzinfo=UTC)

BOX = BindingBox(
    center_x=35.4, center_y=-2.9, center_z=-0.7, size_x=21.6, size_y=19.8, size_z=19.3
)
ELSEWHERE = BindingBox(
    center_x=10.0, center_y=10.0, center_z=10.0, size_x=20.0, size_y=20.0, size_z=20.0
)


def _vina(
    batch_id: str,
    scores: list[float | None],
    *,
    site: str = SITE,
    receptor: str = RECEPTOR,
    minutes: int = 0,
    status: DockingJobStatus = DockingJobStatus.COMPLETED,
) -> VinaBatchDockingRecord:
    return VinaBatchDockingRecord(
        batch_id=batch_id,
        status=status,
        phase=DockingJobPhase.COMPLETE,
        created_at=BASE_TIME + timedelta(minutes=minutes),
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
        selection_manifest_sha256=MANIFEST,
        selected_count=len(scores),
        worker_count=1,
        threads_per_ligand=1,
        completed_count=len(scores),
        succeeded_count=sum(1 for s in scores if s is not None),
        failed_count=sum(1 for s in scores if s is None),
        canceled_count=0,
        entries=[
            VinaBatchLigandResult(
                ligand_id=f"ligand-{index}",
                source_index=index,
                name=f"Compound {index}",
                canonical_smiles="CC",
                status=(
                    DockingJobStatus.COMPLETED
                    if score is not None
                    else DockingJobStatus.FAILED
                ),
                phase=DockingJobPhase.COMPLETE,
                poses=(
                    []
                    if score is None
                    else [
                        DockingPoseResult(
                            mode=1,
                            affinity_kcal_mol=score,
                            rmsd_lower_bound_angstrom=0,
                            rmsd_upper_bound_angstrom=0,
                            artifact=DockingPoseArtifact(
                                artifact_id=f"pose-{index}",
                                mode=1,
                                filename="pose_1.pdbqt",
                                format="pdbqt",
                                sha256=str(index).rjust(64, "0"),
                                size_bytes=100,
                                content_url=f"/vina/{index}",
                            ),
                        )
                    ]
                ),
            )
            for index, score in enumerate(scores)
        ],
    )


def _autodock4(
    batch_id: str,
    energies: list[float | None],
    *,
    site: str = SITE,
    receptor: str = RECEPTOR,
    minutes: int = 0,
    status: AutoDock4JobStatus = AutoDock4JobStatus.COMPLETED,
) -> AutoDock4BatchRecord:
    return AutoDock4BatchRecord(
        batch_id=batch_id,
        status=status,
        phase=AutoDock4JobPhase.COMPLETE,
        created_at=BASE_TIME + timedelta(minutes=minutes),
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
        selection_manifest_sha256=MANIFEST,
        selected_count=len(energies),
        worker_count=1,
        completed_count=len(energies),
        succeeded_count=sum(1 for e in energies if e is not None),
        failed_count=sum(1 for e in energies if e is None),
        entries=[
            AutoDock4BatchLigandResult(
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
                clusters=(
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
                ),
            )
            for index, energy in enumerate(energies)
        ],
    )


class _FakeBindingSiteStore:
    """Only the box matters here, so only the box is modelled."""

    def __init__(self, boxes: dict[str, BindingBox]) -> None:
        self._boxes = boxes

    def load_record(self, binding_site_id: str) -> object:
        try:
            box = self._boxes[binding_site_id]
        except KeyError as error:
            raise AnkoraDomainError(
                code="BINDING_SITE_NOT_FOUND",
                stage="binding_site_storage",
                message="No such binding site.",
                status_code=404,
            ) from error
        return type("_Record", (), {"box": box})()


class _FakeDockingStore:
    def __init__(self, records: list[VinaBatchDockingRecord]) -> None:
        self._records = records

    def list_batch_records(self) -> list[VinaBatchDockingRecord]:
        return list(self._records)


class _FakeAutoDock4Store:
    def __init__(self, records: list[AutoDock4BatchRecord]) -> None:
        self._records = records

    def list_batches(self) -> list[AutoDock4BatchRecord]:
        return list(self._records)


def _service(
    *,
    vina: list[VinaBatchDockingRecord] | None = None,
    autodock4: list[AutoDock4BatchRecord] | None = None,
    boxes: dict[str, BindingBox] | None = None,
) -> CampaignHistoryService:
    return CampaignHistoryService(
        docking_store=_FakeDockingStore(vina or []),  # type: ignore[arg-type]
        autodock4_store=_FakeAutoDock4Store(autodock4 or []),  # type: ignore[arg-type]
        binding_site_store=_FakeBindingSiteStore(  # type: ignore[arg-type]
            boxes or {SITE: BOX, SITE_TWIN: BOX, OTHER_SITE: ELSEWHERE}
        ),
    )


def test_earlier_campaigns_are_listed_newest_first() -> None:
    """Reconnecting to the newest is not enough: every campaign is offered."""
    service = _service(
        autodock4=[
            _autodock4("first", [-5.0], minutes=0),
            _autodock4("third", [-5.2], minutes=120),
            _autodock4("second", [-5.1], minutes=60),
        ]
    )

    history = service.autodock4_history(receptor_id=RECEPTOR, binding_site_id=SITE)

    assert [c.batch_id for c in history.campaigns] == ["third", "second", "first"]
    assert history.engine is CampaignEngine.AUTODOCK4


def test_a_campaign_over_the_same_box_is_recoverable_from_another_site_record() -> None:
    """Confirming one pocket twice must not hide a scientist's own campaigns.

    Two binding-site records can define the identical search space. Matching on
    the record id would report an empty history over real, usable work.
    """
    service = _service(
        vina=[_vina("twin-campaign", [-7.5], site=SITE_TWIN)],
    )

    history = service.vina_history(receptor_id=RECEPTOR, binding_site_id=SITE)

    assert [c.batch_id for c in history.campaigns] == ["twin-campaign"]
    # The reuse is stated rather than passed off as the same record.
    assert history.campaigns[0].same_site_record is False
    assert history.campaigns[0].binding_site_id == SITE_TWIN


def test_a_campaign_over_its_own_site_record_is_not_flagged() -> None:
    service = _service(vina=[_vina("direct", [-7.5], site=SITE)])

    history = service.vina_history(receptor_id=RECEPTOR, binding_site_id=SITE)

    assert history.campaigns[0].same_site_record is True


def test_a_campaign_over_a_different_box_is_not_offered() -> None:
    """A different search space is a different experiment, not history."""
    service = _service(
        vina=[
            _vina("here", [-7.5], site=SITE),
            _vina("elsewhere", [-9.9], site=OTHER_SITE),
        ]
    )

    history = service.vina_history(receptor_id=RECEPTOR, binding_site_id=SITE)

    assert [c.batch_id for c in history.campaigns] == ["here"]


def test_a_campaign_on_another_receptor_is_not_offered() -> None:
    service = _service(
        autodock4=[
            _autodock4("mine", [-5.0]),
            _autodock4("other-protein", [-5.0], receptor="receptor-2"),
        ]
    )

    history = service.autodock4_history(receptor_id=RECEPTOR, binding_site_id=SITE)

    assert [c.batch_id for c in history.campaigns] == ["mine"]


def test_a_campaign_whose_site_record_is_gone_is_left_out() -> None:
    """It cannot be shown to search this space, so it is not claimed to."""
    service = _service(
        vina=[_vina("orphan", [-7.5], site="deleted-site")],
        boxes={SITE: BOX},
    )

    history = service.vina_history(receptor_id=RECEPTOR, binding_site_id=SITE)

    assert history.campaigns == []


def test_each_summary_carries_its_own_engines_best_result() -> None:
    """Vina's best pose and AutoDock4's best cluster, each on its own scale."""
    service = _service(
        vina=[_vina("v", [-7.0, None, -8.4, -6.1])],
        autodock4=[_autodock4("a", [-4.0, -6.3, None])],
    )

    vina = service.vina_history(
        receptor_id=RECEPTOR, binding_site_id=SITE
    ).campaigns[0]
    autodock4 = service.autodock4_history(
        receptor_id=RECEPTOR, binding_site_id=SITE
    ).campaigns[0]

    assert vina.best_result_kcal_mol == -8.4
    assert vina.best_ligand_name == "Compound 2"
    assert vina.succeeded_count == 3
    assert vina.failed_count == 1
    assert autodock4.best_result_kcal_mol == -6.3
    assert autodock4.best_ligand_name == "Compound 1"
    # Each number is only ever reported beside the engine that produced it.
    assert vina.engine is CampaignEngine.AUTODOCK_VINA
    assert autodock4.engine is CampaignEngine.AUTODOCK4


def test_a_campaign_that_produced_nothing_reports_no_best_result() -> None:
    service = _service(
        vina=[_vina("empty", [None, None], status=DockingJobStatus.CANCELED)]
    )

    campaign = service.vina_history(
        receptor_id=RECEPTOR, binding_site_id=SITE
    ).campaigns[0]

    assert campaign.best_result_kcal_mol is None
    assert campaign.best_ligand_name is None
    assert campaign.status == "canceled"
    assert campaign.is_running is False


def test_an_unfinished_campaign_is_marked_as_still_running() -> None:
    service = _service(
        autodock4=[_autodock4("live", [-5.0], status=AutoDock4JobStatus.RUNNING)]
    )

    campaign = service.autodock4_history(
        receptor_id=RECEPTOR, binding_site_id=SITE
    ).campaigns[0]

    assert campaign.is_running is True
    assert campaign.status == "running"


def test_a_summary_carries_no_results() -> None:
    """A completed record is megabytes of poses; a listing must stay small."""
    service = _service(vina=[_vina("v", [-7.0])])

    payload = service.vina_history(
        receptor_id=RECEPTOR, binding_site_id=SITE
    ).campaigns[0].model_dump()

    assert "entries" not in payload
    assert "poses" not in payload
    assert "clusters" not in payload


def test_history_is_empty_rather_than_an_error_when_nothing_has_been_run() -> None:
    """A first run is the normal state, not a failure to report."""
    service = _service()

    assert (
        service.vina_history(receptor_id=RECEPTOR, binding_site_id=SITE).campaigns == []
    )
    assert (
        service.autodock4_history(
            receptor_id=RECEPTOR, binding_site_id=SITE
        ).campaigns
        == []
    )
