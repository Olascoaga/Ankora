"""End-to-end live ProLIF 2.2.1 service, HTTP API, E8 FlexRes, stale-DAG, and Methods tests (M4b).

All receptors, ligands, and poses in this module are explicitly synthetic and
labelled synthetic. Tests run live ProLIF 2.2.1 and Meeko 0.7.1 without mocking
the interaction detector.
"""

from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256
from importlib import import_module
from pathlib import Path
from typing import Any

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
from ankora_backend.schemas.interaction_rules import (
    InteractionRuleEvaluationRecord,
    InteractionRuleSetRecord,
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
from ankora_backend.schemas.warnings import WarningCode
from ankora_backend.services.methods_report import render_interaction_rules_methods
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

# Synthetic SER A:5 crystal receptor + distant ALA A:6.
# In the crystal conformation, SER A:5 OG/HG point in +Y (far from a ligand at y = -4.2).
_SYNTHETIC_SER_CRYSTAL_PDB = (
    "ATOM      1  N   SER A   5      -0.500   1.350   0.250  1.00  0.00           N  \n"
    "ATOM      2  CA  SER A   5       0.000   0.000   0.000  1.00  0.00           C  \n"
    "ATOM      3  C   SER A   5      -0.550  -0.500  -1.320  1.00  0.00           C  \n"
    "ATOM      4  O   SER A   5      -0.100  -1.550  -1.780  1.00  0.00           O  \n"
    "ATOM      5  HA  SER A   5      -0.350  -0.650   0.780  1.00  0.00           H  \n"
    "ATOM      6  CB  SER A   5       1.530   0.000   0.000  1.00  0.00           C  \n"
    "ATOM      7  OG  SER A   5       2.040   1.340   0.000  1.00  0.00           O  \n"
    "ATOM      8  HB2 SER A   5       1.894  -0.514   0.890  1.00  0.00           H  \n"
    "ATOM      9  HB3 SER A   5       1.894  -0.514  -0.890  1.00  0.00           H  \n"
    "ATOM     10  HG  SER A   5       2.040   2.300   0.000  1.00  0.00           H  \n"
    "ATOM     11  N   ALA A   6      -1.550   0.250  -1.850  1.00  0.00           N  \n"
    "ATOM     12  CA  ALA A   6      -2.250  -0.150  -3.080  1.00  0.00           C  \n"
    "ATOM     13  C   ALA A   6      -3.750  -0.150  -2.850  1.00  0.00           C  \n"
    "ATOM     14  O   ALA A   6      -4.250  -1.100  -2.250  1.00  0.00           O  \n"
    "ATOM     15  CB  ALA A   6      -1.850   0.800  -4.210  1.00  0.00           C  \n"
    "END\n"
)

_SYNTHETIC_SER_RIGID_PDBQT = (
    "ATOM      1  N   SER A   5      -0.500   1.350   0.250  1.00  0.00     0.000 N \n"
    "ATOM      2  C   SER A   5      -0.550  -0.500  -1.320  1.00  0.00     0.000 C \n"
    "ATOM      3  O   SER A   5      -0.100  -1.550  -1.780  1.00  0.00     0.000 OA\n"
    "ATOM      4  N   ALA A   6      -1.550   0.250  -1.850  1.00  0.00     0.000 N \n"
    "ATOM      5  CA  ALA A   6      -2.250  -0.150  -3.080  1.00  0.00     0.000 C \n"
)

# Pose 1: moved SER A:5 rotated into -Y so OG sits at (2.04, -1.34, 0.00) with polar HG
# pointing straight down to (2.04, -2.30, 0.00) — ideal H-bond geometry to an ethanol
# oxygen positioned at (2.04, -4.14, 0.00) (O...O distance = 2.80 A, O-H...O angle = 180 deg).
_SYNTHETIC_SER_FLEX_HBOND_PDBQT = (
    "BEGIN_RES SER A 5\n"
    "ROOT\n"
    "ATOM      1  CA  SER A   5       0.000   0.000   0.000  1.00  0.00     0.000 C \n"
    "ENDROOT\n"
    "BRANCH   1   2\n"
    "ATOM      2  CB  SER A   5       1.530   0.000   0.000  1.00  0.00     0.000 C \n"
    "BRANCH   2   3\n"
    "ATOM      3  OG  SER A   5       2.040  -1.340   0.000  1.00  0.00    -0.400 OA\n"
    "ATOM      4  HG  SER A   5       2.040  -2.300   0.000  1.00  0.00     0.210 HD\n"
    "ENDBRANCH   2   3\n"
    "ENDBRANCH   1   2\n"
    "END_RES SER A 5\n"
)

# Pose 2: moved SER A:5 remains in crystal +Y orientation (OG at +1.34, > 5.4 A from ethanol O).
_SYNTHETIC_SER_FLEX_AWAY_PDBQT = (
    "BEGIN_RES SER A 5\n"
    "ROOT\n"
    "ATOM      1  CA  SER A   5       0.000   0.000   0.000  1.00  0.00     0.000 C \n"
    "ENDROOT\n"
    "BRANCH   1   2\n"
    "ATOM      2  CB  SER A   5       1.530   0.000   0.000  1.00  0.00     0.000 C \n"
    "BRANCH   2   3\n"
    "ATOM      3  OG  SER A   5       2.040   1.340   0.000  1.00  0.00    -0.400 OA\n"
    "ATOM      4  HG  SER A   5       2.040   2.300   0.000  1.00  0.00     0.210 HD\n"
    "ENDBRANCH   2   3\n"
    "ENDBRANCH   1   2\n"
    "END_RES SER A 5\n"
)


def _sha(data: bytes) -> str:
    return sha256(data).hexdigest()


def _build_synthetic_ethanol_with_oxygen_at(
    ox: float, oy: float, oz: float
) -> tuple[bytes, bytes]:
    """Create a minimized ethanol SDF + Meeko PDBQT with its hydroxyl oxygen at `(ox, oy, oz)`."""
    mol = Chem.AddHs(Chem.MolFromSmiles("CCO"))
    params = AllChem.ETKDGv3()
    params.randomSeed = 20261119
    params.numThreads = 1
    assert AllChem.EmbedMolecule(mol, params) == 0
    assert AllChem.MMFFOptimizeMolecule(mol, mmffVariant="MMFF94s") == 0

    conf = mol.GetConformer()
    o_idx = next(atom.GetIdx() for atom in mol.GetAtoms() if atom.GetAtomicNum() == 8)
    o_pt = conf.GetAtomPosition(o_idx)
    # Orient so the rest of ethanol lies further in -Y (away from SER A:5 backbone at y ~ 0)
    # by checking centroid of carbons relative to O and flipping Y if carbons are above O.
    c_ys = [conf.GetAtomPosition(a.GetIdx()).y for a in mol.GetAtoms() if a.GetAtomicNum() == 6]
    flip_y = -1.0 if (sum(c_ys) / len(c_ys)) > o_pt.y else 1.0
    for idx in range(mol.GetNumAtoms()):
        pt = conf.GetAtomPosition(idx)
        nx = (pt.x - o_pt.x) + ox
        ny = (pt.y - o_pt.y) * flip_y + oy
        nz = (pt.z - o_pt.z) + oz
        conf.SetAtomPosition(idx, (nx, ny, nz))

    sdf_bytes = (Chem.MolToMolBlock(mol) + "\n$$$$\n").encode("utf-8")
    prep = meeko.MoleculePreparation()
    setups = prep.prepare(mol)
    pdbqt_str, is_ok, err = meeko.PDBQTWriterLegacy.write_string(setups[0])
    assert is_ok, err
    return sdf_bytes, pdbqt_str.encode("utf-8")


def _seed_flex_ser_vina_job() -> dict[str, str]:
    now = datetime.now(UTC)
    receptors = ReceptorArtifactStore.from_environment()
    sites = BindingSiteArtifactStore.from_environment()
    ligands = LigandArtifactStore.from_environment()
    docking = DockingArtifactStore.from_environment()

    rec_id = receptors.new_receptor_id()
    receptors.create_receptor(rec_id)
    prot_bytes = _SYNTHETIC_SER_CRYSTAL_PDB.encode("utf-8")
    rigid_bytes = _SYNTHETIC_SER_RIGID_PDBQT.encode("utf-8")
    flex_init_bytes = _SYNTHETIC_SER_FLEX_AWAY_PDBQT.encode("utf-8")
    prot_art_id = "art-ser-prot-pdb"
    rigid_art_id = "art-ser-rigid-pdbqt"
    flex_art_id = "art-ser-flex-pdbqt"
    receptors.write_bytes(rec_id, "protonated.pdb", prot_bytes)
    receptors.write_bytes(rec_id, "receptor_rigid.pdbqt", rigid_bytes)
    receptors.write_bytes(rec_id, "receptor_flex.pdbqt", flex_init_bytes)

    flex_res = ResidueLocator(chain_id="A", residue_name="SER", sequence_number=5)
    receptors.save_record(
        ReceptorPreparationRecord(
            receptor_id=rec_id,
            source_artifact_id="src-synth-ser",
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
            flex_spec=ReceptorFlexSpec(
                mode=ReceptorFlexMode.SIDECHAIN_FLEX,
                flex_residues=(flex_res,),
                receptor_rigid_sha256=_sha(rigid_bytes),
                receptor_flex_sha256=_sha(flex_init_bytes),
            ),
            warnings=[],
            display_output_artifact_id=prot_art_id,
            provenance=[
                ProvenanceEvent(
                    event_id="evt-rec-ser",
                    event_type="receptor_prepared",
                    timestamp=now,
                    input_artifacts=["src-synth-ser"],
                    output_artifacts=[prot_art_id, rigid_art_id, flex_art_id],
                    tool=ToolIdentity(name="Meeko", version="0.7.1"),
                )
            ],
        )
    )

    # Also seed a second unrelated receptor to verify cross-receptor mismatch rejection.
    other_rec_id = receptors.new_receptor_id()
    receptors.create_receptor(other_rec_id)
    other_prot = (
        b"ATOM      1  CA  GLY A   1       0.000   0.000   0.000  1.00  0.00           C  \n"
        b"END\n"
    )
    receptors.write_bytes(other_rec_id, "protonated.pdb", other_prot)
    receptors.save_record(
        ReceptorPreparationRecord(
            receptor_id=other_rec_id,
            source_artifact_id="src-synth-other",
            created_at=now,
            status=ReceptorPreparationStatus.DOCKING_READY,
            decisions=ReceptorPreparationRequest(
                selected_chains=["A"],
                water_action=ComponentAction.REMOVE,
                component_decisions=[],
                issue_decisions=[],
                protonation=ProtonationSettings(enabled=True),
                generate_pdbqt=False,
            ),
            outputs=[
                ReceptorOutputArtifact(
                    artifact_id="art-other-prot",
                    stage=ReceptorOutputStage.PROTONATED_PDB,
                    filename="protonated.pdb",
                    format="pdb",
                    sha256=_sha(other_prot),
                    size_bytes=len(other_prot),
                    created_at=now,
                    content_url=f"/receptors/{other_rec_id}/outputs/art-other-prot/content",
                ),
            ],
            warnings=[],
            display_output_artifact_id="art-other-prot",
            provenance=[
                ProvenanceEvent(
                    event_id="evt-rec-other",
                    event_type="receptor_prepared",
                    timestamp=now,
                    input_artifacts=["src-synth-other"],
                    output_artifacts=["art-other-prot"],
                    tool=ToolIdentity(name="Meeko", version="0.7.1"),
                )
            ],
        )
    )

    site_id = sites.new_binding_site_id()
    sites.save_record(
        BindingSiteRecord(
            binding_site_id=site_id,
            receptor_id=rec_id,
            source_artifact_id="src-synth-ser",
            created_at=now,
            box=_BOX,
            decisions=BindingSiteRequest(source=BindingSiteSource.MANUAL, manual_box=_BOX),
            warnings=[],
            provenance=[
                ProvenanceEvent(
                    event_id="evt-site-ser",
                    event_type="binding_site_confirmed",
                    timestamp=now,
                    input_artifacts=[rec_id],
                    output_artifacts=[site_id],
                    tool=ToolIdentity(name="Ankora", version="0.2.0-dev"),
                )
            ],
        )
    )

    sdf_bytes, pdbqt_bytes = _build_synthetic_ethanol_with_oxygen_at(2.04, -4.14, 0.0)
    lig_id = ligands.new_ligand_id()
    inspection = LigandInspection(
        name="synthetic_ethanol",
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
                filename="ethanol.sdf",
                format=LigandFormat.SDF,
                sha256=_sha(sdf_bytes),
                size_bytes=len(sdf_bytes),
                created_at=now,
            ),
            inspection=inspection,
            warnings=[],
            provenance=ProvenanceEvent(
                event_id="evt-lig-ser",
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
                filename="ethanol_conf.sdf",
                format="sdf",
                sha256=_sha(sdf_bytes),
                size_bytes=len(sdf_bytes),
                created_at=now,
            ),
            inspection=inspection,
            minimization=LigandMinimizationResult(
                force_field=LigandForceField.MMFF94S,
                max_iterations=200,
                converged=True,
                initial_energy_kcal_mol=0.1,
                final_energy_kcal_mol=0.0,
            ),
            warnings=[],
            provenance=ProvenanceEvent(
                event_id="evt-conf-ser",
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
                filename="ethanol.pdbqt",
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
                event_id="evt-prep-ser",
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
    pose1_id = "pose-ser-hbond"
    pose2_id = "pose-ser-away"
    flex1_bytes = _SYNTHETIC_SER_FLEX_HBOND_PDBQT.encode("utf-8")
    flex2_bytes = _SYNTHETIC_SER_FLEX_AWAY_PDBQT.encode("utf-8")
    rigid_sha = _sha(rigid_bytes)
    pose_sha = _sha(pdbqt_bytes)

    complex1 = PoseComplexIdentity(
        mode=ReceptorFlexMode.SIDECHAIN_FLEX,
        receptor_rigid_sha256=rigid_sha,
        pose_flex_sidechains_sha256=_sha(flex1_bytes),
        ligand_pose_sha256=pose_sha,
    )
    complex2 = PoseComplexIdentity(
        mode=ReceptorFlexMode.SIDECHAIN_FLEX,
        receptor_rigid_sha256=rigid_sha,
        pose_flex_sidechains_sha256=_sha(flex2_bytes),
        ligand_pose_sha256=pose_sha,
    )

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
            receptor_sha256=rigid_sha,
            receptor_flex_mode=ReceptorFlexMode.SIDECHAIN_FLEX,
            receptor_flex_output_artifact_id=flex_art_id,
            receptor_flex_sha256=_sha(flex_init_bytes),
            flex_residues=[flex_res],
            ligand_sha256=pose_sha,
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
                        sha256=pose_sha,
                        size_bytes=len(pdbqt_bytes),
                        content_url=f"/docking/vina/jobs/{job_id}/poses/{pose1_id}/content",
                        flex_filename="pose_1_flex.pdbqt",
                        pose_flex_sidechains_sha256=_sha(flex1_bytes),
                        flex_content_url=f"/docking/vina/jobs/{job_id}/poses/{pose1_id}/flex",
                        pose_complex_identity_sha256=complex1.complex_identity_sha256,
                    ),
                ),
                DockingPoseResult(
                    mode=2,
                    affinity_kcal_mol=-2.1,
                    rmsd_lower_bound_angstrom=0.0,
                    rmsd_upper_bound_angstrom=0.0,
                    artifact=DockingPoseArtifact(
                        artifact_id=pose2_id,
                        mode=2,
                        filename="pose_2.pdbqt",
                        format="pdbqt",
                        sha256=pose_sha,
                        size_bytes=len(pdbqt_bytes),
                        content_url=f"/docking/vina/jobs/{job_id}/poses/{pose2_id}/content",
                        flex_filename="pose_2_flex.pdbqt",
                        pose_flex_sidechains_sha256=_sha(flex2_bytes),
                        flex_content_url=f"/docking/vina/jobs/{job_id}/poses/{pose2_id}/flex",
                        pose_complex_identity_sha256=complex2.complex_identity_sha256,
                    ),
                ),
            ],
        )
    )
    docking.write_bytes(job_id, "pose_1.pdbqt", pdbqt_bytes)
    docking.write_bytes(job_id, "pose_1_flex.pdbqt", flex1_bytes)
    docking.write_bytes(job_id, "pose_2.pdbqt", pdbqt_bytes)
    docking.write_bytes(job_id, "pose_2_flex.pdbqt", flex2_bytes)

    return {
        "receptor_id": rec_id,
        "other_receptor_id": other_rec_id,
        "ligand_id": lig_id,
        "job_id": job_id,
        "catalog_id": f"vina_job:{job_id}",
        "pose1_id": pose1_id,
        "pose2_id": pose2_id,
    }


