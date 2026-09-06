"""Storage for AutoDock4 job state, raw evidence, and immutable pose artifacts."""

import json
import os
import threading
from collections.abc import Sequence
from pathlib import Path
from uuid import UUID, uuid4

from ankora_backend.domain.errors import AnkoraDomainError
from ankora_backend.domain.project_context import resolve_project_root
from ankora_backend.persistence.incremental_batch_store import IncrementalBatchStore
from ankora_backend.schemas.autodock4 import (
    AutoDock4BatchLigandResult,
    AutoDock4BatchRecord,
    AutoDock4DockingJobRecord,
)


def _best_autodock4_result(entry: AutoDock4BatchLigandResult) -> float | None:
    if not entry.clusters:
        return None
    return float(min(cluster.lowest_binding_energy_kcal_mol for cluster in entry.clusters))


class AutoDock4JobStore:
    def __init__(self, root: Path, project_id: str | None = None) -> None:
        self._root = root.resolve()
        self._project_root = resolve_project_root(self._root, project_id)
        self._record_lock = threading.RLock()
        self._batch_state = IncrementalBatchStore(
            record_type=AutoDock4BatchRecord,
            entry_type=AutoDock4BatchLigandResult,
            best_result=_best_autodock4_result,
        )

    @classmethod
    def from_environment(cls, project_id: str | None = None) -> "AutoDock4JobStore":
        configured = os.getenv("ANKORA_DATA_DIR")
        return cls(Path(configured) if configured else Path.cwd() / ".ankora-data", project_id)

    def new_job_id(self) -> str:
        return str(uuid4())

    def create_job(self, record: AutoDock4DockingJobRecord) -> Path:
        directory = self._job_dir(record.job_id)
        directory.mkdir(parents=True, exist_ok=False)
        path = directory / "record.json"
        with path.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(record.model_dump(mode="json"), stream, indent=2, ensure_ascii=False)
            stream.write("\n")
        return directory

    def update_job(self, record: AutoDock4DockingJobRecord) -> None:
        with self._record_lock:
            directory = self._job_dir(record.job_id)
            if not directory.is_dir():
                raise self._not_found(record.job_id)
            temporary = directory / "record.json.tmp"
            with temporary.open("w", encoding="utf-8", newline="\n") as stream:
                json.dump(record.model_dump(mode="json"), stream, indent=2, ensure_ascii=False)
                stream.write("\n")
            os.replace(temporary, directory / "record.json")

    def load_job(self, job_id: str) -> AutoDock4DockingJobRecord:
        with self._record_lock:
            try:
                raw = (self._job_dir(job_id) / "record.json").read_text(encoding="utf-8")
            except FileNotFoundError as error:
                raise self._not_found(job_id) from error
        return AutoDock4DockingJobRecord.model_validate_json(raw)

    def job_directory(self, job_id: str) -> Path:
        return self._job_dir(job_id)

    def output_path(self, job_id: str, filename: str) -> Path:
        if not filename or Path(filename).name != filename:
            raise ValueError("An AutoDock4 artifact filename must be a plain filename")
        return self._job_dir(job_id) / filename

    def write_pose(self, job_id: str, filename: str, content: bytes) -> Path:
        """Poses are create-only: a run's conformation is never rewritten."""
        path = self.output_path(job_id, filename)
        with path.open("xb") as stream:
            stream.write(content)
        return path

    def pose_content_path(self, job_id: str, artifact_id: str) -> Path:
        record = self.load_job(job_id)
        artifact = next(
            (item.artifact for item in record.runs if item.artifact.artifact_id == artifact_id),
            None,
        )
        if artifact is None:
            raise self._not_found(job_id, artifact_id)
        path = self.output_path(job_id, artifact.filename)
        if not path.is_file():
            raise self._not_found(job_id, artifact_id)
        return path

    # --- library campaigns ---

    def list_jobs(self) -> list[AutoDock4DockingJobRecord]:
        """Every single-ligand job this project holds."""
        directory = self._jobs_dir()
        if not directory.is_dir():
            return []
        records: list[AutoDock4DockingJobRecord] = []
        for candidate in sorted(directory.iterdir(), key=lambda item: item.name):
            if not candidate.is_dir():
                continue
            try:
                records.append(self.load_job(candidate.name))
            except (AnkoraDomainError, ValueError):
                continue
        return records

    def new_batch_id(self) -> str:
        return str(uuid4())

    def create_batch(self, record: AutoDock4BatchRecord) -> Path:
        directory = self._batch_dir(record.batch_id)
        directory.mkdir(parents=True, exist_ok=False)
        for entry in record.entries:
            self.batch_ligand_directory(record.batch_id, entry.ligand_id).mkdir(
                parents=True, exist_ok=False
            )
        path = directory / "record.json"
        with path.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(record.model_dump(mode="json"), stream, indent=2, ensure_ascii=False)
            stream.write("\n")
        self._batch_state.create(directory, record)
        return directory

    def update_batch(
        self,
        record: AutoDock4BatchRecord,
        *,
        changed_entries: Sequence[AutoDock4BatchLigandResult] | None = None,
    ) -> AutoDock4BatchRecord:
        with self._record_lock:
            directory = self._batch_dir(record.batch_id)
            if not directory.is_dir():
                raise self._not_found(record.batch_id)
            return self._batch_state.update(directory, record, changed_entries=changed_entries)

    def load_batch(self, batch_id: str) -> AutoDock4BatchRecord:
        with self._record_lock:
            try:
                return self._batch_state.load(self._batch_dir(batch_id))
            except FileNotFoundError as error:
                raise self._not_found(batch_id) from error

    def load_batch_overview(self, batch_id: str) -> AutoDock4BatchRecord:
        try:
            return self._batch_state.load_overview(self._batch_dir(batch_id))
        except FileNotFoundError as error:
            raise self._not_found(batch_id) from error

    def load_batch_summary(self, batch_id: str) -> dict[str, object]:
        try:
            return self._batch_state.load_summary(self._batch_dir(batch_id))
        except FileNotFoundError as error:
            raise self._not_found(batch_id) from error

    def load_batch_entry(self, batch_id: str, ligand_id: str) -> AutoDock4BatchLigandResult | None:
        try:
            return self._batch_state.load_entry(self._batch_dir(batch_id), ligand_id)
        except FileNotFoundError as error:
            raise self._not_found(batch_id) from error

    def update_batch_entry(
        self, batch_id: str, entry: AutoDock4BatchLigandResult
    ) -> AutoDock4BatchLigandResult:
        try:
            return self._batch_state.update_entry(self._batch_dir(batch_id), entry)
        except FileNotFoundError as error:
            raise self._not_found(batch_id) from error

    def batch_ligand_ids_with_status(self, batch_id: str, status: str) -> list[str]:
        try:
            return self._batch_state.ligand_ids_with_status(self._batch_dir(batch_id), status)
        except FileNotFoundError as error:
            raise self._not_found(batch_id) from error

    def page_batch_entries(
        self,
        batch_id: str,
        *,
        offset: int,
        limit: int,
        status: str | None = None,
        search: str | None = None,
    ) -> tuple[list[AutoDock4BatchLigandResult], int]:
        try:
            return self._batch_state.page(
                self._batch_dir(batch_id),
                offset=offset,
                limit=limit,
                status=status,
                search=search,
            )
        except FileNotFoundError as error:
            raise self._not_found(batch_id) from error

    def list_batches(self) -> list[AutoDock4BatchRecord]:
        """Every campaign persisted for this project, newest last.

        A campaign outlives the session that started it, so the interface can
        reconnect to one instead of only remembering what it launched itself.
        """
        directory = self._batches_dir()
        if not directory.is_dir():
            return []
        records: list[AutoDock4BatchRecord] = []
        for candidate in sorted(directory.iterdir(), key=lambda item: item.name):
            if not candidate.is_dir():
                continue
            try:
                records.append(self.load_batch(candidate.name))
            except (AnkoraDomainError, ValueError):
                continue
        return records

    def list_batch_overviews(self) -> list[AutoDock4BatchRecord]:
        directory = self._batches_dir()
        if not directory.is_dir():
            return []
        records: list[AutoDock4BatchRecord] = []
        for candidate in sorted(directory.iterdir(), key=lambda item: item.name):
            if not candidate.is_dir():
                continue
            try:
                records.append(self.load_batch_overview(candidate.name))
            except (AnkoraDomainError, ValueError):
                continue
        return records

    def batch_ligand_directory(self, batch_id: str, ligand_id: str) -> Path:
        try:
            normalized = str(UUID(ligand_id))
        except ValueError as error:
            raise self._not_found(batch_id, ligand_id) from error
        path = self._batch_dir(batch_id) / "ligands" / normalized
        resolved = path.resolve()
        if self._root not in resolved.parents:
            raise self._not_found(batch_id, ligand_id)
        return resolved

    def write_batch_pose(
        self, batch_id: str, ligand_id: str, filename: str, content: bytes
    ) -> Path:
        if not filename or Path(filename).name != filename:
            raise ValueError("An AutoDock4 artifact filename must be a plain filename")
        path = self.batch_ligand_directory(batch_id, ligand_id) / filename
        with path.open("xb") as stream:
            stream.write(content)
        return path

    def batch_pose_content_path(self, batch_id: str, ligand_id: str, artifact_id: str) -> Path:
        entry = self.load_batch_entry(batch_id, ligand_id)
        artifact = next(
            (
                item.artifact
                for item in (entry.runs if entry is not None else [])
                if item.artifact.artifact_id == artifact_id
            ),
            None,
        )
        if artifact is None:
            raise self._not_found(batch_id, artifact_id)
        path = self.batch_ligand_directory(batch_id, ligand_id) / artifact.filename
        if not path.is_file():
            raise self._not_found(batch_id, artifact_id)
        return path

    def _batches_dir(self) -> Path:
        path = self._project_root / "results" / "autodock4_batches"
        resolved = path.resolve()
        if self._root not in resolved.parents and resolved != self._root:
            raise self._not_found("autodock4_batches")
        return resolved

    def _batch_dir(self, batch_id: str) -> Path:
        try:
            normalized = str(UUID(batch_id))
        except ValueError as error:
            raise self._not_found(batch_id) from error
        path = self._batches_dir() / normalized
        resolved = path.resolve()
        if self._root not in resolved.parents:
            raise self._not_found(batch_id)
        return resolved

    def _jobs_dir(self) -> Path:
        path = self._project_root / "results" / "autodock4_jobs"
        resolved = path.resolve()
        if self._root not in resolved.parents and resolved != self._root:
            raise self._not_found("autodock4_jobs")
        return resolved

    def _job_dir(self, job_id: str) -> Path:
        try:
            normalized = str(UUID(job_id))
        except ValueError as error:
            raise self._not_found(job_id) from error
        path = self._jobs_dir() / normalized
        resolved = path.resolve()
        if self._root not in resolved.parents:
            raise self._not_found(job_id)
        return resolved

    @staticmethod
    def _not_found(job_id: str, artifact_id: str | None = None) -> AnkoraDomainError:
        details: dict[str, object] = {"job_id": job_id}
        if artifact_id is not None:
            details["artifact_id"] = artifact_id
        return AnkoraDomainError(
            code="AUTODOCK4_JOB_NOT_FOUND",
            stage="autodock4_storage",
            message="The requested AutoDock4 job or pose is not available in this project.",
            status_code=404,
            details=details,
        )
