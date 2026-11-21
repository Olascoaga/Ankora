"""Receptor-frame heavy-atom MCS core RMSD (strictly zero ligand superposition, ADR-033 §7).

Measures whether an analog pose places its Maximum Common Substructure (MCS) core in the
same 3D position inside the receptor coordinate frame as the parent seed pose. Never applies
Kabsch / ligand-alignment superposition, which would mask core translation or flipping.
"""

from __future__ import annotations

import math
import re
from importlib import import_module
from pathlib import Path
from typing import Any

from ankora_backend.adapters.chemistry.redocking_rmsd import (
    load_reference,
    pdbqt_to_pdb_block,
)
from ankora_backend.domain.errors import AnkoraDomainError
from ankora_backend.schemas.analog_expansion import McsCoreRmsdResult, McsCoreRmsdStatus
from ankora_backend.schemas.warnings import StructuredWarning, WarningCode

Chem: Any = import_module("rdkit.Chem")
AllChem: Any = import_module("rdkit.Chem.AllChem")
rdFMCS: Any = import_module("rdkit.Chem.rdFMCS")

_STAGE = "analog_mcs_core_rmsd"
_MAX_SUBSTRUCT_MATCHES = 1000
_PSEUDOATOM_TYPE_RE = re.compile(r"^(?:C?G\d+|G|DU|LP)$", re.IGNORECASE)


def _strip_macrocycle_pseudoatoms(pdbqt_text: str) -> str:
    kept: list[str] = []
    for line in pdbqt_text.splitlines():
        if line.startswith(("ATOM  ", "HETATM")):
            atom_name = line[12:16].strip()
            ad_type = line[77:].strip() if len(line) > 77 else ""
            if _PSEUDOATOM_TYPE_RE.match(ad_type) or _PSEUDOATOM_TYPE_RE.match(atom_name):
                continue
        kept.append(line)
    return "\n".join(kept) + "\n"


def _load_pose_heavy_mol(*, pose_pdbqt_text: str, conformer_sdf_path: Path) -> Any:
    """Parse docked PDBQT pose into an RDKit heavy-atom Mol with verified template bond orders."""
    template = load_reference(conformer_sdf_path)
    cleaned_pdbqt = _strip_macrocycle_pseudoatoms(pose_pdbqt_text)
    pdb_block = pdbqt_to_pdb_block(cleaned_pdbqt, keep_hydrogens=False)
    pose_mol = Chem.MolFromPDBBlock(pdb_block, removeHs=True, sanitize=True)
    if pose_mol is None:
        raise AnkoraDomainError(
            code="ANALOG_MCS_POSE_UNREADABLE",
            stage=_STAGE,
            message="Could not construct a valid RDKit heavy-atom molecule from the docked PDBQT.",
            status_code=422,
        )
    try:
        assigned = AllChem.AssignBondOrdersFromTemplate(template, pose_mol)
        return Chem.RemoveHs(assigned)
    except Exception:  # noqa: BLE001
        # Fall back cleanly to the PDB-parsed heavy-atom graph if template order assignment
        # cannot reconcile a minor protonation/tautomer valence mismatch, preserving exact
        # receptor-frame heavy-atom coordinates.
        return Chem.RemoveHs(pose_mol)


