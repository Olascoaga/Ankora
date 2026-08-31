"""Cancellable Windows-native subprocess execution with raw capture."""

import subprocess
import threading
import time
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from ankora_backend.domain.errors import AnkoraDomainError
from ankora_backend.execution.subprocess_runner import _kill_tree_and_drain


@dataclass(frozen=True, slots=True)
class CancellableToolExecution:
    command: list[str]
    exit_code: int
    stdout: str
    stderr: str
    canceled: bool
    timed_out: bool


def run_cancellable_tool(
    *,
    executable: str,
    arguments: list[str],
    cwd: Path,
    stage: str,
    cancel_event: threading.Event,
    timeout_seconds: int,
    environment: Mapping[str, str] | None = None,
) -> CancellableToolExecution:
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

    started = time.monotonic()
    while True:
        try:
            stdout, stderr = process.communicate(timeout=0.2)
            return CancellableToolExecution(
                command=command,
                exit_code=process.returncode,
                stdout=stdout or "",
                stderr=stderr or "",
                canceled=False,
                timed_out=False,
            )
        except subprocess.TimeoutExpired:
            if cancel_event.is_set():
                stdout, stderr = _kill_tree_and_drain(process)
                return CancellableToolExecution(
                    command=command,
                    exit_code=process.returncode,
                    stdout=stdout,
                    stderr=stderr,
                    canceled=True,
                    timed_out=False,
                )
            if time.monotonic() - started >= timeout_seconds:
                stdout, stderr = _kill_tree_and_drain(process)
                return CancellableToolExecution(
                    command=command,
                    exit_code=process.returncode,
                    stdout=stdout,
                    stderr=stderr,
                    canceled=False,
                    timed_out=True,
                )
