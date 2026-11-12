"""Run Ankora's localhost backend or one packaged scientific worker."""

import argparse
import os
import sys
import threading
import time
from collections.abc import Callable, Sequence
from typing import cast

import psutil
import uvicorn

Worker = Callable[[], object]


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--parent-pid", type=int)
    parser.add_argument(
        "--worker",
        choices=(
            "meeko-ligand",
            "meeko-receptor",
            "pdb2pqr",
            "pdbfixer",
            "propka",
            "native-smoke",
            "installer-resources",
        ),
    )
    return parser


def _worker(name: str) -> Worker:
    if name == "installer-resources":
        from ankora_backend.installer_resources import main as installer_main

        return installer_main
    if name == "native-smoke":
        from ankora_backend.validation.native_tool_smoke import main as smoke_main

        return cast(Worker, smoke_main)
    if name == "meeko-ligand":
        from meeko.cli.mk_prepare_ligand import main

        return cast(Worker, main)
    if name == "meeko-receptor":
        from meeko.cli.mk_prepare_receptor import main

        return cast(Worker, main)
    if name == "pdbfixer":
        from ankora_backend.adapters.tools.pdbfixer_worker import main

        return cast(Worker, main)
    if name == "propka":
        from propka.run import main

        return cast(Worker, main)
    from ankora_backend.adapters.tools.pdb2pqr_worker import main

    return cast(Worker, main)


def _capture_parent_identity(parent_pid: int) -> tuple[float | None, bool]:
    getppid = getattr(os, "getppid", None)
    was_direct_parent = callable(getppid) and getppid() == parent_pid
    try:
        return psutil.Process(parent_pid).create_time(), was_direct_parent
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
        return None, was_direct_parent


def _parent_process_alive(
    parent_pid: int,
    *,
    expected_create_time: float | None = None,
    was_direct_parent: bool = False,
) -> bool:
    getppid = getattr(os, "getppid", None)
    if was_direct_parent and callable(getppid) and getppid() != parent_pid:
        return False
    if not psutil.pid_exists(parent_pid):
        return False
    try:
        proc = psutil.Process(parent_pid)
        if proc.status() == psutil.STATUS_ZOMBIE:
            return False
        if (
            expected_create_time is not None
            and abs(proc.create_time() - expected_create_time) > 1.0
        ):
            return False
    except (psutil.NoSuchProcess, psutil.ZombieProcess):
        return False
    except psutil.AccessDenied:
        return True
    return True


def _exit_when_parent_stops(parent_pid: int) -> None:
    expected_create_time, was_direct_parent = _capture_parent_identity(parent_pid)
    while _parent_process_alive(
        parent_pid,
        expected_create_time=expected_create_time,
        was_direct_parent=was_direct_parent,
    ):
        time.sleep(0.5)
    os._exit(0)


def _resolve_backend_port() -> int:
    raw = os.getenv("ANKORA_BACKEND_PORT", "8765").strip()
    try:
        port = int(raw)
    except ValueError as error:
        raise ValueError(f"Invalid ANKORA_BACKEND_PORT: {raw!r}") from error
    if not (1024 <= port <= 65535):
        raise ValueError(f"ANKORA_BACKEND_PORT out of unprivileged range: {port}")
    return port


def main(argv: Sequence[str] | None = None) -> None:
    arguments = list(sys.argv[1:] if argv is None else argv)
    parsed, worker_arguments = _parser().parse_known_args(arguments)
    if parsed.worker is not None:
        sys.argv = [sys.argv[0], *worker_arguments]
        result = _worker(parsed.worker)()
        if isinstance(result, int):
            raise SystemExit(result)
        return
    if worker_arguments:
        _parser().error(f"unrecognized arguments: {' '.join(worker_arguments)}")
    port = _resolve_backend_port()
    if parsed.parent_pid is not None:
        threading.Thread(
            target=_exit_when_parent_stops,
            args=(parsed.parent_pid,),
            daemon=True,
        ).start()

    from ankora_backend.api.app import create_app

    uvicorn.run(
        create_app(),
        host="127.0.0.1",
        port=port,
        log_level="info",
    )


if __name__ == "__main__":
    main()
