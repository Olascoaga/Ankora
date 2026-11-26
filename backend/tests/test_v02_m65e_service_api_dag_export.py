"""End-to-end tests for M6.5e (AnalogExpansionService, API, DAG stale lineage, Methods & Export v6).

All structures, catalogs, poses, and docking batches in this module are synthetic.
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import UTC, datetime
from hashlib import sha256
from importlib import import_module
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from ankora_backend.api.app import create_app
from ankora_backend.persistence.docking_store import DockingArtifactStore
from ankora_backend.persistence.ligand_store import LigandArtifactStore
from ankora_backend.schemas.analog_expansion import (
    AnalogCandidateRole,
    AnalogCatalogRecord,
    AnalogSearchRecord,
    AnalogSelectionRecord,
    ExternalConsentPreview,
    McsCoreRmsdResult,
    McsCoreRmsdStatus,
)
from ankora_backend.schemas.binding_sites import BindingSiteRecord, BindingSiteSource
from ankora_backend.schemas.docking import (
    DockingEngine,
    DockingExecutionEvidence,
    DockingJobPhase,
    DockingJobStatus,
    DockingPoseArtifact,
    DockingPoseResult,
    VinaBatchDockingParameters,
    VinaBatchDockingRecord,
    VinaBatchDockingRequest,
    VinaBatchLigandResult,
)
from ankora_backend.schemas.ligands import LigandSource
from ankora_backend.schemas.projects import DependencyNodeKind
from ankora_backend.schemas.provenance import ProvenanceEvent, ToolIdentity
from ankora_backend.services.project_dependencies import ProjectDependencyService
from ankora_backend.services.result_catalog import VINA_BATCH

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_v02_m65b_pose_focused_site import _seed_project_with_saved_pose  # noqa: E402

Chem: Any = import_module("rdkit.Chem")
AllChem: Any = import_module("rdkit.Chem.AllChem")

ROOT = Path(__file__).resolve().parents[2]
VERIFY_SCRIPT = ROOT / "scripts" / "verify_export_bundle.py"


def _create_synthetic_focused_batch(
    *,
    data_dir: Path,
    receptor_id: str,
    focused_site_id: str,
    derived_library_id: str,
    pose_bytes: bytes,
) -> str:
    now = datetime.now(UTC)
    tool = ToolIdentity(name="AutoDock Vina", version="1.2.7")
    lig_store = LigandArtifactStore(root=data_dir)
    lib = lig_store.load_library_record(derived_library_id)
    first_entry = next(e for e in lib.entries if e.ligand is not None)
    assert first_entry.ligand is not None
    lig = first_entry.ligand

    dock_store = DockingArtifactStore(root=data_dir)
    batch_id = dock_store.new_batch_id()
    pose_id = f"{batch_id}-pose-1"
    pose_sha = sha256(pose_bytes).hexdigest()
    record = VinaBatchDockingRecord(
        batch_id=batch_id,
        engine=DockingEngine.AUTODOCK_VINA,
        status=DockingJobStatus.COMPLETED,
        phase=DockingJobPhase.COMPLETE,
        created_at=now,
        started_at=now,
        completed_at=now,
        request=VinaBatchDockingRequest(
            receptor_id=receptor_id,
            binding_site_id=focused_site_id,
            library_id=derived_library_id,
            filter_run_id="synthetic-filter-run",
            parameters=VinaBatchDockingParameters(
                total_cpu_threads=1,
                parallel_ligands=1,
                exhaustiveness=8,
                num_modes=1,
                seed=42,
            ),
            acknowledge_inputs_and_scoring=True,
        ),
        tool=tool,
        receptor_output_artifact_id=f"{receptor_id}-pdbqt",
        receptor_sha256="a" * 64,
        selection_manifest_artifact_id="synthetic-selection-manifest",
        selection_manifest_sha256="b" * 64,
        selected_count=1,
        worker_count=1,
        threads_per_ligand=1,
        completed_count=1,
        succeeded_count=1,
        failed_count=0,
        canceled_count=0,
        entries=[
            VinaBatchLigandResult(
                ligand_id=lig.artifact.ligand_id,
                parent_compound_id=lig.artifact.ligand_id,
                source_index=0,
                name=lig.inspection.name,
                canonical_smiles=lig.inspection.canonical_smiles,
                molecular_weight_g_mol=lig.inspection.molecular_weight_g_mol,
                ligand_preparation_id="synth-prep",
                ligand_sha256=pose_sha,
                status=DockingJobStatus.COMPLETED,
                phase=DockingJobPhase.COMPLETE,
                started_at=now,
                completed_at=now,
                command=["vina"],
                execution=DockingExecutionEvidence(
                    command=["vina"], exit_code=0, stdout="", stderr=""
                ),
                poses=[
                    DockingPoseResult(
                        mode=1,
                        affinity_kcal_mol=-8.1,
                        rmsd_lower_bound_angstrom=0.0,
                        rmsd_upper_bound_angstrom=0.0,
                        artifact=DockingPoseArtifact(
                            artifact_id=pose_id,
                            mode=1,
                            filename="pose_01.pdbqt",
                            format="pdbqt",
                            sha256=pose_sha,
                            size_bytes=len(pose_bytes),
                            content_url=f"/api/v1/docking/vina/batches/{batch_id}/ligands/{lig.artifact.ligand_id}/poses/{pose_id}/content",
                        ),
                    )
                ],
                provenance=ProvenanceEvent(
                    event_id=f"batch-lig-{batch_id}",
                    event_type="vina_batch_ligand_completed",
                    timestamp=now,
                    input_artifacts=[receptor_id, focused_site_id],
                    output_artifacts=[pose_id],
                    tool=tool,
                    parameters={},
                ),
            )
        ],
        warnings=[],
        provenance=ProvenanceEvent(
            event_id=f"batch-{batch_id}",
            event_type="vina_batch_completed",
            timestamp=now,
            input_artifacts=[receptor_id, focused_site_id, derived_library_id],
            output_artifacts=[batch_id],
            tool=tool,
            parameters={},
        ),
    )
    dock_store.create_batch(record)
    out_file = dock_store.batch_output_path(batch_id, lig.artifact.ligand_id, "pose_01.pdbqt")
    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_bytes(pose_bytes)
    return batch_id


def test_end_to_end_offline_analog_expansion_pose_focused_site_dag_and_export_v6_tamper_detection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Full ADR-033 loop: catalog -> search -> selection -> library -> POSE_FOCUSED -> Export v6."""
    data_dir = tmp_path / "ankora_data"
    monkeypatch.setenv("ANKORA_DATA_DIR", str(data_dir))
    seeded = _seed_project_with_saved_pose(data_dir, with_flex_res=False, bonded_pose=True)
    app = create_app()

    with TestClient(app) as client:
        # 1. Import bounded CSV analog catalog (100% offline)
        csv_bytes = (
            b"cid,smiles\n"
            b"ethanol_analog,CCO\n"
            b"propanol_analog,CCCO\n"
            b"methanol_seed,CO\n"
            b"bad_row,NOT_VALID\n"
        )
        cat_resp = client.post(
            "/api/v1/analog-expansion/catalogs",
            files={"file": ("synth_analogs.csv", csv_bytes, "text/csv")},
            data={
                "name": "Synthetic Alcohol Series",
                "smiles_column": "smiles",
                "id_column": "cid",
            },
        )
        assert cat_resp.status_code == 201, cat_resp.text
        catalog = AnalogCatalogRecord.model_validate(cat_resp.json())
        assert catalog.valid_records == 3
        assert catalog.invalid_records == 1

        # 2. Run 100% offline RDKit Morgan similarity search anchored to saved lead pose
        search_resp = client.post(
            "/api/v1/analog-expansion/searches/offline",
            json={
                "source_catalog_id": seeded["catalog_id"],
                "source_ligand_id": seeded["ligand_id"],
                "source_pose_artifact_id": seeded["pose_artifact_id"],
                "analog_catalog_id": catalog.analog_catalog_id,
                "min_tanimoto": 0.0,
                "top_k": 10,
            },
        )
        assert search_resp.status_code == 201, search_resp.text
        search = AnalogSearchRecord.model_validate(search_resp.json())
        assert search.query_canonical_isomeric_smiles == "CO"
        assert search.hits[0].role is AnalogCandidateRole.SEED_CONTROL
        analog_ids = [h.hit_id for h in search.hits if h.role is AnalogCandidateRole.ANALOG]
        assert len(analog_ids) == 2

        # 3. Curate explicit selection (including mandatory seed_control) -> derived LigandLibrary
        sel_resp = client.post(
            f"/api/v1/analog-expansion/searches/{search.analog_search_id}/selections",
            json={
                "library_name": "Focused Methanol Analogs",
                "selected_hit_ids": [analog_ids[0]],
                "include_seed_control": True,
            },
        )
        assert sel_resp.status_code == 201, sel_resp.text
        selection = AnalogSelectionRecord.model_validate(sel_resp.json())
        assert selection.selected_count == 2  # seed_control + 1 analog
        assert selection.include_seed_control is True

        lig_store = LigandArtifactStore(root=data_dir)
        derived_lib = lig_store.load_library_record(selection.derived_library_id)
        assert derived_lib.artifact.origin_analog_selection_id == selection.analog_selection_id
        assert derived_lib.artifact.origin_analog_search_id == search.analog_search_id
        assert derived_lib.entries[0].ligand is not None
        assert derived_lib.entries[0].ligand.artifact.source is LigandSource.ANALOG_EXPANSION
        assert derived_lib.entries[0].ligand.inspection.name.startswith("SEED_")

        # 4. Derive immutable POSE_FOCUSED binding site from the same saved lead pose
        site_resp = client.post(
            f"/api/v1/receptors/{seeded['receptor_id']}/binding-sites",
            json={
                "source": "pose_focused",
                "parent_binding_site_id": seeded["parent_site_id"],
                "pose_focused": {
                    "source_catalog_id": seeded["catalog_id"],
                    "ligand_id": seeded["ligand_id"],
                    "pose_artifact_id": seeded["pose_artifact_id"],
                    "padding_angstrom": 5.0,
                },
            },
        )
        assert site_resp.status_code == 201, site_resp.text
        focused_site = BindingSiteRecord.model_validate(site_resp.json())
        assert focused_site.decisions.source is BindingSiteSource.POSE_FOCUSED

        # 5. Create synthetic focused batch campaign and export -> MUST auto-upgrade to Export v6!
        pose_bytes = (
            b"MODEL 1\nROOT\n"
            b"ATOM      1  C1  UNL     1       0.000   0.000   0.000  1.00  0.00    +0.000 C\n"
            b"ATOM      2  O1  UNL     1       1.400   0.000   0.000  1.00  0.00    +0.000 OA\n"
            b"ENDROOT\nTORSDOF 0\nENDMDL\n"
        )
        batch_id = _create_synthetic_focused_batch(
            data_dir=data_dir,
            receptor_id=seeded["receptor_id"],
            focused_site_id=focused_site.binding_site_id,
            derived_library_id=selection.derived_library_id,
            pose_bytes=pose_bytes,
        )
        export_resp = client.post(
            "/api/v1/exports/campaigns",
            params={
                "source_kind": VINA_BATCH,
                "source_id": batch_id,
                "display_name": "Focused Analog Campaign",
            },
        )
        assert export_resp.status_code == 201, export_resp.text
        export_data = export_resp.json()
        export_dir = Path(export_data["directory"])
        manifest = json.loads((export_dir / "manifest.json").read_text(encoding="utf-8"))
        assert manifest["ankora_export_format"] == 6
        assert "analog_expansion_provenance" in manifest
        assert (
            manifest["analog_expansion_provenance"]["analog_search_id"]
            == search.analog_search_id
        )
        assert (
            manifest["analog_expansion_provenance"]["pose_focused_binding_site_id"]
            == focused_site.binding_site_id
        )
        methods_text = (export_dir / "methods.md").read_text(encoding="utf-8")
        assert "Hit-to-Analog Structural Similarity Expansion" in methods_text
        assert "ADR-033" in methods_text

        # 6. Zero-dependency stdlib verifier MUST verify Export v6 under `python -S`
        proc = subprocess.run(
            [
                sys.executable,
                "-S",
                str(VERIFY_SCRIPT),
                str(export_dir),
                "--require-format",
                "6",
                "--json",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        assert proc.returncode == 0, proc.stdout + proc.stderr
        ver_report = json.loads(proc.stdout)
        assert ver_report["verified"] is True
        assert ver_report["ankora_export_format"] == 6
        assert ver_report["analog_verified_evidence_files"] >= 4

        # 7. Tampering an analog_expansion evidence artifact MUST fail verification closed!
        first_analog_art = manifest["recorded_evidence"]["analog_expansion_artifacts"][0]
        tampered_path = export_dir / first_analog_art["path"]
        tampered_path.write_text(tampered_path.read_text(encoding="utf-8") + " ", encoding="utf-8")
        tamper_proc = subprocess.run(
            [sys.executable, "-S", str(VERIFY_SCRIPT), str(export_dir), "--json"],
            capture_output=True,
            text=True,
            check=False,
        )
        assert tamper_proc.returncode != 0

        # 8. DAG stale propagation (ADR-011): source job -> search -> selection -> derived library
        deps = ProjectDependencyService(root=data_dir)
        graph = deps.graph(offset=0, limit=200)
        kinds_present = {node.kind for node in graph.nodes}
        assert DependencyNodeKind.ANALOG_CATALOG in kinds_present
        assert DependencyNodeKind.ANALOG_SEARCH in kinds_present
        assert DependencyNodeKind.ANALOG_SELECTION in kinds_present

        marked = deps.mark_stale(catalog.analog_catalog_id, "Catalog snapshot superseded")
        assert search.analog_search_id in marked.affected_node_ids
        assert selection.analog_selection_id in marked.affected_node_ids
        assert selection.derived_library_id in marked.affected_node_ids

        # 9. External consent preview works offline & online search without consent fails 422
        consent_resp = client.post(
            "/api/v1/analog-expansion/external-consent-preview",
            json={
                "source_catalog_id": seeded["catalog_id"],
                "source_ligand_id": seeded["ligand_id"],
                "source_pose_artifact_id": seeded["pose_artifact_id"],
                "provider": "pubchem_pug_rest",
            },
        )
        assert consent_resp.status_code == 200, consent_resp.text
        preview = ExternalConsentPreview.model_validate(consent_resp.json())
        assert preview.query_canonical_isomeric_smiles == "CO"
        assert "intellectual property" in preview.disclosure_message.lower()

        bad_online = client.post(
            "/api/v1/analog-expansion/searches/online",
            json={
                "source_catalog_id": seeded["catalog_id"],
                "source_ligand_id": seeded["ligand_id"],
                "source_pose_artifact_id": seeded["pose_artifact_id"],
                "provider": "pubchem_pug_rest",
                "consent": {
                    "provider": "pubchem_pug_rest",
                    "query_canonical_smiles": "CO",
                    "consent_payload_sha256": preview.consent_payload_sha256,
                    "acknowledge_external_transmission": False,
                },
            },
        )
        assert bad_online.status_code == 422
        assert bad_online.json()["code"] == "ANALOG_EXTERNAL_CONSENT_REQUIRED"

        # 10. MCS core RMSD REST endpoint works (self-pose -> 0.0 A, superposition_applied=False)
        mcs_resp = client.post(
            "/api/v1/analog-expansion/mcs-core-rmsd",
            json={
                "seed_catalog_id": seeded["catalog_id"],
                "seed_ligand_id": seeded["ligand_id"],
                "seed_pose_artifact_id": seeded["pose_artifact_id"],
                "target_catalog_id": seeded["catalog_id"],
                "target_ligand_id": seeded["ligand_id"],
                "target_pose_artifact_id": seeded["pose_artifact_id"],
            },
        )
        assert mcs_resp.status_code == 200, mcs_resp.text
        mcs_res = McsCoreRmsdResult.model_validate(mcs_resp.json())
        assert mcs_res.status is McsCoreRmsdStatus.EVALUATED
        assert mcs_res.superposition_applied is False
        assert mcs_res.receptor_frame_rmsd_angstrom == pytest.approx(0.0, abs=1e-4)
