"""Resolve installed scientific tools only inside Ankora's private payload.

Never search a developer environment when a packaged component is missing.
The build emits a relative, hash-bound inventory including Java/P2Rank data.
"""

import hashlib
import json
import sys
from functools import lru_cache
from pathlib import Path, PurePosixPath


def bundle_root() -> Path | None:
    return (
        Path(sys.executable).resolve().parent / "tools" if getattr(sys, "frozen", False) else None
    )


def _relative(root: Path, value: str) -> Path:
    relative = PurePosixPath(value)
    if (
        not value
        or "\\" in value
        or ":" in value
        or relative.is_absolute()
        or ".." in relative.parts
    ):
        raise ValueError("Invalid bundled scientific resource path")
    path = root.joinpath(*relative.parts).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError("Bundled resource escaped its installation")
    return path


@lru_cache(maxsize=4)
def _inventory(root: Path, modified_ns: int, size: int) -> dict[str, tuple[Path, str]]:
    # Cache only a successfully verified, complete manifest. Arguments bind the
    # cache to the manifest's filesystem identity, not a global developer path.
    del modified_ns, size
    payload = json.loads((root / "payload.json").read_text(encoding="utf-8"))
    if payload["schema_version"] != 1:
        raise ValueError("Unsupported bundled scientific inventory")
    files: dict[str, str] = payload["files"]
    actual_files = {path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file()}
    if actual_files != set(files) | {"payload.json"}:
        raise ValueError("Bundled scientific inventory has missing or unlisted files")
    for relative, expected in files.items():
        path = _relative(root, relative)
        with path.open("rb") as stream:
            actual = hashlib.file_digest(stream, "sha256").hexdigest()
        if actual != expected:
            raise ValueError(f"Bundled scientific resource checksum failed: {relative}")
    tools: dict[str, tuple[Path, str]] = {}
    for name, record in payload["tools"].items():
        relative = record["path"]
        if relative not in files:
            raise ValueError("Bundled tool has no integrity record")
        tools[name] = (_relative(root, relative), record["version"])
    required = {"vina", "autogrid4", "autodock4", "autodock_gpu", "p2rank", "java"}
    if set(tools) != required:
        raise ValueError("Incomplete bundled scientific tool inventory")
    return tools


def bundled_tool(name: str) -> tuple[Path, str] | None:
    root = bundle_root()
    if root is None:
        return None
    try:
        stat = (root / "payload.json").stat()
        tools = _inventory(root, stat.st_mtime_ns, stat.st_size)
        found = tools.get(name)
        if found is not None and found[0].is_file():
            return found
    except (OSError, ValueError, KeyError, TypeError):
        # Readiness is false, never a request to discover another installation.
        return None
    return None


def bundled_execution_identity(name: str) -> dict[str, object]:
    """Bind recorded work to the entire private payload, including Java/models.

    Historical/external installations are not assigned an invented identity.
    A changed dependency remains distinguishable even when prank.bat is unchanged.
    """
    root = bundle_root()
    if root is None or bundled_tool(name) is None:
        return {}
    raw = (root / "payload.json").read_bytes()
    payload = json.loads(raw)
    return {
        "bundled_payload_sha256": hashlib.sha256(raw).hexdigest(),
        "bundled_tool_variant": payload["tools"][name].get("variant", "upstream"),
    }
