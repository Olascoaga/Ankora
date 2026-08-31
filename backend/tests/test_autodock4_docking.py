"""Service tests for AutoDock4 CPU single-ligand docking (ADR-015 Phase 2).

The synthetic AutoDock4 replays a real captured DLG, so the parsing and result
contract exercised here is the one the real binary produces. Real end-to-end
execution is recorded separately as Windows validation evidence.
"""

import json
import pathlib
import threading
import time
from hashlib import sha256
from pathlib import Path

import pytest
from test_autogrid_maps import _install_synthetic_autogrid
from test_autogrid_maps import _service as _map_service

from ankora_backend.adapters.engines.autodock4_runner import (
    DOCKING_LOG_FILENAME,
    AutoDock4Installation,
)
from ankora_backend.domain.errors import AnkoraDomainError
from ankora_backend.execution.cancellable_subprocess import CancellableToolExecution
from ankora_backend.persistence.autodock4_store import AutoDock4JobStore
from ankora_backend.persistence.autogrid_store import AutoGridMapStore
from ankora_backend.persistence.binding_site_store import BindingSiteArtifactStore
from ankora_backend.persistence.ligand_store import LigandArtifactStore
from ankora_backend.persistence.receptor_store import ReceptorArtifactStore
from ankora_backend.schemas.autodock4 import (
    AutoDock4BatchParameters,
    AutoDock4BatchRequest,
    AutoDock4DockingParameters,
    AutoDock4DockingRequest,
    AutoDock4JobPhase,
    AutoDock4JobStatus,
)
from ankora_backend.schemas.warnings import WarningCode
from ankora_backend.services import autodock4_docking as docking_module
from ankora_backend.services.autodock4_docking import AutoDock4DockingService

REAL_LOG = (
    Path(__file__).parent / "fixtures" / "autodock4_real_compound1.dlg"
).read_text(encoding="utf-8", errors="replace")


def _installation() -> AutoDock4Installation:
    return AutoDock4Installation(
        executable="synthetic-autodock4.exe",
        version="4.2.6",
        sha256="c" * 64,
        architecture="x86",
        max_torsions=32,
        max_atoms=2048,
        max_maps=16,
    )


def _execution(
    *,
    exit_code: int = 0,
    canceled: bool = False,
    timed_out: bool = False,
    stderr: str = "",
) -> CancellableToolExecution:
    return CancellableToolExecution(
        command=["synthetic-autodock4.exe", "-p", "ligand.dpf"],
        exit_code=exit_code,
        stdout="",
        stderr=stderr,
        canceled=canceled,
        timed_out=timed_out,
    )


def _replay_real_log(**kwargs: object) -> CancellableToolExecution:
    job_directory = kwargs["job_directory"]
    assert isinstance(job_directory, Path)
    (job_directory / DOCKING_LOG_FILENAME).write_text(REAL_LOG, encoding="utf-8")
    return _execution()


def _docking_fixture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[AutoDock4DockingService, AutoDock4DockingRequest]:
    map_service, map_request = _map_service(tmp_path, monkeypatch)
    _install_synthetic_autogrid(monkeypatch)
    map_set = map_service.ensure_map_set(map_request).record

    ligand_store = LigandArtifactStore(tmp_path)
    filter_run = ligand_store.load_filter_run(
        map_request.library_id or "", map_request.filter_run_id or ""
    )
    ligand_id = filter_run.selected_ligand_ids[0]
    preparation = ligand_store.load_preparation_status(map_request.library_id or "")
    preparation_id = preparation.entries[ligand_id].pdbqt_preparation_id
    assert preparation_id is not None

    service = AutoDock4DockingService(
        job_store=AutoDock4JobStore(tmp_path),
        map_store=AutoGridMapStore(tmp_path),
        ligand_store=ligand_store,
        receptor_store=ReceptorArtifactStore(tmp_path),
        binding_site_store=BindingSiteArtifactStore(tmp_path),
    )
    request = AutoDock4DockingRequest(
        receptor_id=map_set.receptor_id,
        binding_site_id=map_set.binding_site_id,
        map_set_id=map_set.map_set_id,
        ligand_id=ligand_id,
        ligand_preparation_id=preparation_id,
        parameters=AutoDock4DockingParameters(ga_runs=3),
        acknowledge_inputs_and_scoring=True,
    )
    monkeypatch.setattr(docking_module, "probe_autodock4", _installation)
    return service, request


