"""The global scientific-work scheduler grants whole, fair reservations."""

import threading
from pathlib import Path

import pytest

from ankora_backend.domain.errors import AnkoraDomainError
from ankora_backend.services.resource_arbiter import (
    ResourceArbiter,
    ResourceClaim,
    ResourceRequestCanceled,
)


def _arbiter(tmp_path: Path, *, cpu: int = 4, gpu: int = 1) -> ResourceArbiter:
    return ResourceArbiter(
        cpu_threads=cpu,
        gpu_slots=gpu,
        memory_total_bytes=10_000,
        memory_reserve_bytes=1_000,
        disk_path=tmp_path,
        disk_total_bytes=20_000,
        disk_reserve_bytes=2_000,
        memory_available=lambda: 10_000,
        disk_free=lambda: 20_000,
    )


def _claim(owner: str, *, cpu: int = 1, gpu: int = 0) -> ResourceClaim:
    return ResourceClaim(
        workload="test",
        owner_id=owner,
        cpu_threads=cpu,
        memory_bytes=100,
        disk_bytes=100,
        gpu_slots=gpu,
    )


def test_claims_are_atomic_and_wait_for_global_cpu_capacity(tmp_path: Path) -> None:
    arbiter = _arbiter(tmp_path, cpu=2)
    first = arbiter.acquire(_claim("first", cpu=2))
    admitted = threading.Event()
    released = threading.Event()

    def wait_for_capacity() -> None:
        lease = arbiter.acquire(_claim("second"))
        admitted.set()
        released.wait(timeout=2)
        lease.release()

    thread = threading.Thread(target=wait_for_capacity)
    thread.start()
    assert not admitted.wait(timeout=0.1)
    assert arbiter.snapshot().queued_requests == 1

    first.release()
    assert admitted.wait(timeout=1)
    snapshot = arbiter.snapshot()
    assert snapshot.cpu_threads_allocated == 1
    assert snapshot.active_allocations[0].owner_id == "second"
    released.set()
    thread.join(timeout=1)


def test_a_waiting_claim_can_be_canceled_without_leaking_capacity(
    tmp_path: Path,
) -> None:
    arbiter = _arbiter(tmp_path, gpu=1)
    first = arbiter.acquire(_claim("gpu-one", gpu=1))
    canceled = threading.Event()
    outcome: list[str] = []

    def wait_for_gpu() -> None:
        try:
            arbiter.acquire(_claim("gpu-two", gpu=1), cancel_event=canceled)
        except ResourceRequestCanceled:
            outcome.append("canceled")

    thread = threading.Thread(target=wait_for_gpu)
    thread.start()
    assert _wait_until(lambda: arbiter.snapshot().queued_requests == 1)
    canceled.set()
    thread.join(timeout=1)

    assert outcome == ["canceled"]
    assert arbiter.snapshot().queued_requests == 0
    assert arbiter.snapshot().gpu_slots_allocated == 1
    first.release()
    assert arbiter.snapshot().gpu_slots_allocated == 0


def test_fifo_prevents_a_smaller_later_job_from_cutting_the_queue(
    tmp_path: Path,
) -> None:
    arbiter = _arbiter(tmp_path, cpu=3)
    blocker = arbiter.acquire(_claim("blocker", cpu=2))
    order: list[str] = []
    finish = threading.Event()

    def acquire(owner: str, cpu: int) -> None:
        lease = arbiter.acquire(_claim(owner, cpu=cpu))
        order.append(owner)
        finish.wait(timeout=2)
        lease.release()

    large = threading.Thread(target=acquire, args=("large", 2))
    small = threading.Thread(target=acquire, args=("small", 1))
    large.start()
    assert _wait_until(lambda: arbiter.snapshot().queued_requests == 1)
    small.start()
    assert _wait_until(lambda: arbiter.snapshot().queued_requests == 2)
    assert order == []

    blocker.release()
    assert _wait_until(lambda: bool(order))
    assert order[0] == "large"
    finish.set()
    large.join(timeout=1)
    small.join(timeout=1)
    assert order == ["large", "small"]


def test_an_impossible_claim_fails_instead_of_waiting_forever(tmp_path: Path) -> None:
    arbiter = _arbiter(tmp_path, cpu=2)

    with pytest.raises(AnkoraDomainError) as captured:
        arbiter.acquire(_claim("too-large", cpu=3))

    assert captured.value.code == "RESOURCE_REQUEST_EXCEEDS_CAPACITY"
    assert captured.value.details["resources"] == {"cpu_threads": {"requested": 3, "capacity": 2}}
    assert arbiter.snapshot().queued_requests == 0


def test_memory_and_disk_are_part_of_the_same_admission_decision(
    tmp_path: Path,
) -> None:
    arbiter = _arbiter(tmp_path)
    first = arbiter.acquire(
        ResourceClaim("test", "first", 1, memory_bytes=8_500, disk_bytes=17_500)
    )
    snapshot = arbiter.snapshot()
    assert snapshot.memory_bytes_reserved == 8_500
    assert snapshot.disk_bytes_reserved == 17_500
    first.release()
    assert arbiter.snapshot().memory_bytes_reserved == 0
    assert arbiter.snapshot().disk_bytes_reserved == 0


def _wait_until(predicate: object) -> bool:
    import time

    deadline = time.monotonic() + 1
    while time.monotonic() < deadline:
        if callable(predicate) and predicate():
            return True
        time.sleep(0.01)
    return False
