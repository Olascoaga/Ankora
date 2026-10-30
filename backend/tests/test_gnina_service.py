"""Synthetic service lifecycle with retained real GNINA output fixtures."""

import threading
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace

import pytest

from ankora_backend.adapters.engines.gnina import GninaInstallation
from ankora_backend.domain.errors import AnkoraDomainError
from ankora_backend.execution.cancellable_subprocess import CancellableToolExecution
from ankora_backend.persistence.gnina_store import GninaJobStore
from ankora_backend.persistence.work_lease_store import WorkLeaseStore
from ankora_backend.schemas.binding_sites import BindingBox
from ankora_backend.schemas.docking import DockingJobPhase, DockingJobStatus
from ankora_backend.schemas.gnina import (
    GninaDockingParameters,
    GninaDockingRequest,
    GninaJobRecord,
    GninaToolIdentity,
)
from ankora_backend.services.gnina_docking import GninaDockingService
from ankora_backend.services.resource_arbiter import ResourceArbiter
from ankora_backend.services.work_leases import WorkLeaseManager


def _setup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        "ankora_backend.services.gnina_docking.require_current_inputs", lambda *_a, **_k: None
    )
    store = GninaJobStore(tmp_path)
    arbiter = ResourceArbiter(
        cpu_threads=4,
        gpu_slots=1,
        memory_total_bytes=16 * 1024**3,
        memory_reserve_bytes=0,
        disk_path=tmp_path,
        disk_total_bytes=16 * 1024**3,
        disk_reserve_bytes=0,
        memory_available=lambda: 16 * 1024**3,
        disk_free=lambda: 16 * 1024**3,
    )
    leases = WorkLeaseManager(WorkLeaseStore(tmp_path))
    service = GninaDockingService(
        store=store,
        receptors=SimpleNamespace(),
        sites=SimpleNamespace(),
        ligands=SimpleNamespace(),
        leases=leases,
        resources=arbiter,
    )
    receptor, ligand = b"synthetic receptor", b"synthetic ligand"
    conformer = (Path(__file__).parent / "fixtures" / "gnina_input_1hsg_mk1.sdf").read_bytes()
    request = GninaDockingRequest(
        receptor_id="receptor",
        binding_site_id="site",
        ligand_id="ligand",
        ligand_preparation_id="preparation",
        parameters=GninaDockingParameters(compute="cpu"),
        acknowledge_inputs_and_scoring=True,
    )
    job = GninaJobRecord(
        job_id=store.new_job_id(),
        status=DockingJobStatus.QUEUED,
        phase=DockingJobPhase.QUEUED,
        created_at=datetime.now(UTC),
        request=request,
        tool=GninaToolIdentity(version="1.3.3", sha256="a" * 64, architecture="x86_64"),
        box=BindingBox(center_x=0, center_y=0, center_z=0, size_x=10, size_y=10, size_z=10),
        receptor_output_artifact_id="output",
        receptor_sha256=sha256(receptor).hexdigest(),
        ligand_sha256=sha256(ligand).hexdigest(),
        conformer_sha256=sha256(conformer).hexdigest(),
    )
    store.create_job(job)
    for name, content in (
        ("receptor.pdbqt", receptor),
        ("ligand.pdbqt", ligand),
        ("conformer.sdf", conformer),
    ):
        store.write_artifact(job.job_id, name, content)
    installation = GninaInstallation("/synthetic/gnina", "1.3.3", "a" * 64, "x86_64")
    return service, store, arbiter, leases, job, installation


def test_cpu_job_validates_real_pose_fixture_and_preserves_engine_rank(tmp_path, monkeypatch):
    service, store, arbiter, leases, job, installation = _setup(tmp_path, monkeypatch)
    raw = (Path(__file__).parent / "fixtures" / "gnina_real_1hsg_mk1.pdbqt").read_bytes()

    def execute(**kwargs):
        kwargs["output_path"].write_bytes(raw)
        return CancellableToolExecution(["gnina", "--no_gpu"], 0, "stdout", "stderr", False, False)

    monkeypatch.setattr("ankora_backend.services.gnina_docking.execute_gnina", execute)
    service._run(job.job_id, installation, threading.Event())
    result = store.load_job(job.job_id)
    assert result.status is DockingJobStatus.COMPLETED
    assert len(result.poses) == 2
    assert result.poses[0].cnn_score > result.poses[1].cnn_score
    assert result.poses[0].minimized_affinity_kcal_mol > result.poses[1].minimized_affinity_kcal_mol
    assert store.output_path(job.job_id, "raw_poses.pdbqt").read_bytes() == raw
    assert store.pose_content_path(job.job_id, result.poses[0].artifact.artifact_id).is_file()
    assert not arbiter.snapshot().active_allocations
    leases.shutdown()
    service.shutdown()


