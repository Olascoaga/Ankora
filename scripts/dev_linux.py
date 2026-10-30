#!/usr/bin/env python3
"""Run Ankora's Linux development backend and web frontend as one owned session.

Tauri's ``beforeDevCommand`` invokes ``python3 ../../scripts/dev_linux.py`` from
``apps/desktop``. The launcher starts ``python -m ankora_backend`` and then
``npm run dev`` from the repository root, each in its own session. The API is
ready only when 127.0.0.1:8765 answers the health contract *and* every listening
socket on that port belongs to the started backend; the frontend is ready when
127.0.0.1:1420 is listening from the started npm session.

Listeners the launcher did not start are reported, never stopped or reused.
Raw child output goes to the terminal and to ``logs/dev-linux/<session>/``
(Git-ignored). On SIGINT/SIGTERM/SIGHUP, frontend exit, or startup failure every
process in the owned sessions is terminated, then killed after a grace period.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import math
import os
import re
import shutil
import signal
import socket
import struct
import subprocess
import sys
import threading
import time
import urllib.request
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
LOOPBACK = "127.0.0.1"
API_PORT = 8765
WEB_PORT = 1420
HEALTH_PATH = "/api/v1/health"
SYSTEM_PATH = "/api/v1/system"
DEFAULT_STARTUP_TIMEOUT = 90.0
STOP_GRACE_SECONDS = 5.0
CONDA_DISTRIBUTIONS = ("miniforge3", "mambaforge", "miniconda3", "anaconda3")
_WINDOWS_DRIVE = re.compile(r"^/mnt/[a-zA-Z](/|$)")
_WINDOWS_SUFFIXES = {".exe", ".bat", ".cmd", ".ps1"}
_TCP_LISTEN = "0A"
# A local listener can only intercept 127.0.0.1 traffic from these addresses.
_LOOPBACK_REACHABLE = {
    "/proc/net/tcp": ((socket.AF_INET, "127.0.0.1"), (socket.AF_INET, "0.0.0.0")),
    "/proc/net/tcp6": ((socket.AF_INET6, "::"), (socket.AF_INET6, "::ffff:127.0.0.1")),
}

Ownership = Literal["absent", "owned", "foreign"]


class LauncherError(RuntimeError):
    """A startup problem the developer must resolve; nothing unowned was touched."""


class StopRequested(Exception):
    def __init__(self, signum: int) -> None:
        super().__init__(signal.Signals(signum).name)
        self.signum = signum


class StopRequest:
    """Signal-safe request to end the session; handlers only record the signal."""

    def __init__(self) -> None:
        self.signum: int | None = None
        self._event = threading.Event()

    def request(self, signum: int) -> None:
        if self.signum is None:
            self.signum = signum
        self._event.set()

    def wait(self, seconds: float) -> None:
        self._event.wait(seconds)

    def raise_if_requested(self) -> None:
        if self.signum is not None:
            raise StopRequested(self.signum)


def install_stop_handlers(stop: StopRequest) -> None:
    for signum in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(signum, lambda received, _frame: stop.request(received))


def _say(message: str) -> None:
    with contextlib.suppress(OSError, ValueError):
        print(f"[ankora-dev] {message}", file=sys.stderr, flush=True)


# --- Interpreter and tool selection -------------------------------------------------


@dataclass(frozen=True)
class PythonSelection:
    executable: Path
    source: str
    environment: str
    conda_prefix: Path | None


def is_windows_executable(path: Path) -> bool:
    """True for Windows binaries or anything reached through a WSL drive mount."""
    if path.suffix.lower() in _WINDOWS_SUFFIXES:
        return True
    for candidate in (path.absolute(), path.resolve()):
        if _WINDOWS_DRIVE.match(candidate.as_posix()):
            return True
    try:
        with path.open("rb") as handle:
            return handle.read(2) == b"MZ"
    except OSError:
        return False


def interpreter_problem(path: Path) -> str | None:
    if is_windows_executable(path):
        return "it is a Windows executable or path; Linux development must not reuse it"
    if not path.is_file():
        return "it does not exist"
    if not os.access(path, os.X_OK):
        return "it is not executable"
    return None


def _selection(executable: Path, source: str) -> PythonSelection:
    prefix = executable.parent.parent
    if (prefix / "conda-meta").is_dir():
        return PythonSelection(executable, source, prefix.name, prefix)
    environment = prefix.name if (prefix / "pyvenv.cfg").is_file() else "system"
    return PythonSelection(executable, source, environment, None)


def _named_conda_candidates(environ: Mapping[str, str], home: Path) -> list[Path]:
    roots: list[Path] = []
    if environ.get("CONDA_EXE"):
        roots.append(Path(environ["CONDA_EXE"]).parent.parent)
    if environ.get("MAMBA_ROOT_PREFIX"):
        roots.append(Path(environ["MAMBA_ROOT_PREFIX"]))
    roots.extend(home / distribution for distribution in CONDA_DISTRIBUTIONS)
    roots.append(home / ".conda")
    candidates = [root / "envs" / "ankora-dev" / "bin" / "python" for root in roots]
    return list(dict.fromkeys(candidates))


def select_python(
    environ: Mapping[str, str],
    root: Path = REPOSITORY_ROOT,
    home: Path | None = None,
) -> PythonSelection:
    """Explicit path, active non-base Conda, project ``.venv``, then named ``ankora-dev``."""
    configured = environ.get("ANKORA_PYTHON_PATH", "").strip()
    if configured:
        executable = Path(configured).expanduser()
        problem = interpreter_problem(executable)
        if problem is not None:
            raise LauncherError(
                f"ANKORA_PYTHON_PATH={configured!r} cannot be used because {problem}. "
                "Fix or unset it; an explicit interpreter is never silently replaced."
            )
        return _selection(executable, "ANKORA_PYTHON_PATH")

    checked: list[str] = []
    conda_prefix = environ.get("CONDA_PREFIX", "").strip()
    if conda_prefix:
        prefix = Path(conda_prefix)
        candidate = prefix / "bin" / "python"
        if environ.get("CONDA_DEFAULT_ENV") == "base" or (prefix / "condabin").is_dir():
            checked.append(f"{candidate} (active Conda base, ignored)")
        elif (problem := interpreter_problem(candidate)) is None:
            return _selection(candidate, "active-conda")
        else:
            checked.append(f"{candidate} ({problem})")

    venv = root / ".venv" / "bin" / "python"
    if (problem := interpreter_problem(venv)) is None:
        return _selection(venv, "project-venv")
    checked.append(f"{venv} ({problem})")

    for candidate in _named_conda_candidates(environ, home or Path.home()):
        if (problem := interpreter_problem(candidate)) is None:
            return _selection(candidate, "named-conda")
        checked.append(f"{candidate} ({problem})")

    raise LauncherError(
        "No Linux Python environment for Ankora was found. Set ANKORA_PYTHON_PATH, "
        "activate a non-base Conda environment, create the project .venv, or create "
        "the 'ankora-dev' Conda environment. Checked:\n  " + "\n  ".join(checked)
    )


def find_npm(environ: Mapping[str, str]) -> str:
    found = shutil.which("npm", path=environ.get("PATH"))
    if found is None:
        raise LauncherError("npm was not found on PATH. Install Linux Node.js 22+ and npm.")
    if is_windows_executable(Path(found)):
        raise LauncherError(
            f"PATH resolves npm to {found}, a Windows installation reached through WSL. "
            "Install Linux Node.js 22+ and put it before Windows paths."
        )
    return found


def backend_environment(
    base: Mapping[str, str], selection: PythonSelection, root: Path = REPOSITORY_ROOT
) -> dict[str, str]:
    """Inherited environment plus the selected interpreter's tools and this checkout's code."""
    environment = dict(base)
    bin_directory = str(selection.executable.parent)
    inherited_path = environment.get("PATH")
    environment["PATH"] = (
        f"{bin_directory}{os.pathsep}{inherited_path}" if inherited_path else bin_directory
    )
    source = str(root / "backend" / "src")
    inherited_pythonpath = environment.get("PYTHONPATH")
    environment["PYTHONPATH"] = (
        f"{source}{os.pathsep}{inherited_pythonpath}" if inherited_pythonpath else source
    )
    if selection.conda_prefix is not None:
        environment["CONDA_PREFIX"] = str(selection.conda_prefix)
        environment["CONDA_DEFAULT_ENV"] = selection.conda_prefix.name
    elif selection.environment != "system":
        environment["VIRTUAL_ENV"] = str(selection.executable.parent.parent)
    environment.setdefault("ANKORA_PYTHON_ENVIRONMENT", selection.environment)
    return environment


def backend_command(selection: PythonSelection, parent_pid: int) -> list[str]:
    # --parent-pid is the backend's existing guard: it exits if the launcher vanishes.
    return [str(selection.executable), "-m", "ankora_backend", "--parent-pid", str(parent_pid)]


def frontend_command(npm: str) -> list[str]:
    return [npm, "run", "dev"]


# --- Port and process identity through /proc ------------------------------------------


def _proc_address(family: int, address: str) -> str:
    packed = socket.inet_pton(family, address)
    words = struct.unpack(f"={len(packed) // 4}I", packed)
    return "".join(f"{word:08X}" for word in words)


def listening_inodes(port: int) -> set[int]:
    """Socket inodes listening where they could accept connections to 127.0.0.1:port."""
    inodes: set[int] = set()
    for table, addresses in _LOOPBACK_REACHABLE.items():
        accepted = {_proc_address(family, address) for family, address in addresses}
        try:
            rows = Path(table).read_text(encoding="ascii").splitlines()[1:]
        except OSError:
            continue
        for row in rows:
            fields = row.split()
            if len(fields) < 10 or fields[3] != _TCP_LISTEN:
                continue
            address, port_hex = fields[1].rsplit(":", 1)
            if int(port_hex, 16) == port and address in accepted:
                inodes.add(int(fields[9]))
    return inodes


def session_members(session_id: int) -> dict[int, int]:
    """Live (non-zombie) processes of one session, mapped to their process groups."""
    members: dict[int, int] = {}
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            stat = (entry / "stat").read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        state, _ppid, group, session = stat[stat.rindex(")") + 2 :].split()[:4]
        if state != "Z" and int(session) == session_id:
            members[int(entry.name)] = int(group)
    return members


def socket_inodes(pid: int) -> set[int]:
    inodes: set[int] = set()
    descriptors = Path("/proc") / str(pid) / "fd"
    try:
        entries = list(descriptors.iterdir())
    except OSError:
        return inodes
    for entry in entries:
        try:
            target = os.readlink(entry)
        except OSError:
            continue
        if target.startswith("socket:["):
            inodes.add(int(target[8:-1]))
    return inodes


def listener_owners(port: int) -> dict[int, str]:
    """Visible processes listening on the port, for diagnostics only."""
    wanted = listening_inodes(port)
    owners: dict[int, str] = {}
    if not wanted:
        return owners
    for entry in Path("/proc").iterdir():
        if entry.name.isdigit() and socket_inodes(int(entry.name)) & wanted:
            try:
                owners[int(entry.name)] = (entry / "comm").read_text().strip()
            except OSError:
                owners[int(entry.name)] = "?"
    return owners


def listener_ownership(port: int, session_id: int) -> Ownership:
    listeners = listening_inodes(port)
    if not listeners:
        return "absent"
    owned: set[int] = set()
    for pid in session_members(session_id):
        owned |= socket_inodes(pid)
    return "owned" if listeners <= owned else "foreign"


def _local_opener() -> urllib.request.OpenerDirector:
    # Never route loopback probes through an inherited HTTP proxy.
    return urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _get_json(port: int, path: str) -> object | None:
    try:
        with _local_opener().open(f"http://{LOOPBACK}:{port}{path}", timeout=1.0) as response:
            if response.status != 200:
                return None
            payload: object = json.loads(response.read(65536))
            return payload
    except (OSError, ValueError):
        return None


def health_ok(port: int) -> bool:
    payload = _get_json(port, HEALTH_PATH)
    return (
        isinstance(payload, dict)
        and payload.get("status") == "ok"
        and isinstance(payload.get("backend_version"), str)
    )


def port_problem(port: int) -> str | None:
    try:
        with socket.create_connection((LOOPBACK, port), timeout=0.5):
            return "a process is accepting connections on it"
    except OSError:
        pass
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        # Same option uvicorn and Vite use, so lingering TIME_WAIT is not a conflict.
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            probe.bind((LOOPBACK, port))
        except OSError as error:
            return f"it cannot be bound ({error.strerror})"
    return None


def ensure_ports_free(ports: Mapping[str, int]) -> None:
    problems: list[str] = []
    for label, port in ports.items():
        problem = port_problem(port)
        if problem is None:
            continue
        detail = f"{label} port {LOOPBACK}:{port} is unavailable: {problem}"
        owners = listener_owners(port)
        if owners:
            detail += " (listener: " + ", ".join(f"{n} pid {p}" for p, n in owners.items()) + ")"
        system = _get_json(port, SYSTEM_PATH)
        if isinstance(system, dict) and "python_environment" in system:
            detail += (
                f"; it answers as an Ankora backend (Python environment "
                f"{system['python_environment']!r}) and will not be reused"
            )
        problems.append(detail)
    if problems:
        raise LauncherError(
            "\n".join(problems)
            + "\nStop that process yourself. This launcher never stops or reuses "
            "listeners it did not start."
        )


# --- Owned child processes --------------------------------------------------------------


class OwnedProcess:
    """A child started in its own session; only that session is ever signalled."""

    def __init__(
        self,
        name: str,
        command: Sequence[str],
        *,
        cwd: Path,
        env: Mapping[str, str],
        log_directory: Path,
    ) -> None:
        self.name = name
        self.command = list(command)
        self.log_path = log_directory / f"{name}.log"
        self._log = self.log_path.open("xb")
        try:
            self.process = subprocess.Popen(
                self.command,
                cwd=cwd,
                env=dict(env),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        except OSError as error:
            self._log.close()
            raise LauncherError(
                f"Could not start the {name} ({self.command[0]}): {error}"
            ) from error
        self._pump = threading.Thread(target=self._copy_output, name=f"{name}-output", daemon=True)
        self._pump.start()

    @property
    def pid(self) -> int:
        return self.process.pid

    def _copy_output(self) -> None:
        assert self.process.stdout is not None
        descriptor = self.process.stdout.fileno()
        while chunk := os.read(descriptor, 65536):
            self._log.write(chunk)
            self._log.flush()
            with contextlib.suppress(OSError, ValueError):
                sys.stdout.buffer.write(chunk)
                sys.stdout.buffer.flush()

    def exit_code(self) -> int | None:
        """Exit status without reaping, so the session id cannot be recycled before cleanup."""
        if self.process.returncode is not None:
            return self.process.returncode
        try:
            result = os.waitid(os.P_PID, self.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT)
        except ChildProcessError:
            return self.process.poll()
        if result is None:
            return None
        return result.si_status if result.si_code == os.CLD_EXITED else -result.si_status

    def _signal_session(self, signum: int) -> None:
        groups = set(session_members(self.pid).values())
        if self.process.returncode is None:
            groups.add(self.pid)
        for group in groups:
            with contextlib.suppress(ProcessLookupError, PermissionError):
                os.killpg(group, signum)

    def _wait_for_empty_session(self, seconds: float) -> bool:
        deadline = time.monotonic() + seconds
        while session_members(self.pid):
            if time.monotonic() >= deadline:
                return False
            time.sleep(0.05)
        return True

    def stop(self, grace: float = STOP_GRACE_SECONDS) -> int:
        if session_members(self.pid):
            self._signal_session(signal.SIGTERM)
            if not self._wait_for_empty_session(grace):
                _say(f"{self.name} did not stop within {grace:g} s; killing its session")
                self._signal_session(signal.SIGKILL)
                self._wait_for_empty_session(grace)
        code = self.process.wait()
        self._pump.join(timeout=2.0)
        self._log.close()
        return code

    def tail(self, lines: int = 40) -> str:
        try:
            text = self.log_path.read_bytes().decode("utf-8", errors="replace")
        except OSError:
            return ""
        return "\n".join(text.splitlines()[-lines:])


def _exit_status(code: int) -> int:
    return 128 - code if code < 0 else code


def _startup_failure(process: OwnedProcess, summary: str) -> LauncherError:
    output = process.tail()
    shown = f"\nLast {process.name} output:\n{output}" if output else ""
    return LauncherError(f"{summary}{shown}\nRaw output: {process.log_path}")


def wait_until_ready(
    process: OwnedProcess,
    port: int,
    *,
    timeout: float,
    stop: StopRequest,
    require_health: bool,
) -> None:
    deadline = time.monotonic() + timeout
    while True:
        stop.raise_if_requested()
        code = process.exit_code()
        if code is not None:
            raise _startup_failure(
                process,
                f"The {process.name} exited with status {code} before becoming ready "
                f"on {LOOPBACK}:{port}.",
            )
        ownership = listener_ownership(port, process.pid)
        if ownership == "foreign":
            raise _startup_failure(
                process,
                f"Another process is listening on {LOOPBACK}:{port}; the started "
                f"{process.name} cannot be identified as the server there.",
            )
        if ownership == "owned" and (not require_health or health_ok(port)):
            return
        if time.monotonic() >= deadline:
            expectation = "a healthy, owned listener" if require_health else "an owned listener"
            raise _startup_failure(
                process,
                f"The {process.name} did not provide {expectation} on {LOOPBACK}:{port} "
                f"within {timeout:g} s.",
            )
        stop.wait(0.25)


def _is_bound(seconds: float) -> bool:
    # NaN and infinity never reach a deadline, so they would make waits unbounded.
    return math.isfinite(seconds) and seconds > 0


def startup_seconds(text: str) -> float:
    """Parse ``--startup-timeout``; rejected values fail before anything is spawned."""
    try:
        seconds = float(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{text!r} is not a number of seconds") from None
    if not _is_bound(seconds):
        raise argparse.ArgumentTypeError(
            f"{text!r} is not a finite number of seconds greater than zero"
        )
    return seconds


def run_session(
    backend: Sequence[str],
    frontend: Sequence[str],
    *,
    cwd: Path,
    backend_env: Mapping[str, str],
    frontend_env: Mapping[str, str],
    log_directory: Path,
    stop: StopRequest,
    api_port: int = API_PORT,
    web_port: int = WEB_PORT,
    startup_timeout: float = DEFAULT_STARTUP_TIMEOUT,
    stop_grace: float = STOP_GRACE_SECONDS,
) -> int:
    """Run backend then frontend; return the frontend's status or 128+signal."""
    for name, seconds in (("startup_timeout", startup_timeout), ("stop_grace", stop_grace)):
        if not _is_bound(seconds):
            raise LauncherError(
                f"{name} must be finite seconds greater than zero, not {seconds!r}."
            )
    started: list[OwnedProcess] = []
    try:
        stop.raise_if_requested()
        ensure_ports_free({"Ankora API": api_port, "Web frontend": web_port})
        api = OwnedProcess(
            "backend", backend, cwd=cwd, env=backend_env, log_directory=log_directory
        )
        started.append(api)
        wait_until_ready(api, api_port, timeout=startup_timeout, stop=stop, require_health=True)
        _say(f"Backend pid {api.pid} is healthy on {LOOPBACK}:{api_port}")

        web = OwnedProcess(
            "frontend", frontend, cwd=cwd, env=frontend_env, log_directory=log_directory
        )
        started.append(web)
        wait_until_ready(web, web_port, timeout=startup_timeout, stop=stop, require_health=False)
        _say(f"Frontend pid {web.pid} is listening on {LOOPBACK}:{web_port}; session ready")

        while True:
            stop.raise_if_requested()
            code = web.exit_code()
            if code is not None:
                _say(f"Frontend exited with status {code}; stopping the backend")
                return _exit_status(code)
            code = api.exit_code()
            if code is not None:
                raise _startup_failure(api, f"The backend exited unexpectedly with status {code}.")
            stop.wait(0.2)
    except StopRequested as request:
        _say(f"Received {request}; stopping owned processes")
        return 128 + request.signum
    finally:
        for owned in reversed(started):
            owned.stop(stop_grace)


