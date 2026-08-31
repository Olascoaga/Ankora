"""The project-level result catalog (M6).

The catalog is where every campaign and every single job in a project becomes
findable at once, which makes it the one place where two scoring families can
most easily be silently merged. These tests fix that boundary, and the second
one the spec sets: a listing carries identity, never results.
"""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from ankora_backend.domain.errors import AnkoraDomainError
from ankora_backend.schemas.autodock4 import (
    AutoDock4BatchLigandResult,
    AutoDock4BatchParameters,
    AutoDock4BatchRecord,
    AutoDock4BatchRequest,
    AutoDock4ClusterResult,
    AutoDock4DockingJobRecord,
    AutoDock4DockingRequest,
    AutoDock4JobPhase,
    AutoDock4JobStatus,
    AutoDock4ToolIdentity,
)
from ankora_backend.schemas.autodock_gpu import (
    AutoDockGpuBatchLigandResult,
    AutoDockGpuBatchParameters,
    AutoDockGpuBatchRecord,
    AutoDockGpuBatchRequest,
    AutoDockGpuToolIdentity,
)
from ankora_backend.schemas.binding_sites import BindingBox
from ankora_backend.schemas.docking import (
    DockingJobPhase,
    DockingJobStatus,
    DockingPoseArtifact,
    DockingPoseResult,
    VinaBatchDockingParameters,
    VinaBatchDockingRecord,
    VinaBatchDockingRequest,
    VinaBatchLigandResult,
    VinaDockingJobRecord,
    VinaDockingParameters,
    VinaDockingRequest,
)
from ankora_backend.schemas.provenance import ToolIdentity
from ankora_backend.schemas.results_catalog import ResultMode, ScoringFamily
from ankora_backend.services.result_catalog import ResultCatalogService

RECEPTOR = "receptor-1"
SITE = "site-1"
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

VINA_TOOL = ToolIdentity(name="AutoDock Vina", version="1.2.7")
CPU_TOOL = AutoDock4ToolIdentity(
    tool=ToolIdentity(name="AutoDock", version="4.2.6"),
    executable_path="synthetic",
    sha256="1" * 64,
    max_torsions=32,
    max_atoms=2048,
    max_maps=16,
)
GPU_TOOL = AutoDockGpuToolIdentity(
    tool=ToolIdentity(name="AutoDock-GPU", version="1.6"),
    executable_path="synthetic",
    sha256="2" * 64,
    build="ocl",
    device_number=1,
    device_name="NVIDIA GeForce RTX 5050",
)


def _pose(index: int, score: float) -> DockingPoseResult:
    return DockingPoseResult(
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


def _cluster(energy: float, *, runs: int = 4) -> AutoDock4ClusterResult:
    return AutoDock4ClusterResult(
        cluster_rank=1,
        lowest_binding_energy_kcal_mol=energy,
        mean_binding_energy_kcal_mol=energy,
        run_count=runs,
        representative_run=1,
        runs=list(range(1, runs + 1)),
    )


def _vina_batch(
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
        tool=VINA_TOOL,
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
                canonical_smiles="CCO" if index else "CC",
                status=(
                    DockingJobStatus.COMPLETED
                    if score is not None
                    else DockingJobStatus.FAILED
                ),
                phase=DockingJobPhase.COMPLETE,
                poses=[] if score is None else [_pose(index, score)],
            )
            for index, score in enumerate(scores)
        ],
    )


def _autodock4_batch(
    batch_id: str,
    energies: list[float | None],
    *,
    site: str = SITE,
    receptor: str = RECEPTOR,
    minutes: int = 0,
) -> AutoDock4BatchRecord:
    return AutoDock4BatchRecord(
        batch_id=batch_id,
        status=AutoDock4JobStatus.COMPLETED,
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
        autodock4=CPU_TOOL,
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
                status=(
                    AutoDock4JobStatus.COMPLETED
                    if energy is not None
                    else AutoDock4JobStatus.FAILED
                ),
                phase=AutoDock4JobPhase.COMPLETE,
                clusters=[] if energy is None else [_cluster(energy, runs=6)],
            )
            for index, energy in enumerate(energies)
        ],
    )


