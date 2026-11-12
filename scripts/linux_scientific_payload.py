"""Acquire and verify exact Linux scientific upstream inputs and GNINA pack locks.

Mirrors scripts/windows_scientific_payload.py for linux-x86_64 under ADR-029.
Never installs host-wide packages or trusts unverified developer binaries.
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
LOCK = ROOT / "resources/linux-scientific-payload.lock.json"
GNINA_PACK_LOCK = ROOT / "resources/linux-gnina-cuda12-pack.lock.json"
CACHE = ROOT / "build/linux-runtime/upstream"
ALLOWED_HOSTS = {"github.com", "autodock.scripps.edu"}
ALLOWED_ROLES = ("runtime", "addon-runtime", "source", "reference-only", "build-only")
FORBIDDEN_HOST_DRIVER_PREFIXES = (
    "libcuda.so",
    "libnvidia-ml.so",
    "libnvidia-ptxjitcompiler.so",
)


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def safe_relative(name: str) -> PurePosixPath:
    """Reject traversal, device aliases, absolute paths, and Windows separators."""
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
    if payload.get("schema_version") != 1 or payload.get("platform") != "linux-x86_64":
        raise ValueError("Unsupported Linux scientific payload lock")
    entries = payload["artifacts"]
    if not isinstance(entries, list) or not entries:
        raise ValueError("Empty Linux scientific payload lock")
    ids: set[str] = set()
    names: set[str] = set()
    by_id: dict[str, dict[str, Any]] = {}
    for entry in entries:
        entry_id = entry["id"]
        filename = entry["filename"]
        if entry_id in ids or filename.casefold() in names:
            raise ValueError(f"Duplicate payload identity or filename: {entry_id}")
        ids.add(entry_id)
        names.add(filename.casefold())
        by_id[entry_id] = entry
        if len(safe_relative(filename).parts) != 1:
            raise ValueError("Cache filename must be a basename")
        if not re.fullmatch(r"[0-9a-f]{64}", entry["sha256"]):
            raise ValueError(f"Invalid SHA-256 in payload lock: {entry_id}")
        if not isinstance(entry.get("size_bytes"), int) or entry["size_bytes"] <= 0:
            raise ValueError(f"Invalid size_bytes in payload lock: {entry_id}")
        url = urlsplit(entry["url"])
        if url.scheme != "https" or url.hostname not in ALLOWED_HOSTS or url.username:
            raise ValueError("Payload source must be an allowlisted upstream HTTPS URL")
        if entry["role"] not in ALLOWED_ROLES:
            raise ValueError(f"Unrecognized payload role: {entry['role']}")
    for entry in entries:
        if entry["role"] in ("runtime", "addon-runtime") and not entry.get("source_id"):
            raise ValueError(f"Runtime artifact must declare source_id: {entry['id']}")
        source_refs = []
        if entry.get("source_id"):
            source_refs.append(entry["source_id"])
        source_refs.extend(entry.get("extra_source_ids", []))
        for ref in source_refs:
            if ref not in by_id or by_id[ref]["role"] != "source":
                raise ValueError(f"Missing corresponding source entry: {ref}")
    return entries


def load_gnina_pack_lock(
    path: Path = GNINA_PACK_LOCK, *, payload_lock_path: Path = LOCK
) -> dict[str, Any]:
    """Validate the static GNINA + CUDA 12.8 / cuDNN 9 add-on pack lock."""
    upstream_entries = {item["id"]: item for item in load_lock(payload_lock_path)}
    pack = json.loads(path.read_text(encoding="utf-8"))
    if pack.get("schema_version") != 1 or pack.get("platform") != "linux-x86_64":
        raise ValueError("Unsupported GNINA pack lock")
    executable = pack.get("executable")
    if not isinstance(executable, dict):
        raise TypeError("Missing GNINA executable lock")
    safe_relative(executable["relative_path"])
    gnina_upstream = upstream_entries.get("gnina")
    if gnina_upstream is None:
        raise ValueError("Upstream lock is missing gnina entry")
    if (
        executable.get("sha256") != gnina_upstream["sha256"]
        or executable.get("size_bytes") != gnina_upstream["size_bytes"]
    ):
        raise ValueError("GNINA pack executable disagrees with upstream lock")
    for src_id in executable.get("corresponding_source_ids", []):
        if src_id not in upstream_entries or upstream_entries[src_id]["role"] != "source":
            raise ValueError(f"Missing GNINA corresponding source lock: {src_id}")

    declared_forbidden = tuple(pack.get("forbidden_driver_prefixes", ()))
    for required_prefix in FORBIDDEN_HOST_DRIVER_PREFIXES:
        if required_prefix not in declared_forbidden:
            raise ValueError(f"Pack lock must forbid host driver library {required_prefix}")

    libs = pack.get("shared_libraries")
    if not isinstance(libs, list) or not libs:
        raise ValueError("GNINA pack lock has no shared_libraries")
    sonames: set[str] = set()
    filenames: set[str] = set()
    for lib in libs:
        soname = lib["soname"]
        fname = lib["filename"]
        if len(safe_relative(soname).parts) != 1 or len(safe_relative(fname).parts) != 1:
            raise ValueError(f"Library names must be basenames: {soname}")
        for prefix in declared_forbidden:
            if soname.startswith(prefix) or fname.startswith(prefix):
                raise ValueError(f"Forbidden host GPU driver library in pack: {soname}")
        if soname in sonames or fname in filenames:
            raise ValueError(f"Duplicate library in GNINA pack lock: {soname}")
        sonames.add(soname)
        filenames.add(fname)
        if not re.fullmatch(r"[0-9a-f]{64}", lib["sha256"]):
            raise ValueError(f"Invalid library SHA-256: {soname}")
        if not isinstance(lib.get("size_bytes"), int) or lib["size_bytes"] <= 0:
            raise ValueError(f"Invalid library size_bytes: {soname}")
        if not lib.get("redistribution_clause"):
            raise ValueError(f"Missing redistribution_clause for {soname}")

    licenses = pack.get("license_documents")
    if not isinstance(licenses, list) or len(licenses) < 2:
        raise ValueError("GNINA pack lock must pin CUDA and cuDNN license documents")
    seen_lic: set[str] = set()
    for doc in licenses:
        rel = str(safe_relative(doc["relative_path"]))
        if rel in seen_lic:
            raise ValueError(f"Duplicate license document path: {rel}")
        seen_lic.add(rel)
        if not re.fullmatch(r"[0-9a-f]{64}", doc["sha256"]):
            raise ValueError(f"Invalid license document SHA-256: {doc['id']}")
        if not isinstance(doc.get("size_bytes"), int) or doc["size_bytes"] <= 0:
            raise ValueError(f"Invalid license document size_bytes: {doc['id']}")
    return pack


def verify(path: Path, entry: dict[str, Any]) -> None:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"Missing regular payload file: {entry['id']}")
    if entry.get("size_bytes") is not None and path.stat().st_size != entry["size_bytes"]:
        raise ValueError(f"Payload size mismatch: {entry['id']}")
    if sha256(path) != entry["sha256"]:
        raise ValueError(f"Payload SHA-256 mismatch: {entry['id']}")


def acquire(entry: dict[str, Any], cache: Path = CACHE, *, offline: bool = False) -> Path:
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
    with tempfile.NamedTemporaryFile(dir=cache, delete=False, suffix=".partial") as target:
        temporary = Path(target.name)
        try:
            request = urllib.request.Request(
                entry["url"], headers={"User-Agent": "Ankora-Linux-Payload/1.0"}
            )
            with urllib.request.urlopen(request, timeout=120) as response:
                if urlsplit(response.url).scheme != "https":
                    raise ValueError("Refusing an insecure payload redirect")
                shutil.copyfileobj(response, target)
        except BaseException:
            target.close()
            temporary.unlink(missing_ok=True)
            raise
    try:
        verify(temporary, entry)
        destination.hardlink_to(temporary)
    finally:
        temporary.unlink(missing_ok=True)
    return destination


def _resolve_intra_archive_symlink(
    member_rel: PurePosixPath,
    linkname: str,
    *,
    selected_prefix: PurePosixPath | None,
) -> PurePosixPath:
    if not linkname or "\\" in linkname or ":" in linkname:
        raise ValueError(f"Unsafe TAR symlink target: {member_rel} -> {linkname}")
    link_path = PurePosixPath(linkname)
    if link_path.is_absolute():
        raise ValueError(f"Absolute TAR symlink rejected: {member_rel} -> {linkname}")
    stack = list(member_rel.parent.parts)
    min_depth = len(selected_prefix.parts) if selected_prefix is not None else 0
    for part in linkname.split("/"):
        if part in ("", "."):
            continue
        if part == "..":
            if len(stack) <= min_depth:
                raise ValueError(f"Escaping TAR symlink rejected: {member_rel} -> {linkname}")
            stack.pop()
        else:
            safe_relative(part)
            stack.append(part)
    if not stack:
        raise ValueError(f"Empty TAR symlink target: {member_rel} -> {linkname}")
    resolved = PurePosixPath(*stack)
    if selected_prefix is not None and not resolved.is_relative_to(selected_prefix):
        raise ValueError(f"Escaping TAR symlink rejected: {member_rel} -> {linkname}")
    return resolved


def extract_archive(
    archive: Path,
    destination: Path,
    *,
    prefix: str = "",
    include: tuple[str, ...] | None = None,
) -> None:
    """Create-only extraction materializing only safe intra-archive regular-file symlinks."""
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
                if stat.S_ISLNK(mode) or (
                    stat.S_IFMT(mode) not in (0, stat.S_IFREG, stat.S_IFDIR)
                ):
                    raise ValueError(f"Non-regular ZIP member: {member.filename}")
                if path and not member.is_dir():
                    plan.append((member, path))
            destination.mkdir(parents=True)
            for member, path in plan:
                path.parent.mkdir(parents=True, exist_ok=True)
                with source.open(member) as src, path.open("xb") as dst:
                    shutil.copyfileobj(src, dst)
    else:
        with tarfile.open(archive) as tar_source:
            members = tar_source.getmembers()
            regular_by_rel: dict[PurePosixPath, tarfile.TarInfo] = {}
            for tar_member in members:
                if tar_member.isfile():
                    regular_by_rel[safe_relative(tar_member.name)] = tar_member

            tar_plan: list[tuple[tarfile.TarInfo, Path, int]] = []
            for tar_member in members:
                member_rel = safe_relative(tar_member.name)
                path = target(tar_member.name)
                if tar_member.isfile():
                    if path is not None:
                        exec_mode = 0o755 if (tar_member.mode & 0o111) else 0o644
                        tar_plan.append((tar_member, path, exec_mode))
                elif tar_member.isdir():
                    continue
                elif tar_member.issym():
                    resolved_rel = _resolve_intra_archive_symlink(
                        member_rel,
                        tar_member.linkname,
                        selected_prefix=selected_prefix,
                    )
                    target_member = regular_by_rel.get(resolved_rel)
                    if target_member is None:
                        raise ValueError(
                            f"TAR symlink does not target an intra-archive regular file: "
                            f"{tar_member.name} -> {tar_member.linkname}"
                        )
                    if path is not None:
                        exec_mode = 0o755 if (target_member.mode & 0o111) else 0o644
                        tar_plan.append((target_member, path, exec_mode))
                else:
                    raise ValueError(f"Non-regular TAR member: {tar_member.name}")

            destination.mkdir(parents=True)
            for source_member, path, exec_mode in tar_plan:
                path.parent.mkdir(parents=True, exist_ok=True)
                stream = tar_source.extractfile(source_member)
                assert stream is not None
                with stream as src, path.open("xb") as dst:
                    shutil.copyfileobj(src, dst)
                path.chmod(exec_mode)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", type=Path, default=CACHE)
    parser.add_argument("--offline", action="store_true")
    args = parser.parse_args()
    entries = load_lock()
    load_gnina_pack_lock()
    for entry in entries:
        acquire(entry, args.cache, offline=args.offline)
        print(f"Verified {entry['id']} {entry['version']} ({entry['role']})", flush=True)


if __name__ == "__main__":
    main()
