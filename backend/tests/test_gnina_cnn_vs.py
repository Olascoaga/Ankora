"""Unit tests for ADR-028 GNINA CNN_VS persistence, hit_ranking_metric, and sign guard.

Synthetic score manipulations in this module are explicitly labeled synthetic and
exercise parser, schema, service, and transactional store invariants only.
"""

from __future__ import annotations

import threading
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError
from test_gnina_screening_preparation import prepared as prepared
from test_gnina_screening_schema import _queued, _record, _request
from test_gnina_screening_store import _create_synthetic
from test_gnina_service import _setup

from ankora_backend.adapters.engines.gnina import parse_gnina_pdbqt
from ankora_backend.domain.errors import AnkoraDomainError
from ankora_backend.execution.cancellable_subprocess import CancellableToolExecution
from ankora_backend.persistence.gnina_screening_store import GninaScreeningStore
from ankora_backend.schemas.docking import DockingJobPhase, DockingJobStatus
from ankora_backend.schemas.gnina import GninaPoseArtifact, GninaPoseResult
from ankora_backend.schemas.gnina_screening import (
    GninaScreeningCampaignRecord,
    GninaScreeningRequest,
)
from ankora_backend.schemas.warnings import WarningCode


def _synthetic_pdbqt_block(
    *,
    mode: int = 1,
    minimized_affinity: str = "-8.500",
    cnn_score: str = "0.9100",
    cnn_affinity: str = "7.2000",
    extra_remarks: list[str] | None = None,
) -> bytes:
    lines = [
        f"MODEL {mode}",
        f"REMARK minimizedAffinity {minimized_affinity}",
        f"REMARK CNNscore {cnn_score}",
        f"REMARK CNNaffinity {cnn_affinity}",
        *(extra_remarks or []),
        "HETATM    1  C   LIG A   1       1.000   2.000   3.000  1.00  0.00     0.000 C",
        "ENDMDL",
    ]
    return ("\n".join(lines) + "\n").encode("ascii")


def test_parse_gnina_pdbqt_handles_optional_cnn_vs_and_variance() -> None:
    standard = parse_gnina_pdbqt(_synthetic_pdbqt_block())
    assert len(standard) == 1
    assert standard[0].cnn_vs is None
    assert standard[0].cnn_affinity_variance is None

    with_optional = parse_gnina_pdbqt(
        _synthetic_pdbqt_block(
            extra_remarks=[
                "REMARK CNN_VS 6.5520",
                "REMARK CNNaffinity_variance 0.4215",
            ]
        )
    )
    assert with_optional[0].cnn_vs == pytest.approx(6.5520)
    assert with_optional[0].cnn_affinity_variance == pytest.approx(0.4215)


@pytest.mark.parametrize(
    "bad_remark",
    [
        ["REMARK CNNaffinity_variance -0.01"],
        ["REMARK CNN_VS nan"],
        ["REMARK CNN_VS 1.0", "REMARK CNN_VS 2.0"],
    ],
)
def test_parse_gnina_pdbqt_rejects_invalid_optional_remarks(bad_remark: list[str]) -> None:
    with pytest.raises(AnkoraDomainError) as error:
        parse_gnina_pdbqt(_synthetic_pdbqt_block(extra_remarks=bad_remark))
    assert error.value.code == "GNINA_OUTPUT_INVALID"


def test_pose_result_requires_paired_cnn_vs_provenance_and_supports_legacy_records() -> None:
    artifact = GninaPoseArtifact(
        artifact_id="synthetic-pose-1",
        mode=1,
        filename="pose_1.pdbqt",
        sha256="a" * 64,
        size_bytes=128,
    )
    legacy = GninaPoseResult(
        mode=1,
        minimized_affinity_kcal_mol=-10.2,
        cnn_score=0.95,
        cnn_affinity=8.1,
        artifact=artifact,
    )
    assert legacy.cnn_vs is None
    assert legacy.cnn_vs_source is None
    assert legacy.cnn_affinity_variance is None

    derived = GninaPoseResult(
        mode=1,
        minimized_affinity_kcal_mol=-10.2,
        cnn_score=0.95,
        cnn_affinity=8.1,
        cnn_vs=0.95 * 8.1,
        cnn_vs_source="derived_from_recorded_axes",
        artifact=artifact,
    )
    assert derived.cnn_vs == pytest.approx(7.695)

    with pytest.raises(ValidationError, match="cnn_vs and cnn_vs_source"):
        GninaPoseResult(
            mode=1,
            minimized_affinity_kcal_mol=-10.2,
            cnn_score=0.95,
            cnn_affinity=8.1,
            cnn_vs=7.695,
            artifact=artifact,
        )
    with pytest.raises(ValidationError, match="cnn_vs and cnn_vs_source"):
        GninaPoseResult(
            mode=1,
            minimized_affinity_kcal_mol=-10.2,
            cnn_score=0.95,
            cnn_affinity=8.1,
            cnn_vs_source="derived_from_recorded_axes",
            artifact=artifact,
        )
    with pytest.raises(ValidationError):
        GninaPoseResult(
            mode=1,
            minimized_affinity_kcal_mol=-10.2,
            cnn_score=0.95,
            cnn_affinity=8.1,
            cnn_vs=7.695,
            cnn_vs_source="derived_from_recorded_axes",
            cnn_affinity_variance=-0.1,
            artifact=artifact,
        )


