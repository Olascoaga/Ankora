"""Contracts for the Linux development launcher, including real process lifecycle.

Every child here is a tiny SYNTHETIC stand-in (stdlib HTTP/socket servers that
sleep); none runs Ankora, chemistry, or docking. Lifecycle checks use real
processes, real sockets and real signals because session ownership, listener
identity and cleanup are exactly what is under test.
"""

from __future__ import annotations

import importlib.util
import json
import math
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path
from types import ModuleType

import pytest

pytestmark = pytest.mark.skipif(
    not sys.platform.startswith("linux"), reason="Linux development launcher"
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPOSITORY_ROOT / "scripts" / "dev_linux.py"

# SYNTHETIC API stand-in: answers only the health route; spawns one helper child.
SYNTHETIC_API = """
import http.server, json, os, pathlib, subprocess, sys
port, record, status = int(sys.argv[1]), pathlib.Path(sys.argv[2]), sys.argv[3]
helper = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(600)"])
class Health(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        body = json.dumps({"status": status, "backend_version": "synthetic"}).encode()
        self.send_response(200 if self.path == "/api/v1/health" else 404)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)
    def log_message(self, *args):
        pass
server = http.server.HTTPServer(("127.0.0.1", port), Health)
record.write_text(json.dumps({"leader": os.getpid(), "helper": helper.pid}))
server.serve_forever()
"""

# SYNTHETIC frontend stand-in: listens, optionally exits after a delay.
SYNTHETIC_WEB = """
import json, os, pathlib, socket, subprocess, sys, time
port, record = int(sys.argv[1]), pathlib.Path(sys.argv[2])
lifetime, code = float(sys.argv[3]), int(sys.argv[4])
helper = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(600)"])
listener = socket.create_server(("127.0.0.1", port))
record.write_text(json.dumps({"leader": os.getpid(), "helper": helper.pid}))
time.sleep(lifetime)
sys.exit(code)
"""

# SYNTHETIC failing backend: reports a recognisable error and exits.
SYNTHETIC_CRASH = """
import sys
print("synthetic import failure: no module named imaginary", file=sys.stderr)
sys.exit(7)
"""

# SYNTHETIC hung backend: never listens; leaves a helper that must be cleaned up.
SYNTHETIC_HANG = """
import json, os, pathlib, subprocess, sys, time
helper = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(600)"])
pathlib.Path(sys.argv[1]).write_text(json.dumps({"leader": os.getpid(), "helper": helper.pid}))
time.sleep(600)
"""

DRIVER = """
import importlib.util, json, os, sys
from pathlib import Path
spec = importlib.util.spec_from_file_location("dev_linux_driver", sys.argv[1])
launcher = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = launcher
spec.loader.exec_module(launcher)
config = json.loads(sys.argv[2])
stop = launcher.StopRequest()
launcher.install_stop_handlers(stop)
sys.exit(launcher.run_session(
    config["backend"], config["frontend"], cwd=Path(config["cwd"]),
    backend_env=dict(os.environ), frontend_env=dict(os.environ),
    log_directory=Path(config["logs"]), stop=stop, api_port=config["api_port"],
    web_port=config["web_port"], startup_timeout=20.0, stop_grace=2.0,
))
"""


@pytest.fixture(scope="module")
def launcher() -> ModuleType:
    spec = importlib.util.spec_from_file_location("dev_linux", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def _alive(pid: int) -> bool:
    try:
        stat = Path(f"/proc/{pid}/stat").read_text()
    except OSError:
        return False
    return stat[stat.rindex(")") + 2] != "Z"


def _assert_all_stopped(*records: Path) -> None:
    pids = [pid for record in records for pid in json.loads(record.read_text()).values()]
    deadline = time.monotonic() + 5.0
    while any(_alive(pid) for pid in pids) and time.monotonic() < deadline:
        time.sleep(0.05)
    assert not [pid for pid in pids if _alive(pid)], "owned processes survived cleanup"


def _python(code: str, *arguments: object) -> list[str]:
    return [sys.executable, "-c", code, *(str(argument) for argument in arguments)]


def _executable(path: Path, content: bytes = b"#!/bin/sh\n# synthetic, never run\n") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    path.chmod(0o755)
    return path


# --- Interpreter selection (synthetic, never executed) -----------------------------


def test_explicit_python_wins_over_every_other_candidate(launcher, tmp_path: Path) -> None:
    explicit = _executable(tmp_path / "custom" / "bin" / "python")
    _executable(tmp_path / "repo" / ".venv" / "bin" / "python")
    selection = launcher.select_python(
        {"ANKORA_PYTHON_PATH": str(explicit)}, root=tmp_path / "repo", home=tmp_path
    )
    assert selection.executable == explicit
    assert selection.source == "ANKORA_PYTHON_PATH"


@pytest.mark.parametrize(
    ("name", "content", "mode", "reason"),
    [
        ("missing", None, None, "does not exist"),
        ("plain", b"#!/bin/sh\n", 0o644, "not executable"),
        ("python.exe", b"MZ\x90\x00", 0o755, "Windows"),
        ("python", b"MZ\x90\x00", 0o755, "Windows"),
    ],
)
def test_invalid_explicit_python_fails_without_fallback(
    launcher, tmp_path: Path, name: str, content: bytes | None, mode: int | None, reason: str
) -> None:
    _executable(tmp_path / "repo" / ".venv" / "bin" / "python")
    explicit = tmp_path / "explicit" / name
    if content is not None and mode is not None:
        explicit.parent.mkdir(parents=True)
        explicit.write_bytes(content)
        explicit.chmod(mode)
    with pytest.raises(launcher.LauncherError, match=reason):
        launcher.select_python(
            {"ANKORA_PYTHON_PATH": str(explicit)}, root=tmp_path / "repo", home=tmp_path
        )


def test_windows_drive_paths_are_never_reused(launcher) -> None:
    assert launcher.is_windows_executable(Path("/mnt/c/Program Files/nodejs/npm"))
    assert launcher.interpreter_problem(Path("/mnt/d/envs/ankora-dev/bin/python"))


def test_active_non_base_conda_precedes_project_venv(launcher, tmp_path: Path) -> None:
    prefix = tmp_path / "conda" / "envs" / "work"
    (prefix / "conda-meta").mkdir(parents=True)
    conda_python = _executable(prefix / "bin" / "python")
    _executable(tmp_path / "repo" / ".venv" / "bin" / "python")
    selection = launcher.select_python(
        {"CONDA_PREFIX": str(prefix), "CONDA_DEFAULT_ENV": "work"},
        root=tmp_path / "repo",
        home=tmp_path,
    )
    assert (selection.executable, selection.source) == (conda_python, "active-conda")
    assert selection.conda_prefix == prefix


def test_conda_base_is_ignored_in_favour_of_project_venv(launcher, tmp_path: Path) -> None:
    base = tmp_path / "miniforge3"
    (base / "condabin").mkdir(parents=True)
    _executable(base / "bin" / "python")
    venv_python = _executable(tmp_path / "repo" / ".venv" / "bin" / "python")
    (tmp_path / "repo" / ".venv" / "pyvenv.cfg").write_text("home = /usr/bin\n")
    selection = launcher.select_python(
        {"CONDA_PREFIX": str(base), "CONDA_DEFAULT_ENV": "base"},
        root=tmp_path / "repo",
        home=tmp_path,
    )
    assert (selection.executable, selection.source) == (venv_python, "project-venv")
    assert selection.environment == ".venv"


def test_named_ankora_dev_is_the_last_candidate(launcher, tmp_path: Path) -> None:
    root = tmp_path / "miniforge3"
    named = _executable(root / "envs" / "ankora-dev" / "bin" / "python")
    (root / "envs" / "ankora-dev" / "conda-meta").mkdir()
    selection = launcher.select_python(
        {"CONDA_EXE": str(root / "bin" / "conda")}, root=tmp_path / "repo", home=tmp_path / "h"
    )
    assert (selection.executable, selection.source) == (named, "named-conda")
    assert selection.environment == "ankora-dev"


def test_missing_environment_lists_what_was_checked(launcher, tmp_path: Path) -> None:
    with pytest.raises(launcher.LauncherError, match=r"(?s)No Linux Python.*\.venv/bin/python"):
        launcher.select_python({}, root=tmp_path / "repo", home=tmp_path)


def test_backend_environment_keeps_tool_discovery_and_uses_this_checkout(
    launcher, tmp_path: Path
) -> None:
    prefix = tmp_path / "envs" / "ankora-dev"
    (prefix / "conda-meta").mkdir(parents=True)
    selection = launcher.PythonSelection(
        prefix / "bin" / "python", "named-conda", "ankora-dev", prefix
    )
    environment = launcher.backend_environment(
        {"PATH": "/usr/bin", "ANKORA_VINA_PATH": "/opt/vina", "CONDA_DEFAULT_ENV": "base"},
        selection,
        root=tmp_path / "repo",
    )
    assert environment["PATH"] == f"{prefix / 'bin'}:/usr/bin"
    assert environment["PYTHONPATH"] == str(tmp_path / "repo" / "backend" / "src")
    assert environment["ANKORA_VINA_PATH"] == "/opt/vina"
    assert environment["CONDA_PREFIX"] == str(prefix)
    assert environment["CONDA_DEFAULT_ENV"] == "ankora-dev"
    assert environment["ANKORA_PYTHON_ENVIRONMENT"] == "ankora-dev"


def test_commands_are_argument_arrays_with_the_existing_parent_guard(launcher) -> None:
    selection = launcher.PythonSelection(Path("/env/bin/python"), "x", "env", None)
    assert launcher.backend_command(selection, 4321) == [
        "/env/bin/python",
        "-m",
        "ankora_backend",
        "--parent-pid",
        "4321",
    ]
    assert launcher.frontend_command("/usr/bin/npm") == ["/usr/bin/npm", "run", "dev"]


def _forbidden(*_arguments: object, **_keywords: object) -> None:
    raise AssertionError("nothing may be selected or spawned")


@pytest.mark.parametrize(
    "value", ["nan", "NaN", "inf", "-inf", "infinity", "1e400", "0", "-0", "-1", "abc", ""]
)
def test_cli_rejects_unbounded_startup_timeout_before_spawning(
    launcher, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], value: str
) -> None:
    monkeypatch.setattr(launcher, "select_python", _forbidden)
    monkeypatch.setattr(launcher.subprocess, "Popen", _forbidden)
    with pytest.raises(SystemExit) as excinfo:
        launcher.main([f"--startup-timeout={value}"])
    assert excinfo.value.code == 2
    error = capsys.readouterr().err
    assert "--startup-timeout" in error
    assert "seconds" in error


@pytest.mark.parametrize(("value", "expected"), [("2.5", 2.5), ("90", 90.0), ("1e-3", 0.001)])
def test_startup_timeout_parser_accepts_finite_positive_seconds(
    launcher, value: str, expected: float
) -> None:
    assert launcher.startup_seconds(value) == expected


@pytest.mark.parametrize("field", ["startup_timeout", "stop_grace"])
@pytest.mark.parametrize("seconds", [math.nan, math.inf, 0.0, -1.0])
def test_session_refuses_unbounded_waits_before_spawning(
    launcher, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, field: str, seconds: float
) -> None:
    monkeypatch.setattr(launcher.subprocess, "Popen", _forbidden)
    with pytest.raises(launcher.LauncherError, match=field):
        launcher.run_session(
            ["synthetic-never-run-backend"],
            ["synthetic-never-run-frontend"],
            cwd=tmp_path,
            backend_env={},
            frontend_env={},
            log_directory=tmp_path,
            stop=launcher.StopRequest(),
            api_port=_free_port(),
            web_port=_free_port(),
            **{field: seconds},
        )
    assert list(tmp_path.iterdir()) == []


# --- Real ports, identity and lifecycle (synthetic children) ------------------------


def test_occupied_port_is_rejected_and_left_untouched(launcher, tmp_path: Path) -> None:
    api_port, web_port = _free_port(), _free_port()
    with socket.create_server(("127.0.0.1", api_port)) as foreign:
        with pytest.raises(launcher.LauncherError, match=rf"(?s){api_port}.*never stops"):
            launcher.run_session(
                _python(SYNTHETIC_API, api_port, tmp_path / "api.json", "ok"),
                _python(SYNTHETIC_WEB, web_port, tmp_path / "web.json", 60, 0),
                cwd=tmp_path,
                backend_env=os.environ,
                frontend_env=os.environ,
                log_directory=tmp_path,
                stop=launcher.StopRequest(),
                api_port=api_port,
                web_port=web_port,
            )
        assert not (tmp_path / "backend.log").exists()
        with socket.create_connection(("127.0.0.1", api_port), timeout=1):
            pass
        assert foreign.fileno() != -1


def test_listener_identity_distinguishes_owned_from_foreign(launcher) -> None:
    port = _free_port()
    sleeper = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)"], start_new_session=True
    )
    try:
        assert launcher.listener_ownership(port, sleeper.pid) == "absent"
        with socket.create_server(("127.0.0.1", port)):
            assert launcher.listener_ownership(port, sleeper.pid) == "foreign"
            assert os.getpid() in launcher.listener_owners(port)
    finally:
        sleeper.kill()
        sleeper.wait()


