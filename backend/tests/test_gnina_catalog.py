"""Synthetic GNINA catalog records: score axes never become kcal/mol."""

import shutil
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from ankora_backend.api.app import create_app
from ankora_backend.persistence.gnina_screening_store import GninaScreeningStore
from ankora_backend.persistence.gnina_store import GninaJobStore
from ankora_backend.schemas.binding_sites import BindingBox
from ankora_backend.schemas.docking import DockingFailure, DockingJobPhase, DockingJobStatus
from ankora_backend.schemas.gnina import (
    GninaDockingParameters,
    GninaDockingRequest,
    GninaExecutionEvidence,
    GninaJobRecord,
    GninaPoseArtifact,
    GninaPoseResult,
    GninaToolIdentity,
)
from ankora_backend.schemas.gnina_screening import (
    GninaScreeningCampaignRecord,
    GninaScreeningEntry,
    GninaScreeningPreflightCode,
    GninaScreeningRequest,
    GninaScreeningSelection,
)


def _completed(store: GninaJobStore) -> GninaJobRecord:
    request = GninaDockingRequest(
        receptor_id="synthetic-receptor",
        binding_site_id="synthetic-site",
        ligand_id="synthetic-ligand",
        ligand_preparation_id="synthetic-preparation",
        parameters=GninaDockingParameters(compute="cpu"),
        acknowledge_inputs_and_scoring=True,
    )
    poses = []
    for mode, score, energy in ((1, 0.9, -4.0), (2, 0.7, -9.0)):
        raw = f"synthetic pose {mode}".encode()
        poses.append(
            GninaPoseResult(
                mode=mode,
                cnn_score=score,
                cnn_affinity=7 + mode,
                minimized_affinity_kcal_mol=energy,
                artifact=GninaPoseArtifact(
                    artifact_id=f"pose-{mode}",
                    mode=mode,
                    filename=f"pose_{mode}.pdbqt",
                    sha256=sha256(raw).hexdigest(),
                    size_bytes=len(raw),
                ),
            )
        )
    return GninaJobRecord(
        job_id=store.new_job_id(),
        status=DockingJobStatus.COMPLETED,
        phase=DockingJobPhase.COMPLETE,
        created_at=datetime.now(UTC),
        completed_at=datetime.now(UTC),
        request=request,
        tool=GninaToolIdentity(version="1.3.3", sha256="a" * 64, architecture="x86_64"),
        box=BindingBox(center_x=1, center_y=2, center_z=3, size_x=10, size_y=12, size_z=14),
        receptor_output_artifact_id="receptor-pdbqt",
        receptor_sha256="b" * 64,
        ligand_sha256="c" * 64,
        conformer_sha256="d" * 64,
        execution=GninaExecutionEvidence(
            command=["synthetic-gnina"], exit_code=0, stdout="", stderr=""
        ),
        poses=poses,
    )


def test_screening_children_do_not_appear_as_independent_campaigns(tmp_path, monkeypatch):
    monkeypatch.setenv("ANKORA_DATA_DIR", str(tmp_path))
    store = GninaJobStore.from_environment()
    standalone = _completed(store)
    child = _completed(store).model_copy(update={"screening_campaign_id": str(uuid4())})
    store.create_job(standalone)
    store.create_job(child)
    with TestClient(create_app()) as client:
        page = client.get("/api/v1/results/campaigns?scoring_family=gnina").json()
        assert page["total"] == 1
        assert page["entries"][0]["catalog_id"] == f"gnina_job:{standalone.job_id}"


