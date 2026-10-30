"""Project-scoped, create-only scientific artifacts for GNINA jobs."""

import json
import os
import threading
from hashlib import sha256
from pathlib import Path
from uuid import UUID, uuid4

from ankora_backend.domain.errors import AnkoraDomainError
from ankora_backend.domain.project_context import resolve_project_root
from ankora_backend.schemas.gnina import GninaJobRecord


class GninaJobStore:
    def __init__(self, root: Path, project_id: str | None = None) -> None:
        self._project_root = resolve_project_root(root, project_id)
        self._lock = threading.RLock()

    @classmethod
    def from_environment(cls, project_id: str | None = None) -> "GninaJobStore":
        configured = os.getenv("ANKORA_DATA_DIR")
        return cls(Path(configured) if configured else Path.cwd() / ".ankora-data", project_id)

    def new_job_id(self) -> str:
        return str(uuid4())

    def create_job(self, record: GninaJobRecord) -> Path:
        record = GninaJobRecord.model_validate(record.model_dump())
        directory = self.job_directory(record.job_id)
        directory.mkdir(parents=True, exist_ok=False)
        with (directory / "record.json").open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(record.model_dump(mode="json"), stream, indent=2, ensure_ascii=False)
            stream.write("\n")
        return directory

    def update_job(self, record: GninaJobRecord) -> None:
        record = GninaJobRecord.model_validate(record.model_dump())
        with self._lock:
            directory = self.job_directory(record.job_id)
            if not directory.is_dir():
                raise self._not_found(record.job_id)
            temporary = directory / f".record-{uuid4()}.tmp"
            try:
                with temporary.open("x", encoding="utf-8", newline="\n") as stream:
                    json.dump(record.model_dump(mode="json"), stream, indent=2, ensure_ascii=False)
                    stream.write("\n")
                os.replace(temporary, directory / "record.json")
            finally:
                temporary.unlink(missing_ok=True)

    def load_job(self, job_id: str) -> GninaJobRecord:
        with self._lock:
            try:
                raw = (self.job_directory(job_id) / "record.json").read_text(encoding="utf-8")
            except FileNotFoundError as error:
                raise self._not_found(job_id) from error
        return GninaJobRecord.model_validate_json(raw)

    def list_jobs(self) -> list[GninaJobRecord]:
        directory = self._project_root / "results" / "gnina_jobs"
        if not directory.is_dir():
            return []
        records = []
        for candidate in sorted(directory.iterdir(), key=lambda item: item.name):
            if not candidate.is_dir():
                continue
            try:
                records.append(self.load_job(candidate.name))
            except (AnkoraDomainError, ValueError):
                continue
        return records

    def job_directory(self, job_id: str) -> Path:
        try:
            normalized = str(UUID(job_id))
        except (ValueError, AttributeError) as error:
            raise self._not_found(job_id) from error
        directory = (self._project_root / "results" / "gnina_jobs" / normalized).resolve()
        if self._project_root not in directory.parents:
            raise self._not_found(job_id)
        return directory

    def output_path(self, job_id: str, filename: str) -> Path:
        if not filename or Path(filename).name != filename or filename in {".", ".."}:
            raise ValueError("A GNINA artifact filename must be a plain filename")
        directory = self.job_directory(job_id)
        path = (directory / filename).resolve()
        if path.parent != directory:
            raise self._not_found(job_id)
        return path

    def write_artifact(self, job_id: str, filename: str, content: bytes) -> Path:
        path = self.output_path(job_id, filename)
        with path.open("xb") as stream:
            stream.write(content)
        return path

    def pose_content_path(self, job_id: str, artifact_id: str) -> Path:
        record = self.load_job(job_id)
        pose = next(
            (item for item in record.poses if item.artifact.artifact_id == artifact_id), None
        )
        if pose is None:
            raise self._not_found(job_id)
        path = self.output_path(job_id, pose.artifact.filename)
        if not path.is_file():
            raise self._not_found(job_id)
        if sha256(path.read_bytes()).hexdigest() != pose.artifact.sha256:
            raise AnkoraDomainError(
                code="GNINA_POSE_INTEGRITY_FAILED",
                stage="gnina_storage",
                message="The stored GNINA pose no longer matches its recorded hash.",
                status_code=409,
                details={"job_id": job_id, "artifact_id": artifact_id},
            )
        return path

    @staticmethod
    def _not_found(job_id: str) -> AnkoraDomainError:
        return AnkoraDomainError(
            code="GNINA_JOB_NOT_FOUND",
            stage="gnina_storage",
            message="No GNINA job artifact exists for this identifier in this project.",
            status_code=404,
            details={"job_id": job_id},
        )
