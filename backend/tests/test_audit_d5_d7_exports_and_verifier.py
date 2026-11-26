"""Regression tests for D5/D7 Unit 1: Export v5/v6 integrity, stale propagation,
consensus secondary rankings, canceled batch verification, and verifier hardening.

All molecules, scores, and identifiers in this module are explicitly labelled synthetic fixtures.
"""

from __future__ import annotations

import csv
import importlib.util
import io
import json
import subprocess
import sys
import zipfile
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from ankora_backend.domain.errors import AnkoraDomainError
from ankora_backend.persistence.calibration_store import CalibrationArtifactStore
from ankora_backend.persistence.consensus_store import ConsensusArtifactStore
from ankora_backend.schemas.consensus import (
    ConsensusParentInput,
    ConsensusPoseScoreInput,
    ConsensusVariantId,
    CreateStructuredConsensusRequest,
)
from ankora_backend.schemas.receptors import ReceptorFlexMode, ReceptorFlexSpec
from ankora_backend.schemas.results_catalog import (
    CatalogEntry,
    ReproducibilityAssessment,
    ScoringFamily,
)
from ankora_backend.schemas.v02_contracts import PoseComplexIdentity, ScoringFunctionId
from ankora_backend.services.campaign_export import (
    ExportedCampaign,
    _bundle_identity,
    _write_portable_bundle,
    manifest,
    readme,
    results_csv,
)
from ankora_backend.services.consensus_export import (
    ConsensusExportService,
    _consensus_readme,
    _resolve_source_library_ids,
    consensus_results_csv,
)
from ankora_backend.services.methods_report import MethodsReportService
from ankora_backend.services.pose_consensus import PoseConsensusService
from ankora_backend.services.project_dependencies import ArtifactFreshness

REPO_ROOT = Path(__file__).resolve().parents[2]
VERIFIER_SCRIPT = REPO_ROOT / "scripts" / "verify_export_bundle.py"
EVALUATOR_SCRIPT = REPO_ROOT / "benchmarks" / "external_comparison" / "evaluate_comparison.py"


