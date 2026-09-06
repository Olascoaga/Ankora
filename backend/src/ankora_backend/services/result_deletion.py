"""Recoverable, all-or-nothing removal of durable result records.

Results are large derivative trees with later M7/M9 records pointing back to
them.  Deleting only ``record.json`` or one pose would leave a scientifically
misleading half-campaign, so this service moves the complete authoritative
directory and every dependent validation/interaction record together.  Shared
inputs and independently useful export bundles deliberately stay in place.
"""

import json
import os
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from ankora_backend.domain.errors import AnkoraDomainError
from ankora_backend.domain.project_context import resolve_project_root
from ankora_backend.schemas.results_catalog import (
    CatalogEntry,
    TrashedResultCampaign,
    TrashResultCampaignsRequest,
    TrashResultCampaignsResponse,
)
from ankora_backend.services.result_catalog import ResultCatalogService

_STAGE = "results_deletion"
_TRASH_LOCK = threading.RLock()
_TERMINAL_STATUSES = {"completed", "failed", "canceled"}
_RESULT_DIRECTORIES = {
    "vina_job": "docking",
    "vina_batch": "docking_batches",
    "autodock4_job": "autodock4_jobs",
    "autodock4_batch": "autodock4_batches",
    "autodock_gpu_job": "autodock_gpu_jobs",
    "autodock_gpu_batch": "autodock_gpu_batches",
}


@dataclass(frozen=True)
class _Move:
    source: Path
    destination: Path
    category: str
    identity: str


