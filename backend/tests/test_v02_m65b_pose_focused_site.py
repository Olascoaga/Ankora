"""Tests for M6.5b (ADR-033 §3 immutable BindingSiteSource.POSE_FOCUSED + FlexRes/ADR-018/E7).

All molecular structures, pose coordinates, and docking records in this module are synthetic.
"""

from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ankora_backend.api.app import create_app
from ankora_backend.persistence.artifact_store import StructureArtifactStore
from ankora_backend.persistence.binding_site_store import BindingSiteArtifactStore
from ankora_backend.persistence.docking_store import DockingArtifactStore
from ankora_backend.persistence.ligand_store import LigandArtifactStore
from ankora_backend.persistence.receptor_store import ReceptorArtifactStore
from ankora_backend.schemas.binding_sites import (
    BindingBox,
    BindingSitePreview,
    BindingSiteRecord,
    BindingSiteRequest,
    BindingSiteSource,
)
from ankora_backend.schemas.docking import (
    DockingEngine,
    DockingExecutionEvidence,
    DockingJobPhase,
    DockingJobStatus,
    DockingPoseArtifact,
    DockingPoseResult,
    VinaDockingJobRecord,
    VinaDockingParameters,
    VinaDockingRequest,
)
from ankora_backend.schemas.ligands import (
    LigandArtifact,
    LigandChargeModel,
    LigandConformerArtifact,
    LigandConformerRecord,
    LigandForceField,
    LigandFormat,
    LigandInspection,
    LigandMinimizationResult,
    LigandPdbqtArtifact,
    LigandPdbqtRecord,
    LigandRecord,
    LigandSource,
)
from ankora_backend.schemas.provenance import ProvenanceEvent, ToolIdentity
from ankora_backend.schemas.receptors import (
    ComponentAction,
    ReceptorFlexMode,
    ReceptorFlexSpec,
    ReceptorOutputArtifact,
    ReceptorOutputStage,
    ReceptorPreparationRecord,
    ReceptorPreparationRequest,
    ReceptorPreparationStatus,
    ResidueLocator,
)
from ankora_backend.schemas.structures import (
    ChainSummary,
    StructureArtifact,
    StructureFormat,
    StructureMetadata,
    StructureRecord,
    StructureSource,
)
from ankora_backend.schemas.warnings import WarningCode
from ankora_backend.services.project_dependencies import ProjectDependencyService
from ankora_backend.services.result_catalog import VINA_JOB

# Synthetic minimal receptor PDB with SER A:5 whose CA is at (2, 2, 2) and OG is at (8, 2, 2).
_SYNTH_RECEPTOR_PDB = """\
ATOM      1  N   SER A   5       1.000   2.000   2.000  1.00 20.00           N
ATOM      2  CA  SER A   5       2.000   2.000   2.000  1.00 20.00           C
ATOM      3  C   SER A   5       2.500   3.200   2.000  1.00 20.00           C
ATOM      4  O   SER A   5       2.500   4.200   2.000  1.00 20.00           O
ATOM      5  CB  SER A   5       3.500   2.000   2.000  1.00 20.00           C
ATOM      6  OG  SER A   5       8.000   2.000   2.000  1.00 20.00           O
END
"""

_SYNTH_RECEPTOR_PDBQT = """\
ATOM      1  N   SER A   5       1.000   2.000   2.000  1.00 20.00     0.000 N
ATOM      2  CA  SER A   5       2.000   2.000   2.000  1.00 20.00     0.000 C
END
"""

# Synthetic ligand pose PDBQT:
# - Two real heavy atoms at (0, 0, 0) and (4, 2, 6) -> heavy bbox center=(2, 1, 3), span=(4, 2, 6)
# - Far-away hydrogen HD at (50, 50, 50) -> MUST be excluded
# - Far-away Meeko macrocycle dummy glue pseudoatoms G0 and G1 at (-50, -50, -50) -> excluded
_SYNTH_POSE_PDBQT = """\
MODEL 1
REMARK VINA RESULT:      -7.5      0.000      0.000
ROOT
ATOM      1  C1  UNL     1       0.000   0.000   0.000  1.00  0.00    +0.000 C
ATOM      2  O1  UNL     1       4.000   2.000   6.000  1.00  0.00    +0.000 OA
ATOM      3  H1  UNL     1      50.000  50.000  50.000  1.00  0.00    +0.000 HD
ATOM      4  G0  UNL     1     -50.000 -50.000 -50.000  1.00  0.00    +0.000 G0
ATOM      5  G1  UNL     1     -45.000 -45.000 -45.000  1.00  0.00    +0.000 G1
ENDROOT
TORSDOF 0
ENDMDL
"""

