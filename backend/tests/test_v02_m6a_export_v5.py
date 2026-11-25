"""Tests for M6a Export v5 (M1-M5 full provenance + ADR-030 consensus bundles + stdlib verifier).

All compounds, scores, and diagnostics in this module are explicitly labelled synthetic fixtures.
"""

from __future__ import annotations

import json
import subprocess
import sys
import zipfile
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from ankora_backend.api.app import create_app
from ankora_backend.persistence.calibration_store import CalibrationArtifactStore
from ankora_backend.persistence.interaction_rules_store import (
    InteractionRuleEvaluationStore,
    InteractionRuleSetStore,
)
from ankora_backend.persistence.pose_quality_store import PoseQualityStore
from ankora_backend.schemas.calibration import CalibrationCompoundInput, CalibrationSplitPolicy
from ankora_backend.schemas.consensus import ConsensusRunRecord
from ankora_backend.schemas.exports import ExportKind
from ankora_backend.schemas.interaction_rules import (
    ClauseEvaluationResult,
    IfpBit,
    IfpCountEntry,
    IfpSourceKind,
    InteractionFingerprint,
    InteractionRuleClause,
    InteractionRuleEvaluationRecord,
    InteractionRuleKind,
    InteractionRuleSetRecord,
    InteractionTarget,
    TargetEvaluationResult,
    compute_ifp_sha256,
    compute_rule_set_identity_sha256,
)
from ankora_backend.schemas.pose_interactions import InteractionProfile, PoseKind, PoseReference
from ankora_backend.schemas.pose_quality import PoseQualityRecord
from ankora_backend.schemas.provenance import ProvenanceEvent, ToolIdentity
from ankora_backend.schemas.receptors import ReceptorFlexMode, ResidueLocator
from ankora_backend.schemas.results_catalog import ReproducibilityAssessment
from ankora_backend.schemas.v02_contracts import (
    ConformationalStrainDiagnostic,
    DiagnosticStatus,
    PoseAssessment,
    PoseComplexIdentity,
    PoseDiagnosticCheck,
)
from ankora_backend.services.campaign_export import (
    ExportedCampaign,
    _bundle_identity,
    _write_portable_bundle,
    collect_recorded_evidence,
    manifest,
    readme,
    results_csv,
)
from ankora_backend.services.export_catalog import ExportCatalogService
from ankora_backend.services.protocol_calibration import ProtocolCalibrationService

ROOT = Path(__file__).resolve().parents[2]
VERIFIER_SCRIPT = ROOT / "scripts" / "verify_export_bundle.py"


def _sha(data: bytes) -> str:
    return sha256(data).hexdigest()


