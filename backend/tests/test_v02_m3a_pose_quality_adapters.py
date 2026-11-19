"""Unit and live-adapter tests for Ankora v0.2 M3a pose-quality adapters.

All structures and molecules in this module are synthetic and explicitly labelled
synthetic. Tests exercise real PoseBusters 0.6.5 and RDKit MMFF94s execution.
"""

from __future__ import annotations

from importlib import import_module
from pathlib import Path
from typing import Any

from ankora_backend.adapters.quality.conformational_strain import (
    HYDROGEN_POLICY,
    evaluate_dual_mmff94s_strain,
)
from ankora_backend.adapters.quality.flex_sidechain_geometry import (
    evaluate_flex_sidechain_geometry,
)
from ankora_backend.adapters.quality.posebusters_adapter import (
    detect_posebusters_version,
    evaluate_posebusters_dock,
    reconstruct_ligand_mol_from_pose,
)
from ankora_backend.schemas.receptors import ResidueLocator
from ankora_backend.schemas.v02_contracts import DiagnosticStatus
from ankora_backend.schemas.warnings import WarningCode

Chem: Any = import_module("rdkit.Chem")
AllChem: Any = import_module("rdkit.Chem.AllChem")
rdMolTransforms: Any = import_module("rdkit.Chem.rdMolTransforms")


def _synthetic_ibuprofen() -> Any:
    mol = Chem.AddHs(Chem.MolFromSmiles("CC(C)Cc1ccc([C@@H](C)C(=O)O)cc1"))
    params = AllChem.ETKDGv3()
    params.randomSeed = 20261119
    params.numThreads = 1
    assert AllChem.EmbedMolecule(mol, params) == 0
    assert AllChem.MMFFOptimizeMolecule(mol, mmffVariant="MMFF94s") == 0
    return mol


def _synthetic_protein_at(x: float, y: float, z: float) -> Any:
    x2, x3, x4 = x + 1.458, x + 2.009, x + 1.251
    y3, y4 = y + 1.420, y + 2.390
    pdb = (
        f"ATOM      1  N   MET A   5    {x:8.3f}{y:8.3f}{z:8.3f}  1.00  0.00           N  \n"
        f"ATOM      2  CA  MET A   5    {x2:8.3f}{y:8.3f}{z:8.3f}  1.00  0.00           C  \n"
        f"ATOM      3  C   MET A   5    {x3:8.3f}{y3:8.3f}{z:8.3f}  1.00  0.00           C  \n"
        f"ATOM      4  O   MET A   5    {x4:8.3f}{y4:8.3f}{z:8.3f}  1.00  0.00           O  \n"
        "END\n"
    )
    prot = Chem.MolFromPDBBlock(pdb, removeHs=False, sanitize=True, proximityBonding=True)
    assert prot is not None
    return prot


def test_posebusters_valid_pose_honest_four_state_and_non_mutation() -> None:
    pb_ver = detect_posebusters_version()
    assert pb_ver == "0.6.5"

    lig = _synthetic_ibuprofen()
    before_sdf = Chem.MolToMolBlock(lig)
    p0 = lig.GetConformer().GetAtomPosition(0)
    # Place synthetic receptor atom ~3.6 A away (inside 5 A max distance, outside clash radius)
    receptor = _synthetic_protein_at(p0.x + 3.6, p0.y + 1.0, p0.z + 1.0)

    result = evaluate_posebusters_dock(ligand_mol=lig, receptor_mol=receptor)
    assert result.tool_version == pb_ver
    assert Chem.MolToMolBlock(lig) == before_sdf  # input never mutated

    by_id = {chk.check_id: chk for chk in result.checks}
    assert by_id["pb_sanitization"].status is DiagnosticStatus.PASS
    assert by_id["pb_bond_lengths"].status is DiagnosticStatus.PASS
    assert by_id["pb_bond_angles"].status is DiagnosticStatus.PASS
    assert by_id["pb_aromatic_ring_flatness"].status is DiagnosticStatus.PASS
    assert by_id["pb_minimum_distance_to_protein"].status is DiagnosticStatus.PASS
    assert by_id["pb_volume_overlap_with_protein"].status is DiagnosticStatus.PASS

    # Absent motifs & receptor species must be NOT_APPLICABLE, never fake PASS.
    assert by_id["pb_non_aromatic_ring_non_flatness"].status is DiagnosticStatus.NOT_APPLICABLE
    assert by_id["pb_double_bond_flatness"].status is DiagnosticStatus.NOT_APPLICABLE
    assert by_id["pb_minimum_distance_to_waters"].status is DiagnosticStatus.NOT_APPLICABLE
    assert by_id["pb_volume_overlap_with_waters"].status is DiagnosticStatus.NOT_APPLICABLE
    assert (
        by_id["pb_minimum_distance_to_organic_cofactors"].status
        is DiagnosticStatus.NOT_APPLICABLE
    )
    assert (
        by_id["pb_minimum_distance_to_inorganic_cofactors"].status
        is DiagnosticStatus.NOT_APPLICABLE
    )