def test_gnina_service_persists_derived_and_engine_emitted_cnn_vs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service, store, _arbiter, leases, job, installation = _setup(tmp_path / "derived", monkeypatch)
    raw = (Path(__file__).parent / "fixtures" / "gnina_real_1hsg_mk1.pdbqt").read_bytes()
    monkeypatch.setattr(
        "ankora_backend.services.gnina_docking.execute_gnina",
        lambda **kwargs: (
            kwargs["output_path"].write_bytes(raw),
            CancellableToolExecution(["gnina", "--no_gpu"], 0, "stdout", "stderr", False, False),
        )[1],
    )
    service._run(job.job_id, installation, threading.Event())
    completed = store.load_job(job.job_id)
    assert completed.status is DockingJobStatus.COMPLETED
    for pose in completed.poses:
        assert pose.cnn_vs == pytest.approx(pose.cnn_score * pose.cnn_affinity)
        assert pose.cnn_vs_source == "derived_from_recorded_axes"
        assert pose.cnn_affinity_variance is None
    leases.shutdown()
    service.shutdown()

    # Synthetic engine-emitted CNN_VS and CNNaffinity_variance branch.
    service2, store2, _arbiter2, leases2, job2, installation2 = _setup(
        tmp_path / "emitted", monkeypatch
    )
    emitted_raw = raw.replace(
        b"REMARK CNNaffinity ",
        b"REMARK CNN_VS 7.12345\nREMARK CNNaffinity_variance 0.3456\nREMARK CNNaffinity ",
        1,
    )
    monkeypatch.setattr(
        "ankora_backend.services.gnina_docking.execute_gnina",
        lambda **kwargs: (
            kwargs["output_path"].write_bytes(emitted_raw),
            CancellableToolExecution(["gnina", "--no_gpu"], 0, "stdout", "stderr", False, False),
        )[1],
    )
    service2._run(job2.job_id, installation2, threading.Event())
    completed2 = store2.load_job(job2.job_id)
    assert completed2.status is DockingJobStatus.COMPLETED
    assert completed2.poses[0].cnn_vs == pytest.approx(7.12345)
    assert completed2.poses[0].cnn_vs_source == "engine_emitted"
    assert completed2.poses[0].cnn_affinity_variance == pytest.approx(0.3456)
    assert completed2.poses[1].cnn_vs_source == "derived_from_recorded_axes"
    leases2.shutdown()
    service2.shutdown()


def test_screening_hit_ranking_metric_defaults_and_rejects_contradiction() -> None:
    default_req = _request()
    assert default_req.hit_ranking_metric == "cnn_score"

    cnn_vs_req = _request(hit_ranking_metric="cnn_vs")
    assert cnn_vs_req.hit_ranking_metric == "cnn_vs"
    campaign = _record([_queued("lig-a", 0)], request=cnn_vs_req)
    assert campaign.hit_ranking_metric == "cnn_vs"

    with pytest.raises(ValidationError, match="hit_ranking_metric"):
        _record([_queued("lig-a", 0)], request=cnn_vs_req, hit_ranking_metric="cnn_score")

    # Legacy serialized payload without hit_ranking_metric loads as cnn_score.
    raw_payload = _record([_queued("lig-a", 0)]).model_dump(mode="json")
    raw_payload.pop("hit_ranking_metric")
    raw_payload["request"].pop("hit_ranking_metric")
    loaded = GninaScreeningCampaignRecord.model_validate(raw_payload)
    assert loaded.hit_ranking_metric == "cnn_score"
    assert loaded.request.hit_ranking_metric == "cnn_score"


