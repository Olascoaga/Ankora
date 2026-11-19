"""End-to-end service, HTTP API, MethodsReport, and E8 coupled-complex tests for M3b.

All receptors, ligands, and poses in this module are synthetic and explicitly
labelled synthetic. Tests run live PoseBusters 0.6.5 and RDKit MMFF94s.
"""

from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256
from importlib import import_module
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from ankora_backend.api.app import create_app
from ankora_backend.persistence.binding_site_store import BindingSiteArtifactStore
from ankora_backend.persistence.docking_store import DockingArtifactStore
from ankora_backend.persistence.ligand_store import LigandArtifactStore
from ankora_backend.persistence.receptor_store import ReceptorArtifactStore
from ankora_backend.schemas.binding_sites import (
    BindingBox,
    BindingSiteRecord,
    BindingSiteRequest,
    BindingSiteSource,
)
from ankora_backend.schemas.docking import (
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
from ankora_backend.schemas.pose_quality import PoseQualityRecord
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
from ankora_backend.schemas.v02_contracts import DiagnosticStatus, PoseComplexIdentity
from ankora_backend.services.methods_report import render_pose_quality_methods
from ankora_backend.services.project_dependencies import ProjectDependencyService

Chem: Any = import_module("rdkit.Chem")
AllChem: Any = import_module("rdkit.Chem.AllChem")
meeko: Any = import_module("meeko")

_BOX = BindingBox(
    center_x=0.0,
    center_y=0.0,
    center_z=0.0,
    size_x=20.0,
    size_y=20.0,
    size_z=20.0,
)

# Synthetic MET A:5 crystal receptor (side chain points in +Y away from ligand in -Y)
_SYNTHETIC_CRYSTAL_PDB = (
    "ATOM      1  N   MET A   5      -0.500  -1.350   0.250  1.00  0.00           N  \n"
    "ATOM      2  CA  MET A   5       0.000   0.000   0.000  1.00  0.00           C  \n"
    "ATOM      3  C   MET A   5      -0.550   0.500  -1.320  1.00  0.00           C  \n"
    "ATOM      4  O   MET A   5      -0.100   1.550  -1.780  1.00  0.00           O  \n"
    "ATOM      5  HA  MET A   5      -0.350   0.650   0.780  1.00  0.00           H  \n"
    "ATOM      6  CB  MET A   5       1.530   0.000   0.000  1.00  0.00           C  \n"
    "ATOM      7  CG  MET A   5       2.040   1.440   0.000  1.00  0.00           C  \n"
    "ATOM      8  SD  MET A   5       3.850   1.440   0.000  1.00  0.00           S  \n"
    "ATOM      9  CE  MET A   5       4.200   3.190   0.250  1.00  0.00           C  \n"
    "ATOM     10  HB2 MET A   5       1.894  -0.514   0.890  1.00  0.00           H  \n"
    "ATOM     11  HB3 MET A   5       1.894  -0.514  -0.890  1.00  0.00           H  \n"
    "ATOM     12  HG2 MET A   5       1.676   1.954   0.890  1.00  0.00           H  \n"
    "ATOM     13  HG3 MET A   5       1.676   1.954  -0.890  1.00  0.00           H  \n"
    "ATOM     14  HE1 MET A   5       5.280   3.310   0.250  1.00  0.00           H  \n"
    "ATOM     15  HE2 MET A   5       3.780   3.620   1.158  1.00  0.00           H  \n"
    "ATOM     16  HE3 MET A   5       3.780   3.620  -0.658  1.00  0.00           H  \n"
    "END\n"
)

_SYNTHETIC_RIGID_PDBQT = (
    "ATOM      1  N   MET A   5      -0.500  -1.350   0.250  1.00  0.00     0.000 N \n"
    "ATOM      2  C   MET A   5      -0.550   0.500  -1.320  1.00  0.00     0.000 C \n"
    "ATOM      3  O   MET A   5      -0.100   1.550  -1.780  1.00  0.00     0.000 OA\n"
)

# Pose 1 moved MET A:5 (clear of ligand, rotated slightly in +Y/+Z preserving exact bond lengths)
_SYNTHETIC_FLEX_CLEAR_PDBQT = (
    "BEGIN_RES MET A 5\n"
    "ROOT\n"
    "ATOM      1  CA  MET A   5       0.000   0.000   0.000  1.00  0.00     0.000 C \n"
    "ENDROOT\n"
    "BRANCH   1   2\n"
    "ATOM      2  CB  MET A   5       1.530   0.000   0.000  1.00  0.00     0.000 C \n"
    "BRANCH   2   3\n"
    "ATOM      3  CG  MET A   5       2.040   1.440   0.000  1.00  0.00     0.000 C \n"
    "BRANCH   3   4\n"
    "ATOM      4  SD  MET A   5       3.850   1.440   0.000  1.00  0.00     0.000 SA\n"
    "ATOM      5  CE  MET A   5       4.200   3.190   0.250  1.00  0.00     0.000 C \n"
    "ENDBRANCH   3   4\n"
    "ENDBRANCH   2   3\n"
    "ENDBRANCH   1   2\n"
    "END_RES MET A 5\n"
)

# Pose 2 moved MET A:5 rotated 180 deg around CA-CB into -Y so CG/SD/CE sit at (-Y),
# colliding right on top of the ligand centered around (3.85, -1.8, 0.0) while crystal
# MET A:5 in +Y was > 5 A away!
_SYNTHETIC_FLEX_CLASH_PDBQT = (
    "BEGIN_RES MET A 5\n"
    "ROOT\n"
    "ATOM      1  CA  MET A   5       0.000   0.000   0.000  1.00  0.00     0.000 C \n"
    "ENDROOT\n"
    "BRANCH   1   2\n"
    "ATOM      2  CB  MET A   5       1.530   0.000   0.000  1.00  0.00     0.000 C \n"
    "BRANCH   2   3\n"
    "ATOM      3  CG  MET A   5       2.040  -1.440   0.000  1.00  0.00     0.000 C \n"
    "BRANCH   3   4\n"
    "ATOM      4  SD  MET A   5       3.850  -1.440   0.000  1.00  0.00     0.000 SA\n"
    "ATOM      5  CE  MET A   5       4.200  -3.190  -0.250  1.00  0.00     0.000 C \n"
    "ENDBRANCH   3   4\n"
    "ENDBRANCH   2   3\n"
    "ENDBRANCH   1   2\n"
    "END_RES MET A 5\n"
)


def _sha(data: bytes) -> str:
    return sha256(data).hexdigest()


def _build_synthetic_ethanol_at(dx: float, dy: float, dz: float) -> tuple[bytes, bytes]:
    """Create a real minimized ethanol SDF + Meeko PDBQT translated to `(dx, dy, dz)`."""
    mol = Chem.AddHs(Chem.MolFromSmiles("CCO"))
    params = AllChem.ETKDGv3()
    params.randomSeed = 20261119
    params.numThreads = 1
    assert AllChem.EmbedMolecule(mol, params) == 0
    assert AllChem.MMFFOptimizeMolecule(mol, mmffVariant="MMFF94s") == 0

    conf = mol.GetConformer()
    # Center heavy-atom centroid at (dx, dy, dz) so no ethanol atom drifts near backbone.
    heavy_indices = [a.GetIdx() for a in mol.GetAtoms() if a.GetAtomicNum() > 1]
    cx = sum(conf.GetAtomPosition(i).x for i in heavy_indices) / len(heavy_indices)
    cy = sum(conf.GetAtomPosition(i).y for i in heavy_indices) / len(heavy_indices)
    cz = sum(conf.GetAtomPosition(i).z for i in heavy_indices) / len(heavy_indices)
    shift_x, shift_y, shift_z = dx - cx, dy - cy, dz - cz
    for idx in range(mol.GetNumAtoms()):
        pt = conf.GetAtomPosition(idx)
        conf.SetAtomPosition(idx, (pt.x + shift_x, pt.y + shift_y, pt.z + shift_z))

    sdf_bytes = (Chem.MolToMolBlock(mol) + "\n$$$$\n").encode("utf-8")
    prep = meeko.MoleculePreparation()
    setups = prep.prepare(mol)
    pdbqt_str, is_ok, err = meeko.PDBQTWriterLegacy.write_string(setups[0])
    assert is_ok, err
    return sdf_bytes, pdbqt_str.encode("utf-8")


def _seed_coupled_flex_vina_job(tmp_path: Path) -> dict[str, str]:
    now = datetime.now(UTC)
    receptors = ReceptorArtifactStore.from_environment()
    sites = BindingSiteArtifactStore.from_environment()
    ligands = LigandArtifactStore.from_environment()
    docking = DockingArtifactStore.from_environment()

    rec_id = receptors.new_receptor_id()
    receptors.create_receptor(rec_id)
    prot_bytes = _SYNTHETIC_CRYSTAL_PDB.encode("utf-8")
    rigid_bytes = _SYNTHETIC_RIGID_PDBQT.encode("utf-8")
    flex_init_bytes = _SYNTHETIC_FLEX_CLEAR_PDBQT.encode("utf-8")
    prot_art_id = "art-prot-pdb"
    rigid_art_id = "art-rigid-pdbqt"
    flex_art_id = "art-flex-pdbqt"
    receptors.write_bytes(rec_id, "protonated.pdb", prot_bytes)
    receptors.write_bytes(rec_id, "receptor_rigid.pdbqt", rigid_bytes)
    receptors.write_bytes(rec_id, "receptor_flex.pdbqt", flex_init_bytes)

    flex_res = ResidueLocator(chain_id="A", residue_name="MET", sequence_number=5)
    receptors.save_record(
        ReceptorPreparationRecord(
            receptor_id=rec_id,
            source_artifact_id="src-synth-met",
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
                    flex_residues=[flex_res],
                ),
            ),
            outputs=[
                ReceptorOutputArtifact(
                    artifact_id=prot_art_id,
                    stage=ReceptorOutputStage.PROTONATED_PDB,
                    filename="protonated.pdb",
                    format="pdb",
                    sha256=_sha(prot_bytes),
                    size_bytes=len(prot_bytes),
                    created_at=now,
                    content_url=f"/receptors/{rec_id}/outputs/{prot_art_id}/content",
                ),
                ReceptorOutputArtifact(
                    artifact_id=rigid_art_id,
                    stage=ReceptorOutputStage.PDBQT_RIGID,
                    filename="receptor_rigid.pdbqt",
                    format="pdbqt",
                    sha256=_sha(rigid_bytes),
                    size_bytes=len(rigid_bytes),
                    created_at=now,
                    content_url=f"/receptors/{rec_id}/outputs/{rigid_art_id}/content",
                ),
                ReceptorOutputArtifact(
                    artifact_id=flex_art_id,
                    stage=ReceptorOutputStage.PDBQT_FLEX,
                    filename="receptor_flex.pdbqt",
                    format="pdbqt",
                    sha256=_sha(flex_init_bytes),
                    size_bytes=len(flex_init_bytes),
                    created_at=now,
                    content_url=f"/receptors/{rec_id}/outputs/{flex_art_id}/content",
                ),
            ],
            warnings=[],
            provenance=[],
            display_output_artifact_id=prot_art_id,
            flex_spec=ReceptorFlexSpec(
                mode=ReceptorFlexMode.SIDECHAIN_FLEX,
                flex_residues=(flex_res,),
                receptor_rigid_sha256=_sha(rigid_bytes),
                receptor_flex_sha256=_sha(flex_init_bytes),
                added_chi_torsion_count=3,
            ),
            flex_atom_types=["C", "SA"],
        )
    )

    site_id = sites.new_binding_site_id()
    sites.save_record(
        BindingSiteRecord(
            binding_site_id=site_id,
            receptor_id=rec_id,
            source_artifact_id="src-synth-met",
            created_at=now,
            box=_BOX,
            decisions=BindingSiteRequest(source=BindingSiteSource.MANUAL, manual_box=_BOX),
            warnings=[],
            provenance=[
                ProvenanceEvent(
                    event_id="evt-site",
                    event_type="binding_site_confirmed",
                    timestamp=now,
                    input_artifacts=[rec_id],
                    output_artifacts=[site_id],
                    tool=ToolIdentity(name="Ankora", version="0.2.0-dev"),
                )
            ],
        )
    )

    # Place ethanol centroid at (4.20, -3.19, -0.25):
    # - ~4.15 A from crystal MET A:5 CB (1.53, 0, 0) (inside 5 A window, clear of clashes)
    #   -> Pose 1 (clear flex) PASSES
    # - Directly overlapping Pose 2 moved MET A:5 CE (4.20, -3.19, -0.25)
    #   -> Pose 2 (clash flex) FAILS!
    sdf_bytes, pose_pdbqt_bytes = _build_synthetic_ethanol_at(4.20, -3.19, -0.25)
    lig_id = ligands.new_ligand_id()
    inspection = LigandInspection(
        name="SYNTH_ETHANOL",
        formula="C2H6O",
        formal_charge=0,
        atom_count=9,
        heavy_atom_count=3,
        rotatable_bond_count=0,
        aromatic_ring_count=0,
        stereocenter_count=0,
        conformer_count=1,
        has_3d_coordinates=True,
        canonical_smiles="CCO",
    )
    ligands.create(
        lig_id,
        sdf_bytes,
        LigandRecord(
            artifact=LigandArtifact(
                ligand_id=lig_id,
                source=LigandSource.LOCAL,
                filename="synth_ethanol.sdf",
                format=LigandFormat.SDF,
                sha256=_sha(sdf_bytes),
                size_bytes=len(sdf_bytes),
                created_at=now,
            ),
            inspection=inspection,
            warnings=[],
            provenance=ProvenanceEvent(
                event_id="evt-lig",
                event_type="ligand_imported",
                timestamp=now,
                input_artifacts=[],
                output_artifacts=[lig_id],
                tool=ToolIdentity(name="RDKit", version="2025.9.6"),
            ),
            content_url=f"/ligands/{lig_id}/content",
        ),
    )
    conf_id = ligands.new_conformer_id()
    ligands.create_conformer(
        lig_id,
        conf_id,
        sdf_bytes,
        LigandConformerRecord(
            artifact=LigandConformerArtifact(
                conformer_id=conf_id,
                ligand_id=lig_id,
                stage="minimized",
                filename="conformer.sdf",
                format="sdf",
                sha256=_sha(sdf_bytes),
                size_bytes=len(sdf_bytes),
                created_at=now,
            ),
            inspection=inspection,
            minimization=LigandMinimizationResult(
                force_field=LigandForceField.MMFF94S,
                max_iterations=500,
                converged=True,
                initial_energy_kcal_mol=1.0,
                final_energy_kcal_mol=0.5,
            ),
            warnings=[],
            provenance=ProvenanceEvent(
                event_id="evt-conf",
                event_type="ligand_minimized",
                timestamp=now,
                input_artifacts=[lig_id],
                output_artifacts=[conf_id],
                tool=ToolIdentity(name="RDKit", version="2025.9.6"),
            ),
            content_url=f"/ligands/{lig_id}/conformers/{conf_id}/content",
        ),
    )
    prep_id = ligands.new_preparation_id()
    ligands.create_pdbqt(
        lig_id,
        prep_id,
        pose_pdbqt_bytes,
        LigandPdbqtRecord(
            artifact=LigandPdbqtArtifact(
                preparation_id=prep_id,
                ligand_id=lig_id,
                conformer_id=conf_id,
                filename="synth_ethanol.pdbqt",
                format="pdbqt",
                sha256=_sha(pose_pdbqt_bytes),
                size_bytes=len(pose_pdbqt_bytes),
                created_at=now,
            ),
            charge_model=LigandChargeModel.GASTEIGER,
            tool=ToolIdentity(name="Meeko", version="0.7.1"),
            command=["mk_prepare_ligand"],
            stdout="",
            stderr="",
            provenance=ProvenanceEvent(
                event_id="evt-prep",
                event_type="ligand_pdbqt_prepared",
                timestamp=now,
                input_artifacts=[conf_id],
                output_artifacts=[prep_id],
                tool=ToolIdentity(name="Meeko", version="0.7.1"),
            ),
            content_url=f"/ligands/{lig_id}/pdbqt/{prep_id}/content",
        ),
    )

    job_id = docking.new_job_id()
    pose1_id = "pose-clear-1"
    pose2_id = "pose-clash-2"
    flex_clear_bytes = _SYNTHETIC_FLEX_CLEAR_PDBQT.encode("utf-8")
    flex_clash_bytes = _SYNTHETIC_FLEX_CLASH_PDBQT.encode("utf-8")

    complex1 = PoseComplexIdentity(
        mode=ReceptorFlexMode.SIDECHAIN_FLEX,
        receptor_rigid_sha256=_sha(rigid_bytes),
        pose_flex_sidechains_sha256=_sha(flex_clear_bytes),
        ligand_pose_sha256=_sha(pose_pdbqt_bytes),
    ).complex_identity_sha256
    complex2 = PoseComplexIdentity(
        mode=ReceptorFlexMode.SIDECHAIN_FLEX,
        receptor_rigid_sha256=_sha(rigid_bytes),
        pose_flex_sidechains_sha256=_sha(flex_clash_bytes),
        ligand_pose_sha256=_sha(pose_pdbqt_bytes),
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
                ligand_id=lig_id,
                ligand_preparation_id=prep_id,
                parameters=VinaDockingParameters(),
                acknowledge_inputs_and_scoring=True,
            ),
            tool=ToolIdentity(name="AutoDock Vina", version="1.2.7"),
            receptor_output_artifact_id=rigid_art_id,
            receptor_sha256=_sha(rigid_bytes),
            receptor_flex_mode=ReceptorFlexMode.SIDECHAIN_FLEX,
            receptor_flex_output_artifact_id=flex_art_id,
            receptor_flex_sha256=_sha(flex_init_bytes),
            flex_residues=[flex_res],
            ligand_sha256=_sha(pose_pdbqt_bytes),
            poses=[
                DockingPoseResult(
                    mode=1,
                    affinity_kcal_mol=-3.4,
                    rmsd_lower_bound_angstrom=0.0,
                    rmsd_upper_bound_angstrom=0.0,
                    artifact=DockingPoseArtifact(
                        artifact_id=pose1_id,
                        mode=1,
                        filename="pose_1.pdbqt",
                        format="pdbqt",
                        sha256=_sha(pose_pdbqt_bytes),
                        size_bytes=len(pose_pdbqt_bytes),
                        content_url=f"/docking/vina/jobs/{job_id}/poses/{pose1_id}/content",
                        flex_filename="pose_1_flex.pdbqt",
                        pose_flex_sidechains_sha256=_sha(flex_clear_bytes),
                        flex_content_url=f"/docking/vina/jobs/{job_id}/poses/{pose1_id}/flex",
                        pose_complex_identity_sha256=complex1,
                    ),
                ),
                DockingPoseResult(
                    mode=2,
                    affinity_kcal_mol=-3.1,
                    rmsd_lower_bound_angstrom=0.0,
                    rmsd_upper_bound_angstrom=0.0,
                    artifact=DockingPoseArtifact(
                        artifact_id=pose2_id,
                        mode=2,
                        filename="pose_2.pdbqt",
                        format="pdbqt",
                        sha256=_sha(pose_pdbqt_bytes),
                        size_bytes=len(pose_pdbqt_bytes),
                        content_url=f"/docking/vina/jobs/{job_id}/poses/{pose2_id}/content",
                        flex_filename="pose_2_flex.pdbqt",
                        pose_flex_sidechains_sha256=_sha(flex_clash_bytes),
                        flex_content_url=f"/docking/vina/jobs/{job_id}/poses/{pose2_id}/flex",
                        pose_complex_identity_sha256=complex2,
                    ),
                ),
            ],
        )
    )
    docking.write_bytes(job_id, "pose_1.pdbqt", pose_pdbqt_bytes)
    docking.write_bytes(job_id, "pose_1_flex.pdbqt", flex_clear_bytes)
    docking.write_bytes(job_id, "pose_2.pdbqt", pose_pdbqt_bytes)
    docking.write_bytes(job_id, "pose_2_flex.pdbqt", flex_clash_bytes)

    return {
        "receptor_id": rec_id,
        "ligand_id": lig_id,
        "job_id": job_id,
        "pose1_id": pose1_id,
        "pose2_id": pose2_id,
        "pose_sha": _sha(pose_pdbqt_bytes),
    }