def _restate_pdbqt_hash(pdbqt_path: Path, content: bytes) -> None:
    """Keep a deliberately edited fixture's recorded hash honest."""
    record_path = pdbqt_path.parent / "record.json"
    record = json.loads(record_path.read_text(encoding="utf-8"))
    record["artifact"]["sha256"] = sha256(content).hexdigest()
    record["artifact"]["size_bytes"] = len(content)
    record_path.write_text(
        json.dumps(record, indent=2), encoding="utf-8", newline="\n"
    )


def _wait(service: AutoDock4DockingService, job_id: str) -> object:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        record = service.get(job_id)
        if record.status in {
            AutoDock4JobStatus.COMPLETED,
            AutoDock4JobStatus.CANCELED,
            AutoDock4JobStatus.FAILED,
        }:
            return record
        time.sleep(0.01)
    raise AssertionError("the synthetic AutoDock4 job did not terminate")


def test_completed_job_reports_clusters_and_create_only_poses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Results stay cluster-native: cluster population is preserved rather than
    flattened into a Vina-shaped ranked pose list."""
    service, request = _docking_fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(
        docking_module, "execute_autodock4_cancellable", _replay_real_log
    )

    job = service.start(request)
    assert job.status is AutoDock4JobStatus.QUEUED
    record = _wait(service, job.job_id)

    assert record.status is AutoDock4JobStatus.COMPLETED  # type: ignore[attr-defined]
    assert record.phase is AutoDock4JobPhase.COMPLETE  # type: ignore[attr-defined]
    clusters = record.clusters  # type: ignore[attr-defined]
    assert [cluster.cluster_rank for cluster in clusters] == [1, 2]
    assert clusters[0].run_count == 2
    assert clusters[0].runs == [3, 2]
    assert clusters[0].lowest_binding_energy_kcal_mol == -3.40
    assert clusters[1].runs == [1]
    runs = record.runs  # type: ignore[attr-defined]
    assert [item.run for item in runs] == [1, 2, 3]
    assert runs[0].artifact.filename == "run_1.pdbqt"
    content = service.pose_content_path(
        job.job_id, runs[0].artifact.artifact_id
    ).read_text(encoding="utf-8")
    assert content.startswith("MODEL")
    assert "DOCKED:" not in content
    assert record.provenance is not None  # type: ignore[attr-defined]
    service.shutdown()


def test_a_ligand_type_absent_from_the_map_set_is_refused_before_running(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AutoDock cannot score an atom type it has no affinity map for, so the
    mismatch must surface as a decision, not as a cryptic tool failure."""
    service, request = _docking_fixture(tmp_path, monkeypatch)

    def must_not_run(**_kwargs: object) -> CancellableToolExecution:
        raise AssertionError("AutoDock4 must not run for an uncovered atom type")

    monkeypatch.setattr(docking_module, "execute_autodock4_cancellable", must_not_run)
    # Give the prepared ligand an atom type the map set does not cover, keeping
    # its recorded hash truthful so the production integrity check still runs.
    ligand_store = LigandArtifactStore(tmp_path)
    path = ligand_store.pdbqt_content_path(
        request.ligand_id, request.ligand_preparation_id
    )
    mutated = path.read_bytes().replace(b" OA\n", b" Fe\n")
    path.write_bytes(mutated)
    _restate_pdbqt_hash(path, mutated)

    with pytest.raises(AnkoraDomainError) as failure:
        service.start(request)

    assert failure.value.code == "AUTODOCK4_LIGAND_TYPES_NOT_IN_MAP_SET"
    assert failure.value.details["missing_atom_types"] == ["Fe"]
    service.shutdown()


def test_a_map_set_from_another_receptor_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service, request = _docking_fixture(tmp_path, monkeypatch)

    with pytest.raises(AnkoraDomainError) as failure:
        service.start(
            request.model_copy(update={"receptor_id": "another-receptor"})
        )

    # A receptor that does not exist fails before any map comparison.
    assert failure.value.status_code in {404, 422}
    service.shutdown()


