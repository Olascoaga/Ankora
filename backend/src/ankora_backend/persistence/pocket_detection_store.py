"""Create-only storage for M4 P2Rank pocket-detection reports."""

import json
import os
from pathlib import Path
from uuid import UUID, uuid4

from ankora_backend.domain.errors import AnkoraDomainError
from ankora_backend.schemas.binding_sites import PocketDetectionReport


class PocketDetectionArtifactStore:
    def __init__(self, root: Path) -> None:
        self._root = root.resolve()

    @classmethod
    def from_environment(cls) -> "PocketDetectionArtifactStore":
        configured = os.getenv("ANKORA_DATA_DIR")
        root = Path(configured) if configured else Path.cwd() / ".ankora-data"
        return cls(root)

    def new_report_id(self) -> str:
        return str(uuid4())

    def save_record(self, record: PocketDetectionReport) -> None:
        directory = self._report_dir(record.report_id)
        directory.mkdir(parents=True, exist_ok=False)
        path = directory / "record.json"
        with path.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(record.model_dump(mode="json"), stream, indent=2, ensure_ascii=False)
            stream.write("\n")

    def load_record(self, report_id: str) -> PocketDetectionReport:
        path = self._report_dir(report_id) / "record.json"
        try:
            raw = path.read_text(encoding="utf-8")
        except FileNotFoundError as error:
            raise self._not_found(report_id) from error
        return PocketDetectionReport.model_validate_json(raw)

    def _report_dir(self, report_id: str) -> Path:
        try:
            normalized_id = str(UUID(report_id))
        except ValueError as error:
            raise self._not_found(report_id) from error
        path = self._root / "projects" / "default" / "derived" / "pocket_detection" / normalized_id
        resolved = path.resolve()
        if self._root not in resolved.parents:
            raise self._not_found(report_id)
        return resolved

    @staticmethod
    def _not_found(report_id: str) -> AnkoraDomainError:
        return AnkoraDomainError(
            code="POCKET_DETECTION_REPORT_NOT_FOUND",
            stage="pocket_detection_storage",
            message="The requested pocket-detection report is not available in this project.",
            status_code=404,
            details={"report_id": report_id},
        )
