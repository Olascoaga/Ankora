"""Service tests for AutoDock-GPU single-ligand docking (ADR-015 item 5).

The synthetic AutoDock-GPU replays a real captured `.dlg` and the real stdout
phrases, so the parsing, the verdict and the result contract exercised here are
the ones the actual binary produces. Real end-to-end execution against the GPU
is recorded separately as validation evidence.
"""

import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from test_autogrid_maps import _install_synthetic_autogrid
from test_autogrid_maps import _service as _map_service

from ankora_backend.adapters.engines.autodock_gpu import (
    DOCKING_LOG_FILENAME,
    AutoDockGpuInstallation,
)
from ankora_backend.api.app import create_app
from ankora_backend.domain.errors import AnkoraDomainError
from ankora_backend.execution.cancellable_subprocess import CancellableToolExecution
from ankora_backend.persistence.autodock_gpu_store import AutoDockGpuJobStore
from ankora_backend.persistence.autogrid_store import AutoGridMapStore
from ankora_backend.persistence.binding_site_store import BindingSiteArtifactStore
from ankora_backend.persistence.ligand_store import LigandArtifactStore
from ankora_backend.persistence.receptor_store import ReceptorArtifactStore
from ankora_backend.schemas.autodock_gpu import (
    AutoDockBackend,
    AutoDockGpuBatchParameters,
    AutoDockGpuBatchRequest,
    AutoDockGpuDockingParameters,
    AutoDockGpuDockingRequest,
    AutoDockJobStatus,
)
from ankora_backend.schemas.warnings import WarningCode
from ankora_backend.services import autodock_gpu_docking as gpu_module
from ankora_backend.services.autodock_gpu_docking import AutoDockGpuDockingService

REAL_LOG = (
    Path(__file__).parent / "fixtures" / "autodock_gpu_real_compound252.dlg"
).read_text(encoding="utf-8", errors="replace")

# The tool's own words, which are the only verdict it gives.
SUCCESS_STDOUT = "OpenCL device: synthetic\nAll jobs ran without errors."
FAILURE_STDOUT = "Error in setup of Job #1\nThe job was not successful."

DEVICE = "Synthetic OpenCL Device"


def _installation(**_: object) -> AutoDockGpuInstallation:
    return AutoDockGpuInstallation(
        executable="synthetic-autodock-gpu.exe",
        version="1.6",
        sha256="c" * 64,
        architecture="x86_64",
        build="Release",
        device_name=DEVICE,
    )


def _no_device(**_: object) -> AutoDockGpuInstallation:
    return AutoDockGpuInstallation(
        executable="synthetic-autodock-gpu.exe",
        version="1.6",
        sha256="c" * 64,
        architecture="x86_64",
        build="Release",
        device_name=None,
    )


def _execution(
    *, stdout: str = SUCCESS_STDOUT, exit_code: int = 0, canceled: bool = False,
    timed_out: bool = False,
) -> CancellableToolExecution:
    return CancellableToolExecution(
        command=["synthetic-autodock-gpu.exe", "--lfile", "ligand.pdbqt"],
        exit_code=exit_code,
        stdout=stdout,
        stderr="",
        canceled=canceled,
        timed_out=timed_out,
    )


def _replay_real_log(**kwargs: object) -> CancellableToolExecution:
    job_directory = kwargs["job_directory"]
    assert isinstance(job_directory, Path)
    (job_directory / DOCKING_LOG_FILENAME).write_text(REAL_LOG, encoding="utf-8")
    return _execution()


def _fixture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[AutoDockGpuDockingService, AutoDockGpuDockingRequest]:
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

    service = AutoDockGpuDockingService(
        job_store=AutoDockGpuJobStore(tmp_path),
        map_store=AutoGridMapStore(tmp_path),
        ligand_store=ligand_store,
        receptor_store=ReceptorArtifactStore(tmp_path),
        binding_site_store=BindingSiteArtifactStore(tmp_path),
    )
    request = AutoDockGpuDockingRequest(
        receptor_id=map_set.receptor_id,
        binding_site_id=map_set.binding_site_id,
        map_set_id=map_set.map_set_id,
        ligand_id=ligand_id,
        ligand_preparation_id=preparation_id,
        parameters=AutoDockGpuDockingParameters(runs=3),
        acknowledge_inputs_and_scoring=True,
    )
    monkeypatch.setattr(gpu_module, "probe_autodock_gpu", _installation)
    return service, request


def _wait(service: AutoDockGpuDockingService, job_id: str) -> object:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        record = service.get(job_id)
        if record.status in {
            AutoDockJobStatus.COMPLETED,
            AutoDockJobStatus.CANCELED,
            AutoDockJobStatus.FAILED,
        }:
            return record
        time.sleep(0.01)
    raise AssertionError("the synthetic AutoDock-GPU job did not terminate")