def test_a_map_set_from_an_equivalent_binding_site_record_is_accepted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One receptor accumulates many binding-site records with the same box, and
    map identity is keyed on geometry rather than on which record produced it.
    Rejecting a reused map set by record id would refuse a correct reuse."""
    service, request = _docking_fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(
        docking_module, "execute_autodock4_cancellable", _replay_real_log
    )
    binding_store = BindingSiteArtifactStore(tmp_path)
    original = binding_store.load_record(request.binding_site_id)
    twin_id = binding_store.new_binding_site_id()
    binding_store.save_record(
        original.model_copy(update={"binding_site_id": twin_id})
    )

    job = service.start(request.model_copy(update={"binding_site_id": twin_id}))
    record = _wait(service, job.job_id)

    assert record.status is AutoDock4JobStatus.COMPLETED  # type: ignore[attr-defined]
    # The job records the site the scientist asked for, not the map set's origin.
    assert record.binding_site_id == twin_id  # type: ignore[attr-defined]
    assert [w.code for w in record.warnings] == [  # type: ignore[attr-defined]
        WarningCode.DOCKING_MAPS_FROM_EQUIVALENT_SITE
    ]
    service.shutdown()


def test_a_map_set_covering_a_different_box_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service, request = _docking_fixture(tmp_path, monkeypatch)
    binding_store = BindingSiteArtifactStore(tmp_path)
    original = binding_store.load_record(request.binding_site_id)
    moved_id = binding_store.new_binding_site_id()
    binding_store.save_record(
        original.model_copy(
            update={
                "binding_site_id": moved_id,
                "box": original.box.model_copy(update={"size_x": 30.0}),
            }
        )
    )

    with pytest.raises(AnkoraDomainError) as failure:
        service.start(request.model_copy(update={"binding_site_id": moved_id}))

    assert failure.value.code == "AUTODOCK4_MAP_SET_BOX_MISMATCH"
    service.shutdown()


def test_docking_requires_explicit_acknowledgement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service, request = _docking_fixture(tmp_path, monkeypatch)

    with pytest.raises(AnkoraDomainError) as failure:
        service.start(
            request.model_copy(update={"acknowledge_inputs_and_scoring": False})
        )

    assert failure.value.code == "AUTODOCK4_CONFIRMATION_REQUIRED"
    service.shutdown()


def test_canceling_a_running_job_publishes_no_results(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service, request = _docking_fixture(tmp_path, monkeypatch)
    entered = threading.Event()

    def blocking(**kwargs: object) -> CancellableToolExecution:
        cancel_event = kwargs["cancel_event"]
        assert isinstance(cancel_event, threading.Event)
        entered.set()
        cancel_event.wait(timeout=5)
        return _execution(exit_code=1, canceled=True)

    monkeypatch.setattr(docking_module, "execute_autodock4_cancellable", blocking)

    job = service.start(request)
    assert entered.wait(timeout=5)
    assert service.cancel(job.job_id).status is AutoDock4JobStatus.CANCEL_REQUESTED
    record = _wait(service, job.job_id)

    assert record.status is AutoDock4JobStatus.CANCELED  # type: ignore[attr-defined]
    assert record.runs == []  # type: ignore[attr-defined]
    assert record.clusters == []  # type: ignore[attr-defined]
    service.shutdown()


def test_a_failed_run_preserves_structured_evidence_and_no_results(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AutoDock can exit zero on an incomplete run, so a log without the
    completion marker is still a failure."""
    service, request = _docking_fixture(tmp_path, monkeypatch)

    def silent(**kwargs: object) -> CancellableToolExecution:
        job_directory = kwargs["job_directory"]
        assert isinstance(job_directory, Path)
        (job_directory / DOCKING_LOG_FILENAME).write_text(
            "autodock synthetic partial log\n", encoding="utf-8"
        )
        return _execution(exit_code=0)

    monkeypatch.setattr(docking_module, "execute_autodock4_cancellable", silent)

    job = service.start(request)
    record = _wait(service, job.job_id)

    assert record.status is AutoDock4JobStatus.FAILED  # type: ignore[attr-defined]
    assert record.failure is not None  # type: ignore[attr-defined]
    assert record.failure.code == "AUTODOCK4_EXECUTION_FAILED"  # type: ignore[attr-defined]
    assert record.failure.details["successful_completion_logged"] is False  # type: ignore[attr-defined]
    assert record.runs == []  # type: ignore[attr-defined]
    service.shutdown()


