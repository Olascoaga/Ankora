"""Regression tests for D2/D4 chemistry, stereochemistry, insertion-code, and mmCIF alignment.

All molecular coordinates, mmCIF blocks, and PDB fixtures in this file are explicitly synthetic.
"""

from __future__ import annotations

import json
import math
import subprocess
import sys
from importlib import import_module
from pathlib import Path
from typing import Any

import gemmi
import pytest

from ankora_backend.adapters.engines.gnina import GninaPdbqtPose, require_matching_topology
from ankora_backend.adapters.interactions.prolif_adapter import ProlifInteractionAdapter
from ankora_backend.domain.errors import AnkoraDomainError
from ankora_backend.persistence.artifact_store import StructureArtifactStore
from ankora_backend.persistence.ligand_store import LigandArtifactStore
from ankora_backend.schemas.ligands import ExtractLigandRequest, LigandLocator
from ankora_backend.schemas.pose_interactions import InteractionProfile
from ankora_backend.schemas.receptors import (
    ComponentAction,
    IssueDecision,
    ReceptorDecisionAction,
    ReceptorIssueKind,
    ReceptorPreparationRequest,
)
from ankora_backend.schemas.structures import StructureFormat, StructureSource
from ankora_backend.services.ligand_extraction import extract_crystallographic_ligand
from ankora_backend.services.receptor_inspection import inspect_receptor
from ankora_backend.services.receptor_preparation import _build_selected_receptor
from ankora_backend.services.receptor_protonation import build_protonation_analysis
from ankora_backend.services.structure_inspection import import_structure_bytes

Chem: Any = import_module("rdkit.Chem")
AllChem: Any = import_module("rdkit.Chem.AllChem")


def _meeko_pdbqt(mol: Any) -> str:
    meeko = import_module("meeko")
    prep = meeko.MoleculePreparation()
    setups = prep.prepare(mol)
    text, ok, err = meeko.PDBQTWriterLegacy.write_string(setups[0])
    assert ok, err
    return str(text)


def _mirror_z_pdbqt(pdbqt_text: str) -> str:
    """Invert Z coordinate of every ATOM/HETATM line without altering REMARK SMILES."""
    out: list[str] = []
    for line in pdbqt_text.splitlines():
        if line.startswith(("ATOM  ", "HETATM")) and len(line) >= 54:
            z = float(line[46:54])
            line = f"{line[:46]}{-z:8.3f}{line[54:]}"
        out.append(line)
    return "\n".join(out) + "\n"


def test_gnina_and_prolif_reject_3d_inverted_enantiomer_despite_stale_remark_smiles(
    tmp_path: Path,
) -> None:
    """D2-003/D4-007: AssignStereochemistryFrom3D rejects 3D mirror-inverted enantiomers."""
    mol = Chem.AddHs(Chem.MolFromSmiles("C[C@H](O)F"))
    AllChem.EmbedMolecule(mol, randomSeed=42)
    conformer_sdf = (Chem.MolToMolBlock(mol) + "\n$$$$\n").encode("utf-8")
    pdbqt_valid = _meeko_pdbqt(mol)
    pdbqt_inverted = _mirror_z_pdbqt(pdbqt_valid)

    # Valid pose passes GNINA topology guard
    require_matching_topology(
        GninaPdbqtPose(
            mode=1,
            minimized_affinity_kcal_mol=-5.0,
            cnn_score=0.8,
            cnn_affinity=6.0,
            cnn_vs=4.8,
            pdbqt=pdbqt_valid.encode("utf-8"),
        ),
        conformer_sdf,
    )

    # Mirror-inverted 3D enantiomer MUST fail closed in GNINA topology guard
    with pytest.raises(AnkoraDomainError) as gnina_exc:
        require_matching_topology(
            GninaPdbqtPose(
                mode=1,
                minimized_affinity_kcal_mol=-5.0,
                cnn_score=0.8,
                cnn_affinity=6.0,
                cnn_vs=4.8,
                pdbqt=pdbqt_inverted.encode("utf-8"),
            ),
            conformer_sdf,
        )
    assert gnina_exc.value.code == "GNINA_POSE_TOPOLOGY_MISMATCH"

    # Mirror-inverted 3D enantiomer MUST ALSO fail closed in ProlifInteractionAdapter
    pose_path = tmp_path / "inverted.pdbqt"
    conf_path = tmp_path / "conformer.sdf"
    rec_path = tmp_path / "receptor.pdb"
    pose_path.write_text(pdbqt_inverted, encoding="utf-8")
    conf_path.write_bytes(conformer_sdf)
    rec_path.write_text(
        "ATOM      1  N   ALA A   1      20.000  20.000  20.000  1.00 20.00           N  \n"
        "ATOM      2  CA  ALA A   1      21.458  20.000  20.000  1.00 20.00           C  \n"
        "END\n",
        encoding="utf-8",
    )
    with pytest.raises(AnkoraDomainError) as prolif_exc:
        ProlifInteractionAdapter().analyze(
            pose_path=pose_path,
            conformer_path=conf_path,
            receptor_path=rec_path,
            profile=InteractionProfile(interactions=["HBDonor"]),
        )
    assert prolif_exc.value.code == "POSE_INTERACTION_TOPOLOGY_MISMATCH"