def test_catalog_keeps_gnina_score_axes_and_renders_methods(tmp_path, monkeypatch):
    monkeypatch.setenv("ANKORA_DATA_DIR", str(tmp_path))
    store = GninaJobStore.from_environment()
    job = _completed(store)
    store.create_job(job)
    for pose in job.poses:
        store.write_artifact(
            job.job_id, pose.artifact.filename, f"synthetic pose {pose.mode}".encode()
        )
    with TestClient(create_app()) as client:
        page = client.get("/api/v1/results/campaigns?scoring_family=gnina").json()
        assert page["total"] == 1
        entry = page["entries"][0]
        assert entry["engine_key"] == "gnina_job" and entry["succeeded_count"] == 1
        assert entry["best_result_kcal_mol"] is None
        assert entry["primary_cnn_score"] == 0.9
        assert entry["cnn_affinity_pk"] == 8 and entry["minimized_affinity_kcal_mol"] == -4
        assert entry["box"]["center_x"] == 1
        detail = client.get(f"/api/v1/results/campaigns/gnina_job/{job.job_id}")
        assert detail.status_code == 200
        assert detail.json()["reproducibility"]["status"] == "not_assessed"
        compounds = client.get(f"/api/v1/results/campaigns/gnina_job/{job.job_id}/compounds").json()
        assert compounds["value_label"].startswith("CNN score")
        assert compounds["rows"][0]["primary_cnn_score"] == 0.9
        assert compounds["rows"][0]["best_result_kcal_mol"] is None
        # Methods used to fail closed here; it now renders GNINA's own protocol.
        # The axes must stay apart in the prose exactly as they do in the catalog.
        methods = client.get(f"/api/v1/results/campaigns/gnina_job/{job.job_id}/methods")
        assert methods.status_code == 200
        markdown = methods.json()["markdown"]
        assert "descending CNN pose score" in markdown
        assert "not an energy and has no kcal/mol interpretation" in markdown
        assert "CNN pose score of 0.9" in markdown
        assert "minimized affinity of -4 kcal mol⁻¹" in markdown
        assert "Lamarckian" not in markdown and "AutoGrid" not in markdown
        assert (
            client.get(f"/api/v1/docking/gnina/jobs/{job.job_id}").json()["poses"][0]["mode"] == 1
        )


def test_catalog_deletes_gnina_job_as_a_complete_recoverable_result(tmp_path, monkeypatch):
    monkeypatch.setenv("ANKORA_DATA_DIR", str(tmp_path))
    store = GninaJobStore.from_environment()
    job = _completed(store)
    store.create_job(job)
    store.write_artifact(job.job_id, "pose_1.pdbqt", b"synthetic pose 1")
    with TestClient(create_app()) as client:
        response = client.post(
            "/api/v1/results/campaigns/trash",
            json={
                "catalog_ids": [f"gnina_job:{job.job_id}"],
                "acknowledge_removal": True,
            },
        )
        assert response.status_code == 200
        assert response.json()["recoverable"] is True
        assert client.get(f"/api/v1/docking/gnina/jobs/{job.job_id}").status_code == 404
        assert client.get("/api/v1/results/campaigns?scoring_family=gnina").json()["total"] == 0


def test_group_delete_rejects_active_job_without_moving_any_result(tmp_path, monkeypatch):
    monkeypatch.setenv("ANKORA_DATA_DIR", str(tmp_path))
    store = GninaJobStore.from_environment()
    first, second = _completed(store), _completed(store)
    running = _completed(store).model_copy(
        update={
            "status": DockingJobStatus.RUNNING,
            "phase": DockingJobPhase.DOCKING,
            "poses": [],
            "execution": None,
            "completed_at": None,
        }
    )
    for job in (first, second, running):
        store.create_job(job)
    with TestClient(create_app()) as client:
        # Recovery reconciles abandoned work; restore the active record after startup.
        store.update_job(running)
        active_selection = [f"gnina_job:{first.job_id}", f"gnina_job:{running.job_id}"]
        rejected = client.post(
            "/api/v1/results/campaigns/trash",
            json={
                "catalog_ids": active_selection,
                "acknowledge_removal": True,
            },
        )
        assert rejected.status_code == 409 and rejected.json()["code"] == "RESULT_TRASH_ACTIVE"
        assert store.load_job(first.job_id).status is DockingJobStatus.COMPLETED
        removed = client.post(
            "/api/v1/results/campaigns/trash",
            json={
                "catalog_ids": [f"gnina_job:{first.job_id}", f"gnina_job:{second.job_id}"],
                "acknowledge_removal": True,
            },
        )
        assert removed.status_code == 200 and len(removed.json()["campaigns"]) == 2
        assert store.load_job(running.job_id).status is DockingJobStatus.RUNNING


