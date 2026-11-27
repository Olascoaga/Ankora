"""Regression tests for Wave 3 D8 docking engine parity & lifecycle fixes.

All fixtures, tool outputs, and execution evidence in this module are synthetic
(reusing recorded real DLG fixtures where applicable).
"""

import json
import threading
import time
from datetime import UTC, datetime
from pathlib import Path

import pytest
from test_autodock4_docking import (
    _batch_fixture as _ad4_batch_fixture,
)
from test_autodock4_docking import (
    _replay_real_log as _ad4_replay_real_log,
)
from test_autodock4_docking import (
    _wait_batch as _ad4_wait_batch,
)
from test_autodock_gpu_docking import (
    REAL_LOG as GPU_REAL_LOG,
)
from test_autodock_gpu_docking import (
    _batch_fixture as _gpu_batch_fixture,
)
from test_autodock_gpu_docking import (
    _execution as _gpu_execution,
)
from test_autodock_gpu_docking import (
    _fixture as _gpu_single_fixture,
)
from test_autodock_gpu_docking import (
    _probe_test_arbiter,
)
from test_autodock_gpu_docking import (
    _replay_filelist as _gpu_replay_filelist,
)
from test_autodock_gpu_docking import (
    _wait_batch as _gpu_wait_batch,
)
from test_gnina_service import _setup as _gnina_setup
from test_vina_docking import (
    SYNTHETIC_POSES as VINA_SYNTHETIC_POSES,
)
from test_vina_docking import (
    _batch_request as _vina_batch_request,
)
from test_vina_docking import (
    _service as _vina_single_service,
)
from test_vina_docking import (
    _wait_for_batch_terminal as _vina_wait_batch,
)

from ankora_backend.adapters.engines.autodock4_runner import DOCKING_LOG_FILENAME
from ankora_backend.adapters.engines.vina import VinaInstallation
from ankora_backend.domain.errors import AnkoraDomainError
from ankora_backend.execution.cancellable_subprocess import CancellableToolExecution
from ankora_backend.persistence.binding_site_store import BindingSiteArtifactStore
from ankora_backend.persistence.ligand_store import LigandArtifactStore
from ankora_backend.schemas.autodock4 import AutoDock4JobStatus
from ankora_backend.schemas.autodock_gpu import AutoDockJobStatus
from ankora_backend.schemas.docking import (
    DockingJobStatus,
    VinaLocalRefinementRequest,
)
from ankora_backend.schemas.ligand_library_preparation import LigandPreparationStatus
from ankora_backend.services import autodock4_docking as ad4_module
from ankora_backend.services import autodock_gpu_docking as gpu_module
from ankora_backend.services import vina_docking as vina_module
from ankora_backend.services.project_dependencies import ProjectDependencyService
from ankora_backend.services.resource_arbiter import (
    ResourceArbiter,
    autodock4_claim,
    autodock_gpu_claim,
)


def test_d8_001_autodock_gpu_latest_batch_prefers_active_and_returns_full_entries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service, request = _gpu_batch_fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(gpu_module, "execute_autodock_gpu_cancellable", _gpu_replay_filelist)
    first = _gpu_wait_batch(service, service.start_batch(request).batch_id)
    assert first.status is AutoDockJobStatus.COMPLETED  # type: ignore[attr-defined]
    assert first.succeeded_count == 2  # type: ignore[attr-defined]

    entered = threading.Event()
    release = threading.Event()

    def blocking(**kwargs: object) -> CancellableToolExecution:
        event = kwargs["cancel_event"]
        assert isinstance(event, threading.Event)
        entered.set()
        release.wait(timeout=5)
        return _gpu_execution(stdout="", canceled=True)

    monkeypatch.setattr(gpu_module, "execute_autodock_gpu_cancellable", blocking)
    second = service.start_batch(request)
    try:
        assert entered.wait(timeout=5)
        latest_while_running = service.latest_batch(
            receptor_id=request.receptor_id,
            binding_site_id=request.binding_site_id,
            filter_run_id=request.filter_run_id,
        )
        assert latest_while_running.batch_id == second.batch_id
        assert len(latest_while_running.entries) == 2

        service.cancel_batch(second.batch_id)
        release.set()
        _gpu_wait_batch(service, second.batch_id)

        latest_after_cancel = service.latest_batch(
            receptor_id=request.receptor_id,
            binding_site_id=request.binding_site_id,
            filter_run_id=request.filter_run_id,
        )
        assert latest_after_cancel.batch_id == first.batch_id  # type: ignore[attr-defined]
        assert len(latest_after_cancel.entries) == 2
    finally:
        release.set()
        service.shutdown()


