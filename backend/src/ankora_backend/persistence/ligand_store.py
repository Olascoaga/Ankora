"""Create-only storage for immutable M3 ligand originals."""

import json
import os
import re
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from ankora_backend.domain.errors import AnkoraDomainError
from ankora_backend.schemas.ligand_library_preparation import (
    LigandLibraryPreparationRecord,
    LigandPreparationEntry,
)
from ankora_backend.schemas.ligands import (
    LigandChemicalStateArtifact,
    LigandChemicalStateRecord,
    LigandConformerRecord,
    LigandInspection,
    LigandLibraryArtifact,
    LigandLibraryFilterRun,
    LigandLibraryRecord,
    LigandLibrarySummary,
    LigandPdbqtRecord,
    LigandProtonationRecord,
    LigandRecord,
)

_SAFE_FILENAME = re.compile(r"[^A-Za-z0-9._-]+")

# Route handlers construct a fresh LigandArtifactStore per request, so the lock
# guarding a library's aggregate status file must live at module scope, keyed by
# library_id, to actually serialize concurrent batch-preparation workers.
_PREPARATION_LOCKS: dict[str, threading.Lock] = {}
_PREPARATION_LOCKS_GUARD = threading.Lock()


def _preparation_lock(library_id: str) -> threading.Lock:
    with _PREPARATION_LOCKS_GUARD:
        lock = _PREPARATION_LOCKS.get(library_id)
        if lock is None:
            lock = threading.Lock()
            _PREPARATION_LOCKS[library_id] = lock
        return lock


