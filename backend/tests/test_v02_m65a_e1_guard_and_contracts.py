"""Tests for M6.5a (ADR-033, 0-byte M6.5 budget, hardened E1 guard & small-panel warning).

All synthetic scores, executable hashes, and compound identifiers in this file are explicitly
labelled synthetic.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ankora_backend.adapters.consensus.pcq_math import (
    SMALL_PANEL_WARNING_THRESHOLD,
    build_reference_panel,
    compute_pcq_and_ecr_consensus,
)
from ankora_backend.api.app import create_app
from ankora_backend.schemas.consensus import (
    ConsensusParentInput,
    ConsensusPoseScoreInput,
    ConsensusRunRecord,
    ConsensusVariantId,
)
from ankora_backend.schemas.projects import DependencyNodeKind
from ankora_backend.schemas.receptors import ReceptorFlexMode, ReceptorFlexSpec
from ankora_backend.schemas.v02_contracts import PoseComplexIdentity, ScoringFunctionId
from ankora_backend.schemas.warnings import WarningCode

ROOT = Path(__file__).resolve().parents[2]
BUDGET_SCRIPT = ROOT / "scripts" / "check_v02_installer_budget.py"
ADR_033_PATH = (
    ROOT
    / "docs"
    / "architecture"
    / "ADR"
    / "ADR-033-hit-to-analog-expansion-and-pose-focused-screening.md"
)

_REC_SHA = "a" * 64
_BOX_SHA = "b" * 64
_MAP_SHA = "c" * 64


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _synthetic_parent_payload(pid: str, vina_score: float, ad4_score: float) -> dict[str, object]:
    return {
        "parent_compound_id": pid,
        "parent_state_id": f"{pid}-state-1",
        "medoids": [
            {
                "cluster_id": f"cl-{pid}",
                "medoid_pose_id": f"pose-{pid}",
                "pose_complex": {
                    "mode": "rigid",
                    "receptor_rigid_sha256": _REC_SHA,
                    "ligand_pose_sha256": _sha(f"lig:{pid}"),
                },
                "canonical_coordinate_sha256": _sha(f"coord:{pid}"),
                "search_engines_present": ["vina", "autodock4"],
                "scores_by_function": {
                    "vina": vina_score,
                    "autodock4": ad4_score,
                },
            }
        ],
    }


def _synthetic_parent_input(pid: str, vina_score: float, ad4_score: float) -> ConsensusParentInput:
    return ConsensusParentInput(
        parent_compound_id=pid,
        parent_state_id=f"{pid}-state-1",
        medoids=(
            ConsensusPoseScoreInput(
                cluster_id=f"cl-{pid}",
                medoid_pose_id=f"pose-{pid}",
                pose_complex=PoseComplexIdentity(
                    mode=ReceptorFlexMode.RIGID,
                    receptor_rigid_sha256=_REC_SHA,
                    ligand_pose_sha256=_sha(f"lig:{pid}"),
                ),
                canonical_coordinate_sha256=_sha(f"coord:{pid}"),
                search_engines_present=("vina", "autodock4"),
                scores_by_function={
                    ScoringFunctionId.VINA: vina_score,
                    ScoringFunctionId.AUTODOCK4: ad4_score,
                },
            ),
        ),
    )


def test_adr033_exists_and_m65_zero_byte_budget_passes_under_python_s() -> None:
    """ADR-033 is tracked and ADR-031 CI guard enforces M6.5 = 0 new dependency bytes."""
    assert ADR_033_PATH.is_file()
    adr_text = ADR_033_PATH.read_text(encoding="utf-8")
    assert "BindingSiteSource.POSE_FOCUSED" in adr_text
    assert "consent_payload_sha256" in adr_text

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

    # New stable M6.5 contracts exist
    assert WarningCode.CONSENSUS_SMALL_OR_CONGENERIC_PANEL.value == (
        "CONSENSUS_SMALL_OR_CONGENERIC_PANEL"
    )
    assert WarningCode.ANALOG_MCS_TIMEOUT.value == "ANALOG_MCS_TIMEOUT"
    assert DependencyNodeKind.ANALOG_CATALOG.value == "analog_catalog"
    assert DependencyNodeKind.ANALOG_SEARCH.value == "analog_search"
    assert DependencyNodeKind.ANALOG_SELECTION.value == "analog_selection"


def test_hardened_e1_guard_rejects_k_max_and_executable_hash_drift_and_freezes_panel(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-033 §2.1-2.2: reused panel fails closed on k_max/binary drift and stays frozen."""
    monkeypatch.setenv("ANKORA_DATA_DIR", str(tmp_path / "ankora_data"))
    app = create_app()
    exec_hashes = {"vina": _sha("vina-1.2.7-bin"), "autodock4": _sha("ad4-4.2.6-bin")}

    with TestClient(app) as client:
        # 1. Create parent campaign consensus with locked panel (4 synthetic panel parents)
        base_resp = client.post(
            "/api/v1/consensus/runs/structured",
            json={
                "name": "Synthetic Parent Panel",
                "variant_id": "pcq-core-v1",
                "receptor_id": "rec-synth-1",
                "binding_site_id": "site-synth-1",
                "receptor_flex_spec": {
                    "mode": "rigid",
                    "receptor_rigid_sha256": _REC_SHA,
                },
                "binding_box_sha256": _BOX_SHA,
                "autogrid_map_set_sha256": _MAP_SHA,
                "enabled_functions": ["vina", "autodock4"],
                "k_max": 3,
                "search_engine_count": 2,
                "parents": [
                    _synthetic_parent_payload("synth_parent_1", -9.0, -8.5),
                    _synthetic_parent_payload("synth_parent_2", -8.0, -7.5),
                    _synthetic_parent_payload("synth_parent_3", -7.0, -6.5),
                    _synthetic_parent_payload("synth_parent_4", -6.0, -5.5),
                ],
                "executable_sha256s": exec_hashes,
            },
        )
        assert base_resp.status_code == 201, base_resp.text
        base_run = ConsensusRunRecord.model_validate(base_resp.json())
        panel_id = base_run.reference_panel.panel_id
        panel_sha = base_run.reference_panel.reference_panel_sha256

        # 2. Mismatched k_max MUST fail closed with 422 CONSENSUS_SHARED_CONTEXT_MISMATCH
        bad_kmax = client.post(
            "/api/v1/consensus/runs/structured",
            json={
                "name": "Synthetic Analog Bad k_max",
                "variant_id": "pcq-core-v1",
                "receptor_id": "rec-synth-1",
                "binding_site_id": "site-synth-1",
                "receptor_flex_spec": {
                    "mode": "rigid",
                    "receptor_rigid_sha256": _REC_SHA,
                },
                "binding_box_sha256": _BOX_SHA,
                "autogrid_map_set_sha256": _MAP_SHA,
                "enabled_functions": ["vina", "autodock4"],
                "k_max": 5,
                "search_engine_count": 2,
                "reference_panel_id": panel_id,
                "parents": [_synthetic_parent_payload("synth_analog_1", -9.5, -9.0)],
                "executable_sha256s": exec_hashes,
            },
        )
        assert bad_kmax.status_code == 422
        assert bad_kmax.json()["code"] == "CONSENSUS_SHARED_CONTEXT_MISMATCH"

        # 3. Drifted executable_sha256s MUST fail closed
        bad_exec = client.post(
            "/api/v1/consensus/runs/structured",
            json={
                "name": "Synthetic Analog Bad Binary Hash",
                "variant_id": "pcq-core-v1",
                "receptor_id": "rec-synth-1",
                "binding_site_id": "site-synth-1",
                "receptor_flex_spec": {
                    "mode": "rigid",
                    "receptor_rigid_sha256": _REC_SHA,
                },
                "binding_box_sha256": _BOX_SHA,
                "autogrid_map_set_sha256": _MAP_SHA,
                "enabled_functions": ["vina", "autodock4"],
                "k_max": 3,
                "search_engine_count": 2,
                "reference_panel_id": panel_id,
                "parents": [_synthetic_parent_payload("synth_analog_1", -9.5, -9.0)],
                "executable_sha256s": {
                    "vina": _sha("vina-1.2.8-different-bin"),
                    "autodock4": exec_hashes["autodock4"],
                },
            },
        )
        assert bad_exec.status_code == 422
        assert bad_exec.json()["code"] == "CONSENSUS_SHARED_CONTEXT_MISMATCH"

        # 4. Omitted executable_sha256s against a hashed panel MUST fail closed
        missing_exec = client.post(
            "/api/v1/consensus/runs/structured",
            json={
                "name": "Synthetic Analog Missing Binary Hash",
                "variant_id": "pcq-core-v1",
                "receptor_id": "rec-synth-1",
                "binding_site_id": "site-synth-1",
                "receptor_flex_spec": {
                    "mode": "rigid",
                    "receptor_rigid_sha256": _REC_SHA,
                },
                "binding_box_sha256": _BOX_SHA,
                "autogrid_map_set_sha256": _MAP_SHA,
                "enabled_functions": ["vina", "autodock4"],
                "k_max": 3,
                "search_engine_count": 2,
                "reference_panel_id": panel_id,
                "parents": [_synthetic_parent_payload("synth_analog_1", -9.5, -9.0)],
                "executable_sha256s": {},
            },
        )
        assert missing_exec.status_code == 422
        assert missing_exec.json()["code"] == "CONSENSUS_SHARED_CONTEXT_MISMATCH"

        # 5. Matching context succeeds and evaluates DISJOINT analog targets strictly against
        #    the unchanged frozen ReferencePanelArtifact (ADR-033 §2.2 E1 separation)
        ok_analog = client.post(
            "/api/v1/consensus/runs/structured",
            json={
                "name": "Synthetic Analog Disjoint Targets",
                "variant_id": "pcq-core-v1",
                "receptor_id": "rec-synth-1",
                "binding_site_id": "site-synth-1",
                "receptor_flex_spec": {
                    "mode": "rigid",
                    "receptor_rigid_sha256": _REC_SHA,
                },
                "binding_box_sha256": _BOX_SHA,
                "autogrid_map_set_sha256": _MAP_SHA,
                "enabled_functions": ["vina", "autodock4"],
                "k_max": 3,
                "search_engine_count": 2,
                "reference_panel_id": panel_id,
                "parents": [
                    _synthetic_parent_payload("synth_analog_A", -10.0, -9.5),
                    _synthetic_parent_payload("synth_analog_B", -7.5, -7.0),
                ],
                "executable_sha256s": exec_hashes,
            },
        )
        assert ok_analog.status_code == 201, ok_analog.text
        analog_run = ConsensusRunRecord.model_validate(ok_analog.json())
        assert analog_run.reference_panel.reference_panel_sha256 == panel_sha
        assert analog_run.reference_panel.total_panel_parents == 4
        assert analog_run.ranking.total_parents == 2
        assert analog_run.provenance.parameters["frozen_panel_parent_count"] == 4
        assert analog_run.provenance.parameters["scored_target_parent_count"] == 2
        # New superior analog scores 100.0 against frozen panel without mutating panel entries
        panel_ids = {entry.parent_compound_id for entry in analog_run.reference_panel.entries}
        assert "synth_analog_A" not in panel_ids
        assert "synth_analog_B" not in panel_ids


