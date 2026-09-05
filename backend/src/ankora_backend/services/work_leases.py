"""One-process lease ownership with durable periodic heartbeats."""

import threading
from datetime import UTC, datetime
from uuid import uuid4

from ankora_backend.persistence.work_lease_store import WorkLeaseStore
from ankora_backend.schemas.work_recovery import (
    WorkKind,
    WorkLeaseRecord,
    WorkLeaseState,
)


class WorkLeaseManager:
    def __init__(
        self,
        store: WorkLeaseStore,
        *,
        heartbeat_interval_seconds: float = 5.0,
    ) -> None:
        self._store = store
        self._heartbeat_interval_seconds = heartbeat_interval_seconds
        self._instance_id = str(uuid4())
        self._active: dict[tuple[WorkKind, str], WorkLeaseRecord] = {}
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def instance_id(self) -> str:
        return self._instance_id

    def acquire(self, work_kind: WorkKind, work_id: str) -> WorkLeaseRecord:
        now = datetime.now(UTC)
        record = WorkLeaseRecord(
            lease_id=str(uuid4()),
            work_kind=work_kind,
            work_id=work_id,
            owner_instance_id=self._instance_id,
            acquired_at=now,
            heartbeat_at=now,
        )
        with self._lock:
            self._store.write(record)
            self._active[(work_kind, work_id)] = record
            self._ensure_thread()
        return record

    def release(self, work_kind: WorkKind, work_id: str) -> None:
        with self._lock:
            record = self._active.pop((work_kind, work_id), None)
            if record is None:
                return
            now = datetime.now(UTC)
            self._store.write(
                record.model_copy(
                    update={
                        "heartbeat_at": now,
                        "state": WorkLeaseState.RELEASED,
                        "released_at": now,
                    }
                )
            )

    def heartbeat_once(self) -> None:
        now = datetime.now(UTC)
        with self._lock:
            for key, record in list(self._active.items()):
                updated = record.model_copy(update={"heartbeat_at": now})
                self._store.write(updated)
                self._active[key] = updated

    def shutdown(self) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=max(1.0, self._heartbeat_interval_seconds * 2))

    def _ensure_thread(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(
            target=self._heartbeat_loop,
            name="ankora-work-heartbeat",
            daemon=True,
        )
        self._thread.start()

    def _heartbeat_loop(self) -> None:
        while not self._stop.wait(self._heartbeat_interval_seconds):
            self.heartbeat_once()