def _batch_fixture(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[AutoDock4DockingService, AutoDock4BatchRequest]:
    service, single = _docking_fixture(tmp_path, monkeypatch)
    ligand_store = LigandArtifactStore(tmp_path)
    map_store = AutoGridMapStore(tmp_path)
    map_set = map_store.load_record(single.map_set_id)
    library_id = map_set.request.library_id
    filter_run_id = map_set.request.filter_run_id
    assert library_id is not None and filter_run_id is not None
    assert ligand_store.load_filter_run(library_id, filter_run_id) is not None
    request = AutoDock4BatchRequest(
        receptor_id=single.receptor_id,
        binding_site_id=single.binding_site_id,
        map_set_id=single.map_set_id,
        library_id=library_id,
        filter_run_id=filter_run_id,
        parameters=AutoDock4BatchParameters(ga_runs=3, parallel_ligands=2),
        acknowledge_inputs_and_scoring=True,
    )
    return service, request


def _wait_batch(service: AutoDock4DockingService, batch_id: str) -> object:
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        record = service.get_batch(batch_id)
        if record.status in {
            AutoDock4JobStatus.COMPLETED,
            AutoDock4JobStatus.CANCELED,
            AutoDock4JobStatus.FAILED,
        }:
            return record
        time.sleep(0.01)
    raise AssertionError("the synthetic AutoDock4 campaign did not terminate")


def test_every_molecule_gets_its_own_autodock_clustering(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Parallelism is per molecule, so each one runs a complete AutoDock4 process
    and reports the clusters AutoDock itself produced."""
    service, request = _batch_fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(
        docking_module, "execute_autodock4_cancellable", _replay_real_log
    )

    batch = service.start_batch(request)
    record = _wait_batch(service, batch.batch_id)

    assert record.status is AutoDock4JobStatus.COMPLETED  # type: ignore[attr-defined]
    assert record.succeeded_count == 2  # type: ignore[attr-defined]
    assert record.worker_count == 2  # type: ignore[attr-defined]
    for entry in record.entries:  # type: ignore[attr-defined]
        assert entry.status is AutoDock4JobStatus.COMPLETED
        assert [cluster.cluster_rank for cluster in entry.clusters] == [1, 2]
        assert [run.run for run in entry.runs] == [1, 2, 3]
        # Poses are create-only per molecule, under that molecule's directory.
        path = service.batch_pose_content_path(
            batch.batch_id, entry.ligand_id, entry.runs[0].artifact.artifact_id
        )
        assert path.read_text(encoding="utf-8").startswith("MODEL")
    service.shutdown()


def test_one_molecule_failing_does_not_stop_the_others(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service, request = _batch_fixture(tmp_path, monkeypatch)
    seen: list[str] = []

    def flaky(**kwargs: object) -> CancellableToolExecution:
        directory = kwargs["job_directory"]
        assert isinstance(directory, pathlib.Path)
        seen.append(directory.name)
        if len(seen) == 1:
            (directory / DOCKING_LOG_FILENAME).write_text(
                "autodock synthetic partial log\n", encoding="utf-8"
            )
            return _execution(exit_code=1, stderr="synthetic failure")
        return _replay_real_log(**kwargs)

    monkeypatch.setattr(docking_module, "execute_autodock4_cancellable", flaky)

    batch = service.start_batch(
        request.model_copy(
            update={
                "parameters": request.parameters.model_copy(
                    update={"parallel_ligands": 1}
                )
            }
        )
    )
    record = _wait_batch(service, batch.batch_id)

    assert record.status is AutoDock4JobStatus.COMPLETED  # type: ignore[attr-defined]
    assert record.succeeded_count == 1  # type: ignore[attr-defined]
    assert record.failed_count == 1  # type: ignore[attr-defined]
    failed = [
        entry for entry in record.entries  # type: ignore[attr-defined]
        if entry.status is AutoDock4JobStatus.FAILED
    ]
    assert len(failed) == 1
    assert failed[0].failure is not None
    assert failed[0].failure.code == "AUTODOCK4_EXECUTION_FAILED"
    service.shutdown()


def test_progress_counts_every_molecule_without_resending_results(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service, request = _batch_fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(
        docking_module, "execute_autodock4_cancellable", _replay_real_log
    )

    batch = service.start_batch(request)
    _wait_batch(service, batch.batch_id)
    progress = service.get_batch_progress(batch.batch_id, 0)

    assert progress.selected_count == 2
    assert progress.completed_count == 2
    assert progress.succeeded_count == 2
    assert progress.running_ligand_ids == []
    assert progress.revision > 0
    service.shutdown()


def test_a_second_campaign_is_refused_while_one_is_running(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AutoDock4 4.2.6 is single-threaded, so the pool is the whole CPU budget;
    two campaigns would oversubscribe it."""
    service, request = _batch_fixture(tmp_path, monkeypatch)
    release = threading.Event()

    def blocking(**kwargs: object) -> CancellableToolExecution:
        release.wait(timeout=5)
        return _replay_real_log(**kwargs)

    monkeypatch.setattr(docking_module, "execute_autodock4_cancellable", blocking)

    first = service.start_batch(request)
    try:
        with pytest.raises(AnkoraDomainError) as failure:
            service.start_batch(request)
        assert failure.value.code == "AUTODOCK4_BATCH_ALREADY_ACTIVE"
    finally:
        release.set()
    _wait_batch(service, first.batch_id)
    service.shutdown()
