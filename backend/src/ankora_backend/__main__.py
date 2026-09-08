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
        choices=("meeko-ligand", "meeko-receptor", "pdb2pqr", "pdbfixer", "propka"),
    )
    return parser


def _worker(name: str) -> Worker:
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


def _exit_when_parent_stops(parent_pid: int) -> None:
    while psutil.pid_exists(parent_pid):
        time.sleep(1)
    os._exit(0)


def main(argv: Sequence[str] | None = None) -> None:
    arguments = list(sys.argv[1:] if argv is None else argv)
    parsed, worker_arguments = _parser().parse_known_args(arguments)
    if parsed.worker is not None:
        sys.argv = [sys.argv[0], *worker_arguments]
        _worker(parsed.worker)()
        return
    if worker_arguments:
        _parser().error(f"unrecognized arguments: {' '.join(worker_arguments)}")
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
        port=8765,
        log_level="info",
    )


if __name__ == "__main__":
    main()
