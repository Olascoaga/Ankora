"""Synthetic tests for the immutable GNINA screening-campaign correlation.

Every receptor, ligand, conformer, hash and executable here is synthetic and
carries no scientific meaning: these tests assert correlation and lifecycle
bookkeeping only, never a docking result. GNINA is never executed - the
service's worker submission is captured by a controlled executor, so the
durable record can be inspected at the moment it exists and before execution
could have started.
"""

import json
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError

from ankora_backend.adapters.engines.gnina import GninaInstallation
from ankora_backend.domain.errors import AnkoraDomainError
from ankora_backend.persistence.gnina_store import GninaJobStore
from ankora_backend.persistence.work_lease_store import WorkLeaseStore
from ankora_backend.schemas.binding_sites import BindingBox
from ankora_backend.schemas.docking import DockingJobPhase, DockingJobStatus
from ankora_backend.schemas.gnina import (
    GninaDockingParameters,
    GninaDockingRequest,
    GninaJobRecord,
    GninaToolIdentity,
)
from ankora_backend.schemas.receptors import ReceptorOutputStage, ReceptorPreparationStatus
from ankora_backend.services.gnina_docking import GninaDockingService
from ankora_backend.services.resource_arbiter import ResourceArbiter
from ankora_backend.services.work_leases import WorkLeaseManager

_BOX = BindingBox(center_x=0, center_y=0, center_z=0, size_x=10, size_y=10, size_z=10)
_RECEPTOR = b"synthetic receptor"
_LIGAND = b"synthetic ligand"
_CONFORMER = b"synthetic conformer"
_RUNNING = {"status": DockingJobStatus.RUNNING, "phase": DockingJobPhase.DOCKING}


def _request() -> GninaDockingRequest:
    return GninaDockingRequest(
        receptor_id="receptor",
        binding_site_id="site",
        ligand_id="ligand",
        ligand_preparation_id="preparation",
        parameters=GninaDockingParameters(compute="cpu"),
        acknowledge_inputs_and_scoring=True,
    )


def _queued_record(job_id: str | None = None, **updates: object) -> GninaJobRecord:
    return GninaJobRecord(
        job_id=job_id or str(uuid4()),
        status=DockingJobStatus.QUEUED,
        phase=DockingJobPhase.QUEUED,
        created_at=datetime.now(UTC),
        request=_request(),
        tool=GninaToolIdentity(version="1.3.3", sha256="a" * 64, architecture="x86_64"),
        box=_BOX,
        receptor_output_artifact_id="output",
        receptor_sha256="b" * 64,
        ligand_sha256="c" * 64,
        conformer_sha256="d" * 64,
        **updates,
    )


class _CapturedExecutor:
    """Accepts the worker submission without ever running it."""

    def __init__(self) -> None:
        self.submissions: list[tuple[object, ...]] = []
        self.failure: Exception | None = None

    def submit(self, _function: object, *args: object) -> None:
        if self.failure is not None:
            raise self.failure
        self.submissions.append(args)

    def shutdown(self, wait: bool = True) -> None:
        return None


def _stub_input_stores(tmp_path: Path) -> tuple[SimpleNamespace, SimpleNamespace, SimpleNamespace]:
    """Minimal stand-ins for the prepared-input stores `start` consults."""
    directory = tmp_path / "synthetic-inputs"
    directory.mkdir()
    receptor_path = directory / "receptor.pdbqt"
    ligand_path = directory / "ligand.pdbqt"
    conformer_path = directory / "conformer.sdf"
    receptor_path.write_bytes(_RECEPTOR)
    ligand_path.write_bytes(_LIGAND)
    conformer_path.write_bytes(_CONFORMER)
    receptors = SimpleNamespace(
        load_record=lambda _receptor_id: SimpleNamespace(
            status=ReceptorPreparationStatus.DOCKING_READY,
            outputs=[
                SimpleNamespace(
                    stage=ReceptorOutputStage.PDBQT,
                    artifact_id="receptor-output",
                    sha256=sha256(_RECEPTOR).hexdigest(),
                )
            ],
        ),
        content_path=lambda _receptor_id, _artifact_id: receptor_path,
    )
    sites = SimpleNamespace(
        load_record=lambda _site_id: SimpleNamespace(
            receptor_id="receptor", stale=False, box=_BOX
        )
    )
    ligands = SimpleNamespace(
        load_pdbqt_record=lambda _ligand_id, _preparation_id: SimpleNamespace(
            artifact=SimpleNamespace(
                ligand_id="ligand",
                sha256=sha256(_LIGAND).hexdigest(),
                conformer_id="conformer",
            )
        ),
        load_conformer_record=lambda _ligand_id, _conformer_id: SimpleNamespace(
            artifact=SimpleNamespace(ligand_id="ligand", sha256=sha256(_CONFORMER).hexdigest())
        ),
        pdbqt_content_path=lambda _ligand_id, _preparation_id: ligand_path,
        conformer_content_path=lambda _ligand_id, _conformer_id: conformer_path,
    )
    return receptors, sites, ligands