def test_posebusters_detects_coupled_flex_sidechain_clash_and_stretched_bond() -> None:
    lig = _synthetic_ibuprofen()
    p0 = lig.GetConformer().GetAtomPosition(0)

    # Crystal receptor far away vs moved FlexRes side chain clashing onto ligand atom 0
    receptor_clashing = _synthetic_protein_at(p0.x, p0.y, p0.z)
    clash_res = evaluate_posebusters_dock(ligand_mol=lig, receptor_mol=receptor_clashing)
    clash_by_id = {chk.check_id: chk for chk in clash_res.checks}
    assert clash_by_id["pb_minimum_distance_to_protein"].status is DiagnosticStatus.FAIL
    assert clash_by_id["pb_volume_overlap_with_protein"].status is DiagnosticStatus.FAIL

    # Stretch one C-C bond to 3.2 A to verify bond-length check fails
    stretched = Chem.Mol(lig)
    bond = next(
        b
        for b in stretched.GetBonds()
        if b.GetBeginAtom().GetAtomicNum() > 1 and b.GetEndAtom().GetAtomicNum() > 1
    )
    rdMolTransforms.SetBondLength(
        stretched.GetConformer(),
        bond.GetBeginAtomIdx(),
        bond.GetEndAtomIdx(),
        3.2,
    )
    receptor_ok = _synthetic_protein_at(p0.x + 3.6, p0.y + 1.0, p0.z + 1.0)
    stretch_res = evaluate_posebusters_dock(ligand_mol=stretched, receptor_mol=receptor_ok)
    stretch_by_id = {chk.check_id: chk for chk in stretch_res.checks}
    assert stretch_by_id["pb_bond_lengths"].status is DiagnosticStatus.FAIL


def test_dual_mmff94s_strain_deterministic_high_strain_and_unparameterized_boron() -> None:
    lig = _synthetic_ibuprofen()
    before_sdf = Chem.MolToMolBlock(lig)

    res1 = evaluate_dual_mmff94s_strain(
        ligand_mol=lig,
        parent_state_id="synth-state-ibuprofen",
        conformer_seed=20261119,
        conformer_budget=15,
    )
    res2 = evaluate_dual_mmff94s_strain(
        ligand_mol=lig,
        parent_state_id="synth-state-ibuprofen",
        conformer_seed=20261119,
        conformer_budget=15,
    )
    assert Chem.MolToMolBlock(lig) == before_sdf
    assert res1.diagnostic is not None
    assert res2.diagnostic is not None
    assert res1.diagnostic == res2.diagnostic  # deterministic across runs
    assert res1.diagnostic.hydrogen_policy == HYDROGEN_POLICY
    assert res1.check.status is DiagnosticStatus.PASS
    assert res1.diagnostic.delta_e_ref_kcal_mol <= 10.0

    # Distort ligand severely and keep heavy atoms tethered to trigger high strain flag
    strained = Chem.Mol(lig)
    conf = strained.GetConformer()
    # Pull atom 0 far from atom 1 so heavy-atom tether retains high internal tension
    p1 = conf.GetAtomPosition(1)
    conf.SetAtomPosition(0, (p1.x + 2.6, p1.y, p1.z))
    strained_res = evaluate_dual_mmff94s_strain(
        ligand_mol=strained,
        parent_state_id="synth-state-ibuprofen",
        conformer_seed=20261119,
        conformer_budget=10,
        strain_flag_threshold_kcal_mol=10.0,
    )
    assert strained_res.diagnostic is not None
    assert strained_res.diagnostic.delta_e_ref_kcal_mol > 10.0
    assert strained_res.check.status is DiagnosticStatus.FAIL
    assert any(w.code is WarningCode.POSE_QUALITY_HIGH_STRAIN for w in strained_res.warnings)

    # Unparameterizable boron molecule must NOT silently downgrade to UFF
    boron = Chem.AddHs(Chem.MolFromSmiles("c1ccccc1B(O)O"))
    params = AllChem.ETKDGv3()
    params.randomSeed = 20261119
    assert AllChem.EmbedMolecule(boron, params) == 0
    boron_res = evaluate_dual_mmff94s_strain(
        ligand_mol=boron,
        parent_state_id="synth-state-boronic",
        conformer_seed=20261119,
        conformer_budget=10,
    )
    assert boron_res.diagnostic is None
    assert boron_res.check.status is DiagnosticStatus.NOT_EVALUABLE
    assert any(
        w.code is WarningCode.POSE_QUALITY_MMFF94S_UNPARAMETERIZED for w in boron_res.warnings
    )


