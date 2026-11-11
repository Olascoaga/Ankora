"""Synthetic GNINA records: preserve score semantics and fail on identity drift."""

import pytest
from test_gnina_catalog import _completed
from test_pose_interactions import LIGAND, PREPARATION, RECEPTOR, _hash, _service

from ankora_backend.domain.errors import AnkoraDomainError
from ankora_backend.persistence.gnina_store import GninaJobStore
from ankora_backend.schemas.pose_interactions import InteractionAnalysisRequest


def _gnina_service(tmp_path):
    service, pose_path, detector = _service(tmp_path)
    store = GninaJobStore(tmp_path)
    job = _completed(store)
    job = job.model_copy(
        update={
            "request": job.request.model_copy(
                update={
                    "ligand_id": LIGAND,
                    "ligand_preparation_id": PREPARATION,
                    "receptor_id": RECEPTOR,
                }
            ),
            "receptor_sha256": _hash(tmp_path / "receptor.pdbqt"),
            "ligand_sha256": _hash(tmp_path / "ligand.pdbqt"),
            "conformer_sha256": _hash(tmp_path / "conformer.sdf"),
        }
    )
    store.create_job(job)
    for pose in job.poses:
        store.write_artifact(
            job.job_id, pose.artifact.filename, f"synthetic pose {pose.mode}".encode()
        )
    service._gnina = store
    service._ligands.pdbqt_content_path = lambda ligand, preparation: tmp_path / "ligand.pdbqt"
    return service, job, detector


def test_gnina_inventory_and_analysis_keep_score_axes(tmp_path):
    service, job, detector = _gnina_service(tmp_path)
    inventory = service.list_poses(f"gnina_job:{job.job_id}", LIGAND)
    assert [pose.cnn_score for pose in inventory.poses] == [0.9, 0.7]
    assert [pose.result_kcal_mol for pose in inventory.poses] == [-4, -9]
    assert inventory.poses[0].cnn_affinity_pk == 8
    result = service.analyze(
        f"gnina_job:{job.job_id}", LIGAND, "pose-1", InteractionAnalysisRequest()
    )
    assert result.pose.cnn_score == 0.9
    assert result.pose.value_label == "GNINA minimized affinity"
    assert detector.calls == 1


@pytest.mark.parametrize("field", ["ligand_sha256", "conformer_sha256"])
def test_gnina_rejects_docking_input_identity_drift(tmp_path, field):
    service, job, detector = _gnina_service(tmp_path)
    service._gnina.update_job(job.model_copy(update={field: "f" * 64}))
    with pytest.raises(AnkoraDomainError) as captured:
        service.analyze(f"gnina_job:{job.job_id}", LIGAND, "pose-1", InteractionAnalysisRequest())
    assert captured.value.code == "POSE_INTERACTION_LIGAND_IDENTITY_MISMATCH"
    assert detector.calls == 0


def test_gnina_refuses_another_ligand(tmp_path):
    service, job, _ = _gnina_service(tmp_path)
    with pytest.raises(AnkoraDomainError) as captured:
        service.list_poses(f"gnina_job:{job.job_id}", "different-ligand")
    assert captured.value.code == "RESULT_LIGAND_NOT_FOUND"


def test_gnina_rejects_a_tampered_saved_pose(tmp_path):
    service, job, detector = _gnina_service(tmp_path)
    service._gnina.pose_content_path(job.job_id, "pose-1").write_bytes(b"tampered synthetic pose")
    with pytest.raises(AnkoraDomainError):
        service.analyze(f"gnina_job:{job.job_id}", LIGAND, "pose-1", InteractionAnalysisRequest())
    assert detector.calls == 0


def test_gnina_complex_rejects_a_changed_docking_receptor(tmp_path):
    service, job, _ = _gnina_service(tmp_path)
    (tmp_path / "receptor.pdbqt").write_bytes(b"tampered synthetic receptor")
    with pytest.raises(AnkoraDomainError) as captured:
        service.complex_pdb(f"gnina_job:{job.job_id}", LIGAND, "pose-1")
    assert captured.value.code == "POSE_INTERACTION_INPUT_HASH_MISMATCH"


