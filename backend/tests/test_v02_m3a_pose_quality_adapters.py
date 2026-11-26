"""Unit and live-adapter tests for Ankora v0.2 M3a pose-quality adapters.

All structures and molecules in this module are synthetic and explicitly labelled
synthetic. Tests exercise real PoseBusters 0.6.5 and RDKit MMFF94s execution.
"""

from __future__ import annotations

from importlib import import_module
from pathlib import Path
from typing import Any

import pytest

from ankora_backend.adapters.quality import conformational_strain as strain_mod
from ankora_backend.adapters.quality.conformational_strain import (
    HYDROGEN_POLICY,
    _heavy_atom_coords,
    _in_place_rmsd,
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
from ankora_backend.domain.errors import AnkoraDomainError
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


def test_flex_sidechain_geometry_flex_to_flex_icode_missing_malformed_and_3d_oracles() -> None:
    """D2-010/D4-010/D1-002 + 3D off-origin oracles for flex_sidechain_geometry."""
    # Off-origin shifted THR A:5 (CA at 10.5, -7.25, 4.75) + covalently bonded GLY A:6 (C-N=1.33 A)
    # + non-adjacent ALA A:5E (insertion code) + second FlexRes SER A:20
    ox, oy, oz = 10.5, -7.25, 4.75

    def _line(
        serial: int,
        atom: str,
        res: str,
        chain: str,
        seq: int,
        icode: str,
        xyz: tuple[float, float, float],
        elem: str,
    ) -> str:
        x, y, z = xyz
        return (
            f"ATOM  {serial:5d} {atom:^4s} {res:>3s} {chain}{seq:4d}{icode}   "
            f"{x:8.3f}{y:8.3f}{z:8.3f}  1.00  0.00          {elem:>2s}\n"
        )

    base_lines = [
        _line(1, "N", "THR", "A", 5, " ", (ox - 0.50, oy - 1.35, oz + 0.25), "N"),
        _line(2, "CA", "THR", "A", 5, " ", (ox, oy, oz), "C"),
        _line(3, "C", "THR", "A", 5, " ", (ox - 0.55, oy + 0.50, oz - 1.32), "C"),
        _line(4, "O", "THR", "A", 5, " ", (ox - 0.10, oy + 1.55, oz - 1.78), "O"),
        _line(5, "CB", "THR", "A", 5, " ", (ox + 1.53, oy, oz), "C"),
        _line(6, "OG1", "THR", "A", 5, " ", (ox + 2.04, oy + 1.32, oz + 0.20), "O"),
        _line(7, "CG2", "THR", "A", 5, " ", (ox + 2.04, oy - 0.50, oz - 1.35), "C"),
        # Explicit hydrogen (78-char line) & no-element-column H to test hydrogen filtering
        _line(8, "HG1", "THR", "A", 5, " ", (ox + 2.80, oy + 1.32, oz + 0.20), "H"),
        (
            f"ATOM      9  H   THR A   5    "
            f"{ox - 1.10:8.3f}{oy - 1.35:8.3f}{oz + 0.25:8.3f}  1.00  0.00\n"
        ),
        # Peptide-bonded neighbor GLY A:6 (N 1.33 A from THR A:5 C; backbone must be skipped)
        _line(10, "N", "GLY", "A", 6, " ", (ox - 1.88, oy + 0.50, oz - 1.32), "N"),
        _line(11, "CA", "GLY", "A", 6, " ", (ox + 2.04, oy + 1.32, oz + 0.90), "C"),
        # Distant rigid GLY A:10
        _line(12, "CA", "GLY", "A", 10, " ", (ox + 12.0, oy, oz), "C"),
        # Second FlexRes SER A:20 initially distant
        _line(13, "N", "SER", "A", 20, " ", (ox + 20.0, oy, oz), "N"),
        _line(14, "CA", "SER", "A", 20, " ", (ox + 21.45, oy, oz), "C"),
        _line(15, "C", "SER", "A", 20, " ", (ox + 22.00, oy + 1.42, oz), "C"),
        _line(16, "CB", "SER", "A", 20, " ", (ox + 22.00, oy - 0.76, oz - 1.22), "C"),
        _line(17, "OG", "SER", "A", 20, " ", (ox + 23.40, oy - 0.76, oz - 1.22), "O"),
        "END\n",
    ]
    crystal = "".join(base_lines)
    thr_loc = ResidueLocator(chain_id="A", residue_name="THR", sequence_number=5)
    ser_loc = ResidueLocator(chain_id="A", residue_name="SER", sequence_number=20)

    # 1. Clean off-origin check: covalently bonded GLY A:6 CA at 0.70 A is backbone -> skipped!
    res_ok = {
        c.check_id: c
        for c in evaluate_flex_sidechain_geometry(
            crystal_receptor_pdb=crystal,
            coupled_receptor_pdb=crystal,
            flex_residues=[thr_loc, ser_loc],
        )
    }
    assert res_ok["flex_sidechain_bond_lengths"].status is DiagnosticStatus.PASS
    assert res_ok["flex_sidechain_bond_lengths"].value == pytest.approx(0.0, abs=1e-6)
    assert res_ok["flex_sidechain_chirality"].status is DiagnosticStatus.PASS
    assert res_ok["flex_sidechain_receptor_clash"].status is DiagnosticStatus.PASS

    # 2. Flex-to-flex interpenetration: move SER A:20 OG to 0.05 A from THR A:5 OG1 -> FAIL
    flex_clash_lines = list(base_lines)
    flex_clash_lines[-2] = _line(
        17, "OG", "SER", "A", 20, " ", (ox + 2.09, oy + 1.32, oz + 0.20), "O"
    )
    res_f2f = {
        c.check_id: c
        for c in evaluate_flex_sidechain_geometry(
            crystal_receptor_pdb=crystal,
            coupled_receptor_pdb="".join(flex_clash_lines),
            flex_residues=[thr_loc, ser_loc],
        )
    }
    assert res_f2f["flex_sidechain_receptor_clash"].status is DiagnosticStatus.FAIL
    assert res_f2f["flex_sidechain_receptor_clash"].value == pytest.approx(0.05, abs=1e-3)

    # 3. Insertion-code clash (D4-010): non-bonded ALA A:5E O at 0.80 A from THR A:5 OG1 -> FAIL
    icode_clash_lines = base_lines[:-1] + [
        _line(18, "N", "ALA", "A", 5, "E", (ox + 8.0, oy + 8.0, oz + 8.0), "N"),
        _line(19, "O", "ALA", "A", 5, "E", (ox + 2.84, oy + 1.32, oz + 0.20), "O"),
        "END\n",
    ]
    res_icode = {
        c.check_id: c
        for c in evaluate_flex_sidechain_geometry(
            crystal_receptor_pdb=crystal,
            coupled_receptor_pdb="".join(icode_clash_lines),
            flex_residues=[thr_loc],
        )
    }
    assert res_icode["flex_sidechain_receptor_clash"].status is DiagnosticStatus.FAIL
    assert res_icode["flex_sidechain_receptor_clash"].value == pytest.approx(0.80, abs=1e-3)
    assert "A:5E:O" in res_icode["flex_sidechain_receptor_clash"].message

    # 4. Exact 1.95 A covalent cutoff boundary (kills d_cryst < 1.95) + CA chiral inversion
    met_loc = ResidueLocator(chain_id="A", residue_name="MET", sequence_number=50)
    b195_cryst = (
        _line(1, "CG", "MET", "A", 50, " ", (0.000, 0.000, 0.000), "C")
        + _line(2, "SD", "MET", "A", 50, " ", (1.950, 0.000, 0.000), "S")
        + "END\n"
    )
    b195_moved = (
        _line(1, "CG", "MET", "A", 50, " ", (0.000, 0.000, 0.000), "C")
        + _line(2, "SD", "MET", "A", 50, " ", (2.150, 0.000, 0.000), "S")
        + "END\n"
    )
    res_b195 = {
        c.check_id: c
        for c in evaluate_flex_sidechain_geometry(
            crystal_receptor_pdb=b195_cryst,
            coupled_receptor_pdb=b195_moved,
            flex_residues=[met_loc],
        )
    }
    assert res_b195["flex_sidechain_bond_lengths"].status is DiagnosticStatus.FAIL
    assert res_b195["flex_sidechain_bond_lengths"].value == pytest.approx(0.20, abs=1e-3)

    # Invert CA chirality off-origin by swapping N and C around CA (kills signed-volume mutants)
    ca_inv_lines = list(base_lines)
    ca_inv_lines[0] = _line(1, "N", "THR", "A", 5, " ", (ox - 0.55, oy + 0.50, oz - 1.32), "N")
    ca_inv_lines[2] = _line(3, "C", "THR", "A", 5, " ", (ox - 0.50, oy - 1.35, oz + 0.25), "C")
    res_cainv = {
        c.check_id: c
        for c in evaluate_flex_sidechain_geometry(
            crystal_receptor_pdb=crystal,
            coupled_receptor_pdb="".join(ca_inv_lines),
            flex_residues=[thr_loc],
        )
    }
    assert res_cainv["flex_sidechain_chirality"].status is DiagnosticStatus.FAIL
    assert "A:5:CA" in res_cainv["flex_sidechain_chirality"].message

    # 5. Missing FlexRes residue (present in crystal, missing in coupled & vice versa) -> all 3 NE
    missing_loc = ResidueLocator(chain_id="A", residue_name="SER", sequence_number=99)
    res_miss = {
        c.check_id: c
        for c in evaluate_flex_sidechain_geometry(
            crystal_receptor_pdb=crystal,
            coupled_receptor_pdb=crystal,
            flex_residues=[thr_loc, missing_loc],
        )
    }
    assert res_miss["flex_sidechain_bond_lengths"].status is DiagnosticStatus.NOT_EVALUABLE
    assert res_miss["flex_sidechain_chirality"].status is DiagnosticStatus.NOT_EVALUABLE
    assert res_miss["flex_sidechain_receptor_clash"].status is DiagnosticStatus.NOT_EVALUABLE

    # Present in crystal, absent in coupled (kills `not c_map and not m_map`)
    no_ser_coupled = "".join(line for line in base_lines if "SER A  20" not in line)
    res_miss2 = {
        c.check_id: c
        for c in evaluate_flex_sidechain_geometry(
            crystal_receptor_pdb=crystal,
            coupled_receptor_pdb=no_ser_coupled,
            flex_residues=[ser_loc],
        )
    }
    assert res_miss2["flex_sidechain_bond_lengths"].status is DiagnosticStatus.NOT_EVALUABLE
    assert res_miss2["flex_sidechain_receptor_clash"].status is DiagnosticStatus.NOT_EVALUABLE

    # 6. Malformed / non-finite / truncated PDB records must fail closed (D1-002)
    for bad_pdb in (
        crystal.replace(f"{ox + 2.04:8.3f}", "********"),
        crystal.replace(f"{ox + 2.04:8.3f}", "     nan"),
        "ATOM      1  CA  THR A   5\nEND\n",
    ):
        with pytest.raises(AnkoraDomainError) as bad_exc:
            evaluate_flex_sidechain_geometry(
                crystal_receptor_pdb=crystal,
                coupled_receptor_pdb=bad_pdb,
                flex_residues=[thr_loc],
            )
        assert bad_exc.value.code == "FLEX_GEOMETRY_PDB_INVALID"


def test_conformational_strain_untagged_alkene_unconverged_and_rmsd_oracles(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """D2-004 + D1-004 + mutation oracles for conformational_strain."""
    # 1. Untagged 3D (Z)-di-tert-butylethylene must NOT isomerize to (E) (+12.6 kcal/mol false FAIL)
    z_alkene = Chem.AddHs(Chem.MolFromSmiles(r"CC(C)(C)/C=C\C(C)(C)C"))
    params = AllChem.ETKDGv3()
    params.randomSeed = 42
    assert AllChem.EmbedMolecule(z_alkene, params) == 0
    assert AllChem.MMFFOptimizeMolecule(z_alkene, mmffVariant="MMFF94s") == 0
    untagged = Chem.MolFromPDBBlock(Chem.MolToPDBBlock(z_alkene), removeHs=True, sanitize=False)
    untagged = AllChem.AssignBondOrdersFromTemplate(
        Chem.MolFromSmiles("CC(C)(C)C=CC(C)(C)C"), untagged
    )
    Chem.SanitizeMol(untagged)
    res_z = evaluate_dual_mmff94s_strain(
        ligand_mol=untagged,
        parent_state_id="synth-z-alkene",
        conformer_seed=42,
        conformer_budget=15,
    )
    assert res_z.check.status is DiagnosticStatus.PASS
    assert res_z.diagnostic is not None
    assert res_z.diagnostic.delta_e_ref_kcal_mol < 1.0
    assert res_z.converged_free_conformer_count > 0

    # 2. Exact threshold equality delta_e == threshold must PASS (kills > -> >=)
    res_eq = evaluate_dual_mmff94s_strain(
        ligand_mol=untagged,
        parent_state_id="synth-z-alkene",
        conformer_seed=42,
        conformer_budget=15,
        strain_flag_threshold_kcal_mol=res_z.diagnostic.delta_e_ref_kcal_mol,
    )
    assert res_eq.check.status is DiagnosticStatus.PASS

    # 3. Conformer-less molecule must return NOT_EVALUABLE (kills GetNumConformers == 0.5)
    no_conf = Chem.MolFromSmiles("CCO")
    res_noconf = evaluate_dual_mmff94s_strain(
        ligand_mol=no_conf, parent_state_id="synth-no-conf", conformer_budget=5
    )
    assert res_noconf.check.status is DiagnosticStatus.NOT_EVALUABLE

    # 4. Zero converged free conformers must return NOT_EVALUABLE, never silent PASS (D1-004)
    lig = _synthetic_ibuprofen()
    monkeypatch.setattr(strain_mod, "_MAX_MINIMIZATION_ITERATIONS", 1)
    res_unconv = evaluate_dual_mmff94s_strain(
        ligand_mol=lig,
        parent_state_id="synth-ibu-unconv",
        conformer_seed=20261119,
        conformer_budget=5,
    )
    assert res_unconv.check.status is DiagnosticStatus.NOT_EVALUABLE
    assert res_unconv.diagnostic is None
    assert any(w.code is WarningCode.POSE_QUALITY_NOT_EVALUABLE for w in res_unconv.warnings)
    monkeypatch.undo()

    # 5. Exact 3D off-origin _heavy_atom_coords & _in_place_rmsd oracles (kills M10..M18)
    coords = _heavy_atom_coords(lig)
    assert len(coords) == lig.GetNumHeavyAtoms()
    assert _in_place_rmsd([], []) == 0.0
    assert _in_place_rmsd([(1.0, 2.0, 3.0)], [(1.0, 2.0, 3.0), (4.0, 5.0, 6.0)]) == 0.0
    shifted = [(x + 3.0, y - 4.0, z + 12.0) for x, y, z in coords]
    assert _in_place_rmsd(coords, shifted) == pytest.approx(13.0, abs=1e-9)
    z_only = [(x, y, z + 2.5) for x, y, z in coords]
    assert _in_place_rmsd(coords, z_only) == pytest.approx(2.5, abs=1e-9)

    # 6. Distorted H on explicit-H ibuprofen must relax freely without moving heavy atoms
    #    (kills atom.GetAtomicNum() > 1 -> >= 1 which would tether hydrogens!)
    distorted_h = Chem.Mol(lig)
    h_idx = next(a.GetIdx() for a in distorted_h.GetAtoms() if a.GetAtomicNum() == 1)
    h_conf = distorted_h.GetConformer()
    hp = h_conf.GetAtomPosition(h_idx)
    h_conf.SetAtomPosition(h_idx, (hp.x + 0.8, hp.y, hp.z))
    res_h = evaluate_dual_mmff94s_strain(
        ligand_mol=distorted_h,
        parent_state_id="synth-ibu-h-relax",
        conformer_seed=20261119,
        conformer_budget=10,
    )
    assert res_h.check.status is DiagnosticStatus.PASS
    assert res_h.diagnostic is not None
    assert res_h.diagnostic.delta_e_ref_kcal_mol < 10.0
