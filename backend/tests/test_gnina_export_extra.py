"""Synthetic adversarial checks for GNINA export integrity."""

from hashlib import sha256

import pytest
from test_gnina_export import RAW_POSES, _service, _store_job

from ankora_backend.adapters.engines.gnina import parse_gnina_pdbqt
from ankora_backend.domain.errors import AnkoraDomainError


@pytest.mark.parametrize("filename", ["stdout.log", "stderr.log"])
def test_changed_raw_log_is_not_packaged_as_recorded_execution(tmp_path, monkeypatch, filename):
    store, job = _store_job(tmp_path, monkeypatch)
    store.output_path(job.job_id, filename).write_bytes(b"tampered synthetic engine output\n")
    with pytest.raises(AnkoraDomainError):
        _service(tmp_path, store).export_campaign(source_kind="gnina_job", batch_id=job.job_id)
    assert not list((tmp_path / "projects" / "default" / "exports").rglob("manifest.json"))
    assert not list((tmp_path / "projects" / "default" / "exports").rglob("*.zip"))


def test_changed_raw_poses_are_not_packaged_as_original(tmp_path, monkeypatch):
    store, job = _store_job(tmp_path, monkeypatch)
    parsed = parse_gnina_pdbqt(RAW_POSES)
    poses = []
    for pose, native in zip(job.poses, parsed, strict=True):
        store.output_path(job.job_id, pose.artifact.filename).write_bytes(native.pdbqt)
        artifact = pose.artifact.model_copy(
            update={
                "sha256": sha256(native.pdbqt).hexdigest(),
                "size_bytes": len(native.pdbqt),
            }
        )
        poses.append(pose.model_copy(update={"artifact": artifact}))
    job = job.model_copy(update={"poses": poses})
    store.update_job(job)
    store.output_path(job.job_id, "raw_poses.pdbqt").write_bytes(
        RAW_POSES.replace(b"0.91", b"0.81")
    )
    with pytest.raises(AnkoraDomainError):
        _service(tmp_path, store).export_campaign(source_kind="gnina_job", batch_id=job.job_id)
    assert not list((tmp_path / "projects" / "default" / "exports").rglob("manifest.json"))