def test_small_or_congeneric_panel_warning_emits_quantiles_and_saturation() -> None:
    """ADR-033 §2.3: warns when N_panel < 50 or monoscaffold, silent when >= 50 diverse."""
    rec_spec = ReceptorFlexSpec(mode=ReceptorFlexMode.RIGID, receptor_rigid_sha256=_REC_SHA)
    enabled = (ScoringFunctionId.VINA, ScoringFunctionId.AUTODOCK4)

    # Small synthetic panel (N = 5 < 50)
    small_parents = tuple(
        _synthetic_parent_input(f"synth_small_{i}", -5.0 - i, -5.0 - i) for i in range(5)
    )
    small_panel = build_reference_panel(
        receptor_id="rec-1",
        binding_site_id="site-1",
        receptor_flex_spec=rec_spec,
        binding_box_sha256=_BOX_SHA,
        autogrid_map_set_sha256=_MAP_SHA,
        enabled_functions=enabled,
        k_max=2,
        parents=small_parents,
    )
    small_out = compute_pcq_and_ecr_consensus(
        variant_id=ConsensusVariantId.PCQ_CORE_V1,
        enabled_functions=enabled,
        reference_panel=small_panel,
        parents=(_synthetic_parent_input("synth_analog_top", -12.0, -12.0),),
        search_engine_count=2,
    )
    small_warn = next(
        (
            w
            for w in small_out.warnings
            if w.code is WarningCode.CONSENSUS_SMALL_OR_CONGENERIC_PANEL
        ),
        None,
    )
    assert small_warn is not None
    assert small_warn.details["total_panel_parents"] == 5
    assert small_warn.details["quantile_step_resolution"] == pytest.approx(20.0)
    assert small_warn.details["upper_tail_saturation_fraction"] == pytest.approx(1.0)

    # Diverse large synthetic panel (N = 50, 20 scaffolds) -> NO small/congeneric warning
    large_parents = tuple(
        _synthetic_parent_input(f"synth_large_{i:02d}", -5.0 - i * 0.1, -5.0 - i * 0.1)
        for i in range(SMALL_PANEL_WARNING_THRESHOLD)
    )
    large_panel = build_reference_panel(
        receptor_id="rec-1",
        binding_site_id="site-1",
        receptor_flex_spec=rec_spec,
        binding_box_sha256=_BOX_SHA,
        autogrid_map_set_sha256=_MAP_SHA,
        enabled_functions=enabled,
        k_max=2,
        parents=large_parents,
    )
    large_diverse_out = compute_pcq_and_ecr_consensus(
        variant_id=ConsensusVariantId.PCQ_CORE_V1,
        enabled_functions=enabled,
        reference_panel=large_panel,
        parents=large_parents[:3],
        search_engine_count=2,
        panel_unique_scaffolds=20,
    )
    assert all(
        w.code is not WarningCode.CONSENSUS_SMALL_OR_CONGENERIC_PANEL
        for w in large_diverse_out.warnings
    )

    # Large but monoscaffold panel (N = 50, 1 scaffold) -> MUST still emit warning!
    large_mono_out = compute_pcq_and_ecr_consensus(
        variant_id=ConsensusVariantId.PCQ_CORE_V1,
        enabled_functions=enabled,
        reference_panel=large_panel,
        parents=large_parents[:3],
        search_engine_count=2,
        panel_unique_scaffolds=1,
    )
    mono_warn = next(
        (
            w
            for w in large_mono_out.warnings
            if w.code is WarningCode.CONSENSUS_SMALL_OR_CONGENERIC_PANEL
        ),
        None,
    )
    assert mono_warn is not None
    assert mono_warn.details["panel_unique_scaffolds"] == 1