def test_d8_002_autodock_gpu_watch_progress_reports_live_count_and_respects_cancel(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service, request = _gpu_batch_fixture(tmp_path, monkeypatch)
    first_written = threading.Event()
    proceed = threading.Event()

    def staged_filelist(**kwargs: object) -> CancellableToolExecution:
        work = kwargs["job_directory"]
        assert isinstance(work, Path)
        tags = (work / "campaign.lst").read_text(encoding="ascii").splitlines()[2::2]
        assert len(tags) == 2
        (work / f"{tags[0]}.dlg").write_text(GPU_REAL_LOG, encoding="utf-8")
        first_written.set()
        proceed.wait(timeout=5)
        (work / f"{tags[1]}.dlg").write_text(GPU_REAL_LOG, encoding="utf-8")
        return _gpu_execution()

    monkeypatch.setattr(gpu_module, "execute_autodock_gpu_cancellable", staged_filelist)
    started = service.start_batch(request)
    try:
        assert first_written.wait(timeout=5)
        deadline = time.monotonic() + 5
        observed = 0
        while time.monotonic() < deadline:
            progress = service.get_batch_progress(started.batch_id)
            if progress.completed_count >= 1:
                observed = progress.completed_count
                break
            time.sleep(0.05)
        assert observed == 1
        assert service.cancel_batch(started.batch_id).status is AutoDockJobStatus.CANCEL_REQUESTED
        # Wait past one watcher cycle to verify CANCEL_REQUESTED is not clobbered back to RUNNING.
        time.sleep(0.6)
        status_after = service.get_batch_progress(started.batch_id).status
        assert status_after is AutoDockJobStatus.CANCEL_REQUESTED
    finally:
        proceed.set()
        _gpu_wait_batch(service, started.batch_id)
        service.shutdown()


def test_d8_003_autodock4_and_gpu_resource_cancel_transitions_all_entries_to_canceled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ad4_dir = tmp_path / "ad4"
    ad4_dir.mkdir()
    ad4_service, ad4_request = _ad4_batch_fixture(ad4_dir, monkeypatch)
    capacity = 8 * 1024**3
    ad4_arbiter = ResourceArbiter(
        cpu_threads=2,
        gpu_slots=1,
        memory_total_bytes=capacity,
        memory_reserve_bytes=0,
        disk_path=ad4_dir,
        disk_total_bytes=capacity,
        disk_reserve_bytes=0,
        memory_available=lambda: capacity,
        disk_free=lambda: capacity,
    )
    monkeypatch.setattr(ad4_service, "_resources", ad4_arbiter)
    ad4_blocker = ad4_arbiter.acquire(
        autodock4_claim("blocker", concurrent_processes=2, ligand_count=1)
    )
    try:
        started = ad4_service.start_batch(ad4_request)
        deadline = time.monotonic() + 5
        while ad4_arbiter.snapshot().queued_requests == 0 and time.monotonic() < deadline:
            time.sleep(0.01)
        ad4_service.cancel_batch(started.batch_id)
        record = _ad4_wait_batch(ad4_service, started.batch_id)
        assert record.status is AutoDock4JobStatus.CANCELED  # type: ignore[attr-defined]
        assert record.canceled_count == record.selected_count  # type: ignore[attr-defined]
        assert record.completed_count == record.selected_count  # type: ignore[attr-defined]
        assert all(
            entry.status is AutoDock4JobStatus.CANCELED
            for entry in record.entries  # type: ignore[attr-defined]
        )
        ad4_record_path = ad4_service._job_store._batch_dir(started.batch_id) / "record.json"
        materialized = json.loads(ad4_record_path.read_text(encoding="utf-8"))
        assert materialized["canceled_count"] == materialized["selected_count"]
        assert all(entry["status"] == "canceled" for entry in materialized["entries"])
    finally:
        ad4_blocker.release()
        ad4_service.shutdown()

    gpu_dir = tmp_path / "gpu"
    gpu_dir.mkdir()
    gpu_service, gpu_request = _gpu_batch_fixture(gpu_dir, monkeypatch)
    gpu_arbiter = _probe_test_arbiter(gpu_dir)
    monkeypatch.setattr(gpu_service, "_resources", gpu_arbiter)
    # Bypass probe reservation during start_batch so the worker itself queues on gpu_arbiter.
    monkeypatch.setattr(
        gpu_service,
        "_probe_installation",
        lambda _dev: gpu_module.probe_autodock_gpu(),
    )
    gpu_blocker = gpu_arbiter.acquire(autodock_gpu_claim("blocker", ligand_count=1))
    try:
        started_gpu = gpu_service.start_batch(gpu_request)
        deadline = time.monotonic() + 5
        while gpu_arbiter.snapshot().queued_requests == 0 and time.monotonic() < deadline:
            time.sleep(0.01)
        gpu_service.cancel_batch(started_gpu.batch_id)
        gpu_record = _gpu_wait_batch(gpu_service, started_gpu.batch_id)
        assert gpu_record.status is AutoDockJobStatus.CANCELED  # type: ignore[attr-defined]
        assert gpu_record.canceled_count == gpu_record.selected_count  # type: ignore[attr-defined]
        assert gpu_record.completed_count == gpu_record.selected_count  # type: ignore[attr-defined]
        assert all(
            entry.status is AutoDockJobStatus.CANCELED
            for entry in gpu_record.entries  # type: ignore[attr-defined]
        )
        gpu_record_path = gpu_service._job_store._batch_dir(started_gpu.batch_id) / "record.json"
        materialized_gpu = json.loads(gpu_record_path.read_text(encoding="utf-8"))
        assert materialized_gpu["canceled_count"] == materialized_gpu["selected_count"]
        assert all(entry["status"] == "canceled" for entry in materialized_gpu["entries"])
    finally:
        gpu_blocker.release()
        gpu_service.shutdown()


def test_d8_004_vina_local_refinement_rejects_stale_inputs_and_stale_parent_lineage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service, request = _vina_single_service(tmp_path)
    monkeypatch.setattr(
        vina_module,
        "probe_vina",
        lambda: VinaInstallation(executable="synthetic-vina", version="1.2.5"),
    )

    def fake_execute(**kwargs: object) -> CancellableToolExecution:
        output_path = kwargs["output_path"]
        assert isinstance(output_path, Path)
        output_path.write_bytes(VINA_SYNTHETIC_POSES)
        return CancellableToolExecution(
            command=["synthetic-vina"],
            exit_code=0,
            stdout="ok",
            stderr="",
            canceled=False,
            timed_out=False,
        )

    monkeypatch.setattr(vina_module, "execute_vina", fake_execute)
    monkeypatch.setattr(
        vina_module,
        "execute_vina_local_only",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("stale local refinement must not execute Vina")
        ),
    )
    started = service.start(request)
    deadline = time.monotonic() + 10
    terminal = {DockingJobStatus.COMPLETED, DockingJobStatus.FAILED}
    parent = service.get(started.job_id)
    while parent.status not in terminal and time.monotonic() < deadline:
        time.sleep(0.01)
        parent = service.get(started.job_id)
    assert parent.status is DockingJobStatus.COMPLETED
    pose_id = parent.poses[0].artifact.artifact_id

    # Mark parent job stale via ProjectDependencyService (while binding_site.stale remains False)
    binding_store = BindingSiteArtifactStore(tmp_path)
    deps = ProjectDependencyService.for_project_root(binding_store.project_root)
    deps.mark_stale(parent.job_id, reason="Synthetic upstream receptor changed")

    with pytest.raises(AnkoraDomainError) as failure:
        service.refine_pose_local_only(
            VinaLocalRefinementRequest(
                parent_job_id=parent.job_id,
                parent_pose_artifact_id=pose_id,
            )
        )
    assert failure.value.status_code == 409
    assert failure.value.code == "PROJECT_INPUT_STALE"
    service.shutdown()


