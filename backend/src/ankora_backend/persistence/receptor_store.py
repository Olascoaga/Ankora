"""Create-only storage for M2 receptor derivatives and raw tool output."""

import json
import os
from pathlib import Path
from uuid import UUID, uuid4

from ankora_backend.domain.errors import AnkoraDomainError
from ankora_backend.domain.project_context import resolve_project_root
from ankora_backend.schemas.receptors import ReceptorPreparationRecord


class ReceptorArtifactStore:
    def __init__(self, root: Path, project_id: str | None = None) -> None:
        self._root = root.resolve()
        self._project_root = resolve_project_root(self._root, project_id)

    @classmethod
    def from_environment(cls, project_id: str | None = None) -> "ReceptorArtifactStore":
        configured = os.getenv("ANKORA_DATA_DIR")
        root = Path(configured) if configured else Path.cwd() / ".ankora-data"
        return cls(root, project_id)

    def new_receptor_id(self) -> str:
        return str(uuid4())

    def create_receptor(self, receptor_id: str) -> Path:
        directory = self._receptor_dir(receptor_id)
        directory.mkdir(parents=True, exist_ok=False)
        return directory

    def output_path(self, receptor_id: str, filename: str) -> Path:
        if Path(filename).name != filename or not filename:
            raise ValueError("Receptor output filename must be a plain filename")
        return self._receptor_dir(receptor_id) / filename

    def write_bytes(self, receptor_id: str, filename: str, content: bytes) -> Path:
        path = self.output_path(receptor_id, filename)
        with path.open("xb") as stream:
            stream.write(content)
        return path

    def write_text(self, receptor_id: str, filename: str, content: str) -> Path:
        path = self.output_path(receptor_id, filename)
        with path.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(content)
        return path

    def save_record(self, record: ReceptorPreparationRecord) -> None:
        path = self.output_path(record.receptor_id, "record.json")
        with path.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(record.model_dump(mode="json"), stream, indent=2, ensure_ascii=False)
            stream.write("\n")

    def load_record(self, receptor_id: str) -> ReceptorPreparationRecord:
        path = self.output_path(receptor_id, "record.json")
        try:
            raw = path.read_text(encoding="utf-8")
        except FileNotFoundError as error:
            raise self._not_found(receptor_id) from error
        return ReceptorPreparationRecord.model_validate_json(raw)

    def load_latest_record(self) -> ReceptorPreparationRecord:
        receptor_root = self._project_root / "derived" / "receptors"
        if not receptor_root.is_dir():
            raise self._latest_not_found()
        records = [
            ReceptorPreparationRecord.model_validate_json(path.read_text(encoding="utf-8"))
            for path in receptor_root.glob("*/record.json")
        ]
        if not records:
            raise self._latest_not_found()
        return max(records, key=lambda record: record.created_at)

    def content_path(self, receptor_id: str, artifact_id: str) -> Path:
        record = self.load_record(receptor_id)
        output = next((item for item in record.outputs if item.artifact_id == artifact_id), None)
        if output is None:
            raise self._not_found(receptor_id, artifact_id)
        path = self.output_path(receptor_id, output.filename)
        if not path.is_file():
            raise self._not_found(receptor_id, artifact_id)
        return path

    def _receptor_dir(self, receptor_id: str) -> Path:
        try:
            normalized_id = str(UUID(receptor_id))
        except ValueError as error:
            raise self._not_found(receptor_id) from error
        path = self._project_root / "derived" / "receptors" / normalized_id
        resolved = path.resolve()
        if self._root not in resolved.parents:
            raise self._not_found(receptor_id)
        return resolved

    @staticmethod
    def _not_found(receptor_id: str, artifact_id: str | None = None) -> AnkoraDomainError:
        details: dict[str, object] = {"receptor_id": receptor_id}
        if artifact_id is not None:
            details["artifact_id"] = artifact_id
        return AnkoraDomainError(
            code="RECEPTOR_NOT_FOUND",
            stage="receptor_storage",
            message="The requested receptor derivative is not available in this project.",
            status_code=404,
            details=details,
        )

    @staticmethod
    def _latest_not_found() -> AnkoraDomainError:
        return AnkoraDomainError(
            code="RECEPTOR_HISTORY_EMPTY",
            stage="receptor_storage",
            message="No saved receptor derivative is available in this project yet.",
            status_code=404,
            details={},
        )
