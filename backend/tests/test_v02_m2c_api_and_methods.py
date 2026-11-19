"""HTTP API and MethodsReport tests for Ankora v0.2 Milestone M2c.

All fixtures in this module are synthetic and explicitly labelled synthetic.
"""

from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from ankora_backend.adapters.engines.vina import VinaInstallation
from ankora_backend.api.app import create_app
from ankora_backend.execution.cancellable_subprocess import CancellableToolExecution
from ankora_backend.persistence.binding_site_store import BindingSiteArtifactStore
from ankora_backend.persistence.docking_store import DockingArtifactStore
from ankora_backend.persistence.receptor_store import ReceptorArtifactStore
from ankora_backend.schemas.binding_sites import (
    BindingBox,
    BindingSiteRecord,
    BindingSiteRequest,
    BindingSiteSource,
)
from ankora_backend.schemas.calibration import CalibrationRunRecord
from ankora_backend.schemas.docking import (
    DockingJobPhase,
    DockingJobStatus,
    DockingPoseArtifact,
    DockingPoseResult,
    VinaDockingJobRecord,
    VinaDockingParameters,
    VinaDockingRequest,
)
from ankora_backend.schemas.provenance import ProvenanceEvent, ToolIdentity
from ankora_backend.schemas.receptors import (
    ComponentAction,
    ProtonationSettings,
    ReceptorFlexMode,
    ReceptorFlexRequest,
    ReceptorFlexSpec,
    ReceptorOutputArtifact,
    ReceptorOutputStage,
    ReceptorPreparationRecord,
    ReceptorPreparationRequest,
    ReceptorPreparationStatus,
    ResidueLocator,
)
from ankora_backend.schemas.rescoring import PoseRescoreResult
from ankora_backend.schemas.screening_benchmark import ScoreDirection
from ankora_backend.schemas.v02_contracts import (
    ObservationStatus,
    PoseComplexIdentity,
    ProtocolSpec,
    ScoreObservation,
    ScoringFamily,
    ScoringFunctionId,
    canonical_contract_sha256,
)
from ankora_backend.services import pose_rescoring as rescoring_module
from ankora_backend.services.methods_report import render_calibration_methods

_SYNTHETIC_COMPOUNDS = [
    # 6 distinct scaffolds across actives & inactives so split is feasible
    {"parent_id": "SYNTH_A1", "canonical_smiles": "c1ccccc1O", "is_active": True},
    {"parent_id": "SYNTH_A2", "canonical_smiles": "c1ccncc1O", "is_active": True},
    {"parent_id": "SYNTH_A3", "canonical_smiles": "c1ccc2ccccc2c1O", "is_active": True},
    {"parent_id": "SYNTH_A4", "canonical_smiles": "c1ccc2[nH]ccc2c1O", "is_active": True},
    {"parent_id": "SYNTH_A5", "canonical_smiles": "c1csc(C)c1O", "is_active": True},
    {"parent_id": "SYNTH_A6", "canonical_smiles": "c1cnc2ccccc2n1", "is_active": True},
    {"parent_id": "SYNTH_I1", "canonical_smiles": "c1ccccc1C", "is_active": False},
    {"parent_id": "SYNTH_I2", "canonical_smiles": "c1ccncc1C", "is_active": False},
    {"parent_id": "SYNTH_I3", "canonical_smiles": "c1ccc2ccccc2c1C", "is_active": False},
    {"parent_id": "SYNTH_I4", "canonical_smiles": "c1ccc2[nH]ccc2c1C", "is_active": False},
    {"parent_id": "SYNTH_I5", "canonical_smiles": "c1csc(C)c1C", "is_active": False},
    {"parent_id": "SYNTH_I6", "canonical_smiles": "c1cnc2ccccc2c1", "is_active": False},
    {"parent_id": "SYNTH_I7", "canonical_smiles": "C1CCCCC1O", "is_active": False},
    {"parent_id": "SYNTH_I8", "canonical_smiles": "C1CCNCC1", "is_active": False},
    {"parent_id": "SYNTH_I9", "canonical_smiles": "C1COCCN1", "is_active": False},
    {"parent_id": "SYNTH_I10", "canonical_smiles": "c1ccoc1C", "is_active": False},
]


def _sha(data: bytes) -> str:
    return sha256(data).hexdigest()