def test_d8_005_autodock_gpu_single_job_verifies_ligand_pdbqt_hash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service, request = _gpu_single_fixture(tmp_path, monkeypatch)
    ligand_store = LigandArtifactStore(tmp_path)
    pdbqt_path = ligand_store.pdbqt_content_path(request.ligand_id, request.ligand_preparation_id)
    pdbqt_path.write_bytes(pdbqt_path.read_bytes() + b"\nREMARK tampered\n")

    with pytest.raises(AnkoraDomainError) as failure:
        service.start(request)
    assert failure.value.code == "AUTODOCK_GPU_INPUT_HASH_MISMATCH"
    assert failure.value.status_code == 422
    service.shutdown()


def test_d8_006_gnina_shutdown_sets_active_cancel_events(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service, _store, _arbiter, leases, _job, _inst = _gnina_setup(tmp_path, monkeypatch)
    active_event = threading.Event()
    service._events["synthetic-active-job"] = active_event  # noqa: SLF001
    try:
        service.shutdown()
        assert active_event.is_set()
    finally:
        leases.shutdown()


def test_d8_007_lease_release_oserror_does_not_deadlock_next_ad4_or_gpu_batch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class FailingReleaseLeases:
        def acquire(self, *_args: object) -> None:
            pass

        def release(self, *_args: object) -> None:
            raise OSError("synthetic lease release I/O error")

    ad4_dir = tmp_path / "ad4"
    ad4_dir.mkdir()
    ad4_service, ad4_request = _ad4_batch_fixture(ad4_dir, monkeypatch)
    monkeypatch.setattr(ad4_module, "execute_autodock4_cancellable", _ad4_replay_real_log)
    monkeypatch.setattr(ad4_service, "_leases", FailingReleaseLeases())
    first_ad4 = _ad4_wait_batch(ad4_service, ad4_service.start_batch(ad4_request).batch_id)
    assert first_ad4.status is AutoDock4JobStatus.COMPLETED  # type: ignore[attr-defined]
    deadline = time.monotonic() + 5
    while ad4_service.has_active_work() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert not ad4_service.has_active_work()
    second_ad4 = _ad4_wait_batch(ad4_service, ad4_service.start_batch(ad4_request).batch_id)
    assert second_ad4.status is AutoDock4JobStatus.COMPLETED  # type: ignore[attr-defined]
    ad4_service.shutdown()

    gpu_dir = tmp_path / "gpu"
    gpu_dir.mkdir()
    gpu_service, gpu_request = _gpu_batch_fixture(gpu_dir, monkeypatch)
    monkeypatch.setattr(gpu_module, "execute_autodock_gpu_cancellable", _gpu_replay_filelist)
    monkeypatch.setattr(gpu_service, "_leases", FailingReleaseLeases())
    first_gpu = _gpu_wait_batch(gpu_service, gpu_service.start_batch(gpu_request).batch_id)
    assert first_gpu.status is AutoDockJobStatus.COMPLETED  # type: ignore[attr-defined]
    deadline = time.monotonic() + 5
    while gpu_service.has_active_work() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert not gpu_service.has_active_work()
    second_gpu = _gpu_wait_batch(gpu_service, gpu_service.start_batch(gpu_request).batch_id)
    assert second_gpu.status is AutoDockJobStatus.COMPLETED  # type: ignore[attr-defined]
    gpu_service.shutdown()


def test_d8_008_autodock4_and_gpu_verify_filter_manifest_and_reject_zero_runnable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ad4_dir = tmp_path / "ad4"
    ad4_dir.mkdir()
    ad4_service, ad4_request = _ad4_batch_fixture(ad4_dir, monkeypatch)
    ad4_store = LigandArtifactStore(ad4_dir)
    manifest_path = ad4_store.filter_run_content_path(
        ad4_request.library_id, ad4_request.filter_run_id
    )
    original_bytes = manifest_path.read_bytes()
    manifest_path.write_bytes(original_bytes + b"\n")
    with pytest.raises(AnkoraDomainError) as ad4_hash_err:
        ad4_service.start_batch(ad4_request)
    assert ad4_hash_err.value.code == "AUTODOCK4_INPUT_HASH_MISMATCH"
    assert ad4_hash_err.value.status_code == 422
    manifest_path.write_bytes(original_bytes)

    # Mark all selected molecules unprepared -> 0 runnable must raise 422
    prep = ad4_store.load_preparation_status(ad4_request.library_id)
    for _lid, entry in prep.entries.items():
        ad4_store.upsert_preparation_entry(
            ad4_request.library_id,
            entry.model_copy(
                update={
                    "status": LigandPreparationStatus.FAILED,
                    "pdbqt_preparation_id": None,
                    "updated_at": datetime.now(UTC),
                }
            ),
        )
    with pytest.raises(AnkoraDomainError) as zero_err:
        ad4_service.start_batch(ad4_request)
    assert zero_err.value.code == "AUTODOCK4_NO_RUNNABLE_MOLECULES"
    assert zero_err.value.status_code == 422
    ad4_service.shutdown()

    gpu_dir = tmp_path / "gpu"
    gpu_dir.mkdir()
    gpu_service, gpu_request = _gpu_batch_fixture(gpu_dir, monkeypatch)
    gpu_store = LigandArtifactStore(gpu_dir)
    gpu_manifest = gpu_store.filter_run_content_path(
        gpu_request.library_id, gpu_request.filter_run_id
    )
    gpu_manifest.write_bytes(gpu_manifest.read_bytes() + b"\n")
    with pytest.raises(AnkoraDomainError) as gpu_hash_err:
        gpu_service.start_batch(gpu_request)
    assert gpu_hash_err.value.code == "AUTODOCK_GPU_INPUT_HASH_MISMATCH"
    assert gpu_hash_err.value.status_code == 422
    gpu_service.shutdown()


def test_d8_010_vina_and_autodock4_batch_preserve_execution_evidence_on_parse_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # 1. AutoDock4 batch entry parse failure preserves execution & command
    ad4_dir = tmp_path / "ad4"
    ad4_dir.mkdir()
    ad4_service, ad4_request = _ad4_batch_fixture(ad4_dir, monkeypatch)

    def write_corrupt_complete_log(**kwargs: object) -> CancellableToolExecution:
        job_dir = kwargs["job_directory"]
        assert isinstance(job_dir, Path)
        # Completion marker makes log_reports_success() True, while missing clustering raises
        (job_dir / DOCKING_LOG_FILENAME).write_text(
            "autodock4: Successful Completion on synthetic host\nNO CLUSTERS HERE\n",
            encoding="utf-8",
        )
        return CancellableToolExecution(
            command=["synthetic-autodock4.exe", "-p", "ligand.dpf"],
            exit_code=0,
            stdout="ad4-synthetic-stdout",
            stderr="ad4-synthetic-stderr",
            canceled=False,
            timed_out=False,
        )

    monkeypatch.setattr(ad4_module, "execute_autodock4_cancellable", write_corrupt_complete_log)
    ad4_record = _ad4_wait_batch(ad4_service, ad4_service.start_batch(ad4_request).batch_id)
    ad4_service.shutdown()
    assert ad4_record.failed_count == 2  # type: ignore[attr-defined]
    for entry in ad4_record.entries:  # type: ignore[attr-defined]
        assert entry.status is AutoDock4JobStatus.FAILED
        assert entry.execution is not None
        assert entry.execution.stdout == "ad4-synthetic-stdout"
        assert entry.execution.stderr == "ad4-synthetic-stderr"
        assert entry.command == ["synthetic-autodock4.exe", "-p", "ligand.dpf"]

    # 2. Vina batch entry parse failure preserves execution evidence
    vina_dir = tmp_path / "vina"
    vina_dir.mkdir()
    vina_service, single_req = _vina_single_service(vina_dir)
    vina_request = _vina_batch_request(vina_dir, vina_service, single_req, monkeypatch)
    monkeypatch.setattr(
        vina_module,
        "probe_vina",
        lambda: VinaInstallation(executable="synthetic-vina", version="1.2.7"),
    )

    def write_corrupt_vina_pdbqt(**kwargs: object) -> CancellableToolExecution:
        output_path = kwargs["output_path"]
        assert isinstance(output_path, Path)
        output_path.write_bytes(b"MODEL 1\nNOT A VALID VINA POSE\nENDMDL\n")
        return CancellableToolExecution(
            command=["synthetic-vina", "--out", str(output_path)],
            exit_code=0,
            stdout="vina-synthetic-stdout",
            stderr="vina-synthetic-stderr",
            canceled=False,
            timed_out=False,
        )

    monkeypatch.setattr(vina_module, "execute_vina", write_corrupt_vina_pdbqt)
    batch = vina_service.start_batch(vina_request)
    vina_record = _vina_wait_batch(vina_service, batch.batch_id)
    vina_service.shutdown()
    assert vina_record.failed_count == 2
    for entry in vina_record.entries:
        assert entry.status is DockingJobStatus.FAILED
        assert entry.execution is not None
        assert entry.execution.stdout == "vina-synthetic-stdout"
        assert entry.execution.stderr == "vina-synthetic-stderr"
