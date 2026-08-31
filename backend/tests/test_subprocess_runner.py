"""Contracts for Windows subprocess execution, including real process-tree cleanup.

The timeout-kills-the-whole-tree behavior is verified against a real child
process (not mocked): `subprocess.run(timeout=...)`/`Popen.kill()` only ever
terminate the process Ankora launches directly, so for a `cmd /c <tool>`
invocation the tool's own child (e.g. `java.exe` under `prank.bat`) would
otherwise survive a timeout indefinitely. This is real, not guessed — Windows
process-tree semantics are exactly what's under test.
"""

import subprocess
import time
from pathlib import Path

import pytest

from ankora_backend.domain.errors import AnkoraDomainError
from ankora_backend.execution.subprocess_runner import run_tool


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
