"""Contracts for subprocess execution, including Windows cmd/taskkill and cross-platform runs.

The timeout-kills-the-whole-tree behavior is verified against a real child
process (not mocked): `subprocess.run(timeout=...)`/`Popen.kill()` only ever
terminate the process Ankora launches directly, so for a `cmd /c <tool>`
invocation the tool's own child (e.g. `java.exe` under `prank.bat`) would
otherwise survive a timeout indefinitely. All inline Python helper invocations
below are explicitly SYNTHETIC process-control probes, never scientific fixtures.
"""

import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from ankora_backend.domain.errors import AnkoraDomainError
from ankora_backend.execution.cancellable_subprocess import run_cancellable_tool
from ankora_backend.execution.subprocess_runner import (
    LAUNCH_FAILED_MESSAGE,
    run_tool,
)


def _ping_still_running() -> bool:
    for _ in range(10):
        result = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq ping.exe", "/FO", "CSV"],
            capture_output=True,
            text=True,
            check=False,
        )
        if "ping.exe" not in result.stdout.lower():
            return False
        time.sleep(0.2)
    return True


@pytest.mark.skipif(
    sys.platform != "win32",
    reason="Windows cmd.exe and tasklist process-tree contract",
)
def test_timeout_kills_the_whole_process_tree_not_just_cmd(tmp_path: Path) -> None:
    with pytest.raises(AnkoraDomainError) as excinfo:
        run_tool(
            executable="cmd",
            arguments=["/c", "ping", "-n", "60", "127.0.0.1"],
            cwd=tmp_path,
            stage="test",
            timeout_seconds=1,
        )
    assert excinfo.value.code == "SCIENTIFIC_TOOL_TIMEOUT"

    # cmd.exe itself is `run_tool`'s direct child and is always cleaned up
    # even without tree-killing; ping.exe is cmd's own child, and is exactly
    # what a direct-child-only kill would leave orphaned.
    assert not _ping_still_running()


@pytest.mark.skipif(
    sys.platform != "win32",
    reason="Windows cmd.exe echo contract",
)
def test_successful_run_still_returns_captured_output(tmp_path: Path) -> None:
    execution = run_tool(
        executable="cmd",
        arguments=["/c", "echo", "hello"],
        cwd=tmp_path,
        stage="test",
        timeout_seconds=10,
    )
    assert execution.exit_code == 0
    assert "hello" in execution.stdout


def test_cross_platform_run_tool_preserves_args_env_cwd_and_exact_streams(
    tmp_path: Path,
) -> None:
    """SYNTHETIC process probe verifying argument arrays, cwd, env, and stream capture."""
    script = (
        "import os, pathlib, sys\n"
        "sys.stdout.write(f'cwd={pathlib.Path.cwd().name}|arg={sys.argv[1]}|"
        "env={os.environ.get(\"ANKORA_SYNTHETIC_PROBE\", \"\")}\\n')\n"
        "sys.stderr.write('synthetic-stderr-line\\n')\n"
    )
    env = {**os.environ, "ANKORA_SYNTHETIC_PROBE": "expected-value"}
    execution = run_tool(
        executable=sys.executable,
        arguments=["-c", script, "synthetic-arg"],
        cwd=tmp_path,
        stage="synthetic_test",
        timeout_seconds=10,
        environment=env,
    )
    assert execution.command == [sys.executable, "-c", script, "synthetic-arg"]
    assert execution.exit_code == 0
    assert execution.stdout == f"cwd={tmp_path.name}|arg=synthetic-arg|env=expected-value\n"
    assert execution.stderr == "synthetic-stderr-line\n"


def test_cross_platform_run_tool_preserves_nonzero_exit_and_streams(tmp_path: Path) -> None:
    """SYNTHETIC process probe verifying non-zero exit code and exact output preservation."""
    script = (
        "import sys\n"
        "sys.stdout.write('synthetic-out\\n')\n"
        "sys.stderr.write('synthetic-err\\n')\n"
        "raise SystemExit(17)\n"
    )
    execution = run_tool(
        executable=sys.executable,
        arguments=["-c", script],
        cwd=tmp_path,
        stage="synthetic_test",
        timeout_seconds=10,
    )
    assert execution.exit_code == 17
    assert execution.stdout == "synthetic-out\n"
    assert execution.stderr == "synthetic-err\n"


