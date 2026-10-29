"""Cross-platform scientific subprocess execution with argument arrays and raw capture."""

import contextlib
import io
import os
import selectors
import signal
import subprocess
import threading
import time
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import IO, Any

from ankora_backend.domain.errors import AnkoraDomainError

LAUNCH_FAILED_MESSAGE = "Ankora could not launch the configured scientific tool."
TIMEOUT_MESSAGE = "The scientific tool exceeded Ankora's execution time limit."
_PROC_SCAN_INTERVAL_SECONDS = 0.25
_READ_CHUNK_BYTES = 65536
_MAX_READS_PER_DRAIN = 16


@dataclass(frozen=True, slots=True)
class ToolExecution:
    command: list[str]
    exit_code: int
    stdout: str
    stderr: str


@dataclass(frozen=True, slots=True)
class _ProcStat:
    pid: int
    ppid: int
    pgrp: int
    sid: int
    state: str
    starttime: int


def _decode_stream(chunks: list[bytes]) -> str:
    decoded = b"".join(chunks).decode("utf-8", errors="replace")
    return io.IncrementalNewlineDecoder(None, translate=True).decode(decoded, final=True)


class _PosixSelectorPipes:
    """Single-thread non-blocking stdout/stderr pipe reader using selectors."""

    def __init__(
        self,
        stdout: IO[bytes] | None,
        stderr: IO[bytes] | None,
    ) -> None:
        self._stdout = stdout
        self._stderr = stderr
        self._stdout_chunks: list[bytes] = []
        self._stderr_chunks: list[bytes] = []
        self._selector: selectors.BaseSelector | None = None
        self._open_streams: dict[int, tuple[IO[bytes], list[bytes]]] = {}
        try:
            self._selector = selectors.DefaultSelector()
            self._register(stdout, self._stdout_chunks)
            self._register(stderr, self._stderr_chunks)
        except Exception:
            self.close()
            raise

    def _register(self, stream: IO[bytes] | None, chunks: list[bytes]) -> None:
        if stream is None or self._selector is None:
            return
        fd = stream.fileno()
        os.set_blocking(fd, False)
        self._selector.register(fd, selectors.EVENT_READ, (stream, chunks))
        self._open_streams[fd] = (stream, chunks)

    def is_eof(self) -> bool:
        return not self._open_streams

    def poll_and_drain(self, timeout: float) -> None:
        if self._selector is None or not self._open_streams:
            return
        try:
            events = self._selector.select(timeout=max(0.0, timeout))
        except OSError:
            return
        for key, _ in events:
            fd = int(key.fd)
            entry = self._open_streams.get(fd)
            if entry is not None:
                self._drain_fd(fd, entry[0], entry[1])

    def _drain_fd(self, fd: int, stream: IO[bytes], chunks: list[bytes]) -> None:
        for _ in range(_MAX_READS_PER_DRAIN):
            try:
                chunk = os.read(fd, _READ_CHUNK_BYTES)
            except BlockingIOError:
                return
            except (OSError, ValueError):
                self._close_fd(fd, stream)
                return
            if not chunk:
                self._close_fd(fd, stream)
                return
            chunks.append(chunk)

    def _close_fd(self, fd: int, stream: IO[bytes]) -> None:
        self._open_streams.pop(fd, None)
        if self._selector is not None:
            with contextlib.suppress(KeyError, OSError, ValueError):
                self._selector.unregister(fd)
        with contextlib.suppress(OSError, ValueError):
            stream.close()

    def finish(self, drain_timeout: float = 0.2) -> tuple[str, str]:
        deadline = time.monotonic() + max(0.0, drain_timeout)
        while self._open_streams and time.monotonic() < deadline:
            if self._selector is None:
                break
            remaining = max(0.0, deadline - time.monotonic())
            try:
                events = self._selector.select(timeout=min(0.02, remaining))
            except OSError:
                break
            if not events:
                break
            for key, _ in events:
                fd = int(key.fd)
                entry = self._open_streams.get(fd)
                if entry is not None:
                    self._drain_fd(fd, entry[0], entry[1])
        self.close()
        return _decode_stream(self._stdout_chunks), _decode_stream(self._stderr_chunks)

    def close(self) -> None:
        for fd, (stream, _) in list(self._open_streams.items()):
            self._close_fd(fd, stream)
        if self._selector is not None:
            with contextlib.suppress(OSError, ValueError):
                self._selector.close()
            self._selector = None
        if self._stdout is not None:
            with contextlib.suppress(OSError, ValueError):
                self._stdout.close()
        if self._stderr is not None:
            with contextlib.suppress(OSError, ValueError):
                self._stderr.close()