def _build_aligned_methanol_for_od1(od1_xyz: tuple[float, float, float]) -> Any:
    """Build synthetic methanol with O 2.75 A from OD1 and O-H pointing directly at OD1."""
    ox, oy, oz = od1_xyz
    mol = Chem.AddHs(Chem.MolFromSmiles("CO"))
    AllChem.EmbedMolecule(mol, randomSeed=7)
    conf = mol.GetConformer()
    # Identify C (idx 0), O (idx 1), H on O (bonded to O), and 3 H on C
    o_idx = next(a.GetIdx() for a in mol.GetAtoms() if a.GetSymbol() == "O")
    c_idx = next(a.GetIdx() for a in mol.GetAtoms() if a.GetSymbol() == "C")
    ho_idx = next(
        n.GetIdx() for n in mol.GetAtomWithIdx(o_idx).GetNeighbors() if n.GetSymbol() == "H"
    )
    ch_indices = [
        n.GetIdx() for n in mol.GetAtomWithIdx(c_idx).GetNeighbors() if n.GetSymbol() == "H"
    ]
    # Place O at (ox + 2.75, oy, oz), H_O along -X toward OD1 (linear 180 deg H-bond!)
    conf.SetAtomPosition(o_idx, (ox + 2.75, oy, oz))
    conf.SetAtomPosition(ho_idx, (ox + 1.79, oy, oz))
    # Place C at tetrahedral ~109.5 deg off O-H axis
    conf.SetAtomPosition(c_idx, (ox + 2.75 + 0.48, oy + 1.35, oz))
    cx, cy, cz = ox + 2.75 + 0.48, oy + 1.35, oz
    offsets = [(0.9, 0.5, 0.3), (-0.4, 0.8, 0.7), (-0.4, 0.8, -0.7)]
    for h_idx, (dx, dy, dz) in zip(ch_indices, offsets, strict=True):
        norm = math.sqrt(dx * dx + dy * dy + dz * dz)
        conf.SetAtomPosition(
            h_idx, (cx + 1.09 * dx / norm, cy + 1.09 * dy / norm, cz + 1.09 * dz / norm)
        )
    return mol