def test_pose_quality_http_api_coupled_flex_clash_persistence_methods_and_stale(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ANKORA_DATA_DIR", str(tmp_path))
    app = create_app()
    ids = _seed_coupled_flex_vina_job(tmp_path)

    base1 = (
        f"/api/v1/results/campaigns/vina_job/{ids['job_id']}"
        f"/compounds/{ids['ligand_id']}/poses/{ids['pose1_id']}/quality"
    )
    base2 = (
        f"/api/v1/results/campaigns/vina_job/{ids['job_id']}"
        f"/compounds/{ids['ligand_id']}/poses/{ids['pose2_id']}/quality"
    )

    with TestClient(app) as client:
        # Initially empty history
        assert client.get(base1).json() == []

        # 1. Pose 1 (clear coupled FlexRes side chain) -> PASS + MMFF94s strain attached
        resp1 = client.post(
            base1,
            json={"include_strain": True, "conformer_seed": 20261119, "conformer_budget": 10},
        )
        assert resp1.status_code == 201, resp1.text
        rec1 = PoseQualityRecord.model_validate(resp1.json())
        assert rec1.posebusters_version == "0.6.5"
        assert rec1.assessment.mutated_original_pose is False
        assert rec1.materialized_coupled_receptor_sha256 is not None
        assert rec1.assessment.strain is not None
        assert rec1.assessment.overall_status is DiagnosticStatus.PASS
        checks1 = {c.check_id: c for c in rec1.assessment.checks}
        assert checks1["pb_minimum_distance_to_protein"].status is DiagnosticStatus.PASS
        assert checks1["flex_sidechain_bond_lengths"].status is DiagnosticStatus.PASS
        assert checks1["flex_sidechain_chirality"].status is DiagnosticStatus.PASS
        assert checks1["conformational_strain_mmff94s"].status is DiagnosticStatus.PASS

        # 2. Pose 2 (identical ligand coords, moved MET A:5 clashes directly!) -> FAIL
        resp2 = client.post(base2, json={"include_strain": False})
        assert resp2.status_code == 201, resp2.text
        rec2 = PoseQualityRecord.model_validate(resp2.json())
        assert rec2.assessment.strain is None
        assert rec2.assessment.overall_status is DiagnosticStatus.FAIL
        checks2 = {c.check_id: c for c in rec2.assessment.checks}
        assert checks2["pb_minimum_distance_to_protein"].status is DiagnosticStatus.FAIL
        assert checks2["pb_volume_overlap_with_protein"].status is DiagnosticStatus.FAIL
        assert any(w.code == "POSE_QUALITY_CHECKS_FAILED" for w in rec2.warnings)

        # 3. Persisted history reloads cleanly
        hist1 = client.get(base1)
        assert hist1.status_code == 200
        assert len(hist1.json()) == 1
        assert hist1.json()[0]["assessment_id"] == rec1.assessment_id

    # 4. MethodsReport prose cites PoseBusters DOI, coupled FlexRes E8, and strain disclaimer
    methods_md = render_pose_quality_methods([rec1, rec2])
    assert "10.1039/D3SC04185A" in methods_md
    assert "PoseBusters (0.6.5" in methods_md
    assert "receptor_rigid + pose_flex_sidechains" in methods_md
    assert "never added to or subtracted from any docking score" in methods_md
    assert "mutated_original_pose = false" in methods_md

    # 5. Stale propagation reaches persisted analysis/pose_quality without mutating it
    deps = ProjectDependencyService(root=tmp_path, project_id="default")
    stale_res = deps.mark_stale(ids["receptor_id"], "Synthetic upstream receptor edit")
    assert rec1.assessment_id in stale_res.affected_node_ids
    assert rec2.assessment_id in stale_res.affected_node_ids


def test_pose_quality_http_api_boron_ligand_reports_not_evaluable_without_uff_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ANKORA_DATA_DIR", str(tmp_path))
    app = create_app()
    now = datetime.now(UTC)

    receptors = ReceptorArtifactStore.from_environment()
    sites = BindingSiteArtifactStore.from_environment()
    ligands = LigandArtifactStore.from_environment()
    docking = DockingArtifactStore.from_environment()

    rec_id = receptors.new_receptor_id()
    receptors.create_receptor(rec_id)
    prot_bytes = _SYNTHETIC_CRYSTAL_PDB.encode("utf-8")
    rigid_bytes = _SYNTHETIC_RIGID_PDBQT.encode("utf-8")
    prot_art_id = "art-prot-rigid"
    rigid_art_id = "art-rigid-only"
    receptors.write_bytes(rec_id, "protonated.pdb", prot_bytes)
    receptors.write_bytes(rec_id, "receptor_rigid.pdbqt", rigid_bytes)
    receptors.save_record(
        ReceptorPreparationRecord(
            receptor_id=rec_id,
            source_artifact_id="src-synth-rigid",
            created_at=now,
            status=ReceptorPreparationStatus.DOCKING_READY,
            decisions=ReceptorPreparationRequest(
                selected_chains=["A"],
                water_action=ComponentAction.REMOVE,
                component_decisions=[],
                issue_decisions=[],
                protonation=ProtonationSettings(enabled=True),
                generate_pdbqt=True,
            ),
            outputs=[
                ReceptorOutputArtifact(
                    artifact_id=prot_art_id,
                    stage=ReceptorOutputStage.PROTONATED_PDB,
                    filename="protonated.pdb",
                    format="pdb",
                    sha256=_sha(prot_bytes),
                    size_bytes=len(prot_bytes),
                    created_at=now,
                    content_url=f"/receptors/{rec_id}/outputs/{prot_art_id}/content",
                ),
                ReceptorOutputArtifact(
                    artifact_id=rigid_art_id,
                    stage=ReceptorOutputStage.PDBQT,
                    filename="receptor_rigid.pdbqt",
                    format="pdbqt",
                    sha256=_sha(rigid_bytes),
                    size_bytes=len(rigid_bytes),
                    created_at=now,
                    content_url=f"/receptors/{rec_id}/outputs/{rigid_art_id}/content",
                ),
            ],
            warnings=[],
            provenance=[],
            display_output_artifact_id=prot_art_id,
        )
    )
    site_id = sites.new_binding_site_id()
    sites.save_record(
        BindingSiteRecord(
            binding_site_id=site_id,
            receptor_id=rec_id,
            source_artifact_id="src-synth-rigid",
            created_at=now,
            box=_BOX,
            decisions=BindingSiteRequest(source=BindingSiteSource.MANUAL, manual_box=_BOX),
            warnings=[],
            provenance=[
                ProvenanceEvent(
                    event_id="evt-site-b",
                    event_type="binding_site_confirmed",
                    timestamp=now,
                    input_artifacts=[rec_id],
                    output_artifacts=[site_id],
                    tool=ToolIdentity(name="Ankora", version="0.2.0-dev"),
                )
            ],
        )
    )

    # Synthetic phenylboronic acid positioned ~4.3 A clear of crystal MET A:5
    mol = Chem.AddHs(Chem.MolFromSmiles("c1ccccc1B(O)O"))
    params = AllChem.ETKDGv3()
    params.randomSeed = 20261119
    params.numThreads = 1
    assert AllChem.EmbedMolecule(mol, params) == 0
    conf = mol.GetConformer()
    heavy = [a.GetIdx() for a in mol.GetAtoms() if a.GetAtomicNum() > 1]
    cx = sum(conf.GetAtomPosition(i).x for i in heavy) / len(heavy)
    cy = sum(conf.GetAtomPosition(i).y for i in heavy) / len(heavy)
    cz = sum(conf.GetAtomPosition(i).z for i in heavy) / len(heavy)
    for idx in range(mol.GetNumAtoms()):
        pt = conf.GetAtomPosition(idx)
        conf.SetAtomPosition(idx, (pt.x + (5.2 - cx), pt.y + (-4.0 - cy), pt.z - cz))

    sdf_bytes = (Chem.MolToMolBlock(mol) + "\n$$$$\n").encode("utf-8")
    prep = meeko.MoleculePreparation()
    setups = prep.prepare(mol)
    pdbqt_str, is_ok, err = meeko.PDBQTWriterLegacy.write_string(setups[0])
    assert is_ok, err
    pdbqt_bytes = pdbqt_str.encode("utf-8")

    lig_id = ligands.new_ligand_id()
    inspection = LigandInspection(
        name="SYNTH_PHENYLBORONIC",
        formula="C6H7BO2",
        formal_charge=0,
        atom_count=mol.GetNumAtoms(),
        heavy_atom_count=len(heavy),
        rotatable_bond_count=1,
        aromatic_ring_count=1,
        stereocenter_count=0,
        conformer_count=1,
        has_3d_coordinates=True,
        canonical_smiles="OB(O)c1ccccc1",
    )
    ligands.create(
        lig_id,
        sdf_bytes,
        LigandRecord(
            artifact=LigandArtifact(
                ligand_id=lig_id,
                source=LigandSource.LOCAL,
                filename="boron.sdf",
                format=LigandFormat.SDF,
                sha256=_sha(sdf_bytes),
                size_bytes=len(sdf_bytes),
                created_at=now,
            ),
            inspection=inspection,
            warnings=[],
            provenance=ProvenanceEvent(
                event_id="evt-lig-b",
                event_type="ligand_imported",
                timestamp=now,
                input_artifacts=[],
                output_artifacts=[lig_id],
                tool=ToolIdentity(name="RDKit", version="2025.9.6"),
            ),
            content_url=f"/ligands/{lig_id}/content",
        ),
    )
    conf_id = ligands.new_conformer_id()
    ligands.create_conformer(
        lig_id,
        conf_id,
        sdf_bytes,
        LigandConformerRecord(
            artifact=LigandConformerArtifact(
                conformer_id=conf_id,
                ligand_id=lig_id,
                stage="minimized",
                filename="boron_conf.sdf",
                format="sdf",
                sha256=_sha(sdf_bytes),
                size_bytes=len(sdf_bytes),
                created_at=now,
            ),
            inspection=inspection,
            minimization=LigandMinimizationResult(
                force_field=LigandForceField.MMFF94S,
                max_iterations=1,
                converged=False,
                initial_energy_kcal_mol=0.0,
                final_energy_kcal_mol=0.0,
            ),
            warnings=[],
            provenance=ProvenanceEvent(
                event_id="evt-conf-b",
                event_type="ligand_minimized",
                timestamp=now,
                input_artifacts=[lig_id],
                output_artifacts=[conf_id],
                tool=ToolIdentity(name="RDKit", version="2025.9.6"),
            ),
            content_url=f"/ligands/{lig_id}/conformers/{conf_id}/content",
        ),
    )
    prep_id = ligands.new_preparation_id()
    ligands.create_pdbqt(
        lig_id,
        prep_id,
        pdbqt_bytes,
        LigandPdbqtRecord(
            artifact=LigandPdbqtArtifact(
                preparation_id=prep_id,
                ligand_id=lig_id,
                conformer_id=conf_id,
                filename="boron.pdbqt",
                format="pdbqt",
                sha256=_sha(pdbqt_bytes),
                size_bytes=len(pdbqt_bytes),
                created_at=now,
            ),
            charge_model=LigandChargeModel.GASTEIGER,
            tool=ToolIdentity(name="Meeko", version="0.7.1"),
            command=["mk_prepare_ligand"],
            stdout="",
            stderr="",
            provenance=ProvenanceEvent(
                event_id="evt-prep-b",
                event_type="ligand_pdbqt_prepared",
                timestamp=now,
                input_artifacts=[conf_id],
                output_artifacts=[prep_id],
                tool=ToolIdentity(name="Meeko", version="0.7.1"),
            ),
            content_url=f"/ligands/{lig_id}/pdbqt/{prep_id}/content",
        ),
    )

    job_id = docking.new_job_id()
    pose_id = "pose-boron-1"
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
                ligand_id=lig_id,
                ligand_preparation_id=prep_id,
                parameters=VinaDockingParameters(),
                acknowledge_inputs_and_scoring=True,
            ),
            tool=ToolIdentity(name="AutoDock Vina", version="1.2.7"),
            receptor_output_artifact_id=rigid_art_id,
            receptor_sha256=_sha(rigid_bytes),
            ligand_sha256=_sha(pdbqt_bytes),
            poses=[
                DockingPoseResult(
                    mode=1,
                    affinity_kcal_mol=-4.2,
                    rmsd_lower_bound_angstrom=0.0,
                    rmsd_upper_bound_angstrom=0.0,
                    artifact=DockingPoseArtifact(
                        artifact_id=pose_id,
                        mode=1,
                        filename="pose_1.pdbqt",
                        format="pdbqt",
                        sha256=_sha(pdbqt_bytes),
                        size_bytes=len(pdbqt_bytes),
                        content_url=f"/docking/vina/jobs/{job_id}/poses/{pose_id}/content",
                    ),
                )
            ],
        )
    )
    docking.write_bytes(job_id, "pose_1.pdbqt", pdbqt_bytes)

    url = (
        f"/api/v1/results/campaigns/vina_job/{job_id}"
        f"/compounds/{lig_id}/poses/{pose_id}/quality"
    )
    with TestClient(app) as client:
        resp = client.post(url, json={"include_strain": True, "conformer_budget": 5})
        assert resp.status_code == 201, resp.text
        rec = PoseQualityRecord.model_validate(resp.json())
        assert rec.assessment.pose_complex.mode is ReceptorFlexMode.RIGID
        assert rec.materialized_coupled_receptor_sha256 is None
        assert rec.assessment.strain is None
        assert rec.assessment.overall_status is DiagnosticStatus.NOT_EVALUABLE
        assert rec.not_evaluable_count >= 1
        assert any(w.code == "POSE_QUALITY_MMFF94S_UNPARAMETERIZED" for w in rec.warnings)
        # No flex_sidechain_* checks emitted for rigid poses
        assert not any(c.check_id.startswith("flex_sidechain_") for c in rec.assessment.checks)