class ResultDeletionService:
    def __init__(self, *, root: Path, catalog: ResultCatalogService) -> None:
        self._root = root.resolve()
        self._project = resolve_project_root(self._root)
        self._catalog = catalog

    @classmethod
    def from_environment(cls) -> "ResultDeletionService":
        configured = os.getenv("ANKORA_DATA_DIR")
        root = Path(configured) if configured else Path.cwd() / ".ankora-data"
        return cls(root=root, catalog=ResultCatalogService.from_environment())

    def trash(self, request: TrashResultCampaignsRequest) -> TrashResultCampaignsResponse:
        if not request.acknowledge_removal:
            raise AnkoraDomainError(
                code="RESULT_TRASH_NOT_ACKNOWLEDGED",
                stage=_STAGE,
                message="Confirm the exact result selection before removing it.",
                status_code=422,
                details={"catalog_ids": request.catalog_ids},
            )
        if len(set(request.catalog_ids)) != len(request.catalog_ids):
            raise AnkoraDomainError(
                code="RESULT_TRASH_DUPLICATE_ID",
                stage=_STAGE,
                message="Each result can appear only once in a removal operation.",
                status_code=422,
                details={"catalog_ids": request.catalog_ids},
            )

        with _TRASH_LOCK:
            # Resolve every record before moving any of them. One missing or
            # active result rejects the complete group rather than producing a
            # partial deletion that the user did not ask for.
            entries = [self._catalog.get_campaign(item) for item in request.catalog_ids]
            active = [entry for entry in entries if entry.status not in _TERMINAL_STATUSES]
            if active:
                raise AnkoraDomainError(
                    code="RESULT_TRASH_ACTIVE",
                    stage=_STAGE,
                    message="Finish or cancel active results before removing them.",
                    status_code=409,
                    details={"catalog_ids": [entry.catalog_id for entry in active]},
                )

            operation_id = str(uuid4())
            trashed_at = datetime.now(UTC)
            operation_dir = self._trash_root() / operation_id
            moves = self._campaign_moves(entries, operation_dir)
            interaction_moves = self._interaction_moves(set(request.catalog_ids), operation_dir)
            validation_moves = self._validation_moves(set(request.catalog_ids), operation_dir)
            moves.extend(interaction_moves)
            moves.extend(validation_moves)

            operation_dir.mkdir(parents=True, exist_ok=False)
            manifest = {
                "operation_id": operation_id,
                "status": "moving",
                "trashed_at": trashed_at.isoformat(),
                "campaigns": [entry.model_dump(mode="json") for entry in entries],
                "moves": [self._move_manifest(item) for item in moves],
                "exports_preserved": True,
            }
            self._write_manifest(operation_dir, manifest)

            moved: list[_Move] = []
            try:
                for item in moves:
                    item.destination.parent.mkdir(parents=True, exist_ok=True)
                    os.replace(item.source, item.destination)
                    moved.append(item)
                manifest["status"] = "completed"
                self._write_manifest(operation_dir, manifest)
            except OSError as error:
                rollback_errors: list[str] = []
                for item in reversed(moved):
                    try:
                        item.source.parent.mkdir(parents=True, exist_ok=True)
                        os.replace(item.destination, item.source)
                    except OSError as rollback_error:
                        rollback_errors.append(str(rollback_error))
                manifest.update(
                    {
                        "status": "rollback_incomplete" if rollback_errors else "rolled_back",
                        "error": str(error),
                        "rollback_errors": rollback_errors,
                    }
                )
                self._write_manifest(operation_dir, manifest)
                raise AnkoraDomainError(
                    code="RESULT_TRASH_FAILED",
                    stage=_STAGE,
                    message="Ankora could not remove the complete result selection.",
                    status_code=500,
                    details={
                        "operation_id": operation_id,
                        "rolled_back": not rollback_errors,
                        "error": str(error),
                    },
                ) from error

            return TrashResultCampaignsResponse(
                operation_id=operation_id,
                trashed_at=trashed_at,
                campaigns=[
                    TrashedResultCampaign(
                        catalog_id=entry.catalog_id,
                        engine_label=entry.engine_label,
                        status=entry.status,
                    )
                    for entry in entries
                ],
                interaction_analysis_count=len(interaction_moves),
                redocking_validation_count=len(validation_moves),
                exports_preserved=True,
                recoverable=True,
            )

    def _campaign_moves(self, entries: list[CatalogEntry], operation_dir: Path) -> list[_Move]:
        moves: list[_Move] = []
        for entry in entries:
            directory_name = _RESULT_DIRECTORIES.get(entry.engine_key)
            if directory_name is None:
                raise AnkoraDomainError(
                    code="RESULT_CATALOG_ENGINE_UNKNOWN",
                    stage=_STAGE,
                    message="Ankora cannot remove this kind of result record.",
                    status_code=422,
                    details={"engine_key": entry.engine_key},
                )
            record_id = self._uuid(entry.record_id)
            source = self._safe(self._project / "results" / directory_name / record_id)
            if not source.is_dir():
                raise AnkoraDomainError(
                    code="RESULT_CATALOG_NOT_FOUND",
                    stage=_STAGE,
                    message="A selected result is no longer available in this project.",
                    status_code=404,
                    details={"catalog_id": entry.catalog_id},
                )
            moves.append(
                _Move(
                    source=source,
                    destination=operation_dir / "campaigns" / entry.engine_key / record_id,
                    category="campaign",
                    identity=entry.catalog_id,
                )
            )
        return moves

    def _interaction_moves(self, catalog_ids: set[str], operation_dir: Path) -> list[_Move]:
        return self._dependent_moves(
            source_root=self._project / "analysis" / "pose_interactions",
            destination_root=operation_dir / "dependencies" / "pose_interactions",
            category="pose_interaction",
            matches=lambda data: data.get("catalog_id") in catalog_ids,
        )

    def _validation_moves(self, catalog_ids: set[str], operation_dir: Path) -> list[_Move]:
        return self._dependent_moves(
            source_root=self._project / "validation" / "redocking",
            destination_root=operation_dir / "dependencies" / "redocking",
            category="redocking_validation",
            matches=lambda data: (
                f"{data.get('source_kind', '')}:{data.get('source_id', '')}" in catalog_ids
            ),
        )

    def _dependent_moves(
        self,
        *,
        source_root: Path,
        destination_root: Path,
        category: str,
        matches: Callable[[dict[str, Any]], bool],
    ) -> list[_Move]:
        if not source_root.is_dir():
            return []
        moves: list[_Move] = []
        for record_path in sorted(source_root.glob("*/record.json")):
            try:
                data = json.loads(record_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if not isinstance(data, dict) or not matches(data):
                continue
            identity = self._uuid(record_path.parent.name)
            source = self._safe(record_path.parent)
            moves.append(
                _Move(
                    source=source,
                    destination=destination_root / identity,
                    category=category,
                    identity=identity,
                )
            )
        return moves

    def _trash_root(self) -> Path:
        return self._safe(self._project / "trash" / "result_campaigns")

    def _safe(self, path: Path) -> Path:
        resolved = path.resolve()
        if resolved != self._root and self._root not in resolved.parents:
            raise AnkoraDomainError(
                code="RESULT_TRASH_PATH_INVALID",
                stage=_STAGE,
                message="A result path escaped the configured Ankora data directory.",
                status_code=422,
                details={"path": str(path)},
            )
        return resolved

    @staticmethod
    def _uuid(value: str) -> str:
        try:
            return str(UUID(value))
        except ValueError as error:
            raise AnkoraDomainError(
                code="RESULT_TRASH_ID_INVALID",
                stage=_STAGE,
                message="A result removal identifier is not a valid UUID.",
                status_code=422,
                details={"identifier": value},
            ) from error

    def _move_manifest(self, item: _Move) -> dict[str, str]:
        return {
            "category": item.category,
            "identity": item.identity,
            "original_path": str(item.source.relative_to(self._root)),
            "trash_path": str(item.destination.relative_to(self._root)),
        }

    @staticmethod
    def _write_manifest(directory: Path, payload: dict[str, Any]) -> None:
        temporary = directory / "operation.json.tmp"
        with temporary.open("w", encoding="utf-8", newline="\n") as stream:
            json.dump(payload, stream, indent=2, ensure_ascii=False)
            stream.write("\n")
        os.replace(temporary, directory / "operation.json")