def test_prolif_preserves_insertion_code_colliding_residues(tmp_path: Path) -> None:
    """D4-001: ASP A:100 and ASP A:100B must not overwrite each other in ProLIF ResidueGroup."""
    # Synthetic receptor with ASP A:100 (OD1 at 5.20, 5.28, 1.15) AND ASP A:100B 30 A away
    receptor_colliding = (
        "ATOM      1  N   ASP A 100       3.320   1.550   0.000  1.00 20.00           N  \n"
        "ATOM      2  CA  ASP A 100       3.950   2.860   0.000  1.00 20.00           C  \n"
        "ATOM      3  C   ASP A 100       5.460   2.750   0.000  1.00 20.00           C  \n"
        "ATOM      4  O   ASP A 100       6.050   1.680   0.000  1.00 20.00           O  \n"
        "ATOM      5  CB  ASP A 100       3.450   3.680   1.190  1.00 20.00           C  \n"
        "ATOM      6  CG  ASP A 100       3.980   5.100   1.200  1.00 20.00           C  \n"
        "ATOM      7  OD1 ASP A 100       5.200   5.280   1.150  1.00 20.00           O  \n"
        "ATOM      8  OD2 ASP A 100       3.160   6.040   1.250  1.00 20.00           O1-\n"
        "ATOM      9  N   ASP A 100B     33.320   1.550   0.000  1.00 20.00           N  \n"
        "ATOM     10  CA  ASP A 100B     33.950   2.860   0.000  1.00 20.00           C  \n"
        "ATOM     11  C   ASP A 100B     35.460   2.750   0.000  1.00 20.00           C  \n"
        "ATOM     12  O   ASP A 100B     36.050   1.680   0.000  1.00 20.00           O  \n"
        "ATOM     13  CB  ASP A 100B     33.450   3.680   1.190  1.00 20.00           C  \n"
        "ATOM     14  CG  ASP A 100B     33.980   5.100   1.200  1.00 20.00           C  \n"
        "ATOM     15  OD1 ASP A 100B     35.200   5.280   1.150  1.00 20.00           O  \n"
        "ATOM     16  OD2 ASP A 100B     33.160   6.040   1.250  1.00 20.00           O1-\n"
        "END\n"
    )
    receptor_control = receptor_colliding.replace("ASP A 100B", "ASP A 102 ")

    methanol = _build_aligned_methanol_for_od1((5.200, 5.280, 1.150))
    pose_path = tmp_path / "methanol.pdbqt"
    conf_path = tmp_path / "methanol.sdf"
    rec_coll_path = tmp_path / "rec_coll.pdb"
    rec_ctrl_path = tmp_path / "rec_ctrl.pdb"
    pose_path.write_text(_meeko_pdbqt(methanol), encoding="utf-8")
    conf_path.write_text(Chem.MolToMolBlock(methanol) + "\n$$$$\n", encoding="utf-8")
    rec_coll_path.write_text(receptor_colliding, encoding="utf-8")
    rec_ctrl_path.write_text(receptor_control, encoding="utf-8")

    profile = InteractionProfile(interactions=["HBDonor"])
    ctrl_contacts, _ = ProlifInteractionAdapter().analyze(
        pose_path=pose_path,
        conformer_path=conf_path,
        receptor_path=rec_ctrl_path,
        profile=profile,
    )
    coll_contacts, _ = ProlifInteractionAdapter().analyze(
        pose_path=pose_path,
        conformer_path=conf_path,
        receptor_path=rec_coll_path,
        profile=profile,
    )

    assert len(ctrl_contacts) >= 1
    assert len(coll_contacts) == len(ctrl_contacts)
    assert any(
        c.detector_type == "HBDonor"
        and c.residue.chain_id == "A"
        and c.residue.residue_name == "ASP"
        and c.residue.sequence_number == 100
        and c.residue.insertion_code == ""
        for c in coll_contacts
    )