def test_a_completed_job_reports_clusters_and_names_its_backend(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service, request = _fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(
        gpu_module, "execute_autodock_gpu_cancellable", _replay_real_log
    )

    started = service.start(request)
    record = _wait(service, started.job_id)

    assert record.status is AutoDockJobStatus.COMPLETED  # type: ignore[attr-defined]
    assert record.backend is AutoDockBackend.GPU  # type: ignore[attr-defined]
    assert record.clusters and record.runs  # type: ignore[attr-defined]
    # Every ranked run got its own create-only pose file.
    for run in record.runs:  # type: ignore[attr-defined]
        path = service.pose_content_path(started.job_id, run.artifact.artifact_id)
        assert path.is_file()
    service.shutdown()


def test_every_job_states_that_it_cannot_be_reproduced(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Six repeats of one seed gave six different rankings on real hardware.

    Ankora's provenance model promises recorded inputs reproduce a result. This
    backend cannot keep that promise, so it says so on the record itself rather
    than leaving a scientist to infer determinism from the presence of a seed.
    """
    service, request = _fixture(tmp_path, monkeypatch)

    record = service.start(request)

    assert record.bitwise_reproducible is False
    assert WarningCode.DOCKING_BACKEND_NOT_REPRODUCIBLE in {
        warning.code for warning in record.warnings
    }
    service.shutdown()


def test_the_device_is_recorded_because_hardware_changes_the_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service, request = _fixture(tmp_path, monkeypatch)

    record = service.start(request)

    assert record.autodock_gpu.device_name == DEVICE
    assert record.autodock_gpu.build == "Release"
    service.shutdown()


def test_a_machine_with_no_opencl_device_is_refused_before_any_record_exists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service, request = _fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(gpu_module, "probe_autodock_gpu", _no_device)

    with pytest.raises(AnkoraDomainError) as error:
        service.start(request)

    assert error.value.code == "AUTODOCK_GPU_NO_DEVICE"
    service.shutdown()


def test_the_verdict_comes_from_stdout_not_from_the_exit_code(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AutoDock-GPU returned zero from a run whose map file did not exist."""
    service, request = _fixture(tmp_path, monkeypatch)

    def _fail_while_exiting_zero(**kwargs: object) -> CancellableToolExecution:
        job_directory = kwargs["job_directory"]
        assert isinstance(job_directory, Path)
        (job_directory / DOCKING_LOG_FILENAME).write_text(REAL_LOG, encoding="utf-8")
        return _execution(stdout=FAILURE_STDOUT, exit_code=0)

    monkeypatch.setattr(
        gpu_module, "execute_autodock_gpu_cancellable", _fail_while_exiting_zero
    )

    record = _wait(service, service.start(request).job_id)

    assert record.status is AutoDockJobStatus.FAILED  # type: ignore[attr-defined]
    assert record.failure is not None  # type: ignore[attr-defined]
    assert record.failure.code == "AUTODOCK_GPU_EXECUTION_FAILED"  # type: ignore[attr-defined]
    # The evidence keeps both, so the disagreement is visible.
    assert record.execution.exit_code == 0  # type: ignore[attr-defined]
    assert record.execution.success_reported_on_stdout is False  # type: ignore[attr-defined]
    assert not record.clusters  # type: ignore[attr-defined]
    service.shutdown()


def test_docking_requires_explicit_acknowledgement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service, request = _fixture(tmp_path, monkeypatch)

    with pytest.raises(AnkoraDomainError) as error:
        service.start(
            request.model_copy(update={"acknowledge_inputs_and_scoring": False})
        )

    assert error.value.code == "AUTODOCK_GPU_CONFIRMATION_REQUIRED"
    service.shutdown()


def test_canceling_a_running_job_publishes_no_results(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service, request = _fixture(tmp_path, monkeypatch)
    released = threading.Event()

    def _cancelable(**kwargs: object) -> CancellableToolExecution:
        event = kwargs["cancel_event"]
        assert isinstance(event, threading.Event)
        released.set()
        event.wait(timeout=5)
        return _execution(stdout="", canceled=True)

    monkeypatch.setattr(gpu_module, "execute_autodock_gpu_cancellable", _cancelable)

    started = service.start(request)
    assert released.wait(timeout=5)
    service.cancel(started.job_id)
    record = _wait(service, started.job_id)

    assert record.status is AutoDockJobStatus.CANCELED  # type: ignore[attr-defined]
    assert not record.clusters and not record.runs  # type: ignore[attr-defined]
    service.shutdown()


def test_one_device_means_one_worker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two concurrent processes on one GPU measured slower, not faster.

    The CPU engine parallelises across ligands because it has many cores and a
    single-threaded executable. This one has a single device.
    """
    service, _ = _fixture(tmp_path, monkeypatch)

    assert service._executor._max_workers == 1  # noqa: SLF001

    service.shutdown()


def test_the_api_exposes_the_gpu_engine_on_its_own_paths() -> None:
    """A GPU job is never served from the CPU engine's paths.

    Two backends of one scoring family are still two executions, and the
    interface has to be able to ask for each without ambiguity.
    """
    specification = TestClient(create_app()).get("/api/openapi.json").json()

    gpu_paths = {p for p in specification["paths"] if "autodock-gpu" in p}

    assert gpu_paths == {
        "/api/v1/docking/autodock-gpu/jobs",
        "/api/v1/docking/autodock-gpu/jobs/{job_id}",
        "/api/v1/docking/autodock-gpu/jobs/{job_id}/cancel",
        "/api/v1/docking/autodock-gpu/jobs/{job_id}/poses/{artifact_id}/content",
        "/api/v1/docking/autodock-gpu/batches",
        "/api/v1/docking/autodock-gpu/batches/latest",
        "/api/v1/docking/autodock-gpu/batches/{batch_id}",
        "/api/v1/docking/autodock-gpu/batches/{batch_id}/progress",
        "/api/v1/docking/autodock-gpu/batches/{batch_id}/cancel",
        "/api/v1/docking/autodock-gpu/batches/{batch_id}"
        "/ligands/{ligand_id}/poses/{artifact_id}/content",
    }
    # The CPU engine keeps its own, untouched, and nothing is shared.
    assert "/api/v1/docking/autodock4/jobs" in specification["paths"]
    assert "/api/v1/docking/autodock4/batches" in specification["paths"]
    assert not any("autodock4" in path for path in gpu_paths)


def test_a_pose_url_written_into_a_record_is_a_route_that_exists() -> None:
    """The service composes these URLs by hand, so they can silently rot."""
    specification = TestClient(create_app()).get("/api/openapi.json").json()

    assert (
        "/api/v1/docking/autodock-gpu/jobs/{job_id}/poses/{artifact_id}/content"
        in specification["paths"]
    )


# --- library campaigns -----------------------------------------------------


def _batch_fixture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[AutoDockGpuDockingService, AutoDockGpuBatchRequest]:
    service, single = _fixture(tmp_path, monkeypatch)
    map_set = AutoGridMapStore(tmp_path).load_record(single.map_set_id)
    library_id = map_set.request.library_id
    filter_run_id = map_set.request.filter_run_id
    assert library_id is not None and filter_run_id is not None
    return service, AutoDockGpuBatchRequest(
        receptor_id=single.receptor_id,
        binding_site_id=single.binding_site_id,
        map_set_id=single.map_set_id,
        library_id=library_id,
        filter_run_id=filter_run_id,
        parameters=AutoDockGpuBatchParameters(runs=3),
        acknowledge_inputs_and_scoring=True,
    )


def _replay_filelist(**kwargs: object) -> CancellableToolExecution:
    """Answer a file list the way the real tool does: one log per molecule."""
    work = kwargs["job_directory"]
    assert isinstance(work, Path)
    listed = (work / "campaign.lst").read_text(encoding="ascii").splitlines()
    for tag in listed[2::2]:
        (work / f"{tag}.dlg").write_text(REAL_LOG, encoding="utf-8")
    return _execution()


def _wait_batch(service: AutoDockGpuDockingService, batch_id: str) -> object:
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        record = service.get_batch(batch_id)
        if record.status in {
            AutoDockJobStatus.COMPLETED,
            AutoDockJobStatus.CANCELED,
            AutoDockJobStatus.FAILED,
        }:
            return record
        time.sleep(0.02)
    raise AssertionError("the synthetic AutoDock-GPU campaign did not terminate")


def test_a_campaign_is_one_invocation_over_a_file_list(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One process per molecule measured slower, and two at once slower still."""
    service, request = _batch_fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(
        gpu_module, "execute_autodock_gpu_cancellable", _replay_filelist
    )

    record = _wait_batch(service, service.start_batch(request).batch_id)

    assert record.status is AutoDockJobStatus.COMPLETED
    assert record.worker_count == 1
    assert "--filelist" in record.command
    # The single-ligand flags are gone: build_arguments is reused, not forked.
    assert "--lfile" not in record.command
    assert "--resnam" not in record.command
    assert record.provenance.parameters["invocations"] == 1
    service.shutdown()


def test_every_molecule_keeps_its_own_clustering(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service, request = _batch_fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(
        gpu_module, "execute_autodock_gpu_cancellable", _replay_filelist
    )

    record = _wait_batch(service, service.start_batch(request).batch_id)

    docked = [e for e in record.entries if e.status is AutoDockJobStatus.COMPLETED]
    assert docked, "no molecule was docked"
    for entry in docked:
        assert entry.clusters and entry.runs
        assert sum(c.run_count for c in entry.clusters) == len(entry.runs)
        for run in entry.runs:
            assert service.batch_pose_content_path(
                record.batch_id, entry.ligand_id, run.artifact.artifact_id
            ).is_file()
    service.shutdown()


def test_gpu_batch_rejects_pdbqt_from_another_chemical_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service, request = _batch_fixture(tmp_path, monkeypatch)
    store = LigandArtifactStore(tmp_path)
    filter_run = store.load_filter_run(request.library_id, request.filter_run_id)
    stale_id = filter_run.selected_ligand_ids[-1]
    preparation = store.load_preparation_status(request.library_id)
    store.upsert_preparation_entry(
        request.library_id,
        preparation.entries[stale_id].model_copy(
            update={"chemical_state_id": "synthetic-different-state"}
        ),
    )
    monkeypatch.setattr(
        gpu_module, "execute_autodock_gpu_cancellable", _replay_filelist
    )

    record = _wait_batch(service, service.start_batch(request).batch_id)
    service.shutdown()

    assert record.succeeded_count == 1
    stale = next(entry for entry in record.entries if entry.ligand_id == stale_id)
    assert stale.failure is not None
    assert stale.failure.code == "AUTODOCK_GPU_PREPARATION_STATE_MISMATCH"
    assert stale.chemical_state_id == next(
        evaluation.state_id
        for evaluation in filter_run.evaluations
        if evaluation.ligand_id == stale_id
    )


def test_a_second_campaign_is_refused_while_one_is_running(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The device is shared; a second process only slows the first down."""
    service, request = _batch_fixture(tmp_path, monkeypatch)
    released = threading.Event()

    def _blocking(**kwargs: object) -> CancellableToolExecution:
        event = kwargs["cancel_event"]
        assert isinstance(event, threading.Event)
        released.set()
        event.wait(timeout=5)
        return _execution(stdout="", canceled=True)

    monkeypatch.setattr(gpu_module, "execute_autodock_gpu_cancellable", _blocking)
    started = service.start_batch(request)
    assert released.wait(timeout=5)

    with pytest.raises(AnkoraDomainError) as error:
        service.start_batch(request)

    assert error.value.code == "AUTODOCK_GPU_CAMPAIGN_ALREADY_RUNNING"
    assert error.value.status_code == 409
    service.cancel_batch(started.batch_id)
    _wait_batch(service, started.batch_id)
    service.shutdown()


def test_a_canceled_campaign_keeps_what_it_already_produced(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The tool writes each log as it finishes, so partial work is real work."""
    service, request = _batch_fixture(tmp_path, monkeypatch)

    def _partial(**kwargs: object) -> CancellableToolExecution:
        work = kwargs["job_directory"]
        assert isinstance(work, Path)
        listed = (work / "campaign.lst").read_text(encoding="ascii").splitlines()
        # Only the first molecule finished before the cancellation.
        (work / f"{listed[2]}.dlg").write_text(REAL_LOG, encoding="utf-8")
        return _execution(stdout="", canceled=True)

    monkeypatch.setattr(gpu_module, "execute_autodock_gpu_cancellable", _partial)
    record = _wait_batch(service, service.start_batch(request).batch_id)

    assert record.status is AutoDockJobStatus.CANCELED
    assert record.succeeded_count == 1
    assert len([e for e in record.entries if e.clusters]) == 1, (
        "the completed molecule was discarded"
    )
    service.shutdown()


def test_a_molecule_that_cannot_be_docked_stays_in_the_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A scientist must see that a molecule was selected and why it was not run."""
    service, request = _batch_fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(
        gpu_module, "execute_autodock_gpu_cancellable", _replay_filelist
    )

    record = _wait_batch(service, service.start_batch(request).batch_id)

    assert record.selected_count == len(record.entries)
    for entry in record.entries:
        if entry.status is AutoDockJobStatus.FAILED:
            assert entry.failure is not None and entry.failure.code
    service.shutdown()


def test_a_campaign_states_the_backend_and_its_irreproducibility(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service, request = _batch_fixture(tmp_path, monkeypatch)

    record = service.start_batch(request)

    assert record.backend is AutoDockBackend.GPU
    assert record.bitwise_reproducible is False
    assert WarningCode.DOCKING_BACKEND_NOT_REPRODUCIBLE in {
        w.code for w in record.warnings
    }
    service.cancel_batch(record.batch_id)
    service.shutdown()
