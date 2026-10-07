"""Acquire exact upstream inputs without installing anything on the build host.

This module does not confer redistribution approval. Reference-only artifacts
are never runtime payloads. The complete packaging/legal gate is separate.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import stat
import tarfile
import tempfile
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
LOCK = ROOT / "resources/windows-scientific-payload.lock.json"
CACHE = ROOT / "build/windows-runtime/upstream"
ALLOWED_HOSTS = {"github.com", "autodock.scripps.edu"}


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def safe_relative(name: str) -> PurePosixPath:
    """Reject traversal, NTFS streams/devices, aliases and Windows separators."""
    path = PurePosixPath(name)
    if (
        not name
        or "\\" in name
        or ":" in name
        or path.is_absolute()
        or any(
            part in (".", "..", "")
            or part.endswith((".", " "))
            or re.fullmatch(r"(?i)(con|prn|aux|nul|com[0-9]|lpt[0-9])(?:\..*)?", part)
            for part in name.rstrip("/").split("/")
        )
    ):
        raise ValueError(f"Unsafe payload path: {name}")
    return path


def load_lock(path: Path = LOCK) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != 1 or payload.get("platform") != "windows-x86_64":
        raise ValueError("Unsupported scientific payload lock")
    entries = payload["artifacts"]
    ids: set[str] = set()
    names: set[str] = set()
    for entry in entries:
        if entry["id"] in ids or entry["filename"].casefold() in names:
            raise ValueError("Duplicate payload identity or filename")
        ids.add(entry["id"])
        names.add(entry["filename"].casefold())
        if len(safe_relative(entry["filename"]).parts) != 1:
            raise ValueError("Cache filename must be a basename")
        if not re.fullmatch("[0-9a-f]{64}", entry["sha256"]):
            raise ValueError("Invalid SHA-256 in payload lock")
        url = urlsplit(entry["url"])
        if url.scheme != "https" or url.hostname not in ALLOWED_HOSTS or url.username:
            raise ValueError("Payload source must be an allowlisted upstream HTTPS URL")
        if entry["role"] not in ("runtime", "source", "reference-only", "build-only"):
            raise ValueError("Unrecognized payload role")
    for entry in entries:
        if entry.get("source_id") and entry["source_id"] not in ids:
            raise ValueError("Missing corresponding source entry")
    return entries


def verify(path: Path, entry: dict[str, Any]) -> None:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"Missing regular payload file: {entry['id']}")
    if entry.get("size_bytes") is not None and path.stat().st_size != entry["size_bytes"]:
        raise ValueError(f"Payload size mismatch: {entry['id']}")
    if sha256(path) != entry["sha256"]:
        raise ValueError(f"Payload SHA-256 mismatch: {entry['id']}")


def acquire(entry: dict[str, Any], cache: Path, *, offline: bool = False) -> Path:
    cache.mkdir(parents=True, exist_ok=True)
    filename = safe_relative(entry["filename"])
    if len(filename.parts) != 1:
        raise ValueError("Cache filename must be a basename")
    destination = cache / str(filename)
    if destination.exists() or destination.is_symlink():
        verify(destination, entry)
        return destination
    if offline:
        raise FileNotFoundError(f"Offline cache is missing {entry['id']}")
    # Partial network transfers never acquire a valid cache name. Existing bad
    # bytes are an error, not silently replaced under a supposedly frozen lock.
    with tempfile.NamedTemporaryFile(dir=cache, delete=False, suffix=".partial") as target:
        temporary = Path(target.name)
        try:
            with urllib.request.urlopen(entry["url"], timeout=60) as response:
                if urlsplit(response.url).scheme != "https":
                    raise ValueError("Refusing an insecure payload redirect")
                shutil.copyfileobj(response, target)
        except BaseException:
            target.close()
            temporary.unlink(missing_ok=True)
            raise
    try:
        verify(temporary, entry)
        # Hard link publishes create-only; a concurrent writer cannot be replaced.
        destination.hardlink_to(temporary)
    finally:
        temporary.unlink(missing_ok=True)
    return destination


def extract_archive(
    archive: Path, destination: Path, *, prefix: str = "", include: tuple[str, ...] | None = None
) -> None:
    """Create-only extraction after validating every member, including unused ones."""
    if destination.exists():
        raise FileExistsError(f"Extraction is create-only: {destination}")
    selected_prefix = safe_relative(prefix) if prefix else None
    seen: set[str] = set()

    def target(name: str) -> Path | None:
        relative = safe_relative(name)
        key = str(relative).casefold()
        if key in seen:
            raise ValueError(f"Duplicate archive member: {name}")
        seen.add(key)
        if selected_prefix:
            if not relative.is_relative_to(selected_prefix):
                return None
            relative = relative.relative_to(selected_prefix)
        if not relative.parts:
            return None
        if include is not None and not any(
            relative.is_relative_to(safe_relative(item)) for item in include
        ):
            return None
        return destination.joinpath(*relative.parts)

    if zipfile.is_zipfile(archive):
        with zipfile.ZipFile(archive) as source:
            plan = []
            for member in source.infolist():
                path = target(member.filename)
                mode = member.external_attr >> 16
                if stat.S_ISLNK(mode) or (stat.S_IFMT(mode) not in (0, stat.S_IFREG, stat.S_IFDIR)):
                    raise ValueError(f"Non-regular ZIP member: {member.filename}")
                if path and not member.is_dir():
                    plan.append((member, path))
            destination.mkdir(parents=True)
            for member, path in plan:
                path.parent.mkdir(parents=True, exist_ok=True)
                with source.open(member) as src, path.open("xb") as dst:
                    shutil.copyfileobj(src, dst)
    else:
        with tarfile.open(archive) as source:
            tar_plan = []
            for member in source.getmembers():
                path = target(member.name)
                if not member.isfile() and not member.isdir():
                    raise ValueError(f"Non-regular TAR member: {member.name}")
                if path and member.isfile():
                    tar_plan.append((member, path))
            destination.mkdir(parents=True)
            for member, path in tar_plan:
                path.parent.mkdir(parents=True, exist_ok=True)
                stream = source.extractfile(member)
                assert stream is not None
                with stream as src, path.open("xb") as dst:
                    shutil.copyfileobj(src, dst)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", type=Path, default=CACHE)
    parser.add_argument("--offline", action="store_true")
    args = parser.parse_args()
    for entry in load_lock():
        acquire(entry, args.cache, offline=args.offline)
        print(f"Verified {entry['id']} {entry['version']} ({entry['role']})", flush=True)


if __name__ == "__main__":
    main()