def test_pdb2pqr_worker_and_protonation_analysis_preserve_insertion_codes(tmp_path: Path) -> None:
    """D4-002: PROPKA pKa assignment & verification must respect insertion codes."""
    # Synthetic peptide chain with colliding insertion codes:
    # ALA 99 -> ASP 100 -> ASP 100B -> HIS 102 -> HIS 102B -> ALA 103
    pdb_text = (
        "ATOM      1  N   ALA A  99       0.000   0.000   0.000  1.00 20.00           N  \n"
        "ATOM      2  CA  ALA A  99       1.458   0.000   0.000  1.00 20.00           C  \n"
        "ATOM      3  C   ALA A  99       2.009   1.420   0.000  1.00 20.00           C  \n"
        "ATOM      4  O   ALA A  99       1.251   2.390   0.000  1.00 20.00           O  \n"
        "ATOM      5  CB  ALA A  99       1.986  -0.760  -1.217  1.00 20.00           C  \n"
        "ATOM      6  N   ASP A 100       3.320   1.550   0.000  1.00 20.00           N  \n"
        "ATOM      7  CA  ASP A 100       3.950   2.860   0.000  1.00 20.00           C  \n"
        "ATOM      8  C   ASP A 100       5.460   2.750   0.000  1.00 20.00           C  \n"
        "ATOM      9  O   ASP A 100       6.050   1.680   0.000  1.00 20.00           O  \n"
        "ATOM     10  CB  ASP A 100       3.450   3.680   1.190  1.00 20.00           C  \n"
        "ATOM     11  CG  ASP A 100       3.980   5.100   1.200  1.00 20.00           C  \n"
        "ATOM     12  OD1 ASP A 100       5.200   5.280   1.150  1.00 20.00           O  \n"
        "ATOM     13  OD2 ASP A 100       3.160   6.040   1.250  1.00 20.00           O  \n"
        "ATOM     14  N   ASP A 100B      6.080   3.920   0.000  1.00 20.00           N  \n"
        "ATOM     15  CA  ASP A 100B      7.520   4.000   0.000  1.00 20.00           C  \n"
        "ATOM     16  C   ASP A 100B      8.050   5.420   0.000  1.00 20.00           C  \n"
        "ATOM     17  O   ASP A 100B      7.300   6.390   0.000  1.00 20.00           O  \n"
        "ATOM     18  CB  ASP A 100B      8.050   3.240  -1.220  1.00 20.00           C  \n"
        "ATOM     19  CG  ASP A 100B      9.560   3.200  -1.250  1.00 20.00           C  \n"
        "ATOM     20  OD1 ASP A 100B     10.160   4.290  -1.200  1.00 20.00           O  \n"
        "ATOM     21  OD2 ASP A 100B     10.130   2.090  -1.320  1.00 20.00           O  \n"
        "ATOM     22  N   HIS A 102       9.360   5.550   0.000  1.00 20.00           N  \n"
        "ATOM     23  CA  HIS A 102       9.990   6.860   0.000  1.00 20.00           C  \n"
        "ATOM     24  C   HIS A 102      11.500   6.750   0.000  1.00 20.00           C  \n"
        "ATOM     25  O   HIS A 102      12.090   5.680   0.000  1.00 20.00           O  \n"
        "ATOM     26  CB  HIS A 102       9.490   7.680   1.190  1.00 20.00           C  \n"
        "ATOM     27  CG  HIS A 102      10.020   9.080   1.200  1.00 20.00           C  \n"
        "ATOM     28  ND1 HIS A 102      11.350   9.380   1.150  1.00 20.00           N  \n"
        "ATOM     29  CD2 HIS A 102       9.400  10.280   1.260  1.00 20.00           C  \n"
        "ATOM     30  CE1 HIS A 102      11.520  10.690   1.180  1.00 20.00           C  \n"
        "ATOM     31  NE2 HIS A 102      10.350  11.270   1.250  1.00 20.00           N  \n"
        "ATOM     32  N   HIS A 102B     12.120   7.920   0.000  1.00 20.00           N  \n"
        "ATOM     33  CA  HIS A 102B     13.560   8.000   0.000  1.00 20.00           C  \n"
        "ATOM     34  C   HIS A 102B     14.090   9.420   0.000  1.00 20.00           C  \n"
        "ATOM     35  O   HIS A 102B     13.340  10.390   0.000  1.00 20.00           O  \n"
        "ATOM     36  CB  HIS A 102B     14.090   7.240  -1.220  1.00 20.00           C  \n"
        "ATOM     37  CG  HIS A 102B     15.590   7.200  -1.250  1.00 20.00           C  \n"
        "ATOM     38  ND1 HIS A 102B     16.350   8.330  -1.200  1.00 20.00           N  \n"
        "ATOM     39  CD2 HIS A 102B     16.460   6.150  -1.320  1.00 20.00           C  \n"
        "ATOM     40  CE1 HIS A 102B     17.620   7.980  -1.240  1.00 20.00           C  \n"
        "ATOM     41  NE2 HIS A 102B     17.710   6.660  -1.310  1.00 20.00           N  \n"
        "ATOM     42  N   ALA A 103      15.400   9.550   0.000  1.00 20.00           N  \n"
        "ATOM     43  CA  ALA A 103      16.030  10.860   0.000  1.00 20.00           C  \n"
        "ATOM     44  C   ALA A 103      17.540  10.750   0.000  1.00 20.00           C  \n"
        "ATOM     45  O   ALA A 103      18.130   9.680   0.000  1.00 20.00           O  \n"
        "ATOM     46  OXT ALA A 103      18.100  11.850   0.000  1.00 20.00           O  \n"
        "ATOM     47  CB  ALA A 103      15.530  11.680   1.190  1.00 20.00           C  \n"
        "END\n"
    )
    inp = tmp_path / "icode_rec.pdb"
    pqr = tmp_path / "icode_rec.pqr"
    out_pdb = tmp_path / "icode_rec_out.pdb"
    inp.write_text(pdb_text, encoding="utf-8")

    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "ankora_backend.adapters.tools.pdb2pqr_worker",
            "--input",
            str(inp),
            "--pqr-output",
            str(pqr),
            "--pdb-output",
            str(out_pdb),
            "--ph",
            "2.5",
            "--force-field",
            "AMBER",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    report = json.loads(proc.stdout)
    state_by_key = {
        (
            item["chain_id"],
            item["residue_name"],
            item["sequence_number"],
            item["insertion_code"],
        ): item["state"]
        for item in report["output_states"]
    }
    assert state_by_key[("A", "ASP", 100, "")] == "ASH"
    assert state_by_key[("A", "ASP", 100, "B")] == "ASH"
    assert state_by_key[("A", "HIS", 102, "")] == "HIP"
    assert state_by_key[("A", "HIS", 102, "B")] == "HIP"

    # Also verify build_protonation_analysis catches non-override PROPKA-vs-output mismatch
    store = StructureArtifactStore(tmp_path / "store")
    rec = import_structure_bytes(
        content=pdb_text.encode("utf-8"),
        filename="icode_rec.pdb",
        source=StructureSource.LOCAL,
        source_uri=None,
        store=store,
    )
    inspection = inspect_receptor(artifact_id=rec.artifact.artifact_id, store=store)
    analysis = build_protonation_analysis(
        source_artifact_id=rec.artifact.artifact_id,
        input_path=inp,
        inspection=inspection,
        structure_store=store,
        worker_report=report,
        ph=2.5,
        force_field="AMBER",
        tool_version="pdb2pqr test",
        overrides=[],
    )
    assert len(analysis.proposals) >= 4

    tampered = json.loads(json.dumps(report))
    for item in tampered["output_states"]:
        if item["residue_name"] == "HIS" and item["insertion_code"] == "B":
            item["state"] = "HID"
    with pytest.raises(AnkoraDomainError, match="PROPKA titration decision"):
        build_protonation_analysis(
            source_artifact_id=rec.artifact.artifact_id,
            input_path=inp,
            inspection=inspection,
            structure_store=store,
            worker_report=tampered,
            ph=2.5,
            force_field="AMBER",
            tool_version="pdb2pqr test",
            overrides=[],
        )


