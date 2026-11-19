"""Create-only storage for ADR-030 consensus runs and hash-locked reference panels (M5)."""

from __future__ import annotations

import json
import os
from pathlib import Path
from uuid import UUID, uuid4

from ankora_backend.domain.errors import AnkoraDomainError
from ankora_backend.domain.project_context import resolve_project_root
from ankora_backend.schemas.consensus import ConsensusRunRecord, ReferencePanelArtifact

_STAGE = "consensus_storage"


class ConsensusArtifactStore:
    """Stores immutable consensus runs and reference panels under `<project_root>/analysis/`."""

    def __init__(self, root: Path, project_id: str | None = None) -> None:
        self._root = root.resolve()
        self._project_root = resolve_project_root(self._root, project_id)

    @classmethod
    def from_environment(cls, project_id: str | None = None) -> ConsensusArtifactStore:
        configured = os.getenv("ANKORA_DATA_DIR")
        return cls(Path(configured) if configured else Path.cwd() / ".ankora-data", project_id)

    def new_consensus_id(self) -> str:
        return str(uuid4())

    def new_panel_id(self) -> str:
        return str(uuid4())

    def create_panel(self, panel: ReferencePanelArtifact) -> None:
        directory = self._panel_dir(panel.panel_id)
        directory.mkdir(parents=True, exist_ok=False)
        with (directory / "record.json").open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(panel.model_dump(mode="json"), stream, indent=2, ensure_ascii=False)
            stream.write("\n")

    def load_panel(self, panel_id: str) -> ReferencePanelArtifact:
        try:
            raw = (self._panel_dir(panel_id) / "record.json").read_text(encoding="utf-8")
        except FileNotFoundError as error:
            raise self._panel_not_found(panel_id) from error
        return ReferencePanelArtifact.model_validate_json(raw)

    def list_panels(self) -> list[ReferencePanelArtifact]:
        root = self._panels_dir()
        if not root.is_dir():
            return []
        panels: list[ReferencePanelArtifact] = []
        for path in sorted(root.glob("*/record.json")):
            try:
                panels.append(
                    ReferencePanelArtifact.model_validate_json(path.read_text(encoding="utf-8"))
                )
            except (OSError, ValueError):
                continue
        return sorted(panels, key=lambda item: (item.created_at, item.panel_id), reverse=True)

    def create_run(self, record: ConsensusRunRecord) -> None:
        directory = self._run_dir(record.consensus_id)
        directory.mkdir(parents=True, exist_ok=False)
        with (directory / "record.json").open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(record.model_dump(mode="json"), stream, indent=2, ensure_ascii=False)
            stream.write("\n")

    def load_run(self, consensus_id: str) -> ConsensusRunRecord:
        try:
            raw = (self._run_dir(consensus_id) / "record.json").read_text(encoding="utf-8")
        except FileNotFoundError as error:
            raise self._run_not_found(consensus_id) from error
        return ConsensusRunRecord.model_validate_json(raw)

    def list_runs(self) -> list[ConsensusRunRecord]:
        root = self._runs_dir()
        if not root.is_dir():
            return []
        records: list[ConsensusRunRecord] = []
        for path in sorted(root.glob("*/record.json")):
            try:
                records.append(
                    ConsensusRunRecord.model_validate_json(path.read_text(encoding="utf-8"))
                )
            except (OSError, ValueError):
                continue
        return sorted(records, key=lambda item: (item.created_at, item.consensus_id), reverse=True)

    def _runs_dir(self) -> Path:
        return self._project_root / "analysis" / "consensus"

    def _panels_dir(self) -> Path:
        return self._project_root / "analysis" / "consensus_panels"

    def _run_dir(self, consensus_id: str) -> Path:
        try:
            normalized = str(UUID(consensus_id))
        except ValueError as error:
            raise self._run_not_found(consensus_id) from error
        path = (self._runs_dir() / normalized).resolve()
        if self._root not in path.parents:
            raise self._run_not_found(consensus_id)
        return path

    def _panel_dir(self, panel_id: str) -> Path:
        try:
            normalized = str(UUID(panel_id))
        except ValueError as error:
            raise self._panel_not_found(panel_id) from error
        path = (self._panels_dir() / normalized).resolve()
        if self._root not in path.parents:
            raise self._panel_not_found(panel_id)
        return path

    @staticmethod
    def _run_not_found(consensus_id: str) -> AnkoraDomainError:
        return AnkoraDomainError(
            code="CONSENSUS_RUN_NOT_FOUND",
            stage=_STAGE,
            message="No consensus prioritization run exists for this identifier.",
            status_code=404,
            details={"consensus_id": consensus_id},
        )

    @staticmethod
    def _panel_not_found(panel_id: str) -> AnkoraDomainError:
        return AnkoraDomainError(
            code="CONSENSUS_REFERENCE_PANEL_NOT_FOUND",
            stage=_STAGE,
            message="No consensus reference panel exists for this identifier.",
            status_code=404,
            details={"panel_id": panel_id},
        )
