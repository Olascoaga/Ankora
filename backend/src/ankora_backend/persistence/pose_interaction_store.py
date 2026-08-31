"""Create-only storage for pose interaction analyses (M9)."""

import json
import os
from pathlib import Path
from uuid import UUID, uuid4

from ankora_backend.domain.errors import AnkoraDomainError
from ankora_backend.schemas.pose_interactions import InteractionAnalysisRecord

_STAGE = "pose_interaction_storage"


class PoseInteractionStore:
    def __init__(self, root: Path) -> None:
        self._root = root.resolve()

    @classmethod
    def from_environment(cls) -> "PoseInteractionStore":
        configured = os.getenv("ANKORA_DATA_DIR")
        return cls(Path(configured) if configured else Path.cwd() / ".ankora-data")

    def new_analysis_id(self) -> str:
        return str(uuid4())

    def create(self, record: InteractionAnalysisRecord) -> None:
        directory = self._analysis_dir(record.analysis_id)
        directory.mkdir(parents=True, exist_ok=False)
        with (directory / "record.json").open(
            "x", encoding="utf-8", newline="\n"
        ) as stream:
            json.dump(record.model_dump(mode="json"), stream, indent=2, ensure_ascii=False)
            stream.write("\n")

    def load(self, analysis_id: str) -> InteractionAnalysisRecord:
        try:
            raw = (self._analysis_dir(analysis_id) / "record.json").read_text(
                encoding="utf-8"
            )
        except FileNotFoundError as error:
            raise self._not_found(analysis_id) from error
        return InteractionAnalysisRecord.model_validate_json(raw)

    def list_for_pose(
        self, catalog_id: str, ligand_id: str, pose_artifact_id: str
    ) -> list[InteractionAnalysisRecord]:
        root = self._analyses_dir()
        if not root.is_dir():
            return []
        records: list[InteractionAnalysisRecord] = []
        for path in sorted(root.glob("*/record.json")):
            try:
                record = InteractionAnalysisRecord.model_validate_json(
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
        return sorted(records, key=lambda item: (item.created_at, item.analysis_id), reverse=True)

    def _analyses_dir(self) -> Path:
        return self._root / "projects" / "default" / "analysis" / "pose_interactions"

    def _analysis_dir(self, analysis_id: str) -> Path:
        try:
            normalized = str(UUID(analysis_id))
        except ValueError as error:
            raise self._not_found(analysis_id) from error
        path = (self._analyses_dir() / normalized).resolve()
        if self._root not in path.parents:
            raise self._not_found(analysis_id)
        return path

    @staticmethod
    def _not_found(analysis_id: str) -> AnkoraDomainError:
        return AnkoraDomainError(
            code="POSE_INTERACTION_ANALYSIS_NOT_FOUND",
            stage=_STAGE,
            message="No pose interaction analysis exists for this identifier.",
            status_code=404,
            details={"analysis_id": analysis_id},
        )
