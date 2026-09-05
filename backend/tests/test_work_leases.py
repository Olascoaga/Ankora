"""Durable ownership evidence for long-running work."""

from uuid import uuid4

from ankora_backend.persistence.work_lease_store import WorkLeaseStore
from ankora_backend.schemas.work_recovery import WorkKind, WorkLeaseState
from ankora_backend.services.work_leases import WorkLeaseManager


def test_lease_is_heartbeated_and_released_durably(tmp_path) -> None:
    store = WorkLeaseStore(tmp_path)
    manager = WorkLeaseManager(store, heartbeat_interval_seconds=60)
    work_id = str(uuid4())

    acquired = manager.acquire(WorkKind.VINA_BATCH, work_id)
    manager.heartbeat_once()
    active = store.load(WorkKind.VINA_BATCH, work_id)

    assert active is not None
    assert active.state is WorkLeaseState.ACTIVE
    assert active.owner_instance_id == manager.instance_id
    assert active.heartbeat_at >= acquired.heartbeat_at

    manager.release(WorkKind.VINA_BATCH, work_id)
    manager.shutdown()
    released = store.load(WorkKind.VINA_BATCH, work_id)

    assert released is not None
    assert released.state is WorkLeaseState.RELEASED
    assert released.released_at is not None
    assert store.list_active() == []
