"""Create-only filesystem storage for imported molecular structures."""

import json
import os
import re
from pathlib import Path
from uuid import UUID, uuid4

from ankora_backend.domain.errors import AnkoraDomainError
from ankora_backend.schemas.structures import StructureArtifact, StructureRecord

_SAFE_FILENAME = re.compile(r"[^A-Za-z0-9._-]+")


class StructureArtifactStore:
    def __init__(self, root: Path) -> None:
        self._root = root.resolve()

    @classmethod
    def from_environment(cls) -> "StructureArtifactStore":
        configured = os.getenv("ANKORA_DATA_DIR")
        root = Path(configured) if configured else Path.cwd() / ".ankora-data"
        return cls(root)

    def create_artifact(
        self,
        *,
        artifact: StructureArtifact,
        content: bytes,
    ) -> Path:
        artifact_dir = self._artifact_dir(artifact.artifact_id)
        artifact_dir.mkdir(parents=True, exist_ok=False)
        safe_name = self._sanitize_filename(artifact.original_filename)
        content_path = artifact_dir / safe_name
        with content_path.open("xb") as stream:
            stream.write(content)
        return content_path

    def save_record(self, record: StructureRecord) -> None:
        record_path = self._artifact_dir(record.artifact.artifact_id) / "record.json"
        with record_path.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(record.model_dump(mode="json"), stream, indent=2, ensure_ascii=False)
            stream.write("\n")

    def load_record(self, artifact_id: str) -> StructureRecord:
        record_path = self._artifact_dir(artifact_id) / "record.json"
        try:
            raw = record_path.read_text(encoding="utf-8")
        except FileNotFoundError as error:
            raise self._not_found(artifact_id) from error
        return StructureRecord.model_validate_json(raw)

    def content_path(self, artifact_id: str) -> Path:
        record = self.load_record(artifact_id)
        path = self._artifact_dir(artifact_id) / self._sanitize_filename(
            record.artifact.original_filename
        )
        if not path.is_file():
            raise self._not_found(artifact_id)
        return path

    def new_artifact_id(self) -> str:
        return str(uuid4())

    def _artifact_dir(self, artifact_id: str) -> Path:
        try:
            normalized_id = str(UUID(artifact_id))
        except ValueError as error:
            raise self._not_found(artifact_id) from error
        path = (self._root / "projects" / "default" / "original" / "structures" / normalized_id)
        resolved = path.resolve()
        if self._root not in resolved.parents:
            raise self._not_found(artifact_id)
        return resolved

    @staticmethod
    def _sanitize_filename(filename: str) -> str:
        basename = Path(filename.replace("\\", "/")).name
        sanitized = _SAFE_FILENAME.sub("_", basename).strip("._")
        return sanitized or "structure.cif"

    @staticmethod
    def _not_found(artifact_id: str) -> AnkoraDomainError:
        return AnkoraDomainError(
            code="STRUCTURE_NOT_FOUND",
            stage="structure_storage",
            message="The requested structure is not available in this project.",
            status_code=404,
            details={"artifact_id": artifact_id},
        )
