"""Storage for redocking validation runs (M7).

A validation is a verdict about a specific docking result, so it is kept beside
the results rather than inside them: the docking record stays exactly what the
engine produced, and the validation is a separate, later judgement that names
what it judged.
"""

import json
import os
import threading
from pathlib import Path
from uuid import UUID, uuid4

from ankora_backend.domain.errors import AnkoraDomainError
from ankora_backend.schemas.redocking import RedockingRunRecord

_STAGE = "redocking_storage"


class RedockingValidationStore:
    def __init__(self, root: Path) -> None:
        self._root = root.resolve()
        self._lock = threading.RLock()

    @classmethod
    def from_environment(cls) -> "RedockingValidationStore":
        configured = os.getenv("ANKORA_DATA_DIR")
        return cls(Path(configured) if configured else Path.cwd() / ".ankora-data")

    def new_validation_id(self) -> str:
        return str(uuid4())

    def create(self, record: RedockingRunRecord) -> Path:
        """Create-only: a verdict is never rewritten, only superseded."""
        directory = self._run_dir(record.validation_id)
        directory.mkdir(parents=True, exist_ok=False)
        path = directory / "record.json"
        with path.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(
                record.model_dump(mode="json"), stream, indent=2, ensure_ascii=False
            )
            stream.write("\n")
        return directory

    def load(self, validation_id: str) -> RedockingRunRecord:
        with self._lock:
            try:
                raw = (self._run_dir(validation_id) / "record.json").read_text(
                    encoding="utf-8"
                )
            except FileNotFoundError as error:
                raise self._not_found(validation_id) from error
        return RedockingRunRecord.model_validate_json(raw)

    def list_runs(self) -> list[RedockingRunRecord]:
        """Every validation this project has recorded, newest first."""
        directory = self._runs_dir()
        if not directory.is_dir():
            return []
        records: list[RedockingRunRecord] = []
        for candidate in directory.iterdir():
            if not candidate.is_dir():
                continue
            try:
                records.append(self.load(candidate.name))
            except (AnkoraDomainError, ValueError):
                continue
        return sorted(
            records,
            key=lambda item: (item.created_at, item.validation_id),
            reverse=True,
        )

    def _runs_dir(self) -> Path:
        return self._root / "projects" / "default" / "validation" / "redocking"

    def _run_dir(self, validation_id: str) -> Path:
        try:
            normalized = str(UUID(validation_id))
        except ValueError as error:
            raise self._not_found(validation_id) from error
        resolved = (self._runs_dir() / normalized).resolve()
        if self._root not in resolved.parents:
            raise self._not_found(validation_id)
        return resolved

    @staticmethod
    def _not_found(validation_id: str) -> AnkoraDomainError:
        return AnkoraDomainError(
            code="REDOCKING_VALIDATION_NOT_FOUND",
            stage=_STAGE,
            message="No redocking validation exists for this identifier.",
            status_code=404,
            details={"validation_id": validation_id},
        )