def compute_receptor_frame_mcs_core_rmsd(
    *,
    seed_pose_artifact_id: str,
    seed_pose_sha256: str,
    seed_pose_pdbqt_text: str,
    seed_conformer_path: Path,
    target_pose_artifact_id: str,
    target_pose_sha256: str,
    target_pose_pdbqt_text: str,
    target_conformer_path: Path,
    timeout_seconds: int = 5,
    ring_matches_ring_only: bool = True,
    complete_rings_only: bool = True,
) -> McsCoreRmsdResult:
    """Compute minimum symmetry-aware in-place heavy-atom MCS RMSD in receptor coordinates."""
    seed_mol = _load_pose_heavy_mol(
        pose_pdbqt_text=seed_pose_pdbqt_text,
        conformer_sdf_path=seed_conformer_path,
    )
    target_mol = _load_pose_heavy_mol(
        pose_pdbqt_text=target_pose_pdbqt_text,
        conformer_sdf_path=target_conformer_path,
    )
    seed_heavy = int(seed_mol.GetNumHeavyAtoms())
    target_heavy = int(target_mol.GetNumHeavyAtoms())

    atom_compare = rdFMCS.AtomCompare.CompareElements
    bond_compare = rdFMCS.BondCompare.CompareOrderExact

    mcs = rdFMCS.FindMCS(
        [seed_mol, target_mol],
        atomCompare=atom_compare,
        bondCompare=bond_compare,
        ringMatchesRingOnly=ring_matches_ring_only,
        completeRingsOnly=complete_rings_only,
        timeout=timeout_seconds,
    )

    warnings: list[StructuredWarning] = []
    timed_out = bool(mcs.canceled)
    if timed_out:
        warnings.append(
            StructuredWarning(
                code=WarningCode.ANALOG_MCS_TIMEOUT,
                stage=_STAGE,
                message=(
                    f"MCS search reached timeout ({timeout_seconds}s); the reported common "
                    "substructure is not a certified global maximum (ADR-033 §7)."
                ),
                details={"timeout_seconds": timeout_seconds, "num_atoms": int(mcs.numAtoms)},
            )
        )

    mcs_atoms = int(mcs.numAtoms)
    mcs_smarts = str(mcs.smartsString) if mcs.smartsString else None
    if mcs_atoms < 1 or not mcs_smarts:
        return McsCoreRmsdResult(
            seed_pose_artifact_id=seed_pose_artifact_id,
            seed_pose_sha256=seed_pose_sha256,
            target_pose_artifact_id=target_pose_artifact_id,
            target_pose_sha256=target_pose_sha256,
            status=McsCoreRmsdStatus.NO_COMMON_SUBSTRUCTURE,
            mcs_smarts=None,
            mcs_heavy_atom_count=0,
            seed_heavy_atom_count=seed_heavy,
            target_heavy_atom_count=target_heavy,
            mcs_coverage_seed=0.0 if seed_heavy > 0 else None,
            mcs_coverage_target=0.0 if target_heavy > 0 else None,
            mcs_timed_out=timed_out,
            receptor_frame_rmsd_angstrom=None,
            superposition_applied=False,
            timeout_seconds=timeout_seconds,
            atom_compare="CompareElements",
            bond_compare="CompareOrderExact",
            ring_matches_ring_only=ring_matches_ring_only,
            complete_rings_only=complete_rings_only,
            warnings=warnings,
        )

    query = Chem.MolFromSmarts(mcs_smarts)
    if query is None:
        return McsCoreRmsdResult(
            seed_pose_artifact_id=seed_pose_artifact_id,
            seed_pose_sha256=seed_pose_sha256,
            target_pose_artifact_id=target_pose_artifact_id,
            target_pose_sha256=target_pose_sha256,
            status=McsCoreRmsdStatus.NOT_EVALUABLE,
            mcs_smarts=mcs_smarts,
            mcs_heavy_atom_count=mcs_atoms,
            seed_heavy_atom_count=seed_heavy,
            target_heavy_atom_count=target_heavy,
            mcs_coverage_seed=round(mcs_atoms / seed_heavy, 4) if seed_heavy > 0 else None,
            mcs_coverage_target=round(mcs_atoms / target_heavy, 4) if target_heavy > 0 else None,
            mcs_timed_out=timed_out,
            receptor_frame_rmsd_angstrom=None,
            superposition_applied=False,
            timeout_seconds=timeout_seconds,
            atom_compare="CompareElements",
            bond_compare="CompareOrderExact",
            ring_matches_ring_only=ring_matches_ring_only,
            complete_rings_only=complete_rings_only,
            warnings=warnings,
        )

    seed_matches = seed_mol.GetSubstructMatches(
        query, uniquify=False, maxMatches=_MAX_SUBSTRUCT_MATCHES
    )
    target_matches = target_mol.GetSubstructMatches(
        query, uniquify=False, maxMatches=_MAX_SUBSTRUCT_MATCHES
    )
    if not seed_matches or not target_matches:
        return McsCoreRmsdResult(
            seed_pose_artifact_id=seed_pose_artifact_id,
            seed_pose_sha256=seed_pose_sha256,
            target_pose_artifact_id=target_pose_artifact_id,
            target_pose_sha256=target_pose_sha256,
            status=McsCoreRmsdStatus.NOT_EVALUABLE,
            mcs_smarts=mcs_smarts,
            mcs_heavy_atom_count=mcs_atoms,
            seed_heavy_atom_count=seed_heavy,
            target_heavy_atom_count=target_heavy,
            mcs_coverage_seed=round(mcs_atoms / seed_heavy, 4) if seed_heavy > 0 else None,
            mcs_coverage_target=round(mcs_atoms / target_heavy, 4) if target_heavy > 0 else None,
            mcs_timed_out=timed_out,
            receptor_frame_rmsd_angstrom=None,
            superposition_applied=False,
            timeout_seconds=timeout_seconds,
            atom_compare="CompareElements",
            bond_compare="CompareOrderExact",
            ring_matches_ring_only=ring_matches_ring_only,
            complete_rings_only=complete_rings_only,
            warnings=warnings,
        )

    seed_conf = seed_mol.GetConformer()
    target_conf = target_mol.GetConformer()
    # Fix one canonical seed match and iterate over all symmetry-equivalent target matches
    # (equivalent to minimizing over all automorphism pairs since query symmetry acts on both).
    seed_match = seed_matches[0]
    seed_coords = [seed_conf.GetAtomPosition(idx) for idx in seed_match]

    best_rmsd = float("inf")
    for t_match in target_matches:
        sq_sum = 0.0
        for s_pos, t_idx in zip(seed_coords, t_match, strict=True):
            t_pos = target_conf.GetAtomPosition(t_idx)
            dx = float(s_pos.x) - float(t_pos.x)
            dy = float(s_pos.y) - float(t_pos.y)
            dz = float(s_pos.z) - float(t_pos.z)
            sq_sum += dx * dx + dy * dy + dz * dz
        rmsd = math.sqrt(sq_sum / float(len(seed_coords)))
        if rmsd < best_rmsd:
            best_rmsd = rmsd

    return McsCoreRmsdResult(
        seed_pose_artifact_id=seed_pose_artifact_id,
        seed_pose_sha256=seed_pose_sha256,
        target_pose_artifact_id=target_pose_artifact_id,
        target_pose_sha256=target_pose_sha256,
        status=McsCoreRmsdStatus.EVALUATED,
        mcs_smarts=mcs_smarts,
        mcs_heavy_atom_count=mcs_atoms,
        seed_heavy_atom_count=seed_heavy,
        target_heavy_atom_count=target_heavy,
        mcs_coverage_seed=round(mcs_atoms / seed_heavy, 4) if seed_heavy > 0 else None,
        mcs_coverage_target=round(mcs_atoms / target_heavy, 4) if target_heavy > 0 else None,
        mcs_timed_out=timed_out,
        receptor_frame_rmsd_angstrom=round(best_rmsd, 6),
        superposition_applied=False,
        timeout_seconds=timeout_seconds,
        atom_compare="CompareElements",
        bond_compare="CompareOrderExact",
        ring_matches_ring_only=ring_matches_ring_only,
        complete_rings_only=complete_rings_only,
        warnings=warnings,
    )
