"""Create-only immutable persistence for ADR-033 analog catalogs, searches, and selections."""

from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from uuid import UUID, uuid4

from ankora_backend.domain.errors import AnkoraDomainError
from ankora_backend.domain.project_context import resolve_project_root
from ankora_backend.schemas.analog_expansion import (
    AnalogCatalogRecord,
    AnalogCatalogSummary,
    AnalogSearchRecord,
    AnalogSelectionRecord,
)

_LOG = logging.getLogger(__name__)

_SAFE_FILENAME = re.compile(r"[^A-Za-z0-9._-]+")
_STAGE = "analog_expansion_storage"


class AnalogExpansionStore:
    """Create-only artifact store for ADR-033 records + workspace-local SQLite FP cache path."""

    def __init__(self, root: Path, project_id: str | None = None) -> None:
        self._root = root.resolve()
        self._project_root = resolve_project_root(self._root, project_id)

    @classmethod
    def from_environment(cls, project_id: str | None = None) -> AnalogExpansionStore:
        configured = os.getenv("ANKORA_DATA_DIR")
        root = Path(configured) if configured else Path.cwd() / ".ankora-data"
        return cls(root, project_id)

    @property
    def root(self) -> Path:
        return self._root

    @property
    def project_root(self) -> Path:
        return self._project_root

    @property
    def fp_cache_path(self) -> Path:
        """Workspace-local fingerprint cache outside immutable project evidence."""
        return (self._root / "workspace" / "cache" / "analog_fp_cache.sqlite3").resolve()

    @staticmethod
    def sanitize_filename(filename: str) -> str:
        basename = Path(filename.replace("\\", "/")).name
        cleaned = _SAFE_FILENAME.sub("_", basename).strip("._")
        return cleaned or "analog_catalog.smi"

    def new_catalog_id(self) -> str:
        return str(uuid4())

    def new_search_id(self) -> str:
        return str(uuid4())

    def new_selection_id(self) -> str:
        return str(uuid4())

    def create_catalog(self, record: AnalogCatalogRecord, raw_content: bytes) -> Path:
        directory = self._catalog_dir(record.analog_catalog_id)
        directory.mkdir(parents=True, exist_ok=False)
        content_path = directory / self.sanitize_filename(record.filename)
        with content_path.open("xb") as stream:
            stream.write(raw_content)
        with (directory / "record.json").open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(record.model_dump(mode="json"), stream, indent=2, ensure_ascii=False)
            stream.write("\n")
        return content_path

    def load_catalog(self, analog_catalog_id: str) -> AnalogCatalogRecord:
        path = self._catalog_dir(analog_catalog_id) / "record.json"
        try:
            raw = path.read_text(encoding="utf-8")
        except FileNotFoundError as error:
            raise self._not_found("ANALOG_CATALOG_NOT_FOUND", analog_catalog_id) from error
        return AnalogCatalogRecord.model_validate_json(raw)

    def catalog_content_path(self, analog_catalog_id: str) -> Path:
        record = self.load_catalog(analog_catalog_id)
        path = self._catalog_dir(analog_catalog_id) / self.sanitize_filename(record.filename)
        if not path.is_file():
            raise self._not_found("ANALOG_CATALOG_NOT_FOUND", analog_catalog_id)
        return path

    def list_catalogs(self) -> list[AnalogCatalogSummary]:
        root = self._base_dir() / "catalogs"
        if not root.is_dir():
            return []
        summaries: list[AnalogCatalogSummary] = []
        for entry in root.iterdir():
            if not entry.is_dir():
                continue
            try:
                rec = self.load_catalog(entry.name)
            except (AnkoraDomainError, OSError, ValueError) as error:
                _LOG.warning(
                    "Skipping unreadable analog expansion record %s: %s (%s)",
                    entry,
                    type(error).__name__,
                    error,
                )
                continue
            summaries.append(
                AnalogCatalogSummary(
                    analog_catalog_id=rec.analog_catalog_id,
                    name=rec.name,
                    source_format=rec.source_format,
                    filename=rec.filename,
                    sha256=rec.sha256,
                    size_bytes=rec.size_bytes,
                    created_at=rec.created_at,
                    source_library_id=rec.source_library_id,
                    total_records=rec.total_records,
                    valid_records=rec.valid_records,
                    invalid_records=rec.invalid_records,
                )
            )
        summaries.sort(key=lambda item: (item.created_at, item.analog_catalog_id), reverse=True)
        return summaries

    def create_search(
        self,
        record: AnalogSearchRecord,
        *,
        raw_provider_response: bytes | None = None,
    ) -> Path:
        directory = self._search_dir(record.analog_search_id)
        directory.mkdir(parents=True, exist_ok=False)
        if raw_provider_response is not None and record.external_evidence is not None:
            raw_name = self.sanitize_filename(record.external_evidence.raw_response_filename)
            with (directory / raw_name).open("xb") as stream:
                stream.write(raw_provider_response)
        record_path = directory / "record.json"
        with record_path.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(record.model_dump(mode="json"), stream, indent=2, ensure_ascii=False)
            stream.write("\n")
        return record_path

    def load_search(self, analog_search_id: str) -> AnalogSearchRecord:
        path = self._search_dir(analog_search_id) / "record.json"
        try:
            raw = path.read_text(encoding="utf-8")
        except FileNotFoundError as error:
            raise self._not_found("ANALOG_SEARCH_NOT_FOUND", analog_search_id) from error
        return AnalogSearchRecord.model_validate_json(raw)

    def search_raw_response_path(self, analog_search_id: str) -> Path | None:
        record = self.load_search(analog_search_id)
        if record.external_evidence is None:
            return None
        path = self._search_dir(analog_search_id) / self.sanitize_filename(
            record.external_evidence.raw_response_filename
        )
        return path if path.is_file() else None

    def list_searches(self) -> list[AnalogSearchRecord]:
        root = self._base_dir() / "searches"
        if not root.is_dir():
            return []
        records: list[AnalogSearchRecord] = []
        for entry in root.iterdir():
            if not entry.is_dir():
                continue
            try:
                records.append(self.load_search(entry.name))
            except (AnkoraDomainError, OSError, ValueError) as error:
                _LOG.warning(
                    "Skipping unreadable analog expansion record %s: %s (%s)",
                    entry,
                    type(error).__name__,
                    error,
                )
                continue
        records.sort(key=lambda item: (item.created_at, item.analog_search_id), reverse=True)
        return records

    def create_selection(self, record: AnalogSelectionRecord) -> Path:
        directory = self._selection_dir(record.analog_selection_id)
        directory.mkdir(parents=True, exist_ok=False)
        record_path = directory / "record.json"
        with record_path.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(record.model_dump(mode="json"), stream, indent=2, ensure_ascii=False)
            stream.write("\n")
        return record_path

    def load_selection(self, analog_selection_id: str) -> AnalogSelectionRecord:
        path = self._selection_dir(analog_selection_id) / "record.json"
        try:
            raw = path.read_text(encoding="utf-8")
        except FileNotFoundError as error:
            raise self._not_found("ANALOG_SELECTION_NOT_FOUND", analog_selection_id) from error
        return AnalogSelectionRecord.model_validate_json(raw)

    def list_selections(self) -> list[AnalogSelectionRecord]:
        root = self._base_dir() / "selections"
        if not root.is_dir():
            return []
        records: list[AnalogSelectionRecord] = []
        for entry in root.iterdir():
            if not entry.is_dir():
                continue
            try:
                records.append(self.load_selection(entry.name))
            except (AnkoraDomainError, OSError, ValueError) as error:
                _LOG.warning(
                    "Skipping unreadable analog expansion record %s: %s (%s)",
                    entry,
                    type(error).__name__,
                    error,
                )
                continue
        records.sort(key=lambda item: (item.created_at, item.analog_selection_id), reverse=True)
        return records

    def _base_dir(self) -> Path:
        return self._project_root / "derived" / "analog_expansion"

    def _safe_subdir(self, bucket: str, item_id: str, code: str) -> Path:
        try:
            normalized = str(UUID(item_id))
        except ValueError as error:
            raise self._not_found(code, item_id) from error
        resolved = (self._base_dir() / bucket / normalized).resolve()
        if self._root not in resolved.parents:
            raise self._not_found(code, item_id)
        return resolved

    def _catalog_dir(self, analog_catalog_id: str) -> Path:
        return self._safe_subdir("catalogs", analog_catalog_id, "ANALOG_CATALOG_NOT_FOUND")

    def _search_dir(self, analog_search_id: str) -> Path:
        return self._safe_subdir("searches", analog_search_id, "ANALOG_SEARCH_NOT_FOUND")

    def _selection_dir(self, analog_selection_id: str) -> Path:
        return self._safe_subdir("selections", analog_selection_id, "ANALOG_SELECTION_NOT_FOUND")

    @staticmethod
    def _not_found(code: str, item_id: str) -> AnkoraDomainError:
        return AnkoraDomainError(
            code=code,
            stage=_STAGE,
            message=f"Analog expansion artifact '{item_id}' was not found.",
            status_code=404,
            details={"artifact_id": item_id},
        )
