"""Mutable workspace metadata kept outside immutable project evidence."""

from __future__ import annotations

import json
import os
import threading
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from ankora_backend.domain.errors import AnkoraDomainError
from ankora_backend.domain.project_context import (
    DEFAULT_PROJECT_ID,
    resolve_project_root,
    validate_project_id,
)
from ankora_backend.schemas.projects import ProjectCatalog, ProjectRecord


class ProjectStore:
    """Own project names and the active identity without rewriting evidence."""

    def __init__(self, root: Path) -> None:
        self._root = root.resolve()
        self._workspace = self._root / "workspace"
        self._catalog_path = self._workspace / "projects.json"
        self._lock = threading.RLock()
        self._ensure_catalog()

    @classmethod
    def from_environment(cls) -> ProjectStore:
        configured = os.getenv("ANKORA_DATA_DIR")
        root = Path(configured) if configured else Path.cwd() / ".ankora-data"
        return cls(root)

    @property
    def root(self) -> Path:
        return self._root

    def catalog(self) -> ProjectCatalog:
        with self._lock:
            return self._read()

    def active_project_id(self) -> str:
        return self.catalog().active_project_id

    def get(self, project_id: str) -> ProjectRecord:
        """Resolve a registered project without changing active state or storage."""
        normalized = validate_project_id(project_id)
        with self._lock:
            project = next(
                (item for item in self._read().projects if item.project_id == normalized),
                None,
            )
            if project is None:
                raise self._not_found(normalized)
            return project

    def create(self, name: str) -> ProjectRecord:
        with self._lock:
            catalog = self._read()
            project_id = str(uuid4())
            project_root = resolve_project_root(self._root, project_id)
            project_root.mkdir(parents=True, exist_ok=False)
            record = ProjectRecord(
                project_id=project_id,
                name=name,
                registered_at=datetime.now(UTC),
            )
            updated = catalog.model_copy(update={"projects": [*catalog.projects, record]})
            try:
                self._write(updated)
            except Exception:
                project_root.rmdir()
                raise
            return record

    def activate(self, project_id: str) -> ProjectRecord:
        normalized = validate_project_id(project_id)
        with self._lock:
            catalog = self._read()
            project = next(
                (item for item in catalog.projects if item.project_id == normalized), None
            )
            if project is None:
                raise self._not_found(normalized)
            if catalog.active_project_id != normalized:
                self._write(catalog.model_copy(update={"active_project_id": normalized}))
            return project

    @staticmethod
    def _not_found(project_id: str) -> AnkoraDomainError:
        return AnkoraDomainError(
            code="PROJECT_NOT_FOUND",
            stage="project_workspace",
            message="The requested project is not registered in this workspace.",
            status_code=404,
            details={"project_id": project_id},
        )

    def _ensure_catalog(self) -> None:
        with self._lock:
            if self._catalog_path.is_file():
                catalog = self._read()
                resolve_project_root(self._root, catalog.active_project_id).mkdir(
                    parents=True, exist_ok=True
                )
                return
            projects_root = self._root / "projects"
            existing_ids = (
                sorted(
                    child.name
                    for child in projects_root.iterdir()
                    if child.is_dir() and _is_valid_project_directory(child.name)
                )
                if projects_root.is_dir()
                else []
            )
            if DEFAULT_PROJECT_ID not in existing_ids:
                resolve_project_root(self._root, DEFAULT_PROJECT_ID).mkdir(
                    parents=True, exist_ok=True
                )
                existing_ids.insert(0, DEFAULT_PROJECT_ID)
            now = datetime.now(UTC)
            records = [
                ProjectRecord(
                    project_id=project_id,
                    name=("Default project" if project_id == DEFAULT_PROJECT_ID else project_id),
                    registered_at=now,
                    migrated_legacy=True,
                )
                for project_id in existing_ids
            ]
            self._write(
                ProjectCatalog(
                    active_project_id=DEFAULT_PROJECT_ID,
                    projects=records,
                )
            )

    def _read(self) -> ProjectCatalog:
        try:
            return ProjectCatalog.model_validate_json(
                self._catalog_path.read_text(encoding="utf-8")
            )
        except (OSError, ValueError) as error:
            raise AnkoraDomainError(
                code="PROJECT_CATALOG_INVALID",
                stage="project_workspace",
                message="The project catalog could not be read safely.",
                status_code=500,
                details={"path": str(self._catalog_path)},
                recoverable=False,
            ) from error

    def _write(self, catalog: ProjectCatalog) -> None:
        self._workspace.mkdir(parents=True, exist_ok=True)
        temporary = self._catalog_path.with_suffix(f".{uuid4().hex}.tmp")
        payload = json.dumps(catalog.model_dump(mode="json"), indent=2, ensure_ascii=False) + "\n"
        try:
            with temporary.open("x", encoding="utf-8", newline="\n") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self._catalog_path)
        finally:
            temporary.unlink(missing_ok=True)


def _is_valid_project_directory(project_id: str) -> bool:
    try:
        validate_project_id(project_id)
    except AnkoraDomainError:
        return False
    return True