def _seed_v02_pose_evidence(root: Path, *, catalog_id: str, receptor_id: str) -> dict[str, str]:
    """Write labelled synthetic immutable M3 PoseQuality + M4 InteractionRules records."""
    now = datetime(2026, 11, 20, 12, 0, tzinfo=UTC)
    rec_sha = "1" * 64
    lig_sha = "2" * 64
    pose_complex = PoseComplexIdentity(
        mode=ReceptorFlexMode.RIGID,
        receptor_rigid_sha256=rec_sha,
        ligand_pose_sha256=lig_sha,
    )
    pose_ref = PoseReference(
        artifact_id="synth-pose-1",
        kind=PoseKind.VINA_MODE,
        ordinal=1,
        label="Mode 1",
        result_kcal_mol=-7.2,
        value_label="Vina affinity (kcal/mol)",
        sha256=lig_sha,
        content_url="/docking/vina/batches/b/ligands/l/poses/synth-pose-1/content",
    )
    provenance = ProvenanceEvent(
        event_id="evt-synth-m6a",
        event_type="synthetic_m6a_fixture",
        timestamp=now,
        input_artifacts=[receptor_id],
        output_artifacts=["synth-out"],
        tool=ToolIdentity(name="ankora-test", version="0.2.0"),
    )

    # M3 PoseQualityRecord
    q_store = PoseQualityStore(root=root)
    assessment_id = q_store.new_assessment_id()
    q_store.create(
        PoseQualityRecord(
            assessment_id=assessment_id,
            created_at=now,
            catalog_id=catalog_id,
            engine_key="vina_batch",
            record_id=catalog_id.split(":", 1)[1],
            engine_label="AutoDock Vina 1.2.7",
            ligand_id="synth-lig-1",
            ligand_preparation_id="synth-prep-1",
            conformer_id="synth-conf-1",
            conformer_sha256="3" * 64,
            parent_state_id="synth-state-1",
            receptor_id=receptor_id,
            docking_receptor_artifact_id="rec-pdbqt",
            docking_receptor_sha256=rec_sha,
            analysis_receptor_artifact_id="rec-prot",
            analysis_receptor_sha256="4" * 64,
            pose=pose_ref,
            posebusters_version="0.6.5",
            assessment=PoseAssessment(
                pose_complex=pose_complex,
                overall_status=DiagnosticStatus.PASS,
                checks=(
                    PoseDiagnosticCheck(
                        check_id="posebusters:mol_pred_loaded",
                        tool_name="PoseBusters",
                        tool_version="0.6.5",
                        status=DiagnosticStatus.PASS,
                        value=1.0,
                        threshold=1.0,
                    ),
                ),
                strain=ConformationalStrainDiagnostic(
                    parent_state_id="synth-state-1",
                    hydrogen_policy="explicit_h",
                    conformer_seed=42,
                    conformer_budget=25,
                    pose_restrained_energy_kcal_mol=14.2,
                    lowest_free_conformer_energy_kcal_mol=12.0,
                    delta_e_ref_kcal_mol=2.2,
                ),
            ),
            passed_count=1,
            failed_count=0,
            not_applicable_count=0,
            not_evaluable_count=0,
            provenance=provenance,
        )
    )

    # M4 InteractionRuleSetRecord + InteractionRuleEvaluationRecord
    rs_store = InteractionRuleSetStore(root=root)
    eval_store = InteractionRuleEvaluationStore(root=root)
    rule_set_id = rs_store.new_rule_set_id()
    eval_id = eval_store.new_evaluation_id()
    residue = ResidueLocator(chain_id="A", residue_name="ASP", sequence_number=42)
    target = InteractionTarget(
        residue=residue, interaction_types=("HBDonor",), max_distance_angstrom=3.5
    )
    clause = InteractionRuleClause(
        clause_id="c-hbond",
        label="Synthetic hinge H-bond",
        kind=InteractionRuleKind.REQUIRED,
        targets=(target,),
    )
    profile = InteractionProfile(
        profile_id="ankora-default-v1",
        interactions=["HBDonor", "HBAcceptor", "Hydrophobic"],
    )
    bit = IfpBit(residue=residue, interaction_type="HBDonor")
    rule_set_hash = compute_rule_set_identity_sha256(
        receptor_protonated_sha256="4" * 64,
        profile=profile,
        clauses=(clause,),
        reference_fingerprint_sha256=None,
        min_tanimoto_similarity=None,
    )
    pose_ifp = InteractionFingerprint(
        profile=profile,
        bits=(bit,),
        counts=(IfpCountEntry(bit=bit, count=1),),
        source_kind=IfpSourceKind.POSE_ANALYSIS,
        fingerprint_sha256=compute_ifp_sha256(profile=profile, bits=(bit,)),
    )
    rs_store.create(
        InteractionRuleSetRecord(
            rule_set_id=rule_set_id,
            created_at=now,
            name="Synthetic Hinge Rules",
            description="Labelled synthetic test rule set.",
            receptor_id=receptor_id,
            receptor_protonated_artifact_id="rec-prot",
            receptor_protonated_sha256="4" * 64,
            profile=profile,
            clauses=(clause,),
            rule_set_identity_sha256=rule_set_hash,
            provenance=provenance,
        )
    )
    eval_store.create(
        InteractionRuleEvaluationRecord(
            evaluation_id=eval_id,
            created_at=now,
            rule_set_id=rule_set_id,
            rule_set_name="Synthetic Hinge Rules",
            rule_set_identity_sha256=rule_set_hash,
            catalog_id=catalog_id,
            engine_key="vina_batch",
            record_id=catalog_id.split(":", 1)[1],
            engine_label="AutoDock Vina 1.2.7",
            ligand_id="synth-lig-1",
            ligand_preparation_id="synth-prep-1",
            conformer_id="synth-conf-1",
            conformer_sha256="3" * 64,
            receptor_id=receptor_id,
            docking_receptor_artifact_id="rec-pdbqt",
            docking_receptor_sha256=rec_sha,
            analysis_receptor_artifact_id="rec-prot",
            analysis_receptor_sha256="4" * 64,
            pose=pose_ref,
            pose_complex=pose_complex,
            detector=ToolIdentity(name="ProLIF", version="2.2.1"),
            profile=profile,
            pose_ifp=pose_ifp,
            contacts=[],
            overall_status=DiagnosticStatus.PASS,
            clause_results=(
                ClauseEvaluationResult(
                    clause_id="c-hbond",
                    label="Synthetic hinge H-bond",
                    kind=InteractionRuleKind.REQUIRED,
                    status=DiagnosticStatus.PASS,
                    satisfied_target_count=1,
                    required_target_count=1,
                    matched_contact_ids=("contact-1",),
                    target_results=(
                        TargetEvaluationResult(
                            target=target,
                            matched=True,
                            matched_contact_ids=("contact-1",),
                            shortest_distance_angstrom=2.82,
                        ),
                    ),
                    explanation="Matched synthetic H-bond.",
                ),
            ),
            passed_clause_count=1,
            failed_clause_count=0,
            provenance=provenance,
        )
    )
    return {
        "assessment_id": assessment_id,
        "rule_set_id": rule_set_id,
        "evaluation_id": eval_id,
    }


