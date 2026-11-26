"""Tests for M6.5c (100% offline RDKit analog search, CSV/SDF/SMI, SQLite cache & MCS core RMSD).

All catalogs, SMILES, and 3D coordinates in this module are explicitly labelled synthetic.
"""

from __future__ import annotations

import socket
from hashlib import sha256
from importlib import import_module
from pathlib import Path
from typing import Any

import pytest

from ankora_backend.adapters.chemistry.analog_similarity import (
    SqliteFingerprintCache,
    parse_local_analog_catalog,
    run_offline_similarity_search,
)
from ankora_backend.adapters.chemistry.mcs_core_rmsd import (
    compute_receptor_frame_mcs_core_rmsd,
)
from ankora_backend.domain.errors import AnkoraDomainError
from ankora_backend.schemas.analog_expansion import (
    AnalogCandidateRole,
    AnalogFingerprintProfile,
    CsvCatalogSchema,
    McsCoreRmsdStatus,
)
from ankora_backend.schemas.warnings import WarningCode

Chem: Any = import_module("rdkit.Chem")
AllChem: Any = import_module("rdkit.Chem.AllChem")


def _mol_to_pdbqt_block(mol: Any, shift: tuple[float, float, float] = (0.0, 0.0, 0.0)) -> str:
    conf = mol.GetConformer()
    dx, dy, dz = shift
    lines = ["MODEL 1", "ROOT"]
    for idx in range(mol.GetNumAtoms()):
        atom = mol.GetAtomWithIdx(idx)
        sym = atom.GetSymbol()
        if sym == "H":
            continue
        pos = conf.GetAtomPosition(idx)
        ad_type = "A" if atom.GetIsAromatic() and sym == "C" else sym
        lines.append(
            f"ATOM  {idx + 1:5d}  {sym}{idx + 1:<2d} UNL     1    "
            f"{pos.x + dx:8.3f}{pos.y + dy:8.3f}{pos.z + dz:8.3f}  "
            f"1.00  0.00    +0.000 {ad_type:<2s}"
        )
    lines.extend(["ENDROOT", "TORSDOF 0", "ENDMDL"])
    return "\n".join(lines) + "\n"