def _read_proc_stat(pid: int) -> _ProcStat | None:
    try:
        stat_text = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8", errors="replace")
    except (FileNotFoundError, ProcessLookupError, PermissionError, OSError):
        return None
    rparen = stat_text.rfind(")")
    if rparen == -1:
        return None
    fields = stat_text[rparen + 2 :].split()
    if len(fields) < 20:
        return None
    try:
        return _ProcStat(
            pid=pid,
            state=fields[0],
            ppid=int(fields[1]),
            pgrp=int(fields[2]),
            sid=int(fields[3]),
            starttime=int(fields[19]),
        )
    except ValueError:
        return None


def _scan_proc_table() -> dict[int, _ProcStat]:
    proc_root = Path("/proc")
    if not proc_root.is_dir():
        return {}
    table: dict[int, _ProcStat] = {}
    with contextlib.suppress(OSError), os.scandir(proc_root) as entries:
        for entry in entries:
            if not entry.name.isdigit():
                continue
            pid = int(entry.name)
            stat = _read_proc_stat(pid)
            if stat is not None:
                table[pid] = stat
    return table


class _PosixProcessTracker:
    """Track current members of an owned POSIX session with (pid, starttime) identity."""

    def __init__(self, root_pid: int) -> None:
        self.root_pid = root_pid
        self._self_pid = os.getpid()
        self._self_pgrp = os.getpgrp() if hasattr(os, "getpgrp") else self._self_pid
        root_stat = _read_proc_stat(root_pid)
        self.root_starttime: int | None = (
            root_stat.starttime if root_stat is not None else None
        )
        self._known_starttimes: dict[int, int] = (
            {root_pid: root_stat.starttime} if root_stat is not None else {}
        )

    def _is_owned_stat(self, stat: _ProcStat) -> bool:
        if stat.pid <= 1 or stat.pid == self._self_pid:
            return False
        if stat.pid == self.root_pid:
            if self.root_starttime is None:
                self.root_starttime = stat.starttime
            elif stat.starttime != self.root_starttime:
                return False
        recorded_start = self._known_starttimes.get(stat.pid)
        if recorded_start is not None and stat.starttime != recorded_start:
            self._known_starttimes.pop(stat.pid, None)
            if stat.sid != self.root_pid and stat.pgrp != self.root_pid:
                return False
        return (
            stat.pid == self.root_pid
            or stat.sid == self.root_pid
            or stat.pgrp == self.root_pid
        )

    def snapshot(self) -> tuple[set[int], dict[int, int], set[int]]:
        """Return (live_descendant_pids, live_pid_starttimes, target_pgids)."""
        table = _scan_proc_table()
        if not table:
            default_pgids = (
                {self.root_pid}
                if self.root_pid > 1 and self.root_pid != self._self_pgrp
                else set()
            )
            return set(), {}, default_pgids

        owned_stats: dict[int, _ProcStat] = {
            pid: stat for pid, stat in table.items() if self._is_owned_stat(stat)
        }
        self._known_starttimes = {
            pid: stat.starttime for pid, stat in owned_stats.items()
        }
        if self.root_starttime is not None:
            self._known_starttimes.setdefault(self.root_pid, self.root_starttime)

        live_pid_starttimes: dict[int, int] = {
            pid: stat.starttime
            for pid, stat in owned_stats.items()
            if stat.state != "Z"
        }
        live_descendants: set[int] = {
            pid for pid in live_pid_starttimes if pid != self.root_pid
        }
        target_pgids: set[int] = {
            owned_stats[pid].pgrp
            for pid in live_pid_starttimes
            if owned_stats[pid].pgrp > 1 and owned_stats[pid].pgrp != self._self_pgrp
        }
        if (
            self.root_pid in live_pid_starttimes
            and self.root_pid > 1
            and self.root_pid != self._self_pgrp
        ):
            target_pgids.add(self.root_pid)
        return live_descendants, live_pid_starttimes, target_pgids