_SYNTH_BONDED_POSE_PDBQT = """\
MODEL 1
REMARK VINA RESULT:      -7.5      0.000      0.000
ROOT
ATOM      1  C1  UNL     1       0.000   0.000   0.000  1.00  0.00    +0.000 C
ATOM      2  O1  UNL     1       1.400   0.000   0.000  1.00  0.00    +0.000 OA
ATOM      3  H1  UNL     1      50.000  50.000  50.000  1.00  0.00    +0.000 HD
ATOM      4  G0  UNL     1     -50.000 -50.000 -50.000  1.00  0.00    +0.000 G0
ATOM      5  G1  UNL     1     -45.000 -45.000 -45.000  1.00  0.00    +0.000 G1
ENDROOT
TORSDOF 0
ENDMDL
"""

_SYNTH_CONFORMER_SDF = """\
synth_seed
     RDKit          3D

  2  1  0  0  0  0  0  0  0  0999 V2000
    0.0000    0.0000    0.0000 C   0  0  0  0  0  0  0  0  0  0  0  0
    1.4000    0.0000    0.0000 O   0  0  0  0  0  0  0  0  0  0  0  0
  1  2  1  0
M  END
$$$$
"""


def _seed_project_with_saved_pose(
    data_dir: Path,
    *,
    with_flex_res: bool = False,
    bonded_pose: bool = False,
) -> dict[str, str]:
    now = datetime.now(UTC)
    tool = ToolIdentity(name="synthetic-test", version="0.0.0")

    struct_store = StructureArtifactStore(root=data_dir)
    struct_bytes = _SYNTH_RECEPTOR_PDB.encode("utf-8")
    struct_id = struct_store.new_artifact_id()
    struct_art = StructureArtifact(
        artifact_id=struct_id,
        original_filename="synth_receptor.pdb",
        format=StructureFormat.PDB,
        sha256=sha256(struct_bytes).hexdigest(),
        size_bytes=len(struct_bytes),
        source=StructureSource.LOCAL,
        imported_at=now,
    )
    struct_store.create_artifact(artifact=struct_art, content=struct_bytes)
    struct_store.save_record(
        StructureRecord(
            artifact=struct_art,
            metadata=StructureMetadata(
                model_count=1,
                atom_count=6,
                residue_count=1,
                chains=[
                    ChainSummary(
                        chain_id="A",
                        residue_count=1,
                        polymer_residue_count=1,
                        atom_count=6,
                    )
                ],
                heterogens=[],
                alternate_location_atom_count=0,
                missing_residue_count=0,
                missing_atom_count=0,
                nonstandard_polymer_residues=[],
            ),
            warnings=[],
            provenance=ProvenanceEvent(
                event_id=f"str-{struct_id}",
                event_type="structure_imported",
                timestamp=now,
                input_artifacts=[],
                output_artifacts=[struct_id],
                tool=tool,
                parameters={},
            ),
            content_url=f"/api/v1/structures/{struct_id}/content",
        )
    )

    rec_store = ReceptorArtifactStore(root=data_dir)
    receptor_id = rec_store.new_receptor_id()
    rec_store.create_receptor(receptor_id)
    rec_store.write_bytes(receptor_id, "protonated.pdb", struct_bytes)
    pdb_art_id = f"{receptor_id}-protonated"
    pdb_art = ReceptorOutputArtifact(
        artifact_id=pdb_art_id,
        stage=ReceptorOutputStage.PROTONATED_PDB,
        filename="protonated.pdb",
        format=StructureFormat.PDB,
        sha256=sha256(struct_bytes).hexdigest(),
        size_bytes=len(struct_bytes),
        created_at=now,
        content_url=f"/api/v1/receptors/{receptor_id}/outputs/{pdb_art_id}/content",
    )
    pdbqt_bytes = _SYNTH_RECEPTOR_PDBQT.encode("utf-8")
    docking_stage = (
        ReceptorOutputStage.PDBQT_RIGID if with_flex_res else ReceptorOutputStage.PDBQT
    )
    docking_filename = "receptor_rigid.pdbqt" if with_flex_res else "receptor.pdbqt"
    rec_store.write_bytes(receptor_id, docking_filename, pdbqt_bytes)
    pdbqt_art_id = f"{receptor_id}-pdbqt"
    pdbqt_art = ReceptorOutputArtifact(
        artifact_id=pdbqt_art_id,
        stage=docking_stage,
        filename=docking_filename,
        format="pdbqt",
        sha256=sha256(pdbqt_bytes).hexdigest(),
        size_bytes=len(pdbqt_bytes),
        created_at=now,
        content_url=f"/api/v1/receptors/{receptor_id}/outputs/{pdbqt_art_id}/content",
    )
    outputs: list[ReceptorOutputArtifact] = [pdb_art, pdbqt_art]
    flex_spec: ReceptorFlexSpec | None = None
    if with_flex_res:
        flex_bytes = b"BEGIN_RES SER A   5\nEND_RES SER A   5\n"
        rec_store.write_bytes(receptor_id, "receptor_flex.pdbqt", flex_bytes)
        flex_art_id = f"{receptor_id}-flex"
        flex_art = ReceptorOutputArtifact(
            artifact_id=flex_art_id,
            stage=ReceptorOutputStage.PDBQT_FLEX,
            filename="receptor_flex.pdbqt",
            format="pdbqt",
            sha256=sha256(flex_bytes).hexdigest(),
            size_bytes=len(flex_bytes),
            created_at=now,
            content_url=f"/api/v1/receptors/{receptor_id}/outputs/{flex_art_id}/content",
        )
        outputs.append(flex_art)
        flex_spec = ReceptorFlexSpec(
            mode=ReceptorFlexMode.SIDECHAIN_FLEX,
            flex_residues=(
                ResidueLocator(chain_id="A", residue_name="SER", sequence_number=5),
            ),
            receptor_rigid_sha256=pdbqt_art.sha256,
            receptor_flex_sha256=flex_art.sha256,
        )

    rec_record = ReceptorPreparationRecord(
        receptor_id=receptor_id,
        source_artifact_id=struct_art.artifact_id,
        status=ReceptorPreparationStatus.DOCKING_READY,
        created_at=now,
        decisions=ReceptorPreparationRequest(
            selected_chains=["A"],
            water_action=ComponentAction.REMOVE,
            component_decisions=[],
            issue_decisions=[],
        ),
        outputs=outputs,
        display_output_artifact_id=pdb_art.artifact_id,
        warnings=[],
        provenance=[
            ProvenanceEvent(
                event_id=f"rec-{receptor_id}",
                event_type="receptor_prepared",
                timestamp=now,
                input_artifacts=[struct_art.artifact_id],
                output_artifacts=[receptor_id],
                tool=tool,
                parameters={},
            )
        ],
        flex_spec=flex_spec,
    )
    rec_store.save_record(rec_record)

    site_store = BindingSiteArtifactStore(root=data_dir)
    parent_site_id = site_store.new_binding_site_id()
    parent_box = BindingBox(
        center_x=2.0, center_y=2.0, center_z=2.0, size_x=30.0, size_y=30.0, size_z=30.0
    )
    site_store.save_record(
        BindingSiteRecord(
            binding_site_id=parent_site_id,
            receptor_id=receptor_id,
            source_artifact_id=struct_art.artifact_id,
            created_at=now,
            decisions=BindingSiteRequest(
                source=BindingSiteSource.MANUAL,
                manual_box=parent_box,
            ),
            box=parent_box,
            stale=False,
            warnings=[],
            provenance=[
                ProvenanceEvent(
                    event_id=f"site-{parent_site_id}",
                    event_type="binding_site_defined",
                    timestamp=now,
                    input_artifacts=[struct_art.artifact_id, receptor_id],
                    output_artifacts=[parent_site_id],
                    tool=tool,
                    parameters={},
                )
            ],
        )
    )

    lig_store = LigandArtifactStore(root=data_dir)
    ligand_id = lig_store.new_ligand_id()
    sdf_bytes = _SYNTH_CONFORMER_SDF.encode("utf-8")
    lig_art = LigandArtifact(
        ligand_id=ligand_id,
        source=LigandSource.LOCAL,
        filename="synth_seed.sdf",
        format=LigandFormat.SDF,
        sha256=sha256(sdf_bytes).hexdigest(),
        size_bytes=len(sdf_bytes),
        created_at=now,
    )
    inspection = LigandInspection(
        name="synth_seed",
        formula="CH4O",
        molecular_weight_g_mol=32.04,
        exact_mass_da=32.0262,
        formal_charge=0,
        atom_count=2,
        heavy_atom_count=2,
        rotatable_bond_count=0,
        aromatic_ring_count=0,
        stereocenter_count=0,
        conformer_count=1,
        has_3d_coordinates=True,
        canonical_smiles="CO",
    )
    lig_store.create(
        ligand_id,
        sdf_bytes,
        LigandRecord(
            artifact=lig_art,
            inspection=inspection,
            warnings=[],
            provenance=ProvenanceEvent(
                event_id=f"lig-{ligand_id}",
                event_type="ligand_imported",
                timestamp=now,
                input_artifacts=[],
                output_artifacts=[ligand_id],
                tool=tool,
                parameters={},
            ),
            content_url=f"/api/v1/ligands/{ligand_id}/content",
        ),
    )
    conf_id = lig_store.new_conformer_id()
    lig_store.create_conformer(
        ligand_id,
        conf_id,
        sdf_bytes,
        LigandConformerRecord(
            artifact=LigandConformerArtifact(
                conformer_id=conf_id,
                ligand_id=ligand_id,
                stage="generated_minimized",
                filename="conf.sdf",
                format="sdf",
                sha256=sha256(sdf_bytes).hexdigest(),
                size_bytes=len(sdf_bytes),
                created_at=now,
            ),
            inspection=inspection,
            minimization=LigandMinimizationResult(
                force_field=LigandForceField.MMFF94S,
                max_iterations=200,
                converged=True,
                initial_energy_kcal_mol=2.0,
                final_energy_kcal_mol=1.0,
                random_seed=42,
                independent_from_source_coordinates=True,
            ),
            warnings=[],
            provenance=ProvenanceEvent(
                event_id=f"conf-{conf_id}",
                event_type="ligand_conformer_generated",
                timestamp=now,
                input_artifacts=[ligand_id],
                output_artifacts=[conf_id],
                tool=tool,
                parameters={},
            ),
            content_url=f"/api/v1/ligands/{ligand_id}/conformers/{conf_id}/content",
        ),
    )
    prep_id = lig_store.new_preparation_id()
    pose_bytes = (_SYNTH_BONDED_POSE_PDBQT if bonded_pose else _SYNTH_POSE_PDBQT).encode("utf-8")
    lig_store.create_pdbqt(
        ligand_id,
        prep_id,
        pose_bytes,
        LigandPdbqtRecord(
            artifact=LigandPdbqtArtifact(
                preparation_id=prep_id,
                ligand_id=ligand_id,
                conformer_id=conf_id,
                filename="prep.pdbqt",
                format="pdbqt",
                sha256=sha256(pose_bytes).hexdigest(),
                size_bytes=len(pose_bytes),
                created_at=now,
            ),
            charge_model=LigandChargeModel.GASTEIGER,
            tool=tool,
            command=["mk_prepare_ligand"],
            stdout="",
            stderr="",
            provenance=ProvenanceEvent(
                event_id=f"prep-{prep_id}",
                event_type="ligand_prepared",
                timestamp=now,
                input_artifacts=[conf_id],
                output_artifacts=[prep_id],
                tool=tool,
                parameters={},
            ),
            content_url=f"/api/v1/ligands/{ligand_id}/preparations/{prep_id}/content",
        ),
    )

    dock_store = DockingArtifactStore(root=data_dir)
    job_id = dock_store.new_job_id()
    pose_artifact_id = f"{job_id}-pose-1"
    pose_sha = sha256(pose_bytes).hexdigest()
    pose_art = DockingPoseArtifact(
        artifact_id=pose_artifact_id,
        mode=1,
        filename="pose_01.pdbqt",
        format="pdbqt",
        sha256=pose_sha,
        size_bytes=len(pose_bytes),
        content_url=f"/api/v1/docking/vina/{job_id}/poses/{pose_artifact_id}/content",
    )
    dock_record = VinaDockingJobRecord(
        job_id=job_id,
        engine=DockingEngine.AUTODOCK_VINA,
        status=DockingJobStatus.COMPLETED,
        phase=DockingJobPhase.COMPLETE,
        created_at=now,
        started_at=now,
        completed_at=now,
        request=VinaDockingRequest(
            receptor_id=receptor_id,
            binding_site_id=parent_site_id,
            ligand_id=ligand_id,
            ligand_preparation_id=prep_id,
            parameters=VinaDockingParameters(exhaustiveness=8, num_modes=1, seed=42),
            acknowledge_inputs_and_scoring=True,
        ),
        tool=tool,
        receptor_output_artifact_id=pdbqt_art.artifact_id,
        receptor_sha256=pdbqt_art.sha256,
        receptor_flex_mode=(
            ReceptorFlexMode.SIDECHAIN_FLEX if with_flex_res else ReceptorFlexMode.RIGID
        ),
        flex_residues=(
            [ResidueLocator(chain_id="A", residue_name="SER", sequence_number=5)]
            if with_flex_res
            else []
        ),
        ligand_sha256=pose_sha,
        command=["vina"],
        execution=DockingExecutionEvidence(
            command=["vina"],
            exit_code=0,
            stdout="",
            stderr="",
        ),
        poses=[
            DockingPoseResult(
                mode=1,
                affinity_kcal_mol=-7.5,
                rmsd_lower_bound_angstrom=0.0,
                rmsd_upper_bound_angstrom=0.0,
                artifact=pose_art,
            )
        ],
        warnings=[],
        provenance=ProvenanceEvent(
            event_id=f"dock-{job_id}",
            event_type="vina_docking_completed",
            timestamp=now,
            input_artifacts=[receptor_id, prep_id, parent_site_id],
            output_artifacts=[job_id, pose_artifact_id],
            tool=tool,
            parameters={},
        ),
    )
    dock_store.create_job(dock_record)
    dock_store.write_bytes(job_id, "pose_01.pdbqt", pose_bytes)

    return {
        "receptor_id": receptor_id,
        "parent_site_id": parent_site_id,
        "ligand_id": ligand_id,
        "job_id": job_id,
        "catalog_id": f"{VINA_JOB}:{job_id}",
        "pose_artifact_id": pose_artifact_id,
        "pose_sha256": pose_sha,
    }