class LigandArtifactStore:
    def __init__(self, root: Path) -> None:
        self._root = root.resolve()

    @property
    def root(self) -> Path:
        return self._root

    @classmethod
    def from_environment(cls) -> "LigandArtifactStore":
        configured = os.getenv("ANKORA_DATA_DIR")
        return cls(Path(configured) if configured else Path.cwd() / ".ankora-data")

    def new_ligand_id(self) -> str:
        return str(uuid4())

    def new_library_id(self) -> str:
        return str(uuid4())

    def new_filter_run_id(self) -> str:
        return str(uuid4())

    def new_conformer_id(self) -> str:
        return str(uuid4())

    def new_state_id(self) -> str:
        return str(uuid4())

    def new_preparation_id(self) -> str:
        return str(uuid4())

    def create(
        self,
        ligand_id: str,
        content: bytes,
        record: LigandRecord,
        *,
        state_content: bytes | None = None,
    ) -> None:
        directory = self._ligand_dir(ligand_id)
        directory.mkdir(parents=True, exist_ok=False)
        with (directory / self.sanitize_filename(record.artifact.filename)).open("xb") as stream:
            stream.write(content)
        if record.state is not None and state_content is not None:
            state_directory = self._state_dir(ligand_id, record.state.state_id)
            state_directory.mkdir(parents=True, exist_ok=False)
            with (state_directory / self.sanitize_filename(record.state.filename)).open(
                "xb"
            ) as stream:
                stream.write(state_content)
        with (directory / "record.json").open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(record.model_dump(mode="json"), stream, indent=2, ensure_ascii=False)
            stream.write("\n")

    def create_library(
        self, library_id: str, content: bytes, record: LigandLibraryRecord
    ) -> None:
        directory = self._library_dir(library_id)
        directory.mkdir(parents=True, exist_ok=False)
        with (directory / self.sanitize_filename(record.artifact.filename)).open(
            "xb"
        ) as stream:
            stream.write(content)
        with (directory / "record.json").open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(record.model_dump(mode="json"), stream, indent=2, ensure_ascii=False)
            stream.write("\n")

    def list_libraries(self) -> list[LigandLibrarySummary]:
        """Every imported library, newest first, without their molecules.

        The 38 libraries in the real project hold 35.7 MiB of record JSON
        between them; parsing all of it to draw a list would get slower with
        every import. `artifact` is written first, so a bounded head-read
        reaches the whole identity without touching the entries array, and a
        record whose shape has changed falls back to a full parse rather than
        disappearing from the list.
        """
        directory = self._libraries_dir()
        if not directory.is_dir():
            return []
        summaries: list[LigandLibrarySummary] = []
        for candidate in directory.iterdir():
            if not candidate.is_dir():
                continue
            artifact = self._library_artifact(candidate / "record.json")
            if artifact is None:
                continue
            runs = self._filter_run_directories(candidate.name)
            summaries.append(
                LigandLibrarySummary(
                    artifact=artifact,
                    filter_run_count=len(runs),
                    latest_filter_run_id=runs[-1].name if runs else None,
                )
            )
        summaries.sort(
            key=lambda item: (item.artifact.created_at, item.artifact.library_id),
            reverse=True,
        )
        return summaries

    def _library_artifact(self, path: Path) -> LigandLibraryArtifact | None:
        try:
            with path.open("r", encoding="utf-8") as stream:
                head = stream.read(4096)
        except OSError:
            return None
        artifact = _first_object_after(head, '"artifact"')
        if artifact is not None:
            try:
                return LigandLibraryArtifact.model_validate_json(artifact)
            except ValueError:
                pass
        try:
            return LigandLibraryRecord.model_validate_json(
                path.read_text(encoding="utf-8")
            ).artifact
        except (OSError, ValueError):
            return None

    def _filter_run_directories(self, library_id: str) -> list[Path]:
        """Ordered by write time, which is a stat rather than a parse."""
        try:
            runs = self._filter_runs_dir(library_id)
        except AnkoraDomainError:
            return []
        if not runs.is_dir():
            return []
        return sorted(
            (item for item in runs.iterdir() if item.is_dir()),
            key=lambda item: item.stat().st_mtime,
        )

    def _libraries_dir(self) -> Path:
        path = self._root / "projects" / "default" / "original" / "ligand_libraries"
        resolved = path.resolve()
        if self._root not in resolved.parents:
            raise self._library_not_found("ligand_libraries")
        return resolved

    def load_library_record(self, library_id: str) -> LigandLibraryRecord:
        try:
            raw = (self._library_dir(library_id) / "record.json").read_text(
                encoding="utf-8"
            )
        except FileNotFoundError as error:
            raise self._library_not_found(library_id) from error
        return LigandLibraryRecord.model_validate_json(raw)

    def library_content_path(self, library_id: str) -> Path:
        record = self.load_library_record(library_id)
        path = self._library_dir(library_id) / self.sanitize_filename(
            record.artifact.filename
        )
        if not path.is_file():
            raise self._library_not_found(library_id)
        return path

    def create_filter_run(
        self,
        library_id: str,
        filter_run_id: str,
        manifest: bytes,
        record: LigandLibraryFilterRun,
    ) -> None:
        directory = self._filter_run_dir(library_id, filter_run_id)
        directory.mkdir(parents=True, exist_ok=False)
        with (directory / self.sanitize_filename(record.artifact.filename)).open("xb") as stream:
            stream.write(manifest)
        with (directory / "record.json").open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(record.model_dump(mode="json"), stream, indent=2, ensure_ascii=False)
            stream.write("\n")

    def load_preparation_status(self, library_id: str) -> LigandLibraryPreparationRecord:
        path = self._preparation_status_path(library_id)
        if not path.is_file():
            return LigandLibraryPreparationRecord(
                library_id=library_id, updated_at=datetime.now(UTC), entries={}
            )
        return LigandLibraryPreparationRecord.model_validate_json(
            path.read_text(encoding="utf-8")
        )

    def upsert_preparation_entry(
        self, library_id: str, entry: LigandPreparationEntry
    ) -> LigandLibraryPreparationRecord:
        with _preparation_lock(library_id):
            record = self.load_preparation_status(library_id)
            record.entries[entry.ligand_id] = entry
            record.updated_at = entry.updated_at
            # Written to a sibling temp file and atomically renamed into place
            # (os.replace) rather than truncate-then-write directly: a batch
            # run upserts this file on every ligand, and a GET arriving mid
            # write() would otherwise see a truncated file and a stale-but-
            # tolerated ValidationError (LigandWorkspace.tsx swallows it),
            # losing that hydration for no reason — replace is a single
            # filesystem operation with no partially-written state to observe.
            final_path = self._preparation_status_path(library_id)
            tmp_path = final_path.with_name(f"{final_path.name}.{uuid4().hex}.tmp")
            tmp_path.write_text(
                json.dumps(record.model_dump(mode="json"), indent=2, ensure_ascii=False)
                + "\n",
                encoding="utf-8",
                newline="\n",
            )
            os.replace(tmp_path, final_path)
            return record

    def load_filter_run(
        self, library_id: str, filter_run_id: str
    ) -> LigandLibraryFilterRun:
        try:
            raw = (self._filter_run_dir(library_id, filter_run_id) / "record.json").read_text(
                encoding="utf-8"
            )
        except FileNotFoundError as error:
            raise self._filter_run_not_found(library_id, filter_run_id) from error
        return LigandLibraryFilterRun.model_validate_json(raw)

    def load_latest_filter_run(self, library_id: str) -> LigandLibraryFilterRun:
        self.load_library_record(library_id)
        directory = self._filter_runs_dir(library_id)
        if not directory.is_dir():
            raise self._filter_run_not_found(library_id, "latest")
        records: list[LigandLibraryFilterRun] = []
        for candidate in directory.iterdir():
            if not candidate.is_dir():
                continue
            try:
                records.append(self.load_filter_run(library_id, candidate.name))
            except AnkoraDomainError:
                continue
        if not records:
            raise self._filter_run_not_found(library_id, "latest")
        return max(
            records,
            key=lambda record: (
                record.artifact.created_at,
                record.artifact.filter_run_id,
            ),
        )

    def filter_run_content_path(self, library_id: str, filter_run_id: str) -> Path:
        record = self.load_filter_run(library_id, filter_run_id)
        path = self._filter_run_dir(library_id, filter_run_id) / self.sanitize_filename(
            record.artifact.filename
        )
        if not path.is_file():
            raise self._filter_run_not_found(library_id, filter_run_id)
        return path

    def load_record(self, ligand_id: str) -> LigandRecord:
        try:
            raw = (self._ligand_dir(ligand_id) / "record.json").read_text(encoding="utf-8")
        except FileNotFoundError as error:
            raise self._not_found(ligand_id) from error
        return LigandRecord.model_validate_json(raw)

    def content_path(self, ligand_id: str) -> Path:
        record = self.load_record(ligand_id)
        path = self._ligand_dir(ligand_id) / self.sanitize_filename(record.artifact.filename)
        if not path.is_file():
            raise self._not_found(ligand_id)
        return path

    def state_content_path(self, ligand_id: str, state_id: str | None = None) -> Path:
        record = self.load_record(ligand_id)
        if record.state is None:
            return self.content_path(ligand_id)
        requested_state_id = state_id or record.state.state_id
        if requested_state_id == record.state.state_id:
            artifact = record.state
        else:
            artifact = self.load_state_artifact(ligand_id, requested_state_id)
        path = self._state_dir(ligand_id, requested_state_id) / self.sanitize_filename(
            artifact.filename
        )
        if not path.is_file():
            raise self._state_not_found(ligand_id, requested_state_id)
        return path

    def create_state(
        self,
        ligand_id: str,
        state_id: str,
        content: bytes,
        record: LigandChemicalStateRecord | LigandProtonationRecord,
    ) -> None:
        directory = self._state_dir(ligand_id, state_id)
        directory.mkdir(parents=True, exist_ok=False)
        with (directory / self.sanitize_filename(record.artifact.filename)).open(
            "xb"
        ) as stream:
            stream.write(content)
        with (directory / "record.json").open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(record.model_dump(mode="json"), stream, indent=2, ensure_ascii=False)
            stream.write("\n")

    def _read_state_record_json(self, ligand_id: str, state_id: str) -> dict[str, Any]:
        try:
            raw = (self._state_dir(ligand_id, state_id) / "record.json").read_text(
                encoding="utf-8"
            )
        except FileNotFoundError as error:
            raise self._state_not_found(ligand_id, state_id) from error
        payload: dict[str, Any] = json.loads(raw)
        return payload

    def load_state_artifact(
        self, ligand_id: str, state_id: str
    ) -> LigandChemicalStateArtifact:
        """Read only the artifact metadata shared by every state-producing decision
        (component/stereo resolution, protonation) without depending on which
        decision's record shape wrote it."""
        payload = self._read_state_record_json(ligand_id, state_id)
        return LigandChemicalStateArtifact.model_validate(payload["artifact"])

    def load_state_inspection(self, ligand_id: str, state_id: str) -> LigandInspection:
        """Read only the molecular inspection shared by every state-producing
        decision, for the same reason as `load_state_artifact`."""
        payload = self._read_state_record_json(ligand_id, state_id)
        return LigandInspection.model_validate(payload["inspection"])

    def load_state_record(
        self, ligand_id: str, state_id: str
    ) -> LigandChemicalStateRecord | LigandProtonationRecord:
        """Load the exact scientist-recorded decision that produced a state."""
        payload = self._read_state_record_json(ligand_id, state_id)
        event_type = payload.get("provenance", {}).get("event_type")
        if event_type == "ligand_protonation_resolved":
            return LigandProtonationRecord.model_validate(payload)
        if event_type == "ligand_chemical_state_resolved":
            return LigandChemicalStateRecord.model_validate(payload)
        raise AnkoraDomainError(
            code="LIGAND_STATE_RECORD_UNRECOGNIZED",
            stage="ligand_store",
            message="The ligand chemical-state record has an unknown decision type.",
            status_code=422,
            details={
                "ligand_id": ligand_id,
                "state_id": state_id,
                "event_type": event_type,
            },
        )

    def create_conformer(
        self,
        ligand_id: str,
        conformer_id: str,
        content: bytes,
        record: LigandConformerRecord,
    ) -> None:
        directory = self._conformer_dir(ligand_id, conformer_id)
        directory.mkdir(parents=True, exist_ok=False)
        with (directory / self.sanitize_filename(record.artifact.filename)).open("xb") as stream:
            stream.write(content)
        with (directory / "record.json").open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(record.model_dump(mode="json"), stream, indent=2, ensure_ascii=False)
            stream.write("\n")

    def load_conformer_record(
        self, ligand_id: str, conformer_id: str
    ) -> LigandConformerRecord:
        try:
            raw = (self._conformer_dir(ligand_id, conformer_id) / "record.json").read_text(
                encoding="utf-8"
            )
        except FileNotFoundError as error:
            raise self._conformer_not_found(ligand_id, conformer_id) from error
        return LigandConformerRecord.model_validate_json(raw)

    def conformer_content_path(self, ligand_id: str, conformer_id: str) -> Path:
        record = self.load_conformer_record(ligand_id, conformer_id)
        path = self._conformer_dir(ligand_id, conformer_id) / self.sanitize_filename(
            record.artifact.filename
        )
        if not path.is_file():
            raise self._conformer_not_found(ligand_id, conformer_id)
        return path

    def create_pdbqt(
        self,
        ligand_id: str,
        preparation_id: str,
        content: bytes,
        record: LigandPdbqtRecord,
    ) -> None:
        directory = self._preparation_dir(ligand_id, preparation_id)
        directory.mkdir(parents=True, exist_ok=False)
        with (directory / self.sanitize_filename(record.artifact.filename)).open(
            "xb"
        ) as stream:
            stream.write(content)
        self._write_execution_logs(directory, record.stdout, record.stderr)
        with (directory / "record.json").open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(record.model_dump(mode="json"), stream, indent=2, ensure_ascii=False)
            stream.write("\n")

    def create_pdbqt_failure(
        self,
        ligand_id: str,
        preparation_id: str,
        payload: dict[str, object],
        stdout: str,
        stderr: str,
    ) -> None:
        directory = self._preparation_dir(ligand_id, preparation_id)
        directory.mkdir(parents=True, exist_ok=False)
        self._write_execution_logs(directory, stdout, stderr)
        with (directory / "failure.json").open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(payload, stream, indent=2, ensure_ascii=False)
            stream.write("\n")

    def load_pdbqt_record(self, ligand_id: str, preparation_id: str) -> LigandPdbqtRecord:
        try:
            raw = (
                self._preparation_dir(ligand_id, preparation_id) / "record.json"
            ).read_text(encoding="utf-8")
        except FileNotFoundError as error:
            raise self._preparation_not_found(ligand_id, preparation_id) from error
        return LigandPdbqtRecord.model_validate_json(raw)

    def pdbqt_content_path(self, ligand_id: str, preparation_id: str) -> Path:
        record = self.load_pdbqt_record(ligand_id, preparation_id)
        path = self._preparation_dir(ligand_id, preparation_id) / self.sanitize_filename(
            record.artifact.filename
        )
        if not path.is_file():
            raise self._preparation_not_found(ligand_id, preparation_id)
        return path

    def _ligand_dir(self, ligand_id: str) -> Path:
        try:
            normalized = str(UUID(ligand_id))
        except ValueError as error:
            raise self._not_found(ligand_id) from error
        path = self._root / "projects" / "default" / "original" / "ligands" / normalized
        resolved = path.resolve()
        if self._root not in resolved.parents:
            raise self._not_found(ligand_id)
        return resolved

    def _library_dir(self, library_id: str) -> Path:
        try:
            normalized = str(UUID(library_id))
        except ValueError as error:
            raise self._library_not_found(library_id) from error
        path = self._root / "projects" / "default" / "original" / "ligand_libraries" / normalized
        resolved = path.resolve()
        if self._root not in resolved.parents:
            raise self._library_not_found(library_id)
        return resolved

    def _preparation_status_path(self, library_id: str) -> Path:
        return self._library_dir(library_id) / "preparation_status.json"

    def _conformer_dir(self, ligand_id: str, conformer_id: str) -> Path:
        try:
            normalized_ligand = str(UUID(ligand_id))
            normalized_conformer = str(UUID(conformer_id))
        except ValueError as error:
            raise self._conformer_not_found(ligand_id, conformer_id) from error
        path = (
            self._root
            / "projects"
            / "default"
            / "derived"
            / "ligands"
            / normalized_ligand
            / "conformers"
            / normalized_conformer
        )
        resolved = path.resolve()
        if self._root not in resolved.parents:
            raise self._conformer_not_found(ligand_id, conformer_id)
        return resolved

    def _filter_run_dir(self, library_id: str, filter_run_id: str) -> Path:
        try:
            normalized_run = str(UUID(filter_run_id))
        except ValueError as error:
            raise self._filter_run_not_found(library_id, filter_run_id) from error
        path = self._filter_runs_dir(library_id) / normalized_run
        resolved = path.resolve()
        if self._root not in resolved.parents:
            raise self._filter_run_not_found(library_id, filter_run_id)
        return resolved

    def _filter_runs_dir(self, library_id: str) -> Path:
        try:
            normalized_library = str(UUID(library_id))
        except ValueError as error:
            raise self._library_not_found(library_id) from error
        path = (
            self._root
            / "projects"
            / "default"
            / "derived"
            / "ligand_libraries"
            / normalized_library
            / "filter_runs"
        )
        resolved = path.resolve()
        if self._root not in resolved.parents:
            raise self._library_not_found(library_id)
        return resolved

    def _state_dir(self, ligand_id: str, state_id: str) -> Path:
        try:
            normalized_ligand = str(UUID(ligand_id))
            normalized_state = str(UUID(state_id))
        except ValueError as error:
            raise self._state_not_found(ligand_id, state_id) from error
        path = (
            self._root
            / "projects"
            / "default"
            / "derived"
            / "ligands"
            / normalized_ligand
            / "states"
            / normalized_state
        )
        resolved = path.resolve()
        if self._root not in resolved.parents:
            raise self._state_not_found(ligand_id, state_id)
        return resolved

    def _preparation_dir(self, ligand_id: str, preparation_id: str) -> Path:
        try:
            normalized_ligand = str(UUID(ligand_id))
            normalized_preparation = str(UUID(preparation_id))
        except ValueError as error:
            raise self._preparation_not_found(ligand_id, preparation_id) from error
        path = (
            self._root
            / "projects"
            / "default"
            / "derived"
            / "ligands"
            / normalized_ligand
            / "preparations"
            / normalized_preparation
        )
        resolved = path.resolve()
        if self._root not in resolved.parents:
            raise self._preparation_not_found(ligand_id, preparation_id)
        return resolved

    @staticmethod
    def _write_execution_logs(directory: Path, stdout: str, stderr: str) -> None:
        with (directory / "stdout.log").open("x", encoding="utf-8", newline="") as stream:
            stream.write(stdout)
        with (directory / "stderr.log").open("x", encoding="utf-8", newline="") as stream:
            stream.write(stderr)

    @staticmethod
    def sanitize_filename(filename: str) -> str:
        basename = Path(filename.replace("\\", "/")).name
        sanitized = _SAFE_FILENAME.sub("_", basename).strip("._")
        return sanitized or "ligand.sdf"

    @staticmethod
    def _not_found(ligand_id: str) -> AnkoraDomainError:
        return AnkoraDomainError(
            code="LIGAND_NOT_FOUND",
            stage="ligand_storage",
            message="The requested ligand artifact is not available in this project.",
            status_code=404,
            details={"ligand_id": ligand_id},
        )

    @staticmethod
    def _library_not_found(library_id: str) -> AnkoraDomainError:
        return AnkoraDomainError(
            code="LIGAND_LIBRARY_NOT_FOUND",
            stage="ligand_storage",
            message="The requested ligand library is not available in this project.",
            status_code=404,
            details={"library_id": library_id},
        )

    @staticmethod
    def _filter_run_not_found(
        library_id: str, filter_run_id: str
    ) -> AnkoraDomainError:
        return AnkoraDomainError(
            code="LIGAND_FILTER_RUN_NOT_FOUND",
            stage="ligand_storage",
            message="The requested ligand-library filter run is not available.",
            status_code=404,
            details={"library_id": library_id, "filter_run_id": filter_run_id},
        )

    @staticmethod
    def _conformer_not_found(ligand_id: str, conformer_id: str) -> AnkoraDomainError:
        return AnkoraDomainError(
            code="LIGAND_CONFORMER_NOT_FOUND",
            stage="ligand_storage",
            message="The requested ligand conformer is not available in this project.",
            status_code=404,
            details={"ligand_id": ligand_id, "conformer_id": conformer_id},
        )

    @staticmethod
    def _state_not_found(ligand_id: str, state_id: str) -> AnkoraDomainError:
        return AnkoraDomainError(
            code="LIGAND_STATE_NOT_FOUND",
            stage="ligand_storage",
            message="The requested ligand chemical state is not available in this project.",
            status_code=404,
            details={"ligand_id": ligand_id, "state_id": state_id},
        )

    @staticmethod
    def _preparation_not_found(
        ligand_id: str, preparation_id: str
    ) -> AnkoraDomainError:
        return AnkoraDomainError(
            code="LIGAND_PREPARATION_NOT_FOUND",
            stage="ligand_storage",
            message="The requested ligand PDBQT preparation is not available.",
            status_code=404,
            details={"ligand_id": ligand_id, "preparation_id": preparation_id},
        )


def _first_object_after(document: str, key: str) -> str | None:
    """The balanced JSON object that follows `key`, if it fits in `document`."""
    start = document.find(key)
    if start < 0:
        return None
    start = document.find("{", start + len(key))
    if start < 0:
        return None
    depth = 0
    for index in range(start, len(document)):
        character = document[index]
        if character == "{":
            depth += 1
        elif character == "}":
            depth -= 1
            if depth == 0:
                return document[start : index + 1]
    return None
