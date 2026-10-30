"""Synthetic persistence tests; no scientific result is inferred from these fixtures."""

from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path

import pytest
from pydantic import ValidationError

from ankora_backend.domain.errors import AnkoraDomainError
from ankora_backend.persistence.gnina_store import GninaJobStore
from ankora_backend.persistence.work_lease_store import WorkLeaseStore
from ankora_backend.schemas.binding_sites import BindingBox
from ankora_backend.schemas.docking import DockingJobPhase, DockingJobStatus
from ankora_backend.schemas.gnina import (
    GninaDockingParameters,
    GninaDockingRequest,
    GninaExecutionEvidence,
    GninaJobRecord,
    GninaPoseArtifact,
    GninaPoseResult,
    GninaToolIdentity,
)
from ankora_backend.schemas.work_recovery import WorkKind, WorkLeaseRecord, WorkLeaseState
from ankora_backend.services.work_recovery import InterruptedWorkRecovery


def _record(job_id: str) -> GninaJobRecord:
    return GninaJobRecord(
        job_id=job_id,
        status=DockingJobStatus.QUEUED,
        phase=DockingJobPhase.QUEUED,
        created_at=datetime.now(UTC),
        request=GninaDockingRequest(
            receptor_id="receptor",
            binding_site_id="site",
            ligand_id="ligand",
            ligand_preparation_id="preparation",
            parameters=GninaDockingParameters(compute="cuda"),
            acknowledge_inputs_and_scoring=True,
        ),
        tool=GninaToolIdentity(version="1.3.3", sha256="a" * 64, architecture="x86_64"),
        box=BindingBox(center_x=0, center_y=0, center_z=0, size_x=10, size_y=10, size_z=10),
        receptor_output_artifact_id="output",
        receptor_sha256="b" * 64,
        ligand_sha256="c" * 64,
        conformer_sha256="d" * 64,
    )


def test_project_isolation_and_immutable_artifacts(tmp_path: Path) -> None:
    first = GninaJobStore(tmp_path, "first")
    second = GninaJobStore(tmp_path, "second")
    job = _record(first.new_job_id())
    first.create_job(job)
    first.write_artifact(job.job_id, "pose_1.pdbqt", b"synthetic pose")
    with pytest.raises(FileExistsError):
        first.write_artifact(job.job_id, "pose_1.pdbqt", b"replacement")
    with pytest.raises(AnkoraDomainError):
        second.load_job(job.job_id)
    assert second.list_jobs() == []
    assert first.load_job(job.job_id) == job
    assert first.output_path(job.job_id, "pose_1.pdbqt").read_bytes() == b"synthetic pose"


def test_pose_is_visible_only_after_publication(tmp_path: Path) -> None:
    store = GninaJobStore(tmp_path)
    job = _record(store.new_job_id())
    store.create_job(job)
    store.write_artifact(job.job_id, "pose_1.pdbqt", b"synthetic pose")
    with pytest.raises(AnkoraDomainError):
        store.pose_content_path(job.job_id, "pose-id")
    result = GninaPoseResult(
        mode=1,
        minimized_affinity_kcal_mol=-1,
        cnn_score=0.7,
        cnn_affinity=5,
        artifact=GninaPoseArtifact(
            artifact_id="pose-id",
            mode=1,
            filename="pose_1.pdbqt",
            sha256=sha256(b"synthetic pose").hexdigest(),
            size_bytes=14,
        ),
    )
    with pytest.raises(ValidationError):
        store.update_job(job.model_copy(update={"poses": [result]}))
    with pytest.raises(ValidationError):
        store.update_job(
            job.model_copy(
                update={
                    "status": DockingJobStatus.COMPLETED,
                    "poses": [result],
                    "execution": GninaExecutionEvidence(
                        command=["gnina"], exit_code=0, stdout="", stderr=""
                    ),
                }
            )
        )
    updated = job.model_copy(
        update={
            "status": DockingJobStatus.COMPLETED,
            "poses": [result],
            "execution": GninaExecutionEvidence(
                command=["gnina"],
                exit_code=0,
                stdout="",
                stderr="",
                gpu_process_observed=True,
            ),
        }
    )
    store.update_job(updated)
    assert store.pose_content_path(job.job_id, "pose-id").read_bytes() == b"synthetic pose"
    assert store.load_job(job.job_id).poses[0].cnn_score == 0.7
    store.output_path(job.job_id, "pose_1.pdbqt").write_bytes(b"tampered")
    with pytest.raises(AnkoraDomainError) as caught:
        store.pose_content_path(job.job_id, "pose-id")
    assert caught.value.code == "GNINA_POSE_INTEGRITY_FAILED"


def test_rejects_path_traversal_and_requires_acknowledgement(tmp_path: Path) -> None:
    store = GninaJobStore(tmp_path)
    job = _record(store.new_job_id())
    store.create_job(job)
    with pytest.raises((AnkoraDomainError, ValueError)):
        store.output_path("../outside", "pose_1.pdbqt")
    with pytest.raises(ValueError):
        store.output_path(job.job_id, "../outside")
    with pytest.raises(ValidationError):
        GninaDockingRequest(**{**job.request.model_dump(), "acknowledge_inputs_and_scoring": False})


def test_rejects_cross_project_symlink(tmp_path: Path) -> None:
    first = GninaJobStore(tmp_path, "first")
    second = GninaJobStore(tmp_path, "second")
    job = _record(second.new_job_id())
    second.create_job(job)
    parent = tmp_path / "projects" / "first" / "results" / "gnina_jobs"
    parent.mkdir(parents=True)
    try:
        (parent / job.job_id).symlink_to(second.job_directory(job.job_id), target_is_directory=True)
    except OSError:
        pytest.skip("Creating symlinks is unavailable on this host")
    with pytest.raises(AnkoraDomainError):
        first.load_job(job.job_id)


def test_recovery_marks_interrupted_job_without_publishing_partial_pose(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ANKORA_DATA_DIR", str(tmp_path))
    store = GninaJobStore.from_environment()
    job = _record(store.new_job_id()).model_copy(
        update={
            "status": DockingJobStatus.RUNNING,
            "phase": DockingJobPhase.DOCKING,
        }
    )
    store.create_job(job)
    store.write_artifact(job.job_id, "raw.pdbqt", b"partial synthetic output")
    now = datetime.now(UTC)
    leases = WorkLeaseStore.from_environment()
    lease = WorkLeaseRecord(
        lease_id=store.new_job_id(),
        work_kind=WorkKind.GNINA_JOB,
        work_id=job.job_id,
        owner_instance_id=store.new_job_id(),
        acquired_at=now,
        heartbeat_at=now,
    )
    leases.write(lease)
    recovery = InterruptedWorkRecovery.from_environment(leases=leases)
    summary = recovery.reconcile()
    assert len(summary.items) == 1
    assert summary.items[0].work_kind is WorkKind.GNINA_JOB
    result = store.load_job(job.job_id)
    assert result.status is DockingJobStatus.FAILED
    assert result.failure is not None and result.failure.code == "GNINA_EXECUTION_INTERRUPTED"
    assert result.poses == []
    assert store.output_path(job.job_id, "raw.pdbqt").read_bytes() == b"partial synthetic output"
    restored_lease = leases.load(WorkKind.GNINA_JOB, job.job_id)
    assert restored_lease is not None and restored_lease.state is WorkLeaseState.RECONCILED
    assert recovery.reconcile().items == []
