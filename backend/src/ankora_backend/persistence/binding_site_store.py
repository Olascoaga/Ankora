"""Create-only storage for M4 binding-site definitions."""

import json
import os
from pathlib import Path
from uuid import UUID, uuid4

from ankora_backend.domain.errors import AnkoraDomainError
from ankora_backend.schemas.binding_sites import BindingSiteRecord


class BindingSiteArtifactStore:
    def __init__(self, root: Path) -> None:
        self._root = root.resolve()

    @classmethod
    def from_environment(cls) -> "BindingSiteArtifactStore":
        configured = os.getenv("ANKORA_DATA_DIR")
        root = Path(configured) if configured else Path.cwd() / ".ankora-data"
        return cls(root)

    def new_binding_site_id(self) -> str:
        return str(uuid4())

    def save_record(self, record: BindingSiteRecord) -> None:
        directory = self._binding_site_dir(record.binding_site_id)
        directory.mkdir(parents=True, exist_ok=False)
        path = directory / "record.json"
        with path.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(record.model_dump(mode="json"), stream, indent=2, ensure_ascii=False)
            stream.write("\n")

    def load_record(self, binding_site_id: str) -> BindingSiteRecord:
        path = self._binding_site_dir(binding_site_id) / "record.json"
        try:
            raw = path.read_text(encoding="utf-8")
        except FileNotFoundError as error:
            raise self._not_found(binding_site_id) from error
        return BindingSiteRecord.model_validate_json(raw)

    def _binding_site_dir(self, binding_site_id: str) -> Path:
        try:
            normalized_id = str(UUID(binding_site_id))
        except ValueError as error:
            raise self._not_found(binding_site_id) from error
        path = self._root / "projects" / "default" / "derived" / "binding_sites" / normalized_id
        resolved = path.resolve()
        if self._root not in resolved.parents:
            raise self._not_found(binding_site_id)
        return resolved

    @staticmethod
    def _not_found(binding_site_id: str) -> AnkoraDomainError:
        return AnkoraDomainError(
            code="BINDING_SITE_NOT_FOUND",
            stage="binding_site_storage",
            message="The requested binding site is not available in this project.",
            status_code=404,
            details={"binding_site_id": binding_site_id},
        )