def _has_leader_exited_no_reap(process: subprocess.Popen[Any]) -> bool:
    """Check whether the session leader has exited without reaping its PID/session."""
    if process.returncode is not None:
        return True
    waitid_fn = getattr(os, "waitid", None)
    p_pid = getattr(os, "P_PID", None)
    wexited = getattr(os, "WEXITED", 0)
    wnohang = getattr(os, "WNOHANG", 0)
    wnowait = getattr(os, "WNOWAIT", 0)
    if waitid_fn is not None and p_pid is not None and wnowait != 0:
        try:
            result = waitid_fn(p_pid, process.pid, wexited | wnohang | wnowait)
            return result is not None
        except ChildProcessError:
            return True
        except OSError:
            pass
    stat = _read_proc_stat(process.pid)
    if stat is not None:
        return stat.state == "Z"
    return process.poll() is not None


def _signal_posix_targets(
    pid_starttimes: Mapping[int, int | None],
    pgids: set[int],
    sig: int,
    *,
    root_pid: int,
    self_pid: int,
    self_pgrp: int,
) -> None:
    table = _scan_proc_table()
    verified_pgids: set[int] = set()
    if not table:
        verified_pgids = {pgid for pgid in pgids if pgid > 1 and pgid != self_pgrp}
    else:
        for pgid in pgids:
            if pgid <= 1 or pgid == self_pgrp:
                continue
            if any(
                stat.state != "Z"
                and stat.pgrp == pgid
                and (stat.pid == root_pid or stat.sid == root_pid or stat.pgrp == root_pid)
                and (
                    stat.pid not in pid_starttimes
                    or pid_starttimes[stat.pid] is None
                    or stat.starttime == pid_starttimes[stat.pid]
                )
                for stat in table.values()
            ):
                verified_pgids.add(pgid)

    for pgid in sorted(verified_pgids):
        with contextlib.suppress(ProcessLookupError, PermissionError, OSError):
            os.killpg(pgid, sig)

    for pid in sorted(pid_starttimes):
        if pid <= 1 or pid == self_pid:
            continue
        expected_start = pid_starttimes[pid]
        if table:
            stat = table.get(pid)
            if stat is None or stat.state == "Z":
                continue
            if expected_start is not None and stat.starttime != expected_start:
                continue
            if stat.pid != root_pid and stat.sid != root_pid and stat.pgrp != root_pid:
                continue
        with contextlib.suppress(ProcessLookupError, PermissionError, OSError):
            os.kill(pid, sig)


def _terminate_posix_session(
    process: subprocess.Popen[Any],
    tracker: _PosixProcessTracker,
) -> None:
    """Terminate only the owned POSIX session/process groups and reap the leader."""
    self_pid = os.getpid()
    self_pgrp = os.getpgrp() if hasattr(os, "getpgrp") else self_pid

    _, live_pid_starttimes, target_pgids = tracker.snapshot()
    targets: dict[int, int | None] = dict(live_pid_starttimes)
    if not _has_leader_exited_no_reap(process):
        targets.setdefault(process.pid, tracker.root_starttime)
        if process.pid > 1 and process.pid != self_pgrp:
            target_pgids.add(process.pid)

    _signal_posix_targets(
        targets,
        target_pgids,
        signal.SIGTERM,
        root_pid=process.pid,
        self_pid=self_pid,
        self_pgrp=self_pgrp,
    )

    grace_deadline = time.monotonic() + 0.25
    while time.monotonic() < grace_deadline:
        live_descendants, live_pid_starttimes, _ = tracker.snapshot()
        if (
            _has_leader_exited_no_reap(process)
            and not live_descendants
            and not live_pid_starttimes
        ):
            break
        time.sleep(0.02)

    kill_deadline = time.monotonic() + 1.0
    while True:
        live_descendants, live_pid_starttimes, target_pgids = tracker.snapshot()
        kill_targets: dict[int, int | None] = dict(live_pid_starttimes)
        if not _has_leader_exited_no_reap(process):
            kill_targets.setdefault(process.pid, tracker.root_starttime)
            if process.pid > 1 and process.pid != self_pgrp:
                target_pgids.add(process.pid)
        if (
            _has_leader_exited_no_reap(process)
            and not live_descendants
            and not kill_targets
        ):
            break
        _signal_posix_targets(
            kill_targets,
            target_pgids,
            signal.SIGKILL,
            root_pid=process.pid,
            self_pid=self_pid,
            self_pgrp=self_pgrp,
        )
        if time.monotonic() >= kill_deadline:
            break
        time.sleep(0.02)

    try:
        process.wait(timeout=1.0)
    except subprocess.TimeoutExpired:
        with contextlib.suppress(ProcessLookupError, PermissionError, OSError):
            process.kill()
        with contextlib.suppress(subprocess.TimeoutExpired):
            process.wait(timeout=0.5)


