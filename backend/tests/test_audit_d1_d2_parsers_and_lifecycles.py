"""Regression tests for Audit Unit 5: parser finiteness/epdb guards and docking worker lifecycles.

Covers verified findings:
- D1-003: AutoDock4 epdb parser requires finite (1)/(3)/(4) terms and never falls back to biased
          estimated energy when (4) Unbound == 0.00.
- D2-014: AutoDock4 & Vina v0.2 parsers reject non-finite floats and duplicate run numbers.
- D1-005: AutoDock4DockingService._run containment + WorkLease/ResourceLease cleanup on preamble
          and unexpected worker failures.
- D1-006: AutoDock4DockingService._run_batch and _run_batch_entry containment & ligand isolation.
- D1-007: GninaScreeningService._run reconciles stranded non-terminal campaigns while respecting
          active child jobs and do-not-recover domain codes.
- D1-008: VinaDockingService._run and _run_batch containment + WorkLease/ResourceLease cleanup.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, cast

import pytest

from ankora_backend.adapters.engines.autodock4_job import (
    ParsedAutoDock4EpdbResult,
    parse_autodock4_epdb_dlg,
    parse_autodock4_log,
)
from ankora_backend.adapters.engines.vina_v02 import parse_vina_poses, parse_vina_stdout_energy
from ankora_backend.domain.errors import AnkoraDomainError
from ankora_backend.schemas.autodock4 import (
    AutoDock4Failure,
    AutoDock4JobPhase,
    AutoDock4JobStatus,
)
from ankora_backend.schemas.binding_sites import BindingBox
from ankora_backend.schemas.docking import DockingJobPhase, DockingJobStatus, VinaDockingParameters
from ankora_backend.schemas.work_recovery import WorkKind
from ankora_backend.services.autodock4_docking import AutoDock4DockingService
from ankora_backend.services.gnina_screening_service import GninaScreeningService
from ankora_backend.services.vina_docking import VinaDockingService

# ---------------------------------------------------------------------------
# D1-003 & D2-014: AutoDock4 & Vina v0.2 parsers
# ---------------------------------------------------------------------------


def test_d1_003_epdb_requires_finite_component_terms() -> None:
    valid_dlg = b"""\
epdb: USER    Estimated Free Energy of Binding    =   -7.50 kcal/mol  [=(1)+(2)+(3)-(4)]
epdb: USER    (1) Final Intermolecular Energy     =   -8.20 kcal/mol
epdb: USER    (2) Final Total Internal Energy     =   +0.10 kcal/mol
epdb: USER    (3) Torsional Free Energy           =   +0.60 kcal/mol
epdb: USER    (4) Unbound System's Energy         =   +0.00 kcal/mol
Successful Completion
"""
    parsed = parse_autodock4_epdb_dlg(valid_dlg)
    assert parsed.bound_unbound_free_energy_kcal_mol == pytest.approx(-7.6, abs=1e-9)

    missing_inter = b"""\
epdb: USER    Estimated Free Energy of Binding    =   -7.50 kcal/mol  [=(1)+(2)+(3)-(4)]
epdb: USER    (2) Final Total Internal Energy     =   +0.10 kcal/mol
epdb: USER    (3) Torsional Free Energy           =   +0.60 kcal/mol
epdb: USER    (4) Unbound System's Energy         =   +0.00 kcal/mol
Successful Completion
"""
    with pytest.raises(AnkoraDomainError) as exc_inter:
        parse_autodock4_epdb_dlg(missing_inter)
    assert exc_inter.value.code == "AUTODOCK4_OUTPUT_INVALID"

    missing_tors = b"""\
epdb: USER    Estimated Free Energy of Binding    =   -7.50 kcal/mol  [=(1)+(2)+(3)-(4)]
epdb: USER    (1) Final Intermolecular Energy     =   -8.20 kcal/mol
epdb: USER    (4) Unbound System's Energy         =   +0.00 kcal/mol
Successful Completion
"""
    with pytest.raises(AnkoraDomainError) as exc_tors:
        parse_autodock4_epdb_dlg(missing_tors)
    assert exc_tors.value.code == "AUTODOCK4_OUTPUT_INVALID"

    missing_unbound = b"""\
