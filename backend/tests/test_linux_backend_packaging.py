"""Unit and contract tests for Linux PyInstaller backend packaging & POSIX watchdog."""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path
from types import ModuleType

import psutil
import pytest

from ankora_backend import __main__ as backend_entry

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
LINUX_SPEC = ROOT / "backend/packaging/ankora_backend_linux.spec"


def _load_script(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


build_linux_backend = _load_script("build_linux_backend")


def test_parent_process_alive_detects_zombie_and_pid_reuse_and_reparenting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(psutil, "pid_exists", lambda _pid: True)

    class FakeProc:
        def __init__(self, status: str, created: float) -> None:
            self._status = status
            self._created = created

        def status(self) -> str:
            return self._status

        def create_time(self) -> float:
            return self._created

    monkeypatch.setattr(psutil, "Process", lambda _pid: FakeProc(psutil.STATUS_RUNNING, 1000.0))
    assert (
        backend_entry._parent_process_alive(
            4242, expected_create_time=1000.0, was_direct_parent=False
        )
        is True
    )

    # POSIX zombie parent must be treated as stopped immediately.
    monkeypatch.setattr(psutil, "Process", lambda _pid: FakeProc(psutil.STATUS_ZOMBIE, 1000.0))
    assert (
        backend_entry._parent_process_alive(
            4242, expected_create_time=1000.0, was_direct_parent=False
        )
        is False
    )

    # Recycled PID with new creation timestamp must be treated as stopped.
    monkeypatch.setattr(psutil, "Process", lambda _pid: FakeProc(psutil.STATUS_RUNNING, 1050.0))
    assert (
        backend_entry._parent_process_alive(
            4242, expected_create_time=1000.0, was_direct_parent=False
        )
        is False
    )

    # POSIX reparenting (getppid() changed from initial parent_pid) stops immediately.
    monkeypatch.setattr(psutil, "Process", lambda _pid: FakeProc(psutil.STATUS_RUNNING, 1000.0))
    monkeypatch.setattr(os, "getppid", lambda: 1, raising=False)
    assert (
        backend_entry._parent_process_alive(
            4242, expected_create_time=1000.0, was_direct_parent=True
        )
        is False
    )

    # Linux monotonic /proc/<pid>/stat starttime ticks survive wall-clock / NTP jumps!
    monkeypatch.setattr(psutil, "Process", lambda _pid: FakeProc(psutil.STATUS_RUNNING, 9999.0))
    monkeypatch.setattr(backend_entry, "_read_linux_proc_starttime_ticks", lambda _pid: 123456)
    assert (
        backend_entry._parent_process_alive(
            4242,
            expected_create_time=1000.0,
            was_direct_parent=False,
            expected_starttime_ticks=123456,
        )
        is True
    )
    monkeypatch.setattr(backend_entry, "_read_linux_proc_starttime_ticks", lambda _pid: 789012)
    assert (
        backend_entry._parent_process_alive(
            4242,
            expected_create_time=1000.0,
            was_direct_parent=False,
            expected_starttime_ticks=123456,
        )
        is False
    )


def test_resolve_backend_port_defaults_to_8765_and_validates_bounds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("ANKORA_BACKEND_PORT", raising=False)
    assert backend_entry._resolve_backend_port() == 8765

    monkeypatch.setenv("ANKORA_BACKEND_PORT", "18765")
    assert backend_entry._resolve_backend_port() == 18765

    for invalid in ("80", "70000", "not-a-port"):
        monkeypatch.setenv("ANKORA_BACKEND_PORT", invalid)
        with pytest.raises(ValueError, match="ANKORA_BACKEND_PORT"):
            backend_entry._resolve_backend_port()


def test_frozen_module_parity_verifier_catches_missing_or_extra_modules(tmp_path: Path) -> None:
    expected = build_linux_backend.expected_ankora_modules()
    assert "ankora_backend" in expected
    assert "ankora_backend.__main__" in expected
    assert "ankora_backend.adapters.engines.gnina" in expected

    toc = tmp_path / "PYZ-00.toc"
    toc.write_text(
        repr(
            (
                "/virtual/PYZ-00.pyz",
                [(name, f"/virtual/{name}.pyc", "PYMODULE-1") for name in sorted(expected)],
            )
        ),
        encoding="utf-8",
    )
    assert build_linux_backend.verify_frozen_module_parity(toc) == expected

    incomplete = sorted(expected - {"ankora_backend.adapters.engines.gnina"})
    toc.write_text(
        repr([(name, f"/virtual/{name}.pyc", "PYMODULE") for name in incomplete]),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="parity mismatch"):
        build_linux_backend.verify_frozen_module_parity(toc)


def test_linux_spec_retains_required_science_and_excludes_driver_and_tk_bloat() -> None:
    spec_text = LINUX_SPEC.read_text(encoding="utf-8")
    # Extract and evaluate only the pure filter definitions from the spec file.
    start = spec_text.index("_RETAINED_OPENMM_DATA = {")
    end = spec_text.index("analysis = Analysis(")
    namespace: dict[str, object] = {"Path": Path}
    exec(spec_text[start:end], namespace)
    retain_data = namespace["_retain_data"]
    retain_binary = namespace["_retain_binary"]
    assert callable(retain_data) and callable(retain_binary)

    assert retain_data(("openmm/app/data/amber14-all.xml", "/src/amber14-all.xml", "DATA"))
    assert not retain_data(("openmm/app/data/charmm36.xml", "/src/charmm36.xml", "DATA"))
    assert not retain_data(("prolif/data/traj.xtc", "/src/traj.xtc", "DATA"))
    assert not retain_data((" _tcl_data/init.tcl".strip(), "/src/init.tcl", "DATA"))
    assert not retain_data(("MDAnalysis/lib/formats/include/fast.h", "/src/fast.h", "DATA"))

    assert retain_binary(("openmm_plugins/libOpenMMCPU.so", "/src/libOpenMMCPU.so", "BINARY"))
    assert not retain_binary(("libOpenMMCUDA.so", "/src/libOpenMMCUDA.so", "BINARY"))
    assert not retain_binary(("libcuda.so.1", "/usr/lib/libcuda.so.1", "BINARY"))
    assert not retain_binary(("libnvidia-ml.so.1", "/usr/lib/libnvidia-ml.so.1", "BINARY"))
    assert not retain_binary(("libtcl8.6.so", "/src/libtcl8.6.so", "BINARY"))
    assert not retain_binary(("_tkinter.cpython-312-x86_64-linux-gnu.so", "/src/tk.so", "BINARY"))
