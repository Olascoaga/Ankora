"""Atomic durable lease records for long-running local scientific work."""

import json
import os
import threading
from pathlib import Path
from uuid import UUID

from ankora_backend.schemas.work_recovery import (
    WorkKind,
    WorkLeaseRecord,
)


class WorkLeaseStore:
    def __init__(self, root: Path) -> None:
        self._root = root.resolve()
        self._lock = threading.RLock()

    @classmethod
    def from_environment(cls) -> "WorkLeaseStore":
        configured = os.getenv("ANKORA_DATA_DIR")
        return cls(Path(configured) if configured else Path.cwd() / ".ankora-data")

    def write(self, record: WorkLeaseRecord) -> None:
        with self._lock:
            path = self._path(record.work_kind, record.work_id)
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_suffix(".json.tmp")
            with temporary.open("w", encoding="utf-8", newline="\n") as stream:
                json.dump(
                    record.model_dump(mode="json"),
                    stream,
                    indent=2,
                    ensure_ascii=False,
                )
                stream.write("\n")
            os.replace(temporary, path)

    def load(self, work_kind: WorkKind, work_id: str) -> WorkLeaseRecord | None:
        with self._lock:
            try:
                raw = self._path(work_kind, work_id).read_text(encoding="utf-8")
            except FileNotFoundError:
                return None
        return WorkLeaseRecord.model_validate_json(raw)

    def list_active(self) -> list[WorkLeaseRecord]:
        directory = self._root / "projects" / "default" / "runtime" / "work_leases"
        if not directory.is_dir():
            return []
        records: list[WorkLeaseRecord] = []
        for path in directory.glob("*/*.json"):
            try:
                record = WorkLeaseRecord.model_validate_json(
                    path.read_text(encoding="utf-8")
                )
            except (OSError, ValueError):
                continue
            if record.state.value == "active":
                records.append(record)
        return records

    def _path(self, work_kind: WorkKind, work_id: str) -> Path:
        normalized = str(UUID(work_id))
        path = (
            self._root
            / "projects"
            / "default"
            / "runtime"
            / "work_leases"
            / work_kind.value
            / f"{normalized}.json"
        ).resolve()
        if self._root not in path.parents:
            raise ValueError("Work lease path escaped the Ankora data directory")
        return path
