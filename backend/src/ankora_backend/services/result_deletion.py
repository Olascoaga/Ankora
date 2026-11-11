"""Recoverable, all-or-nothing removal of durable result records.

Results are large derivative trees with later M7/M9 records pointing back to
them.  Deleting only ``record.json`` or one pose would leave a scientifically
misleading half-campaign, so this service moves the complete authoritative
directory and every dependent validation/interaction record together.  Shared
inputs and independently useful export bundles deliberately stay in place.
"""

import json
import os
import sqlite3
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from ankora_backend.domain.errors import AnkoraDomainError
from ankora_backend.domain.project_context import resolve_project_root
from ankora_backend.persistence.gnina_screening_store import GninaScreeningStore
from ankora_backend.schemas.results_catalog import (
    CatalogEntry,
    ResultMode,
    ScoringFamily,
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
    "gnina_job": "gnina_jobs",
    "gnina_screening": "gnina_screening_campaigns",
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
            entries = [self._resolve_entry(item) for item in request.catalog_ids]
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
            moves, child_catalog_ids = self._campaign_moves(entries, operation_dir)
            dependent_ids = set(request.catalog_ids) | child_catalog_ids
            interaction_moves = self._interaction_moves(dependent_ids, operation_dir)
            validation_moves = self._validation_moves(dependent_ids, operation_dir)
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

    def _resolve_entry(self, catalog_id: str) -> CatalogEntry:
        try:
            entry = self._catalog.get_campaign(catalog_id)
        except AnkoraDomainError as error:
            if catalog_id.startswith("gnina_screening:") and error.code in {
                "GNINA_SCREENING_JOB_MISMATCH",
                "GNINA_POSE_INTEGRITY_FAILED",
            }:
                entry = self._fallback_gnina_screening_entry(catalog_id)
            else:
                raise
        if entry.engine_key == "gnina_job":
            self._refuse_owned_child_job(entry)
        return entry

    def _fallback_gnina_screening_entry(self, catalog_id: str) -> CatalogEntry:
        record_id = self._uuid(catalog_id.partition(":")[2])
        store = GninaScreeningStore(self._root)
        progress = store.load_progress(record_id)
        origin = store.original_selection(record_id)
        return CatalogEntry(
            catalog_id=catalog_id,
            engine_key="gnina_screening",
            record_id=record_id,
            mode=ResultMode.SCREENING,
            scoring_family=ScoringFamily.GNINA,
            backend=origin.request.parameters.compute,
            engine_label=f"GNINA {origin.tool.version}",
            engine_version=origin.tool.version,
            executable_sha256=origin.tool.sha256,
            status=progress.status.value,
            created_at=origin.created_at,
            completed_at=progress.completed_at,
            receptor_id=origin.request.receptor_id,
            binding_site_id=origin.request.binding_site_id,
            library_id=origin.request.library_id,
            filter_run_id=origin.request.filter_run_id,
            selected_count=progress.selected_count,
            succeeded_count=progress.succeeded_count,
            failed_count=progress.failed_count,
            canceled_count=progress.canceled_count,
        )

    def _refuse_owned_child_job(self, entry: CatalogEntry) -> None:
        record_id = self._uuid(entry.record_id)
        record_path = self._safe(
            self._project / "results" / "gnina_jobs" / record_id / "record.json"
        )
        if not record_path.is_file():
            return
        try:
            data = json.loads(record_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        owning = data.get("screening_campaign_id") if isinstance(data, dict) else None
        if owning:
            raise AnkoraDomainError(
                code="RESULT_TRASH_CHILD_OWNED",
                stage=_STAGE,
                message=(
                    "Remove the owning GNINA screening campaign rather than one of its "
                    "molecule jobs."
                ),
                status_code=409,
                details={
                    "catalog_id": entry.catalog_id,
                    "screening_campaign_id": str(owning),
                },
            )

    def _campaign_moves(
        self, entries: list[CatalogEntry], operation_dir: Path
    ) -> tuple[list[_Move], set[str]]:
        moves: list[_Move] = []
        child_catalog_ids: set[str] = set()
        seen_sources: set[Path] = set()
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
            seen_sources.add(source)
            if entry.engine_key == "gnina_screening":
                for job_id in self._gnina_screening_child_job_ids(record_id, source):
                    child_source = self._safe(self._project / "results" / "gnina_jobs" / job_id)
                    if not child_source.is_dir() or child_source in seen_sources:
                        continue
                    seen_sources.add(child_source)
                    child_catalog_ids.add(f"gnina_job:{job_id}")
                    moves.append(
                        _Move(
                            source=child_source,
                            destination=(
                                operation_dir
                                / "campaigns"
                                / "gnina_screening_jobs"
                                / record_id
                                / job_id
                            ),
                            category="campaign_child_job",
                            identity=f"gnina_job:{job_id}",
                        )
                    )
        return moves, child_catalog_ids

    def _gnina_screening_child_job_ids(self, campaign_id: str, campaign_dir: Path) -> list[str]:
        found: set[str] = set()
        db_path = campaign_dir / "campaign_state.sqlite3"
        if db_path.is_file():
            try:
                with sqlite3.connect(db_path) as connection:
                    rows = connection.execute("SELECT payload_json FROM entries").fetchall()
                for (raw,) in rows:
                    payload = json.loads(str(raw))
                    job_id = payload.get("gnina_job_id") if isinstance(payload, dict) else None
                    if isinstance(job_id, str) and job_id:
                        found.add(self._uuid(job_id))
            except (sqlite3.Error, OSError, ValueError):
                pass
        jobs_root = self._project / "results" / "gnina_jobs"
        if jobs_root.is_dir():
            for record_path in sorted(jobs_root.glob("*/record.json")):
                try:
                    data = json.loads(record_path.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    continue
                if isinstance(data, dict) and data.get("screening_campaign_id") == campaign_id:
                    found.add(self._uuid(record_path.parent.name))
        return sorted(found)

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