def test_pose_focused_site_heavy_atom_box_and_stale_propagation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-033 §3: exact heavy-atom geometry, parent immutability, ADR-018 warning, stale DAG."""
    data_dir = tmp_path / "ankora_data"
    monkeypatch.setenv("ANKORA_DATA_DIR", str(data_dir))
    seeded = _seed_project_with_saved_pose(data_dir, with_flex_res=False)
    app = create_app()

    with TestClient(app) as client:
        # 1. Preview POSE_FOCUSED site with padding = 5.0 A
        preview_resp = client.post(
            f"/api/v1/receptors/{seeded['receptor_id']}/binding-site-preview",
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
        assert preview_resp.status_code == 200, preview_resp.text
        preview = BindingSitePreview.model_validate(preview_resp.json())
        # Heavy atoms (0,0,0) and (4,2,6) -> center=(2,1,3), size=(14,12,16)
        assert preview.box.center_x == pytest.approx(2.0, abs=1e-6)
        assert preview.box.center_y == pytest.approx(1.0, abs=1e-6)
        assert preview.box.center_z == pytest.approx(3.0, abs=1e-6)
        assert preview.box.size_x == pytest.approx(14.0, abs=1e-6)
        assert preview.box.size_y == pytest.approx(12.0, abs=1e-6)
        assert preview.box.size_z == pytest.approx(16.0, abs=1e-6)
        assert preview.pose_focused_evidence is not None
        assert preview.pose_focused_evidence.heavy_atom_count == 2
        assert preview.pose_focused_evidence.excluded_hydrogen_count == 1
        assert preview.pose_focused_evidence.excluded_pseudoatom_count == 2
        assert preview.pose_focused_evidence.pose_sha256 == seeded["pose_sha256"]
        assert preview.warnings == []

        # 2. Persist immutable POSE_FOCUSED record with large box override (> 27,000 A^3 -> ADR-018)
        large_override = {
            "center_x": 2.0,
            "center_y": 1.0,
            "center_z": 3.0,
            "size_x": 32.0,
            "size_y": 32.0,
            "size_z": 32.0,
        }
        create_resp = client.post(
            f"/api/v1/receptors/{seeded['receptor_id']}/binding-sites",
            json={
                "source": "pose_focused",
                "parent_binding_site_id": seeded["parent_site_id"],
                "pose_focused": {
                    "source_catalog_id": seeded["catalog_id"],
                    "ligand_id": seeded["ligand_id"],
                    "pose_artifact_id": seeded["pose_artifact_id"],
                    "padding_angstrom": 5.0,
                    "box_override": large_override,
                },
            },
        )
        assert create_resp.status_code == 201, create_resp.text
        created = BindingSiteRecord.model_validate(create_resp.json())
        assert created.decisions.source is BindingSiteSource.POSE_FOCUSED
        assert created.box.size_x == pytest.approx(32.0)
        assert created.pose_focused_evidence is not None
        assert created.pose_focused_evidence.box_overridden is True
        assert created.pose_focused_evidence.computed_base_box.size_x == pytest.approx(14.0)
        assert any(w.code is WarningCode.DOCKING_SEARCH_SPACE_LARGE for w in created.warnings)

        # Parent site remains completely intact
        parent_get = client.get(f"/api/v1/binding-sites/{seeded['parent_site_id']}")
        assert parent_get.status_code == 200
        assert parent_get.json()["box"]["size_x"] == pytest.approx(30.0)

        # 3. Stale source docking job propagates to derived POSE_FOCUSED site & blocks new ones
        deps = ProjectDependencyService(root=data_dir)
        marked = deps.mark_stale(seeded["job_id"], "Source wide campaign superseded")
        assert created.binding_site_id in marked.affected_node_ids

        stale_resp = client.post(
            f"/api/v1/receptors/{seeded['receptor_id']}/binding-sites",
            json={
                "source": "pose_focused",
                "pose_focused": {
                    "source_catalog_id": seeded["catalog_id"],
                    "ligand_id": seeded["ligand_id"],
                    "pose_artifact_id": seeded["pose_artifact_id"],
                    "padding_angstrom": 5.0,
                },
            },
        )
        assert stale_resp.status_code == 409
        assert stale_resp.json()["code"] == "PROJECT_INPUT_STALE"


def test_pose_focused_site_enforces_full_atom_flexres_containment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-033 §3: FlexRes side-chain atom (OG at x=8) outside box fails closed (not CA-only)."""
    data_dir = tmp_path / "ankora_data"
    monkeypatch.setenv("ANKORA_DATA_DIR", str(data_dir))
    seeded = _seed_project_with_saved_pose(data_dir, with_flex_res=True)
    app = create_app()

    with TestClient(app) as client:
        # With padding=4.0: center_x=2.0, size_x=12.0 -> half=6.0 -> x in [-4, 8].
        # SER A:5 CA is at x=2 (inside!), but mobile side-chain atom OG is at x=8.0,
        # which violates interior margin 1.5 A (max_x = 8.0 - 1.5 = 6.5 < 8.0)!
        fail_resp = client.post(
            f"/api/v1/receptors/{seeded['receptor_id']}/binding-sites",
            json={
                "source": "pose_focused",
                "pose_focused": {
                    "source_catalog_id": seeded["catalog_id"],
                    "ligand_id": seeded["ligand_id"],
                    "pose_artifact_id": seeded["pose_artifact_id"],
                    "padding_angstrom": 4.0,
                    "flex_containment_margin_angstrom": 1.5,
                },
            },
        )
        assert fail_resp.status_code == 422, fail_resp.text
        err = fail_resp.json()
        assert err["code"] == "BINDING_SITE_FLEXRES_OUTSIDE_BOX"
        offending_atoms = [item["atom_name"] for item in err["details"]["offending_atoms"]]
        assert "OG" in offending_atoms
        assert err["details"]["recommended_min_size"]["size_x"] >= 15.0

        # Expanding padding to 6.0 -> center_x=2, size_x=16 -> x in [-6, 10], interior [-4.5, 8.5]
        # -> OG at x=8.0 is strictly inside with >= 1.5 A margin!
        ok_resp = client.post(
            f"/api/v1/receptors/{seeded['receptor_id']}/binding-sites",
            json={
                "source": "pose_focused",
                "pose_focused": {
                    "source_catalog_id": seeded["catalog_id"],
                    "ligand_id": seeded["ligand_id"],
                    "pose_artifact_id": seeded["pose_artifact_id"],
                    "padding_angstrom": 6.0,
                    "flex_containment_margin_angstrom": 1.5,
                },
            },
        )
        assert ok_resp.status_code == 201, ok_resp.text
        ok_rec = BindingSiteRecord.model_validate(ok_resp.json())
        assert ok_rec.pose_focused_evidence is not None
        assert ok_rec.pose_focused_evidence.flex_containment_checked is True