def test_frontend_exit_stops_the_backend_session_and_returns_its_status(
    launcher, tmp_path: Path
) -> None:
    api_port, web_port = _free_port(), _free_port()
    api_record, web_record = tmp_path / "api.json", tmp_path / "web.json"
    status = launcher.run_session(
        _python(SYNTHETIC_API, api_port, api_record, "ok"),
        _python(SYNTHETIC_WEB, web_port, web_record, 1.0, 3),
        cwd=tmp_path,
        backend_env=os.environ,
        frontend_env=os.environ,
        log_directory=tmp_path,
        stop=launcher.StopRequest(),
        api_port=api_port,
        web_port=web_port,
        startup_timeout=20.0,
        stop_grace=2.0,
    )
    assert status == 3
    _assert_all_stopped(api_record, web_record)
    assert launcher.port_problem(api_port) is None


def test_backend_crash_reports_raw_output_and_never_starts_frontend(
    launcher, tmp_path: Path
) -> None:
    api_port, web_port = _free_port(), _free_port()
    with pytest.raises(launcher.LauncherError) as excinfo:
        launcher.run_session(
            _python(SYNTHETIC_CRASH),
            _python(SYNTHETIC_WEB, web_port, tmp_path / "web.json", 60, 0),
            cwd=tmp_path,
            backend_env=os.environ,
            frontend_env=os.environ,
            log_directory=tmp_path,
            stop=launcher.StopRequest(),
            api_port=api_port,
            web_port=web_port,
            startup_timeout=20.0,
        )
    message = str(excinfo.value)
    assert "status 7" in message
    assert "synthetic import failure" in message
    assert "synthetic import failure" in (tmp_path / "backend.log").read_text()
    assert not (tmp_path / "frontend.log").exists()