def test_mmcif_ligand_extraction_normalizes_uppercase_bond_orders_and_fails_closed(
    tmp_path: Path,
) -> None:
    """D4-008: uppercase wwPDB 'DOUB' extracts acetone (C3H6O), unknown order raises 422."""
    def _make_cif(bond_order: str) -> bytes:
        return (
            "data_SYNTH_ACE\n"
            "loop_\n"
            "_chem_comp_atom.comp_id\n"
            "_chem_comp_atom.atom_id\n"
            "_chem_comp_atom.type_symbol\n"
            "_chem_comp_atom.charge\n"
            "ACE C1 C 0\n"
            "ACE C2 C 0\n"
            "ACE C3 C 0\n"
            "ACE O1 O 0\n"
            "loop_\n"
            "_chem_comp_bond.comp_id\n"
            "_chem_comp_bond.atom_id_1\n"
            "_chem_comp_bond.atom_id_2\n"
            "_chem_comp_bond.value_order\n"
            "ACE C1 C2 SING\n"
            "ACE C2 C3 SING\n"
            f"ACE C2 O1 {bond_order}\n"
            "loop_\n"
            "_atom_site.group_PDB\n"
            "_atom_site.id\n"
            "_atom_site.type_symbol\n"
            "_atom_site.label_atom_id\n"
            "_atom_site.label_alt_id\n"
            "_atom_site.label_comp_id\n"
            "_atom_site.label_asym_id\n"
            "_atom_site.label_entity_id\n"
            "_atom_site.label_seq_id\n"
            "_atom_site.pdbx_PDB_ins_code\n"
            "_atom_site.Cartn_x\n"
            "_atom_site.Cartn_y\n"
            "_atom_site.Cartn_z\n"
            "_atom_site.occupancy\n"
            "_atom_site.B_iso_or_equiv\n"
            "_atom_site.auth_seq_id\n"
            "_atom_site.auth_comp_id\n"
            "_atom_site.auth_asym_id\n"
            "_atom_site.auth_atom_id\n"
            "_atom_site.pdbx_PDB_model_num\n"
            "HETATM 1 C C1 . ACE A 1 . ? 0.000 0.000 0.000 1.00 20.00 201 ACE A C1 1\n"
            "HETATM 2 C C2 . ACE A 1 . ? 1.500 0.000 0.000 1.00 20.00 201 ACE A C2 1\n"
            "HETATM 3 C C3 . ACE A 1 . ? 2.250 1.299 0.000 1.00 20.00 201 ACE A C3 1\n"
            "HETATM 4 O O1 . ACE A 1 . ? 2.100 -1.060 0.000 1.00 20.00 201 ACE A O1 1\n"
        ).encode()

    s_store = StructureArtifactStore(tmp_path / "structures")
    l_store = LigandArtifactStore(tmp_path / "ligands")
    src_ok = import_structure_bytes(
        content=_make_cif("DOUB"),
        filename="synth_acetone.cif",
        source=StructureSource.LOCAL,
        source_uri=None,
        store=s_store,
    )
    req = ExtractLigandRequest(
        locator=LigandLocator(
            chain_id="A",
            component_name="ACE",
            sequence_number=201,
            insertion_code="",
        )
    )
    lig = extract_crystallographic_ligand(
        source_artifact_id=src_ok.artifact.artifact_id,
        request=req,
        structure_store=s_store,
        ligand_store=l_store,
    )
    assert lig.inspection.formula == "C3H6O"
    assert lig.inspection.canonical_smiles == "CC(C)=O"

    # Unsupported value_order must fail closed instead of downgrading to SINGLE
    src_bad = import_structure_bytes(
        content=_make_cif("UNKNOWN_ORDER"),
        filename="synth_bad_order.cif",
        source=StructureSource.LOCAL,
        source_uri=None,
        store=s_store,
    )
    with pytest.raises(AnkoraDomainError) as bad_exc:
        extract_crystallographic_ligand(
            source_artifact_id=src_bad.artifact.artifact_id,
            request=req,
            structure_store=s_store,
            ligand_store=l_store,
        )
    assert bad_exc.value.code == "LIGAND_BOND_ORDER_UNSUPPORTED"