def test_flex_sidechain_geometry_checks_bond_chirality_and_clash() -> None:
    # Synthetic THR A:5 (chiral CA and CB) + distant rigid GLY A:10
    crystal_pdb = (
        "ATOM      1  N   THR A   5      -0.500  -1.350   0.250  1.00  0.00           N  \n"
        "ATOM      2  CA  THR A   5       0.000   0.000   0.000  1.00  0.00           C  \n"
        "ATOM      3  C   THR A   5      -0.550   0.500  -1.320  1.00  0.00           C  \n"
        "ATOM      4  O   THR A   5      -0.100   1.550  -1.780  1.00  0.00           O  \n"
        "ATOM      5  CB  THR A   5       1.530   0.000   0.000  1.00  0.00           C  \n"
        "ATOM      6  OG1 THR A   5       2.040   1.320   0.200  1.00  0.00           O  \n"
        "ATOM      7  CG2 THR A   5       2.040  -0.500  -1.350  1.00  0.00           C  \n"
        "ATOM      8  CA  GLY A  10       8.000   0.000   0.000  1.00  0.00           C  \n"
        "END\n"
    )
    loc = [ResidueLocator(chain_id="A", residue_name="THR", sequence_number=5)]

    # 1. Clean identical geometry -> all pass
    ok = {
        c.check_id: c
        for c in evaluate_flex_sidechain_geometry(
            crystal_receptor_pdb=crystal_pdb,
            coupled_receptor_pdb=crystal_pdb,
            flex_residues=loc,
        )
    }
    assert ok["flex_sidechain_bond_lengths"].status is DiagnosticStatus.PASS
    assert ok["flex_sidechain_chirality"].status is DiagnosticStatus.PASS
    assert ok["flex_sidechain_receptor_clash"].status is DiagnosticStatus.PASS

    # 2. Torn CB-OG1 bond (stretch OG1 by +1.0 A) -> bond_lengths FAIL
    torn_pdb = crystal_pdb.replace("2.040   1.320   0.200", "2.040   2.320   0.200")
    torn = {
        c.check_id: c
        for c in evaluate_flex_sidechain_geometry(
            crystal_receptor_pdb=crystal_pdb,
            coupled_receptor_pdb=torn_pdb,
            flex_residues=loc,
        )
    }
    assert torn["flex_sidechain_bond_lengths"].status is DiagnosticStatus.FAIL

    # 3. Swap OG1 and CG2 coordinates -> CB chiral inversion -> chirality FAIL
    swapped_pdb = crystal_pdb.replace(
        "ATOM      6  OG1 THR A   5       2.040   1.320   0.200",
        "ATOM      6  OG1 THR A   5       2.040  -0.500  -1.350",
    ).replace(
        "ATOM      7  CG2 THR A   5       2.040  -0.500  -1.350",
        "ATOM      7  CG2 THR A   5       2.040   1.320   0.200",
    )
    inv = {
        c.check_id: c
        for c in evaluate_flex_sidechain_geometry(
            crystal_receptor_pdb=crystal_pdb,
            coupled_receptor_pdb=swapped_pdb,
            flex_residues=loc,
        )
    }
    assert inv["flex_sidechain_chirality"].status is DiagnosticStatus.FAIL

    # 4. Distal CG2 placed 1.0 A from rigid GLY A:10 CA -> clash FAIL
    clash_pdb = crystal_pdb.replace("8.000   0.000   0.000", "2.500  -0.500  -1.350")
    clashed = {
        c.check_id: c
        for c in evaluate_flex_sidechain_geometry(
            crystal_receptor_pdb=crystal_pdb,
            coupled_receptor_pdb=clash_pdb,
            flex_residues=loc,
        )
    }
    assert clashed["flex_sidechain_receptor_clash"].status is DiagnosticStatus.FAIL


def test_reconstruct_ligand_mol_from_meeko_pdbqt_and_conformer_sdf(tmp_path: Path) -> None:
    meeko = import_module("meeko")
    lig = _synthetic_ibuprofen()
    sdf_path = tmp_path / "conformer.sdf"
    writer = Chem.SDWriter(str(sdf_path))
    writer.write(lig)
    writer.close()

    prep = meeko.MoleculePreparation()
    setups = prep.prepare(lig)
    pdbqt_str, is_ok, err = meeko.PDBQTWriterLegacy.write_string(setups[0])
    assert is_ok, err
    pose_path = tmp_path / "pose_1.pdbqt"
    pose_path.write_text(pdbqt_str, encoding="utf-8")

    reconstructed, smiles = reconstruct_ligand_mol_from_pose(
        pose_path=pose_path,
        conformer_path=sdf_path,
    )
    assert reconstructed.GetNumAtoms() == lig.GetNumAtoms()
    assert "C(=O)O" in smiles
