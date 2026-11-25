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