def _gpu_batch(
    batch_id: str,
    energies: list[float | None],
    *,
    site: str = SITE,
    minutes: int = 0,
) -> AutoDockGpuBatchRecord:
    return AutoDockGpuBatchRecord(
        batch_id=batch_id,
        status=AutoDock4JobStatus.COMPLETED,
        phase=AutoDock4JobPhase.COMPLETE,
        created_at=BASE_TIME + timedelta(minutes=minutes),
        request=AutoDockGpuBatchRequest(
            receptor_id=RECEPTOR,
            binding_site_id=site,
            map_set_id="map-set-1",
            library_id=LIBRARY,
            filter_run_id=FILTER_RUN,
            parameters=AutoDockGpuBatchParameters(),
            acknowledge_inputs_and_scoring=True,
        ),
        autodock_gpu=GPU_TOOL,
        receptor_id=RECEPTOR,
        binding_site_id=site,
        map_set_id="map-set-1",
        map_set_identity_key="f" * 64,
        selection_manifest_sha256=MANIFEST,
        selected_count=len(energies),
        completed_count=len(energies),
        succeeded_count=sum(1 for e in energies if e is not None),
        failed_count=sum(1 for e in energies if e is None),
        entries=[
            AutoDockGpuBatchLigandResult(
                ligand_id=f"ligand-{index}",
                source_index=index,
                name=f"Compound {index}",
                status=(
                    AutoDock4JobStatus.COMPLETED
                    if energy is not None
                    else AutoDock4JobStatus.FAILED
                ),
                phase=AutoDock4JobPhase.COMPLETE,
                clusters=[] if energy is None else [_cluster(energy, runs=3)],
            )
            for index, energy in enumerate(energies)
        ],
    )


def _vina_job(
    job_id: str, score: float | None, *, minutes: int = 0
) -> VinaDockingJobRecord:
    return VinaDockingJobRecord(
        job_id=job_id,
        status=(
            DockingJobStatus.COMPLETED if score is not None else DockingJobStatus.FAILED
        ),
        phase=DockingJobPhase.COMPLETE,
        created_at=BASE_TIME + timedelta(minutes=minutes),
        request=VinaDockingRequest(
            receptor_id=RECEPTOR,
            binding_site_id=SITE,
            ligand_id="ligand-solo",
            ligand_preparation_id="prep-1",
            parameters=VinaDockingParameters(),
            acknowledge_inputs_and_scoring=True,
        ),
        tool=VINA_TOOL,
        receptor_output_artifact_id="receptor-pdbqt",
        receptor_sha256="b" * 64,
        ligand_sha256="d" * 64,
        poses=[] if score is None else [_pose(0, score)],
    )


def _autodock4_job(
    job_id: str, energy: float, *, minutes: int = 0
) -> AutoDock4DockingJobRecord:
    return AutoDock4DockingJobRecord(
        job_id=job_id,
        status=AutoDock4JobStatus.COMPLETED,
        phase=AutoDock4JobPhase.COMPLETE,
        created_at=BASE_TIME + timedelta(minutes=minutes),
        request=AutoDock4DockingRequest(
            receptor_id=RECEPTOR,
            binding_site_id=SITE,
            map_set_id="map-set-1",
            ligand_id="ligand-solo",
            ligand_preparation_id="prep-1",
            acknowledge_inputs_and_scoring=True,
        ),
        autodock4=CPU_TOOL,
        receptor_id=RECEPTOR,
        binding_site_id=SITE,
        map_set_id="map-set-1",
        map_set_identity_key="f" * 64,
        ligand_sha256="d" * 64,
        ligand_atom_types=["C", "OA"],
        ligand_atom_count=12,
        torsional_degrees_of_freedom=3,
        clusters=[_cluster(energy, runs=9)],
    )


class _FakeBindingSiteStore:
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


class _FakeLigandStore:
    """Only the inspection matters here, so only the inspection is modelled."""

    def __init__(self, names: dict[str, str]) -> None:
        self._names = names

    def load_record(self, ligand_id: str) -> object:
        try:
            name = self._names[ligand_id]
        except KeyError as error:
            raise AnkoraDomainError(
                code="LIGAND_NOT_FOUND",
                stage="ligand_storage",
                message="No such ligand.",
                status_code=404,
            ) from error
        inspection = type(
            "_Inspection",
            (),
            {"name": name, "canonical_smiles": "CCN", "molecular_weight_g_mol": 45.0},
        )()
        return type("_Record", (), {"inspection": inspection})()