epdb: USER    Estimated Free Energy of Binding    =   -7.50 kcal/mol  [=(1)+(2)+(3)-(4)]
epdb: USER    (1) Final Intermolecular Energy     =   -8.20 kcal/mol
epdb: USER    (3) Torsional Free Energy           =   +0.60 kcal/mol
Successful Completion
"""
    with pytest.raises(AnkoraDomainError) as exc_unb:
        parse_autodock4_epdb_dlg(missing_unbound)
    assert exc_unb.value.code == "AUTODOCK4_OUTPUT_INVALID"

    # Direct dataclass construction guard when unbound == 0.00 and components are absent
    incomplete = ParsedAutoDock4EpdbResult(
        estimated_free_energy_kcal_mol=-7.5,
        intermolecular_kcal_mol=None,
        total_internal_kcal_mol=0.1,
        torsional_free_energy_kcal_mol=0.6,
        unbound_system_energy_kcal_mol=0.0,
    )
    with pytest.raises(AnkoraDomainError) as exc_prop:
        _ = incomplete.bound_unbound_free_energy_kcal_mol
    assert exc_prop.value.code == "AUTODOCK4_OUTPUT_INVALID"


def test_d2_014_autodock4_log_rejects_duplicate_runs_and_overflow_floats() -> None:
    base_pose = (
        "DOCKED: MODEL        1\n"
        "DOCKED: USER    Run = 1\n"
        "DOCKED: USER    Estimated Free Energy of Binding    =   -6.50 kcal/mol\n"
        "DOCKED: ATOM      1  C   LIG A   1       1.000   2.000   3.000  1.00  0.00     0.000 C \n"
        "DOCKED: ENDMDL\n"
    )
    hist_header = "CLUSTERING HISTOGRAM\n"
    dup_ranking_dlg = (
        hist_header
        + "   1 |   -6.50 |   1 |   -6.45 |   2 | ###\n"
        + "RMSD TABLE\n"
        + "   1   1   1   -6.50   0.00   0.00   RANKING\n"
        + "   1   2   1   -6.40   0.10   0.10   RANKING\n"
        + base_pose
    )
    with pytest.raises(AnkoraDomainError) as exc_dup:
        parse_autodock4_log(dup_ranking_dlg)
    assert exc_dup.value.code == "AUTODOCK4_OUTPUT_INVALID"
    assert "duplicate" in str(exc_dup.value.details.get("reason", "")).lower()

    dup_pose_dlg = (
        hist_header
        + "   1 |   -6.50 |   1 |   -6.50 |   1 | #\n"
        + "RMSD TABLE\n"
        + "   1   1   1   -6.50   0.00   0.00   RANKING\n"
        + base_pose
        + base_pose
    )
    with pytest.raises(AnkoraDomainError) as exc_pose_dup:
        parse_autodock4_log(dup_pose_dlg)
    assert exc_pose_dup.value.code == "AUTODOCK4_OUTPUT_INVALID"
    assert "duplicate" in str(exc_pose_dup.value.details.get("reason", "")).lower()

    huge = "9" * 320
    inf_ranking_dlg = (
        hist_header
        + "   1 |   -6.50 |   1 |   -6.50 |   1 | #\n"
        + "RMSD TABLE\n"
        + f"   1   1   1   -{huge}.00   0.00   0.00   RANKING\n"
        + base_pose
    )
    with pytest.raises(AnkoraDomainError) as exc_inf:
        parse_autodock4_log(inf_ranking_dlg)
    assert exc_inf.value.code == "AUTODOCK4_OUTPUT_INVALID"
    assert "non-finite" in str(exc_inf.value.details.get("reason", "")).lower()


def test_d2_014_vina_v02_parsers_reject_non_finite_values() -> None:
    overflow_stdout = (
        "Estimated Free Energy of Binding   : -1e400 (kcal/mol)\n"
        "(1) Final Intermolecular Energy    : -7.5 (kcal/mol)\n"
    )
    with pytest.raises(AnkoraDomainError) as exc_stdout:
        parse_vina_stdout_energy(overflow_stdout)
    assert exc_stdout.value.code == "VINA_OUTPUT_INVALID"

    overflow_term_stdout = (
        "Estimated Free Energy of Binding   : -7.5 (kcal/mol)\n"
        "(1) Final Intermolecular Energy    : 1e500 (kcal/mol)\n"
    )
    with pytest.raises(AnkoraDomainError) as exc_term:
        parse_vina_stdout_energy(overflow_term_stdout)
    assert exc_term.value.code == "VINA_OUTPUT_INVALID"

    huge = "9" * 320
    overflow_pose = (
        "MODEL 1\n"
        f"REMARK VINA RESULT: -{huge}.0 0.000 0.000\n"
        "ATOM      1  C   LIG A   1       0.000   0.000   0.000  1.00  0.00     0.000 C \n"
        "ENDMDL\n"
    ).encode()
    with pytest.raises(AnkoraDomainError) as exc_pose:
        parse_vina_poses(overflow_pose)
    assert exc_pose.value.code == "VINA_OUTPUT_INVALID"


# ---------------------------------------------------------------------------
# Helpers for lifecycle containment tests (D1-005, D1-006, D1-007, D1-008)
# ---------------------------------------------------------------------------


@dataclass
class _StubLeaseManager:
    fail_on_acquire: Exception | None = None
    acquired: list[tuple[WorkKind, str]] = field(default_factory=list)
    released: list[tuple[WorkKind, str]] = field(default_factory=list)

    def acquire(self, kind: WorkKind, work_id: str) -> None:
        if self.fail_on_acquire is not None:
            raise self.fail_on_acquire
        self.acquired.append((kind, work_id))

    def release(self, kind: WorkKind, work_id: str) -> None:
        self.released.append((kind, work_id))


@dataclass
class _StubResourceLease:
    released: bool = False

    def release(self) -> None:
        self.released = True


@dataclass
class _StubResourceArbiter:
    fail_on_acquire: Exception | None = None
    leases: list[_StubResourceLease] = field(default_factory=list)

    def acquire(self, _claim: Any, *, cancel_event: threading.Event) -> _StubResourceLease:
        if self.fail_on_acquire is not None:
            raise self.fail_on_acquire
        lease = _StubResourceLease()
        self.leases.append(lease)
        return lease


@dataclass
class _FakeRecord:
    job_id: str
    status: Any
    phase: Any
    revision: int = 0
    execution: Any = None
    failure: Any = None
    request: Any = None
    worker_count: int = 1
    entries: list[Any] = field(default_factory=list)
    map_set_id: str = "map-1"

    def model_copy(self, *, update: dict[str, Any]) -> _FakeRecord:
        copied = _FakeRecord(
            job_id=self.job_id,
            status=update.get("status", self.status),
            phase=update.get("phase", self.phase),
            revision=update.get("revision", self.revision),
            execution=update.get("execution", self.execution),
            failure=update.get("failure", self.failure),
            request=update.get("request", self.request),
            worker_count=update.get("worker_count", self.worker_count),
            entries=update.get("entries", self.entries),
            map_set_id=update.get("map_set_id", self.map_set_id),
        )
        return copied


# ---------------------------------------------------------------------------
# D1-005 & D1-006: AutoDock4DockingService._run, _run_batch, _run_batch_entry
# ---------------------------------------------------------------------------


def test_d1_005_autodock4_run_releases_leases_and_fails_on_preamble_crash() -> None:
    record = _FakeRecord(
        job_id="ad4-job-1",
        status=AutoDock4JobStatus.QUEUED,
        phase=AutoDock4JobPhase.QUEUED,
    )
    updated: list[_FakeRecord] = []

    class _FakeStore:
        def load_job(self, job_id: str) -> _FakeRecord:
            assert job_id == "ad4-job-1"
            return record

        def update_job(self, rec: _FakeRecord) -> None:
            if rec.status is AutoDock4JobStatus.RUNNING:
                raise RuntimeError("disk full during running transition")
            updated.append(rec)

    leases = _StubLeaseManager()
    resources = _StubResourceArbiter()
    service = AutoDock4DockingService(
        job_store=cast(Any, _FakeStore()),
        map_store=cast(Any, object()),
        ligand_store=cast(Any, object()),
        receptor_store=cast(Any, object()),
        binding_site_store=cast(Any, object()),
        lease_manager=cast(Any, leases),
        resource_arbiter=cast(Any, resources),
    )
    cancel_event = threading.Event()
    service._cancel_events["ad4-job-1"] = cancel_event

    service._run("ad4-job-1", cast(Any, object()), cancel_event)

    assert not service.has_active_work()
    assert leases.acquired == [(WorkKind.AUTODOCK4_JOB, "ad4-job-1")]
    assert leases.released == [(WorkKind.AUTODOCK4_JOB, "ad4-job-1")]
    assert len(resources.leases) == 1 and resources.leases[0].released is True
    assert len(updated) == 1
    assert updated[0].status is AutoDock4JobStatus.FAILED
    assert isinstance(updated[0].failure, AutoDock4Failure)
    assert updated[0].failure.code == "AUTODOCK4_JOB_INTERNAL_ERROR"
    service._executor.shutdown(wait=False)


def test_d1_006_autodock4_batch_and_entry_contain_unexpected_exceptions() -> None:
    batch_record = _FakeRecord(
        job_id="ad4-batch-1",
        status=AutoDock4JobStatus.QUEUED,
        phase=AutoDock4JobPhase.QUEUED,
        entries=[],
    )
    saved_batches: list[_FakeRecord] = []

    class _FakeBatchStore:
        def load_batch(self, batch_id: str) -> _FakeRecord:
            assert batch_id == "ad4-batch-1"
            return batch_record

        def load_batch_overview(self, batch_id: str) -> _FakeRecord:
            assert batch_id == "ad4-batch-1"
            return batch_record

        def update_batch(
            self, rec: _FakeRecord, *, changed_entries: list[Any] | None = None
        ) -> None:
            _ = changed_entries
            saved_batches.append(rec)

    leases = _StubLeaseManager(fail_on_acquire=RuntimeError("lease sqlite locked"))
    service = AutoDock4DockingService(
        job_store=cast(Any, _FakeBatchStore()),
        map_store=cast(Any, object()),
        ligand_store=cast(Any, object()),
        receptor_store=cast(Any, object()),
        binding_site_store=cast(Any, object()),
        lease_manager=cast(Any, leases),
        resource_arbiter=None,
    )
    cancel_event = threading.Event()
    service._cancel_events["ad4-batch-1"] = cancel_event
    service._active_batch_id = "ad4-batch-1"

    service._run_batch("ad4-batch-1", cancel_event)

    assert not service.has_active_work()
    assert service._active_batch_id is None
    # Never release a lease that failed to acquire
    assert leases.released == []
    assert saved_batches[-1].status is AutoDock4JobStatus.FAILED
    assert saved_batches[-1].failure.code == "AUTODOCK4_BATCH_INTERNAL_ERROR"

    # Now test per-ligand entry isolation when map_store.load_record throws RuntimeError
    @dataclass
    class _FakeEntry:
        ligand_id: str = "lig-1"
        ligand_preparation_id: str | None = "prep-1"
        status: AutoDock4JobStatus = AutoDock4JobStatus.QUEUED
        phase: AutoDock4JobPhase = AutoDock4JobPhase.QUEUED
        failure: AutoDock4Failure | None = None
        execution: Any = None
        command: Any = None
        dpf_sha256: str | None = None
        runs: list[Any] = field(default_factory=list)
        clusters: list[Any] = field(default_factory=list)
        provenance: list[Any] = field(default_factory=list)

        def model_copy(self, *, update: dict[str, Any]) -> _FakeEntry:
            return _FakeEntry(
                ligand_id=self.ligand_id,
                ligand_preparation_id=self.ligand_preparation_id,
                status=update.get("status", self.status),
                phase=update.get("phase", self.phase),
                failure=update.get("failure", self.failure),
                execution=update.get("execution", self.execution),
                command=update.get("command", self.command),
                dpf_sha256=update.get("dpf_sha256", self.dpf_sha256),
                runs=update.get("runs", self.runs),
                clusters=update.get("clusters", self.clusters),
                provenance=update.get("provenance", self.provenance),
            )

    entry_obj = _FakeEntry()
    entry_updates: list[_FakeEntry] = []

    class _EntryStore:
        def load_batch_overview(self, _batch_id: str) -> _FakeRecord:
            return batch_record

        def load_batch_entry(self, _batch_id: str, _ligand_id: str) -> _FakeEntry:
            return entry_obj

        def update_batch_entry(self, _batch_id: str, updated_entry: _FakeEntry) -> None:
            entry_updates.append(updated_entry)

    class _ExplodingMapStore:
        def load_record(self, _map_set_id: str) -> Any:
            raise RuntimeError("corrupt map metadata json")

    entry_service = AutoDock4DockingService(
        job_store=cast(Any, _EntryStore()),
        map_store=cast(Any, _ExplodingMapStore()),
        ligand_store=cast(Any, object()),
        receptor_store=cast(Any, object()),
        binding_site_store=cast(Any, object()),
    )
    entry_service._run_batch_entry("ad4-batch-1", "lig-1", threading.Event())
    assert entry_updates[-1].status is AutoDock4JobStatus.FAILED
    assert entry_updates[-1].failure is not None
    assert entry_updates[-1].failure.code == "AUTODOCK4_BATCH_ENTRY_INTERNAL_ERROR"
    service._executor.shutdown(wait=False)
    entry_service._executor.shutdown(wait=False)


# ---------------------------------------------------------------------------
# D1-007: GninaScreeningService._run reconciliation + active-child safety
# ---------------------------------------------------------------------------


def test_d1_007_gnina_screening_reconciles_stranded_and_respects_active_children() -> None:
    @dataclass
    class _FakeProgress:
        status: DockingJobStatus

    @dataclass
    class _FakeJob:
        screening_campaign_id: str | None
        status: DockingJobStatus

    class _FakeJobs:
        def __init__(self, items: list[_FakeJob]) -> None:
            self._items = items

        def list_jobs(self) -> list[_FakeJob]:
            return list(self._items)

    class _FakeStore:
        def __init__(self, status: DockingJobStatus, child_jobs: list[_FakeJob]) -> None:
            self._status = status
            self.jobs = _FakeJobs(child_jobs)
            self.recovered: list[tuple[str, datetime]] = []

        def load_progress(self, _campaign_id: str) -> _FakeProgress:
            return _FakeProgress(status=self._status)

        def recover_interrupted_campaign(
            self, campaign_id: str, *, interrupted_at: datetime
        ) -> _FakeProgress:
            self.recovered.append((campaign_id, interrupted_at))
            self._status = DockingJobStatus.FAILED
            return _FakeProgress(status=self._status)

    class _RaisingRunner:
        def __init__(self, exc: Exception) -> None:
            self._exc = exc

        def run(self, _campaign_id: str) -> None:
            raise self._exc

    # Case 1: Unexpected preamble crash, campaign QUEUED, no active child -> MUST recover
    store_stranded = _FakeStore(DockingJobStatus.QUEUED, child_jobs=[])
    svc_stranded = GninaScreeningService(
        store=cast(Any, store_stranded),
        runner=cast(Any, _RaisingRunner(RuntimeError("sqlite locked before try"))),
        receptors=cast(Any, object()),
        sites=cast(Any, object()),
        ligands=cast(Any, object()),
        resources=cast(Any, object()),
        enable_experimental_cuda=False,
    )
    svc_stranded._scheduled.add("camp-1")
    svc_stranded._run("camp-1")
    assert not svc_stranded.has_active_work()
    assert len(store_stranded.recovered) == 1
    assert store_stranded.recovered[0][0] == "camp-1"
    svc_stranded._executor.shutdown(wait=False)

    # Case 2: Runner refused reconciliation because child still active -> MUST NOT recover
    store_active_err = _FakeStore(DockingJobStatus.RUNNING, child_jobs=[])
    svc_active_err = GninaScreeningService(
        store=cast(Any, store_active_err),
        runner=cast(
            Any,
            _RaisingRunner(
                AnkoraDomainError(
                    code="GNINA_SCREENING_CHILD_STILL_ACTIVE",
                    stage="gnina_screening",
                    message="child running",
                    status_code=409,
                )
            ),
        ),
        receptors=cast(Any, object()),
        sites=cast(Any, object()),
        ligands=cast(Any, object()),
        resources=cast(Any, object()),
        enable_experimental_cuda=False,
    )
    svc_active_err._scheduled.add("camp-2")
    svc_active_err._run("camp-2")
    assert not svc_active_err.has_active_work()
    assert store_active_err.recovered == []
    svc_active_err._executor.shutdown(wait=False)

    # Case 3: Non-terminal child job exists on disk -> MUST NOT recover
    store_live_child = _FakeStore(
        DockingJobStatus.RUNNING,
        child_jobs=[_FakeJob("camp-3", DockingJobStatus.RUNNING)],
    )
    svc_live_child = GninaScreeningService(
        store=cast(Any, store_live_child),
        runner=cast(Any, _RaisingRunner(RuntimeError("unexpected failure"))),
        receptors=cast(Any, object()),
        sites=cast(Any, object()),
        ligands=cast(Any, object()),
        resources=cast(Any, object()),
        enable_experimental_cuda=False,
    )
    svc_live_child._scheduled.add("camp-3")
    svc_live_child._run("camp-3")
    assert not svc_live_child.has_active_work()
    assert store_live_child.recovered == []
    svc_live_child._executor.shutdown(wait=False)


# ---------------------------------------------------------------------------
# D1-008: VinaDockingService._run and _run_batch containment + lease cleanup
# ---------------------------------------------------------------------------


def test_d1_008_vina_run_and_batch_release_leases_and_clear_active_state() -> None:
    @dataclass
    class _ReqStub:
        parameters: VinaDockingParameters

    job_record = _FakeRecord(
        job_id="vina-job-1",
        status=DockingJobStatus.QUEUED,
        phase=DockingJobPhase.QUEUED,
        request=_ReqStub(parameters=VinaDockingParameters()),
    )
    saved_jobs: list[_FakeRecord] = []

    class _FakeVinaStore:
        def load_record(self, job_id: str) -> _FakeRecord:
            assert job_id == "vina-job-1"
            return job_record

        def update_record(self, rec: _FakeRecord) -> None:
            if rec.status is DockingJobStatus.RUNNING:
                raise RuntimeError("disk error writing running state")
            saved_jobs.append(rec)

    leases = _StubLeaseManager()
    resources = _StubResourceArbiter()
    service = VinaDockingService(
        docking_store=cast(Any, _FakeVinaStore()),
        receptor_store=cast(Any, object()),
        binding_site_store=cast(Any, object()),
        ligand_store=cast(Any, object()),
        lease_manager=cast(Any, leases),
        resource_arbiter=cast(Any, resources),
    )
    cancel_event = threading.Event()
    service._cancel_events["vina-job-1"] = cancel_event

    service._run(
        "vina-job-1",
        cast(Any, object()),
        Path("receptor.pdbqt"),
        None,
        Path("ligand.pdbqt"),
        Path("out.pdbqt"),
        BindingBox(center_x=0, center_y=0, center_z=0, size_x=10, size_y=10, size_z=10),
        cancel_event,
    )

    assert not service.has_active_work()
    assert leases.acquired == [(WorkKind.VINA_JOB, "vina-job-1")]
    assert leases.released == [(WorkKind.VINA_JOB, "vina-job-1")]
    assert len(resources.leases) == 1 and resources.leases[0].released is True
    assert saved_jobs[-1].status is DockingJobStatus.FAILED
    assert saved_jobs[-1].failure.code == "VINA_JOB_INTERNAL_ERROR"

    # Also verify _run_batch when lease acquire fails before try body
    batch_record = _FakeRecord(
        job_id="vina-batch-1",
        status=DockingJobStatus.QUEUED,
        phase=DockingJobPhase.QUEUED,
    )
    saved_batches: list[_FakeRecord] = []

    class _FakeVinaBatchStore:
        def load_batch_overview(self, _batch_id: str) -> _FakeRecord:
            return batch_record

        def update_batch_record(self, rec: _FakeRecord, *, changed_entries: list[Any]) -> None:
            assert changed_entries == []
            saved_batches.append(rec)

    failing_leases = _StubLeaseManager(fail_on_acquire=RuntimeError("lease conflict"))
    batch_service = VinaDockingService(
        docking_store=cast(Any, _FakeVinaBatchStore()),
        receptor_store=cast(Any, object()),
        binding_site_store=cast(Any, object()),
        ligand_store=cast(Any, object()),
        lease_manager=cast(Any, failing_leases),
        resource_arbiter=None,
    )
    batch_cancel = threading.Event()
    batch_service._cancel_events["vina-batch-1"] = batch_cancel
    batch_service._active_batch_ids.add("vina-batch-1")

    batch_service._run_batch(
        "vina-batch-1",
        cast(Any, object()),
        Path("receptor.pdbqt"),
        None,
        BindingBox(center_x=0, center_y=0, center_z=0, size_x=10, size_y=10, size_z=10),
        [],
        VinaDockingParameters(),
        batch_cancel,
    )

    assert not batch_service.has_active_work()
    assert failing_leases.released == []
    assert saved_batches[-1].status is DockingJobStatus.FAILED
    assert saved_batches[-1].failure.code == "VINA_BATCH_INTERNAL_ERROR"
    service._executor.shutdown(wait=False)
    batch_service._executor.shutdown(wait=False)