def _service(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        "ankora_backend.services.gnina_docking.require_current_inputs", lambda *_a, **_k: None
    )
    monkeypatch.setattr("ankora_backend.services.gnina_docking._linux_host", lambda: True)
    monkeypatch.setattr(
        "ankora_backend.services.gnina_docking.probe_gnina",
        lambda: GninaInstallation("/synthetic/gnina", "1.3.3", "a" * 64, "x86_64"),
    )
    receptors, sites, ligands = _stub_input_stores(tmp_path)
    store = GninaJobStore(tmp_path)
    arbiter = ResourceArbiter(
        cpu_threads=4,
        gpu_slots=1,
        memory_total_bytes=16 * 1024**3,
        memory_reserve_bytes=0,
        disk_path=tmp_path,
        disk_total_bytes=16 * 1024**3,
        disk_reserve_bytes=0,
        memory_available=lambda: 16 * 1024**3,
        disk_free=lambda: 16 * 1024**3,
    )
    leases = WorkLeaseManager(WorkLeaseStore(tmp_path))
    service = GninaDockingService(
        store=store,
        receptors=receptors,
        sites=sites,
        ligands=ligands,
        leases=leases,
        resources=arbiter,
    )
    # Retire the real worker pool, then take ownership of submission so no
    # GNINA execution can begin while the durable record is inspected.
    service.shutdown()
    executor = _CapturedExecutor()
    service._executor = executor
    return service, store, arbiter, leases, executor


def test_record_written_before_the_field_existed_still_parses(tmp_path: Path) -> None:
    """An old standalone job record has no campaign link and must stay readable."""
    store = GninaJobStore(tmp_path)
    record = _queued_record(store.new_job_id())
    legacy = record.model_dump(mode="json")
    del legacy["screening_campaign_id"]

    restored = GninaJobRecord.model_validate_json(json.dumps(legacy))
    assert restored.screening_campaign_id is None
    assert restored == record

    # The same absence, read back off disk and then updated as usual.
    store.create_job(record)
    path = store.job_directory(record.job_id) / "record.json"
    path.write_text(json.dumps(legacy, indent=2) + "\n", encoding="utf-8")
    assert store.load_job(record.job_id).screening_campaign_id is None
    store.update_job(store.load_job(record.job_id).model_copy(update=_RUNNING))
    reloaded = store.load_job(record.job_id)
    assert reloaded.status is DockingJobStatus.RUNNING
    assert reloaded.screening_campaign_id is None


def test_canonical_campaign_id_is_accepted() -> None:
    campaign_id = str(uuid4())
    assert _queued_record(screening_campaign_id=campaign_id).screening_campaign_id == campaign_id


@pytest.mark.parametrize(
    "malformed",
    [
        "",
        "not-a-uuid",
        "123e4567-e89b-12d3-a456",
        "123E4567-E89B-12D3-A456-426614174000",
        "{123e4567-e89b-12d3-a456-426614174000}",
        "urn:uuid:123e4567-e89b-12d3-a456-426614174000",
        "123e4567e89b12d3a456426614174000",
        " 123e4567-e89b-12d3-a456-426614174000",
    ],
)
def test_malformed_campaign_id_is_rejected(malformed: str) -> None:
    """Only the canonical spelling is stored, so recovery can match by equality."""
    with pytest.raises(ValidationError):
        _queued_record(screening_campaign_id=malformed)


