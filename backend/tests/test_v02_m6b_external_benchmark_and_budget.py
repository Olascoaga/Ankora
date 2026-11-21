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