def test_failed_process_keeps_logs_but_publishes_no_poses(tmp_path, monkeypatch):
    service, store, arbiter, leases, job, installation = _setup(tmp_path, monkeypatch)
    monkeypatch.setattr(
        "ankora_backend.services.gnina_docking.execute_gnina",
        lambda **_kwargs: CancellableToolExecution(
            ["gnina"], 1, "output", "actual error", False, False
        ),
    )
    service._run(job.job_id, installation, threading.Event())
    result = store.load_job(job.job_id)
    assert result.status is DockingJobStatus.FAILED and result.poses == []
    assert result.execution is not None and result.execution.stderr == "actual error"
    assert store.output_path(job.job_id, "stderr.log").read_text() == "actual error"
    assert not arbiter.snapshot().active_allocations
    leases.shutdown()
    service.shutdown()


def test_prelaunch_cancellation_releases_resources(tmp_path, monkeypatch):
    service, store, arbiter, leases, job, installation = _setup(tmp_path, monkeypatch)
    event = threading.Event()
    event.set()
    service._run(job.job_id, installation, event)
    assert store.load_job(job.job_id).status is DockingJobStatus.CANCELED
    assert not arbiter.snapshot().active_allocations
    leases.shutdown()
    service.shutdown()


def test_unverified_cuda_is_rejected_before_launch(tmp_path, monkeypatch):
    service, _store, arbiter, leases, job, _installation = _setup(tmp_path, monkeypatch)
    monkeypatch.setattr("ankora_backend.services.gnina_docking._linux_host", lambda: True)
    request = job.request.model_copy(update={"parameters": GninaDockingParameters(compute="cuda")})
    with pytest.raises(AnkoraDomainError) as caught:
        service.start(request)
    assert caught.value.code == "GNINA_CUDA_VERIFICATION_UNAVAILABLE"
    assert not arbiter.snapshot().active_allocations
    leases.shutdown()
    service.shutdown()


def test_non_linux_is_rejected_before_input_access(tmp_path, monkeypatch):
    service, _store, _arbiter, leases, job, _installation = _setup(tmp_path, monkeypatch)
    monkeypatch.setattr("ankora_backend.services.gnina_docking._linux_host", lambda: False)
    with pytest.raises(AnkoraDomainError) as caught:
        service.start(job.request)
    assert caught.value.code == "GNINA_LINUX_ONLY"
    leases.shutdown()
    service.shutdown()


def test_cuda_without_process_observation_never_publishes_poses(tmp_path, monkeypatch):
    service, store, arbiter, leases, job, installation = _setup(tmp_path, monkeypatch)
    request = job.request.model_copy(update={"parameters": GninaDockingParameters(compute="cuda")})
    store.update_job(job.model_copy(update={"request": request}))
    raw = (Path(__file__).parent / "fixtures" / "gnina_real_1hsg_mk1.pdbqt").read_bytes()

    class Observer:
        observation = None
        gpu_uuid = None

        def __init__(self, *_args):
            pass

        def start(self):
            pass

        def stop(self):
            pass

    def execute(**kwargs):
        kwargs["output_path"].write_bytes(raw)
        return CancellableToolExecution(["gnina"], 0, "", "", False, False)

    monkeypatch.setattr("ankora_backend.services.gnina_docking.GninaGpuObserver", Observer)
    monkeypatch.setattr(
        "ankora_backend.services.gnina_docking.single_gpu_identity", lambda _x: "GPU-test"
    )
    monkeypatch.setattr("ankora_backend.services.gnina_docking.execute_gnina", execute)
    service._run(job.job_id, installation, threading.Event())
    result = store.load_job(job.job_id)
    assert result.status is DockingJobStatus.FAILED and result.poses == []
    assert result.failure is not None and result.failure.code == "GNINA_GPU_EXECUTION_UNVERIFIED"
    assert result.execution is not None and not result.execution.gpu_process_observed
    assert not arbiter.snapshot().active_allocations
    leases.shutdown()
    service.shutdown()


def test_cuda_mismatched_gpu_does_not_publish_poses(tmp_path, monkeypatch):
    service, store, arbiter, leases, job, installation = _setup(tmp_path, monkeypatch)
    request = job.request.model_copy(update={"parameters": GninaDockingParameters(compute="cuda")})
    store.update_job(job.model_copy(update={"request": request}))

    class Observer:
        observation = "synthetic observed process"
        gpu_uuid = "GPU-other"

        def __init__(self, *_args):
            pass

        def start(self):
            pass

        def stop(self):
            pass

    monkeypatch.setattr("ankora_backend.services.gnina_docking.GninaGpuObserver", Observer)
    monkeypatch.setattr(
        "ankora_backend.services.gnina_docking.single_gpu_identity", lambda _x: "GPU-expected"
    )
    monkeypatch.setattr(
        "ankora_backend.services.gnina_docking.execute_gnina",
        lambda **_kwargs: CancellableToolExecution(["gnina"], 0, "", "", False, False),
    )
    service._run(job.job_id, installation, threading.Event())
    result = store.load_job(job.job_id)
    assert result.status is DockingJobStatus.FAILED and result.poses == []
    assert result.failure is not None and result.failure.code == "GNINA_GPU_DEVICE_MISMATCH"
    assert not arbiter.snapshot().active_allocations
    leases.shutdown()
    service.shutdown()