def test_receptor_inspection_exposes_all_altlocs_on_microheterogeneity(tmp_path: Path) -> None:
    """D4-013: microheterogeneity (AMET/BMSE at A:100) exposes both A and B altlocs."""
    pdb = (
        b"ATOM      1  N  AMET A 100       0.000   0.000   0.000  0.50 20.00           N  \n"
        b"ATOM      2  CA AMET A 100       1.458   0.000   0.000  0.50 20.00           C  \n"
        b"ATOM      3  N  BMSE A 100       0.010   0.020   0.000  0.50 20.00           N  \n"
        b"ATOM      4  CA BMSE A 100       1.468   0.020   0.000  0.50 20.00           C  \n"
        b"END\n"
    )
    store = StructureArtifactStore(tmp_path)
    src = import_structure_bytes(
        content=pdb,
        filename="microhet.pdb",
        source=StructureSource.LOCAL,
        source_uri=None,
        store=store,
    )
    inspection = inspect_receptor(artifact_id=src.artifact.artifact_id, store=store)
    alt_issues = [
        item for item in inspection.issues if item.kind is ReceptorIssueKind.ALTERNATE_LOCATION
    ]
    assert len(alt_issues) == 1
    assert alt_issues[0].alternate_locations == ["A", "B"]

    # Selecting altloc 'B' keeps BMSE and cleanly drops emptied AMET
    req = ReceptorPreparationRequest(
        selected_chains=["A"],
        water_action=ComponentAction.REMOVE,
        component_decisions=[],
        issue_decisions=[
            IssueDecision(
                issue_id=alt_issues[0].issue_id,
                action=ReceptorDecisionAction.REPAIR,
                selected_altloc="B",
            )
        ],
    )
    selected_bytes = _build_selected_receptor(
        content=pdb,
        structure_format=StructureFormat.PDB,
        request=req,
        issue_decisions={d.issue_id: d for d in req.issue_decisions},
        issues=alt_issues,
    )
    parsed = gemmi.read_pdb_string(selected_bytes.decode("utf-8"))
    residues = list(parsed[0][0])
    assert len(residues) == 1
    assert residues[0].name == "MSE"