def _spawn_tool_process(
    *,
    command: list[str],
    cwd: Path,
    stage: str,
    environment: Mapping[str, str] | None,
    start_new_session: bool,
) -> subprocess.Popen[str]:
    try:
        if start_new_session:
            return subprocess.Popen(
                command,
                cwd=cwd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                shell=False,
                env=environment,
                start_new_session=True,
            )
        return subprocess.Popen(
            command,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            shell=False,
            env=environment,
        )
    except OSError as error:
        raise AnkoraDomainError(
            code="SCIENTIFIC_TOOL_LAUNCH_FAILED",
            stage=stage,
            message=LAUNCH_FAILED_MESSAGE,
            status_code=500,
            details={"command": command, "reason": str(error)},
        ) from error


def _spawn_posix_binary_process(
    *,
    command: list[str],
    cwd: Path,
    stage: str,
    environment: Mapping[str, str] | None,
) -> subprocess.Popen[bytes]:
    try:
        return subprocess.Popen(
            command,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=False,
            env=environment,
            start_new_session=True,
        )
    except OSError as error:
        raise AnkoraDomainError(
            code="SCIENTIFIC_TOOL_LAUNCH_FAILED",
            stage=stage,
            message=LAUNCH_FAILED_MESSAGE,
            status_code=500,
            details={"command": command, "reason": str(error)},
        ) from error


def _run_posix_tool_process(
    *,
    command: list[str],
    cwd: Path,
    stage: str,
    timeout_seconds: int | float,
    environment: Mapping[str, str] | None = None,
    cancel_event: threading.Event | None = None,
) -> tuple[int, str, str, bool, bool]:
    process = _spawn_posix_binary_process(
        command=command,
        cwd=cwd,
        stage=stage,
        environment=environment,
    )
    tracker: _PosixProcessTracker | None = None
    pipes: _PosixSelectorPipes | None = None
    completed = False

    try:
        tracker = _PosixProcessTracker(process.pid)
        pipes = _PosixSelectorPipes(process.stdout, process.stderr)
        started = time.monotonic()
        effective_timeout = max(0.0, float(timeout_seconds))
        deadline = started + effective_timeout
        last_proc_scan = 0.0
        saw_pipes_eof = False
        live_descendants: set[int] = set()

        while True:
            if cancel_event is not None and cancel_event.is_set():
                _terminate_posix_session(process, tracker)
                stdout, stderr = pipes.finish(drain_timeout=0.2)
                completed = True
                exit_code = (
                    process.returncode
                    if process.returncode is not None and process.returncode != 0
                    else -1
                )
                return exit_code, stdout, stderr, True, False

            pipes.poll_and_drain(timeout=0.0)
            leader_exited = _has_leader_exited_no_reap(process)
            if leader_exited and not pipes.is_eof():
                pipes.poll_and_drain(
                    timeout=min(0.02, max(0.0, deadline - time.monotonic()))
                )

            if leader_exited:
                now_scan = time.monotonic()
                pipes_eof_now = pipes.is_eof()
                eof_just_reached = pipes_eof_now and not saw_pipes_eof
                if eof_just_reached:
                    saw_pipes_eof = True
                if (
                    last_proc_scan == 0.0
                    or eof_just_reached
                    or (now_scan - last_proc_scan) >= _PROC_SCAN_INTERVAL_SECONDS
                ):
                    live_descendants, _, _ = tracker.snapshot()
                    last_proc_scan = now_scan

                if not live_descendants and pipes.is_eof():
                    if cancel_event is not None and cancel_event.is_set():
                        _terminate_posix_session(process, tracker)
                        stdout, stderr = pipes.finish(drain_timeout=0.2)
                        completed = True
                        exit_code = (
                            process.returncode
                            if process.returncode is not None and process.returncode != 0
                            else -1
                        )
                        return exit_code, stdout, stderr, True, False
                    with contextlib.suppress(subprocess.TimeoutExpired):
                        process.wait(timeout=1.0)
                    stdout, stderr = pipes.finish(drain_timeout=0.2)
                    completed = True
                    exit_code = process.returncode if process.returncode is not None else -1
                    return exit_code, stdout, stderr, False, False

            now = time.monotonic()
            if now >= deadline:
                _terminate_posix_session(process, tracker)
                stdout, stderr = pipes.finish(drain_timeout=0.2)
                completed = True
                exit_code = (
                    process.returncode
                    if process.returncode is not None and process.returncode != 0
                    else -1
                )
                return exit_code, stdout, stderr, False, True

            remaining = max(0.0, deadline - now)
            poll_step = min(0.01 if now - started < 0.05 else 0.025, remaining)
            if not pipes.is_eof():
                pipes.poll_and_drain(timeout=poll_step)
            elif cancel_event is not None:
                cancel_event.wait(timeout=poll_step)
            else:
                time.sleep(poll_step)
    finally:
        if not completed:
            with contextlib.suppress(Exception):
                active_tracker = tracker or _PosixProcessTracker(process.pid)
                _terminate_posix_session(process, active_tracker)
        if pipes is not None:
            pipes.close()
        else:
            if process.stdout is not None:
                with contextlib.suppress(OSError, ValueError):
                    process.stdout.close()
            if process.stderr is not None:
                with contextlib.suppress(OSError, ValueError):
                    process.stderr.close()


