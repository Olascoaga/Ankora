"""Windows-authoritative subprocess execution with argument arrays and raw capture."""

import subprocess
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from ankora_backend.domain.errors import AnkoraDomainError


@dataclass(frozen=True, slots=True)
class ToolExecution:
    command: list[str]
    exit_code: int
    stdout: str
    stderr: str


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
    try:
        process = subprocess.Popen(
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
            message="Windows could not launch the configured scientific tool.",
            status_code=500,
            details={"command": command, "reason": str(error)},
        ) from error

    try:
        stdout, stderr = process.communicate(timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        stdout, stderr = _kill_tree_and_drain(process)
        raise AnkoraDomainError(
            code="SCIENTIFIC_TOOL_TIMEOUT",
            stage=stage,
            message="The scientific tool exceeded Ankora's execution time limit.",
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


def _kill_tree_and_drain(process: "subprocess.Popen[str]") -> tuple[str, str]:
    """Kill the whole process tree, not just the direct child.

    `subprocess.run(timeout=...)`/`Popen.kill()` only terminate the process
    Ankora launched directly. For a `cmd /c prank.bat` invocation, that's
    `cmd.exe` — its `java.exe` child survives the timeout and keeps running
    indefinitely. `taskkill /T` walks the tree by PID, which Job Objects
    would also solve but only `taskkill` is available without a new
    dependency.
    """
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
        process.kill()
    try:
        stdout, stderr = process.communicate(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        stdout, stderr = process.communicate()
    return stdout or "", stderr or ""
