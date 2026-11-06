"""Synthetic workflow around a retained real pose fixture; no docking is run."""

import json
import threading
from pathlib import Path

import pytest
from test_gnina_service import _setup

from ankora_backend.domain.errors import AnkoraDomainError
from ankora_backend.execution.cancellable_subprocess import CancellableToolExecution
from ankora_backend.schemas.docking import DockingJobStatus
from ankora_backend.services.gnina_screening_evidence import verified_screening_pose


@pytest.fixture
def completed_job(tmp_path, monkeypatch):
    service, store, arbiter, leases, job, installation = _setup(tmp_path, monkeypatch)
    raw = (Path(__file__).parent / "fixtures" / "gnina_real_1hsg_mk1.pdbqt").read_bytes()

    def execute(**kwargs):
        kwargs["output_path"].write_bytes(raw)
        return CancellableToolExecution(["gnina"], 0, "out", "err", False, False)

    monkeypatch.setattr("ankora_backend.services.gnina_docking.execute_gnina", execute)
    service._run(job.job_id, installation, threading.Event())
    assert store.load_job(job.job_id).status is DockingJobStatus.COMPLETED
    yield store, job
    service.shutdown()
    leases.shutdown()
    assert not arbiter.snapshot().active_allocations


def _project(store, job, **overrides):
    args = {
        "store": store,
        "job_id": job.job_id,
        "expected_request": job.request,
        "expected_receptor_sha256": job.receptor_sha256,
        "expected_ligand_sha256": job.ligand_sha256,
        "expected_conformer_sha256": job.conformer_sha256,
        "expected_tool_sha256": job.tool.sha256,
    }
    return verified_screening_pose(**(args | overrides))


def test_projects_recorded_top_cnn_pose_without_energy_resorting(completed_job):
    store, job = completed_job
    record = store.load_job(job.job_id)
    result = _project(store, job)
    assert result == record.poses[0]
    assert result.cnn_score > record.poses[1].cnn_score
    assert result.minimized_affinity_kcal_mol > record.poses[1].minimized_affinity_kcal_mol


@pytest.mark.parametrize("filename", ["receptor.pdbqt", "ligand.pdbqt", "conformer.sdf"])
@pytest.mark.parametrize("missing", [False, True])
def test_rejects_altered_or_missing_preserved_input(completed_job, filename, missing):
    store, job = completed_job
    path = store.output_path(job.job_id, filename)
    if missing:
        path.unlink()
    else:
        path.write_bytes(b"altered synthetic content")
    with pytest.raises(AnkoraDomainError, match="do not match"):
        _project(store, job)


@pytest.mark.parametrize(
    "field",
    [
        "expected_receptor_sha256",
        "expected_ligand_sha256",
        "expected_conformer_sha256",
        "expected_tool_sha256",
    ],
)
def test_rejects_a_job_from_a_different_campaign_snapshot(completed_job, field):
    store, job = completed_job
    with pytest.raises(AnkoraDomainError, match="do not match"):
        _project(store, job, **{field: "0" * 64})


def test_rejects_a_job_for_another_ligand(completed_job):
    store, job = completed_job
    request = job.request.model_copy(update={"ligand_id": "another-ligand"})
    with pytest.raises(AnkoraDomainError, match="do not match"):
        _project(store, job, expected_request=request)


def test_rejects_an_unfinished_job(tmp_path, monkeypatch):
    service, store, arbiter, leases, job, _installation = _setup(tmp_path, monkeypatch)
    try:
        with pytest.raises(AnkoraDomainError, match="do not match"):
            _project(store, job)
    finally:
        service.shutdown()
        leases.shutdown()
    assert not arbiter.snapshot().active_allocations


def test_rejects_altered_pose(completed_job):
    store, job = completed_job
    store.output_path(job.job_id, "pose_1.pdbqt").write_bytes(b"altered synthetic pose")
    with pytest.raises(AnkoraDomainError) as error:
        _project(store, job)
    assert error.value.code == "GNINA_POSE_INTEGRITY_FAILED"


def test_rejects_job_record_whose_identity_differs_from_its_directory(completed_job):
    store, job = completed_job
    path = store.output_path(job.job_id, "record.json")
    record = json.loads(path.read_text(encoding="utf-8"))
    record["job_id"] = store.new_job_id()
    path.write_text(json.dumps(record), encoding="utf-8")
    with pytest.raises(AnkoraDomainError, match="do not match"):
        _project(store, job)


def test_rejects_pose_size_that_disagrees_with_record(completed_job):
    store, job = completed_job
    path = store.output_path(job.job_id, "record.json")
    record = json.loads(path.read_text(encoding="utf-8"))
    record["poses"][0]["artifact"]["size_bytes"] += 1
    path.write_text(json.dumps(record), encoding="utf-8")
    with pytest.raises(AnkoraDomainError, match="do not match"):
        _project(store, job)
