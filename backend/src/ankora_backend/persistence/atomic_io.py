"""Shared atomic JSON persistence helper with unique temp paths and fsync (D5-021)."""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from uuid import uuid4


def atomic_write_json(path: Path, payload: object) -> None:
    """Persist UTF-8 JSON atomically using a unique temporary file, fsync, and os.replace."""
    temporary = path.with_name(
        f"{path.name}.{os.getpid()}.{threading.get_ident()}.{uuid4().hex[:8]}.tmp"
    )
    try:
        with temporary.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(payload, stream, indent=2, ensure_ascii=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