def run_tool(
    *,
    executable: str,
    arguments: list[str],
    cwd: Path,
    stage: str,
    timeout_seconds: int = 300,
    environment: Mapping[str, str] | None = None,
) -> ToolExecution:
    command = [executable, *arguments]
    if os.name != "nt":
        exit_code, stdout, stderr, _, timed_out = _run_posix_tool_process(
            command=command,
            cwd=cwd,
            stage=stage,
            timeout_seconds=timeout_seconds,
            environment=environment,
            cancel_event=None,
        )
        if timed_out:
            raise AnkoraDomainError(
                code="SCIENTIFIC_TOOL_TIMEOUT",
                stage=stage,
                message=TIMEOUT_MESSAGE,
                status_code=504,
                details={
                    "command": command,
                    "timeout_seconds": timeout_seconds,
                    "stdout": stdout,
                    "stderr": stderr,
                },
            )
        return ToolExecution(
            command=command,
            exit_code=exit_code,
            stdout=stdout,
            stderr=stderr,
        )

    process = _spawn_tool_process(
        command=command,
        cwd=cwd,
        stage=stage,
        environment=environment,
        start_new_session=False,
    )
    try:
        stdout, stderr = process.communicate(timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        stdout, stderr = _kill_tree_and_drain(process)
        raise AnkoraDomainError(
            code="SCIENTIFIC_TOOL_TIMEOUT",
            stage=stage,
            message=TIMEOUT_MESSAGE,
            status_code=504,
            details={
                "command": command,
                "timeout_seconds": timeout_seconds,
                "stdout": stdout,
                "stderr": stderr,
            },
        ) from None

    return ToolExecution(
        command=command,
        exit_code=process.returncode,
        stdout=stdout or "",
        stderr=stderr or "",
    )


def _kill_tree_and_drain(process: subprocess.Popen[str]) -> tuple[str, str]:
    """Kill the whole owned process tree, not just the direct child.

    On Windows, `taskkill /T /F` walks the child tree by PID so wrapper commands
    such as `cmd /c prank.bat` do not orphan `java.exe`. On POSIX, processes are
    launched in an isolated session (`start_new_session=True`) and terminated via
    their owned session and process groups with bounded pipe drainage.
    """
    if os.name != "nt":
        tracker = _PosixProcessTracker(process.pid)
        _terminate_posix_session(process, tracker)
        try:
            stdout, stderr = process.communicate(timeout=2)
        except (subprocess.TimeoutExpired, OSError, ValueError):
            if process.stdout is not None:
                with contextlib.suppress(OSError, ValueError):
                    process.stdout.close()
            if process.stderr is not None:
                with contextlib.suppress(OSError, ValueError):
                    process.stderr.close()
            return "", ""
        return stdout or "", stderr or ""

    try:
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
            shell=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        # Best-effort fallback for environments where taskkill is unavailable.
        with contextlib.suppress(OSError):
            process.kill()
    try:
        stdout, stderr = process.communicate(timeout=5)
    except subprocess.TimeoutExpired:
        with contextlib.suppress(OSError):
            process.kill()
        try:
            stdout, stderr = process.communicate(timeout=2)
        except subprocess.TimeoutExpired:
            if process.stdout is not None:
                with contextlib.suppress(OSError, ValueError):
                    process.stdout.close()
            if process.stderr is not None:
                with contextlib.suppress(OSError, ValueError):
                    process.stderr.close()
            with contextlib.suppress(subprocess.TimeoutExpired):
                process.wait(timeout=1)
            return "", ""
    return stdout or "", stderr or ""
