"""Request-local project identity and safe project-root resolution."""

from __future__ import annotations

import re
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path

from ankora_backend.domain.errors import AnkoraDomainError

DEFAULT_PROJECT_ID = "default"
_PROJECT_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_current_project_id: ContextVar[str] = ContextVar("ankora_project_id", default=DEFAULT_PROJECT_ID)


def validate_project_id(project_id: str) -> str:
    """Return a safe storage identifier or raise a public domain error."""
    if not _PROJECT_ID.fullmatch(project_id) or project_id in {".", ".."}:
        raise AnkoraDomainError(
            code="PROJECT_ID_INVALID",
            stage="project_workspace",
            message="The project identifier is not valid.",
            status_code=422,
            details={"project_id": project_id},
        )
    return project_id


def current_project_id() -> str:
    return _current_project_id.get()


@contextmanager
def project_scope(project_id: str) -> Iterator[None]:
    """Bind storage created within the context to exactly one project."""
    token = _current_project_id.set(validate_project_id(project_id))
    try:
        yield
    finally:
        _current_project_id.reset(token)


def resolve_project_root(data_root: Path, project_id: str | None = None) -> Path:
    """Resolve a project directory without allowing traversal outside data root."""
    root = data_root.resolve()
    normalized = validate_project_id(project_id or current_project_id())
    resolved = (root / "projects" / normalized).resolve()
    if root not in resolved.parents:
        raise AnkoraDomainError(
            code="PROJECT_PATH_INVALID",
            stage="project_workspace",
            message="The project directory resolves outside Ankora's data root.",
            status_code=422,
            details={"project_id": normalized},
        )
    return resolved
