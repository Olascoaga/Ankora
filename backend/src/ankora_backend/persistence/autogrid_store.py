"""Create-only storage for immutable AutoGrid4 map sets and their raw evidence."""

import json
import os
import threading
from pathlib import Path
from uuid import UUID, uuid4

from ankora_backend.domain.errors import AnkoraDomainError
from ankora_backend.schemas.autogrid import AutoGridMapJobRecord, AutoGridMapSetRecord


class AutoGridMapStore:
    """A map set is written once and never mutated.

    The record is the last file written, so a directory without one is an
    incomplete run rather than a reusable map set; identity lookup ignores it.
    """

    def __init__(self, root: Path) -> None:
        self._root = root.resolve()
        self._record_lock = threading.RLock()

    @classmethod
    def from_environment(cls) -> "AutoGridMapStore":
        configured = os.getenv("ANKORA_DATA_DIR")
        return cls(Path(configured) if configured else Path.cwd() / ".ankora-data")

    def new_map_set_id(self) -> str:
        return str(uuid4())

    def create_map_set_directory(self, map_set_id: str) -> Path:
        directory = self._map_set_dir(map_set_id)
        directory.mkdir(parents=True, exist_ok=False)
        return directory

    def map_set_directory(self, map_set_id: str) -> Path:
        return self._map_set_dir(map_set_id)

    def write_record(self, record: AutoGridMapSetRecord) -> Path:
        path = self._map_set_dir(record.map_set_id) / "record.json"
        with path.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(record.model_dump(mode="json"), stream, indent=2, ensure_ascii=False)
            stream.write("\n")
        return path

    def load_record(self, map_set_id: str) -> AutoGridMapSetRecord:
        with self._record_lock:
            try:
                raw = (self._map_set_dir(map_set_id) / "record.json").read_text(
                    encoding="utf-8"
                )
            except FileNotFoundError as error:
                raise self._not_found(map_set_id) from error
        return AutoGridMapSetRecord.model_validate_json(raw)

    def list_records(self) -> list[AutoGridMapSetRecord]:
        directory = self._map_sets_dir()
        if not directory.is_dir():
            return []
        records: list[AutoGridMapSetRecord] = []
        for candidate in sorted(directory.iterdir(), key=lambda item: item.name):
            if not candidate.is_dir():
                continue
            try:
                records.append(self.load_record(candidate.name))
            except (AnkoraDomainError, ValueError):
                continue
        return records

    def find_by_identity(self, identity_key: str) -> AutoGridMapSetRecord | None:
        """Return the existing immutable map set for this exact identity, if any."""
        for record in self.list_records():
            if record.identity_key == identity_key and self._artifacts_present(record):
                return record
        return None

    def content_path(self, map_set_id: str, artifact_id: str) -> Path:
        record = self.load_record(map_set_id)
        artifact = next(
            (item for item in record.artifacts if item.artifact_id == artifact_id),
            None,
        )
        if artifact is None:
            raise self._not_found(map_set_id, artifact_id)
        path = self.output_path(map_set_id, artifact.filename)
        if not path.is_file():
            raise self._not_found(map_set_id, artifact_id)
        return path

    def output_path(self, map_set_id: str, filename: str) -> Path:
        if not filename or Path(filename).name != filename:
            raise ValueError("An AutoGrid artifact filename must be a plain filename")
        return self._map_set_dir(map_set_id) / filename

    def new_job_id(self) -> str:
        return str(uuid4())

    def create_job(self, record: AutoGridMapJobRecord) -> Path:
        directory = self._job_dir(record.job_id)
        directory.mkdir(parents=True, exist_ok=False)
        path = directory / "record.json"
        with path.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(record.model_dump(mode="json"), stream, indent=2, ensure_ascii=False)
            stream.write("\n")
        return directory

    def update_job(self, record: AutoGridMapJobRecord) -> None:
        """Job progress is mutable, unlike the map set it produces.

        The write is atomic so a poll landing mid-update never reads a torn file.
        """
        with self._record_lock:
            directory = self._job_dir(record.job_id)
            if not directory.is_dir():
                raise self._job_not_found(record.job_id)
            temporary = directory / "record.json.tmp"
            with temporary.open("w", encoding="utf-8", newline="\n") as stream:
                json.dump(
                    record.model_dump(mode="json"), stream, indent=2, ensure_ascii=False
                )
                stream.write("\n")
            os.replace(temporary, directory / "record.json")

    def load_job(self, job_id: str) -> AutoGridMapJobRecord:
        with self._record_lock:
            try:
                raw = (self._job_dir(job_id) / "record.json").read_text(encoding="utf-8")
            except FileNotFoundError as error:
                raise self._job_not_found(job_id) from error
        return AutoGridMapJobRecord.model_validate_json(raw)

    def _jobs_dir(self) -> Path:
        path = self._root / "projects" / "default" / "results" / "autogrid_jobs"
        resolved = path.resolve()
        if self._root not in resolved.parents and resolved != self._root:
            raise self._job_not_found("autogrid_jobs")
        return resolved

    def _job_dir(self, job_id: str) -> Path:
        try:
            normalized = str(UUID(job_id))
        except ValueError as error:
            raise self._job_not_found(job_id) from error
        path = self._jobs_dir() / normalized
        resolved = path.resolve()
        if self._root not in resolved.parents:
            raise self._job_not_found(job_id)
        return resolved

    @staticmethod
    def _job_not_found(job_id: str) -> AnkoraDomainError:
        return AnkoraDomainError(
            code="AUTOGRID_JOB_NOT_FOUND",
            stage="autogrid_storage",
            message="The requested AutoGrid job is not available in this project.",
            status_code=404,
            details={"job_id": job_id},
        )

    def _artifacts_present(self, record: AutoGridMapSetRecord) -> bool:
        directory = self._map_set_dir(record.map_set_id)
        return all((directory / item.filename).is_file() for item in record.artifacts)

    def _map_sets_dir(self) -> Path:
        path = self._root / "projects" / "default" / "derived" / "autogrid_maps"
        resolved = path.resolve()
        if self._root not in resolved.parents and resolved != self._root:
            raise self._not_found("autogrid_maps")
        return resolved

    def _map_set_dir(self, map_set_id: str) -> Path:
        try:
            normalized = str(UUID(map_set_id))
        except ValueError as error:
            raise self._not_found(map_set_id) from error
        path = self._map_sets_dir() / normalized
        resolved = path.resolve()
        if self._root not in resolved.parents:
            raise self._not_found(map_set_id)
        return resolved

    @staticmethod
    def _not_found(
        map_set_id: str, artifact_id: str | None = None
    ) -> AnkoraDomainError:
        details: dict[str, object] = {"map_set_id": map_set_id}
        if artifact_id is not None:
            details["artifact_id"] = artifact_id
        return AnkoraDomainError(
            code="AUTOGRID_MAP_SET_NOT_FOUND",
            stage="autogrid_storage",
            message="The requested AutoGrid map set is not available in this project.",
            status_code=404,
            details=details,
        )
