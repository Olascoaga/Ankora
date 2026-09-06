"""Storage for AutoDock-GPU job state, raw evidence, and pose artifacts.

Separate from the CPU store rather than shared, because a GPU result is a
different execution of the same science and must never be served from the same
listing as a CPU one. The layout and the create-only discipline are the same.
"""

import json
import os
import threading
from collections.abc import Sequence
from pathlib import Path
from uuid import UUID, uuid4

from ankora_backend.domain.errors import AnkoraDomainError
from ankora_backend.domain.project_context import resolve_project_root
from ankora_backend.persistence.incremental_batch_store import IncrementalBatchStore
from ankora_backend.schemas.autodock_gpu import (
    AutoDockGpuBatchLigandResult,
    AutoDockGpuBatchRecord,
    AutoDockGpuDockingJobRecord,
)

_STAGE = "autodock_gpu_storage"


def _best_autodock_gpu_result(
    entry: AutoDockGpuBatchLigandResult,
) -> float | None:
    if not entry.clusters:
        return None
    return float(min(cluster.lowest_binding_energy_kcal_mol for cluster in entry.clusters))


class AutoDockGpuJobStore:
    def __init__(self, root: Path, project_id: str | None = None) -> None:
        self._root = root.resolve()
        self._project_root = resolve_project_root(self._root, project_id)
        self._record_lock = threading.RLock()
        self._batch_state = IncrementalBatchStore(
            record_type=AutoDockGpuBatchRecord,
            entry_type=AutoDockGpuBatchLigandResult,
            best_result=_best_autodock_gpu_result,
        )

    @classmethod
    def from_environment(cls, project_id: str | None = None) -> "AutoDockGpuJobStore":
        configured = os.getenv("ANKORA_DATA_DIR")
        return cls(Path(configured) if configured else Path.cwd() / ".ankora-data", project_id)

    def new_job_id(self) -> str:
        return str(uuid4())

    def create_job(self, record: AutoDockGpuDockingJobRecord) -> Path:
        directory = self._job_dir(record.job_id)
        directory.mkdir(parents=True, exist_ok=False)
        path = directory / "record.json"
        with path.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(record.model_dump(mode="json"), stream, indent=2, ensure_ascii=False)
            stream.write("\n")
        return directory

    def update_job(self, record: AutoDockGpuDockingJobRecord) -> None:
        with self._record_lock:
            directory = self._job_dir(record.job_id)
            if not directory.is_dir():
                raise self._not_found(record.job_id)
            temporary = directory / "record.json.tmp"
            with temporary.open("w", encoding="utf-8", newline="\n") as stream:
                json.dump(record.model_dump(mode="json"), stream, indent=2, ensure_ascii=False)
                stream.write("\n")
            os.replace(temporary, directory / "record.json")

    def load_job(self, job_id: str) -> AutoDockGpuDockingJobRecord:
        with self._record_lock:
            try:
                raw = (self._job_dir(job_id) / "record.json").read_text(encoding="utf-8")
            except FileNotFoundError as error:
                raise self._not_found(job_id) from error
        return AutoDockGpuDockingJobRecord.model_validate_json(raw)

    def job_directory(self, job_id: str) -> Path:
        return self._job_dir(job_id)

    def output_path(self, job_id: str, filename: str) -> Path:
        if not filename or Path(filename).name != filename:
            raise ValueError("An AutoDock-GPU artifact filename must be a plain filename")
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

    def list_jobs(self) -> list[AutoDockGpuDockingJobRecord]:
        """Every single-ligand job this project holds."""
        directory = self._project_root / "results" / "autodock_gpu_jobs"
        if not directory.is_dir():
            return []
        records: list[AutoDockGpuDockingJobRecord] = []
        for candidate in sorted(directory.iterdir(), key=lambda item: item.name):
            if not candidate.is_dir():
                continue
            try:
                records.append(self.load_job(candidate.name))
            except (AnkoraDomainError, ValueError):
                continue
        return records

    def _job_dir(self, job_id: str) -> Path:
        try:
            normalized = str(UUID(job_id))
        except ValueError as error:
            raise self._not_found(job_id) from error
        path = self._project_root / "results" / "autodock_gpu_jobs" / normalized
        resolved = path.resolve()
        if self._root not in resolved.parents:
            raise self._not_found(job_id)
        return resolved

    @staticmethod
    def _not_found(job_id: str, artifact_id: str | None = None) -> AnkoraDomainError:
        return AnkoraDomainError(
            code="AUTODOCK_GPU_JOB_NOT_FOUND",
            stage=_STAGE,
            message="No AutoDock-GPU job artifact exists for this identifier.",
            status_code=404,
            details={"job_id": job_id, "artifact_id": artifact_id},
        )

    # --- library campaigns ---

    def new_batch_id(self) -> str:
        return str(uuid4())

    def create_batch(self, record: AutoDockGpuBatchRecord) -> Path:
        directory = self._batch_dir(record.batch_id)
        directory.mkdir(parents=True, exist_ok=False)
        path = directory / "record.json"
        with path.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(record.model_dump(mode="json"), stream, indent=2, ensure_ascii=False)
            stream.write("\n")
        self._batch_state.create(directory, record)
        return directory

    def update_batch(
        self,
        record: AutoDockGpuBatchRecord,
        *,
        changed_entries: Sequence[AutoDockGpuBatchLigandResult] | None = None,
    ) -> AutoDockGpuBatchRecord:
        with self._record_lock:
            directory = self._batch_dir(record.batch_id)
            if not directory.is_dir():
                raise self._not_found(record.batch_id)
            return self._batch_state.update(directory, record, changed_entries=changed_entries)

    def load_batch(self, batch_id: str) -> AutoDockGpuBatchRecord:
        with self._record_lock:
            try:
                return self._batch_state.load(self._batch_dir(batch_id))
            except FileNotFoundError as error:
                raise self._not_found(batch_id) from error

    def load_batch_overview(self, batch_id: str) -> AutoDockGpuBatchRecord:
        try:
            return self._batch_state.load_overview(self._batch_dir(batch_id))
        except FileNotFoundError as error:
            raise self._not_found(batch_id) from error

    def load_batch_summary(self, batch_id: str) -> dict[str, object]:
        try:
            return self._batch_state.load_summary(self._batch_dir(batch_id))
        except FileNotFoundError as error:
            raise self._not_found(batch_id) from error

    def load_batch_entry(
        self, batch_id: str, ligand_id: str
    ) -> AutoDockGpuBatchLigandResult | None:
        try:
            return self._batch_state.load_entry(self._batch_dir(batch_id), ligand_id)
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
    ) -> tuple[list[AutoDockGpuBatchLigandResult], int]:
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

    def list_batches(self) -> list[AutoDockGpuBatchRecord]:
        """Every GPU campaign persisted for this project."""
        directory = self._batches_dir()
        if not directory.is_dir():
            return []
        records: list[AutoDockGpuBatchRecord] = []
        for candidate in sorted(directory.iterdir(), key=lambda item: item.name):
            if not candidate.is_dir():
                continue
            try:
                records.append(self.load_batch(candidate.name))
            except (AnkoraDomainError, ValueError):
                continue
        return records

    def list_batch_overviews(self) -> list[AutoDockGpuBatchRecord]:
        directory = self._batches_dir()
        if not directory.is_dir():
            return []
        records: list[AutoDockGpuBatchRecord] = []
        for candidate in sorted(directory.iterdir(), key=lambda item: item.name):
            if not candidate.is_dir():
                continue
            try:
                records.append(self.load_batch_overview(candidate.name))
            except (AnkoraDomainError, ValueError):
                continue
        return records

    def batch_work_directory(self, batch_id: str) -> Path:
        """Where the whole file list is staged and run, as one invocation."""
        path = self._batch_dir(batch_id) / "work"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def batch_ligand_directory(self, batch_id: str, ligand_id: str) -> Path:
        try:
            normalized = str(UUID(ligand_id))
        except ValueError as error:
            raise self._not_found(batch_id, ligand_id) from error
        path = (self._batch_dir(batch_id) / "ligands" / normalized).resolve()
        if self._root not in path.parents:
            raise self._not_found(batch_id, ligand_id)
        path.mkdir(parents=True, exist_ok=True)
        return path

    def write_batch_pose(
        self, batch_id: str, ligand_id: str, filename: str, content: bytes
    ) -> Path:
        if not filename or Path(filename).name != filename:
            raise ValueError("An AutoDock-GPU artifact filename must be a plain filename")
        path = self.batch_ligand_directory(batch_id, ligand_id) / filename
        with path.open("xb") as stream:
            stream.write(content)
        return path

    def batch_pose_content_path(self, batch_id: str, ligand_id: str, artifact_id: str) -> Path:
        entry = self.load_batch_entry(batch_id, ligand_id)
        if entry is None:
            raise self._not_found(batch_id, artifact_id)
        artifact = next(
            (item.artifact for item in entry.runs if item.artifact.artifact_id == artifact_id),
            None,
        )
        if artifact is None:
            raise self._not_found(batch_id, artifact_id)
        path = self.batch_ligand_directory(batch_id, ligand_id) / artifact.filename
        if not path.is_file():
            raise self._not_found(batch_id, artifact_id)
        return path

    def _batches_dir(self) -> Path:
        return self._project_root / "results" / "autodock_gpu_batches"

    def _batch_dir(self, batch_id: str) -> Path:
        try:
            normalized = str(UUID(batch_id))
        except ValueError as error:
            raise self._not_found(batch_id) from error
        resolved = (self._batches_dir() / normalized).resolve()
        if self._root not in resolved.parents:
            raise self._not_found(batch_id)
        return resolved