def test_coupled_flexres_prolif_rules_tanimoto_api_stale_dag_and_methods(
    tmp_path: Path, monkeypatch: Any
) -> None:
    """Proves live ProLIF 2.2.1 rule evaluation & Tanimoto IFP on coupled FlexRes E8 complexes.

    Pose 1 and Pose 2 carry identical synthetic ethanol coordinates. In the crystal
    receptor, SER A:5 OG points away (+Y). Pose 1 rotates SER A:5 OG/HG into -Y to
    form a real ProLIF H-bond with ethanol (REQUIRED passes, Tanimoto = 1.0); Pose 2
    leaves SER A:5 away in +Y (REQUIRED fails, Tanimoto = 0.0).
    """
    monkeypatch.setenv("ANKORA_DATA_DIR", str(tmp_path))
    app = create_app()
    seeded = _seed_flex_ser_vina_job()

    rec_id = seeded["receptor_id"]
    other_rec_id = seeded["other_receptor_id"]
    lig_id = seeded["ligand_id"]
    job_id = seeded["job_id"]
    catalog_id = seeded["catalog_id"]
    pose1_id = seeded["pose1_id"]
    pose2_id = seeded["pose2_id"]

    with TestClient(app) as client:
        # 1. Residue typo fails closed (422)
        bad_res = client.post(
            "/api/v1/interactions/rule-sets",
            json={
                "name": "Typo rule set",
                "receptor_id": rec_id,
                "clauses": [
                    {
                        "clause_id": "bad-res",
                        "label": "Nonexistent residue",
                        "kind": "required",
                        "targets": [
                            {
                                "residue": {
                                    "chain_id": "A",
                                    "residue_name": "ASP",
                                    "sequence_number": 999,
                                },
                                "interaction_types": ["HBDonor"],
                            }
                        ],
                    }
                ],
            },
        )
        assert bad_res.status_code == 422
        assert bad_res.json()["code"] == "INTERACTION_RULE_RESIDUE_NOT_FOUND"

        # 2. Create sealed rule set with REQUIRED SER A:5 H-bond, FORBIDDEN ALA A:6 Anionic,
        #    and Pose 1 as reference IFP (min Tanimoto = 0.8)
        create_rs = client.post(
            "/api/v1/interactions/rule-sets",
            json={
                "name": "Induced SER A:5 H-bond hypothesis",
                "description": "Requires rotated SER A:5 hydrogen bond on coupled FlexRes complex.",
                "receptor_id": rec_id,
                "clauses": [
                    {
                        "clause_id": "req-ser5-hb",
                        "label": "SER A:5 hydrogen bond",
                        "kind": "required",
                        "targets": [
                            {
                                "residue": {
                                    "chain_id": "A",
                                    "residue_name": "SER",
                                    "sequence_number": 5,
                                },
                                "interaction_types": ["HBDonor", "HBAcceptor"],
                                "max_distance_angstrom": 3.5,
                            }
                        ],
                    },
                    {
                        "clause_id": "forbid-ala6-anionic",
                        "label": "No ALA A:6 anionic contact",
                        "kind": "forbidden",
                        "targets": [
                            {
                                "residue": {
                                    "chain_id": "A",
                                    "residue_name": "ALA",
                                    "sequence_number": 6,
                                },
                                "interaction_types": ["Anionic"],
                            }
                        ],
                    },
                ],
                "reference_pose": {
                    "catalog_id": catalog_id,
                    "ligand_id": lig_id,
                    "pose_artifact_id": pose1_id,
                },
                "min_tanimoto_similarity": 0.8,
            },
        )
        assert create_rs.status_code == 201, create_rs.text
        rule_set = InteractionRuleSetRecord.model_validate(create_rs.json())
        assert rule_set.reference_ifp is not None
        assert len(rule_set.reference_ifp.bits) >= 1
        assert any(
            b.residue.residue_name == "SER"
            and b.residue.sequence_number == 5
            and b.interaction_type in {"HBDonor", "HBAcceptor"}
            for b in rule_set.reference_ifp.bits
        )

        # Verify GET list + detail endpoints
        listed_rs = client.get(f"/api/v1/interactions/rule-sets?receptor_id={rec_id}")
        assert listed_rs.status_code == 200
        assert len(listed_rs.json()) == 1
        fetched_rs = client.get(f"/api/v1/interactions/rule-sets/{rule_set.rule_set_id}")
        assert fetched_rs.status_code == 200
        assert fetched_rs.json()["rule_set_identity_sha256"] == rule_set.rule_set_identity_sha256

        # 3. Evaluate Pose 1 (moved SER A:5 H-bonding): PASS + Tanimoto == 1.0
        pose1_url = (
            f"/api/v1/results/campaigns/vina_job/{job_id}"
            f"/compounds/{lig_id}/poses/{pose1_id}/interaction-rules"
        )
        eval1_resp = client.post(pose1_url, json={"rule_set_id": rule_set.rule_set_id})
        assert eval1_resp.status_code == 201, eval1_resp.text
        eval1 = InteractionRuleEvaluationRecord.model_validate(eval1_resp.json())
        assert eval1.overall_status is DiagnosticStatus.PASS
        assert eval1.passed_clause_count == 2
        assert eval1.failed_clause_count == 0
        assert eval1.mutated_original_pose is False
        assert eval1.pose_complex.mode is ReceptorFlexMode.SIDECHAIN_FLEX
        assert eval1.materialized_coupled_receptor_sha256 is not None
        assert eval1.tanimoto is not None
        assert eval1.tanimoto.similarity == 1.0
        assert eval1.tanimoto.status is DiagnosticStatus.PASS
        assert len(eval1.clause_results[0].matched_contact_ids) >= 1

        # 4. Evaluate Pose 2 (identical ligand, SER A:5 away in +Y): FAIL + Tanimoto < 0.8
        pose2_url = (
            f"/api/v1/results/campaigns/vina_job/{job_id}"
            f"/compounds/{lig_id}/poses/{pose2_id}/interaction-rules"
        )
        eval2_resp = client.post(pose2_url, json={"rule_set_id": rule_set.rule_set_id})
        assert eval2_resp.status_code == 201, eval2_resp.text
        eval2 = InteractionRuleEvaluationRecord.model_validate(eval2_resp.json())
        assert eval2.overall_status is DiagnosticStatus.FAIL
        assert eval2.clause_results[0].status is DiagnosticStatus.FAIL
        assert eval2.clause_results[1].status is DiagnosticStatus.PASS
        assert eval2.materialized_coupled_receptor_sha256 is not None
        assert (
            eval2.materialized_coupled_receptor_sha256 != eval1.materialized_coupled_receptor_sha256
        )
        assert eval2.tanimoto is not None
        assert eval2.tanimoto.status is DiagnosticStatus.FAIL
        assert eval2.tanimoto.similarity is not None and eval2.tanimoto.similarity < 0.8
        warning_codes = {w.code for w in eval2.warnings}
        assert WarningCode.INTERACTION_RULE_CLAUSES_FAILED in warning_codes
        assert WarningCode.INTERACTION_IFP_TANIMOTO_BELOW_THRESHOLD in warning_codes

        # 5. FORBIDDEN rule on SER A:5 triggers INTERACTION_RULE_FORBIDDEN_CONTACT on Pose 1
        forbid_rs_resp = client.post(
            "/api/v1/interactions/rule-sets",
            json={
                "name": "Forbidden SER A:5 H-bond",
                "receptor_id": rec_id,
                "clauses": [
                    {
                        "clause_id": "forbid-ser5-hb",
                        "label": "Must not H-bond SER A:5",
                        "kind": "forbidden",
                        "targets": [
                            {
                                "residue": {
                                    "chain_id": "A",
                                    "residue_name": "SER",
                                    "sequence_number": 5,
                                },
                                "interaction_types": ["HBDonor", "HBAcceptor"],
                            }
                        ],
                    }
                ],
            },
        )
        assert forbid_rs_resp.status_code == 201
        forbid_rs = InteractionRuleSetRecord.model_validate(forbid_rs_resp.json())
        forbid_eval_resp = client.post(pose1_url, json={"rule_set_id": forbid_rs.rule_set_id})
        assert forbid_eval_resp.status_code == 201
        forbid_eval = InteractionRuleEvaluationRecord.model_validate(forbid_eval_resp.json())
        assert forbid_eval.overall_status is DiagnosticStatus.FAIL
        assert any(
            w.code is WarningCode.INTERACTION_RULE_FORBIDDEN_CONTACT for w in forbid_eval.warnings
        )
        assert len(forbid_eval.clause_results[0].matched_contact_ids) >= 1

        # 6. Reusing a matching ProLIF InteractionAnalysisRecord works; wrong pose fails closed
        analyze_p1 = client.post(
            f"/api/v1/results/campaigns/vina_job/{job_id}"
            f"/compounds/{lig_id}/poses/{pose1_id}/interactions",
            json={},
        )
        assert analyze_p1.status_code == 201, analyze_p1.text
        p1_analysis_id = analyze_p1.json()["analysis_id"]
        reuse_ok = client.post(
            pose1_url,
            json={"rule_set_id": rule_set.rule_set_id, "analysis_id": p1_analysis_id},
        )
        assert reuse_ok.status_code == 201
        assert reuse_ok.json()["interaction_analysis_id"] == p1_analysis_id
        assert reuse_ok.json()["overall_status"] == "pass"

        reuse_mismatch = client.post(
            pose2_url,
            json={"rule_set_id": rule_set.rule_set_id, "analysis_id": p1_analysis_id},
        )
        assert reuse_mismatch.status_code == 422
        assert reuse_mismatch.json()["code"] == "INTERACTION_RULE_ANALYSIS_MISMATCH"

        # 7. Cross-receptor mismatch fails closed (422)
        other_rs_resp = client.post(
            "/api/v1/interactions/rule-sets",
            json={
                "name": "Other receptor rule",
                "receptor_id": other_rec_id,
                "clauses": [
                    {
                        "clause_id": "req-gly1",
                        "label": "GLY A:1 H-bond",
                        "kind": "required",
                        "targets": [
                            {
                                "residue": {
                                    "chain_id": "A",
                                    "residue_name": "GLY",
                                    "sequence_number": 1,
                                },
                                "interaction_types": ["HBDonor"],
                            }
                        ],
                    }
                ],
            },
        )
        assert other_rs_resp.status_code == 201
        other_rs_id = other_rs_resp.json()["rule_set_id"]
        mismatch_resp = client.post(pose1_url, json={"rule_set_id": other_rs_id})
        assert mismatch_resp.status_code == 422
        assert mismatch_resp.json()["code"] == "INTERACTION_RULE_RECEPTOR_MISMATCH"

        # 8. List pose evaluations returns create-only history (newest first)
        history = client.get(pose1_url)
        assert history.status_code == 200
        assert len(history.json()) == 3

        # 9. ProjectDependencyService stale propagation: receptor -> rule_set -> pose evaluation
        deps = ProjectDependencyService(root=tmp_path)
        marked = deps.mark_stale(rec_id, "Synthetic receptor changed in M4b test")
        assert rule_set.rule_set_id in marked.affected_node_ids
        assert eval1.evaluation_id in marked.affected_node_ids
        assert eval2.evaluation_id in marked.affected_node_ids

        # 10. MethodsReport prose cites verified ProLIF DOI and exact rule/complex hashes
        methods_md = render_interaction_rules_methods([rule_set], [eval1, eval2])
        assert "10.1186/s13321-021-00548-6" in methods_md
        assert "Bouysset & Fiorucci" in methods_md
        assert rule_set.rule_set_identity_sha256[:12] in methods_md
        assert eval1.materialized_coupled_receptor_sha256[:12] in methods_md
        assert "Tanimoto IFP = 1.000" in methods_md
        assert "ADR-032 E8" in methods_md