def _write_record(path: Path, record: Mapping[str, object]) -> None:
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run Ankora's Linux development backend and web frontend."
    )
    parser.add_argument("--startup-timeout", type=startup_seconds, default=DEFAULT_STARTUP_TIMEOUT)
    arguments = parser.parse_args(argv)
    if not sys.platform.startswith("linux"):
        _say("dev_linux.py runs only on Linux; use scripts/dev.ps1 on Windows.")
        return 2

    stop = StopRequest()
    install_stop_handlers(stop)
    record: dict[str, object] = {"started_at": datetime.now(UTC).isoformat()}
    record_path: Path | None = None
    try:
        selection = select_python(os.environ)
        npm = find_npm(os.environ)
        log_directory = (
            REPOSITORY_ROOT
            / "logs"
            / "dev-linux"
            / f"{datetime.now(UTC):%Y%m%dT%H%M%SZ}-{os.getpid()}"
        )
        log_directory.mkdir(parents=True)
        record_path = log_directory / "session.json"
        backend = backend_command(selection, os.getpid())
        frontend = frontend_command(npm)
        record.update(
            python={
                "executable": str(selection.executable),
                "source": selection.source,
                "environment": selection.environment,
            },
            backend_command=backend,
            frontend_command=frontend,
            cwd=str(REPOSITORY_ROOT),
            ports={"api": API_PORT, "web": WEB_PORT},
        )
        _write_record(record_path, record)
        _say(
            f"Python {selection.executable} ({selection.source}, "
            f"environment {selection.environment!r}); raw output in {log_directory}"
        )
        status = run_session(
            backend,
            frontend,
            cwd=REPOSITORY_ROOT,
            backend_env=backend_environment(os.environ, selection),
            frontend_env=os.environ,
            log_directory=log_directory,
            stop=stop,
            startup_timeout=arguments.startup_timeout,
        )
    except LauncherError as error:
        _say(str(error))
        record["error"] = str(error)
        status = 1
    record.update(ended_at=datetime.now(UTC).isoformat(), exit_status=status)
    if record_path is not None:
        _write_record(record_path, record)
    return status


if __name__ == "__main__":
    raise SystemExit(main())
