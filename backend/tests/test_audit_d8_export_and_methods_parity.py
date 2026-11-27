"""Regression tests for Wave 3 D8 export & Methods report parity fixes
(D8-011, D8-012, D8-013, D8-015).

All records, fixtures, and manifests in this module are synthetic.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from test_gnina_methods import _job as _gnina_job

from ankora_backend.persistence.binding_site_store import BindingSiteArtifactStore
from ankora_backend.persistence.calibration_store import CalibrationArtifactStore
from ankora_backend.persistence.consensus_store import ConsensusArtifactStore
from ankora_backend.persistence.gnina_store import GninaJobStore
from ankora_backend.persistence.pocket_detection_store import PocketDetectionArtifactStore
from ankora_backend.schemas.binding_sites import (
    BindingBox,
    BindingSiteRecord,
    BindingSiteRequest,
    BindingSiteSource,
    PocketCandidate,
    PocketDetectionReport,
    PocketSelection,
    PoseFocusedEvidence,
    PoseFocusedOrigin,
)
from ankora_backend.schemas.consensus import (
    ConsensusParentInput,
    ConsensusPoseScoreInput,
    ConsensusVariantId,
    CreateStructuredConsensusRequest,
    PcL2ModelArtifact,
)
from ankora_backend.schemas.provenance import ProvenanceEvent, ToolIdentity
from ankora_backend.schemas.receptors import ReceptorFlexMode, ReceptorFlexSpec, ResidueLocator
from ankora_backend.schemas.rescoring import ScoringFunctionId
from ankora_backend.schemas.v02_contracts import PoseComplexIdentity
from ankora_backend.schemas.warnings import StructuredWarning, WarningCode
from ankora_backend.services.consensus_export import (
    ConsensusExportService,
    _resolve_source_library_ids,
)
from ankora_backend.services.methods_report import MethodsReportService
from ankora_backend.services.pose_consensus import PoseConsensusService
from ankora_backend.services.result_catalog import GNINA_JOB, ResultCatalogService


def _sha(text: str) -> str:
    return sha256(text.encode("utf-8")).hexdigest()


def _create_synthetic_consensus(
    root: Path,
    *,
    warnings: tuple[StructuredWarning, ...] = (),
    source_catalog_ids: tuple[str, ...] = (),
    pc_l2_model: PcL2ModelArtifact | None = None,
) -> tuple[ConsensusArtifactStore, CalibrationArtifactStore, str]:
    rec_sha = _sha("synthetic-receptor")
    flex_spec = ReceptorFlexSpec(mode=ReceptorFlexMode.RIGID, receptor_rigid_sha256=rec_sha)
    parents = [
        ConsensusParentInput(
            parent_compound_id=f"synth_p{idx}",
            parent_state_id=f"synth_p{idx}-s1",
            rotatable_bond_count=2,
            medoids=(
                ConsensusPoseScoreInput(
                    cluster_id=f"cl-{idx}",
                    medoid_pose_id=f"pose-{idx}",
                    pose_complex=PoseComplexIdentity(
                        mode=ReceptorFlexMode.RIGID,
                        receptor_rigid_sha256=rec_sha,
                        ligand_pose_sha256=_sha(f"lig-{idx}"),
                    ),
                    canonical_coordinate_sha256=_sha(f"coord-{idx}"),
                    search_engines_present=("vina", "autodock4"),
                    scores_by_function={
                        ScoringFunctionId.VINA: -8.5 + idx * 0.3,
                        ScoringFunctionId.AUTODOCK4: -8.2 + idx * 0.3,
                    },
                ),
            ),
        )
        for idx in range(3)
    ]
    cons_store = ConsensusArtifactStore(root=root)
    cal_store = CalibrationArtifactStore(root=root)
    unused = SimpleNamespace()
    svc = PoseConsensusService(
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
    record = svc.create_structured_consensus(
        CreateStructuredConsensusRequest(
            name="Synthetic D8 Consensus",
            variant_id=ConsensusVariantId.PCQ_CORE_V1,
            receptor_id="rec-1",
            binding_site_id="site-1",
            receptor_flex_spec=flex_spec,
            binding_box_sha256=_sha("box-1"),
            autogrid_map_set_sha256=_sha("maps-1"),
            enabled_functions=(ScoringFunctionId.VINA, ScoringFunctionId.AUTODOCK4),
            k_max=2,
            search_engine_count=2,
            parents=tuple(parents),
        )
    )
    if warnings or source_catalog_ids or pc_l2_model is not None:
        updated = record.model_copy(
            update={
                "warnings": (*record.warnings, *warnings),
                "source_catalog_ids": source_catalog_ids or record.source_catalog_ids,
                "pc_l2_model": pc_l2_model,
            }
        )
        rec_path = cons_store._run_dir(record.consensus_id) / "record.json"
        rec_path.write_text(updated.model_dump_json(indent=2), encoding="utf-8")
    return cons_store, cal_store, record.consensus_id


def test_d8_011_resolve_source_library_ids_reads_gnina_screening_campaigns_dir(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "projects" / "default"
    campaign_id = str(uuid4())
    lib_id = str(uuid4())
    rec_dir = project_root / "results" / "gnina_screening_campaigns" / campaign_id
    rec_dir.mkdir(parents=True)
    (rec_dir / "record.json").write_text(
        json.dumps({"request": {"library_id": lib_id}}),
        encoding="utf-8",
    )

    resolved = _resolve_source_library_ids(project_root, [f"gnina_screening:{campaign_id}"])
    assert resolved == [lib_id]


def test_d8_012_and_d8_013_consensus_export_preserves_warnings_and_reports_corrupt_m2_records(
    tmp_path: Path,
) -> None:
    cal_id = str(uuid4())
    cal_dir = tmp_path / "projects" / "default" / "calibrations" / cal_id
    cal_dir.mkdir(parents=True)
    # Write deliberately corrupt calibration JSON so M2 methods rendering catches parse failure.
    (cal_dir / "record.json").write_text("{corrupt-json", encoding="utf-8")

    scientific_warning = StructuredWarning(
        code=WarningCode.DOCKING_GPU_REPRODUCIBILITY_UNVERIFIED,
        message="Synthetic scientific advisory preserved in consensus export.",
        stage="pose_consensus",
        details={"source": "synthetic"},
        recoverable=True,
    )
    pc_l2 = PcL2ModelArtifact(
        calibration_id=cal_id,
        split_identity_sha256=_sha("split-1"),
        reference_panel_sha256=_sha("panel-1"),
        l2_regularization=1.0,
        feature_functions=(ScoringFunctionId.VINA, ScoringFunctionId.AUTODOCK4),
        weights={ScoringFunctionId.VINA: 0.5, ScoringFunctionId.AUTODOCK4: 0.5},
        intercept=0.0,
        solver_name="scipy.optimize.L-BFGS-B",
        iterations=5,
        final_objective=0.123,
        promoted=False,
        promotion_verdict_text="Synthetic non-promoted verdict",
    )
    cons_store, cal_store, consensus_id = _create_synthetic_consensus(
        tmp_path,
        warnings=(scientific_warning,),
        pc_l2_model=pc_l2,
    )
    export_svc = ConsensusExportService(
        root=tmp_path,
        consensus_store=cons_store,
        calibration_store=cal_store,
    )
    receipt = export_svc.export_consensus_run(consensus_id)
    manifest = json.loads(
        (Path(receipt["record_directory"]) / "manifest.json").read_text(encoding="utf-8")
    )

    # D8-012: scientific record.warnings preserved even when not stale
    warning_codes = [w["code"] for w in manifest.get("warnings", [])]
    assert WarningCode.DOCKING_GPU_REPRODUCIBILITY_UNVERIFIED.value in warning_codes

    # D8-013: unreadable M2 calibration record surfaced in collection_warnings
    collection_warnings = manifest["recorded_evidence"]["collection_warnings"]
    assert any(
        w["kind"] == "calibration_methods_unreadable" and w["identity"] == cal_id
        for w in collection_warnings
    )


def test_d8_013_and_d8_015_methods_report_surfaces_corrupt_v02_gnina_pockets_and_pose_focused(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "projects" / "default"
    gnina_store = GninaJobStore(tmp_path)
    pocket_store = PocketDetectionArtifactStore(tmp_path)
    now = datetime.now(UTC)
    box = BindingBox(center_x=1, center_y=2, center_z=3, size_x=10, size_y=12, size_z=14)

    report_id = pocket_store.new_report_id()
    pocket_record = PocketDetectionReport(
        report_id=report_id,
        receptor_id="synthetic-receptor",
        source_output_artifact_id="synthetic-receptor-pdbqt",
        generated_at=now,
        tool=ToolIdentity(name="P2Rank", version="2.4.2"),
        candidates=[
            PocketCandidate(
                pocket_id="pocket1",
                rank=1,
                druggability_score=0.81,
                volume_angstrom3=320.0,
                box=box,
                lining_residues=[
                    ResidueLocator(chain_id="A", residue_name="ALA", sequence_number=10)
                ],
            )
        ],
        warnings=[],
        provenance=ProvenanceEvent(
            event_id="synth-pocket-1",
            event_type="pocket_detection",
            timestamp=now,
            tool=ToolIdentity(name="P2Rank", version="2.4.2"),
        ),
    )
    pocket_store.save_record(pocket_record)

    site_store = BindingSiteArtifactStore(tmp_path)
    parent_site_id = site_store.new_binding_site_id()
    focused_site_id = site_store.new_binding_site_id()
    parent_site = BindingSiteRecord(
        binding_site_id=parent_site_id,
        receptor_id="synthetic-receptor",
        source_artifact_id="synthetic-source",
        created_at=now,
        box=box,
        decisions=BindingSiteRequest(
            source=BindingSiteSource.POCKET_DETECTED,
            pocket_selection=PocketSelection(report_id=report_id, pocket_id="pocket1"),
        ),
        warnings=[],
        provenance=[],
    )
    site_store.save_record(parent_site)

    focused_site = BindingSiteRecord(
        binding_site_id=focused_site_id,
        receptor_id="synthetic-receptor",
        source_artifact_id="synthetic-source",
        created_at=now,
        box=box,
        decisions=BindingSiteRequest(
            source=BindingSiteSource.POSE_FOCUSED,
            pose_focused=PoseFocusedOrigin(
                source_catalog_id="vina_batch:parent-batch",
                ligand_id="seed-lig-1",
                pose_artifact_id="seed-pose-1",
            ),
            parent_binding_site_id=parent_site_id,
        ),
        warnings=[],
        provenance=[],
        pose_focused_evidence=PoseFocusedEvidence(
            source_catalog_id="vina_batch:parent-batch",
            engine_key="vina_batch",
            record_id="parent-batch",
            ligand_id="seed-lig-1",
            ligand_preparation_id="seed-prep-1",
            pose_artifact_id="seed-pose-1",
            pose_sha256=_sha("seed-pose-bytes"),
            heavy_atom_count=18,
            excluded_hydrogen_count=10,
            excluded_pseudoatom_count=0,
            computed_base_box=box,
            flex_containment_checked=False,
        ),
    )
    site_store.save_record(focused_site)

    job = _gnina_job(gnina_store)
    job = job.model_copy(
        update={
            "request": job.request.model_copy(update={"binding_site_id": focused_site_id})
        }
    )
    gnina_store.create_job(job)

    # Plant corrupt M3 pose_quality and M2 calibration records to test D8-013 gap reporting
    bad_pq = project_root / "analysis" / "pose_quality" / "corrupt-pq"
    bad_pq.mkdir(parents=True)
    (bad_pq / "record.json").write_text("{broken", encoding="utf-8")

    bad_cal = project_root / "calibrations" / "corrupt-cal"
    bad_cal.mkdir(parents=True)
    (bad_cal / "record.json").write_text("{broken", encoding="utf-8")

    svc = MethodsReportService.from_root(tmp_path)
    catalog_id = f"{GNINA_JOB}:{job.job_id}"
    assert ResultCatalogService.from_root(tmp_path).get_campaign(catalog_id).record_id == job.job_id

    report = svc.render(catalog_id)

    # D8-015: pose_focused readable label, GNINA inherited P2Rank citation, ADR-033 section
    assert "pose-focused box around a selected hit pose" in report.markdown
    assert "P2Rank 2.4.2" in report.markdown
    assert "pocket1" in report.markdown
    assert any(sw.name == "P2Rank" and sw.version == "2.4.2" for sw in report.software)
    heading = "Hit-to-Analog Structural Similarity Expansion & Pose-Focused Re-Screening"
    assert heading in report.markdown
    assert "seed-pose-1" in report.markdown

    # D8-013: corrupt M3 and M2 records surface as explicit gaps
    assert any("unreadable pose quality record (corrupt-pq)" in gap for gap in report.gaps)
    assert any("unreadable calibration record (corrupt-cal)" in gap for gap in report.gaps)
