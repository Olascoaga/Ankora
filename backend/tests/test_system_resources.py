"""What the machine is doing, for the status bar.

The one rule worth pinning: a machine with no GPU reading reports the reason,
never a plausible 0%. On a status bar those two look identical and mean
opposite things — idle, or not measured at all.
"""

import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import pytest

from ankora_backend.services import system_resources


@pytest.fixture(autouse=True)
def _no_cached_reading() -> Any:
    """Each test asks the driver itself rather than the previous test's answer."""
    system_resources._gpu_cache.clear()
    yield
    system_resources._gpu_cache.clear()


def _completed(stdout: str = "", stderr: str = "", code: int = 0) -> Any:
    return subprocess.CompletedProcess(
        args=["nvidia-smi"], returncode=code, stdout=stdout, stderr=stderr,
    )


def test_the_gpu_reading_comes_from_the_driver(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        system_resources.subprocess, "run",
        lambda *_, **__: _completed("NVIDIA GeForce RTX 5050 Laptop GPU, 37, 549, 8151\n"),
    )

    usage = system_resources.collect_resource_usage()

    assert usage.gpu is not None
    assert usage.gpu.name == "NVIDIA GeForce RTX 5050 Laptop GPU"
    assert usage.gpu.utilization_percent == 37
    # nvidia-smi reports mebibytes under `nounits`.
    assert usage.gpu.memory_used_bytes == 549 * 1024 * 1024
    assert usage.gpu_unavailable_reason is None


def test_a_machine_without_the_driver_says_so_rather_than_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _absent(*_: Any, **__: Any) -> Any:
        raise FileNotFoundError("nvidia-smi")

    monkeypatch.setattr(system_resources.subprocess, "run", _absent)

    usage = system_resources.collect_resource_usage()

    assert usage.gpu is None
    assert usage.gpu_unavailable_reason is not None
    assert "NVIDIA driver" in usage.gpu_unavailable_reason


def test_a_driver_that_does_not_answer_is_not_an_idle_gpu(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _hang(*_: Any, **__: Any) -> Any:
        raise subprocess.TimeoutExpired(cmd="nvidia-smi", timeout=4.0)

    monkeypatch.setattr(system_resources.subprocess, "run", _hang)

    usage = system_resources.collect_resource_usage()

    assert usage.gpu is None
    assert usage.gpu_unavailable_reason == "The NVIDIA driver did not answer."


def test_an_unreadable_reply_is_refused_rather_than_guessed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        system_resources.subprocess, "run",
        lambda *_, **__: _completed("something, entirely, different\n"),
    )

    usage = system_resources.collect_resource_usage()

    assert usage.gpu is None
    assert usage.gpu_unavailable_reason is not None


def test_the_driver_is_asked_once_for_several_close_readings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`nvidia-smi` starts a process and costs about 47 ms, measured.

    The status bar polls, so a cached reading is what keeps that off the
    critical path of every request.
    """
    calls = 0

    def _count(*_: Any, **__: Any) -> Any:
        nonlocal calls
        calls += 1
        return _completed("GPU, 10, 100, 200\n")

    monkeypatch.setattr(system_resources.subprocess, "run", _count)

    system_resources.collect_resource_usage()
    system_resources.collect_resource_usage()
    system_resources.collect_resource_usage()

    assert calls == 1


def test_concurrent_readers_share_one_complete_driver_probe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Threaded API requests must not race separate ``nvidia-smi`` processes."""
    first_probe_started = threading.Event()
    second_call_started = threading.Event()
    second_probe_started = threading.Event()
    allow_probe_to_finish = threading.Event()
    calls = 0
    calls_lock = threading.Lock()

    def _blocking_probe(*_: Any, **__: Any) -> Any:
        nonlocal calls
        with calls_lock:
            calls += 1
            if calls == 1:
                first_probe_started.set()
            else:
                second_probe_started.set()
        assert allow_probe_to_finish.wait(timeout=2)
        return _completed("GPU, 10, 100, 200\n")

    monkeypatch.setattr(system_resources.subprocess, "run", _blocking_probe)

    def _second_read() -> Any:
        second_call_started.set()
        return system_resources.collect_resource_usage()

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(system_resources.collect_resource_usage)
        assert first_probe_started.wait(timeout=1)
        second = executor.submit(_second_read)

        assert second_call_started.wait(timeout=1)
        assert not second_probe_started.wait(timeout=0.25)
        allow_probe_to_finish.set()
        first_usage = first.result(timeout=2)
        second_usage = second.result(timeout=2)

    assert calls == 1
    assert first_usage.gpu == second_usage.gpu


def test_cpu_and_memory_are_read_from_the_real_machine() -> None:
    usage = system_resources.collect_resource_usage()

    assert usage.logical_cores >= 1
    assert usage.memory_total_bytes > 0
    assert 0 <= usage.memory_percent <= 100
    assert usage.memory_used_bytes <= usage.memory_total_bytes