@pytest.mark.parametrize("health_status", ["starting", None])
def test_startup_is_bounded_and_cleans_up_the_owned_session(
    launcher, tmp_path: Path, health_status: str | None
) -> None:
    api_port, web_port = _free_port(), _free_port()
    record = tmp_path / "api.json"
    backend = (
        _python(SYNTHETIC_HANG, record)
        if health_status is None
        else _python(SYNTHETIC_API, api_port, record, health_status)
    )
    started = time.monotonic()
    with pytest.raises(launcher.LauncherError, match="within 1.5 s"):
        launcher.run_session(
            backend,
            _python(SYNTHETIC_WEB, web_port, tmp_path / "web.json", 60, 0),
            cwd=tmp_path,
            backend_env=os.environ,
            frontend_env=os.environ,
            log_directory=tmp_path,
            stop=launcher.StopRequest(),
            api_port=api_port,
            web_port=web_port,
            startup_timeout=1.5,
            stop_grace=2.0,
        )
    assert time.monotonic() - started < 10
    _assert_all_stopped(record)


@pytest.mark.parametrize("signum", [signal.SIGTERM, signal.SIGINT])
def test_signal_to_launcher_stops_every_owned_process(
    launcher, tmp_path: Path, signum: signal.Signals
) -> None:
    api_port, web_port = _free_port(), _free_port()
    api_record, web_record = tmp_path / "api.json", tmp_path / "web.json"
    logs = tmp_path / "logs"
    logs.mkdir()
    config = {
        "backend": _python(SYNTHETIC_API, api_port, api_record, "ok"),
        "frontend": _python(SYNTHETIC_WEB, web_port, web_record, 600, 0),
        "cwd": str(tmp_path),
        "logs": str(logs),
        "api_port": api_port,
        "web_port": web_port,
    }
    output = tmp_path / "driver.out"
    with output.open("wb") as sink:
        driver = subprocess.Popen(
            [sys.executable, "-c", DRIVER, str(SCRIPT_PATH), json.dumps(config)],
            stdout=sink,
            stderr=subprocess.STDOUT,
        )
    try:
        deadline = time.monotonic() + 20
        while b"session ready" not in output.read_bytes():
            assert driver.poll() is None, output.read_text()
            assert time.monotonic() < deadline, output.read_text()
            time.sleep(0.05)
        driver.send_signal(signum)
        assert driver.wait(timeout=15) == 128 + signum
    finally:
        if driver.poll() is None:
            driver.kill()
            driver.wait()
    _assert_all_stopped(api_record, web_record)
