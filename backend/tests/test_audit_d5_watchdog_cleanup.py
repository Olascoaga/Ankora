"""Audit D5-020 regression tests for backend parent-watchdog descendant cleanup."""

from __future__ import annotations

import psutil
import pytest

import ankora_backend.__main__ as backend_main


class _StubChild:
    def __init__(self, *, stays_alive: bool = False, fail_terminate: bool = False) -> None:
        self.terminated = False
        self.killed = False
        self.stays_alive = stays_alive
        self.fail_terminate = fail_terminate

    def terminate(self) -> None:
        self.terminated = True
        if self.fail_terminate:
            raise psutil.NoSuchProcess(pid=99999)

    def kill(self) -> None:
        self.killed = True


class _StubSelfProcess:
    def __init__(self, children: list[_StubChild]) -> None:
        self._children = children

    def children(self, *, recursive: bool = False) -> list[_StubChild]:
        assert recursive is True
        return list(self._children)


def test_terminate_descendant_processes_terminates_and_kills_survivors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gone_child = _StubChild(stays_alive=False)
    stuck_child = _StubChild(stays_alive=True)
    vanished_child = _StubChild(stays_alive=False, fail_terminate=True)

    monkeypatch.setattr(
        backend_main.psutil,
        "Process",
        lambda _pid: _StubSelfProcess([gone_child, stuck_child, vanished_child]),
    )
    monkeypatch.setattr(
        backend_main.psutil,
        "wait_procs",
        lambda procs, timeout=2.0: (
            [p for p in procs if not p.stays_alive],
            [p for p in procs if p.stays_alive],
        ),
    )

    backend_main._terminate_descendant_processes(grace_seconds=0.1)

    assert gone_child.terminated is True
    assert gone_child.killed is False
    assert stuck_child.terminated is True
    assert stuck_child.killed is True
    assert vanished_child.terminated is True


def test_exit_when_parent_stops_cleans_descendants_before_os_exit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []

    monkeypatch.setattr(backend_main, "_capture_parent_identity", lambda _pid: (None, False, None))
    monkeypatch.setattr(backend_main, "_parent_process_alive", lambda *_a, **_kw: False)
    monkeypatch.setattr(
        backend_main,
        "_terminate_descendant_processes",
        lambda: events.append("terminate_descendants"),
    )
    monkeypatch.setattr(backend_main.os, "_exit", lambda code: events.append(f"exit:{code}"))

    backend_main._exit_when_parent_stops(12345)
    assert events == ["terminate_descendants", "exit:0"]