def _gnina_screening_service(tmp_path, monkeypatch):
    from datetime import UTC, datetime
    from types import SimpleNamespace
    from uuid import uuid4

    from ankora_backend.persistence.gnina_screening_store import GninaScreeningStore
    from ankora_backend.schemas.docking import DockingFailure, DockingJobPhase, DockingJobStatus
    from ankora_backend.schemas.gnina_screening import (
        GninaScreeningCampaignRecord,
        GninaScreeningEntry,
        GninaScreeningPreflightCode,
        GninaScreeningRequest,
        GninaScreeningSelection,
    )

    service, _, detector = _service(tmp_path)
    job_store = GninaJobStore(tmp_path)
    screening_store = GninaScreeningStore(tmp_path)
    campaign_id = screening_store.new_campaign_id()
    now = datetime(2026, 8, 26, 20, 0, tzinfo=UTC)

    receptor_bytes = (tmp_path / "receptor.pdbqt").read_bytes()
    ligand_bytes = (tmp_path / "ligand.pdbqt").read_bytes()
    conformer_bytes = (tmp_path / "conformer.sdf").read_bytes()
    receptor_sha = _hash(tmp_path / "receptor.pdbqt")
    ligand_sha = _hash(tmp_path / "ligand.pdbqt")
    conformer_sha = _hash(tmp_path / "conformer.sdf")

    base_job = _completed(job_store)
    request = GninaScreeningRequest(
        receptor_id=RECEPTOR,
        binding_site_id="synthetic-site",
        library_id="synthetic-library",
        filter_run_id="synthetic-filter",
        parameters=base_job.request.parameters,
        acknowledge_inputs_and_scoring=True,
    )
    job = base_job.model_copy(
        update={
            "screening_campaign_id": campaign_id,
            "request": base_job.request.model_copy(
                update={
                    "receptor_id": RECEPTOR,
                    "binding_site_id": "synthetic-site",
                    "ligand_id": LIGAND,
                    "ligand_preparation_id": PREPARATION,
                }
            ),
            "receptor_sha256": receptor_sha,
            "ligand_sha256": ligand_sha,
            "conformer_sha256": conformer_sha,
        }
    )
    job_store.create_job(job)
    job_store.write_artifact(job.job_id, "receptor.pdbqt", receptor_bytes)
    job_store.write_artifact(job.job_id, "ligand.pdbqt", ligand_bytes)
    job_store.write_artifact(job.job_id, "conformer.sdf", conformer_bytes)
    for pose in job.poses:
        job_store.write_artifact(
            job.job_id, pose.artifact.filename, f"synthetic pose {pose.mode}".encode()
        )

    failed_ligand_id = str(uuid4())
    entries = [
        GninaScreeningEntry(
            ligand_id=LIGAND,
            chemical_state_id="state-1",
            source_index=0,
            name="Synthetic Hit",
            ligand_preparation_id=PREPARATION,
            conformer_id="00000000-0000-0000-0000-000000000004",
            ligand_sha256=ligand_sha,
            conformer_sha256=conformer_sha,
            status=DockingJobStatus.QUEUED,
            phase=DockingJobPhase.QUEUED,
        ),
        GninaScreeningEntry(
            ligand_id=failed_ligand_id,
            chemical_state_id="state-2",
            source_index=1,
            name="Synthetic Failed",
            status=DockingJobStatus.FAILED,
            phase=DockingJobPhase.COMPLETE,
            completed_at=now,
            failure=DockingFailure(
                code=GninaScreeningPreflightCode.LIGAND_NOT_PREPARED,
                message="Synthetic preflight failure.",
            ),
        ),
    ]
    campaign = GninaScreeningCampaignRecord(
        campaign_id=campaign_id,
        status=DockingJobStatus.QUEUED,
        phase=DockingJobPhase.QUEUED,
        created_at=now,
        request=request,
        tool=job.tool,
        box=job.box,
        receptor_output_artifact_id="receptor-pdbqt",
        receptor_sha256=receptor_sha,
        selection=GninaScreeningSelection(
            library_id="synthetic-library",
            filter_run_id="synthetic-filter",
            manifest_artifact_id="synthetic-filter",
            manifest_sha256="1" * 64,
        ),
        selected_count=2,
        completed_count=1,
        failed_count=1,
        entries=entries,
    )
    selection_stub = SimpleNamespace(
        artifact=SimpleNamespace(sha256="1" * 64, filter_run_id="synthetic-filter"),
        selected_ligand_ids=[item.ligand_id for item in entries],
        evaluations=[
            SimpleNamespace(
                ligand_id=item.ligand_id,
                state_id=item.chemical_state_id,
                record_index=item.source_index,
            )
            for item in entries
        ],
    )
    monkeypatch.setattr(
        "ankora_backend.persistence.gnina_screening_store.verified_screening_selection",
        lambda **_kwargs: selection_stub,
    )
    monkeypatch.setattr(
        GninaScreeningStore,
        "_verify_entry_preparation",
        lambda *_args, **_kwargs: None,
    )
    screening_store.create_campaign(campaign)
    stored_entry = screening_store.load_entry(campaign_id, LIGAND)
    assert stored_entry is not None
    running = screening_store.update_entry(
        campaign_id,
        stored_entry.model_copy(
            update={
                "status": DockingJobStatus.RUNNING,
                "phase": DockingJobPhase.DOCKING,
                "gnina_job_id": job.job_id,
                "started_at": now,
            }
        ),
    )
    screening_store.update_entry(
        campaign_id,
        running.model_copy(
            update={
                "status": DockingJobStatus.COMPLETED,
                "phase": DockingJobPhase.COMPLETE,
                "completed_at": now,
            }
        ),
    )
    screening_store.finalize_campaign(campaign_id)

    service._gnina = job_store
    service._gnina_screening = screening_store
    service._ligands.pdbqt_content_path = lambda ligand, preparation: tmp_path / "ligand.pdbqt"
    return service, screening_store.load_campaign(campaign_id), job, detector


