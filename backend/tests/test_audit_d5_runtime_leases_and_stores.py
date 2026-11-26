"""Regression tests for D5 Unit 3: worker lease/resource containment, incremental batch store
monotonic counters, crash-isolated startup recovery, AutoGrid SHA-256 cache verification,
heartbeat resilience, ProjectRuntime serialization, and persistence hygiene.

All jobs, records, and files in this module are explicitly labelled synthetic fixtures.
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from ankora_backend.domain.errors import AnkoraDomainError
from ankora_backend.persistence.atomic_io import atomic_write_json
from ankora_backend.persistence.autodock4_store import AutoDock4JobStore
from ankora_backend.persistence.autodock_gpu_store import AutoDockGpuJobStore
from ankora_backend.persistence.autogrid_store import AutoGridMapStore
from ankora_backend.persistence.binding_site_store import BindingSiteArtifactStore
from ankora_backend.persistence.docking_store import DockingArtifactStore
from ankora_backend.persistence.gnina_screening_store import GninaScreeningStore
from ankora_backend.persistence.gnina_store import GninaJobStore
from ankora_backend.persistence.ligand_store import LigandArtifactStore
from ankora_backend.persistence.project_store import ProjectStore
from ankora_backend.persistence.receptor_store import ReceptorArtifactStore
from ankora_backend.persistence.work_lease_store import WorkLeaseStore
from ankora_backend.schemas.autogrid import (
    AutoGridExecutionEvidence,
    AutoGridGeometry,
    AutoGridJobPhase,
    AutoGridJobStatus,
    AutoGridLigandSource,
    AutoGridMapArtifact,
    AutoGridMapJobRecord,
    AutoGridMapKind,
    AutoGridMapSetRecord,
    AutoGridMapSetRequest,
    AutoGridPreflight,
    AutoGridToolIdentity,
)
from ankora_backend.schemas.binding_sites import BindingBox
from ankora_backend.schemas.docking import (
    DockingJobPhase,
    DockingJobStatus,
    VinaBatchDockingParameters,
    VinaBatchDockingRecord,
    VinaBatchDockingRequest,
    VinaBatchLigandResult,
)
from ankora_backend.schemas.provenance import ProvenanceEvent, ToolIdentity
from ankora_backend.schemas.results_catalog import ReproducibilityAssessment
from ankora_backend.schemas.work_recovery import WorkKind, WorkLeaseState
from ankora_backend.services.autogrid_maps import AutoGridMapService
from ankora_backend.services.campaign_export import CampaignExportService, ExportedCampaign
from ankora_backend.services.project_runtime import ProjectRuntime
from ankora_backend.services.resource_arbiter import ResourceArbiter
from ankora_backend.services.work_leases import WorkLeaseManager
from ankora_backend.services.work_recovery import InterruptedWorkRecovery


def test_d5_004_autogrid_run_job_releases_leases_and_marks_failed_on_unexpected_error(
    tmp_path: Path,
) -> None:
    """D5-004: Unexpected exception inside AutoGrid _run_job transitions job to FAILED
    and releases both ResourceLease and WorkLease plus _forget(job_id)."""
    map_store = AutoGridMapStore(tmp_path)
    lease_store = WorkLeaseStore(tmp_path)
    lease_mgr = WorkLeaseManager(lease_store, heartbeat_interval_seconds=60.0)
    released = {"resource": False}

    class _FakeLease:
        def release(self) -> None:
            released["resource"] = True

    class _FakeResources:
        def acquire(self, *_: object, **__: object) -> _FakeLease:
            return _FakeLease()

    svc = AutoGridMapService(
        map_store=map_store,
        receptor_store=ReceptorArtifactStore(tmp_path),
        binding_site_store=BindingSiteArtifactStore(tmp_path),
        ligand_store=LigandArtifactStore(tmp_path),
        lease_manager=lease_mgr,
        resource_arbiter=_FakeResources(),  # type: ignore[arg-type]
    )
    job_id = map_store.new_job_id()
    now = datetime.now(UTC)
    req = AutoGridMapSetRequest(
        receptor_id=str(uuid4()),
        binding_site_id=str(uuid4()),
        source=AutoGridLigandSource.LIGAND_PREPARATION,
        ligand_id=str(uuid4()),
        ligand_preparation_id=str(uuid4()),
    )
    ag_tool = AutoGridToolIdentity(
        tool=ToolIdentity(name="AutoGrid4", version="4.2.6"),
        executable_path="/synthetic/autogrid4",
        sha256="c" * 64,
        architecture="x86_64",
        max_receptor_types=16,
        max_ligand_types=14,
        max_maps=16,
        max_grid_points=126,
    )
    geom = AutoGridGeometry(
        spacing_angstrom=0.375,
        npts=(26, 26, 26),
        requested_size_angstrom=(10.0, 10.0, 10.0),
        realized_size_angstrom=(9.75, 9.75, 9.75),
    )
    preflight = AutoGridPreflight(
        receptor_atom_types=["C", "N"],
        ligand_atom_types=["C", "N"],
        selected_count=1,
        prepared_count=1,
        compatible_count=1,
        incompatible_count=0,
    )
    job = AutoGridMapJobRecord(
        job_id=job_id,
        status=AutoGridJobStatus.QUEUED,
        phase=AutoGridJobPhase.QUEUED,
        created_at=now,
        request=req,
        identity_key="a" * 64,
        geometry=geom,
        preflight=preflight,
        autogrid=ag_tool,
    )
    map_store.create_job(job)
    ev = threading.Event()
    svc._cancel_events[job_id] = ev  # noqa: SLF001

    def _boom(*_: object, **__: object) -> object:
        raise RuntimeError("synthetic unexpected autogrid crash")

    svc._generate = _boom  # type: ignore[method-assign]  # noqa: SLF001
    prepared = SimpleNamespace(geometry=job.geometry, preflight=job.preflight)
    svc._run_job(job_id, prepared, ev)  # type: ignore[arg-type]  # noqa: SLF001

    lease_mgr.shutdown()
    assert released["resource"] is True
    assert svc.has_active_work() is False
    loaded = map_store.load_job(job_id)
    assert loaded.status is AutoGridJobStatus.FAILED
    assert loaded.failure is not None
    assert loaded.failure.code == "AUTOGRID_JOB_INTERNAL_ERROR"
    lease = lease_store.load(WorkKind.AUTOGRID_JOB, job_id)
    assert lease is not None and lease.state is WorkLeaseState.RELEASED


def test_d5_005_incremental_batch_header_update_preserves_live_counts_and_monotonic_revision(
    tmp_path: Path,
) -> None:
    """D5-005: Header-only update(..., changed_entries=[]) never overwrites live SQLite
    counts with stale overview counters and advances revision monotonically."""
    store = DockingArtifactStore(tmp_path)
    batch_id = store.new_batch_id()
    now = datetime.now(UTC)
    lig_a = str(uuid4())
    lig_b = str(uuid4())
    record = VinaBatchDockingRecord(
        batch_id=batch_id,
        status=DockingJobStatus.RUNNING,
        phase=DockingJobPhase.DOCKING,
        created_at=now,
        started_at=now,
        request=VinaBatchDockingRequest(
            receptor_id=str(uuid4()),
            binding_site_id=str(uuid4()),
            library_id=str(uuid4()),
            filter_run_id=str(uuid4()),
            parameters=VinaBatchDockingParameters(exhaustiveness=4, num_modes=1, seed=1),
            acknowledge_inputs_and_scoring=True,
        ),
        tool=ToolIdentity(name="AutoDock Vina", version="1.2.7"),
        receptor_output_artifact_id="rec-out",
        receptor_sha256="1" * 64,
        selection_manifest_artifact_id=str(uuid4()),
        selection_manifest_sha256="2" * 64,
        selected_count=2,
        worker_count=1,
        threads_per_ligand=1,
        completed_count=0,
        succeeded_count=0,
        failed_count=0,
        canceled_count=0,
        revision=1,
        entries=[
            VinaBatchLigandResult(
                ligand_id=lig_a,
                name="lig-a",
                source_index=0,
                status=DockingJobStatus.QUEUED,
                phase=DockingJobPhase.QUEUED,
            ),
            VinaBatchLigandResult(
                ligand_id=lig_b,
                name="lig-b",
                source_index=1,
                status=DockingJobStatus.QUEUED,
                phase=DockingJobPhase.QUEUED,
            ),
        ],
    )
    store.create_batch(record)

    # Stale snapshot taken BEFORE worker completes lig_a:
    stale_overview = store.load_batch_overview(batch_id)
    assert stale_overview.succeeded_count == 0
    assert stale_overview.revision == 1

    # Worker completes lig_a atomically via update_batch_entry:
    updated_entry = store.update_batch_entry(
        batch_id,
        record.entries[0].model_copy(
            update={"status": DockingJobStatus.COMPLETED, "phase": DockingJobPhase.COMPLETE}
        ),
    )
    assert updated_entry.revision == 2

    # Concurrent cancel writes header-only update using stale_overview (changed_entries=[]):
    store.update_batch_record(
        stale_overview.model_copy(
            update={"status": DockingJobStatus.CANCEL_REQUESTED, "revision": 2}
        ),
        changed_entries=[],
    )

    after = store.load_batch_overview(batch_id)
    assert after.status is DockingJobStatus.CANCEL_REQUESTED
    assert after.succeeded_count == 1
    assert after.completed_count == 1
    assert after.revision >= 3


def test_d5_010_recovery_survives_corrupt_stores_and_sweeps_zombie_leases(tmp_path: Path) -> None:
    """D5-010: Corrupt Vina batch JSON + corrupt GNINA screening SQLite DB do not crash
    reconcile(), and zombie active leases for already-terminal work are closed."""
    proj = tmp_path / "projects" / "default"
    corrupt_batch = proj / "results" / "docking_batches" / str(uuid4())
    corrupt_batch.mkdir(parents=True)
    (corrupt_batch / "record.json").write_text("{corrupt json", encoding="utf-8")

    corrupt_gnina = proj / "results" / "gnina_screening_campaigns" / str(uuid4())
    corrupt_gnina.mkdir(parents=True)
    (corrupt_gnina / "campaign_state.sqlite3").write_bytes(b"not a sqlite database")

    lease_store = WorkLeaseStore(tmp_path)
    lease_mgr = WorkLeaseManager(lease_store, heartbeat_interval_seconds=60.0)
    zombie_id = str(uuid4())
    lease_mgr.acquire(WorkKind.VINA_JOB, zombie_id)
    lease_mgr.shutdown()
    assert len(lease_store.list_active()) == 1

    recovery = InterruptedWorkRecovery(
        docking=DockingArtifactStore(tmp_path),
        autogrid=AutoGridMapStore(tmp_path),
        autodock4=AutoDock4JobStore(tmp_path),
        autodock_gpu=AutoDockGpuJobStore(tmp_path),
        leases=lease_store,
        gnina=GninaJobStore(tmp_path),
        gnina_screening=GninaScreeningStore(tmp_path),
    )
    summary = recovery.reconcile()
    assert summary.items == []
    assert lease_store.list_active() == []
    closed = lease_store.load(WorkKind.VINA_JOB, zombie_id)
    assert closed is not None and closed.state is WorkLeaseState.RECONCILED


def test_d5_011_autogrid_store_refuses_tampered_cached_map_files(tmp_path: Path) -> None:
    """D5-011: find_by_identity() verifies both size_bytes and SHA-256 of every cached map."""
    store = AutoGridMapStore(tmp_path)
    map_set_id = store.new_map_set_id()
    directory = store.create_map_set_directory(map_set_id)
    content = b"GRID_PARAMETER_FILE synthetic.gpf\nDATA 1.0 2.0 3.0\n"
    map_file = directory / "receptor.C.map"
    map_file.write_bytes(content)

    now = datetime.now(UTC)
    identity = "f" * 64
    rec_id = str(uuid4())
    site_id = str(uuid4())
    art_id = str(uuid4())
    ag_tool = AutoGridToolIdentity(
        tool=ToolIdentity(name="AutoGrid4", version="4.2.6"),
        executable_path="/synthetic/autogrid4",
        sha256="c" * 64,
        architecture="x86_64",
        max_receptor_types=16,
        max_ligand_types=14,
        max_maps=16,
        max_grid_points=126,
    )
    record = AutoGridMapSetRecord(
        map_set_id=map_set_id,
        identity_key=identity,
        created_at=now,
        request=AutoGridMapSetRequest(
            receptor_id=rec_id,
            binding_site_id=site_id,
            source=AutoGridLigandSource.LIGAND_PREPARATION,
            ligand_id=str(uuid4()),
            ligand_preparation_id=str(uuid4()),
        ),
        receptor_id=rec_id,
        receptor_output_artifact_id="rec-out",
        receptor_sha256="1" * 64,
        binding_site_id=site_id,
        box=BindingBox(center_x=0, center_y=0, center_z=0, size_x=10, size_y=10, size_z=10),
        geometry=AutoGridGeometry(
            spacing_angstrom=0.375,
            npts=(26, 26, 26),
            requested_size_angstrom=(10.0, 10.0, 10.0),
            realized_size_angstrom=(9.75, 9.75, 9.75),
        ),
        preflight=AutoGridPreflight(
            receptor_atom_types=["C"],
            ligand_atom_types=["C"],
            selected_count=1,
            prepared_count=1,
            compatible_count=1,
            incompatible_count=0,
        ),
        autogrid=ag_tool,
        gpf_sha256="2" * 64,
        field_artifact_id=art_id,
        execution=AutoGridExecutionEvidence(
            command=["autogrid4"],
            exit_code=0,
            duration_seconds=0.1,
            stdout="",
            stderr="",
            successful_completion_logged=True,
        ),
        artifacts=[
            AutoGridMapArtifact(
                artifact_id=art_id,
                kind=AutoGridMapKind.AFFINITY,
                atom_type="C",
                filename="receptor.C.map",
                sha256=sha256(content).hexdigest(),
                size_bytes=len(content),
                content_url="/maps/1",
            )
        ],
        provenance=ProvenanceEvent(
            event_id=str(uuid4()),
            event_type="autogrid_maps_generated",
            timestamp=now,
            input_artifacts=["rec-out"],
            output_artifacts=[map_set_id],
            tool=ToolIdentity(name="AutoGrid4", version="4.2.6"),
        ),
    )
    store.write_record(record)
    assert store.find_by_identity(identity) is not None

    # Same-length 1-byte corruption MUST reject cache reuse:
    map_file.write_bytes(content[:-1] + b"X")
    assert store.find_by_identity(identity) is None


def test_d5_012_work_lease_heartbeat_survives_transient_oserror(tmp_path: Path) -> None:
    """D5-012: A transient PermissionError during heartbeat write does not kill the thread."""
    lease_store = WorkLeaseStore(tmp_path)
    calls = {"count": 0}
    real_write = lease_store.write

    def _flaky_write(rec: object) -> None:
        calls["count"] += 1
        if calls["count"] == 2:
            raise PermissionError("simulated Windows AV lock")
        real_write(rec)  # type: ignore[arg-type]

    lease_store.write = _flaky_write  # type: ignore[method-assign]
    mgr = WorkLeaseManager(lease_store, heartbeat_interval_seconds=0.05)
    try:
        mgr.acquire(WorkKind.VINA_JOB, str(uuid4()))
        time.sleep(0.2)
        assert mgr._thread is not None and mgr._thread.is_alive()  # noqa: SLF001
        assert calls["count"] >= 3
    finally:
        mgr.shutdown()


def test_d5_013_project_runtime_run_locked_serializes_against_activate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """D5-013: ProjectRuntime.run_locked holds the project-switch lock."""
    monkeypatch.setenv("ANKORA_DATA_DIR", str(tmp_path))
    projects = ProjectStore(tmp_path)
    p2 = projects.create("Second Project")
    runtime = ProjectRuntime(projects=projects, resources=ResourceArbiter.from_environment())
    state = SimpleNamespace()
    runtime.publish(state)
    entered = threading.Event()
    release = threading.Event()
    switched = threading.Event()

    def _holder() -> None:
        def _work() -> None:
            entered.set()
            release.wait(timeout=2.0)

        runtime.run_locked(_work)

    t1 = threading.Thread(target=_holder)
    t1.start()
    assert entered.wait(timeout=2.0)

    def _switcher() -> None:
        runtime.activate(p2.project_id, state)
        switched.set()

    t2 = threading.Thread(target=_switcher)
    t2.start()
    time.sleep(0.1)
    assert not switched.is_set()
    release.set()
    t1.join(timeout=2.0)
    t2.join(timeout=2.0)
    assert switched.is_set()
    assert runtime.active_project_id == p2.project_id
    runtime.shutdown()


def test_d5_021_d5_022_export_validates_destination_first_atomic_io_and_store_logging(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """D5-021 & D5-022:
    - Invalid export destination fails 422 with zero orphan directories under exports/.
    - atomic_write_json writes cleanly with zero leftover .tmp files.
    - Corrupt store records log a WARNING during list_*() instead of failing silently.
    """
    target = tmp_path / "sample.json"
    atomic_write_json(target, {"ok": True})
    assert list(tmp_path.glob("*.tmp")) == []
    assert target.is_file()

    # Corrupt AutoDock4 job directory logs warning on list_jobs()
    ad4_store = AutoDock4JobStore(tmp_path)
    bad_dir = tmp_path / "projects" / "default" / "results" / "autodock4_jobs" / str(uuid4())
    bad_dir.mkdir(parents=True)
    (bad_dir / "record.json").write_text("{corrupt", encoding="utf-8")
    with caplog.at_level(logging.WARNING):
        assert ad4_store.list_jobs() == []
    assert any("Skipping unreadable AutoDock4 job" in rec.message for rec in caplog.records)

    # Export validates destination before creating exports/<id>/
    exports_root = tmp_path / "projects" / "default" / "exports"
    export_svc = CampaignExportService(
        root=tmp_path,
        docking_store=DockingArtifactStore(tmp_path),
        autodock4_store=ad4_store,
        autodock_gpu_store=AutoDockGpuJobStore(tmp_path),
        binding_site_store=BindingSiteArtifactStore(tmp_path),
    )
    export_svc._load = lambda *_: ExportedCampaign(  # type: ignore[method-assign]  # noqa: SLF001
        engine="AutoDock Vina",
        engine_version="1.2.7",
        backend=None,
        value_column="vina_score_kcal_mol",
        reproducibility=ReproducibilityAssessment(),
        receptor_id="r",
        receptor_sha256="1" * 64,
        binding_site_id="s",
        box={},
        map_set_id=None,
        map_set_identity_key=None,
        selection_manifest_sha256="2" * 64,
        library_id="l",
        filter_run_id="f",
        parameters={},
        executable_sha256=None,
        device_name=None,
        selected_count=0,
        succeeded_count=0,
        failed_count=0,
        rows=[],
    )
    with pytest.raises(AnkoraDomainError) as err:
        export_svc.export_campaign(
            source_kind="vina_batch",
            batch_id=str(uuid4()),
            destination=str(tmp_path / "does_not_exist_dir"),
        )
    assert err.value.status_code == 422
    assert not exports_root.exists() or list(exports_root.iterdir()) == []