class _FakeDockingStore:
    def __init__(
        self,
        batches: list[VinaBatchDockingRecord],
        jobs: list[VinaDockingJobRecord],
    ) -> None:
        self._batches = {record.batch_id: record for record in batches}
        self._jobs = {record.job_id: record for record in jobs}

    def list_batch_records(self) -> list[VinaBatchDockingRecord]:
        return list(self._batches.values())

    def load_batch_record(self, batch_id: str) -> VinaBatchDockingRecord:
        return self._batches[batch_id]

    def list_jobs(self) -> list[VinaDockingJobRecord]:
        return list(self._jobs.values())

    def load_record(self, job_id: str) -> VinaDockingJobRecord:
        return self._jobs[job_id]


class _FakeAutoDock4Store:
    def __init__(
        self,
        batches: list[AutoDock4BatchRecord],
        jobs: list[AutoDock4DockingJobRecord],
    ) -> None:
        self._batches = {record.batch_id: record for record in batches}
        self._jobs = {record.job_id: record for record in jobs}

    def list_batches(self) -> list[AutoDock4BatchRecord]:
        return list(self._batches.values())

    def load_batch(self, batch_id: str) -> AutoDock4BatchRecord:
        return self._batches[batch_id]

    def list_jobs(self) -> list[AutoDock4DockingJobRecord]:
        return list(self._jobs.values())

    def load_job(self, job_id: str) -> AutoDock4DockingJobRecord:
        return self._jobs[job_id]


class _FakeGpuStore:
    def __init__(self, batches: list[AutoDockGpuBatchRecord]) -> None:
        self._batches = {record.batch_id: record for record in batches}

    def list_batches(self) -> list[AutoDockGpuBatchRecord]:
        return list(self._batches.values())

    def load_batch(self, batch_id: str) -> AutoDockGpuBatchRecord:
        return self._batches[batch_id]

    def list_jobs(self) -> list[Any]:
        return []


def _service(
    *,
    vina: list[VinaBatchDockingRecord] | None = None,
    autodock4: list[AutoDock4BatchRecord] | None = None,
    gpu: list[AutoDockGpuBatchRecord] | None = None,
    vina_jobs: list[VinaDockingJobRecord] | None = None,
    autodock4_jobs: list[AutoDock4DockingJobRecord] | None = None,
    boxes: dict[str, BindingBox] | None = None,
    ligands: dict[str, str] | None = None,
) -> ResultCatalogService:
    return ResultCatalogService(
        docking_store=_FakeDockingStore(vina or [], vina_jobs or []),  # type: ignore[arg-type]
        autodock4_store=_FakeAutoDock4Store(  # type: ignore[arg-type]
            autodock4 or [], autodock4_jobs or []
        ),
        autodock_gpu_store=_FakeGpuStore(gpu or []),  # type: ignore[arg-type]
        binding_site_store=_FakeBindingSiteStore(  # type: ignore[arg-type]
            boxes if boxes is not None else {SITE: BOX, OTHER_SITE: ELSEWHERE}
        ),
        ligand_store=_FakeLigandStore(  # type: ignore[arg-type]
            ligands if ligands is not None else {"ligand-solo": "RV2"}
        ),
    )


# --- the two boundaries the spec sets --------------------------------------


def test_a_better_looking_vina_score_never_outranks_a_newer_autodock_campaign() -> None:
    """Ordering a mixed catalog by "best" would compare two scales.

    Vina's empirical score runs several kcal/mol below an AutoDock4 binding
    energy for the same molecule, so score order would put every Vina campaign
    on top and read as a verdict. Time is the only shared axis.
    """
    service = _service(
        vina=[_vina_batch("vina", [-9.9], minutes=0)],
        autodock4=[_autodock4_batch("cpu", [-5.0], minutes=60)],
    )

    order = [entry.catalog_id for entry in service.list_campaigns().entries]

    assert order == ["autodock4_batch:cpu", "vina_batch:vina"]