def test_queued_record_carries_the_campaign_link_before_execution_can_start(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service, store, arbiter, leases, executor = _service(tmp_path, monkeypatch)
    campaign_id = str(uuid4())
    executed: list[object] = []
    monkeypatch.setattr(
        "ankora_backend.services.gnina_docking.execute_gnina",
        lambda **kwargs: executed.append(kwargs),
    )

    record = service.start(_request(), screening_campaign_id=campaign_id)

    # The worker was handed over but deliberately never run.
    assert len(executor.submissions) == 1
    assert executed == []
    assert record.status is DockingJobStatus.QUEUED
    assert record.screening_campaign_id == campaign_id
    durable = store.load_job(record.job_id)
    assert durable.status is DockingJobStatus.QUEUED
    assert durable.screening_campaign_id == campaign_id
    # The ligand stays the request's own field and is not duplicated.
    assert durable.request.ligand_id == "ligand"
    assert not hasattr(durable, "screening_ligand_id")
    assert not arbiter.snapshot().active_allocations
    leases.shutdown()


def test_ordinary_caller_records_no_campaign_link(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service, store, _arbiter, leases, executor = _service(tmp_path, monkeypatch)
    record = service.start(_request())
    assert record.screening_campaign_id is None
    assert store.load_job(record.job_id).screening_campaign_id is None
    assert len(executor.submissions) == 1
    leases.shutdown()


def test_invalid_campaign_id_creates_no_job(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service, store, arbiter, leases, executor = _service(tmp_path, monkeypatch)
    with pytest.raises(AnkoraDomainError) as caught:
        service.start(_request(), screening_campaign_id="not-a-uuid")
    assert caught.value.code == "GNINA_SCREENING_CAMPAIGN_ID_INVALID"
    assert store.list_jobs() == []
    assert executor.submissions == []
    assert not arbiter.snapshot().active_allocations
    leases.shutdown()


def test_pre_submit_failure_keeps_the_campaign_link_in_the_created_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A job can be durable before submission succeeds; its link must survive.

    This is the orphan case the field exists for: the record is already on
    disk, nothing is running, and the campaign never learned the job id.
    """
    service, store, arbiter, leases, executor = _service(tmp_path, monkeypatch)
    executor.failure = RuntimeError("synthetic submission failure")
    campaign_id = str(uuid4())

    with pytest.raises(RuntimeError):
        service.start(_request(), screening_campaign_id=campaign_id)

    jobs = store.list_jobs()
    assert len(jobs) == 1
    failed = jobs[0]
    assert failed.status is DockingJobStatus.FAILED
    assert failed.failure is not None and failed.failure.code == "GNINA_START_FAILED"
    assert failed.screening_campaign_id == campaign_id
    assert failed.poses == []
    assert not arbiter.snapshot().active_allocations
    leases.shutdown()


def test_campaign_link_cannot_be_changed_dropped_or_invented(tmp_path: Path) -> None:
    store = GninaJobStore(tmp_path)
    campaign_id = str(uuid4())
    linked = _queued_record(store.new_job_id(), screening_campaign_id=campaign_id)
    standalone = _queued_record(store.new_job_id())
    store.create_job(linked)
    store.create_job(standalone)

    for rejected in (None, str(uuid4())):
        with pytest.raises(AnkoraDomainError) as caught:
            store.update_job(linked.model_copy(update={"screening_campaign_id": rejected}))
        assert caught.value.code == "GNINA_SCREENING_CAMPAIGN_LINK_IMMUTABLE"
    with pytest.raises(AnkoraDomainError) as caught:
        store.update_job(standalone.model_copy(update={"screening_campaign_id": campaign_id}))
    assert caught.value.code == "GNINA_SCREENING_CAMPAIGN_LINK_IMMUTABLE"

    # Refusals changed nothing, and an ordinary lifecycle update is unaffected.
    assert store.load_job(linked.job_id).screening_campaign_id == campaign_id
    store.update_job(linked.model_copy(update=_RUNNING))
    store.update_job(standalone.model_copy(update=_RUNNING))
    assert store.load_job(linked.job_id).screening_campaign_id == campaign_id
    assert store.load_job(linked.job_id).status is DockingJobStatus.RUNNING
    assert store.load_job(standalone.job_id).screening_campaign_id is None
