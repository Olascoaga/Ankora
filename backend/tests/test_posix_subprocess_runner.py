"""POSIX scientific subprocess lifetime, session isolation, and cancellation contracts.

All child, grandchild, and sentinel processes in this module are explicitly
SYNTHETIC Python process-control probes (`sys.executable -c ...`). They exist
solely to verify POSIX session/process-group isolation, pipe drainage,
leader-exits-before-grandchild cleanup, timeout handling, and cancellation
without inventing scientific outputs.
"""

import contextlib
import gc
import json
import os
import signal
import socket
import subprocess
import sys
import threading
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

from ankora_backend.domain.errors import AnkoraDomainError
from ankora_backend.execution.cancellable_subprocess import run_cancellable_tool
from ankora_backend.execution.subprocess_runner import (
    _MAX_READS_PER_DRAIN,
    LAUNCH_FAILED_MESSAGE,
    _PosixProcessTracker,
    _PosixSelectorPipes,
    _ProcStat,
    _signal_posix_targets,
    run_tool,
)

pytestmark = pytest.mark.skipif(
    os.name == "nt",
    reason="POSIX session and process-group execution contracts",
)


def _pid_is_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    stat_path = Path(f"/proc/{pid}/stat")
    if stat_path.exists():
        try:
            stat_text = stat_path.read_text(encoding="utf-8", errors="replace")
            rparen = stat_text.rfind(")")
            if rparen != -1:
                fields = stat_text[rparen + 2 :].split()
                if fields and fields[0] == "Z":
                    return False
        except OSError:
            return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _wait_until_dead(pids: list[int], timeout: float = 2.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if all(not _pid_is_alive(pid) for pid in pids):
            return True
        time.sleep(0.02)
    return all(not _pid_is_alive(pid) for pid in pids)


def _cleanup_synthetic_pids(pids: list[int]) -> None:
    for pid in pids:
        if pid > 1 and pid != os.getpid():
            with contextlib.suppress(ProcessLookupError, PermissionError, OSError):
                os.kill(pid, signal.SIGKILL)


@contextlib.contextmanager
def _unrelated_sentinel_process() -> Iterator[subprocess.Popen[str]]:
    """Launch an unrelated SYNTHETIC process in its own session that must survive."""
    script = (
        "import sys, time\n"
        "sys.stdout.write('sentinel-ready\\n')\n"
        "sys.stdout.flush()\n"
        "time.sleep(120)\n"
    )
    sentinel = subprocess.Popen(
        [sys.executable, "-c", script],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        shell=False,
        start_new_session=True,
    )
    try:
        assert sentinel.stdout is not None
        ready_line = sentinel.stdout.readline().strip()
        assert ready_line == "sentinel-ready"
        assert sentinel.poll() is None
        assert _pid_is_alive(sentinel.pid)
        yield sentinel
        assert sentinel.poll() is None
        assert _pid_is_alive(sentinel.pid)
    finally:
        with contextlib.suppress(ProcessLookupError, PermissionError, OSError):
            os.killpg(sentinel.pid, signal.SIGKILL)
        with contextlib.suppress(ProcessLookupError, PermissionError, OSError):
            sentinel.kill()
        with contextlib.suppress(subprocess.TimeoutExpired):
            sentinel.wait(timeout=2)
        if sentinel.stdout is not None:
            with contextlib.suppress(OSError):
                sentinel.stdout.close()
        if sentinel.stderr is not None:
            with contextlib.suppress(OSError):
                sentinel.stderr.close()


def _read_recorded_pids(pid_file: Path) -> list[int]:
    if not pid_file.is_file():
        return []
    payload = json.loads(pid_file.read_text(encoding="utf-8"))
    return [int(item) for item in payload]


def test_posix_run_tool_starts_owned_session_and_captures_exact_streams(
    tmp_path: Path,
) -> None:
    """SYNTHETIC child+grandchild run verifying isolated session, env, cwd, and output."""
    grandchild_code = (
        "import os, sys\n"
        "sys.stdout.write(f'grandchild_sid={os.getsid(0)}\\n')\n"
        "sys.stderr.write('grandchild_stderr_ok\\n')\n"
    )
    child_code = (
        "import os, pathlib, subprocess, sys\n"
        "sid = os.getsid(0)\n"
        "pgrp = os.getpgrp()\n"
        "pid = os.getpid()\n"
        "sys.stdout.write("
        "f'leader_match={sid == pid and pgrp == pid}|cwd={pathlib.Path.cwd().name}|"
        "arg={sys.argv[2]}|env={os.environ.get(\"ANKORA_POSIX_SYNTHETIC\", \"\")}\\n'"
        ")\n"
        "sys.stdout.flush()\n"
        "sys.stderr.write('leader_stderr_ok\\n')\n"
        "sys.stderr.flush()\n"
        "subprocess.run([sys.executable, '-c', sys.argv[1]], check=True)\n"
    )
    env = {**os.environ, "ANKORA_POSIX_SYNTHETIC": "session-verified"}

    with _unrelated_sentinel_process():
        execution = run_tool(
            executable=sys.executable,
            arguments=["-c", child_code, grandchild_code, "exact-arg"],
            cwd=tmp_path,
            stage="synthetic_posix_ok",
            timeout_seconds=10,
            environment=env,
        )

    assert execution.exit_code == 0
    assert f"leader_match=True|cwd={tmp_path.name}|arg=exact-arg|env=session-verified\n" in (
        execution.stdout
    )
    assert "grandchild_sid=" in execution.stdout
    assert execution.stderr == "leader_stderr_ok\ngrandchild_stderr_ok\n"


def test_posix_nonzero_exit_preserved_across_both_runners(tmp_path: Path) -> None:
    """SYNTHETIC non-zero exit probe for both run_tool and run_cancellable_tool."""
    script = (
        "import sys\n"
        "sys.stdout.write('synthetic-nonzero-stdout\\n')\n"
        "sys.stderr.write('synthetic-nonzero-stderr\\n')\n"
        "raise SystemExit(int(sys.argv[1]))\n"
    )
    sync_exec = run_tool(
        executable=sys.executable,
        arguments=["-c", script, "23"],
        cwd=tmp_path,
        stage="synthetic_posix_nonzero",
        timeout_seconds=10,
    )
    assert sync_exec.exit_code == 23
    assert sync_exec.stdout == "synthetic-nonzero-stdout\n"
    assert sync_exec.stderr == "synthetic-nonzero-stderr\n"

    cancel_exec = run_cancellable_tool(
        executable=sys.executable,
        arguments=["-c", script, "29"],
        cwd=tmp_path,
        stage="synthetic_posix_cancel_nonzero",
        cancel_event=threading.Event(),
        timeout_seconds=10,
    )
    assert cancel_exec.exit_code == 29
    assert cancel_exec.stdout == "synthetic-nonzero-stdout\n"
    assert cancel_exec.stderr == "synthetic-nonzero-stderr\n"
    assert cancel_exec.canceled is False
    assert cancel_exec.timed_out is False


def test_posix_run_tool_timeout_kills_child_and_grandchild_holding_pipes_and_preserves_sentinel(
    tmp_path: Path,
) -> None:
    """SYNTHETIC timeout test where child+grandchild ignore SIGTERM and hold pipes open."""
    pid_file = tmp_path / "pids.json"
    grandchild_code = (
        "import os, signal, sys, time\n"
        "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
        "os.setpgid(0, 0)\n"
        "sys.stdout.write('grandchild-stdout-before-timeout\\n')\n"
        "sys.stdout.flush()\n"
        "sys.stderr.write('grandchild-stderr-before-timeout\\n')\n"
        "sys.stderr.flush()\n"
        "time.sleep(60)\n"
    )
    child_code = (
        "import json, os, pathlib, signal, subprocess, sys, time\n"
        "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
        "grandchild = subprocess.Popen([sys.executable, '-c', sys.argv[1]])\n"
        "pathlib.Path(sys.argv[2]).write_text("
        "json.dumps([os.getpid(), grandchild.pid]), encoding='utf-8'"
        ")\n"
        "sys.stdout.write('leader-stdout-before-timeout\\n')\n"
        "sys.stdout.flush()\n"
        "sys.stderr.write('leader-stderr-before-timeout\\n')\n"
        "sys.stderr.flush()\n"
        "time.sleep(60)\n"
    )

    recorded_pids: list[int] = []
    try:
        with _unrelated_sentinel_process():
            started = time.monotonic()
            with pytest.raises(AnkoraDomainError) as excinfo:
                run_tool(
                    executable=sys.executable,
                    arguments=["-c", child_code, grandchild_code, str(pid_file)],
                    cwd=tmp_path,
                    stage="synthetic_timeout",
                    timeout_seconds=1,
                )
            elapsed = time.monotonic() - started

            recorded_pids = _read_recorded_pids(pid_file)
            assert len(recorded_pids) == 2
            assert _wait_until_dead(recorded_pids, timeout=1.5)

        assert elapsed < 4.5
        assert excinfo.value.code == "SCIENTIFIC_TOOL_TIMEOUT"
        assert "leader-stdout-before-timeout\n" in excinfo.value.details["stdout"]
        assert "grandchild-stdout-before-timeout\n" in excinfo.value.details["stdout"]
        assert "leader-stderr-before-timeout\n" in excinfo.value.details["stderr"]
        assert "grandchild-stderr-before-timeout\n" in excinfo.value.details["stderr"]
    finally:
        _cleanup_synthetic_pids(recorded_pids or _read_recorded_pids(pid_file))


def test_posix_run_tool_leader_exits_before_grandchild_holding_stdout_times_out_cleanly(
    tmp_path: Path,
) -> None:
    """SYNTHETIC probe: leader exits 0 immediately while grandchild keeps stdout pipe open."""
    pid_file = tmp_path / "leader_exit_pids.json"
    grandchild_code = (
        "import signal, sys, time\n"
        "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
        "sys.stdout.write('grandchild-holding-pipe\\n')\n"
        "sys.stdout.flush()\n"
        "time.sleep(60)\n"
    )
    child_code = (
        "import json, os, pathlib, subprocess, sys\n"
        "grandchild = subprocess.Popen([sys.executable, '-c', sys.argv[1]])\n"
        "pathlib.Path(sys.argv[2]).write_text("
        "json.dumps([os.getpid(), grandchild.pid]), encoding='utf-8'"
        ")\n"
        "sys.stdout.write('leader-exited-early\\n')\n"
        "sys.stdout.flush()\n"
        "raise SystemExit(0)\n"
    )

    recorded_pids: list[int] = []
    try:
        with _unrelated_sentinel_process():
            started = time.monotonic()
            with pytest.raises(AnkoraDomainError) as excinfo:
                run_tool(
                    executable=sys.executable,
                    arguments=["-c", child_code, grandchild_code, str(pid_file)],
                    cwd=tmp_path,
                    stage="synthetic_leader_early_exit",
                    timeout_seconds=1,
                )
            elapsed = time.monotonic() - started

            recorded_pids = _read_recorded_pids(pid_file)
            assert len(recorded_pids) == 2
            assert _wait_until_dead(recorded_pids, timeout=1.5)

        assert elapsed < 4.5
        assert excinfo.value.code == "SCIENTIFIC_TOOL_TIMEOUT"
        assert "leader-exited-early\n" in excinfo.value.details["stdout"]
        assert "grandchild-holding-pipe\n" in excinfo.value.details["stdout"]
    finally:
        _cleanup_synthetic_pids(recorded_pids or _read_recorded_pids(pid_file))


def test_posix_run_cancellable_tool_pre_canceled_does_not_launch_process(
    tmp_path: Path,
) -> None:
    """SYNTHETIC pre-canceled call must not launch a child process."""
    marker = tmp_path / "must_not_be_created.txt"
    script = (
        "import pathlib, sys\n"
        "pathlib.Path(sys.argv[1]).write_text('spawned', encoding='utf-8')\n"
    )
    cancel_event = threading.Event()
    cancel_event.set()

    with _unrelated_sentinel_process():
        execution = run_cancellable_tool(
            executable=sys.executable,
            arguments=["-c", script, str(marker)],
            cwd=tmp_path,
            stage="synthetic_pre_cancel",
            cancel_event=cancel_event,
            timeout_seconds=10,
        )

    assert execution.command == [sys.executable, "-c", script, str(marker)]
    assert execution.canceled is True
    assert execution.timed_out is False
    assert execution.exit_code == -1
    assert execution.stdout == ""
    assert execution.stderr == ""
    assert not marker.exists()


def test_posix_run_cancellable_tool_cancellation_kills_session_and_grandchild_and_drains_pipes(
    tmp_path: Path,
) -> None:
    """SYNTHETIC active cancellation via Unix socket readiness signal kills whole tree."""
    pid_file = tmp_path / "cancel_pids.json"
    sock_path = tmp_path / "ready.sock"

    grandchild_code = (
        "import os, signal, socket, sys, time\n"
        "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
        "os.setpgid(0, 0)\n"
        "sys.stdout.write('grandchild-cancel-stdout\\n')\n"
        "sys.stdout.flush()\n"
        "sys.stderr.write('grandchild-cancel-stderr\\n')\n"
        "sys.stderr.flush()\n"
        "client = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)\n"
        "client.sendto(b'ready', sys.argv[1])\n"
        "client.close()\n"
        "time.sleep(60)\n"
    )
    child_code = (
        "import json, os, pathlib, signal, subprocess, sys, time\n"
        "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
        "sys.stdout.write('leader-cancel-stdout\\n')\n"
        "sys.stdout.flush()\n"
        "sys.stderr.write('leader-cancel-stderr\\n')\n"
        "sys.stderr.flush()\n"
        "grandchild = subprocess.Popen([sys.executable, '-c', sys.argv[1], sys.argv[3]])\n"
        "pathlib.Path(sys.argv[2]).write_text("
        "json.dumps([os.getpid(), grandchild.pid]), encoding='utf-8'"
        ")\n"
        "time.sleep(60)\n"
    )

    cancel_event = threading.Event()
    ready_sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    ready_sock.bind(str(sock_path))
    ready_sock.settimeout(5.0)

    def _trigger_cancel_when_ready() -> None:
        try:
            data, _ = ready_sock.recvfrom(32)
            if data == b"ready":
                cancel_event.set()
        except OSError:
            cancel_event.set()

    trigger_thread = threading.Thread(target=_trigger_cancel_when_ready, daemon=True)
    trigger_thread.start()

    recorded_pids: list[int] = []
    try:
        with _unrelated_sentinel_process():
            started = time.monotonic()
            execution = run_cancellable_tool(
                executable=sys.executable,
                arguments=[
                    "-c",
                    child_code,
                    grandchild_code,
                    str(pid_file),
                    str(sock_path),
                ],
                cwd=tmp_path,
                stage="synthetic_active_cancel",
                cancel_event=cancel_event,
                timeout_seconds=30,
            )
            elapsed = time.monotonic() - started
            trigger_thread.join(timeout=1.0)

            recorded_pids = _read_recorded_pids(pid_file)
            assert len(recorded_pids) == 2
            assert _wait_until_dead(recorded_pids, timeout=1.5)

        assert elapsed < 4.5
        assert execution.canceled is True
        assert execution.timed_out is False
        assert execution.exit_code != 0
        assert "leader-cancel-stdout\n" in execution.stdout
        assert "grandchild-cancel-stdout\n" in execution.stdout
        assert "leader-cancel-stderr\n" in execution.stderr
        assert "grandchild-cancel-stderr\n" in execution.stderr
    finally:
        with contextlib.suppress(OSError):
            ready_sock.close()
        _cleanup_synthetic_pids(recorded_pids or _read_recorded_pids(pid_file))


def test_posix_run_cancellable_tool_leader_exits_before_grandchild_handles_cancel_and_timeout(
    tmp_path: Path,
) -> None:
    """SYNTHETIC probe: leader exits 0 early while grandchild survives until cancel or timeout."""
    cancel_pid_file = tmp_path / "early_leader_cancel_pids.json"
    timeout_pid_file = tmp_path / "early_leader_timeout_pids.json"
    sock_path = tmp_path / "early_leader_ready.sock"

    # Grandchild closes inherited stdio after signaling readiness on the socket so
    # this test also verifies session-member tracking when pipes are already closed.
    grandchild_cancel_code = (
        "import os, signal, socket, sys, time\n"
        "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
        "sys.stdout.write('grandchild-before-close\\n')\n"
        "sys.stdout.flush()\n"
        "devnull = os.open(os.devnull, os.O_RDWR)\n"
        "os.dup2(devnull, 1)\n"
        "os.dup2(devnull, 2)\n"
        "os.close(devnull)\n"
        "client = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)\n"
        "client.sendto(b'ready', sys.argv[1])\n"
        "client.close()\n"
        "time.sleep(60)\n"
    )
    child_cancel_code = (
        "import json, os, pathlib, subprocess, sys\n"
        "grandchild = subprocess.Popen([sys.executable, '-c', sys.argv[1], sys.argv[3]])\n"
        "pathlib.Path(sys.argv[2]).write_text("
        "json.dumps([os.getpid(), grandchild.pid]), encoding='utf-8'"
        ")\n"
        "sys.stdout.write('leader-exited-0-before-cancel\\n')\n"
        "sys.stdout.flush()\n"
        "raise SystemExit(0)\n"
    )

    cancel_event = threading.Event()
    ready_sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    ready_sock.bind(str(sock_path))
    ready_sock.settimeout(5.0)

    def _trigger_cancel() -> None:
        try:
            data, _ = ready_sock.recvfrom(32)
            if data == b"ready":
                time.sleep(0.05)
                cancel_event.set()
        except OSError:
            cancel_event.set()

    trigger_thread = threading.Thread(target=_trigger_cancel, daemon=True)
    trigger_thread.start()

    cancel_pids: list[int] = []
    timeout_pids: list[int] = []
    try:
        with _unrelated_sentinel_process():
            started_cancel = time.monotonic()
            canceled_exec = run_cancellable_tool(
                executable=sys.executable,
                arguments=[
                    "-c",
                    child_cancel_code,
                    grandchild_cancel_code,
                    str(cancel_pid_file),
                    str(sock_path),
                ],
                cwd=tmp_path,
                stage="synthetic_early_leader_cancel",
                cancel_event=cancel_event,
                timeout_seconds=30,
            )
            cancel_elapsed = time.monotonic() - started_cancel
            trigger_thread.join(timeout=1.0)

            cancel_pids = _read_recorded_pids(cancel_pid_file)
            assert len(cancel_pids) == 2
            assert _wait_until_dead(cancel_pids, timeout=1.5)

            assert cancel_elapsed < 4.5
            assert canceled_exec.canceled is True
            assert canceled_exec.timed_out is False
            assert canceled_exec.exit_code != 0
            assert "leader-exited-0-before-cancel\n" in canceled_exec.stdout
            assert "grandchild-before-close\n" in canceled_exec.stdout

            # Now verify timeout in run_cancellable_tool when leader exits 0 early.
            grandchild_timeout_code = (
                "import signal, sys, time\n"
                "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
                "sys.stdout.write('grandchild-holding-pipe-for-timeout\\n')\n"
                "sys.stdout.flush()\n"
                "time.sleep(60)\n"
            )
            child_timeout_code = (
                "import json, os, pathlib, subprocess, sys\n"
                "grandchild = subprocess.Popen([sys.executable, '-c', sys.argv[1]])\n"
                "pathlib.Path(sys.argv[2]).write_text("
                "json.dumps([os.getpid(), grandchild.pid]), encoding='utf-8'"
                ")\n"
                "sys.stdout.write('leader-exited-0-before-timeout\\n')\n"
                "sys.stdout.flush()\n"
                "raise SystemExit(0)\n"
            )

            started_timeout = time.monotonic()
            timed_out_exec = run_cancellable_tool(
                executable=sys.executable,
                arguments=[
                    "-c",
                    child_timeout_code,
                    grandchild_timeout_code,
                    str(timeout_pid_file),
                ],
                cwd=tmp_path,
                stage="synthetic_early_leader_timeout",
                cancel_event=threading.Event(),
                timeout_seconds=1,
            )
            timeout_elapsed = time.monotonic() - started_timeout

            timeout_pids = _read_recorded_pids(timeout_pid_file)
            assert len(timeout_pids) == 2
            assert _wait_until_dead(timeout_pids, timeout=1.5)

            assert timeout_elapsed < 4.5
            assert timed_out_exec.canceled is False
            assert timed_out_exec.timed_out is True
            assert timed_out_exec.exit_code != 0
            assert "leader-exited-0-before-timeout\n" in timed_out_exec.stdout
            assert "grandchild-holding-pipe-for-timeout\n" in timed_out_exec.stdout
    finally:
        with contextlib.suppress(OSError):
            ready_sock.close()
        _cleanup_synthetic_pids(cancel_pids or _read_recorded_pids(cancel_pid_file))
        _cleanup_synthetic_pids(timeout_pids or _read_recorded_pids(timeout_pid_file))


def test_posix_launch_failure_in_cancellable_runner_raises_domain_error(
    tmp_path: Path,
) -> None:
    missing_executable = str(tmp_path / "missing-synthetic-posix-tool")
    with pytest.raises(AnkoraDomainError) as excinfo:
        run_cancellable_tool(
            executable=missing_executable,
            arguments=["--help"],
            cwd=tmp_path,
            stage="synthetic_posix_launch_fail",
            cancel_event=threading.Event(),
            timeout_seconds=5,
        )
    assert excinfo.value.code == "SCIENTIFIC_TOOL_LAUNCH_FAILED"
    assert excinfo.value.message == LAUNCH_FAILED_MESSAGE
    assert "Windows" not in excinfo.value.message


def test_posix_tracker_and_signal_revalidation_ignore_reused_child_pid_with_new_starttime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SYNTHETIC /proc-table probe: reused PID with new starttime/SID/PGRP is never targeted."""
    import ankora_backend.execution.subprocess_runner as runner_mod

    root_pid = 51000
    child_pid = 51001
    unrelated_pgid = 77777
    unrelated_sid = 88888

    scan_1: dict[int, _ProcStat] = {
        root_pid: _ProcStat(
            pid=root_pid,
            ppid=100,
            pgrp=root_pid,
            sid=root_pid,
            state="S",
            starttime=1000,
        ),
        child_pid: _ProcStat(
            pid=child_pid,
            ppid=root_pid,
            pgrp=root_pid,
            sid=root_pid,
            state="S",
            starttime=1050,
        ),
    }
    # In scan 2, child_pid 51001 was reaped and reused by an unrelated process with
    # a newer starttime (9500 != 1050) and unrelated session/process group.
    scan_2: dict[int, _ProcStat] = {
        root_pid: _ProcStat(
            pid=root_pid,
            ppid=100,
            pgrp=root_pid,
            sid=root_pid,
            state="S",
            starttime=1000,
        ),
        child_pid: _ProcStat(
            pid=child_pid,
            ppid=1,
            pgrp=unrelated_pgid,
            sid=unrelated_sid,
            state="S",
            starttime=9500,
        ),
    }

    current_table = scan_1
    monkeypatch.setattr(runner_mod, "_scan_proc_table", lambda: current_table)
    monkeypatch.setattr(runner_mod, "_read_proc_stat", lambda pid: current_table.get(pid))

    tracker = _PosixProcessTracker(root_pid)
    descendants_1, live_map_1, pgids_1 = tracker.snapshot()
    assert descendants_1 == {child_pid}
    assert live_map_1 == {root_pid: 1000, child_pid: 1050}
    assert pgids_1 == {root_pid}

    current_table = scan_2
    descendants_2, live_map_2, pgids_2 = tracker.snapshot()
    assert descendants_2 == set()
    assert live_map_2 == {root_pid: 1000}
    assert pgids_2 == {root_pid}
    assert child_pid not in live_map_2
    assert unrelated_pgid not in pgids_2

    # Even if stale targets from scan_1 are passed into _signal_posix_targets when
    # scan_2 is active, revalidation must prevent signaling child_pid or unrelated_pgid.
    signaled_pids: list[tuple[int, int]] = []
    signaled_pgids: list[tuple[int, int]] = []
    monkeypatch.setattr(
        runner_mod.os,
        "kill",
        lambda pid, sig: signaled_pids.append((pid, sig)),
    )
    monkeypatch.setattr(
        runner_mod.os,
        "killpg",
        lambda pgid, sig: signaled_pgids.append((pgid, sig)),
    )

    _signal_posix_targets(
        {root_pid: 1000, child_pid: 1050},
        {root_pid, unrelated_pgid},
        signal.SIGTERM,
        root_pid=root_pid,
        self_pid=999999,
        self_pgrp=999999,
    )
    assert signaled_pids == [(root_pid, signal.SIGTERM)]
    assert signaled_pgids == [(root_pid, signal.SIGTERM)]


def test_posix_proc_scan_rate_is_throttled_during_active_and_pipe_closed_runs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SYNTHETIC probe verifying /proc is not scanned on every poll tick while leader runs."""
    import ankora_backend.execution.subprocess_runner as runner_mod

    real_scan = runner_mod._scan_proc_table
    scan_count = 0

    def _counting_scan() -> dict[int, _ProcStat]:
        nonlocal scan_count
        scan_count += 1
        return real_scan()

    monkeypatch.setattr(runner_mod, "_scan_proc_table", _counting_scan)

    # Leader closes stdout/stderr early and runs for ~0.35s before exiting 0.
    script = (
        "import os, sys, time\n"
        "sys.stdout.write('before-close\\n')\n"
        "sys.stdout.flush()\n"
        "devnull = os.open(os.devnull, os.O_RDWR)\n"
        "os.dup2(devnull, 1)\n"
        "os.dup2(devnull, 2)\n"
        "os.close(devnull)\n"
        "time.sleep(0.35)\n"
    )
    execution = run_tool(
        executable=sys.executable,
        arguments=["-c", script],
        cwd=tmp_path,
        stage="synthetic_proc_throttle",
        timeout_seconds=10,
    )
    assert execution.exit_code == 0
    assert execution.stdout == "before-close\n"
    # 0 scans while leader is active + 1 scan after leader exit to confirm no live descendants.
    assert scan_count <= 2


def test_posix_unexpected_exception_in_runner_cleans_up_owned_session_and_pipes(
    tmp_path: Path,
) -> None:
    """SYNTHETIC fault-injection probe: unexpected loop error kills session and closes fds."""
    pid_file = tmp_path / "fault_pids.json"
    sock_path = tmp_path / "fault_ready.sock"

    grandchild_code = (
        "import signal, socket, sys, time\n"
        "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
        "sys.stdout.write('grandchild-fault-probe\\n')\n"
        "sys.stdout.flush()\n"
        "client = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)\n"
        "client.sendto(b'ready', sys.argv[1])\n"
        "client.close()\n"
        "time.sleep(60)\n"
    )
    child_code = (
        "import json, os, pathlib, signal, subprocess, sys, time\n"
        "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
        "grandchild = subprocess.Popen([sys.executable, '-c', sys.argv[1], sys.argv[3]])\n"
        "pathlib.Path(sys.argv[2]).write_text("
        "json.dumps([os.getpid(), grandchild.pid]), encoding='utf-8'"
        ")\n"
        "time.sleep(60)\n"
    )

    class _FaultingCancelEvent(threading.Event):
        def __init__(self) -> None:
            super().__init__()
            self.arm_fault = False
            self._checks = 0

        def is_set(self) -> bool:
            self._checks += 1
            if self.arm_fault and self._checks > 1:
                raise RuntimeError("synthetic injected loop failure")
            return super().is_set()

    fault_event = _FaultingCancelEvent()
    ready_sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    ready_sock.bind(str(sock_path))
    ready_sock.settimeout(5.0)

    def _arm_fault_when_ready() -> None:
        with contextlib.suppress(OSError):
            data, _ = ready_sock.recvfrom(32)
            if data == b"ready":
                fault_event.arm_fault = True

    arm_thread = threading.Thread(target=_arm_fault_when_ready, daemon=True)
    arm_thread.start()

    recorded_pids: list[int] = []
    try:
        with _unrelated_sentinel_process():
            with pytest.raises(RuntimeError, match="synthetic injected loop failure"):
                run_cancellable_tool(
                    executable=sys.executable,
                    arguments=[
                        "-c",
                        child_code,
                        grandchild_code,
                        str(pid_file),
                        str(sock_path),
                    ],
                    cwd=tmp_path,
                    stage="synthetic_fault_cleanup",
                    cancel_event=fault_event,
                    timeout_seconds=30,
                )
            arm_thread.join(timeout=1.0)
            recorded_pids = _read_recorded_pids(pid_file)
            assert len(recorded_pids) == 2
            assert _wait_until_dead(recorded_pids, timeout=1.5)
    finally:
        with contextlib.suppress(OSError):
            ready_sock.close()
        _cleanup_synthetic_pids(recorded_pids or _read_recorded_pids(pid_file))


def test_posix_repeated_canceled_runs_preserve_partial_streams_without_leaking_threads_or_fds(
    tmp_path: Path,
) -> None:
    """SYNTHETIC repeated canceled runs verifying partial output and zero thread/fd leaks."""
    sock_path = tmp_path / "repeat_ready.sock"
    ready_sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    ready_sock.bind(str(sock_path))
    ready_sock.settimeout(5.0)

    grandchild_code = (
        "import signal, socket, sys, time\n"
        "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
        "sys.stdout.write(f'gc-out-{sys.argv[2]}\\n')\n"
        "sys.stdout.flush()\n"
        "sys.stderr.write(f'gc-err-{sys.argv[2]}\\n')\n"
        "sys.stderr.flush()\n"
        "client = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)\n"
        "client.sendto(b'ready', sys.argv[1])\n"
        "client.close()\n"
        "time.sleep(60)\n"
    )
    child_code = (
        "import json, os, pathlib, signal, subprocess, sys, time\n"
        "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
        "sys.stdout.write(f'child-out-{sys.argv[4]}\\n')\n"
        "sys.stdout.flush()\n"
        "sys.stderr.write(f'child-err-{sys.argv[4]}\\n')\n"
        "sys.stderr.flush()\n"
        "grandchild = subprocess.Popen("
        "[sys.executable, '-c', sys.argv[1], sys.argv[3], sys.argv[4]]"
        ")\n"
        "pathlib.Path(sys.argv[2]).write_text("
        "json.dumps([os.getpid(), grandchild.pid]), encoding='utf-8'"
        ")\n"
        "time.sleep(60)\n"
    )

    gc.collect()
    baseline_threads = {thread.ident for thread in threading.enumerate()}
    fd_dir = Path("/proc/self/fd")
    baseline_fds = len(os.listdir(fd_dir)) if fd_dir.is_dir() else 0

    all_pids: list[int] = []
    try:
        for index in range(4):
            pid_file = tmp_path / f"repeat_pids_{index}.json"
            cancel_event = threading.Event()

            def _cancel_on_ready(ev: threading.Event = cancel_event) -> None:
                try:
                    data, _ = ready_sock.recvfrom(32)
                    if data == b"ready":
                        ev.set()
                except OSError:
                    ev.set()

            helper = threading.Thread(target=_cancel_on_ready, daemon=True)
            helper.start()
            execution = run_cancellable_tool(
                executable=sys.executable,
                arguments=[
                    "-c",
                    child_code,
                    grandchild_code,
                    str(pid_file),
                    str(sock_path),
                    str(index),
                ],
                cwd=tmp_path,
                stage="synthetic_repeat_cancel",
                cancel_event=cancel_event,
                timeout_seconds=20,
            )
            helper.join(timeout=1.0)
            pids = _read_recorded_pids(pid_file)
            all_pids.extend(pids)
            assert len(pids) == 2
            assert _wait_until_dead(pids, timeout=1.5)
            assert execution.canceled is True
            assert execution.timed_out is False
            assert f"child-out-{index}\n" in execution.stdout
            assert f"gc-out-{index}\n" in execution.stdout
            assert f"child-err-{index}\n" in execution.stderr
            assert f"gc-err-{index}\n" in execution.stderr

        gc.collect()
        current_threads = {thread.ident for thread in threading.enumerate()}
        assert current_threads <= baseline_threads
        if fd_dir.is_dir():
            current_fds = len(os.listdir(fd_dir))
            assert current_fds <= baseline_fds
    finally:
        with contextlib.suppress(OSError):
            ready_sock.close()
        _cleanup_synthetic_pids(all_pids)


def test_posix_selector_pipes_drain_fd_is_bounded_per_quantum_and_preserves_remaining_data(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SYNTHETIC fake continuously-readable FD test verifying bounded drain quantum."""
    import ankora_backend.execution.subprocess_runner as runner_mod

    read_fd, write_fd = os.pipe()
    stream = os.fdopen(read_fd, "rb", buffering=0)
    os.close(write_fd)

    total_chunks = _MAX_READS_PER_DRAIN + 5
    remaining_chunks = [f"chunk-{idx:02d}\n".encode() for idx in range(total_chunks)]
    read_calls = 0

    def _synthetic_os_read(fd: int, n: int) -> bytes:
        nonlocal read_calls
        _ = (fd, n)
        read_calls += 1
        if remaining_chunks:
            return remaining_chunks.pop(0)
        return b""

    pipes = _PosixSelectorPipes(stream, None)
    try:
        monkeypatch.setattr(runner_mod.os, "read", _synthetic_os_read)
        entry = pipes._open_streams[read_fd]
        pipes._drain_fd(read_fd, entry[0], entry[1])

        # First quantum must stop at _MAX_READS_PER_DRAIN and leave the fd registered.
        assert read_calls == _MAX_READS_PER_DRAIN
        assert not pipes.is_eof()
        assert len(remaining_chunks) == 5

        # Second quantum drains the remaining 5 chunks plus 1 EOF read and closes fd.
        pipes._drain_fd(read_fd, entry[0], entry[1])
        assert read_calls == total_chunks + 1
        assert pipes.is_eof()

        stdout, stderr = pipes.finish(drain_timeout=0.05)
        expected = "".join(f"chunk-{idx:02d}\n" for idx in range(total_chunks))
        assert stdout == expected
        assert stderr == ""
    finally:
        pipes.close()


def test_posix_large_stdout_and_stderr_preserved_across_multiple_drain_quanta(
    tmp_path: Path,
) -> None:
    """SYNTHETIC finite large-output probe spanning multiple drain quanta on stdout/stderr."""
    script = (
        "import sys\n"
        "out_block = ('OUT-' + ('A' * 1019) + '\\n') * 1500\n"
        "err_block = ('ERR-' + ('B' * 1019) + '\\n') * 1200\n"
        "sys.stdout.write(out_block)\n"
        "sys.stdout.flush()\n"
        "sys.stderr.write(err_block)\n"
        "sys.stderr.flush()\n"
    )
    execution = run_tool(
        executable=sys.executable,
        arguments=["-c", script],
        cwd=tmp_path,
        stage="synthetic_large_streams",
        timeout_seconds=15,
    )
    expected_out = ("OUT-" + ("A" * 1019) + "\n") * 1500
    expected_err = ("ERR-" + ("B" * 1019) + "\n") * 1200
    assert execution.exit_code == 0
    assert len(execution.stdout) == len(expected_out)
    assert len(execution.stderr) == len(expected_err)
    assert execution.stdout == expected_out
    assert execution.stderr == expected_err


def test_posix_pipe_registration_failure_after_spawn_kills_owned_session_and_closes_fds(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SYNTHETIC constructor/register fault after Popen terminates child and closes fds."""
    import ankora_backend.execution.subprocess_runner as runner_mod

    pid_file = tmp_path / "init_fail_pids.json"
    child_code = (
        "import json, os, pathlib, signal, time\n"
        "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
        "pathlib.Path(os.environ['ANKORA_SYNTHETIC_PID_FILE']).write_text("
        "json.dumps([os.getpid()]), encoding='utf-8'"
        ")\n"
        "time.sleep(60)\n"
    )

    real_register = runner_mod._PosixSelectorPipes._register
    register_calls = 0

    def _failing_second_register(
        self: _PosixSelectorPipes,
        stream: object,
        chunks: list[bytes],
    ) -> None:
        nonlocal register_calls
        register_calls += 1
        if register_calls == 2:
            # Wait briefly so the spawned child records its PID before init fails.
            deadline = time.monotonic() + 2.0
            while not pid_file.is_file() and time.monotonic() < deadline:
                time.sleep(0.01)
            raise OSError("synthetic selector registration failure")
        real_register(self, stream, chunks)  # type: ignore[arg-type]

    monkeypatch.setattr(
        runner_mod._PosixSelectorPipes,
        "_register",
        _failing_second_register,
    )

    fd_dir = Path("/proc/self/fd")
    baseline_fds = len(os.listdir(fd_dir)) if fd_dir.is_dir() else 0
    recorded_pids: list[int] = []
    env = {**os.environ, "ANKORA_SYNTHETIC_PID_FILE": str(pid_file)}

    try:
        with _unrelated_sentinel_process():
            with pytest.raises(OSError, match="synthetic selector registration failure"):
                run_tool(
                    executable=sys.executable,
                    arguments=["-c", child_code],
                    cwd=tmp_path,
                    stage="synthetic_init_failure",
                    timeout_seconds=10,
                    environment=env,
                )
            recorded_pids = _read_recorded_pids(pid_file)
            assert len(recorded_pids) == 1
            assert _wait_until_dead(recorded_pids, timeout=1.5)

        if fd_dir.is_dir():
            assert len(os.listdir(fd_dir)) <= baseline_fds
    finally:
        _cleanup_synthetic_pids(recorded_pids or _read_recorded_pids(pid_file))