@pytest.mark.parametrize(
    ("metric", "synthetic_cnn_affinity", "expect_warning"),
    [
        ("cnn_vs", -0.45, True),
        ("cnn_vs", 0.0, True),
        ("cnn_vs", 6.25, False),
        ("cnn_score", -0.45, False),
    ],
)
def test_finalize_campaign_records_nonpositive_affinity_warning_without_touching_snapshot(
    prepared,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    metric: str,
    synthetic_cnn_affinity: float,
    expect_warning: bool,
) -> None:
    ligand_store, ligand_id, _prepared_entry, pdbqt, conformer = prepared
    campaign_id = str(uuid4())
    service, job_store, _arbiter, leases, initial, installation = _setup(
        tmp_path, monkeypatch, screening_campaign_id=campaign_id
    )
    pdbqt_bytes = ligand_store.pdbqt_content_path(
        ligand_id, pdbqt.artifact.preparation_id
    ).read_bytes()
    sdf_bytes = ligand_store.conformer_content_path(
        ligand_id, conformer.artifact.conformer_id
    ).read_bytes()
    job_store.output_path(initial.job_id, "ligand.pdbqt").write_bytes(pdbqt_bytes)
    job_store.output_path(initial.job_id, "conformer.sdf").write_bytes(sdf_bytes)
    request = initial.request.model_copy(
        update={
            "ligand_id": ligand_id,
            "ligand_preparation_id": pdbqt.artifact.preparation_id,
        }
    )
    job = initial.model_copy(
        update={
            "request": request,
            "ligand_sha256": pdbqt.artifact.sha256,
            "conformer_sha256": conformer.artifact.sha256,
        }
    )
    job_store.update_job(job)
    synthetic_raw = _synthetic_pdbqt_block(
        mode=1,
        minimized_affinity="-5.100",
        cnn_score="0.8200",
        cnn_affinity=f"{synthetic_cnn_affinity:.4f}",
    )
    monkeypatch.setattr(
        "ankora_backend.services.gnina_docking.execute_gnina",
        lambda **kwargs: (
            kwargs["output_path"].write_bytes(synthetic_raw),
            CancellableToolExecution(["synthetic-gnina"], 0, "", "", False, False),
        )[1],
    )
    monkeypatch.setattr(
        "ankora_backend.services.gnina_docking.require_matching_topology", lambda *_: None
    )
    service._run(job.job_id, installation, threading.Event())
    assert job_store.load_job(job.job_id).status is DockingJobStatus.COMPLETED

    store = GninaScreeningStore(tmp_path)
    entry = _queued(
        job.request.ligand_id,
        0,
        chemical_state_id=conformer.artifact.chemical_state_id,
        ligand_preparation_id=pdbqt.artifact.preparation_id,
        ligand_sha256=pdbqt.artifact.sha256,
        conformer_id=conformer.artifact.conformer_id,
        conformer_sha256=conformer.artifact.sha256,
    )
    screening_request = GninaScreeningRequest(
        receptor_id=job.request.receptor_id,
        binding_site_id=job.request.binding_site_id,
        library_id="library-synthetic",
        filter_run_id="filter-run-synthetic",
        parameters=job.request.parameters,
        hit_ranking_metric=metric,  # type: ignore[arg-type]
        acknowledge_inputs_and_scoring=True,
    )
    campaign = _record(
        [entry],
        campaign_id=campaign_id,
        status=DockingJobStatus.QUEUED,
        phase=DockingJobPhase.QUEUED,
        request=screening_request,
        tool=job.tool,
        box=job.box,
        receptor_sha256=job.receptor_sha256,
        receptor_output_artifact_id=job.receptor_output_artifact_id,
    )
    _create_synthetic(store, campaign, monkeypatch)
    snapshot_path = store.campaign_directory(campaign_id) / "record.json"
    snapshot_before = snapshot_path.read_bytes()

    running = store.update_entry(
        campaign_id,
        entry.model_copy(
            update={
                "status": DockingJobStatus.RUNNING,
                "phase": DockingJobPhase.DOCKING,
                "gnina_job_id": job.job_id,
                "started_at": datetime.now(UTC),
            }
        ),
    )
    store.update_entry(
        campaign_id,
        running.model_copy(
            update={
                "status": DockingJobStatus.COMPLETED,
                "phase": DockingJobPhase.COMPLETE,
                "completed_at": datetime.now(UTC),
            }
        ),
    )
    progress = store.finalize_campaign(campaign_id)
    assert progress.status is DockingJobStatus.COMPLETED
    assert snapshot_path.read_bytes() == snapshot_before

    final_campaign = store.load_campaign(campaign_id)
    codes = [warning.code for warning in final_campaign.warnings]
    if expect_warning:
        assert WarningCode.GNINA_CNN_VS_NONPOSITIVE_AFFINITY in codes
        matched = next(
            warning
            for warning in final_campaign.warnings
            if warning.code is WarningCode.GNINA_CNN_VS_NONPOSITIVE_AFFINITY
        )
        assert matched.details["nonpositive_count"] == 1
        assert matched.details["ligand_ids"] == [job.request.ligand_id]
        assert matched.details["min_cnn_affinity"] == pytest.approx(synthetic_cnn_affinity)
    else:
        assert WarningCode.GNINA_CNN_VS_NONPOSITIVE_AFFINITY not in codes

    leases.shutdown()
    service.shutdown()
