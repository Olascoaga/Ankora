"""Synthetic GPU monitor tests; process observation is not a scoring guarantee."""

import threading
from types import SimpleNamespace

from ankora_backend.services.gnina_gpu_observer import GninaGpuObserver


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
