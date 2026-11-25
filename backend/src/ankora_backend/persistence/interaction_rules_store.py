"""Create-only storage for declarative ProLIF pharmacophoric rule sets & evaluations (M4)."""

from __future__ import annotations

import json
import os
from pathlib import Path
from uuid import UUID, uuid4

from ankora_backend.domain.errors import AnkoraDomainError
from ankora_backend.domain.project_context import resolve_project_root
from ankora_backend.schemas.interaction_rules import (
    InteractionRuleEvaluationRecord,
    InteractionRuleSetRecord,
)

_STAGE = "interaction_rules_storage"


class InteractionRuleSetStore:
    """Stores immutable rule sets under `<project_root>/analysis/interaction_rule_sets`."""

    def __init__(self, root: Path, project_id: str | None = None) -> None:
        self._root = root.resolve()
        self._project_root = resolve_project_root(self._root, project_id)

    @classmethod
    def from_environment(cls, project_id: str | None = None) -> InteractionRuleSetStore:
        configured = os.getenv("ANKORA_DATA_DIR")
        return cls(Path(configured) if configured else Path.cwd() / ".ankora-data", project_id)

    def new_rule_set_id(self) -> str:
        return str(uuid4())

    def create(self, record: InteractionRuleSetRecord) -> None:
        directory = self._rule_set_dir(record.rule_set_id)
        directory.mkdir(parents=True, exist_ok=False)
        with (directory / "record.json").open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(record.model_dump(mode="json"), stream, indent=2, ensure_ascii=False)
            stream.write("\n")

    def load(self, rule_set_id: str) -> InteractionRuleSetRecord:
        try:
            raw = (self._rule_set_dir(rule_set_id) / "record.json").read_text(encoding="utf-8")
        except FileNotFoundError as error:
            raise self._not_found(rule_set_id) from error
        return InteractionRuleSetRecord.model_validate_json(raw)

    def list_all(self, *, receptor_id: str | None = None) -> list[InteractionRuleSetRecord]:
        root = self._rule_sets_dir()
        if not root.is_dir():
            return []
        records: list[InteractionRuleSetRecord] = []
        for path in sorted(root.glob("*/record.json")):
            try:
                record = InteractionRuleSetRecord.model_validate_json(
                    path.read_text(encoding="utf-8")
                )
            except (OSError, ValueError):
                continue
            if receptor_id is None or record.receptor_id == receptor_id:
                records.append(record)
        return sorted(records, key=lambda item: (item.created_at, item.rule_set_id), reverse=True)

    def _rule_sets_dir(self) -> Path:
        return self._project_root / "analysis" / "interaction_rule_sets"

    def _rule_set_dir(self, rule_set_id: str) -> Path:
        try:
            normalized = str(UUID(rule_set_id))
        except ValueError as error:
            raise self._not_found(rule_set_id) from error
        path = (self._rule_sets_dir() / normalized).resolve()
        if self._root not in path.parents:
            raise self._not_found(rule_set_id)
        return path

    @staticmethod
    def _not_found(rule_set_id: str) -> AnkoraDomainError:
        return AnkoraDomainError(
            code="INTERACTION_RULE_SET_NOT_FOUND",
            stage=_STAGE,
            message="No interaction rule set exists for this identifier.",
            status_code=404,
            details={"rule_set_id": rule_set_id},
        )


class InteractionRuleEvaluationStore:
    """Stores immutable pose rule evaluations under `analysis/interaction_rule_evaluations`."""

    def __init__(self, root: Path, project_id: str | None = None) -> None:
        self._root = root.resolve()
        self._project_root = resolve_project_root(self._root, project_id)

    @classmethod
    def from_environment(cls, project_id: str | None = None) -> InteractionRuleEvaluationStore:
        configured = os.getenv("ANKORA_DATA_DIR")
        return cls(Path(configured) if configured else Path.cwd() / ".ankora-data", project_id)

    def new_evaluation_id(self) -> str:
        return str(uuid4())

    def create(self, record: InteractionRuleEvaluationRecord) -> None:
        directory = self._evaluation_dir(record.evaluation_id)
        directory.mkdir(parents=True, exist_ok=False)
        with (directory / "record.json").open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(record.model_dump(mode="json"), stream, indent=2, ensure_ascii=False)
            stream.write("\n")

    def load(self, evaluation_id: str) -> InteractionRuleEvaluationRecord:
        try:
            raw = (self._evaluation_dir(evaluation_id) / "record.json").read_text(encoding="utf-8")
        except FileNotFoundError as error:
            raise self._not_found(evaluation_id) from error
        return InteractionRuleEvaluationRecord.model_validate_json(raw)

    def list_for_pose(
        self, catalog_id: str, ligand_id: str, pose_artifact_id: str
    ) -> list[InteractionRuleEvaluationRecord]:
        root = self._evaluations_dir()
        if not root.is_dir():
            return []
        records: list[InteractionRuleEvaluationRecord] = []
        for path in sorted(root.glob("*/record.json")):
            try:
                record = InteractionRuleEvaluationRecord.model_validate_json(
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
            records, key=lambda item: (item.created_at, item.evaluation_id), reverse=True
        )

    def _evaluations_dir(self) -> Path:
        return self._project_root / "analysis" / "interaction_rule_evaluations"

    def _evaluation_dir(self, evaluation_id: str) -> Path:
        try:
            normalized = str(UUID(evaluation_id))
        except ValueError as error:
            raise self._not_found(evaluation_id) from error
        path = (self._evaluations_dir() / normalized).resolve()
        if self._root not in path.parents:
            raise self._not_found(evaluation_id)
        return path

    @staticmethod
    def _not_found(evaluation_id: str) -> AnkoraDomainError:
        return AnkoraDomainError(
            code="INTERACTION_RULE_EVALUATION_NOT_FOUND",
            stage=_STAGE,
            message="No interaction rule evaluation exists for this identifier.",
            status_code=404,
            details={"evaluation_id": evaluation_id},
        )
