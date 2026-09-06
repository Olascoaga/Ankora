"""SQLite-backed mutable state for large, artifact-owning batch records.

The human-readable ``record.json`` remains the portable snapshot of a batch.
While work is active, frequently changing entry rows and the small batch header
live in a rebuildable SQLite sidecar.  Historical JSON records are migrated by
*adding* that sidecar; their existing bytes are never rewritten by migration.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

from pydantic import BaseModel

_DATABASE_NAME = "batch_state.sqlite3"
_SCHEMA_VERSION = "1"
_TERMINAL_STATUSES = {"completed", "failed", "canceled"}
_STATE_LOCKS: dict[str, threading.RLock] = {}
_STATE_LOCKS_GUARD = threading.Lock()


def _state_lock(path: Path) -> threading.RLock:
    key = str(path.resolve())
    with _STATE_LOCKS_GUARD:
        lock = _STATE_LOCKS.get(key)
        if lock is None:
            lock = threading.RLock()
            _STATE_LOCKS[key] = lock
        return lock


class IncrementalBatchStore[RecordT: BaseModel, EntryT: BaseModel]:
    """Persist one batch header plus independently addressable entry rows."""

    def __init__(
        self,
        *,
        record_type: type[RecordT],
        entry_type: type[EntryT],
        best_result: Callable[[EntryT], float | None],
    ) -> None:
        self._record_type = record_type
        self._entry_type = entry_type
        self._best_result = best_result

    def database_path(self, directory: Path) -> Path:
        return directory / _DATABASE_NAME

    def create(self, directory: Path, record: RecordT) -> None:
        """Create the sidecar after the portable initial JSON exists."""
        with _state_lock(directory):
            path = self.database_path(directory)
            if path.exists():
                raise FileExistsError(path)
            self._build_database(path, record)

    def migrate(self, directory: Path) -> bool:
        """Add a sidecar for a legacy JSON batch without changing that JSON."""
        with _state_lock(directory):
            path = self.database_path(directory)
            if path.is_file():
                return False
            raw = (directory / "record.json").read_bytes()
            record = self._record_type.model_validate_json(raw)
            self._build_database(path, record)
            return True

    def load(self, directory: Path) -> RecordT:
        with _state_lock(directory):
            self._ensure_database(directory)
            with self._connect(directory) as database:
                summary = self._summary(database)
                entries = self._entries(database)
        return self._record_type.model_validate({**summary, "entries": entries})

    def load_overview(self, directory: Path) -> RecordT:
        """Load the batch header and at most its best row, never the full batch."""
        with _state_lock(directory):
            self._ensure_database(directory)
            with self._connect(directory) as database:
                summary = self._summary(database)
                row = database.execute(
                    """
                    SELECT payload_json
                    FROM entries
                    ORDER BY (best_result IS NULL), best_result, source_index, ligand_id
                    LIMIT 1
                    """
                ).fetchone()
        entries = [] if row is None else [json.loads(str(row[0]))]
        return self._record_type.model_validate({**summary, "entries": entries})

    def load_summary(self, directory: Path) -> dict[str, Any]:
        with _state_lock(directory):
            self._ensure_database(directory)
            with self._connect(directory) as database:
                return self._summary(database)

    def load_entry(self, directory: Path, ligand_id: str) -> EntryT | None:
        with _state_lock(directory):
            self._ensure_database(directory)
            with self._connect(directory) as database:
                row = database.execute(
                    "SELECT payload_json FROM entries WHERE ligand_id = ?",
                    (ligand_id,),
                ).fetchone()
        if row is None:
            return None
        return self._entry_type.model_validate_json(str(row[0]))

    def entries_after_revision(self, directory: Path, revision: int) -> list[EntryT]:
        with _state_lock(directory):
            self._ensure_database(directory)
            with self._connect(directory) as database:
                rows = database.execute(
                    """
                    SELECT payload_json FROM entries
                    WHERE revision > ?
                    ORDER BY source_index, ligand_id
                    """,
                    (revision,),
                ).fetchall()
        return [self._entry_type.model_validate_json(str(row[0])) for row in rows]

    def ligand_ids_with_status(self, directory: Path, status: str) -> list[str]:
        with _state_lock(directory):
            self._ensure_database(directory)
            with self._connect(directory) as database:
                rows = database.execute(
                    """
                    SELECT ligand_id FROM entries
                    WHERE status = ?
                    ORDER BY source_index, ligand_id
                    """,
                    (status,),
                ).fetchall()
        return [str(row[0]) for row in rows]

    def page(
        self,
        directory: Path,
        *,
        offset: int,
        limit: int,
        status: str | None = None,
        search: str | None = None,
    ) -> tuple[list[EntryT], int]:
        """Return one SQL-windowed page in engine-native best-result order."""
        clauses: list[str] = []
        parameters: list[object] = []
        if status is not None:
            clauses.append("status = ?")
            parameters.append(status)
        if search:
            clauses.append("instr(search_text, ?) > 0")
            parameters.append(search.casefold())
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        with _state_lock(directory):
            self._ensure_database(directory)
            with self._connect(directory) as database:
                total = int(
                    database.execute(
                        f"SELECT COUNT(*) FROM entries{where}",  # noqa: S608
                        parameters,
                    ).fetchone()[0]
                )
                rows = database.execute(
                    f"""
                    SELECT payload_json FROM entries{where}
                    ORDER BY (best_result IS NULL), best_result, source_index, ligand_id
                    LIMIT ? OFFSET ?
                    """,  # noqa: S608
                    [*parameters, limit, offset],
                ).fetchall()
        return (
            [self._entry_type.model_validate_json(str(row[0])) for row in rows],
            total,
        )

    def update(
        self,
        directory: Path,
        record: RecordT,
        *,
        changed_entries: Sequence[EntryT] | None = None,
    ) -> RecordT:
        """Persist a small header and only the supplied changed entry rows.

        ``None`` deliberately means full compatibility update for callers that
        have not identified a delta.  High-frequency execution paths pass the
        exact changed row(s), so they remain O(changes), not O(batch size).
        """
        with _state_lock(directory):
            self._ensure_database(directory)
            selected = list(
                record.__dict__["entries"]
                if changed_entries is None
                else changed_entries
            )
            with self._connect(directory) as database:
                database.execute("BEGIN IMMEDIATE")
                for entry in selected:
                    self._upsert_entry(database, entry)
                summary = record.model_dump(mode="json", exclude={"entries"})
                if selected:
                    self._apply_counts(database, summary)
                self._write_summary(database, summary)
                database.commit()
            if str(summary.get("status")) in _TERMINAL_STATUSES:
                persisted = self.load(directory)
                self._materialize(directory, persisted)
                return persisted
            return record.model_copy(update=summary)

    def update_entry(self, directory: Path, entry: EntryT) -> EntryT:
        """Atomically update one row, the batch revision, and exact counters."""
        with _state_lock(directory):
            self._ensure_database(directory)
            with self._connect(directory) as database:
                database.execute("BEGIN IMMEDIATE")
                summary = self._summary(database)
                next_revision = int(summary.get("revision", 0)) + 1
                updated = entry.model_copy(update={"revision": next_revision})
                previous = database.execute(
                    "SELECT status FROM entries WHERE ligand_id = ?",
                    (str(entry.__dict__["ligand_id"]),),
                ).fetchone()
                if previous is None:
                    raise ValueError("Incremental batch entry no longer exists")
                self._adjust_counts(
                    summary,
                    previous_status=str(previous[0]),
                    updated_status=self._status(updated),
                )
                self._upsert_entry(database, updated)
                summary["revision"] = next_revision
                self._write_summary(database, summary)
                database.commit()
        return updated

    def _ensure_database(self, directory: Path) -> None:
        if not self.database_path(directory).is_file():
            self.migrate(directory)

    def _build_database(self, path: Path, record: RecordT) -> None:
        temporary = path.with_name(f"{path.name}.{uuid4().hex}.tmp")
        try:
            database = sqlite3.connect(temporary)
            try:
                database.execute("PRAGMA synchronous = FULL")
                database.executescript(
                    """
                    CREATE TABLE metadata (
                        key TEXT PRIMARY KEY,
                        value TEXT NOT NULL
                    );
                    CREATE TABLE entries (
                        ligand_id TEXT PRIMARY KEY,
                        source_index INTEGER NOT NULL,
                        revision INTEGER NOT NULL,
                        status TEXT NOT NULL,
                        search_text TEXT NOT NULL,
                        best_result REAL,
                        payload_json TEXT NOT NULL
                    );
                    CREATE UNIQUE INDEX entries_source_order
                        ON entries(source_index, ligand_id);
                    CREATE INDEX entries_status
                        ON entries(status, source_index, ligand_id);
                    CREATE INDEX entries_best_result
                        ON entries((best_result IS NULL), best_result, source_index, ligand_id);
                    """
                )
                database.execute(
                    "INSERT INTO metadata(key, value) VALUES('schema_version', ?)",
                    (_SCHEMA_VERSION,),
                )
                summary = record.model_dump(mode="json", exclude={"entries"})
                self._write_summary(database, summary)
                for entry in record.__dict__["entries"]:
                    self._upsert_entry(database, entry)
                database.commit()
            finally:
                database.close()
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)

    @contextmanager
    def _connect(self, directory: Path) -> Iterator[sqlite3.Connection]:
        database = sqlite3.connect(self.database_path(directory), timeout=30)
        try:
            database.execute("PRAGMA synchronous = FULL")
            yield database
        finally:
            database.close()

    def _entries(self, database: sqlite3.Connection) -> list[dict[str, Any]]:
        rows = database.execute(
            "SELECT payload_json FROM entries ORDER BY source_index, ligand_id"
        ).fetchall()
        return [cast(dict[str, Any], json.loads(str(row[0]))) for row in rows]

    @staticmethod
    def _summary(database: sqlite3.Connection) -> dict[str, Any]:
        version = database.execute(
            "SELECT value FROM metadata WHERE key = 'schema_version'"
        ).fetchone()
        if version is None or str(version[0]) != _SCHEMA_VERSION:
            found = "missing" if version is None else str(version[0])
            raise ValueError(
                f"Unsupported incremental batch-state schema: {found}"
            )
        row = database.execute(
            "SELECT value FROM metadata WHERE key = 'summary_json'"
        ).fetchone()
        if row is None:
            raise ValueError("Incremental batch state has no summary")
        return cast(dict[str, Any], json.loads(str(row[0])))

    @staticmethod
    def _write_summary(database: sqlite3.Connection, summary: dict[str, Any]) -> None:
        payload = json.dumps(
            summary, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        database.execute(
            """
            INSERT INTO metadata(key, value) VALUES('summary_json', ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (payload,),
        )

    def _upsert_entry(self, database: sqlite3.Connection, entry: EntryT) -> None:
        fields = entry.__dict__
        ligand_id = str(fields["ligand_id"])
        source_index = int(fields["source_index"])
        revision = int(fields.get("revision", 0))
        status = self._status(entry)
        name = str(fields.get("name", ""))
        smiles = str(fields.get("canonical_smiles", "") or "")
        payload = entry.model_dump_json()
        database.execute(
            """
            INSERT INTO entries(
                ligand_id, source_index, revision, status, search_text,
                best_result, payload_json
            ) VALUES(?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(ligand_id) DO UPDATE SET
                source_index = excluded.source_index,
                revision = excluded.revision,
                status = excluded.status,
                search_text = excluded.search_text,
                best_result = excluded.best_result,
                payload_json = excluded.payload_json
            """,
            (
                ligand_id,
                source_index,
                revision,
                status,
                f"{name}\n{smiles}".casefold(),
                self._best_result(entry),
                payload,
            ),
        )

    @staticmethod
    def _apply_counts(database: sqlite3.Connection, summary: dict[str, Any]) -> None:
        counts = {
            str(status): int(count)
            for status, count in database.execute(
                "SELECT status, COUNT(*) FROM entries GROUP BY status"
            ).fetchall()
        }
        succeeded = counts.get("completed", 0)
        failed = counts.get("failed", 0)
        canceled = counts.get("canceled", 0)
        summary["selected_count"] = sum(counts.values())
        summary["completed_count"] = succeeded + failed + canceled
        summary["succeeded_count"] = succeeded
        summary["failed_count"] = failed
        summary["canceled_count"] = canceled

    @staticmethod
    def _adjust_counts(
        summary: dict[str, Any], *, previous_status: str, updated_status: str
    ) -> None:
        if previous_status == updated_status:
            return

        def apply(status: str, direction: int) -> None:
            field = {
                "completed": "succeeded_count",
                "failed": "failed_count",
                "canceled": "canceled_count",
            }.get(status)
            if field is None:
                return
            summary[field] = int(summary.get(field, 0)) + direction
            summary["completed_count"] = (
                int(summary.get("completed_count", 0)) + direction
            )

        apply(previous_status, -1)
        apply(updated_status, 1)

    @staticmethod
    def _status(model: BaseModel) -> str:
        value = model.__dict__["status"]
        return str(getattr(value, "value", value))

    @staticmethod
    def _materialize(directory: Path, record: RecordT) -> None:
        """Write one portable terminal snapshot after incremental execution."""
        final_path = directory / "record.json"
        temporary = final_path.with_name(f"{final_path.name}.{uuid4().hex}.tmp")
        try:
            with temporary.open("x", encoding="utf-8", newline="\n") as stream:
                json.dump(
                    record.model_dump(mode="json"),
                    stream,
                    indent=2,
                    ensure_ascii=False,
                )
                stream.write("\n")
            os.replace(temporary, final_path)
        finally:
            temporary.unlink(missing_ok=True)
