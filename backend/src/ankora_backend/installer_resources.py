"""Offline installation-only materialization of byte-identical P2Rank models.

The immutable corresponding-source ZIP already ships all seven model files.
The compact installer stores them once and reconstructs the original private
runtime before launch. This module never starts an API or a scientific tool.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
import zipfile
from pathlib import Path

SOURCE_FILE = "sources/cad17d3051f4d0ad-p2rank-source.zip"
SOURCE_SHA256 = "cad17d3051f4d0ad29b6126f6a59ca36569cdb6c4e09cc4bb296e6c667ba72ce"
PAYLOAD_SHA256 = "e83f404b38e20345806c19e3e811d764d0e1c476324ddfdd544f7e36a52c6c7c"
MODEL_NAMES = (
    "alphafold",
    "alphafold_conservation_hmm",
    "conservation_hmm",
    "default",
    "default_rescore",
    "rescore_2024",
    "rescore_conservation",
)


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def contained(root: Path, relative: str) -> Path:
    path = root / relative
    path.resolve().relative_to(root.resolve())
    for entry in (path, *path.parents):
        if entry == root:
            break
        if entry.is_symlink() or entry.is_junction():
            raise ValueError("Installer resource links are not permitted")
    return path


def materialize(root: Path) -> None:
    root = root.resolve(strict=True)
    source = contained(root, f"legal/{SOURCE_FILE}")
    payload = contained(root, "backend/tools/payload.json")
    if digest(source) != SOURCE_SHA256 or digest(payload) != PAYLOAD_SHA256:
        raise ValueError("Installation source/runtime identity mismatch")
    manifest = json.loads(payload.read_text(encoding="utf-8"))
    with zipfile.ZipFile(source) as archive:
        for model in MODEL_NAMES:
            relative = f"p2rank-2.5.1/models/{model}/model.zst"
            member = f"p2rank-2.5.1/distro/models/{model}/model.zst"
            destination = contained(root, f"backend/tools/{relative}")
            expected = manifest["files"][relative]
            if destination.exists():
                if digest(destination) != expected:
                    raise ValueError(f"Existing model has unexpected bytes: {model}")
                continue
            info = archive.getinfo(member)
            if info.file_size > 64 * 1024 * 1024:
                raise ValueError("Model exceeds reviewed installation size bound")
            destination.parent.mkdir(parents=True, exist_ok=True)
            temporary: Path | None = None
            try:
                with tempfile.NamedTemporaryFile(
                    dir=destination.parent, prefix=".ankora-model-", delete=False
                ) as stream:
                    temporary = Path(stream.name)
                    with archive.open(info) as original:
                        written = 0
                        while chunk := original.read(1024 * 1024):
                            written += len(chunk)
                            if written > info.file_size:
                                raise ValueError("Model exceeds declared size")
                            stream.write(chunk)
                if written != info.file_size or digest(temporary) != expected:
                    raise ValueError(f"Source model differs from runtime: {model}")
                # Windows rename refuses to replace a concurrently created file.
                temporary.rename(destination)
                temporary = None
            finally:
                if temporary is not None:
                    temporary.unlink(missing_ok=True)
    print("Seven P2Rank models restored and SHA-256 verified offline.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()
    try:
        materialize(args.root)
    except (OSError, ValueError, KeyError, zipfile.BadZipFile) as error:
        print(f"Offline model installation failed: {error}")
        return 1
    return 0