def test_offline_catalog_csv_salts_chiral_dedup_cache_and_smarts_with_network_blocked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-033 §4: complete offline proof with sockets blocked, salts/enantiomers/cache verified."""

    def _forbid_network(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("Network access is strictly forbidden during offline search")

    monkeypatch.setattr(socket, "socket", _forbid_network)

    # Synthetic CSV catalog containing:
    # - exact seed (R)-1-phenylethanol (must not duplicate as analog)
    # - (S)-enantiomer (distinct stereoisomer, must be preserved!)
    # - undefined stereocenter analog
    # - salt analog (multi-fragment preserved in canonical_isomeric_smiles, stripped for search)
    # - duplicate exact isomeric row
    # - unrelated benzene-free aliphatic chain (filtered out by SMARTS / threshold)
    # - malformed SMILES + blank SMILES (explicitly recorded, never silently dropped)
    csv_text = (
        "cid,smiles\n"
        "seed_dup,C[C@H](O)c1ccccc1\n"
        "enantiomer_S,C[C@@H](O)c1ccccc1\n"
        "undef_stereo,CC(O)c1ccccc1\n"
        "para_fluoro_salt,C[C@H](O)c1ccc(F)cc1.[Na+]\n"
        "enantiomer_S_dup,C[C@@H](O)c1ccccc1\n"
        "para_methyl,C[C@H](O)c1ccc(C)cc1\n"
        "aliphatic_far,CCCCCCCCCC\n"
        "bad_row,NOT_A_SMILES\n"
        "blank_row,\n"
    )
    raw = csv_text.encode("utf-8")
    parsed = parse_local_analog_catalog(
        content=raw,
        filename="synth_catalog.csv",
        csv_schema=CsvCatalogSchema(smiles_column="smiles", id_column="cid"),
    )
    assert len(parsed.entries) == 9
    assert parsed.valid_records == 7
    assert parsed.invalid_records == 2
    bad_entries = [e for e in parsed.entries if e.parse_error is not None]
    assert {e.identifier for e in bad_entries} == {"bad_row", "blank_row"}

    salt_entry = next(e for e in parsed.entries if e.identifier == "para_fluoro_salt")
    assert salt_entry.had_multiple_fragments is True
    assert "[Na+]" in (salt_entry.canonical_isomeric_smiles or "")
    assert "[Na+]" not in (salt_entry.search_smiles or "")

    undef_entry = next(e for e in parsed.entries if e.identifier == "undef_stereo")
    assert undef_entry.undefined_stereocenter_count == 1

    cache = SqliteFingerprintCache(tmp_path / "analog_fp_cache.sqlite3")
    cat_sha = sha256(raw).hexdigest()
    profile_chiral = AnalogFingerprintProfile(radius=2, fp_size=2048, include_chirality=True)

    # First run populates SQLite FP cache
    res1 = run_offline_similarity_search(
        query_smiles="C[C@H](O)c1ccccc1",
        seed_name="synth_seed_R",
        catalog_sha256=cat_sha,
        entries=parsed.entries,
        profile=profile_chiral,
        min_tanimoto=0.25,
        top_k=3,
        smarts_filter="c1ccccc1",
        cache=cache,
    )
    assert res1.cache_hit is False
    assert res1.invalid_skipped == 2
    assert res1.hits[0].role is AnalogCandidateRole.SEED_CONTROL
    assert res1.hits[0].local_rdkit_tanimoto == pytest.approx(1.0)
    analog_hits = [h for h in res1.hits if h.role is AnalogCandidateRole.ANALOG]
    assert len(analog_hits) == 3  # truncated from 4 unique matching analogs to top_k=3
    assert res1.truncated_by_top_k is True
    assert any(w.code is WarningCode.ANALOG_SEARCH_TRUNCATED for w in res1.warnings)
    # Seed not duplicated as analog, enantiomer_S preserved, aliphatic excluded by SMARTS
    analog_ids = [h.identifier for h in analog_hits]
    assert "seed_dup" not in analog_ids
    assert "enantiomer_S" in analog_ids
    assert "aliphatic_far" not in analog_ids
    assert all(h.smarts_matched is True for h in analog_hits)

    # Second run with exact same profile hits SQLite FP cache and returns bitwise-identical order
    res2 = run_offline_similarity_search(
        query_smiles="C[C@H](O)c1ccccc1",
        seed_name="synth_seed_R",
        catalog_sha256=cat_sha,
        entries=parsed.entries,
        profile=profile_chiral,
        min_tanimoto=0.25,
        top_k=3,
        smarts_filter="c1ccccc1",
        cache=cache,
    )
    assert res2.cache_hit is True
    assert [(h.identifier, h.local_rdkit_tanimoto) for h in res2.hits] == [
        (h.identifier, h.local_rdkit_tanimoto) for h in res1.hits
    ]

    # Changing fingerprint profile invalidates cache cleanly (cache_hit == False)
    profile_r3 = AnalogFingerprintProfile(radius=3, fp_size=2048, include_chirality=True)
    res3 = run_offline_similarity_search(
        query_smiles="C[C@H](O)c1ccccc1",
        seed_name="synth_seed_R",
        catalog_sha256=cat_sha,
        entries=parsed.entries,
        profile=profile_r3,
        min_tanimoto=0.25,
        top_k=10,
        cache=cache,
    )
    assert res3.cache_hit is False

    # Invalid SMARTS fails closed with 422 ANALOG_SMARTS_INVALID
    with pytest.raises(AnkoraDomainError) as exc_info:
        run_offline_similarity_search(
            query_smiles="C[C@H](O)c1ccccc1",
            seed_name="synth_seed_R",
            catalog_sha256=cat_sha,
            entries=parsed.entries,
            profile=profile_chiral,
            min_tanimoto=0.1,
            top_k=10,
            smarts_filter="[invalid_smarts",
            cache=cache,
        )
    assert exc_info.value.code == "ANALOG_SMARTS_INVALID"


def test_receptor_frame_mcs_core_rmsd_measures_in_place_without_superposition(
    tmp_path: Path,
) -> None:
    """ADR-033 §7: 0.0 A when core stays in place, exact 5.0 A when translated (no Kabsch!)."""
    # Build synthetic 3D benzene (seed) and toluene (analog sharing exact benzene ring coords)
    seed_mol = Chem.AddHs(Chem.MolFromSmiles("c1ccccc1"))
    AllChem.EmbedMolecule(seed_mol, randomSeed=42)
    seed_mol = Chem.RemoveHs(seed_mol)

    # Construct toluene with ring atoms 0..5 at the exact same coordinates as seed_mol
    toluene = Chem.RWMol(seed_mol)
    c_idx = toluene.AddAtom(Chem.Atom(6))
    toluene.AddBond(0, c_idx, Chem.BondType.SINGLE)
    toluene_mol = toluene.GetMol()
    Chem.SanitizeMol(toluene_mol)
    conf = Chem.Conformer(toluene_mol.GetNumAtoms())
    seed_conf = seed_mol.GetConformer()
    for idx in range(6):
        conf.SetAtomPosition(idx, seed_conf.GetAtomPosition(idx))
    p0 = seed_conf.GetAtomPosition(0)
    conf.SetAtomPosition(6, (p0.x + 1.5, p0.y, p0.z))
    toluene_mol.RemoveAllConformers()
    toluene_mol.AddConformer(conf, assignId=True)

    seed_sdf = tmp_path / "seed.sdf"
    analog_sdf = tmp_path / "analog.sdf"
    seed_sdf.write_text(Chem.MolToMolBlock(seed_mol) + "\n$$$$\n", encoding="utf-8")
    analog_sdf.write_text(Chem.MolToMolBlock(toluene_mol) + "\n$$$$\n", encoding="utf-8")

    seed_pdbqt = _mol_to_pdbqt_block(seed_mol, shift=(0.0, 0.0, 0.0))
    analog_same_pdbqt = _mol_to_pdbqt_block(toluene_mol, shift=(0.0, 0.0, 0.0))
    analog_shifted_pdbqt = _mol_to_pdbqt_block(toluene_mol, shift=(5.0, 0.0, 0.0))

    # 1. Core sits in exact same receptor coordinates -> 0.0 A
    same_res = compute_receptor_frame_mcs_core_rmsd(
        seed_pose_artifact_id="seed-pose-1",
        seed_pose_sha256="1" * 64,
        seed_pose_pdbqt_text=seed_pdbqt,
        seed_conformer_path=seed_sdf,
        target_pose_artifact_id="analog-pose-same",
        target_pose_sha256="2" * 64,
        target_pose_pdbqt_text=analog_same_pdbqt,
        target_conformer_path=analog_sdf,
    )
    assert same_res.status is McsCoreRmsdStatus.EVALUATED
    assert same_res.superposition_applied is False
    assert same_res.mcs_heavy_atom_count == 6
    assert same_res.receptor_frame_rmsd_angstrom == pytest.approx(0.0, abs=1e-3)

    # 2. Core translated +5.0 A in X -> MUST report 5.0 A (never 0.0 A from ligand superposition!)
    shifted_res = compute_receptor_frame_mcs_core_rmsd(
        seed_pose_artifact_id="seed-pose-1",
        seed_pose_sha256="1" * 64,
        seed_pose_pdbqt_text=seed_pdbqt,
        seed_conformer_path=seed_sdf,
        target_pose_artifact_id="analog-pose-shifted",
        target_pose_sha256="3" * 64,
        target_pose_pdbqt_text=analog_shifted_pdbqt,
        target_conformer_path=analog_sdf,
    )
    assert shifted_res.status is McsCoreRmsdStatus.EVALUATED
    assert shifted_res.superposition_applied is False
    assert shifted_res.mcs_heavy_atom_count == 6
    assert shifted_res.receptor_frame_rmsd_angstrom == pytest.approx(5.0, abs=1e-3)

    # 3. Disjoint chemistry (no shared elements/rings: pure oxygen O=O vs benzene)
    o2_mol = Chem.MolFromSmiles("O=O")
    AllChem.EmbedMolecule(o2_mol, randomSeed=42)
    o2_sdf = tmp_path / "o2.sdf"
    o2_sdf.write_text(Chem.MolToMolBlock(o2_mol) + "\n$$$$\n", encoding="utf-8")
    o2_pdbqt = _mol_to_pdbqt_block(o2_mol)
    disjoint_res = compute_receptor_frame_mcs_core_rmsd(
        seed_pose_artifact_id="seed-pose-1",
        seed_pose_sha256="1" * 64,
        seed_pose_pdbqt_text=seed_pdbqt,
        seed_conformer_path=seed_sdf,
        target_pose_artifact_id="o2-pose",
        target_pose_sha256="4" * 64,
        target_pose_pdbqt_text=o2_pdbqt,
        target_conformer_path=o2_sdf,
    )
    assert disjoint_res.status is McsCoreRmsdStatus.NO_COMMON_SUBSTRUCTURE
    assert disjoint_res.receptor_frame_rmsd_angstrom is None
    assert disjoint_res.mcs_coverage_seed == 0.0
    assert disjoint_res.mcs_coverage_target == 0.0


def test_mcs_core_rmsd_non_planar_3d_axes_coverage_and_single_atom_mcs(tmp_path: Path) -> None:
    """Synthetic 3D non-planar oracle (D2-019): exact X/Y/Z RMSD, coverages, and 1-atom MCS."""
    seed_mol = Chem.AddHs(Chem.MolFromSmiles("c1ccccc1"))
    AllChem.EmbedMolecule(seed_mol, randomSeed=42)
    seed_mol = Chem.RemoveHs(seed_mol)

    # Place toluene ring on exact seed coords shifted off-origin so all axes contribute
    toluene = Chem.RWMol(seed_mol)
    c_idx = toluene.AddAtom(Chem.Atom(6))
    toluene.AddBond(0, c_idx, Chem.BondType.SINGLE)
    toluene_mol = toluene.GetMol()
    Chem.SanitizeMol(toluene_mol)
    conf = Chem.Conformer(toluene_mol.GetNumAtoms())
    seed_conf = seed_mol.GetConformer()
    for idx in range(6):
        p = seed_conf.GetAtomPosition(idx)
        conf.SetAtomPosition(idx, (p.x + 1.25, p.y - 2.5, p.z + 3.75))
    p0 = conf.GetAtomPosition(0)
    conf.SetAtomPosition(6, (p0.x + 1.5, p0.y + 0.2, p0.z - 0.1))
    toluene_mol.RemoveAllConformers()
    toluene_mol.AddConformer(conf, assignId=True)

    # Shift seed to the same off-origin frame before testing exact (3, -4, 12) translation
    seed_off = Chem.Mol(seed_mol)
    s_conf = seed_off.GetConformer()
    for idx in range(6):
        p = s_conf.GetAtomPosition(idx)
        s_conf.SetAtomPosition(idx, (p.x + 1.25, p.y - 2.5, p.z + 3.75))

    seed_sdf = tmp_path / "seed_off.sdf"
    toluene_sdf = tmp_path / "toluene_off.sdf"
    seed_sdf.write_text(Chem.MolToMolBlock(seed_off) + "\n$$$$\n", encoding="utf-8")
    toluene_sdf.write_text(Chem.MolToMolBlock(toluene_mol) + "\n$$$$\n", encoding="utf-8")

    # 3D Pythagorean displacement (dx=3, dy=-4, dz=12) => exact analytical RMSD = 13.0 A
    res_3d = compute_receptor_frame_mcs_core_rmsd(
        seed_pose_artifact_id="s-3d",
        seed_pose_sha256="a" * 64,
        seed_pose_pdbqt_text=_mol_to_pdbqt_block(seed_off),
        seed_conformer_path=seed_sdf,
        target_pose_artifact_id="t-3d",
        target_pose_sha256="b" * 64,
        target_pose_pdbqt_text=_mol_to_pdbqt_block(toluene_mol, shift=(3.0, -4.0, 12.0)),
        target_conformer_path=toluene_sdf,
    )
    assert res_3d.status is McsCoreRmsdStatus.EVALUATED
    assert res_3d.receptor_frame_rmsd_angstrom == pytest.approx(13.0, abs=1e-3)
    assert res_3d.mcs_coverage_seed == pytest.approx(1.0, abs=1e-4)
    assert res_3d.mcs_coverage_target == pytest.approx(round(6 / 7, 4), abs=1e-4)

    # Pure Z displacement (0, 0, 2.5) kills dz*dz sign mutations directly
    res_z = compute_receptor_frame_mcs_core_rmsd(
        seed_pose_artifact_id="s-z",
        seed_pose_sha256="a" * 64,
        seed_pose_pdbqt_text=_mol_to_pdbqt_block(seed_off),
        seed_conformer_path=seed_sdf,
        target_pose_artifact_id="t-z",
        target_pose_sha256="c" * 64,
        target_pose_pdbqt_text=_mol_to_pdbqt_block(toluene_mol, shift=(0.0, 0.0, 2.5)),
        target_conformer_path=toluene_sdf,
    )
    assert res_z.receptor_frame_rmsd_angstrom == pytest.approx(2.5, abs=1e-3)

    # Single-atom MCS (C-O vs C-N -> 1 shared carbon, kills mcs_atoms <= 1)
    methanol = Chem.AddHs(Chem.MolFromSmiles("CO"))
    AllChem.EmbedMolecule(methanol, randomSeed=7)
    methanol = Chem.RemoveHs(methanol)
    methylamine = Chem.Mol(methanol)
    rw = Chem.RWMol(methylamine)
    rw.GetAtomWithIdx(1).SetAtomicNum(7)
    methylamine = rw.GetMol()
    Chem.SanitizeMol(methylamine)
    m1_sdf = tmp_path / "methanol.sdf"
    m2_sdf = tmp_path / "methylamine.sdf"
    m1_sdf.write_text(Chem.MolToMolBlock(methanol) + "\n$$$$\n", encoding="utf-8")
    m2_sdf.write_text(Chem.MolToMolBlock(methylamine) + "\n$$$$\n", encoding="utf-8")
    res_one = compute_receptor_frame_mcs_core_rmsd(
        seed_pose_artifact_id="m1",
        seed_pose_sha256="d" * 64,
        seed_pose_pdbqt_text=_mol_to_pdbqt_block(methanol),
        seed_conformer_path=m1_sdf,
        target_pose_artifact_id="m2",
        target_pose_sha256="e" * 64,
        target_pose_pdbqt_text=_mol_to_pdbqt_block(methylamine, shift=(0.0, 1.5, 2.0)),
        target_conformer_path=m2_sdf,
    )
    assert res_one.status is McsCoreRmsdStatus.EVALUATED
    assert res_one.mcs_heavy_atom_count == 1
    assert res_one.receptor_frame_rmsd_angstrom == pytest.approx(2.5, abs=1e-3)


def test_mcs_core_rmsd_fails_closed_on_template_mismatch_and_bond_order_failure(
    tmp_path: Path,
) -> None:
    """D1-001: never silently fall back to all-single-bond PDB graph or mismatched templates."""
    toluene = Chem.AddHs(Chem.MolFromSmiles("Cc1ccccc1"))
    AllChem.EmbedMolecule(toluene, randomSeed=11)
    toluene = Chem.RemoveHs(toluene)
    ethylbenzene = Chem.AddHs(Chem.MolFromSmiles("CCc1ccccc1"))
    AllChem.EmbedMolecule(ethylbenzene, randomSeed=12)
    ethylbenzene = Chem.RemoveHs(ethylbenzene)

    tol_sdf = tmp_path / "tol.sdf"
    eth_sdf = tmp_path / "eth.sdf"
    tol_sdf.write_text(Chem.MolToMolBlock(toluene) + "\n$$$$\n", encoding="utf-8")
    eth_sdf.write_text(Chem.MolToMolBlock(ethylbenzene) + "\n$$$$\n", encoding="utf-8")

    # 1. Subgraph template mismatch (7-atom template on 8-atom pose) must fail closed
    with pytest.raises(AnkoraDomainError) as mismatch_exc:
        compute_receptor_frame_mcs_core_rmsd(
            seed_pose_artifact_id="s1",
            seed_pose_sha256="1" * 64,
            seed_pose_pdbqt_text=_mol_to_pdbqt_block(ethylbenzene),
            seed_conformer_path=tol_sdf,
            target_pose_artifact_id="t1",
            target_pose_sha256="2" * 64,
            target_pose_pdbqt_text=_mol_to_pdbqt_block(toluene),
            target_conformer_path=tol_sdf,
        )
    assert mismatch_exc.value.code == "ANALOG_MCS_TOPOLOGY_MISMATCH"

    # 2. Same-molecule severely clashed pose where AssignBondOrdersFromTemplate fails must raise
    propyl = Chem.AddHs(Chem.MolFromSmiles("CCCc1ccccc1"))
    AllChem.EmbedMolecule(propyl, randomSeed=13)
    propyl = Chem.RemoveHs(propyl)
    propyl_sdf = tmp_path / "propyl.sdf"
    propyl_sdf.write_text(Chem.MolToMolBlock(propyl) + "\n$$$$\n", encoding="utf-8")

    clashed = Chem.Mol(propyl)
    c_conf = clashed.GetConformer()
    p0 = c_conf.GetAtomPosition(0)
    p6 = c_conf.GetAtomPosition(6)
    # Collapse terminal methyl atom onto para-ring carbon (~1.0 A) creating spurious PDB bond
    c_conf.SetAtomPosition(0, (p6.x + 0.9, p6.y, p0.z))
    with pytest.raises(AnkoraDomainError) as bo_exc:
        compute_receptor_frame_mcs_core_rmsd(
            seed_pose_artifact_id="s2",
            seed_pose_sha256="3" * 64,
            seed_pose_pdbqt_text=_mol_to_pdbqt_block(clashed),
            seed_conformer_path=propyl_sdf,
            target_pose_artifact_id="t2",
            target_pose_sha256="4" * 64,
            target_pose_pdbqt_text=_mol_to_pdbqt_block(propyl),
            target_conformer_path=propyl_sdf,
        )
    assert bo_exc.value.code == "ANALOG_MCS_BOND_ORDER_ASSIGNMENT_FAILED"

    # 3. Non-finite z coordinate (with finite x, y) must fail closed (kills `and` -> `or`)
    nan_z_pdbqt = _mol_to_pdbqt_block(toluene).splitlines()
    for idx, line in enumerate(nan_z_pdbqt):
        if line.startswith("ATOM  "):
            nan_z_pdbqt[idx] = line[:46] + "     nan" + line[54:]
            break
    with pytest.raises(AnkoraDomainError) as nan_exc:
        compute_receptor_frame_mcs_core_rmsd(
            seed_pose_artifact_id="s-nan",
            seed_pose_sha256="5" * 64,
            seed_pose_pdbqt_text="\n".join(nan_z_pdbqt) + "\n",
            seed_conformer_path=tol_sdf,
            target_pose_artifact_id="t-nan",
            target_pose_sha256="6" * 64,
            target_pose_pdbqt_text=_mol_to_pdbqt_block(toluene),
            target_conformer_path=tol_sdf,
        )
    assert nan_exc.value.code in {
        "ANALOG_MCS_POSE_UNREADABLE",
        "ANALOG_MCS_TOPOLOGY_MISMATCH",
        "ANALOG_MCS_BOND_ORDER_ASSIGNMENT_FAILED",
    }

    # 4. Completely empty PDBQT (MolFromPDBBlock -> None / 0 atoms) must raise AnkoraDomainError
    with pytest.raises(AnkoraDomainError):
        compute_receptor_frame_mcs_core_rmsd(
            seed_pose_artifact_id="s-empty",
            seed_pose_sha256="7" * 64,
            seed_pose_pdbqt_text="REMARK empty\n",
            seed_conformer_path=tol_sdf,
            target_pose_artifact_id="t-empty",
            target_pose_sha256="8" * 64,
            target_pose_pdbqt_text=_mol_to_pdbqt_block(toluene),
            target_conformer_path=tol_sdf,
        )

    # 5. Zero common heavy atoms (H2O2 vs toluene) -> NOT_EVALUABLE (kills `mcs_atoms < 1 and ...`)
    peroxide = Chem.AddHs(Chem.MolFromSmiles("OO"))
    AllChem.EmbedMolecule(peroxide, randomSeed=5)
    peroxide = Chem.RemoveHs(peroxide)
    perox_sdf = tmp_path / "peroxide.sdf"
    perox_sdf.write_text(Chem.MolToMolBlock(peroxide) + "\n$$$$\n", encoding="utf-8")
    no_mcs = compute_receptor_frame_mcs_core_rmsd(
        seed_pose_artifact_id="s-oo",
        seed_pose_sha256="9" * 64,
        seed_pose_pdbqt_text=_mol_to_pdbqt_block(peroxide),
        seed_conformer_path=perox_sdf,
        target_pose_artifact_id="t-tol",
        target_pose_sha256="a" * 64,
        target_pose_pdbqt_text=_mol_to_pdbqt_block(toluene),
        target_conformer_path=tol_sdf,
    )
    assert no_mcs.status is McsCoreRmsdStatus.NO_COMMON_SUBSTRUCTURE
    assert no_mcs.mcs_heavy_atom_count == 0


def test_mcs_core_rmsd_preserves_meeko_cg0_macrocycle_and_pdb_cg1_cg2_carbons(
    tmp_path: Path,
) -> None:
    """D2-002: drop only dummy G0 glue pseudoatoms; keep real Meeko CG0 and PDB CG1/CG2 carbons."""
    meeko_prep = import_module("meeko").MoleculePreparation
    meeko_writer = import_module("meeko").PDBQTWriterLegacy

    # 1. Real Meeko flexible 14-carbon macrocycle emits 12 C + 2 CG0 (real) + 2 G0 (dummy)
    macro = Chem.AddHs(Chem.MolFromSmiles("C1CCCCCCCCCCCCC1"))
    AllChem.EmbedMolecule(macro, randomSeed=42)
    prep = meeko_prep(rigid_macrocycles=False)
    setups = prep.prepare(macro)
    pdbqt_str, ok, err = meeko_writer.write_string(setups[0])
    assert ok, err
    assert "CG0" in pdbqt_str and "G0" in pdbqt_str

    macro_heavy = Chem.RemoveHs(macro)
    macro_sdf = tmp_path / "macro14.sdf"
    macro_sdf.write_text(Chem.MolToMolBlock(macro_heavy) + "\n$$$$\n", encoding="utf-8")

    res_macro = compute_receptor_frame_mcs_core_rmsd(
        seed_pose_artifact_id="macro-s",
        seed_pose_sha256="5" * 64,
        seed_pose_pdbqt_text=pdbqt_str,
        seed_conformer_path=macro_sdf,
        target_pose_artifact_id="macro-t",
        target_pose_sha256="6" * 64,
        target_pose_pdbqt_text=pdbqt_str,
        target_conformer_path=macro_sdf,
    )
    assert res_macro.status is McsCoreRmsdStatus.EVALUATED
    assert res_macro.seed_heavy_atom_count == 14
    assert res_macro.target_heavy_atom_count == 14
    assert res_macro.mcs_heavy_atom_count == 14
    assert res_macro.receptor_frame_rmsd_angstrom == pytest.approx(0.0, abs=1e-3)

    # 2. Synthetic branched hydrocarbon with PDB atom names CG1/CG2 and AutoDock type C
    isopentane = Chem.AddHs(Chem.MolFromSmiles("CC(C)CC"))
    AllChem.EmbedMolecule(isopentane, randomSeed=5)
    isopentane = Chem.RemoveHs(isopentane)
    iso_sdf = tmp_path / "isopentane.sdf"
    iso_sdf.write_text(Chem.MolToMolBlock(isopentane) + "\n$$$$\n", encoding="utf-8")
    atom_names = ["CA ", "CB ", "CG1", "CG2", "CD1"]
    conf = isopentane.GetConformer()
    iso_lines = ["MODEL 1", "ROOT"]
    for idx, name in enumerate(atom_names):
        p = conf.GetAtomPosition(idx)
        iso_lines.append(
            f"ATOM  {idx + 1:5d}  {name:<3s} VAL     1    "
            f"{p.x:8.3f}{p.y:8.3f}{p.z:8.3f}  1.00  0.00    +0.000 C "
        )
    iso_lines.extend(["ENDROOT", "TORSDOF 0", "ENDMDL"])
    iso_pdbqt = "\n".join(iso_lines) + "\n"

    res_cg = compute_receptor_frame_mcs_core_rmsd(
        seed_pose_artifact_id="val-s",
        seed_pose_sha256="7" * 64,
        seed_pose_pdbqt_text=iso_pdbqt,
        seed_conformer_path=iso_sdf,
        target_pose_artifact_id="val-t",
        target_pose_sha256="8" * 64,
        target_pose_pdbqt_text=iso_pdbqt,
        target_conformer_path=iso_sdf,
    )
    assert res_cg.seed_heavy_atom_count == 5
    assert res_cg.mcs_heavy_atom_count == 5
    assert res_cg.receptor_frame_rmsd_angstrom == pytest.approx(0.0, abs=1e-3)


def test_mcs_core_rmsd_symmetric_across_multi_ring_and_supergraph_embeddings(
    tmp_path: Path,
) -> None:
    """D2-001/D4-005: minimize over all Aut(Q)-distinct seed embeddings symmetrically."""
    # 1. Diphenylmethane seed vs toluene placed identically on Ring 2 (not seed_matches[0])
    dpm = Chem.AddHs(Chem.MolFromSmiles("c1ccccc1Cc2ccccc2"))
    AllChem.EmbedMolecule(dpm, randomSeed=42)
    dpm = Chem.RemoveHs(dpm)
    dpm_conf = dpm.GetConformer()

    # Build toluene using Ring 2 (atoms 7..12) + methylene bridge atom 6
    ring2_order = [6, 7, 8, 9, 10, 11, 12]
    tol = Chem.MolFromSmiles("Cc1ccccc1")
    tol_conf = Chem.Conformer(tol.GetNumAtoms())
    for t_idx, s_idx in enumerate(ring2_order):
        tol_conf.SetAtomPosition(t_idx, dpm_conf.GetAtomPosition(s_idx))
    tol.RemoveAllConformers()
    tol.AddConformer(tol_conf, assignId=True)

    dpm_sdf = tmp_path / "dpm.sdf"
    tol_sdf = tmp_path / "tol_ring2.sdf"
    dpm_sdf.write_text(Chem.MolToMolBlock(dpm) + "\n$$$$\n", encoding="utf-8")
    tol_sdf.write_text(Chem.MolToMolBlock(tol) + "\n$$$$\n", encoding="utf-8")
    dpm_pdbqt = _mol_to_pdbqt_block(dpm)
    tol_pdbqt = _mol_to_pdbqt_block(tol)

    fwd = compute_receptor_frame_mcs_core_rmsd(
        seed_pose_artifact_id="dpm",
        seed_pose_sha256="9" * 64,
        seed_pose_pdbqt_text=dpm_pdbqt,
        seed_conformer_path=dpm_sdf,
        target_pose_artifact_id="tol",
        target_pose_sha256="0" * 64,
        target_pose_pdbqt_text=tol_pdbqt,
        target_conformer_path=tol_sdf,
    )
    rev = compute_receptor_frame_mcs_core_rmsd(
        seed_pose_artifact_id="tol",
        seed_pose_sha256="0" * 64,
        seed_pose_pdbqt_text=tol_pdbqt,
        seed_conformer_path=tol_sdf,
        target_pose_artifact_id="dpm",
        target_pose_sha256="9" * 64,
        target_pose_pdbqt_text=dpm_pdbqt,
        target_conformer_path=dpm_sdf,
    )
    assert fwd.status is McsCoreRmsdStatus.EVALUATED
    assert fwd.mcs_heavy_atom_count == 7
    assert fwd.receptor_frame_rmsd_angstrom == pytest.approx(0.0, abs=1e-3)
    assert rev.receptor_frame_rmsd_angstrom == pytest.approx(0.0, abs=1e-3)

    # 2. Induced supergraph (cyclopropane C1CC1 vs linear propane CCC placed on non-default orbit)
    # Using ring_matches_ring_only=False so Q=[#6]-[#6]-[#6] embeds onto all 3 vertex-set orbits
    cyc = Chem.AddHs(Chem.MolFromSmiles("C1CC1"))
    AllChem.EmbedMolecule(cyc, randomSeed=7)
    cyc = Chem.RemoveHs(cyc)
    cyc_conf = cyc.GetConformer()
    # Place propane atoms (0, 1, 2) onto cyclopropane vertices (1, 0, 2) — middle atom is 0, NOT 1!
    prop = Chem.MolFromSmiles("CCC")
    prop_conf = Chem.Conformer(3)
    for t_idx, s_idx in enumerate((1, 0, 2)):
        prop_conf.SetAtomPosition(t_idx, cyc_conf.GetAtomPosition(s_idx))
    prop.RemoveAllConformers()
    prop.AddConformer(prop_conf, assignId=True)

    cyc_sdf = tmp_path / "cyc.sdf"
    prop_sdf = tmp_path / "prop.sdf"
    cyc_sdf.write_text(Chem.MolToMolBlock(cyc) + "\n$$$$\n", encoding="utf-8")
    prop_sdf.write_text(Chem.MolToMolBlock(prop) + "\n$$$$\n", encoding="utf-8")
    res_sg = compute_receptor_frame_mcs_core_rmsd(
        seed_pose_artifact_id="cyc",
        seed_pose_sha256="1" * 64,
        seed_pose_pdbqt_text=_mol_to_pdbqt_block(cyc),
        seed_conformer_path=cyc_sdf,
        target_pose_artifact_id="prop",
        target_pose_sha256="2" * 64,
        target_pose_pdbqt_text=_mol_to_pdbqt_block(prop),
        target_conformer_path=prop_sdf,
        ring_matches_ring_only=False,
        complete_rings_only=False,
    )
    assert res_sg.status is McsCoreRmsdStatus.EVALUATED
    assert res_sg.mcs_heavy_atom_count == 3
    assert res_sg.receptor_frame_rmsd_angstrom == pytest.approx(0.0, abs=1e-3)