def _synthetic_obs(
    *,
    protocol_sha: str,
    parent_id: str,
    score: float,
    scoring_function: ScoringFunctionId,
    rigid_sha: str,
) -> dict[str, Any]:
    pose = PoseComplexIdentity(
        mode=ReceptorFlexMode.RIGID,
        receptor_rigid_sha256=rigid_sha,
        ligand_pose_sha256=_sha(f"{protocol_sha}:{parent_id}".encode()),
    )
    return ScoreObservation(
        protocol_identity_sha256=protocol_sha,
        parent_compound_id=parent_id,
        parent_state_id=f"{parent_id}_S1",
        pose_complex=pose,
        scoring_family=ScoringFamily.VINA_VINARDO,
        scoring_function=scoring_function,
        direction=ScoreDirection.LOWER_IS_BETTER,
        unit="kcal/mol",
        tool_name="AutoDock Vina",
        tool_version="1.2.7",
        status=ObservationStatus.SCORED,
        raw_score=score,
    ).model_dump(mode="json")


def test_calibration_http_lifecycle_enforces_stage_guards_and_renders_methods(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ANKORA_DATA_DIR", str(tmp_path))
    app = create_app()
    rigid_sha = "1" * 64
    box_sha = "2" * 64
    rigid_spec = ReceptorFlexSpec(mode=ReceptorFlexMode.RIGID, receptor_rigid_sha256=rigid_sha)
    base_proto = ProtocolSpec(
        engine="vina",
        scoring_function=ScoringFunctionId.VINA,
        receptor_flexibility=rigid_spec,
        binding_box_sha256=box_sha,
    )
    vinardo_proto = ProtocolSpec(
        engine="vina",
        scoring_function=ScoringFunctionId.VINARDO,
        receptor_flexibility=rigid_spec,
        binding_box_sha256=box_sha,
    )

    with TestClient(app) as client:
        # OpenAPI includes all M2c routes
        spec = client.get("/api/openapi.json").json()
        for route in (
            "/api/v1/calibrations",
            "/api/v1/calibrations/{calibration_id}",
            "/api/v1/calibrations/splits",
            "/api/v1/calibrations/{calibration_id}/select",
            "/api/v1/calibrations/{calibration_id}/confirm",
            "/api/v1/rescoring/score-only",
        ):
            assert route in spec["paths"], f"Missing OpenAPI route {route}"

        # Empty list + 404 lookup
        assert client.get("/api/v1/calibrations").json() == {"runs": []}
        missing = client.get("/api/v1/calibrations/00000000-0000-0000-0000-000000000000")
        assert missing.status_code == 404
        assert missing.json()["code"] == "CALIBRATION_NOT_FOUND"

        # Stage 1: Create scaffold-grouped split
        split_resp = client.post(
            "/api/v1/calibrations/splits",
            json={
                "receptor_id": "synth-rec-1",
                "binding_site_id": "synth-site-1",
                "compounds": _SYNTHETIC_COMPOUNDS,
                "policy": {
                    "calibration_fraction": 0.6,
                    "split_seed": 20261119,
                    "min_confirmation_actives": 2,
                    "bootstrap_replicates": 200,
                    "bootstrap_seed": 20261119,
                },
            },
        )
        assert split_resp.status_code == 201, split_resp.text
        run = split_resp.json()
        cal_id = run["calibration_id"]
        assert run["status"] == "split_locked"
        assert run["confirmation_locked"] is True
        assert run["confirmation_consumed"] is False

        # Fail-closed: cannot confirm before selection is sealed
        early_confirm = client.post(
            f"/api/v1/calibrations/{cal_id}/confirm",
            json={"observations_by_protocol": {}},
        )
        assert early_confirm.status_code == 409
        assert early_confirm.json()["code"] == "CALIBRATION_SELECTION_REQUIRED"

        # Stage 2: Select on Calibration (tied scores -> baseline retained / null confirmation)
        cal_parents = run["split"]["calibration_parent_ids"]
        conf_parents = run["split"]["confirmation_parent_ids"]
        candidates = [
            {
                "protocol_id": "vina_base",
                "label": "Vina rigid baseline",
                "protocol_spec": base_proto.model_dump(mode="json"),
            },
            {
                "protocol_id": "vinardo_cand",
                "label": "Vinardo rigid candidate",
                "protocol_spec": vinardo_proto.model_dump(mode="json"),
                "fitted_parameter_count": 1,
            },
        ]
        cal_obs = {
            "vina_base": [
                _synthetic_obs(
                    protocol_sha=base_proto.protocol_identity_sha256,
                    parent_id=pid,
                    score=-7.0,
                    scoring_function=ScoringFunctionId.VINA,
                    rigid_sha=rigid_sha,
                )
                for pid in cal_parents
            ],
            "vinardo_cand": [
                _synthetic_obs(
                    protocol_sha=vinardo_proto.protocol_identity_sha256,
                    parent_id=pid,
                    score=-7.0,
                    scoring_function=ScoringFunctionId.VINARDO,
                    rigid_sha=rigid_sha,
                )
                for pid in cal_parents
            ],
        }
        sel_resp = client.post(
            f"/api/v1/calibrations/{cal_id}/select",
            json={
                "baseline_protocol_id": "vina_base",
                "candidates": candidates,
                "observations_by_protocol": cal_obs,
            },
        )
        assert sel_resp.status_code == 200, sel_resp.text
        selected_run = sel_resp.json()
        assert selected_run["status"] == "calibration_selected"
        assert selected_run["confirmation_locked"] is True
        assert selected_run["calibration_selection"]["selected_protocol_id"] == "vina_base"

        # Fail-closed: cannot re-select after sealing
        reselect = client.post(
            f"/api/v1/calibrations/{cal_id}/select",
            json={
                "baseline_protocol_id": "vina_base",
                "candidates": candidates,
                "observations_by_protocol": cal_obs,
            },
        )
        assert reselect.status_code == 409
        assert reselect.json()["code"] == "CALIBRATION_SELECTION_ALREADY_SEALED"

        # Stage 3: Single-use unlock and evaluate locked Confirmation
        conf_obs = {
            "vina_base": [
                _synthetic_obs(
                    protocol_sha=base_proto.protocol_identity_sha256,
                    parent_id=pid,
                    score=-7.0,
                    scoring_function=ScoringFunctionId.VINA,
                    rigid_sha=rigid_sha,
                )
                for pid in conf_parents
            ],
            "vinardo_cand": [
                _synthetic_obs(
                    protocol_sha=vinardo_proto.protocol_identity_sha256,
                    parent_id=pid,
                    score=-7.0,
                    scoring_function=ScoringFunctionId.VINARDO,
                    rigid_sha=rigid_sha,
                )
                for pid in conf_parents
            ],
        }
        conf_resp = client.post(
            f"/api/v1/calibrations/{cal_id}/confirm",
            json={"observations_by_protocol": conf_obs},
        )
        assert conf_resp.status_code == 200, conf_resp.text
        final_run = conf_resp.json()
        assert final_run["status"] == "confirmation_completed"
        assert final_run["confirmation_locked"] is False
        assert final_run["confirmation_consumed"] is True
        assert (
            final_run["confirmation_evaluation"]["verdict_text"]
            == "Insufficient evidence to prefer over baseline"
        )

        # Fail-closed: single-use confirmation cannot be consumed twice
        second_confirm = client.post(
            f"/api/v1/calibrations/{cal_id}/confirm",
            json={"observations_by_protocol": conf_obs},
        )
        assert second_confirm.status_code == 409
        assert second_confirm.json()["code"] == "CALIBRATION_CONFIRMATION_ALREADY_CONSUMED"

        # List & get return the persisted immutable run
        listed = client.get("/api/v1/calibrations").json()["runs"]
        assert len(listed) == 1
        assert listed[0]["calibration_id"] == cal_id
        fetched = client.get(f"/api/v1/calibrations/{cal_id}").json()
        assert fetched["confirmation_evaluation"]["confirmation_identity_sha256"] == (
            final_run["confirmation_evaluation"]["confirmation_identity_sha256"]
        )

    # Record-derived Methods prose preserves split hash, 1-SE, and exact null verdict
    record = CalibrationRunRecord.model_validate(final_run)
    prose = render_calibration_methods(record)
    assert "Bemis-Murcko scaffold" in prose
    assert record.split.split_identity_sha256[:12] in prose
    assert "1-SE parsimony rule" in prose
    assert "Insufficient evidence to prefer over baseline" in prose


def test_saved_pose_rescore_http_endpoint_and_f4_methods_prose(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ANKORA_DATA_DIR", str(tmp_path))
    app = create_app()

    # Seed immutable synthetic receptor, binding site, and Vina sidechain_flex job
    rigid_bytes = (
        b"ATOM      1  CA  GLY A   1       0.000   0.000   0.000  0.00  0.00     0.000 C \n"
    )
    flex_bytes = (
        b"BEGIN_RES MET A   5\n"
        b"ROOT\n"
        b"ATOM      1  CA  MET A   5       1.000   1.000   1.000  0.00  0.00     0.000 C \n"
        b"ENDROOT\n"
        b"END_RES MET A   5\n"
    )
    pose_bytes = (
        b"MODEL 1\n"
        b"REMARK VINA RESULT:   -6.200      0.000      0.000\n"
        b"ROOT\n"
        b"ATOM      1  C1  LIG A   1       1.000   2.000   3.000  0.00  0.00     0.000 C \n"
        b"ENDROOT\n"
        b"TORSDOF 0\n"
        b"ENDMDL\n"
    )
    rigid_sha = _sha(rigid_bytes)
    flex_sha = _sha(flex_bytes)
    pose_sha = _sha(pose_bytes)
    now = datetime.now(UTC)

    receptors = ReceptorArtifactStore.from_environment()
    rec_id = receptors.new_receptor_id()
    receptors.create_receptor(rec_id)
    receptors.write_bytes(rec_id, "receptor_rigid.pdbqt", rigid_bytes)
    receptors.write_bytes(rec_id, "receptor_flex.pdbqt", flex_bytes)
    rigid_art_id = "art-rigid-1"
    flex_art_id = "art-flex-1"
    flex_locators = [ResidueLocator(chain_id="A", sequence_number=5, residue_name="MET")]
    receptors.save_record(
        ReceptorPreparationRecord(
            receptor_id=rec_id,
            source_artifact_id="struct-1",
            created_at=now,
            status=ReceptorPreparationStatus.DOCKING_READY,
            decisions=ReceptorPreparationRequest(
                selected_chains=["A"],
                water_action=ComponentAction.REMOVE,
                component_decisions=[],
                issue_decisions=[],
                protonation=ProtonationSettings(enabled=True),
                generate_pdbqt=True,
                flexibility=ReceptorFlexRequest(
                    mode=ReceptorFlexMode.SIDECHAIN_FLEX,
                    flex_residues=flex_locators,
                ),
            ),
            outputs=[
                ReceptorOutputArtifact(
                    artifact_id=rigid_art_id,
                    stage=ReceptorOutputStage.PDBQT_RIGID,
                    filename="receptor_rigid.pdbqt",
                    format="pdbqt",
                    sha256=rigid_sha,
                    size_bytes=len(rigid_bytes),
                    created_at=now,
                    content_url=f"/receptors/{rec_id}/outputs/{rigid_art_id}/content",
                ),
                ReceptorOutputArtifact(
                    artifact_id=flex_art_id,
                    stage=ReceptorOutputStage.PDBQT_FLEX,
                    filename="receptor_flex.pdbqt",
                    format="pdbqt",
                    sha256=flex_sha,
                    size_bytes=len(flex_bytes),
                    created_at=now,
                    content_url=f"/receptors/{rec_id}/outputs/{flex_art_id}/content",
                ),
            ],
            warnings=[],
            provenance=[],
            display_output_artifact_id=rigid_art_id,
            flex_spec=ReceptorFlexSpec(
                mode=ReceptorFlexMode.SIDECHAIN_FLEX,
                flex_residues=tuple(flex_locators),
                receptor_rigid_sha256=rigid_sha,
                receptor_flex_sha256=flex_sha,
                added_chi_torsion_count=3,
            ),
            flex_atom_types=["C"],
        )
    )

    sites = BindingSiteArtifactStore.from_environment()
    site_id = sites.new_binding_site_id()
    box = BindingBox(
        center_x=1.0,
        center_y=2.0,
        center_z=3.0,
        size_x=18.0,
        size_y=18.0,
        size_z=18.0,
    )
    sites.save_record(
        BindingSiteRecord(
            binding_site_id=site_id,
            receptor_id=rec_id,
            source_artifact_id="struct-1",
            created_at=now,
            box=box,
            decisions=BindingSiteRequest(
                source=BindingSiteSource.MANUAL,
                manual_box=box,
            ),
            warnings=[],
            provenance=[
                ProvenanceEvent(
                    event_id="evt-site-1",
                    event_type="binding_site_confirmed",
                    timestamp=now,
                    input_artifacts=[rec_id],
                    output_artifacts=[site_id],
                    tool=ToolIdentity(name="Ankora", version="0.2.0-dev"),
                )
            ],
        )
    )

    docking = DockingArtifactStore.from_environment()
    job_id = docking.new_job_id()
    pose_art_id = "pose-art-1"
    complex_id = PoseComplexIdentity(
        mode=ReceptorFlexMode.SIDECHAIN_FLEX,
        receptor_rigid_sha256=rigid_sha,
        pose_flex_sidechains_sha256=flex_sha,
        ligand_pose_sha256=pose_sha,
    ).complex_identity_sha256
    docking.create_job(
        VinaDockingJobRecord(
            job_id=job_id,
            status=DockingJobStatus.COMPLETED,
            phase=DockingJobPhase.COMPLETE,
            created_at=now,
            completed_at=now,
            request=VinaDockingRequest(
                receptor_id=rec_id,
                binding_site_id=site_id,
                ligand_id="synth-lig-1",
                ligand_preparation_id="synth-prep-1",
                parameters=VinaDockingParameters(),
                acknowledge_inputs_and_scoring=True,
            ),
            tool=ToolIdentity(name="AutoDock Vina", version="1.2.7"),
            receptor_output_artifact_id=rigid_art_id,
            receptor_sha256=rigid_sha,
            receptor_flex_mode=ReceptorFlexMode.SIDECHAIN_FLEX,
            receptor_flex_output_artifact_id=flex_art_id,
            receptor_flex_sha256=flex_sha,
            flex_residues=flex_locators,
            ligand_sha256=pose_sha,
            poses=[
                DockingPoseResult(
                    mode=1,
                    affinity_kcal_mol=-6.2,
                    rmsd_lower_bound_angstrom=0.0,
                    rmsd_upper_bound_angstrom=0.0,
                    artifact=DockingPoseArtifact(
                        artifact_id=pose_art_id,
                        mode=1,
                        filename="pose_1.pdbqt",
                        format="pdbqt",
                        sha256=pose_sha,
                        size_bytes=len(pose_bytes),
                        content_url=f"/docking/vina/jobs/{job_id}/poses/{pose_art_id}/content",
                        flex_filename="pose_1_flex.pdbqt",
                        pose_flex_sidechains_sha256=flex_sha,
                        flex_content_url=f"/docking/vina/jobs/{job_id}/poses/{pose_art_id}/flex",
                        pose_complex_identity_sha256=complex_id,
                    ),
                )
            ],
        )
    )
    docking.write_bytes(job_id, "pose_1.pdbqt", pose_bytes)
    docking.write_bytes(job_id, "pose_1_flex.pdbqt", flex_bytes)

    monkeypatch.setattr(
        rescoring_module,
        "probe_vina",
        lambda: VinaInstallation(executable="/synthetic/vina", version="1.2.7"),
    )

    def _fake_vina_score(**kwargs: Any) -> CancellableToolExecution:
        score = -6.25 if kwargs["scoring"] == "vina" else -6.91
        return CancellableToolExecution(
            command=["/synthetic/vina", "--score_only", "--scoring", kwargs["scoring"]],
            exit_code=0,
            stdout=(
                f"Estimated Free Energy of Binding   : {score:.3f} (kcal/mol)\n"
                "(4) Unbound System's Energy        : -0.300 (kcal/mol)\n"
            ),
            stderr="",
            timed_out=False,
            canceled=False,
        )

    monkeypatch.setattr(rescoring_module, "execute_vina_score_only", _fake_vina_score)

    with TestClient(app) as client:
        resp = client.post(
            "/api/v1/rescoring/score-only",
            json={
                "source_engine": "vina",
                "job_id": job_id,
                "pose_artifact_id": pose_art_id,
                "scoring_functions": ["vina", "vinardo"],
            },
        )
        assert resp.status_code == 200, resp.text
        payload = resp.json()
        assert payload["mutated_original_pose"] is False
        assert (
            PoseComplexIdentity.model_validate(payload["pose_complex"]).complex_identity_sha256
            == complex_id
        )
        assert len(payload["observations"]) == 2
        assert payload["observations"][0]["raw_score"] == pytest.approx(-6.25)
        assert payload["observations"][1]["raw_score"] == pytest.approx(-6.91)
        assert all(ev["unbound_reference_shifted"] is True for ev in payload["evidence"])

        # Missing pose artifact returns 404
        not_found = client.post(
            "/api/v1/rescoring/score-only",
            json={
                "source_engine": "vina",
                "job_id": job_id,
                "pose_artifact_id": "nonexistent-pose",
                "scoring_functions": ["vina"],
            },
        )
        assert not_found.status_code == 404
        assert not_found.json()["code"] == "DOCKING_POSE_NOT_FOUND"

        # MethodsReport F4 unbound-reference disclosure
        split_resp = client.post(
            "/api/v1/calibrations/splits",
            json={
                "receptor_id": rec_id,
                "binding_site_id": site_id,
                "compounds": _SYNTHETIC_COMPOUNDS,
            },
        )
        cal_record = CalibrationRunRecord.model_validate(split_resp.json())
        rescore_record = PoseRescoreResult.model_validate(payload)
        prose = render_calibration_methods(cal_record, rescoring_results=[rescore_record])
        assert "Gate 0 F4" in prose
        assert "never averaged, rescaled, or pooled" in prose
        assert canonical_contract_sha256(box) is not None
