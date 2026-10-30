"""Synthetic GPU monitor tests; process observation is not a scoring guarantee."""

import threading
from types import SimpleNamespace

import pytest

from ankora_backend.domain.errors import AnkoraDomainError
from ankora_backend.services.gnina_gpu_observer import GninaGpuObserver, single_gpu_identity


def test_observer_matches_pid_executable_and_unique_job_directory(tmp_path, monkeypatch):
    binary = tmp_path / "gnina"
    directory = tmp_path / "job"
    directory.mkdir()
    binary.touch()
    observed = threading.Event()

    class Process:
        def __init__(self, pid):
            self.pid = pid

        def exe(self):
            return str(binary)

        def cwd(self):
            return str(directory if self.pid == 17 else tmp_path)

    psutil = SimpleNamespace(
        Process=Process, NoSuchProcess=LookupError, AccessDenied=PermissionError
    )
    monkeypatch.setattr(
        "ankora_backend.services.gnina_gpu_observer.import_module", lambda _x: psutil
    )

    def query(*_args, **_kwargs):
        observed.set()
        return SimpleNamespace(returncode=0, stdout="16, GPU-other\n17, GPU-expected\n")

    monkeypatch.setattr("ankora_backend.services.gnina_gpu_observer.subprocess.run", query)
    monitor = GninaGpuObserver(binary, directory)
    monitor.start()
    assert observed.wait(timeout=2)
    monitor.stop()
    assert monitor.observation == "PID 17; GPU UUID GPU-expected"
    assert monitor.gpu_uuid == "GPU-expected"


def test_unavailable_nvidia_smi_is_not_reported_as_gpu_use(tmp_path, monkeypatch):
    observed = threading.Event()

    def unavailable(*_args, **_kwargs):
        observed.set()
        raise FileNotFoundError("synthetic missing nvidia-smi")

    monkeypatch.setattr("ankora_backend.services.gnina_gpu_observer.subprocess.run", unavailable)
    monitor = GninaGpuObserver(tmp_path / "gnina", tmp_path)
    monitor.start()
    assert observed.wait(timeout=2)
    monitor.stop()
    assert monitor.observation is None


def test_single_gpu_identity_rejects_ambiguous_and_remapped_devices(monkeypatch):
    monkeypatch.delenv("CUDA_VISIBLE_DEVICES", raising=False)
    monkeypatch.delenv("NVIDIA_VISIBLE_DEVICES", raising=False)
    for key in list(__import__("os").environ):
        if key.startswith("CUDA_MPS_"):
            monkeypatch.delenv(key)
    gpu = "GPU-4fec5c6f-e22d-45ac-5898-743b25fe83b6"
    monkeypatch.setattr(
        "ankora_backend.services.gnina_gpu_observer.subprocess.run",
        lambda *_a, **_k: SimpleNamespace(stdout=f"{gpu}, [N/A]\n"),
    )
    assert single_gpu_identity(0) == gpu
    with pytest.raises(AnkoraDomainError):
        single_gpu_identity(1)
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "0")
    with pytest.raises(AnkoraDomainError):
        single_gpu_identity(0)
    monkeypatch.delenv("CUDA_VISIBLE_DEVICES")
    monkeypatch.setattr(
        "ankora_backend.services.gnina_gpu_observer.subprocess.run",
        lambda *_a, **_k: SimpleNamespace(stdout=f"{gpu}, Disabled\n{gpu}, Disabled\n"),
    )
    with pytest.raises(AnkoraDomainError):
        single_gpu_identity(0)
