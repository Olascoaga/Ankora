"""Project-scoped, create-only scientific artifacts for GNINA jobs."""

import json
import logging
import os
import threading
from hashlib import sha256
from pathlib import Path
from uuid import UUID, uuid4

from ankora_backend.domain.errors import AnkoraDomainError
from ankora_backend.domain.project_context import resolve_project_root
from ankora_backend.schemas.gnina import (
    GninaJobRecord,
    GninaLocalRefinementRecord,
    GninaPoseArtifact,
)

_LOG = logging.getLogger(__name__)


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
            self._require_stable_campaign_link(record)
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
            except (AnkoraDomainError, OSError, ValueError) as error:
                _LOG.warning(
                    "Skipping unreadable GNINA job %s: %s (%s)",
                    candidate,
                    type(error).__name__,
                    error,
                )
                continue
        return records

    def job_directory(self, job_id: str) -> Path:
        return self._result_directory("gnina_jobs", job_id)

    def _result_directory(self, category: str, job_id: str) -> Path:
        try:
            normalized = str(UUID(job_id))
        except (ValueError, AttributeError) as error:
            raise self._not_found(job_id) from error
        directory = (self._project_root / "results" / category / normalized).resolve()
        if self._project_root not in directory.parents:
            raise self._not_found(job_id)
        return directory

    def output_path(self, job_id: str, filename: str) -> Path:
        return self._output_path(self.job_directory(job_id), job_id, filename)

    def _output_path(self, directory: Path, job_id: str, filename: str) -> Path:
        if not filename or Path(filename).name != filename or filename in {".", ".."}:
            raise ValueError("A GNINA artifact filename must be a plain filename")
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
        artifact = self._job_pose(job_id, artifact_id)
        path = self.output_path(job_id, artifact.filename)
        if not path.is_file():
            raise self._not_found(job_id)
        return self._verify_pose(path, artifact.sha256, job_id, artifact_id)

    def pose_flex_content_path(self, job_id: str, artifact_id: str) -> Path | None:
        artifact = self._job_pose(job_id, artifact_id)
        return self._flex_path(self.job_directory(job_id), job_id, artifact)

    def _job_pose(self, job_id: str, artifact_id: str) -> GninaPoseArtifact:
        for pose in self.load_job(job_id).poses:
            if pose.artifact.artifact_id == artifact_id:
                return pose.artifact
        raise self._not_found(job_id)

    def new_refinement_id(self) -> str:
        return str(uuid4())

    def create_refinement_dir(self, refinement_id: str) -> Path:
        directory = self._result_directory("gnina_refinements", refinement_id)
        directory.mkdir(parents=True, exist_ok=False)
        return directory

    def refinement_output_path(self, refinement_id: str, filename: str) -> Path:
        directory = self._result_directory("gnina_refinements", refinement_id)
        return self._output_path(directory, refinement_id, filename)

    def write_refinement_artifact(self, refinement_id: str, filename: str, content: bytes) -> Path:
        path = self.refinement_output_path(refinement_id, filename)
        with path.open("xb") as stream:
            stream.write(content)
        return path

    def save_refinement(self, record: GninaLocalRefinementRecord) -> None:
        data = record.model_dump_json(indent=2) + "\n"
        with self._lock:
            self.write_refinement_artifact(
                record.refinement_id, "record.json", data.encode("utf-8")
            )

    def load_refinement(self, refinement_id: str) -> GninaLocalRefinementRecord:
        with self._lock:
            try:
                raw = self.refinement_output_path(refinement_id, "record.json").read_bytes()
            except FileNotFoundError as error:
                raise self._not_found(refinement_id) from error
        return GninaLocalRefinementRecord.model_validate_json(raw)

    def refinement_pose_content_path(self, refinement_id: str, artifact_id: str) -> Path:
        artifact = self._refinement_pose(refinement_id, artifact_id)
        path = self.refinement_output_path(refinement_id, artifact.filename)
        return self._verify_pose(path, artifact.sha256, refinement_id, artifact_id)

    def refinement_pose_flex_content_path(
        self, refinement_id: str, artifact_id: str
    ) -> Path | None:
        artifact = self._refinement_pose(refinement_id, artifact_id)
        directory = self._result_directory("gnina_refinements", refinement_id)
        return self._flex_path(directory, refinement_id, artifact)

    def _refinement_pose(self, refinement_id: str, artifact_id: str) -> GninaPoseArtifact:
        artifact = self.load_refinement(refinement_id).refined_pose
        if artifact.artifact_id != artifact_id:
            raise self._not_found(refinement_id)
        return artifact

    def _flex_path(
        self, directory: Path, record_id: str, artifact: GninaPoseArtifact
    ) -> Path | None:
        if artifact.flex_filename is None and artifact.pose_flex_sidechains_sha256 is None:
            return None
        if artifact.flex_filename is None:
            raise self._pose_integrity_failed(record_id, artifact.artifact_id)
        path = self._output_path(directory, record_id, artifact.flex_filename)
        return self._verify_pose(
            path,
            artifact.pose_flex_sidechains_sha256,
            record_id,
            artifact.artifact_id,
        )

    def _verify_pose(
        self, path: Path, expected: str | None, record_id: str, artifact_id: str
    ) -> Path:
        try:
            digest = sha256(path.read_bytes()).hexdigest()
        except OSError as error:
            raise self._pose_integrity_failed(record_id, artifact_id) from error
        if digest != expected:
            raise self._pose_integrity_failed(record_id, artifact_id)
        return path

    @staticmethod
    def _pose_integrity_failed(record_id: str, artifact_id: str) -> AnkoraDomainError:
        return AnkoraDomainError(
            code="GNINA_POSE_INTEGRITY_FAILED",
            stage="gnina_storage",
            message="The stored GNINA pose artifact no longer matches its recorded hash.",
            status_code=409,
            details={"job_id": record_id, "artifact_id": artifact_id},
        )

    def _require_stable_campaign_link(self, record: GninaJobRecord) -> None:
        """The campaign correlation is written once, at creation, and never edited.

        Every lifecycle update copies the loaded record, so this only ever fires
        on a caller that invented, replaced or dropped the link. Refusing the
        write keeps an orphaned job identifiable: a lost correlation cannot be
        reconstructed from the record afterwards, and a changed one would
        reassign a job's scientific work to a campaign that did not create it.
        """
        stored = self.load_job(record.job_id).screening_campaign_id
        if stored == record.screening_campaign_id:
            return
        raise AnkoraDomainError(
            code="GNINA_SCREENING_CAMPAIGN_LINK_IMMUTABLE",
            stage="gnina_storage",
            message="The screening campaign recorded for a GNINA job cannot be changed.",
            status_code=409,
            details={
                "job_id": record.job_id,
                "recorded_screening_campaign_id": stored,
                "rejected_screening_campaign_id": record.screening_campaign_id,
            },
        )

    @staticmethod
    def _not_found(job_id: str) -> AnkoraDomainError:
        return AnkoraDomainError(
            code="GNINA_JOB_NOT_FOUND",
            stage="gnina_storage",
            message="No GNINA job artifact exists for this identifier in this project.",
            status_code=404,
            details={"job_id": job_id},
        )