def test_gnina_screening_inventory_analysis_and_complex_preserve_score_axes(
    tmp_path, monkeypatch
):
    from test_pose_interactions import POSE_PDBQT, RECEPTOR_PDB

    service, campaign, job, detector = _gnina_screening_service(tmp_path, monkeypatch)
    catalog_id = f"gnina_screening:{campaign.campaign_id}"
    inventory = service.list_poses(catalog_id, LIGAND)
    assert [pose.cnn_score for pose in inventory.poses] == [0.9, 0.7]
    assert [pose.cnn_affinity_pk for pose in inventory.poses] == [8, 9]
    assert [pose.result_kcal_mol for pose in inventory.poses] == [-4, -9]
    assert (
        inventory.poses[0].content_url
        == f"/docking/gnina/jobs/{job.job_id}/poses/pose-1/content"
    )

    result = service.analyze(catalog_id, LIGAND, "pose-1", InteractionAnalysisRequest())
    assert result.catalog_id == catalog_id
    assert result.engine_key == "gnina_screening"
    assert result.pose.cnn_score == 0.9
    assert result.pose.cnn_affinity_pk == 8
    assert result.pose.value_label == "GNINA minimized affinity"
    assert detector.calls == 1

    # Write valid synthetic coordinate bytes and update digests to exercise complex_pdb.
    (tmp_path / "receptor.pdb").write_bytes(RECEPTOR_PDB)
    service._receptors.outputs[1] = service._receptors.outputs[1].model_copy(
        update={"sha256": _hash(tmp_path / "receptor.pdb")}
    )
    pose_path = service._gnina.output_path(job.job_id, "pose_1.pdbqt")
    pose_path.write_bytes(POSE_PDBQT)
    updated_pose = job.poses[0].model_copy(
        update={
            "artifact": job.poses[0].artifact.model_copy(
                update={"sha256": _hash(pose_path), "size_bytes": len(POSE_PDBQT)}
            )
        }
    )
    service._gnina.update_job(job.model_copy(update={"poses": [updated_pose, job.poses[1]]}))

    document, filename = service.complex_pdb(catalog_id, LIGAND, "pose-1")
    assert filename == "complex_Mode_1.pdb"
    assert f"REMARK   1 RESULT          {catalog_id}" in document
    assert "REMARK   1 POSE CNN SCORE  0.9000 (dimensionless)" in document
    assert "REMARK   1 POSE CNN AFFIN  8.000 pK" in document
    assert "-4.000 kcal/mol (GNINA minimized affinity)" in document