def _run_verifier_cli(
    target: Path, *, require_format: int | None = None
) -> subprocess.CompletedProcess[str]:
    # Run with -S to prove zero dependency on site-packages or ankora_backend!
    cmd = [sys.executable, "-S", str(VERIFIER_SCRIPT), str(target), "--json"]
    if require_format is not None:
        cmd.extend(["--require-format", str(require_format)])
    return subprocess.run(cmd, capture_output=True, text=True, check=False)


def test_consensus_export_v5_api_catalog_stdlib_verifier_and_tamper_detection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Exports pcq-neural-v1 + PC-L2 + M3/M4 evidence as Export v5 and verifies via python -S."""
    monkeypatch.setenv("ANKORA_DATA_DIR", str(tmp_path))
    app = create_app()

    # Seed M2 Calibration run over 8 synthetic scaffolds
    cores = (
        "c1ccccc1",
        "c1ccc2ccccc2c1",
        "c1ccncc1",
        "C1CCCCC1",
        "c1ccsc1",
        "C1CCNCC1",
        "c1ccc(-c2ccccc2)cc1",
        "c1cnc2ccccc2c1",
    )
    compounds = [
        CalibrationCompoundInput(
            parent_id=f"synth_f{fi}_m{mi}",
            canonical_smiles=f"{core}{'C' * (mi + 1)}",
            is_active=(mi < 3),
        )
        for fi, core in enumerate(cores)
        for mi in range(8)
    ]
    cal_svc = ProtocolCalibrationService(store=CalibrationArtifactStore.from_environment())
    cal_run = cal_svc.create_split(
        project_id="default",
        receptor_id="rec-m6a",
        binding_site_id="site-m6a",
        compounds=compounds,
        policy=CalibrationSplitPolicy(bootstrap_replicates=120, min_confirmation_actives=6),
    )

    # Seed M3 + M4 evidence attached to a synthetic source campaign
    source_catalog = "vina_batch:synth-batch-m6a"
    _seed_v02_pose_evidence(tmp_path, catalog_id=source_catalog, receptor_id="rec-m6a")

    rec_sha = "1" * 64
    box_sha = "2" * 64
    map_sha = "3" * 64
    parents_payload: list[dict[str, Any]] = []
    for comp in cal_run.split.compounds:
        base_score = -9.6 if comp.is_active else -6.4
        parents_payload.append(
            {
                "parent_compound_id": comp.parent_id,
                "parent_state_id": f"{comp.parent_id}-s1",
                "rotatable_bond_count": 3,
                "medoids": [
                    {
                        "cluster_id": f"cl-{comp.parent_id}",
                        "medoid_pose_id": f"p-{comp.parent_id}",
                        "pose_complex": {
                            "mode": "rigid",
                            "receptor_rigid_sha256": rec_sha,
                            "ligand_pose_sha256": _sha(comp.parent_id.encode()),
                        },
                        "canonical_coordinate_sha256": _sha(f"coord-{comp.parent_id}".encode()),
                        "search_engines_present": ["vina", "autodock4", "gnina"],
                        "scores_by_function": {
                            "vina": base_score,
                            "autodock4": base_score,
                            "gnina_cnn_vs": 7.6 if comp.is_active else 2.4,
                        },
                    }
                ],
            }
        )
    # Add an explicit Tier 2 partial_or_unscored parent (ADR-030 E6)
    parents_payload.append(
        {
            "parent_compound_id": "synth_partial_unscored",
            "parent_state_id": "synth_partial_unscored-s1",
            "rotatable_bond_count": 5,
            "medoids": [],
            "failure_or_exclusion_codes": ["AUTODOCK4_ATOM_TYPE_UNSUPPORTED"],
        }
    )

    with TestClient(app) as client:
        cons_resp = client.post(
            "/api/v1/consensus/runs/structured",
            json={
                "name": "Synthetic M6a Neural Consensus",
                "variant_id": "pcq-neural-v1",
                "receptor_id": "rec-m6a",
                "binding_site_id": "site-m6a",
                "receptor_flex_spec": {"mode": "rigid", "receptor_rigid_sha256": rec_sha},
                "binding_box_sha256": box_sha,
                "autogrid_map_set_sha256": map_sha,
                "enabled_functions": ["vina", "autodock4", "gnina_cnn_vs"],
                "k_max": 1,
                "search_engine_count": 3,
                "parents": parents_payload,
            },
        )
        assert cons_resp.status_code == 201, cons_resp.text
        base_rec = ConsensusRunRecord.model_validate(cons_resp.json())

        # Fit gated PC-L2 derivative so calibration evidence is linked too
        pcl2_resp = client.post(
            f"/api/v1/consensus/runs/{base_rec.consensus_id}/pc-l2",
            json={"calibration_id": cal_run.calibration_id, "l2_regularization": 0.5},
        )
        assert pcl2_resp.status_code == 201, pcl2_resp.text
        pcl2_rec = ConsensusRunRecord.model_validate(pcl2_resp.json())

        # Export v5 via REST API
        export_resp = client.post(
            f"/api/v1/consensus/runs/{pcl2_rec.consensus_id}/export",
            params={"display_name": "M6a Verified Consensus Bundle"},
        )
        assert export_resp.status_code == 201, export_resp.text
        exported = export_resp.json()
        assert exported["ankora_export_format"] == 5
        assert exported["full_profile_count"] == 64
        assert exported["partial_or_unscored_count"] == 1
        assert exported["row_count"] == 65

        export_dir = Path(exported["record_directory"])
        zip_path = export_dir / exported["archive_filename"]
        assert zip_path.is_file()
        assert "10.1038/s41598-019-41594-3" in (export_dir / "methods.md").read_text("utf-8")

        # ExportCatalogService lists it under kind=consensus with format=5
        cat_resp = client.get("/api/v1/exports", params={"kind": "consensus"})
        assert cat_resp.status_code == 200
        cat_entries = cat_resp.json()["entries"]
        assert len(cat_entries) == 1
        assert cat_entries[0]["kind"] == ExportKind.CONSENSUS.value
        assert cat_entries[0]["ankora_export_format"] == 5
        assert cat_entries[0]["export_id"] == exported["export_id"]

        # Download ZIP through /api/v1/exports/{export_id}/{filename}
        dl_resp = client.get(
            f"/api/v1/exports/{exported['export_id']}/{exported['archive_filename']}"
        )
        assert dl_resp.status_code == 200
        assert dl_resp.content == zip_path.read_bytes()

    # Verify BOTH directory and standalone ZIP with `python -S` zero-dependency verifier!
    dir_check = _run_verifier_cli(export_dir, require_format=5)
    assert dir_check.returncode == 0, dir_check.stdout + dir_check.stderr
    dir_report = json.loads(dir_check.stdout)
    assert dir_report["verified"] is True
    assert dir_report["ankora_export_format"] == 5
    assert dir_report["row_kind"] == "consensus_parent"
    assert dir_report["row_count"] == 65
    assert dir_report["embedded_zip_verified"] is True
    # consensus record + reference panel + calibration record + split.json = at least 4 v0.2 files
    assert dir_report["v02_verified_evidence_files"] >= 4

    zip_check = _run_verifier_cli(zip_path, require_format=5)
    assert zip_check.returncode == 0, zip_check.stdout + zip_check.stderr
    assert json.loads(zip_check.stdout)["verified"] is True

    # Fail-closed tamper test 1: corrupting one byte of reference panel fails verification
    tampered_dir = tmp_path / "tampered_panel"
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(tampered_dir)
    panel_files = list((tampered_dir / "evidence" / "consensus_panels").glob("*/record.json"))
    assert len(panel_files) == 1
    panel_files[0].write_bytes(panel_files[0].read_bytes() + b" ")
    bad_panel = _run_verifier_cli(tampered_dir, require_format=5)
    assert bad_panel.returncode == 1
    assert "mismatch" in json.loads(bad_panel.stdout)["error"].lower()

    # Fail-closed tamper test 2: imputing a score into a Tier 2 partial_or_unscored row fails E6
    tampered_e6 = tmp_path / "tampered_e6"
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(tampered_e6)
    csv_path = tampered_e6 / "results.csv"
    csv_text = csv_path.read_text("utf-8")
    csv_path.write_text(
        csv_text.replace(
            "partial_or_unscored,,synth_partial_unscored,synth_partial_unscored-s1,,",
            "partial_or_unscored,65,synth_partial_unscored,synth_partial_unscored-s1,12.5,",
        ),
        encoding="utf-8",
    )
    bad_e6 = _run_verifier_cli(tampered_e6, require_format=5)
    assert bad_e6.returncode == 1
    assert "e6 violation" in json.loads(bad_e6.stdout)["error"].lower()


def test_campaign_export_preserves_v4_for_legacy_and_upgrades_to_v5_with_v02_evidence(
    tmp_path: Path,
) -> None:
    """Pure v0.1 rigid campaigns stay format v4; campaigns with M3/M4 records emit verified v5."""
    now = datetime(2026, 11, 20, 12, 30, tzinfo=UTC)
    campaign = ExportedCampaign(
        engine="AutoDock Vina",
        engine_version="1.2.7",
        backend="vina",
        value_column="vina_affinity_kcal_mol",
        reproducibility=ReproducibilityAssessment(),
        receptor_id="rec-compat",
        receptor_sha256="1" * 64,
        binding_site_id="site-compat",
        box={
            "center_x": 0.0,
            "center_y": 0.0,
            "center_z": 0.0,
            "size_x": 18.0,
            "size_y": 18.0,
            "size_z": 18.0,
        },
        map_set_id=None,
        map_set_identity_key=None,
        parameters={"exhaustiveness": 8},
        executable_sha256="7" * 64,
        device_name=None,
        rows=[
            {
                "rank": 1,
                "molecule": "Synth-Lig-1",
                "source_index": 0,
                "ligand_id": "synth-lig-1",
                "canonical_smiles": "CCO",
                "molecular_weight_g_mol": "46.069",
                "status": "completed",
                "failure_code": "",
                "failure_message": "",
                "vina_affinity_kcal_mol": "-7.200",
            }
        ],
        selection_manifest_sha256="8" * 64,
        library_id="lib-compat",
        filter_run_id="flt-compat",
        selected_count=1,
        succeeded_count=1,
        failed_count=0,
    )

    # 1. Pure v0.1 rigid campaign without M3/M4 records -> format v4
    v4_dir = tmp_path / "export_v4"
    v4_dir.mkdir()
    v4_id = _bundle_identity(
        campaign=campaign,
        export_id="00000000-0000-0000-0000-000000000004",
        source_kind="vina_batch",
        source_id="batch-v4",
        exported_at=now,
        display_name="Legacy v4 Bundle",
    )
    v4_ev = collect_recorded_evidence(
        root=tmp_path / "data_v4", catalog_id="vina_batch:batch-v4", export_directory=v4_dir
    )
    (v4_dir / "results.csv").write_text(results_csv(campaign), encoding="utf-8")
    (v4_dir / "manifest.json").write_text(
        manifest(
            campaign,
            exported_at=now,
            evidence=v4_ev,
            source_kind="vina_batch",
            source_id="batch-v4",
            bundle_identity=v4_id,
        ),
        encoding="utf-8",
    )
    (v4_dir / "README.txt").write_text(
        readme(campaign, evidence=v4_ev, exported_at=now, bundle_identity=v4_id),
        encoding="utf-8",
    )
    _write_portable_bundle(v4_dir, v4_id.archive_filename)
    v4_check = _run_verifier_cli(v4_dir, require_format=4)
    assert v4_check.returncode == 0, v4_check.stdout + v4_check.stderr
    assert json.loads(v4_check.stdout)["ankora_export_format"] == 4

    # 2. Same campaign with M3 PoseQuality + M4 InteractionRuleSet/Evaluation -> auto-upgrades to v5
    data_v5 = tmp_path / "data_v5"
    _seed_v02_pose_evidence(data_v5, catalog_id="vina_batch:batch-v5", receptor_id="rec-compat")
    v5_dir = tmp_path / "export_v5"
    v5_dir.mkdir()
    v5_id = _bundle_identity(
        campaign=campaign,
        export_id="00000000-0000-0000-0000-000000000005",
        source_kind="vina_batch",
        source_id="batch-v5",
        exported_at=now,
        display_name="Upgraded v5 Bundle",
    )
    v5_ev = collect_recorded_evidence(
        root=data_v5, catalog_id="vina_batch:batch-v5", export_directory=v5_dir
    )
    assert v5_ev.has_v02_evidence is True
    (v5_dir / "results.csv").write_text(results_csv(campaign), encoding="utf-8")
    (v5_dir / "manifest.json").write_text(
        manifest(
            campaign,
            exported_at=now,
            evidence=v5_ev,
            source_kind="vina_batch",
            source_id="batch-v5",
            bundle_identity=v5_id,
        ),
        encoding="utf-8",
    )
    (v5_dir / "README.txt").write_text(
        readme(campaign, evidence=v5_ev, exported_at=now, bundle_identity=v5_id),
        encoding="utf-8",
    )
    _write_portable_bundle(v5_dir, v5_id.archive_filename)
    v5_check = _run_verifier_cli(v5_dir, require_format=5)
    assert v5_check.returncode == 0, v5_check.stdout + v5_check.stderr
    v5_report = json.loads(v5_check.stdout)
    assert v5_report["ankora_export_format"] == 5
    assert v5_report["v02_verified_evidence_files"] == 3  # pose_quality + rule_eval + rule_set
    assert v5_report["embedded_zip_verified"] is True

    # Catalog projects ExportEntry with ankora_export_format cleanly
    catalog = ExportCatalogService(root=data_v5)
    assert catalog.list_exports().total == 0
