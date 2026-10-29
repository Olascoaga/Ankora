"""Cancellable cross-platform scientific subprocess execution with raw capture."""

import contextlib
import os
import subprocess
import threading
import time
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from ankora_backend.execution.subprocess_runner import (
    _kill_tree_and_drain,
    _run_posix_tool_process,
    _spawn_tool_process,
)


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
    if cancel_event.is_set():
        return CancellableToolExecution(
            command=command,
            exit_code=-1,
            stdout="",
            stderr="",
            canceled=True,
            timed_out=False,
        )

    if os.name != "nt":
        exit_code, stdout, stderr, canceled, timed_out = _run_posix_tool_process(
            command=command,
            cwd=cwd,
            stage=stage,
            timeout_seconds=timeout_seconds,
            environment=environment,
            cancel_event=cancel_event,
        )
        return CancellableToolExecution(
            command=command,
            exit_code=exit_code,
            stdout=stdout,
            stderr=stderr,
            canceled=canceled,
            timed_out=timed_out,
        )

    process = _spawn_tool_process(
        command=command,
        cwd=cwd,
        stage=stage,
        environment=environment,
        start_new_session=False,
    )

    started = time.monotonic()
    completed = False
    try:
        while True:
            if cancel_event.is_set():
                stdout, stderr = _kill_tree_and_drain(process)
                completed = True
                exit_code = (
                    process.returncode
                    if process.returncode is not None and process.returncode != 0
                    else -1
                )
                return CancellableToolExecution(
                    command=command,
                    exit_code=exit_code,
                    stdout=stdout,
                    stderr=stderr,
                    canceled=True,
                    timed_out=False,
                )
            try:
                stdout, stderr = process.communicate(timeout=0.2)
                if cancel_event.is_set():
                    _kill_tree_and_drain(process)
                    completed = True
                    exit_code = (
                        process.returncode
                        if process.returncode is not None and process.returncode != 0
                        else -1
                    )
                    return CancellableToolExecution(
                        command=command,
                        exit_code=exit_code,
                        stdout=stdout or "",
                        stderr=stderr or "",
                        canceled=True,
                        timed_out=False,
                    )
                completed = True
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
                    completed = True
                    exit_code = (
                        process.returncode
                        if process.returncode is not None and process.returncode != 0
                        else -1
                    )
                    return CancellableToolExecution(
                        command=command,
                        exit_code=exit_code,
                        stdout=stdout,
                        stderr=stderr,
                        canceled=True,
                        timed_out=False,
                    )
                if time.monotonic() - started >= timeout_seconds:
                    stdout, stderr = _kill_tree_and_drain(process)
                    completed = True
                    exit_code = (
                        process.returncode
                        if process.returncode is not None and process.returncode != 0
                        else -1
                    )
                    return CancellableToolExecution(
                        command=command,
                        exit_code=exit_code,
                        stdout=stdout,
                        stderr=stderr,
                        canceled=False,
                        timed_out=True,
                    )
    finally:
        if not completed:
            with contextlib.suppress(Exception):
                _kill_tree_and_drain(process)