def test_catalog_orders_gnina_jobs_by_time_not_cnn_score(tmp_path, monkeypatch):
    monkeypatch.setenv("ANKORA_DATA_DIR", str(tmp_path))
    store = GninaJobStore.from_environment()
    older = _completed(store)
    newer = _completed(store)
    newer_pose = newer.poses[0].model_copy(update={"cnn_score": 0.8})
    newer = newer.model_copy(
        update={
            "created_at": older.created_at + timedelta(seconds=1),
            "poses": [newer_pose, newer.poses[1]],
        }
    )
    store.create_job(older)
    store.create_job(newer)
    with TestClient(create_app()) as client:
        entries = client.get("/api/v1/results/campaigns?scoring_family=gnina").json()["entries"]
        assert [entry["record_id"] for entry in entries] == [newer.job_id, older.job_id]
        assert [entry["primary_cnn_score"] for entry in entries] == [0.8, 0.9]


def _synthetic_screening_campaign(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[GninaScreeningStore, GninaJobStore, str, str]:
    monkeypatch.setenv("ANKORA_DATA_DIR", str(tmp_path))
    screening_store = GninaScreeningStore.from_environment()
    job_store = screening_store.jobs
    campaign_id = screening_store.new_campaign_id()
    now = datetime.now(UTC)
    receptor_bytes = b"synthetic receptor pdbqt\n"
    receptor_sha = sha256(receptor_bytes).hexdigest()
    tool = GninaToolIdentity(version="1.3.3", sha256="a" * 64, architecture="x86_64")
    box = BindingBox(center_x=1, center_y=2, center_z=3, size_x=10, size_y=12, size_z=14)
    request = GninaScreeningRequest(
        receptor_id="synthetic-receptor",
        binding_site_id="synthetic-site",
        library_id="synthetic-library",
        filter_run_id="synthetic-filter",
        parameters=GninaDockingParameters(compute="cuda"),
        acknowledge_inputs_and_scoring=True,
    )
    entries = [
        GninaScreeningEntry(
            ligand_id="synthetic-alpha",
            chemical_state_id="state-alpha",
            source_index=4,
            name="Synthetic Alpha",
            ligand_preparation_id="prep-alpha",
            ligand_sha256=sha256(b"ligand alpha").hexdigest(),
            conformer_id="conf-alpha",
            conformer_sha256=sha256(b"conformer alpha").hexdigest(),
            status=DockingJobStatus.QUEUED,
            phase=DockingJobPhase.QUEUED,
        ),
        GninaScreeningEntry(
            ligand_id="synthetic-beta",
            chemical_state_id="state-beta",
            source_index=1,
            name="Synthetic Beta",
            ligand_preparation_id="prep-beta",
            ligand_sha256=sha256(b"ligand beta").hexdigest(),
            conformer_id="conf-beta",
            conformer_sha256=sha256(b"conformer beta").hexdigest(),
            status=DockingJobStatus.QUEUED,
            phase=DockingJobPhase.QUEUED,
        ),
        GninaScreeningEntry(
            ligand_id="synthetic-unprepared",
            chemical_state_id="state-unprepared",
            source_index=None,
            name=None,
            status=DockingJobStatus.FAILED,
            phase=DockingJobPhase.COMPLETE,
            completed_at=now,
            failure=DockingFailure(
                code=GninaScreeningPreflightCode.LIBRARY_RECORD_MISSING,
                message="synthetic missing library record",
            ),
        ),
    ]
    record = GninaScreeningCampaignRecord(
        campaign_id=campaign_id,
        status=DockingJobStatus.QUEUED,
        phase=DockingJobPhase.QUEUED,
        created_at=now,
        request=request,
        tool=tool,
        selection=GninaScreeningSelection(
            library_id="synthetic-library",
            filter_run_id="synthetic-filter",
            manifest_artifact_id="synthetic-filter",
            manifest_sha256="e" * 64,
        ),
        receptor_output_artifact_id="receptor-pdbqt",
        receptor_sha256=receptor_sha,
        box=box,
        selected_count=3,
        completed_count=1,
        failed_count=1,
        entries=entries,
    )
    selection_stub = SimpleNamespace(
        artifact=SimpleNamespace(sha256="e" * 64, filter_run_id="synthetic-filter"),
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
    screening_store.create_campaign(record)

    # Deliberately discordant: Beta has higher CNNscore (0.93) and weaker kcal/mol (-3.2)
    # than Alpha (0.72, -9.4 kcal/mol), proving catalog projection ranks by CNNscore.
    specs = (
        ("synthetic-alpha", "prep-alpha", b"ligand alpha", b"conformer alpha", 0.72, 6.1, -9.4),
        ("synthetic-beta", "prep-beta", b"ligand beta", b"conformer beta", 0.93, 7.8, -3.2),
    )
    beta_job_id = ""
    for ligand_id, prep_id, lig_bytes, conf_bytes, cnn_score, cnn_aff, energy in specs:
        pose_bytes = f"synthetic pose {ligand_id}".encode()
        job_id = job_store.new_job_id()
        if ligand_id == "synthetic-beta":
            beta_job_id = job_id
        job = GninaJobRecord(
            job_id=job_id,
            screening_campaign_id=campaign_id,
            status=DockingJobStatus.COMPLETED,
            phase=DockingJobPhase.COMPLETE,
            created_at=now,
            started_at=now,
            completed_at=now,
            request=GninaDockingRequest(
                receptor_id="synthetic-receptor",
                binding_site_id="synthetic-site",
                ligand_id=ligand_id,
                ligand_preparation_id=prep_id,
                parameters=request.parameters,
                acknowledge_inputs_and_scoring=True,
            ),
            tool=tool,
            box=box,
            receptor_output_artifact_id="receptor-pdbqt",
            receptor_sha256=receptor_sha,
            ligand_sha256=sha256(lig_bytes).hexdigest(),
            conformer_sha256=sha256(conf_bytes).hexdigest(),
            execution=GninaExecutionEvidence(
                command=["synthetic-gnina"],
                exit_code=0,
                stdout="",
                stderr="",
                gpu_process_observed=True,
                gpu_observation="nvidia_smi_compute_apps_observed",
                requested_gpu_uuid="GPU-synthetic-0",
                observed_gpu_uuid="GPU-synthetic-0",
            ),
            poses=[
                GninaPoseResult(
                    mode=1,
                    cnn_score=cnn_score,
                    cnn_affinity=cnn_aff,
                    minimized_affinity_kcal_mol=energy,
                    artifact=GninaPoseArtifact(
                        artifact_id=f"pose-{ligand_id}-1",
                        mode=1,
                        filename="pose_1.pdbqt",
                        sha256=sha256(pose_bytes).hexdigest(),
                        size_bytes=len(pose_bytes),
                    ),
                )
            ],
        )
        job_store.create_job(job)
        job_store.write_artifact(job_id, "receptor.pdbqt", receptor_bytes)
        job_store.write_artifact(job_id, "ligand.pdbqt", lig_bytes)
        job_store.write_artifact(job_id, "conformer.sdf", conf_bytes)
        job_store.write_artifact(job_id, "pose_1.pdbqt", pose_bytes)

        stored_entry = screening_store.load_entry(campaign_id, ligand_id)
        assert stored_entry is not None
        running = screening_store.update_entry(
            campaign_id,
            stored_entry.model_copy(
                update={
                    "status": DockingJobStatus.RUNNING,
                    "phase": DockingJobPhase.DOCKING,
                    "gnina_job_id": job_id,
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
    return screening_store, job_store, campaign_id, beta_job_id


def test_gnina_screening_projects_into_catalog_ranked_by_cnn_score(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, _, campaign_id, _ = _synthetic_screening_campaign(tmp_path, monkeypatch)
    with TestClient(create_app()) as client:
        page = client.get("/api/v1/results/campaigns?scoring_family=gnina&mode=screening").json()
        assert page["total"] == 1
        entry = page["entries"][0]
        assert entry["catalog_id"] == f"gnina_screening:{campaign_id}"
        assert entry["engine_key"] == "gnina_screening"
        assert entry["mode"] == "screening"
        assert entry["scoring_family"] == "gnina"
        assert entry["backend"] == "cuda"
        assert entry["device_name"] == "GPU-synthetic-0"
        assert entry["selected_count"] == 3
        assert entry["succeeded_count"] == 2
        assert entry["failed_count"] == 1
        assert entry["best_result_kcal_mol"] is None
        assert entry["primary_cnn_score"] == 0.93
        assert entry["cnn_affinity_pk"] == 7.8
        assert entry["minimized_affinity_kcal_mol"] == -3.2
        assert entry["best_molecule"] == "Synthetic Beta"

        compounds = client.get(
            f"/api/v1/results/campaigns/gnina_screening/{campaign_id}/compounds"
        ).json()
        assert compounds["value_label"] == "CNN score (higher ranks first)"
        assert [row["ligand_id"] for row in compounds["rows"]] == [
            "synthetic-beta",
            "synthetic-alpha",
            "synthetic-unprepared",
        ]
        assert [row["primary_cnn_score"] for row in compounds["rows"]] == [0.93, 0.72, None]
        assert [row["minimized_affinity_kcal_mol"] for row in compounds["rows"]] == [
            -3.2,
            -9.4,
            None,
        ]
        assert all(row["best_result_kcal_mol"] is None for row in compounds["rows"])
        assert (
            compounds["rows"][2]["failure_code"]
            == GninaScreeningPreflightCode.LIBRARY_RECORD_MISSING
        )


def test_gnina_screening_catalog_fails_closed_when_child_pose_is_tampered(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, job_store, campaign_id, beta_job_id = _synthetic_screening_campaign(tmp_path, monkeypatch)
    original_pose = job_store.output_path(beta_job_id, "pose_1.pdbqt").read_bytes()
    job_store.output_path(beta_job_id, "pose_1.pdbqt").write_bytes(b"tampered pose bytes")
    with TestClient(create_app()) as client:
        detail = client.get(f"/api/v1/results/campaigns/gnina_screening/{campaign_id}")
        assert detail.status_code == 409
        assert detail.json()["code"] == "GNINA_POSE_INTEGRITY_FAILED"
        compounds = client.get(
            f"/api/v1/results/campaigns/gnina_screening/{campaign_id}/compounds"
        )
        assert compounds.status_code == 409
        assert compounds.json()["code"] == "GNINA_POSE_INTEGRITY_FAILED"

        job_store.output_path(beta_job_id, "pose_1.pdbqt").write_bytes(original_pose)
        job_store.output_path(beta_job_id, "ligand.pdbqt").write_bytes(b"tampered ligand bytes")
        drifted = client.get(f"/api/v1/results/campaigns/gnina_screening/{campaign_id}")
        assert drifted.status_code == 409
        assert drifted.json()["code"] == "GNINA_SCREENING_JOB_MISMATCH"


def test_recorded_cuda_campaign_projects_into_catalog_when_present(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
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
        page = client.get("/api/v1/results/campaigns?scoring_family=gnina&mode=screening").json()
        assert page["total"] == 1
        entry = page["entries"][0]
        assert entry["engine_key"] == "gnina_screening"
        assert entry["succeeded_count"] == 11
        assert entry["best_result_kcal_mol"] is None
        assert entry["best_molecule"] == "NCI-68"
        assert entry["primary_cnn_score"] == pytest.approx(0.939, abs=1e-4)
        compounds = client.get(
            f"/api/v1/results/campaigns/gnina_screening/{entry['record_id']}/compounds"
        ).json()
        assert compounds["total"] == 11
        assert compounds["rows"][0]["name"] == "NCI-68"
        assert compounds["rows"][1]["name"] == "NCI-76"
        assert compounds["rows"][0]["primary_cnn_score"] > compounds["rows"][1]["primary_cnn_score"]
        assert (
            compounds["rows"][0]["minimized_affinity_kcal_mol"]
            > compounds["rows"][1]["minimized_affinity_kcal_mol"]
        )


def test_gnina_screening_hit_ranking_metric_cnn_vs_ranks_and_surfaces_nonpositive_warning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Synthetic CNN_VS campaign: Beta (0.82*8.0=6.56) beats Alpha (0.90*5.0=4.50),
    ties break by selection_order (Beta before Gamma), and negative pK emits warning.
    """
    monkeypatch.setenv("ANKORA_DATA_DIR", str(tmp_path))
    job_store = GninaJobStore.from_environment()
    screening_store = GninaScreeningStore.from_environment()
    campaign_id = screening_store.new_campaign_id()
    now = datetime.now(UTC)
    receptor_bytes = b"synthetic receptor pdbqt"
    receptor_sha = sha256(receptor_bytes).hexdigest()
    box = BindingBox(center_x=1, center_y=2, center_z=3, size_x=10, size_y=12, size_z=14)
    tool = GninaToolIdentity(version="1.3.3", sha256="a" * 64, architecture="x86_64")
    request = GninaScreeningRequest(
        receptor_id="synthetic-receptor",
        binding_site_id="synthetic-site",
        library_id="synthetic-library",
        filter_run_id="synthetic-filter",
        parameters=GninaDockingParameters(compute="cuda", device_index=0),
        hit_ranking_metric="cnn_vs",
        acknowledge_inputs_and_scoring=True,
    )

    specs = (
        ("synthetic-alpha", "Synthetic Alpha", 0, 0.90, 5.0, -9.2),
        ("synthetic-beta", "Synthetic Beta", 1, 0.82, 8.0, -3.5),
        ("synthetic-gamma", "Synthetic Gamma", 2, 0.82, 8.0, -10.5),
        ("synthetic-decoy", "Synthetic Decoy", 3, 0.75, -0.4, -1.1),
    )
    entries = [
        GninaScreeningEntry(
            ligand_id=lig_id,
            chemical_state_id=f"state-{lig_id}",
            source_index=idx,
            name=label,
            ligand_preparation_id=f"prep-{lig_id}",
            ligand_sha256=sha256(f"ligand {lig_id}".encode()).hexdigest(),
            conformer_id=f"conf-{lig_id}",
            conformer_sha256=sha256(f"conformer {lig_id}".encode()).hexdigest(),
            status=DockingJobStatus.QUEUED,
            phase=DockingJobPhase.QUEUED,
        )
        for lig_id, label, idx, *_ in specs
    ]
    selection_stub = SimpleNamespace(
        artifact=SimpleNamespace(sha256="e" * 64, filter_run_id="synthetic-filter"),
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
    screening_store.create_campaign(
        GninaScreeningCampaignRecord(
            campaign_id=campaign_id,
            status=DockingJobStatus.QUEUED,
            phase=DockingJobPhase.QUEUED,
            created_at=now,
            request=request,
            tool=tool,
            selection=GninaScreeningSelection(
                library_id="synthetic-library",
                filter_run_id="synthetic-filter",
                manifest_artifact_id="synthetic-filter",
                manifest_sha256="e" * 64,
            ),
            receptor_output_artifact_id="receptor-pdbqt",
            receptor_sha256=receptor_sha,
            box=box,
            selected_count=len(entries),
            entries=entries,
        )
    )

    for lig_id, _label, _idx, cnn_score, cnn_aff, energy in specs:
        lig_bytes = f"ligand {lig_id}".encode()
        conf_bytes = f"conformer {lig_id}".encode()
        pose_bytes = f"synthetic pose {lig_id}".encode()
        job_id = job_store.new_job_id()
        job = GninaJobRecord(
            job_id=job_id,
            screening_campaign_id=campaign_id,
            status=DockingJobStatus.COMPLETED,
            phase=DockingJobPhase.COMPLETE,
            created_at=now,
            started_at=now,
            completed_at=now,
            request=GninaDockingRequest(
                receptor_id="synthetic-receptor",
                binding_site_id="synthetic-site",
                ligand_id=lig_id,
                ligand_preparation_id=f"prep-{lig_id}",
                parameters=request.parameters,
                acknowledge_inputs_and_scoring=True,
            ),
            tool=tool,
            box=box,
            receptor_output_artifact_id="receptor-pdbqt",
            receptor_sha256=receptor_sha,
            ligand_sha256=sha256(lig_bytes).hexdigest(),
            conformer_sha256=sha256(conf_bytes).hexdigest(),
            execution=GninaExecutionEvidence(
                command=["synthetic-gnina"],
                exit_code=0,
                stdout="",
                stderr="",
                gpu_process_observed=True,
                gpu_observation="nvidia_smi_compute_apps_observed",
                requested_gpu_uuid="GPU-synthetic-0",
                observed_gpu_uuid="GPU-synthetic-0",
            ),
            poses=[
                GninaPoseResult(
                    mode=1,
                    cnn_score=cnn_score,
                    cnn_affinity=cnn_aff,
                    cnn_vs=cnn_score * cnn_aff,
                    cnn_vs_source="derived_from_recorded_axes",
                    minimized_affinity_kcal_mol=energy,
                    artifact=GninaPoseArtifact(
                        artifact_id=f"pose-{lig_id}-1",
                        mode=1,
                        filename="pose_1.pdbqt",
                        sha256=sha256(pose_bytes).hexdigest(),
                        size_bytes=len(pose_bytes),
                    ),
                )
            ],
        )
        job_store.create_job(job)
        job_store.write_artifact(job_id, "receptor.pdbqt", receptor_bytes)
        job_store.write_artifact(job_id, "ligand.pdbqt", lig_bytes)
        job_store.write_artifact(job_id, "conformer.sdf", conf_bytes)
        job_store.write_artifact(job_id, "pose_1.pdbqt", pose_bytes)

        stored_entry = screening_store.load_entry(campaign_id, lig_id)
        assert stored_entry is not None
        running = screening_store.update_entry(
            campaign_id,
            stored_entry.model_copy(
                update={
                    "status": DockingJobStatus.RUNNING,
                    "phase": DockingJobPhase.DOCKING,
                    "gnina_job_id": job_id,
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
    progress = screening_store.load_progress(campaign_id)
    assert [w.code for w in progress.warnings] == ["GNINA_CNN_VS_NONPOSITIVE_AFFINITY"]

    with TestClient(create_app()) as client:
        page = client.get("/api/v1/results/campaigns?scoring_family=gnina&mode=screening").json()
        assert page["total"] == 1
        entry = page["entries"][0]
        assert entry["hit_ranking_metric"] == "cnn_vs"
        assert entry["best_molecule"] == "Synthetic Beta"
        assert entry["primary_cnn_vs"] == pytest.approx(6.56)
        assert entry["primary_cnn_score"] == pytest.approx(0.82)
        assert entry["cnn_affinity_pk"] == pytest.approx(8.0)
        assert [w["code"] for w in entry["warnings"]] == ["GNINA_CNN_VS_NONPOSITIVE_AFFINITY"]

        compounds = client.get(
            f"/api/v1/results/campaigns/gnina_screening/{campaign_id}/compounds"
        ).json()
        assert compounds["value_label"] == "CNN_VS (higher ranks first)"
        assert [row["ligand_id"] for row in compounds["rows"]] == [
            "synthetic-beta",
            "synthetic-gamma",
            "synthetic-alpha",
            "synthetic-decoy",
        ]
        assert [row["cnn_vs"] for row in compounds["rows"]] == pytest.approx(
            [6.56, 6.56, 4.50, -0.30]
        )
        assert [row["primary_cnn_score"] for row in compounds["rows"]] == pytest.approx(
            [0.82, 0.82, 0.90, 0.75]
        )