def _load_module(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _missing(*_: Any) -> Any:
    raise AnkoraDomainError(code="NOT_FOUND", stage="test", message="missing", status_code=404)


def _sha(label: str) -> str:
    return sha256(label.encode("utf-8")).hexdigest()


def _make_synthetic_bundle(
    target_dir: Path,
    *,
    campaign: ExportedCampaign,
    include_bundle_files: bool = True,
    methods_text: str | None = "# Synthetic Methods\n",
) -> Path:
    target_dir.mkdir(parents=True, exist_ok=True)
    exported_at = datetime(2026, 11, 26, 18, 0, tzinfo=UTC)
    bundle_id = _bundle_identity(
        export_id="synth-exp-1",
        exported_at=exported_at,
        source_kind="vina_batch",
        source_id="synth-batch-1",
        campaign=campaign,
        display_name="Synthetic Audit Campaign",
    )
    core_files: dict[str, str] = {
        "results.csv": results_csv(campaign),
        "README.txt": readme(campaign, exported_at=exported_at, bundle_identity=bundle_id),
    }
    if methods_text is not None:
        core_files["methods.md"] = methods_text
    bundle_files_meta = (
        [
            {
                "path": name,
                "sha256": sha256(content.encode("utf-8")).hexdigest(),
                "size_bytes": len(content.encode("utf-8")),
            }
            for name, content in sorted(core_files.items())
        ]
        if include_bundle_files
        else None
    )
    all_files = {
        **core_files,
        "manifest.json": manifest(
            campaign,
            exported_at=exported_at,
            source_kind="vina_batch",
            source_id="synth-batch-1",
            bundle_identity=bundle_id,
            bundle_files=bundle_files_meta,
        ),
    }
    for name, content in all_files.items():
        (target_dir / name).write_text(content, encoding="utf-8", newline="\n")
    _write_portable_bundle(target_dir, bundle_id.archive_filename)
    return target_dir / bundle_id.archive_filename


def test_d7_001_consensus_preserves_pcq_core_score_on_gnina_failed_parent(tmp_path: Path) -> None:
    """D7-001: GNINA-failed parents scored in core_ranking retain pcq_core_score in CSV
    and are scored (never silently demoted) by evaluate_comparison.py."""
    root = tmp_path / "data"
    rec_sha = _sha("rec-rigid")
    flex_spec = ReceptorFlexSpec(mode=ReceptorFlexMode.RIGID, receptor_rigid_sha256=rec_sha)

    parents: list[ConsensusParentInput] = []
    for idx in range(1, 5):
        pid = f"synth_full_{idx}"
        parents.append(
            ConsensusParentInput(
                parent_compound_id=pid,
                parent_state_id=f"{pid}-s1",
                rotatable_bond_count=2,
                medoids=(
                    ConsensusPoseScoreInput(
                        cluster_id=f"cl-{pid}",
                        medoid_pose_id=f"pose-{pid}",
                        pose_complex=PoseComplexIdentity(
                            mode=ReceptorFlexMode.RIGID,
                            receptor_rigid_sha256=rec_sha,
                            ligand_pose_sha256=_sha(f"lig-{pid}"),
                        ),
                        canonical_coordinate_sha256=_sha(f"coord-{pid}"),
                        search_engines_present=("vina", "autodock4", "gnina"),
                        scores_by_function={
                            ScoringFunctionId.VINA: -9.5 + idx * 0.5,
                            ScoringFunctionId.AUTODOCK4: -9.0 + idx * 0.4,
                            ScoringFunctionId.GNINA_CNN_VS: 8.0 - idx * 0.6,
                        },
                    ),
                ),
            )
        )
    # Parent with valid Vina + AutoDock4 core scores, but GNINA failed:
    parents.append(
        ConsensusParentInput(
            parent_compound_id="synth_gnina_failed",
            parent_state_id="synth_gnina_failed-s1",
            rotatable_bond_count=3,
            medoids=(
                ConsensusPoseScoreInput(
                    cluster_id="cl-gnina-failed",
                    medoid_pose_id="pose-gnina-failed",
                    pose_complex=PoseComplexIdentity(
                        mode=ReceptorFlexMode.RIGID,
                        receptor_rigid_sha256=rec_sha,
                        ligand_pose_sha256=_sha("lig-gnina-failed"),
                    ),
                    canonical_coordinate_sha256=_sha("coord-gnina-failed"),
                    search_engines_present=("vina", "autodock4"),
                    scores_by_function={
                        ScoringFunctionId.VINA: -8.6,
                        ScoringFunctionId.AUTODOCK4: -8.3,
                    },
                    missing_or_failed_codes=("GNINA_SCORING_FAILED",),
                ),
            ),
        )
    )

    cons_store = ConsensusArtifactStore(root=root)
    cal_store = CalibrationArtifactStore(root=root)
    unused = SimpleNamespace()
    cons_svc = PoseConsensusService(
        store=cons_store,
        catalog=unused,  # type: ignore[arg-type]
        interactions=unused,  # type: ignore[arg-type]
        rescoring=unused,  # type: ignore[arg-type]
        receptors=unused,  # type: ignore[arg-type]
        binding_sites=unused,  # type: ignore[arg-type]
        maps=unused,  # type: ignore[arg-type]
        ligands=unused,  # type: ignore[arg-type]
        calibrations=cal_store,
    )
    record = cons_svc.create_structured_consensus(
        CreateStructuredConsensusRequest(
            name="Synthetic D7-001 Core Recovery Run",
            variant_id=ConsensusVariantId.PCQ_NEURAL_V1,
            receptor_id="rec-1",
            binding_site_id="site-1",
            receptor_flex_spec=flex_spec,
            binding_box_sha256=_sha("box-1"),
            autogrid_map_set_sha256=_sha("maps-1"),
            enabled_functions=(
                ScoringFunctionId.VINA,
                ScoringFunctionId.AUTODOCK4,
                ScoringFunctionId.GNINA_CNN_VS,
            ),
            k_max=3,
            search_engine_count=3,
            parents=tuple(parents),
        )
    )

    assert record.core_ranking is not None
    core_by_pid = {e.parent_compound_id: e for e in record.core_ranking.entries}
    expected_core_score = core_by_pid["synth_gnina_failed"].score_value
    assert core_by_pid["synth_gnina_failed"].tier == "full_profile"
    assert expected_core_score is not None

    csv_text = consensus_results_csv(record)
    rows = {row["parent_compound_id"]: row for row in csv.DictReader(io.StringIO(csv_text))}
    assert rows["synth_gnina_failed"]["tier"] == "partial_or_unscored"
    assert rows["synth_gnina_failed"]["rank"] == ""
    assert rows["synth_gnina_failed"]["pcq_score"] == ""
    assert float(rows["synth_gnina_failed"]["pcq_core_score"]) == pytest.approx(expected_core_score)

    export_svc = ConsensusExportService(
        root=root, consensus_store=cons_store, calibration_store=cal_store
    )
    receipt = export_svc.export_consensus_run(record.consensus_id)
    bundle_zip = Path(receipt["record_directory"]) / receipt["archive_filename"]

    verifier = _load_module("test_verify_export_bundle_d7001", VERIFIER_SCRIPT)
    report = verifier.verify_bundle(bundle_zip, require_format=5, require_core_hashes=True)
    assert report["verified"] is True

    evaluator = _load_module("test_evaluate_comparison_d7001", EVALUATOR_SCRIPT)
    neural_scores, _ = evaluator.load_ankora_export_scores(
        bundle_zip, score_column="pcq_score", higher_is_better=True
    )
    assert neural_scores["synth_full_1"].scored is True
    assert neural_scores["synth_gnina_failed"].scored is False

    core_scores, _ = evaluator.load_ankora_export_scores(
        bundle_zip, score_column="pcq_core_score", higher_is_better=True
    )
    assert core_scores["synth_full_1"].scored is True
    assert core_scores["synth_gnina_failed"].scored is True
    assert core_scores["synth_gnina_failed"].oriented_score == pytest.approx(expected_core_score)

    # Legacy bundle whose CSV blanked pcq_core_score recovers it from record.json core_ranking
    legacy_dir = tmp_path / "legacy_blank_core_csv"
    with zipfile.ZipFile(bundle_zip) as zf:
        zf.extractall(legacy_dir)
    blanked_csv = (legacy_dir / "results.csv").read_text(encoding="utf-8").replace(
        f"{expected_core_score:.6f}", ""
    )
    (legacy_dir / "results.csv").write_text(blanked_csv, encoding="utf-8", newline="\n")
    manifest_data = json.loads((legacy_dir / "manifest.json").read_text(encoding="utf-8"))
    manifest_data.pop("bundle_files", None)
    (legacy_dir / "manifest.json").write_text(
        json.dumps(manifest_data, indent=2), encoding="utf-8"
    )
    legacy_scores, _ = evaluator.load_ankora_export_scores(
        legacy_dir, score_column="pcq_core_score", higher_is_better=True
    )
    assert legacy_scores["synth_gnina_failed"].scored is True
    assert legacy_scores["synth_gnina_failed"].oriented_score == pytest.approx(expected_core_score)


def test_d5_003_d7_002_canceled_batch_export_verifies_and_reports_methods(tmp_path: Path) -> None:
    """D5-003 / D7-002: Canceled Vina batch emits counts['canceled'] + status='canceled',
    passes verify_export_bundle.py, and reports canceled count in MethodsReportService."""
    campaign = ExportedCampaign(
        engine="AutoDock Vina",
        engine_version="1.2.7",
        backend=None,
        value_column="vina_score_kcal_mol",
        reproducibility=ReproducibilityAssessment(),
        receptor_id="rec-1",
        receptor_sha256="1" * 64,
        binding_site_id="site-1",
        box={
            "center_x": 0.0,
            "center_y": 0.0,
            "center_z": 0.0,
            "size_x": 20.0,
            "size_y": 20.0,
            "size_z": 20.0,
        },
        map_set_id=None,
        map_set_identity_key=None,
        selection_manifest_sha256="2" * 64,
        library_id="lib-1",
        filter_run_id="flt-1",
        parameters={"exhaustiveness": 8, "num_modes": 9},
        executable_sha256=None,
        device_name=None,
        selected_count=3,
        succeeded_count=1,
        failed_count=1,
        canceled_count=1,
        campaign_status="canceled",
        rows=[
            {
                "rank": 1,
                "ligand_id": "lig-1",
                "status": "completed",
                "vina_score_kcal_mol": "-8.100",
                "failure_code": "",
            },
            {
                "rank": 2,
                "ligand_id": "lig-2",
                "status": "failed",
                "vina_score_kcal_mol": "",
                "failure_code": "VINA_EXEC_FAILED",
            },
            {
                "rank": 3,
                "ligand_id": "lig-3",
                "status": "canceled",
                "vina_score_kcal_mol": "",
                "failure_code": "CANCELED",
            },
        ],
    )
    bundle_zip = _make_synthetic_bundle(tmp_path / "canceled_bundle", campaign=campaign)

    verifier = _load_module("test_verify_export_bundle_d5003", VERIFIER_SCRIPT)
    report = verifier.verify_bundle(bundle_zip, require_core_hashes=True)
    assert report["verified"] is True
    assert report["row_count"] == 3

    manifest_data = json.loads((tmp_path / "canceled_bundle" / "manifest.json").read_text("utf-8"))
    assert manifest_data["counts"] == {
        "selected": 3,
        "succeeded": 1,
        "failed": 1,
        "canceled": 1,
        "status": "canceled",
    }

    entry = CatalogEntry(
        catalog_id="vina_batch:synth-canceled",
        engine_key="vina_batch",
        engine_label="AutoDock Vina",
        scoring_family=ScoringFamily.VINA,
        mode="screening",
        engine_version="1.2.7",
        record_id="synth-canceled",
        status="canceled",
        created_at=datetime(2026, 11, 26, 18, 0, tzinfo=UTC),
        receptor_id="rec-1",
        binding_site_id="site-1",
        library_id="lib-1",
        filter_run_id="flt-1",
        selected_count=3,
        succeeded_count=1,
        failed_count=1,
        canceled_count=1,
        reproducibility=ReproducibilityAssessment(),
        stale=True,
        stale_reasons=["upstream receptor rec-1 modified"],
    )
    missing_store = SimpleNamespace(
        load_record=_missing,
        load_batch=_missing,
        load_batch_record=_missing,
        load_job=_missing,
        load_campaign=_missing,
        load_library_record=_missing,
        load_filter_run=_missing,
    )
    svc = MethodsReportService(
        catalog=SimpleNamespace(get_campaign=lambda _: entry),
        structures=missing_store,
        receptors=missing_store,
        binding_sites=missing_store,
        ligands=missing_store,
        docking=missing_store,
        maps=missing_store,
        autodock4=missing_store,
        autodock_gpu=missing_store,
        pockets=missing_store,
        gnina=missing_store,
        gnina_screening=missing_store,
    )
    rendered = svc.render("vina_batch:synth-canceled")
    assert "WARNING — STALE ARTIFACT (ADR-011)" in rendered.markdown
    assert "campaign was canceled before completion" in rendered.markdown
    assert "and 1 were canceled" in rendered.markdown


def test_d5_009_d5_001_d5_022_verifier_cryptographic_bundle_files_stale_and_fuzz(
    tmp_path: Path,
) -> None:
    """D5-009, D5-001, D5-022:
    - Tampering a score in results.csv inside a standalone ZIP is caught via bundle_files SHA-256.
    - Injecting an extra unmanifested file into the ZIP is rejected.
    - Stale bundles surface dependency_freshness.stale=True in verifier JSON & CLI stderr.
    - Invalid UTF-8 and boolean counts fail closed with BundleVerificationError.
    """
    campaign = ExportedCampaign(
        engine="AutoDock Vina",
        engine_version="1.2.7",
        backend=None,
        value_column="vina_score_kcal_mol",
        reproducibility=ReproducibilityAssessment(),
        receptor_id="rec-1",
        receptor_sha256="1" * 64,
        binding_site_id="site-1",
        box={},
        map_set_id=None,
        map_set_identity_key=None,
        selection_manifest_sha256="2" * 64,
        library_id="lib-1",
        filter_run_id="flt-1",
        parameters={},
        executable_sha256=None,
        device_name=None,
        selected_count=1,
        succeeded_count=1,
        failed_count=0,
        rows=[
            {
                "rank": 1,
                "ligand_id": "lig-1",
                "status": "completed",
                "vina_score_kcal_mol": "-8.100",
                "failure_code": "",
            }
        ],
        dependency_freshness=ArtifactFreshness(
            stale=True,
            stale_reasons=("upstream receptor rec-1 replaced",),
            unresolved_parent_ids=(),
        ),
    )
    bundle_dir = tmp_path / "stale_bundle"
    bundle_zip = _make_synthetic_bundle(bundle_dir, campaign=campaign)
    verifier = _load_module("test_verify_export_bundle_d5009", VERIFIER_SCRIPT)

    ok_report = verifier.verify_bundle(bundle_zip, require_core_hashes=True)
    assert ok_report["verified"] is True
    assert ok_report["verified_bundle_files"] == 3
    assert ok_report["stale"] is True
    assert ok_report["stale_reasons"] == ["upstream receptor rec-1 replaced"]
    assert "WARNING: STALE ARTIFACT (ADR-011)" in (bundle_dir / "README.txt").read_text("utf-8")

    cli_proc = subprocess.run(
        [sys.executable, "-S", str(VERIFIER_SCRIPT), str(bundle_zip), "--require-core-hashes"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert cli_proc.returncode == 0, cli_proc.stdout + cli_proc.stderr
    assert "VERIFIED OK" in cli_proc.stdout
    assert "WARNING [ADR-011 STALE ARTIFACT]" in cli_proc.stderr

    # Tampering a score in results.csv inside standalone ZIP fails SHA-256 verification (D5-009)
    tampered_score_zip = tmp_path / "tampered_score.zip"
    with (
        zipfile.ZipFile(bundle_zip, "r") as src_zf,
        zipfile.ZipFile(tampered_score_zip, "w", compression=zipfile.ZIP_DEFLATED) as dst_zf,
    ):
        for info in src_zf.infolist():
            data = src_zf.read(info.filename)
            if info.filename == "results.csv":
                data = data.replace(b"-8.100", b"-9.900")
            dst_zf.writestr(info.filename, data)
    with pytest.raises(verifier.BundleVerificationError, match="SHA-256 mismatch for bundle_file"):
        verifier.verify_bundle(tampered_score_zip)

    # Injecting an unexpected unmanifested file into the ZIP is rejected (D5-009)
    extra_file_zip = tmp_path / "extra_file.zip"
    with (
        zipfile.ZipFile(bundle_zip, "r") as src_zf,
        zipfile.ZipFile(extra_file_zip, "w", compression=zipfile.ZIP_DEFLATED) as dst_zf,
    ):
        for info in src_zf.infolist():
            dst_zf.writestr(info.filename, src_zf.read(info.filename))
        dst_zf.writestr("injected_notes.txt", b"spoofed claim")
    with pytest.raises(verifier.BundleVerificationError, match="unexpected unmanifested file"):
        verifier.verify_bundle(extra_file_zip)

    # Invalid UTF-8 in README.txt raises BundleVerificationError (D5-022)
    bad_utf8_dir = tmp_path / "bad_utf8"
    with zipfile.ZipFile(bundle_zip) as zf:
        zf.extractall(bad_utf8_dir)
    (bad_utf8_dir / "README.txt").write_bytes(b"\xff\xfe\xfa invalid utf8")
    with pytest.raises(verifier.BundleVerificationError, match="not valid UTF-8"):
        verifier.verify_bundle(bad_utf8_dir)

    # Boolean counts are rejected strictly (D5-022)
    bool_counts_dir = tmp_path / "bool_counts"
    with zipfile.ZipFile(bundle_zip) as zf:
        zf.extractall(bool_counts_dir)
    bad_manifest = json.loads((bool_counts_dir / "manifest.json").read_text("utf-8"))
    bad_manifest["counts"] = {"selected": True, "succeeded": True, "failed": False}
    (bool_counts_dir / "manifest.json").write_text(json.dumps(bad_manifest), encoding="utf-8")
    with pytest.raises(verifier.BundleVerificationError, match="disagrees with manifest counts"):
        verifier.verify_bundle(bool_counts_dir)


def test_d7_003_d5_017_consensus_readme_v6_and_multi_library_resolution(tmp_path: Path) -> None:
    """D7-003 & D5-017: _consensus_readme emits dynamic Export v6 & --require-format 6,
    and _resolve_source_library_ids returns every distinct source library_id."""
    now = datetime(2026, 11, 26, 18, 0, tzinfo=UTC)
    rec = SimpleNamespace(
        consensus_id="cons-v6",
        name="Synthetic v6 Consensus",
        variant_id=ConsensusVariantId.PCQ_NEURAL_V1,
        k_max=3,
        rmsd_threshold_angstrom=2.0,
        ecr_tau=0.05,
        source_catalog_ids=("vina_batch:b1", "autodock4_batch:b2"),
        reference_panel=SimpleNamespace(
            panel_id="panel-1",
            reference_panel_sha256="c" * 64,
        ),
        ranking=SimpleNamespace(
            full_profile_count=2,
            partial_or_unscored_count=0,
            entries=(),
        ),
        enabled_functions=(
            ScoringFunctionId.VINA,
            ScoringFunctionId.AUTODOCK4,
            ScoringFunctionId.GNINA_CNN_VS,
        ),
    )
    txt = _consensus_readme(
        rec,  # type: ignore[arg-type]
        export_format=6,
        exported_at=now,
        archive_filename="Ankora_consensus_v6_bundle.zip",
        input_identity_sha256="a" * 64,
        bundle_identity_sha256="b" * 64,
        freshness=ArtifactFreshness(stale=True, stale_reasons=("site stale",)),
    )
    assert "Ankora Export v6 — ADR-030 Rank-Space Consensus Bundle" in txt
    assert "--require-format 6" in txt
    assert "--require-format 5" not in txt
    assert "WARNING: STALE ARTIFACT (ADR-011)" in txt

    proj = tmp_path / "proj"
    (proj / "results" / "docking_batches" / "b1").mkdir(parents=True)
    (proj / "results" / "docking_batches" / "b1" / "record.json").write_text(
        json.dumps({"request": {"library_id": "lib-parent"}}), encoding="utf-8"
    )
    (proj / "results" / "autodock4_batches" / "b2").mkdir(parents=True)
    (proj / "results" / "autodock4_batches" / "b2" / "record.json").write_text(
        json.dumps({"request": {"library_id": "lib-analog"}}), encoding="utf-8"
    )
    libs = _resolve_source_library_ids(proj, ["vina_batch:b1", "autodock4_batch:b2"])
    assert libs == ["lib-parent", "lib-analog"]
