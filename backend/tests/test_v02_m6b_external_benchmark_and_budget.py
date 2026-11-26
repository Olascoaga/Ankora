"""Tests for M6b ADR-031 installer-size budget guard and external comparison benchmark harness.

All compound scores, platforms, and installer byte fixtures in this module are explicitly
labelled synthetic.
"""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import io
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from fastapi.testclient import TestClient

from ankora_backend.api.app import create_app
from ankora_backend.schemas.consensus import ConsensusRunRecord

ROOT = Path(__file__).resolve().parents[2]
BUDGET_SCRIPT = ROOT / "scripts" / "check_v02_installer_budget.py"
PROTOCOL_MOD_PATH = ROOT / "benchmarks" / "external_comparison" / "protocol_manifest.py"
EVAL_SCRIPT = ROOT / "benchmarks" / "external_comparison" / "evaluate_comparison.py"


def _load_module(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _sha_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _write_external_csv(path: Path, rows: list[dict[str, Any]]) -> str:
    fieldnames = [
        "parent_compound_id",
        "score",
        "status",
        "failure_code",
        "posebusters_pass",
    ]
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=fieldnames, lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    raw = buf.getvalue().encode("utf-8")
    path.write_bytes(raw)
    return _sha_bytes(raw)


def test_adr031_installer_budget_guard_passes_repo_and_fails_closed_on_violations(
    tmp_path: Path,
) -> None:
    """Verifies check_v02_installer_budget.py via python -S on real repo + synthetic violations."""
    # 1. Real repository must pass cleanly under isolated `python -S`
    proc = subprocess.run(
        [sys.executable, "-S", str(BUDGET_SCRIPT), "--json"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    report = json.loads(proc.stdout)
    assert report["passed"] is True
    assert report["cumulative_m0_m6_max_delta_bytes"] == 1_048_576
    assert report["m3_measured_wheel_bytes"] == 567_794
    assert report["separation"]["forbidden_hits"] == []
    assert report["separation"]["scanned_backend_python_files"] > 100

    # 2. Fail-closed unit test: over-budget installer artifact must raise BudgetGuardError
    guard = _load_module("ankora_budget_guard_test", BUDGET_SCRIPT)
    manifest_data = guard.load_budget_manifest(ROOT)
    # Construct a tiny synthetic manifest copy with small baseline to test exact byte cap cheaply
    synth_manifest = json.loads(json.dumps(manifest_data))
    synth_manifest["published_release_baselines"]["linux_x86_64_deb"]["size_bytes"] = 1000
    synth_manifest["milestone_budgets_bytes"]["M3"]["max_delta_bytes"] = 500

    within_file = tmp_path / "synth_ok.deb"
    within_file.write_bytes(b"x" * 1500)
    ok_res = guard.check_packaged_artifact(
        artifact_key="linux_x86_64_deb",
        artifact_path=within_file,
        manifest_data=synth_manifest,
    )
    assert ok_res["within_budget"] is True
    assert ok_res["delta_bytes"] == 500

    over_file = tmp_path / "synth_over.deb"
    over_file.write_bytes(b"x" * 1501)
    with pytest.raises(guard.BudgetGuardError, match="EXCEEDED"):
        guard.check_packaged_artifact(
            artifact_key="linux_x86_64_deb",
            artifact_path=over_file,
            manifest_data=synth_manifest,
        )

    # 3. Fail-closed unit test: forbidden external harness dependency in lockfile raises error
    fake_repo = tmp_path / "fake_repo"
    (fake_repo / "backend" / "src" / "ankora_backend").mkdir(parents=True)
    (fake_repo / "requirements").mkdir(parents=True)
    (fake_repo / "backend" / "pyproject.toml").write_text(
        '[project]\nname = "ankora"\ndependencies = ["dockm8==1.0.0"]\n', encoding="utf-8"
    )
    for name in (
        "windows-py312.in",
        "windows-py312.lock",
        "linux-py312.in",
        "linux-py312.lock",
    ):
        (fake_repo / "requirements" / name).write_text("posebusters==0.6.5\n", encoding="utf-8")
    with pytest.raises(guard.BudgetGuardError, match="dockm8"):
        guard.audit_dependency_separation(fake_repo)


def test_external_comparison_harness_two_axis_verdicts_and_one_directional_export_v5(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Tests ADR-031 two-axis harness consuming real verified Export v5 bundles under python -S."""
    monkeypatch.setenv("ANKORA_DATA_DIR", str(tmp_path / "ankora_data"))
    app = create_app()

    # Build a 40-parent synthetic Confirmation cohort (12 actives + 28 inactives)
    actives = tuple(f"synth_act_{i:02d}" for i in range(12))
    inactives = tuple(f"synth_dec_{i:02d}" for i in range(28))
    all_parents = actives + inactives

    rec_sha = "1" * 64
    box_sha = "2" * 64
    map_sha = "3" * 64

    # Export two real Ankora Export v5 consensus bundles:
    # - Bundle A (controlled): strong active separation (Ankora beats noisy external)
    # - Bundle B (end_to_end): tied / modest scores (tests null & negative verdicts cleanly)
    def _export_consensus_bundle(
        client: TestClient, *, name: str, active_vina: float, inactive_vina: float
    ) -> Path:
        parents_payload = []
        for idx, pid in enumerate(all_parents):
            is_act = pid in actives
            score_v = (active_vina if is_act else inactive_vina) - (idx % 3) * 0.05
            parents_payload.append(
                {
                    "parent_compound_id": pid,
                    "parent_state_id": f"{pid}-s1",
                    "medoids": [
                        {
                            "cluster_id": f"cl-{pid}",
                            "medoid_pose_id": f"p-{pid}",
                            "pose_complex": {
                                "mode": "rigid",
                                "receptor_rigid_sha256": rec_sha,
                                "ligand_pose_sha256": _sha_bytes(f"{name}:{pid}".encode()),
                            },
                            "canonical_coordinate_sha256": _sha_bytes(
                                f"coord:{name}:{pid}".encode()
                            ),
                            "search_engines_present": ["vina", "autodock4"],
                            "scores_by_function": {
                                "vina": score_v,
                                "autodock4": score_v,
                            },
                        }
                    ],
                }
            )
        resp = client.post(
            "/api/v1/consensus/runs/structured",
            json={
                "name": name,
                "variant_id": "pcq-core-v1",
                "receptor_id": "rec-bench",
                "binding_site_id": "site-bench",
                "receptor_flex_spec": {"mode": "rigid", "receptor_rigid_sha256": rec_sha},
                "binding_box_sha256": box_sha,
                "autogrid_map_set_sha256": map_sha,
                "enabled_functions": ["vina", "autodock4"],
                "k_max": 1,
                "search_engine_count": 2,
                "parents": parents_payload,
            },
        )
        assert resp.status_code == 201, resp.text
        rec = ConsensusRunRecord.model_validate(resp.json())
        exp = client.post(f"/api/v1/consensus/runs/{rec.consensus_id}/export")
        assert exp.status_code == 201, exp.text
        exp_data = exp.json()
        return Path(exp_data["record_directory"]) / exp_data["archive_filename"]

    with TestClient(app) as client:
        ankora_ctrl_zip = _export_consensus_bundle(
            client, name="Synthetic Controlled Ankora", active_vina=-9.5, inactive_vina=-6.0
        )
        ankora_e2e_zip = _export_consensus_bundle(
            client, name="Synthetic E2E Ankora", active_vina=-7.2, inactive_vina=-7.1
        )

    # External controlled CSV: weak separation + 2 failed actives (Ankora should win cleanly)
    ext_ctrl_csv = tmp_path / "external_controlled.csv"
    ext_ctrl_sha = _write_external_csv(
        ext_ctrl_csv,
        [
            {
                "parent_compound_id": pid,
                "score": (
                    "" if idx < 2 else (50.0 + (idx % 7) if pid in actives else 52.0 + (idx % 7))
                ),
                "status": "failed" if idx < 2 else "scored",
                "failure_code": "EXT_PREP_FAIL" if idx < 2 else "",
                "posebusters_pass": "false" if pid in actives and idx < 6 else "true",
            }
            for idx, pid in enumerate(all_parents)
        ],
    )

    # External end-to-end CSV: strong separation (external wins -> proves honest negative verdict!)
    ext_e2e_csv = tmp_path / "external_e2e.csv"
    ext_e2e_sha = _write_external_csv(
        ext_e2e_csv,
        [
            {
                "parent_compound_id": pid,
                "score": 95.0 if pid in actives else 10.0,
                "status": "scored",
                "failure_code": "",
                "posebusters_pass": "true",
            }
            for pid in all_parents
        ],
    )

    proto_mod = _load_module("ankora_ext_protocol_test", PROTOCOL_MOD_PATH)

    # Fail-closed check: "latest" external version MUST be rejected per ADR-031 §1
    with pytest.raises(proto_mod.ProtocolManifestError, match="unpinned platform version"):
        proto_mod.PinnedPlatformIdentity(
            platform_name="DockM8",
            version="latest",
            artifact_digest="a" * 64,
            raw_output_sha256s={"controlled": ext_ctrl_sha},
        )

    manifest = proto_mod.ComparisonProtocolManifest(
        protocol_id="synth-ankora-v02-vs-dockm8-test",
        target_id="SYNTH_TARGET_01",
        preregistered_at="2026-11-20T18:00:00Z",
        ankora_platform=proto_mod.PinnedPlatformIdentity(
            platform_name="Ankora",
            version="0.2.0-dev",
            artifact_digest="a" * 64,
            raw_output_sha256s={},
        ),
        external_platform=proto_mod.PinnedPlatformIdentity(
            platform_name="DockM8-Synthetic",
            version="1.0.0-pinned",
            artifact_digest="b" * 64,
            raw_output_sha256s={"controlled": ext_ctrl_sha, "end_to_end": ext_e2e_sha},
        ),
        split=proto_mod.SplitMembershipSpec(
            split_identity_sha256="c" * 64,
            grouping_strategy="parent_and_murcko_scaffold",
            active_parent_ids=actives,
            inactive_parent_ids=inactives,
        ),
        bootstrap_replicates=300,
    )
    protocol_json = tmp_path / "protocol.json"
    protocol_json.write_text(json.dumps(manifest.to_dict(), indent=2), encoding="utf-8")

    # 1. Single-axis execution MUST exit non-zero (2) and mark INCOMPLETE_SINGLE_AXIS_NOT_ADMISSIBLE
    single_out = tmp_path / "single_axis_report.json"
    single_proc = subprocess.run(
        [
            sys.executable,
            "-S",
            str(EVAL_SCRIPT),
            "--protocol",
            str(protocol_json),
            "--ankora-controlled",
            str(ankora_ctrl_zip),
            "--external-controlled",
            str(ext_ctrl_csv),
            "--output-json",
            str(single_out),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert single_proc.returncode == 2
    single_report = json.loads(single_out.read_text("utf-8"))
    assert single_report["admissible_comparison"] is False
    assert single_report["admissibility_status"] == "INCOMPLETE_SINGLE_AXIS_NOT_ADMISSIBLE"

    # 2. Full two-axis execution under `python -S` succeeds and reports BOTH positive and negative!
    out_json = tmp_path / "two_axis_report.json"
    out_md = tmp_path / "two_axis_report.md"
    full_proc = subprocess.run(
        [
            sys.executable,
            "-S",
            str(EVAL_SCRIPT),
            "--protocol",
            str(protocol_json),
            "--ankora-controlled",
            str(ankora_ctrl_zip),
            "--external-controlled",
            str(ext_ctrl_csv),
            "--ankora-end-to-end",
            str(ankora_e2e_zip),
            "--external-end-to-end",
            str(ext_e2e_csv),
            "--output-json",
            str(out_json),
            "--output-markdown",
            str(out_md),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert full_proc.returncode == 0, full_proc.stdout + full_proc.stderr
    report = json.loads(out_json.read_text("utf-8"))
    assert report["admissible_comparison"] is True
    assert report["admissibility_status"] == "ADMISSIBLE_TWO_AXIS_COMPARISON"
    assert report["mandatory_publication_of_negative_and_null_results"] is True

    # Axis A controlled: Ankora preferred + PoseBusters stratification present
    ctrl = report["axes"]["controlled"]
    assert ctrl["primary_comparison"]["verdict"] == "ankora_preferred"
    assert ctrl["primary_comparison"]["ci_lower"] > 0.0
    assert ctrl["primary_comparison"]["external"]["failed_active_count"] == 2
    assert ctrl["posebusters_stratified_comparison"] is not None

    # Axis B end-to-end: External preferred (negative result published honestly!)
    e2e = report["axes"]["end_to_end"]
    assert e2e["primary_comparison"]["verdict"] == "external_preferred"
    assert e2e["primary_comparison"]["ci_upper"] < 0.0

    md_text = out_md.read_text("utf-8")
    assert "ADMISSIBLE_TWO_AXIS_COMPARISON" in md_text
    assert "External platform preferred" in md_text
    assert "PoseBusters Physical-Validity Stratified Enrichment" in md_text

    # 3. Null verdict check: identical rankings emit verbatim null phrase
    eval_mod = _load_module("ankora_ext_eval_test", EVAL_SCRIPT)
    ank_rec, _ = eval_mod.load_ankora_export_scores(
        ankora_ctrl_zip, score_column="pcq_score", higher_is_better=True
    )
    null_res = eval_mod.paired_parent_bootstrap_delta(
        parent_ids=all_parents,
        active_set=frozenset(actives),
        ankora_records=ank_rec,
        external_records=ank_rec,
        replicates=200,
    )
    assert null_res["verdict"] == "insufficient_evidence_to_prefer_over_baseline"
    assert null_res["verdict_text"] == "Insufficient evidence to prefer over baseline"


def test_external_evaluator_bedroc_matches_canonical_screening_benchmark_exactly() -> None:
    """Regression test: evaluate_comparison.py BEDROC_20 must match screening_benchmark._bedroc."""
    from ankora_backend.services.screening_benchmark import _bedroc as canonical_bedroc

    eval_mod = _load_module("ankora_ext_eval_bedroc_parity", EVAL_SCRIPT)
    pids = tuple(f"P{i:03d}" for i in range(300))
    actives = frozenset(pids[:53])

    # 1. Perfect ranking -> exact 1.0
    perfect_recs = {
        pid: eval_mod.ParentScoreRecord(
            parent_id=pid, scored=True, oriented_score=(1000.0 - idx)
        )
        for idx, pid in enumerate(pids)
    }
    perfect_m = eval_mod.compute_tie_aware_enrichment(
        parent_ids=pids, active_set=actives, records=perfect_recs, bedroc_alpha=20.0
    )
    assert abs(perfect_m["bedroc"] - 1.0) < 1e-12

    # 2. Worst ranking (all actives failed / dead last) -> exact 0.0
    worst_recs = {
        pid: (
            eval_mod.ParentScoreRecord(
                parent_id=pid, scored=False, oriented_score=None, failure_code="FAIL"
            )
            if pid in actives
            else eval_mod.ParentScoreRecord(parent_id=pid, scored=True, oriented_score=1.0)
        )
        for pid in pids
    }
    worst_m = eval_mod.compute_tie_aware_enrichment(
        parent_ids=pids, active_set=actives, records=worst_recs, bedroc_alpha=20.0
    )
    assert abs(worst_m["bedroc"] - 0.0) < 1e-12

    # 3. Mixed tied ranking with failed compounds -> matches canonical _bedroc to <= 1e-12
    mixed_recs: dict[str, Any] = {}
    for idx, pid in enumerate(pids):
        if idx % 29 == 0:
            mixed_recs[pid] = eval_mod.ParentScoreRecord(
                parent_id=pid, scored=False, oriented_score=None, failure_code="FAIL"
            )
        else:
            bucket = float((idx * 17) % 41)
            if pid in actives:
                bucket += 12.0
            mixed_recs[pid] = eval_mod.ParentScoreRecord(
                parent_id=pid, scored=True, oriented_score=bucket
            )
    mixed_m = eval_mod.compute_tie_aware_enrichment(
        parent_ids=pids, active_set=actives, records=mixed_recs, bedroc_alpha=20.0
    )
    groups_raw, _, _ = eval_mod._tie_aware_rank_groups(pids, mixed_recs)
    groups_tuple = [
        (len(g), sum(1 for pid in g if pid in actives)) for g in groups_raw
    ]
    ref_bedroc = canonical_bedroc(groups_tuple, len(pids), len(actives), 20.0)
    assert abs(mixed_m["bedroc"] - ref_bedroc) < 1e-12
    assert 0.2 < mixed_m["bedroc"] < 0.99


def test_audit_unit6_external_evaluator_oracles_pb_strictness_pr_auc_and_mutants(
    tmp_path: Path,
) -> None:
    """Analytical oracles & mutant killers for evaluate_comparison.py and protocol_manifest.py.

    Covers D4-004 (pose_complex_sha256 exact match & fail-closed PB=None), D2-005/D4-009
    (duplicate parents & NaN/inf rejection), D2-011 (PR-AUC parity with screening_benchmark),
    D2-020 (stratified fixed-class bootstrap + linear quantile interpolation), D4-014 (strict
    JSON booleans), and D2-017 (killing all surviving mutants).
    """
    import zipfile

    from ankora_backend.schemas.screening_benchmark import (
        ScoreDirection,
        ScreeningBenchmarkObservation,
    )
    from ankora_backend.services.screening_benchmark import evaluate_target

    eval_mod = _load_module("ankora_ext_eval_audit_u6", EVAL_SCRIPT)
    proto_mod = _load_module("ankora_ext_proto_audit_u6", PROTOCOL_MOD_PATH)

    # 1. D4-014: string "false" must NEVER coerce to True in ComparisonProtocolManifest.from_dict
    base_manifest = proto_mod.ComparisonProtocolManifest(
        protocol_id="audit-u6-proto",
        target_id="SYNTH_T",
        preregistered_at="2026-11-26T00:00:00Z",
        ankora_platform=proto_mod.PinnedPlatformIdentity(
            platform_name="Ankora",
            version="0.2.0-dev",
            artifact_digest="a" * 64,
            raw_output_sha256s={},
        ),
        external_platform=proto_mod.PinnedPlatformIdentity(
            platform_name="Ext",
            version="1.0.0",
            artifact_digest="b" * 64,
            raw_output_sha256s={},
        ),
        split=proto_mod.SplitMembershipSpec(
            split_identity_sha256="c" * 64,
            grouping_strategy="parent_and_murcko_scaffold",
            active_parent_ids=("A1", "A2"),
            inactive_parent_ids=("D1", "D2"),
        ),
        bootstrap_replicates=100,
    ).to_dict()
    bad_ank_bool = {**base_manifest, "ankora_higher_is_better": "false"}
    with pytest.raises(proto_mod.ProtocolManifestError, match="ankora_higher_is_better"):
        proto_mod.ComparisonProtocolManifest.from_dict(bad_ank_bool)
    bad_ext_bool = {**base_manifest, "external_higher_is_better": "false"}
    with pytest.raises(proto_mod.ProtocolManifestError, match="external_higher_is_better"):
        proto_mod.ComparisonProtocolManifest.from_dict(bad_ext_bool)

    # 2. D2-005 / D4-009 & M06 / M08: load_external_scores_csv validation & lower-is-better sign
    no_parent_csv = tmp_path / "no_parent.csv"
    no_parent_csv.write_text("ligand,score\nA1,-8.0\n", encoding="utf-8")
    with pytest.raises(eval_mod.ComparisonEvaluationError, match="parent_compound_id"):
        eval_mod.load_external_scores_csv(
            no_parent_csv, score_column="score", higher_is_better=True
        )

    dup_csv = tmp_path / "dup.csv"
    _write_external_csv(
        dup_csv,
        [
            {
                "parent_compound_id": "A1",
                "score": "-9.0",
                "status": "scored",
                "failure_code": "",
                "posebusters_pass": "true",
            },
            {
                "parent_compound_id": "A1",
                "score": "-7.0",
                "status": "scored",
                "failure_code": "",
                "posebusters_pass": "true",
            },
        ],
    )
    with pytest.raises(eval_mod.ComparisonEvaluationError, match="Duplicate"):
        eval_mod.load_external_scores_csv(dup_csv, score_column="score", higher_is_better=False)

    nan_csv = tmp_path / "nan.csv"
    _write_external_csv(
        nan_csv,
        [
            {
                "parent_compound_id": "A1",
                "score": "nan",
                "status": "scored",
                "failure_code": "",
                "posebusters_pass": "true",
            }
        ],
    )
    with pytest.raises(eval_mod.ComparisonEvaluationError, match="Non-finite"):
        eval_mod.load_external_scores_csv(nan_csv, score_column="score", higher_is_better=False)

    lower_csv = tmp_path / "lower.csv"
    _write_external_csv(
        lower_csv,
        [
            {
                "parent_compound_id": "A1",
                "score": "-9.5",
                "status": "scored",
                "failure_code": "",
                "posebusters_pass": "true",
            },
            {
                "parent_compound_id": "D1",
                "score": "-6.0",
                "status": "scored",
                "failure_code": "",
                "posebusters_pass": "false",
            },
        ],
    )
    lower_recs, _ = eval_mod.load_external_scores_csv(
        lower_csv, score_column="score", higher_is_better=False
    )
    assert lower_recs["A1"].oriented_score == pytest.approx(9.5, abs=1e-12)
    assert lower_recs["D1"].oriented_score == pytest.approx(6.0, abs=1e-12)

    # 3. D2-011, D4-004, M09, M13, M15: exact tie ROC-AUC, PR-AUC parity, and PB=None exclusion
    pids = ("A1", "A2", "D1", "D2", "D3", "D4")
    actives = frozenset({"A1", "A2"})
    # A1 & D1 tie at 10.0 (PB=True); A2 scored at 5.0 (PB=None -> MUST FAIL under require_pb!)
    # D2 scored at 5.0 (PB=True); D3 unscored; D4 missing from records dict.
    recs = {
        "A1": eval_mod.ParentScoreRecord("A1", True, 10.0, None, True),
        "A2": eval_mod.ParentScoreRecord("A2", True, 5.0, None, None),
        "D1": eval_mod.ParentScoreRecord("D1", True, 10.0, None, True),
        "D2": eval_mod.ParentScoreRecord("D2", True, 5.0, None, True),
        "D3": eval_mod.ParentScoreRecord("D3", False, None, "FAIL", None),
    }
    unfiltered = eval_mod.compute_tie_aware_enrichment(
        parent_ids=pids,
        active_set=actives,
        records=recs,
        bedroc_alpha=20.0,
        top_fraction=0.5,
        require_posebusters_pass=False,
    )
    # Analytical ROC-AUC:
    # Group 1 (10.0): 1A, 1D -> favorable = 1 * (3 + 0.5*1) = 3.5
    # Group 2 (5.0):  1A, 1D -> favorable = 1 * (2 + 0.5*1) = 2.5
    # Total pairs = 2 * 4 = 8 -> ROC-AUC = 6.0 / 8 = 0.75 (kills M13 and M15!)
    assert unfiltered["roc_auc"] == pytest.approx(0.75, abs=1e-12)
    # Parity with canonical screening_benchmark (BEDROC, ROC-AUC, PR-AUC, EF) (D2-011!)
    sb_obs = [
        ScreeningBenchmarkObservation(
            parent_id=pid,
            state_id=f"st-{pid}",
            is_active=pid in actives,
            score=recs[pid].oriented_score if pid in recs and recs[pid].scored else None,
            failure_code=None if pid in recs and recs[pid].scored else "FAIL",
        )
        for pid in pids
    ]
    sb_ref = evaluate_target(
        "parity-check",
        sb_obs,
        score_direction=ScoreDirection.HIGHER_IS_BETTER,
        top_fraction=0.5,
        bedroc_alpha=20.0,
    )
    assert unfiltered["bedroc"] == pytest.approx(sb_ref.bedroc, abs=1e-12)
    assert unfiltered["roc_auc"] == pytest.approx(sb_ref.roc_auc, abs=1e-12)
    assert unfiltered["pr_auc"] == pytest.approx(sb_ref.pr_auc, abs=1e-12)
    assert unfiltered["enrichment_factor"] == pytest.approx(sb_ref.enrichment_factor, abs=1e-12)

    # D4-004: under require_posebusters_pass=True, A2 (PB=None) MUST be demoted to failed!
    pb_strict = eval_mod.compute_tie_aware_enrichment(
        parent_ids=pids,
        active_set=actives,
        records=recs,
        bedroc_alpha=20.0,
        top_fraction=0.5,
        require_posebusters_pass=True,
    )
    assert pb_strict["scored_count"] == 3  # only A1, D1, D2
    assert pb_strict["scored_active_count"] == 1
    assert pb_strict["failed_active_count"] == 1  # A2 demoted!
    assert pb_strict["failed_count"] == 3  # A2, D3, D4
    assert pb_strict["roc_auc"] < unfiltered["roc_auc"]

    # Large alpha overflow safety in evaluate_comparison.py too (D2-022)
    large_a = eval_mod.compute_tie_aware_enrichment(
        parent_ids=pids, active_set=actives, records=recs, bedroc_alpha=800.0
    )
    assert 0.0 <= large_a["bedroc"] <= 1.0

    # 4. D2-020 & M18 / M21: stratified fixed-class bootstrap at 2% prevalence + exact point_delta
    low_prev_pids = tuple(f"P{i:03d}" for i in range(100))
    low_prev_actives = frozenset({"P000", "P001"})
    ank_low = {
        pid: eval_mod.ParentScoreRecord(
            pid,
            True,
            100.0 if pid == "P000" else (10.0 if pid == "P001" else 50.0 - idx * 0.1),
        )
        for idx, pid in enumerate(low_prev_pids)
    }
    ext_low = {
        pid: eval_mod.ParentScoreRecord(
            pid,
            True,
            100.0 if pid == "P001" else (10.0 if pid == "P000" else 50.0 - idx * 0.1),
        )
        for idx, pid in enumerate(low_prev_pids)
    }
    boot = eval_mod.paired_parent_bootstrap_delta(
        parent_ids=low_prev_pids,
        active_set=low_prev_actives,
        ankora_records=ank_low,
        external_records=ext_low,
        replicates=80,
        seed=42,
    )
    assert boot["valid_replicates"] == 80  # zero dropped replicates at 2% prevalence!
    assert boot["bootstrap_method"] == "stratified_fixed_class_paired_parent_bootstrap"
    assert boot["percentile_method"] == "linear_interpolated_n_minus_1"
    assert boot["ankora"]["bedroc"] > 0.2 and boot["external"]["bedroc"] > 0.2
    expected_delta = boot["ankora"]["bedroc"] - boot["external"]["bedroc"]
    assert boot["point_delta_bedroc"] == pytest.approx(expected_delta, abs=1e-12)
    assert 0.0 < boot["bootstrap_se"] < 1.0  # kills M21 (mean_delta = sum * len blows SE up!)
    # Single-replicate bootstrap must be accepted (kills replicates < 1 -> <= 1)
    boot_one = eval_mod.paired_parent_bootstrap_delta(
        parent_ids=low_prev_pids,
        active_set=low_prev_actives,
        ankora_records=ank_low,
        external_records=ext_low,
        replicates=1,
        seed=42,
    )
    assert boot_one["valid_replicates"] == 1
    # Permutation invariance of stratified bootstrap
    boot_rev = eval_mod.paired_parent_bootstrap_delta(
        parent_ids=tuple(reversed(low_prev_pids)),
        active_set=low_prev_actives,
        ankora_records=ank_low,
        external_records=ext_low,
        replicates=80,
        seed=42,
    )
    assert boot_rev["ci_lower"] == pytest.approx(boot["ci_lower"], abs=1e-12)
    assert boot_rev["ci_upper"] == pytest.approx(boot["ci_upper"], abs=1e-12)
    assert boot_rev["bootstrap_se"] == pytest.approx(boot["bootstrap_se"], abs=1e-12)

    # 5. D4-004 & M01 / M02 / M03 / M04: load_ankora_export_scores exact pose_complex_sha256 match
    # Build minimal verified Export v5 & Export v4 bundles with known SHA-256 manifests.
    def _make_verified_zip(
        path: Path,
        *,
        csv_text: str,
        row_kind: str,
        columns: list[str],
        counts: dict[str, int],
        pb_assessments: list[dict[str, Any]],
        export_format: int = 5,
    ) -> Path:
        csv_bytes = csv_text.encode("utf-8")
        exported_at = "2026-11-26T00:00:00+00:00"
        source_kind = "consensus_run" if row_kind == "consensus_parent" else "vina_batch"
        source_id = "synth-001"
        export_id = "exp-001"
        inputs_obj = {"synthetic": True, "row_kind": row_kind}
        input_sha = proto_mod.canonical_json_sha256(inputs_obj)
        bundle_sha = proto_mod.canonical_json_sha256(
            {
                "protocol": "ankora-campaign-bundle-identity-v1",
                "export_id": export_id,
                "exported_at": exported_at,
                "catalog_id": f"{source_kind}:{source_id}",
                "display_name": None,
                "input_identity_sha256": input_sha,
            }
        )
        pb_entries: list[dict[str, Any]] = []
        extra_blobs: dict[str, bytes] = {}
        for idx, item in enumerate(pb_assessments):
            rel = f"evidence/pose_quality/pq_{idx}/record.json"
            blob = json.dumps(item).encode("utf-8")
            extra_blobs[rel] = blob
            pb_entries.append(
                {
                    "assessment_id": f"pq_{idx}",
                    **item,
                    "path": rel,
                    "sha256": _sha_bytes(blob),
                    "size_bytes": len(blob),
                }
            )
        manifest_obj: dict[str, Any] = {
            "ankora_export_format": export_format,
            "exported_at": exported_at,
            "source_kind": source_kind,
            "source_id": source_id,
            "engine": {"name": "Ankora Synthetic", "version": "0.2.0-dev"},
            "reproducibility": {"status": "synthetic_fixture"},
            "inputs": inputs_obj,
            "protocol": {"synthetic": True},
            "counts": counts,
            "table": {"file": "results.csv", "row": row_kind, "columns": columns},
            "bundle": {
                "export_id": export_id,
                "catalog_id": f"{source_kind}:{source_id}",
                "display_name": None,
                "input_identity_sha256": input_sha,
                "bundle_identity_sha256": bundle_sha,
            },
            "scientific_notes": ["Labelled synthetic test fixture."],
            "recorded_evidence": {"pose_quality_assessments": pb_entries},
        }
        if export_format >= 5:
            manifest_obj["v02_provenance"] = {"pose_quality_assessment_count": len(pb_entries)}
        manifest_bytes = json.dumps(manifest_obj).encode("utf-8")
        with zipfile.ZipFile(path, "w") as zf:
            zf.writestr("README.txt", b"Labelled synthetic Ankora export fixture.\n")
            zf.writestr("results.csv", csv_bytes)
            zf.writestr("manifest.json", manifest_bytes)
            for rel, blob in extra_blobs.items():
                zf.writestr(rel, blob)
        return path

    pose_pass_sha = "1" * 64
    pose_other_sha = "2" * 64
    pose_mixed_sha = "3" * 64
    cons_csv = (
        "tier,rank,parent_compound_id,parent_state_id,pcq_score,"
        "selected_pose_complex_sha256,failure_or_exclusion_codes\n"
        f"full_profile,1,P1,P1-s1,80.0,{pose_pass_sha},\n"
        f"full_profile,2,P2,P2-s1,70.0,{pose_other_sha},\n"
        f"full_profile,3,P3,P3-s1,60.0,{pose_mixed_sha},\n"
    )
    cons_zip = _make_verified_zip(
        tmp_path / "cons_pb.zip",
        csv_text=cons_csv,
        row_kind="consensus_parent",
        columns=[
            "tier",
            "rank",
            "parent_compound_id",
            "parent_state_id",
            "pcq_score",
            "selected_pose_complex_sha256",
            "failure_or_exclusion_codes",
        ],
        counts={"total_parents": 3, "full_profile": 3, "partial_or_unscored": 0},
        pb_assessments=[
            # P1 exact selected pose passes
            {
                "ligand_id": "lig-1",
                "pose_complex_sha256": pose_pass_sha,
                "overall_status": "pass",
            },
            # P2 has a passing assessment ONLY for a DIFFERENT pose -> must NOT match P2!
            {
                "ligand_id": "P2",
                "pose_complex_sha256": "9" * 64,
                "overall_status": "pass",
            },
            # P3 has both pass and fail for same pose hash -> conservative AND yields False!
            {
                "ligand_id": "lig-3",
                "pose_complex_sha256": pose_mixed_sha,
                "overall_status": "pass",
            },
            {
                "ligand_id": "lig-3",
                "pose_complex_sha256": pose_mixed_sha,
                "overall_status": "fail",
            },
        ],
    )
    cons_recs, _ = eval_mod.load_ankora_export_scores(
        cons_zip, score_column="pcq_score", higher_is_better=False
    )
    assert cons_recs["P1"].posebusters_pass is True
    assert cons_recs["P2"].posebusters_pass is None  # no cross-pose leakage by ligand_id!
    assert cons_recs["P3"].posebusters_pass is False  # conservative AND, never permissive OR!
    assert cons_recs["P1"].oriented_score == pytest.approx(-80.0, abs=1e-12)  # kills M03!

    # Export v4 single-engine lower-is-better sign flip (kills M04!)
    v4_csv = (
        "rank,molecule,source_index,ligand_id,status,vina_affinity_kcal_mol,failure_code\n"
        "1,M1,0,L1,completed,-9.2,\n"
    )
    v4_zip = _make_verified_zip(
        tmp_path / "v4_lower.zip",
        csv_text=v4_csv,
        row_kind="molecule",
        columns=[
            "rank",
            "molecule",
            "source_index",
            "ligand_id",
            "status",
            "vina_affinity_kcal_mol",
            "failure_code",
        ],
        counts={"selected": 1, "succeeded": 1, "failed": 0},
        pb_assessments=[],
        export_format=4,
    )
    v4_recs, _ = eval_mod.load_ankora_export_scores(
        v4_zip, score_column="vina_affinity_kcal_mol", higher_is_better=False
    )
    assert v4_recs["L1"].oriented_score == pytest.approx(9.2, abs=1e-12)

    # 6. M22 & M23: evaluate_two_axis_comparison skips half-supplied axes cleanly
    proto_obj = proto_mod.ComparisonProtocolManifest.from_dict(base_manifest)
    half_ctrl = eval_mod.evaluate_two_axis_comparison(
        protocol=proto_obj,
        ankora_controlled=cons_zip,
        external_controlled=None,
        ankora_end_to_end=None,
        external_end_to_end=lower_csv,
    )
    assert half_ctrl["admissible_comparison"] is False
    assert half_ctrl["axes"] == {}
    assert half_ctrl["evaluator_version"] == eval_mod.EVALUATOR_VERSION