def test_cross_platform_launch_failure_uses_platform_neutral_error(tmp_path: Path) -> None:
    missing_executable = str(tmp_path / "nonexistent-synthetic-tool-binary")
    with pytest.raises(AnkoraDomainError) as excinfo:
        run_tool(
            executable=missing_executable,
            arguments=["--version"],
            cwd=tmp_path,
            stage="synthetic_launch",
            timeout_seconds=5,
        )
    assert excinfo.value.code == "SCIENTIFIC_TOOL_LAUNCH_FAILED"
    assert excinfo.value.stage == "synthetic_launch"
    assert excinfo.value.message == LAUNCH_FAILED_MESSAGE
    assert "Windows" not in excinfo.value.message
    assert excinfo.value.details["command"] == [missing_executable, "--version"]


def test_cross_platform_pre_canceled_call_does_not_launch_process(tmp_path: Path) -> None:
    """SYNTHETIC probe verifying a pre-set cancel_event never spawns the child process."""
    marker = tmp_path / "should_not_exist.marker"
    script = (
        "import pathlib, sys\n"
        "pathlib.Path(sys.argv[1]).write_text('launched', encoding='utf-8')\n"
    )
    cancel_event = threading.Event()
    cancel_event.set()

    execution = run_cancellable_tool(
        executable=sys.executable,
        arguments=["-c", script, str(marker)],
        cwd=tmp_path,
        stage="synthetic_cancel",
        cancel_event=cancel_event,
        timeout_seconds=10,
    )
    assert execution.canceled is True
    assert execution.timed_out is False
    assert execution.exit_code == -1
    assert execution.stdout == ""
    assert execution.stderr == ""
    assert not marker.exists()


def test_windows_cancellable_branch_preserves_single_capture_when_canceled_during_communicate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SYNTHETIC unit probe for the Windows communicate+cancel branch (no double capture)."""
    import ankora_backend.execution.cancellable_subprocess as cancellable_mod
    import ankora_backend.execution.subprocess_runner as runner_mod

    cancel_event = threading.Event()
    taskkill_calls: list[list[str]] = []

    class _SyntheticWindowsPopen:
        pid = 43210
        returncode = 0
        stdout = None
        stderr = None

        def communicate(self, timeout: float | None = None) -> tuple[str, str]:
            _ = timeout
            cancel_event.set()
            # CPython Popen.communicate() returns the same buffered tuple on repeat calls.
            return ("synthetic-once-stdout\n", "synthetic-once-stderr\n")

        def kill(self) -> None:
            self.returncode = 1

    def _fake_spawn(**kwargs: object) -> object:
        _ = kwargs
        return _SyntheticWindowsPopen()

    def _fake_run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        _ = kwargs
        taskkill_calls.append(cmd)
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(cancellable_mod.os, "name", "nt")
    monkeypatch.setattr(runner_mod.os, "name", "nt")
    monkeypatch.setattr(cancellable_mod, "_spawn_tool_process", _fake_spawn)
    monkeypatch.setattr(runner_mod.subprocess, "run", _fake_run)

    execution = run_cancellable_tool(
        executable="synthetic-tool.exe",
        arguments=["--flag"],
        cwd=tmp_path,
        stage="synthetic_win_cancel",
        cancel_event=cancel_event,
        timeout_seconds=10,
    )
    assert execution.canceled is True
    assert execution.timed_out is False
    assert execution.exit_code == -1
    assert execution.stdout == "synthetic-once-stdout\n"
    assert execution.stderr == "synthetic-once-stderr\n"
    assert taskkill_calls == [["taskkill", "/PID", "43210", "/T", "/F"]]