def test_a_listing_carries_no_results() -> None:
    """A completed campaign is megabytes of poses; a page is identity.

    The real project holds 25 MiB across nine campaigns, so a listing that
    embedded results would be unusable at the size a real project reaches.
    """
    service = _service(vina=[_vina_batch("vina", [-7.5, -7.1, None])])

    entry = service.list_campaigns().entries[0]
    payload = entry.model_dump()

    assert not {"poses", "clusters", "entries", "runs"} & set(payload)
    # What a listing does carry: how the campaign went, in counts.
    assert (entry.selected_count, entry.succeeded_count, entry.failed_count) == (3, 2, 1)


def test_each_engine_names_its_own_quantity() -> None:
    """Never just "score": the header is where the two scales stay apart."""
    service = _service(
        vina=[_vina_batch("vina", [-7.5])],
        autodock4=[_autodock4_batch("cpu", [-5.0])],
    )

    assert service.list_compounds("vina_batch:vina").value_label == (
        "Vina score (kcal/mol)"
    )
    assert service.list_compounds("autodock4_batch:cpu").value_label == (
        "Binding energy (kcal/mol)"
    )


def test_the_backend_is_part_of_the_engines_name() -> None:
    """Same scoring family, different execution - and only one reproducible."""
    service = _service(
        autodock4=[_autodock4_batch("cpu", [-5.0])],
        gpu=[_gpu_batch("gpu", [-5.1])],
    )

    entries = {e.engine_key: e for e in service.list_campaigns().entries}
    cpu = entries["autodock4_batch"]
    gpu = entries["autodock_gpu_batch"]

    assert cpu.engine_label == "AutoDock 4.2.6 · CPU"
    assert gpu.engine_label == "AutoDock4 · AutoDock-GPU 1.6"
    assert cpu.bitwise_reproducible is True
    assert gpu.bitwise_reproducible is False
    assert gpu.device_name == "NVIDIA GeForce RTX 5050"
    # One scoring family, so a reader is never told these are different scales.
    assert cpu.scoring_family is gpu.scoring_family is ScoringFamily.AUTODOCK4


# --- compounds --------------------------------------------------------------


def test_vina_counts_poses_and_autodock_counts_clusters() -> None:
    """Neither shape is fabricated for the engine that does not produce it."""
    service = _service(
        vina=[_vina_batch("vina", [-7.5])],
        autodock4=[_autodock4_batch("cpu", [-5.0])],
    )

    vina = service.list_compounds("vina_batch:vina").rows[0]
    cpu = service.list_compounds("autodock4_batch:cpu").rows[0]

    assert (vina.pose_count, vina.cluster_count, vina.top_cluster_runs) == (1, None, None)
    assert (cpu.pose_count, cpu.cluster_count, cpu.top_cluster_runs) == (None, 1, 6)


def test_a_molecule_that_was_never_docked_keeps_its_row_and_sorts_last() -> None:
    """A selection of 3 that produced 2 results is not a table of 2 rows."""
    service = _service(vina=[_vina_batch("vina", [-7.0, None, -7.5])])

    page = service.list_compounds("vina_batch:vina")

    assert page.total == 3
    assert [row.name for row in page.rows] == [
        "Compound 2",
        "Compound 0",
        "Compound 1",
    ]
    assert page.rows[-1].status == "failed"
    assert page.rows[-1].best_result_kcal_mol is None


def test_manifest_order_survives_the_ranking() -> None:
    """Ranked order is a view; which molecule this was stays on the row."""
    service = _service(vina=[_vina_batch("vina", [-7.0, -8.0])])

    page = service.list_compounds("vina_batch:vina")

    assert [row.source_index for row in page.rows] == [1, 0]


def test_a_page_of_compounds_reports_the_whole_table_it_came_from() -> None:
    """Otherwise the interface cannot tell 100 rows from the first 100."""
    service = _service(vina=[_vina_batch("vina", [-1.0 * n for n in range(1, 11)])])

    page = service.list_compounds("vina_batch:vina", offset=2, limit=3)

    assert page.total == 10
    assert len(page.rows) == 3
    assert (page.offset, page.limit) == (2, 3)


def test_compounds_can_be_narrowed_without_losing_the_count() -> None:
    service = _service(vina=[_vina_batch("vina", [-7.0, None, -7.5])])

    failed = service.list_compounds("vina_batch:vina", status="failed")
    searched = service.list_compounds("vina_batch:vina", search="compound 2")

    assert (failed.total, failed.rows[0].name) == (1, "Compound 1")
    assert (searched.total, searched.rows[0].name) == (1, "Compound 2")


