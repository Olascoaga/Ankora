"""Create-only storage for out-of-sample protocol calibration records.

Each stage of `ADR-031` §3 writes its own file exactly once.  `split.json`,
`selection.json`, and `confirmation.json` are opened with `"x"`, so a second
attempt to seal a stage fails at the filesystem rather than depending on an
in-memory flag: the locked Confirmation split stays single-use even across
process restarts.  `record.json` is the mutable projection of those sealed
stages and is replaced atomically.
"""

import json
import os
import threading
from pathlib import Path
from uuid import UUID, uuid4

from ankora_backend.domain.errors import AnkoraDomainError
from ankora_backend.domain.project_context import resolve_project_root
from ankora_backend.schemas.calibration import (
    CalibrationRunRecord,
    CalibrationSelectionRecord,
    ConfirmationEvaluationRecord,
)

_STAGE = "protocol_calibration_storage"
_RECORD_FILENAME = "record.json"
_SPLIT_FILENAME = "split.json"
_SELECTION_FILENAME = "selection.json"
_CONFIRMATION_FILENAME = "confirmation.json"


class CalibrationArtifactStore:
    """Holds one project's calibration runs under `<project_root>/calibrations`."""

    def __init__(self, root: Path) -> None:
        self._root = root.resolve()
        self._record_lock = threading.RLock()

    @classmethod
    def for_project_root(cls, project_root: Path) -> "CalibrationArtifactStore":
        return cls(project_root / "calibrations")

    @classmethod
    def from_environment(cls, project_id: str | None = None) -> "CalibrationArtifactStore":
        configured = os.getenv("ANKORA_DATA_DIR")
        data_root = Path(configured) if configured else Path.cwd() / ".ankora-data"
        return cls.for_project_root(resolve_project_root(data_root, project_id))

    @property
    def root(self) -> Path:
        return self._root

    def new_calibration_id(self) -> str:
        return str(uuid4())

    def create_run(self, record: CalibrationRunRecord) -> CalibrationRunRecord:
        """Write the immutable split and its first record projection."""
        directory = self._run_dir(record.calibration_id)
        with self._record_lock:
            try:
                directory.mkdir(parents=True, exist_ok=False)
            except FileExistsError as error:
                raise AnkoraDomainError(
                    code="CALIBRATION_ALREADY_EXISTS",
                    stage=_STAGE,
                    message="A calibration run with this identifier already exists.",
                    status_code=409,
                    details={"calibration_id": record.calibration_id},
                ) from error
            self._create_json(
                directory / _SPLIT_FILENAME,
                record.split.model_dump(mode="json"),
                code="CALIBRATION_SPLIT_ALREADY_SEALED",
                message="This calibration run already holds a frozen split.",
                calibration_id=record.calibration_id,
            )
            self._replace_record(directory, record)
        return record

    def save_selection(
        self,
        calibration_id: str,
        updated_record: CalibrationRunRecord,
        selection: CalibrationSelectionRecord,
    ) -> CalibrationRunRecord:
        """Seal the Stage 1 decision; a second seal is refused."""
        directory = self._existing_run_dir(calibration_id, updated_record)
        with self._record_lock:
            self._create_json(
                directory / _SELECTION_FILENAME,
                selection.model_dump(mode="json"),
                code="CALIBRATION_SELECTION_ALREADY_SEALED",
                message=(
                    "The calibration selection is already sealed and cannot be chosen again."
                ),
                calibration_id=calibration_id,
            )
            self._replace_record(directory, updated_record)
        return updated_record

    def save_confirmation(
        self,
        calibration_id: str,
        updated_record: CalibrationRunRecord,
        confirmation: ConfirmationEvaluationRecord,
    ) -> CalibrationRunRecord:
        """Consume the locked Confirmation split exactly once."""
        directory = self._existing_run_dir(calibration_id, updated_record)
        with self._record_lock:
            self._create_json(
                directory / _CONFIRMATION_FILENAME,
                confirmation.model_dump(mode="json"),
                code="CALIBRATION_CONFIRMATION_ALREADY_CONSUMED",
                message=(
                    "The locked confirmation split is single-use and has already been consumed."
                ),
                calibration_id=calibration_id,
            )
            self._replace_record(directory, updated_record)
        return updated_record

    def get_run(self, calibration_id: str) -> CalibrationRunRecord:
        directory = self._run_dir(calibration_id)
        with self._record_lock:
            try:
                raw = (directory / _RECORD_FILENAME).read_text(encoding="utf-8")
            except (FileNotFoundError, NotADirectoryError) as error:
                raise self._not_found(calibration_id) from error
        return CalibrationRunRecord.model_validate_json(raw)

    def list_runs(self) -> list[CalibrationRunRecord]:
        """Every readable calibration run in this project, newest first."""
        if not self._root.is_dir():
            return []
        records: list[CalibrationRunRecord] = []
        for candidate in sorted(self._root.iterdir(), key=lambda item: item.name):
            if not candidate.is_dir():
                continue
            try:
                records.append(self.get_run(candidate.name))
            except (AnkoraDomainError, ValueError):
                continue
        records.sort(key=lambda record: (record.created_at, record.calibration_id), reverse=True)
        return records

    def _existing_run_dir(
        self, calibration_id: str, updated_record: CalibrationRunRecord
    ) -> Path:
        if updated_record.calibration_id != calibration_id:
            raise AnkoraDomainError(
                code="CALIBRATION_RECORD_MISMATCH",
                stage=_STAGE,
                message="The updated record does not belong to this calibration run.",
                status_code=422,
                details={
                    "calibration_id": calibration_id,
                    "record_calibration_id": updated_record.calibration_id,
                },
            )
        directory = self._run_dir(calibration_id)
        if not directory.is_dir():
            raise self._not_found(calibration_id)
        return directory

    def _create_json(
        self,
        path: Path,
        payload: dict[str, object],
        *,
        code: str,
        message: str,
        calibration_id: str,
    ) -> None:
        try:
            stream = path.open("x", encoding="utf-8", newline="\n")
        except FileExistsError as error:
            raise AnkoraDomainError(
                code=code,
                stage=_STAGE,
                message=message,
                status_code=409,
                details={"calibration_id": calibration_id, "artifact": path.name},
            ) from error
        with stream:
            json.dump(payload, stream, indent=2, ensure_ascii=False)
            stream.write("\n")

    def _replace_record(self, directory: Path, record: CalibrationRunRecord) -> None:
        temporary = directory / f"{_RECORD_FILENAME}.tmp"
        with temporary.open("w", encoding="utf-8", newline="\n") as stream:
            json.dump(record.model_dump(mode="json"), stream, indent=2, ensure_ascii=False)
            stream.write("\n")
        os.replace(temporary, directory / _RECORD_FILENAME)

    def _run_dir(self, calibration_id: str) -> Path:
        try:
            normalized = str(UUID(calibration_id))
        except (ValueError, AttributeError, TypeError) as error:
            raise self._not_found(calibration_id) from error
        resolved = (self._root / normalized).resolve()
        try:
            relative = resolved.relative_to(self._root)
        except ValueError as error:
            raise self._not_found(calibration_id) from error
        if relative.parts != (normalized,):
            raise self._not_found(calibration_id)
        return resolved

    @staticmethod
    def _not_found(calibration_id: str) -> AnkoraDomainError:
        return AnkoraDomainError(
            code="CALIBRATION_NOT_FOUND",
            stage=_STAGE,
            message="The requested calibration run is not available in this project.",
            status_code=404,
            details={"calibration_id": calibration_id},
        )
