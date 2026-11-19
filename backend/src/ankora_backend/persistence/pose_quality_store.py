"""Create-only storage for coupled pose-quality assessments (M3)."""

from __future__ import annotations

import json
import os
from pathlib import Path
from uuid import UUID, uuid4

from ankora_backend.domain.errors import AnkoraDomainError
from ankora_backend.domain.project_context import resolve_project_root
from ankora_backend.schemas.pose_quality import PoseQualityRecord

_STAGE = "pose_quality_storage"


class PoseQualityStore:
    """Stores immutable pose-quality records under `<project_root>/analysis/pose_quality`."""

    def __init__(self, root: Path, project_id: str | None = None) -> None:
        self._root = root.resolve()
        self._project_root = resolve_project_root(self._root, project_id)

    @classmethod
    def from_environment(cls, project_id: str | None = None) -> PoseQualityStore:
        configured = os.getenv("ANKORA_DATA_DIR")
        return cls(Path(configured) if configured else Path.cwd() / ".ankora-data", project_id)

    def new_assessment_id(self) -> str:
        return str(uuid4())

    def create(self, record: PoseQualityRecord) -> None:
        directory = self._assessment_dir(record.assessment_id)
        directory.mkdir(parents=True, exist_ok=False)
        with (directory / "record.json").open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(record.model_dump(mode="json"), stream, indent=2, ensure_ascii=False)
            stream.write("\n")

    def load(self, assessment_id: str) -> PoseQualityRecord:
        try:
            raw = (self._assessment_dir(assessment_id) / "record.json").read_text(encoding="utf-8")
        except FileNotFoundError as error:
            raise self._not_found(assessment_id) from error
        return PoseQualityRecord.model_validate_json(raw)

    def list_for_pose(
        self, catalog_id: str, ligand_id: str, pose_artifact_id: str
    ) -> list[PoseQualityRecord]:
        root = self._assessments_dir()
        if not root.is_dir():
            return []
        records: list[PoseQualityRecord] = []
        for path in sorted(root.glob("*/record.json")):
            try:
                record = PoseQualityRecord.model_validate_json(
                    path.read_text(encoding="utf-8")
                )
            except (OSError, ValueError):
                continue
            if (
                record.catalog_id == catalog_id
                and record.ligand_id == ligand_id
                and record.pose.artifact_id == pose_artifact_id
            ):
                records.append(record)
        return sorted(
            records, key=lambda item: (item.created_at, item.assessment_id), reverse=True
        )

    def _assessments_dir(self) -> Path:
        return self._project_root / "analysis" / "pose_quality"

    def _assessment_dir(self, assessment_id: str) -> Path:
        try:
            normalized = str(UUID(assessment_id))
        except ValueError as error:
            raise self._not_found(assessment_id) from error
        path = (self._assessments_dir() / normalized).resolve()
        if self._root not in path.parents:
            raise self._not_found(assessment_id)
        return path

    @staticmethod
    def _not_found(assessment_id: str) -> AnkoraDomainError:
        return AnkoraDomainError(
            code="POSE_QUALITY_ASSESSMENT_NOT_FOUND",
            stage=_STAGE,
            message="No pose quality assessment exists for this identifier.",
            status_code=404,
            details={"assessment_id": assessment_id},
        )