# --- single-ligand results --------------------------------------------------


def test_a_single_ligand_job_is_catalogued_beside_the_campaigns() -> None:
    """One molecule against one pocket is as durable a result as a library."""
    service = _service(
        vina=[_vina_batch("vina", [-7.5], minutes=0)],
        vina_jobs=[_vina_job("solo", -8.1, minutes=30)],
    )

    page = service.list_campaigns()
    solo = page.entries[0]

    assert page.total == 2
    assert solo.mode is ResultMode.SINGLE_LIGAND
    assert solo.catalog_id == "vina_job:solo"
    assert (solo.selected_count, solo.succeeded_count) == (1, 0 + 1)
    assert solo.ligand_id == "ligand-solo"
    assert solo.best_molecule == "RV2"


def test_a_single_ligand_job_reads_as_a_one_row_table() -> None:
    """The interface has one results table, not one per mode."""
    service = _service(autodock4_jobs=[_autodock4_job("solo", -4.96)])

    page = service.list_compounds("autodock4_job:solo")

    assert page.total == 1
    assert page.rows[0].name == "RV2"
    assert page.rows[0].best_result_kcal_mol == -4.96
    assert page.rows[0].top_cluster_runs == 9


def test_a_finished_job_survives_the_ligand_being_gone() -> None:
    """A result outlives its inputs; it must not become unreadable with them."""
    service = _service(vina_jobs=[_vina_job("solo", -8.1)], ligands={})

    page = service.list_compounds("vina_job:solo")

    assert page.rows[0].name == "ligand-solo"
    assert page.rows[0].best_result_kcal_mol == -8.1


# --- filtering and identity -------------------------------------------------


def test_the_catalog_can_be_narrowed_to_one_pocket_or_one_mode() -> None:
    service = _service(
        vina=[
            _vina_batch("here", [-7.5], site=SITE),
            _vina_batch("elsewhere", [-7.9], site=OTHER_SITE),
        ],
        vina_jobs=[_vina_job("solo", -8.1)],
    )

    by_site = service.list_campaigns(binding_site_id=OTHER_SITE)
    screening = service.list_campaigns(mode=ResultMode.SCREENING)
    family = service.list_campaigns(scoring_family=ScoringFamily.AUTODOCK4)

    assert [e.catalog_id for e in by_site.entries] == ["vina_batch:elsewhere"]
    assert by_site.total == 1
    assert screening.total == 2
    assert family.total == 0


def test_a_page_reports_the_whole_catalog_it_came_from() -> None:
    service = _service(
        vina=[_vina_batch(f"batch-{n}", [-7.0], minutes=n) for n in range(7)]
    )

    page = service.list_campaigns(offset=5, limit=3)

    assert page.total == 7
    assert len(page.entries) == 2


def test_every_entry_carries_the_search_space_it_ran_in() -> None:
    """Which pocket is half of what identifies a result, and ids do not say.

    Confirming one pocket twice writes two records carrying the same box, so
    the box is the part a reader can actually compare.
    """
    service = _service(vina=[_vina_batch("vina", [-7.5])])

    entry = service.list_campaigns().entries[0]

    assert entry.box["center_x"] == 35.4
    assert entry.box["size_x"] == 21.6


def test_a_result_whose_binding_site_record_is_gone_is_still_listed() -> None:
    """Losing the pocket record must not hide the campaign that used it."""
    service = _service(vina=[_vina_batch("vina", [-7.5])], boxes={})

    page = service.list_campaigns()

    assert page.total == 1
    assert page.entries[0].box == {}
    assert page.entries[0].binding_site_id == SITE


def test_the_catalog_refuses_a_kind_of_record_it_does_not_understand() -> None:
    service = _service()

    with pytest.raises(AnkoraDomainError) as error:
        service.get_campaign("gnina_batch:whatever")

    assert error.value.code == "RESULT_CATALOG_ENGINE_UNKNOWN"


def test_a_catalog_identifier_names_both_its_engine_and_its_record() -> None:
    service = _service()

    with pytest.raises(AnkoraDomainError) as error:
        service.get_campaign("just-an-id")

    assert error.value.code == "RESULT_CATALOG_ID_INVALID"
