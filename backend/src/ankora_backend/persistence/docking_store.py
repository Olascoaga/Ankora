"""Storage for docking job state, raw evidence, and immutable pose artifacts."""

import json
import os
import threading
from collections.abc import Sequence
from pathlib import Path
from uuid import UUID, uuid4

from ankora_backend.domain.errors import AnkoraDomainError
from ankora_backend.domain.project_context import resolve_project_root
from ankora_backend.persistence.incremental_batch_store import IncrementalBatchStore
from ankora_backend.schemas.docking import (
    VinaBatchDockingRecord,
    VinaBatchLigandResult,
    VinaDockingJobRecord,
)


def _best_vina_result(entry: VinaBatchLigandResult) -> float | None:
    if not entry.poses:
        return None
    return float(entry.poses[0].affinity_kcal_mol)


class DockingArtifactStore:
    def __init__(self, root: Path, project_id: str | None = None) -> None:
        self._root = root.resolve()
        self._project_root = resolve_project_root(self._root, project_id)
        self._record_lock = threading.RLock()
        self._batch_state = IncrementalBatchStore(
            record_type=VinaBatchDockingRecord,
            entry_type=VinaBatchLigandResult,
            best_result=_best_vina_result,
        )

    @classmethod
    def from_environment(cls, project_id: str | None = None) -> "DockingArtifactStore":
        configured = os.getenv("ANKORA_DATA_DIR")
        return cls(Path(configured) if configured else Path.cwd() / ".ankora-data", project_id)

    def new_job_id(self) -> str:
        return str(uuid4())

    def new_batch_id(self) -> str:
        return str(uuid4())

    def create_job(self, record: VinaDockingJobRecord) -> Path:
        directory = self._job_dir(record.job_id)
        directory.mkdir(parents=True, exist_ok=False)
        self._write_record(record)
        return directory

    def update_record(self, record: VinaDockingJobRecord) -> None:
        with self._record_lock:
            directory = self._job_dir(record.job_id)
            if not directory.is_dir():
                raise self._not_found(record.job_id)
            temporary = directory / "record.json.tmp"
            with temporary.open("w", encoding="utf-8", newline="\n") as stream:
                json.dump(record.model_dump(mode="json"), stream, indent=2, ensure_ascii=False)
                stream.write("\n")
            os.replace(temporary, directory / "record.json")

    def load_record(self, job_id: str) -> VinaDockingJobRecord:
        with self._record_lock:
            try:
                raw = (self._job_dir(job_id) / "record.json").read_text(encoding="utf-8")
            except FileNotFoundError as error:
                raise self._not_found(job_id) from error
        return VinaDockingJobRecord.model_validate_json(raw)

    def output_path(self, job_id: str, filename: str) -> Path:
        if Path(filename).name != filename or not filename:
            raise ValueError("Docking output filename must be a plain filename")
        return self._job_dir(job_id) / filename

    def write_bytes(self, job_id: str, filename: str, content: bytes) -> Path:
        path = self.output_path(job_id, filename)
        with path.open("xb") as stream:
            stream.write(content)
        return path

    def write_text(self, job_id: str, filename: str, content: str) -> Path:
        path = self.output_path(job_id, filename)
        with path.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(content)
        return path

    def pose_content_path(self, job_id: str, artifact_id: str) -> Path:
        record = self.load_record(job_id)
        pose = next(
            (item for item in record.poses if item.artifact.artifact_id == artifact_id),
            None,
        )
        if pose is None:
            raise self._not_found(job_id, artifact_id)
        path = self.output_path(job_id, pose.artifact.filename)
        if not path.is_file():
            raise self._not_found(job_id, artifact_id)
        return path

    def create_batch(self, record: VinaBatchDockingRecord) -> Path:
        directory = self._batch_dir(record.batch_id)
        directory.mkdir(parents=True, exist_ok=False)
        for entry in record.entries:
            self._batch_ligand_dir(record.batch_id, entry.ligand_id).mkdir(
                parents=True, exist_ok=False
            )
        self._write_batch_record(record)
        self._batch_state.create(directory, record)
        return directory

    def update_batch_record(
        self,
        record: VinaBatchDockingRecord,
        *,
        changed_entries: Sequence[VinaBatchLigandResult] | None = None,
    ) -> VinaBatchDockingRecord:
        with self._record_lock:
            directory = self._batch_dir(record.batch_id)
            if not directory.is_dir():
                raise self._not_found(record.batch_id)
            return self._batch_state.update(directory, record, changed_entries=changed_entries)

    def load_batch_record(self, batch_id: str) -> VinaBatchDockingRecord:
        with self._record_lock:
            try:
                return self._batch_state.load(self._batch_dir(batch_id))
            except FileNotFoundError as error:
                raise self._not_found(batch_id) from error

    def load_batch_overview(self, batch_id: str) -> VinaBatchDockingRecord:
        try:
            return self._batch_state.load_overview(self._batch_dir(batch_id))
        except FileNotFoundError as error:
            raise self._not_found(batch_id) from error

    def load_batch_summary(self, batch_id: str) -> dict[str, object]:
        try:
            return self._batch_state.load_summary(self._batch_dir(batch_id))
        except FileNotFoundError as error:
            raise self._not_found(batch_id) from error

    def load_batch_entry(self, batch_id: str, ligand_id: str) -> VinaBatchLigandResult | None:
        try:
            return self._batch_state.load_entry(self._batch_dir(batch_id), ligand_id)
        except FileNotFoundError as error:
            raise self._not_found(batch_id) from error

    def update_batch_entry(
        self, batch_id: str, entry: VinaBatchLigandResult
    ) -> VinaBatchLigandResult:
        try:
            return self._batch_state.update_entry(self._batch_dir(batch_id), entry)
        except FileNotFoundError as error:
            raise self._not_found(batch_id) from error

    def load_batch_entries_after_revision(
        self, batch_id: str, revision: int
    ) -> list[VinaBatchLigandResult]:
        try:
            return self._batch_state.entries_after_revision(self._batch_dir(batch_id), revision)
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
    ) -> tuple[list[VinaBatchLigandResult], int]:
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

    def list_batch_records(self) -> list[VinaBatchDockingRecord]:
        directory = self._batches_dir()
        if not directory.is_dir():
            return []
        records: list[VinaBatchDockingRecord] = []
        for candidate in directory.iterdir():
            if not candidate.is_dir():
                continue
            try:
                records.append(self.load_batch_record(candidate.name))
            except AnkoraDomainError:
                continue
        return records

    def list_batch_overviews(self) -> list[VinaBatchDockingRecord]:
        directory = self._batches_dir()
        if not directory.is_dir():
            return []
        records: list[VinaBatchDockingRecord] = []
        for candidate in directory.iterdir():
            if not candidate.is_dir():
                continue
            try:
                records.append(self.load_batch_overview(candidate.name))
            except (AnkoraDomainError, ValueError):
                continue
        return records

    def list_jobs(self) -> list[VinaDockingJobRecord]:
        """Every single-ligand job this project holds.

        A single job is as durable as a campaign, so the result catalog can
        offer both instead of only what ran in a library.
        """
        directory = self._project_root / "results" / "docking"
        if not directory.is_dir():
            return []
        records: list[VinaDockingJobRecord] = []
        for candidate in sorted(directory.iterdir(), key=lambda item: item.name):
            if not candidate.is_dir():
                continue
            try:
                records.append(self.load_record(candidate.name))
            except (AnkoraDomainError, ValueError):
                continue
        return records

    def batch_output_path(self, batch_id: str, ligand_id: str, filename: str) -> Path:
        if Path(filename).name != filename or not filename:
            raise ValueError("Docking output filename must be a plain filename")
        return self._batch_ligand_dir(batch_id, ligand_id) / filename

    def write_batch_bytes(
        self, batch_id: str, ligand_id: str, filename: str, content: bytes
    ) -> Path:
        path = self.batch_output_path(batch_id, ligand_id, filename)
        with path.open("xb") as stream:
            stream.write(content)
        return path

    def write_batch_text(self, batch_id: str, ligand_id: str, filename: str, content: str) -> Path:
        path = self.batch_output_path(batch_id, ligand_id, filename)
        with path.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(content)
        return path

    def batch_pose_content_path(self, batch_id: str, ligand_id: str, artifact_id: str) -> Path:
        entry = self.load_batch_entry(batch_id, ligand_id)
        pose = next(
            (
                item
                for item in (entry.poses if entry is not None else [])
                if item.artifact.artifact_id == artifact_id
            ),
            None,
        )
        if pose is None:
            raise self._not_found(batch_id, artifact_id)
        path = self.batch_output_path(batch_id, ligand_id, pose.artifact.filename)
        if not path.is_file():
            raise self._not_found(batch_id, artifact_id)
        return path

    def _write_record(self, record: VinaDockingJobRecord) -> None:
        path = self.output_path(record.job_id, "record.json")
        with path.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(record.model_dump(mode="json"), stream, indent=2, ensure_ascii=False)
            stream.write("\n")

    def _write_batch_record(self, record: VinaBatchDockingRecord) -> None:
        path = self._batch_dir(record.batch_id) / "record.json"
        with path.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(record.model_dump(mode="json"), stream, indent=2, ensure_ascii=False)
            stream.write("\n")

    def _job_dir(self, job_id: str) -> Path:
        try:
            normalized = str(UUID(job_id))
        except ValueError as error:
            raise self._not_found(job_id) from error
        path = self._project_root / "results" / "docking" / normalized
        resolved = path.resolve()
        if self._root not in resolved.parents:
            raise self._not_found(job_id)
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

    def _batches_dir(self) -> Path:
        path = self._project_root / "results" / "docking_batches"
        resolved = path.resolve()
        if self._root not in resolved.parents:
            raise self._not_found("docking_batches")
        return resolved

    def _batch_ligand_dir(self, batch_id: str, ligand_id: str) -> Path:
        directory = self._batch_dir(batch_id)
        try:
            normalized_ligand = str(UUID(ligand_id))
        except ValueError as error:
            raise self._not_found(batch_id, ligand_id) from error
        path = directory / "ligands" / normalized_ligand
        resolved = path.resolve()
        if self._root not in resolved.parents:
            raise self._not_found(batch_id, ligand_id)
        return resolved

    @staticmethod
    def _not_found(job_id: str, artifact_id: str | None = None) -> AnkoraDomainError:
        details: dict[str, object] = {"job_id": job_id}
        if artifact_id is not None:
            details["artifact_id"] = artifact_id
        return AnkoraDomainError(
            code="DOCKING_JOB_NOT_FOUND",
            stage="docking_storage",
            message="The requested docking job or pose is not available in this project.",
            status_code=404,
            details=details,
        )
