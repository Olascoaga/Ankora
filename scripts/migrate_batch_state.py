"""Add rebuildable incremental indexes without rewriting scientific artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "backend" / "src"))

_INDEX_FILES = {
    "batch_state.sqlite3",
    "batch_state.sqlite3-shm",
    "batch_state.sqlite3-wal",
}


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Migrate active Vina, AutoDock4 CPU, and AutoDock-GPU campaign "
            "records to incremental SQLite sidecars. Existing files are "
            "verified byte-for-byte before success is reported."
        )
    )
    parser.add_argument("--data-root", type=Path, required=True)
    return parser.parse_args()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _scientific_manifest(
    roots: tuple[Path, ...], *, relative_to: Path
) -> dict[str, tuple[int, str]]:
    manifest: dict[str, tuple[int, str]] = {}
    for root in roots:
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("*")):
            if not path.is_file() or path.name in _INDEX_FILES:
                continue
            relative = path.relative_to(relative_to).as_posix()
            manifest[relative] = (path.stat().st_size, _sha256(path))
    return manifest


def _migrate_directory(
    directory: Path,
    loader: Callable[[str], object],
) -> tuple[int, int]:
    total = 0
    created = 0
    if not directory.is_dir():
        return total, created
    for candidate in sorted(directory.iterdir(), key=lambda item: item.name):
        if not candidate.is_dir():
            continue
        total += 1
        index = candidate / "batch_state.sqlite3"
        existed = index.is_file()
        loader(candidate.name)
        if not index.is_file():
            raise RuntimeError(f"Incremental index was not created for {candidate.name}")
        created += int(not existed)
    return total, created


def migrate_active_campaigns(data_root: Path) -> dict[str, Any]:
    """Migrate active result catalogs and prove existing bytes stayed intact."""
    from ankora_backend.persistence.autodock4_store import AutoDock4JobStore
    from ankora_backend.persistence.autodock_gpu_store import AutoDockGpuJobStore
    from ankora_backend.persistence.docking_store import DockingArtifactStore

    root = data_root.resolve()
    results_root = root / "projects" / "default" / "results"
    campaign_roots = (
        results_root / "docking_batches",
        results_root / "autodock4_batches",
        results_root / "autodock_gpu_batches",
    )
    before = _scientific_manifest(campaign_roots, relative_to=root)
    vina = DockingArtifactStore(root)
    autodock4 = AutoDock4JobStore(root)
    autodock_gpu = AutoDockGpuJobStore(root)
    engines = {
        "vina": _migrate_directory(
            results_root / "docking_batches", vina.load_batch_overview
        ),
        "autodock4_cpu": _migrate_directory(
            results_root / "autodock4_batches", autodock4.load_batch_overview
        ),
        "autodock_gpu": _migrate_directory(
            results_root / "autodock_gpu_batches", autodock_gpu.load_batch_overview
        ),
    }
    after = _scientific_manifest(campaign_roots, relative_to=root)
    if before != after:
        changed = sorted(set(before) ^ set(after))
        changed.extend(
            path for path in sorted(set(before) & set(after)) if before[path] != after[path]
        )
        raise RuntimeError(
            "Migration changed pre-existing scientific files: " + ", ".join(changed)
        )
    return {
        "schema_version": 1,
        "campaigns": {
            engine: {"total": counts[0], "indexes_created": counts[1]}
            for engine, counts in engines.items()
        },
        "preexisting_files_preserved": len(before),
        "preexisting_bytes_preserved": sum(size for size, _digest in before.values()),
    }


def main() -> int:
    result = migrate_active_campaigns(_parse_args().data_root)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