def test_gnina_screening_interactions_fail_closed_on_incomplete_or_tampered_entries(
    tmp_path, monkeypatch
):
    service, campaign, job, detector = _gnina_screening_service(tmp_path, monkeypatch)
    catalog_id = f"gnina_screening:{campaign.campaign_id}"
    failed_ligand_id = campaign.entries[1].ligand_id

    with pytest.raises(AnkoraDomainError) as failed_entry:
        service.list_poses(catalog_id, failed_ligand_id)
    assert failed_entry.value.code == "RESULT_POSE_NOT_AVAILABLE"

    with pytest.raises(AnkoraDomainError) as wrong_ligand:
        service.list_poses(catalog_id, "unknown-ligand")
    assert wrong_ligand.value.code == "RESULT_LIGAND_NOT_FOUND"

    original_pose = service._gnina.output_path(job.job_id, "pose_1.pdbqt").read_bytes()
    service._gnina.output_path(job.job_id, "pose_1.pdbqt").write_bytes(b"tampered pose")
    with pytest.raises(AnkoraDomainError) as pose_tamper:
        service.analyze(catalog_id, LIGAND, "pose-1", InteractionAnalysisRequest())
    assert pose_tamper.value.code == "GNINA_POSE_INTEGRITY_FAILED"
    assert detector.calls == 0

    service._gnina.output_path(job.job_id, "pose_1.pdbqt").write_bytes(original_pose)
    service._gnina.output_path(job.job_id, "ligand.pdbqt").write_bytes(b"tampered child ligand")
    with pytest.raises(AnkoraDomainError) as child_drift:
        service.analyze(catalog_id, LIGAND, "pose-1", InteractionAnalysisRequest())
    assert child_drift.value.code == "GNINA_SCREENING_JOB_MISMATCH"
    assert detector.calls == 0


def test_recorded_cuda_campaign_runs_real_prolif_and_exports_complex_when_present(
    tmp_path, monkeypatch
):
    import shutil
    from pathlib import Path

    from fastapi.testclient import TestClient

    from ankora_backend.api.app import create_app

    source_data = (
        Path(__file__).resolve().parents[2]
        / "logs/linux-gnina-investigation/v1.3.3/screening-api-cuda-01/data"
    )
    if not source_data.is_dir():
        pytest.skip("Local recorded GNINA CUDA screening evidence is not present in this checkout.")
    isolated_data = tmp_path / "isolated-data"
    shutil.copytree(source_data, isolated_data)
    monkeypatch.setenv("ANKORA_DATA_DIR", str(isolated_data))

    with TestClient(create_app()) as client:
        campaigns = client.get(
            "/api/v1/results/campaigns?scoring_family=gnina&mode=screening"
        ).json()
        campaign_id = campaigns["entries"][0]["record_id"]
        compounds = client.get(
            f"/api/v1/results/campaigns/gnina_screening/{campaign_id}/compounds"
        ).json()
        top_row = compounds["rows"][0]
        assert top_row["name"] == "NCI-68"
        ligand_id = top_row["ligand_id"]

        poses_resp = client.get(
            f"/api/v1/results/campaigns/gnina_screening/{campaign_id}/compounds/{ligand_id}/poses"
        )
        assert poses_resp.status_code == 200
        poses = poses_resp.json()
        top_pose = poses["poses"][0]
        assert top_pose["kind"] == "gnina_mode"
        assert top_pose["cnn_score"] == pytest.approx(0.939, abs=1e-4)

        analysis_resp = client.post(
            f"/api/v1/results/campaigns/gnina_screening/{campaign_id}/compounds/"
            f"{ligand_id}/poses/{top_pose['artifact_id']}/interactions",
            json={},
        )
        assert analysis_resp.status_code == 201
        analysis = analysis_resp.json()
        assert analysis["detector"]["name"] == "ProLIF"
        assert len(analysis["ligand_diagram"]["atoms"]) > 0
        assert len(analysis["contacts"]) > 0

        complex_resp = client.get(
            f"/api/v1/results/campaigns/gnina_screening/{campaign_id}/compounds/"
            f"{ligand_id}/poses/{top_pose['artifact_id']}/complex"
        )
        assert complex_resp.status_code == 200
        assert f"REMARK   1 RESULT          gnina_screening:{campaign_id}" in complex_resp.text
        assert "REMARK   1 POSE CNN SCORE  0.9390 (dimensionless)" in complex_resp.text
