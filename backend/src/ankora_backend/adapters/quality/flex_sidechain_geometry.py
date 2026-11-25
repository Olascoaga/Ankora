"""Covalent geometry and steric checks for moved FlexRes receptor side chains (M3).

Under `sidechain_flex` (ADR-032 E8), flexible side chains rotate around their
`chi` torsions during docking and are re-injected into the coupled receptor PDB.
This module audits those moved residues against the immutable crystal
`protonated.pdb` to detect torn bonds, stereochemical inversions, or severe
sidechain-to-rigid-receptor steric clashes.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

from ankora_backend.schemas.receptors import ResidueLocator
from ankora_backend.schemas.v02_contracts import DiagnosticStatus, PoseDiagnosticCheck

_TOOL_NAME = "Ankora FlexComplexGeometry"
_TOOL_VERSION = "0.2.0"
_MAX_BOND_LENGTH_DELTA_ANGSTROM = 0.05
_COVALENT_HEAVY_BOND_CUTOFF_ANGSTROM = 1.95
_SEVERE_FLEX_RECEPTOR_CLASH_ANGSTROM = 2.00
_BACKBONE_ATOMS = frozenset({"N", "CA", "C", "O", "OXT"})
_ANCHOR_EXCLUSION_ATOMS = frozenset({"N", "CA", "CB", "C", "O", "OXT"})

type _Vec3 = tuple[float, float, float]
type _ResidueKey = tuple[str, int, str]


@dataclass(frozen=True, slots=True)
class _HeavyAtom:
    residue_key: _ResidueKey
    residue_name: str
    atom_name: str
    xyz: _Vec3


def evaluate_flex_sidechain_geometry(
    *,
    crystal_receptor_pdb: str,
    coupled_receptor_pdb: str,
    flex_residues: Sequence[ResidueLocator],
) -> tuple[PoseDiagnosticCheck, ...]:
    """Audit moved FlexRes bond lengths, chiral centers, and receptor clashes."""
    target_keys: set[_ResidueKey] = {
        (res.chain_id, res.sequence_number, res.insertion_code) for res in flex_residues
    }
    if not target_keys:
        return ()

    crystal_atoms = _parse_heavy_atoms(crystal_receptor_pdb)
    coupled_atoms = _parse_heavy_atoms(coupled_receptor_pdb)

    crystal_by_res: dict[_ResidueKey, dict[str, _HeavyAtom]] = {}
    for atom in crystal_atoms:
        if atom.residue_key in target_keys:
            crystal_by_res.setdefault(atom.residue_key, {})[atom.atom_name] = atom

    coupled_by_res: dict[_ResidueKey, dict[str, _HeavyAtom]] = {}
    rigid_atoms: list[_HeavyAtom] = []
    for atom in coupled_atoms:
        if atom.residue_key in target_keys:
            coupled_by_res.setdefault(atom.residue_key, {})[atom.atom_name] = atom
        else:
            rigid_atoms.append(atom)

    # 1. Covalent heavy-atom bond length preservation inside each FlexRes residue
    checked_bonds = 0
    max_bond_delta = 0.0
    worst_bond_label: str | None = None
    missing_flex_residue = False

    # 2. Tetrahedral chirality sign preservation at chiral centers (CA, and CB for ILE/THR)
    checked_centers = 0
    inverted_centers: list[str] = []

    for res_key in sorted(target_keys):
        c_map = crystal_by_res.get(res_key)
        m_map = coupled_by_res.get(res_key)
        if not c_map or not m_map:
            missing_flex_residue = True
            continue
        common_names = sorted(set(c_map) & set(m_map))
        for i, name_a in enumerate(common_names):
            for name_b in common_names[i + 1 :]:
                d_cryst = _dist(c_map[name_a].xyz, c_map[name_b].xyz)
                if d_cryst <= _COVALENT_HEAVY_BOND_CUTOFF_ANGSTROM:
                    d_moved = _dist(m_map[name_a].xyz, m_map[name_b].xyz)
                    delta = abs(d_moved - d_cryst)
                    checked_bonds += 1
                    if delta > max_bond_delta:
                        max_bond_delta = delta
                        worst_bond_label = (
                            f"{c_map[name_a].residue_name} {res_key[0]}:{res_key[1]}{res_key[2]} "
                            f"{name_a}-{name_b}"
                        )

        # Check CA tetrahedral improper volume (N, C, CB around CA)
        if all(name in c_map and name in m_map for name in ("CA", "N", "C", "CB")):
            checked_centers += 1
            v_c = _signed_volume(
                c_map["CA"].xyz, c_map["N"].xyz, c_map["C"].xyz, c_map["CB"].xyz
            )
            v_m = _signed_volume(
                m_map["CA"].xyz, m_map["N"].xyz, m_map["C"].xyz, m_map["CB"].xyz
            )
            if abs(v_c) > 0.1 and (v_c * v_m <= 0.0):
                inverted_centers.append(f"{res_key[0]}:{res_key[1]}{res_key[2]}:CA")

        # Check CB stereocenter on ILE (CA, CG1, CG2) and THR (CA, OG1, CG2)
        res_name = next(iter(c_map.values())).residue_name.upper()
        cb_triad: tuple[str, str, str] | None = None
        if res_name == "ILE":
            cb_triad = ("CA", "CG1", "CG2")
        elif res_name == "THR":
            cb_triad = ("CA", "OG1", "CG2")
        if cb_triad is not None and all(
            name in c_map and name in m_map for name in ("CB", *cb_triad)
        ):
            checked_centers += 1
            v_c = _signed_volume(
                c_map["CB"].xyz,
                c_map[cb_triad[0]].xyz,
                c_map[cb_triad[1]].xyz,
                c_map[cb_triad[2]].xyz,
            )
            v_m = _signed_volume(
                m_map["CB"].xyz,
                m_map[cb_triad[0]].xyz,
                m_map[cb_triad[1]].xyz,
                m_map[cb_triad[2]].xyz,
            )
            if abs(v_c) > 0.1 and (v_c * v_m <= 0.0):
                inverted_centers.append(f"{res_key[0]}:{res_key[1]}{res_key[2]}:CB")

    # 3. Severe steric clash between distal moved FlexRes atoms and rigid receptor atoms
    min_flex_rigid_dist: float | None = None
    worst_clash_label: str | None = None
    for res_key in sorted(target_keys):
        m_map = coupled_by_res.get(res_key)
        if not m_map:
            continue
        distal_atoms = [
            atom for name, atom in m_map.items() if name not in _ANCHOR_EXCLUSION_ATOMS
        ]
        for flex_atom in distal_atoms:
            for rigid_atom in rigid_atoms:
                # Skip immediately adjacent peptide backbone atoms on neighboring sequence numbers
                if (
                    rigid_atom.residue_key[0] == res_key[0]
                    and abs(rigid_atom.residue_key[1] - res_key[1]) <= 1
                    and rigid_atom.atom_name in _BACKBONE_ATOMS
                ):
                    continue
                d = _dist(flex_atom.xyz, rigid_atom.xyz)
                if min_flex_rigid_dist is None or d < min_flex_rigid_dist:
                    min_flex_rigid_dist = d
                    worst_clash_label = (
                        f"{flex_atom.residue_name} {res_key[0]}:{res_key[1]}:{flex_atom.atom_name}"
                        f" -- {rigid_atom.residue_name} "
                        f"{rigid_atom.residue_key[0]}:{rigid_atom.residue_key[1]}:"
                        f"{rigid_atom.atom_name}"
                    )

    if missing_flex_residue or checked_bonds == 0:
        bond_check = PoseDiagnosticCheck(
            check_id="flex_sidechain_bond_lengths",
            tool_name=_TOOL_NAME,
            tool_version=_TOOL_VERSION,
            status=DiagnosticStatus.NOT_EVALUABLE,
            value=None,
            threshold=_MAX_BOND_LENGTH_DELTA_ANGSTROM,
            message="One or more declared FlexRes residues were missing from the receptor PDB.",
        )
    else:
        bond_check = PoseDiagnosticCheck(
            check_id="flex_sidechain_bond_lengths",
            tool_name=_TOOL_NAME,
            tool_version=_TOOL_VERSION,
            status=(
                DiagnosticStatus.PASS
                if max_bond_delta <= _MAX_BOND_LENGTH_DELTA_ANGSTROM
                else DiagnosticStatus.FAIL
            ),
            value=max_bond_delta,
            threshold=_MAX_BOND_LENGTH_DELTA_ANGSTROM,
            message=(
                f"Checked {checked_bonds} covalent heavy-atom bonds across "
                f"{len(target_keys)} FlexRes residue(s); max delta {max_bond_delta:.4f} A "
                f"({worst_bond_label})."
            ),
        )

    if missing_flex_residue:
        chiral_status = DiagnosticStatus.NOT_EVALUABLE
        chiral_msg = "FlexRes stereocenters could not be audited because a residue was missing."
    elif checked_centers == 0:
        chiral_status = DiagnosticStatus.NOT_APPLICABLE
        chiral_msg = "No tetrahedral heavy-atom stereocenters present in declared FlexRes residues."
    elif inverted_centers:
        chiral_status = DiagnosticStatus.FAIL
        chiral_msg = f"Chiral inversion detected at: {', '.join(inverted_centers)}."
    else:
        chiral_status = DiagnosticStatus.PASS
        chiral_msg = f"All {checked_centers} FlexRes tetrahedral stereocenter(s) retained sign."
    chiral_check = PoseDiagnosticCheck(
        check_id="flex_sidechain_chirality",
        tool_name=_TOOL_NAME,
        tool_version=_TOOL_VERSION,
        status=chiral_status,
        value=float(len(inverted_centers)) if chiral_status in (
            DiagnosticStatus.PASS,
            DiagnosticStatus.FAIL,
        ) else None,
        threshold=0.0,
        message=chiral_msg,
    )

    if min_flex_rigid_dist is None:
        clash_check = PoseDiagnosticCheck(
            check_id="flex_sidechain_receptor_clash",
            tool_name=_TOOL_NAME,
            tool_version=_TOOL_VERSION,
            status=DiagnosticStatus.NOT_APPLICABLE,
            value=None,
            threshold=_SEVERE_FLEX_RECEPTOR_CLASH_ANGSTROM,
            message="No non-adjacent rigid receptor heavy atoms available to compare.",
        )
    else:
        clash_check = PoseDiagnosticCheck(
            check_id="flex_sidechain_receptor_clash",
            tool_name=_TOOL_NAME,
            tool_version=_TOOL_VERSION,
            status=(
                DiagnosticStatus.PASS
                if min_flex_rigid_dist >= _SEVERE_FLEX_RECEPTOR_CLASH_ANGSTROM
                else DiagnosticStatus.FAIL
            ),
            value=min_flex_rigid_dist,
            threshold=_SEVERE_FLEX_RECEPTOR_CLASH_ANGSTROM,
            message=(
                f"Minimum distal FlexRes-to-rigid heavy-atom distance: "
                f"{min_flex_rigid_dist:.3f} A ({worst_clash_label})."
            ),
        )

    return (bond_check, chiral_check, clash_check)


def _parse_heavy_atoms(pdb_text: str) -> list[_HeavyAtom]:
    atoms: list[_HeavyAtom] = []
    for line in pdb_text.splitlines():
        if not line.startswith(("ATOM  ", "HETATM")) or len(line) < 54:
            continue
        atom_name = line[12:16].strip()
        element = line[76:78].strip().upper() if len(line) >= 78 else ""
        if element == "H" or (not element and atom_name.startswith("H")):
            continue
        res_name = line[17:20].strip()
        chain_id = line[21:22].strip()
        try:
            seq_num = int(line[22:26].strip())
            x = float(line[30:38])
            y = float(line[38:46])
            z = float(line[46:54])
        except ValueError:
            continue
        ins_code = line[26:27].strip()
        atoms.append(
            _HeavyAtom(
                residue_key=(chain_id, seq_num, ins_code),
                residue_name=res_name,
                atom_name=atom_name,
                xyz=(x, y, z),
            )
        )
    return atoms


def _dist(a: _Vec3, b: _Vec3) -> float:
    return math.sqrt((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2)


def _signed_volume(center: _Vec3, p1: _Vec3, p2: _Vec3, p3: _Vec3) -> float:
    v1 = (p1[0] - center[0], p1[1] - center[1], p1[2] - center[2])
    v2 = (p2[0] - center[0], p2[1] - center[1], p2[2] - center[2])
    v3 = (p3[0] - center[0], p3[1] - center[1], p3[2] - center[2])
    cross = (
        v2[1] * v3[2] - v2[2] * v3[1],
        v2[2] * v3[0] - v2[0] * v3[2],
        v2[0] * v3[1] - v2[1] * v3[0],
    )
    return v1[0] * cross[0] + v1[1] * cross[1] + v1[2] * cross[2]
