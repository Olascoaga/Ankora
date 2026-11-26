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
_DUMMY_GLUE_TYPE_RE = re.compile(r"^(?:G\d+|G|DU|LP)$", re.IGNORECASE)
_MACROCYCLE_CARBON_TYPE_RE = re.compile(r"^CG\d+$", re.IGNORECASE)


def _strip_macrocycle_pseudoatoms(pdbqt_text: str) -> str:
    """Drop Meeko dummy glue pseudoatoms (G0..G9, G, DU, LP) and normalize real CGn carbons."""
    kept: list[str] = []
    for line in pdbqt_text.splitlines():
        if line.startswith(("ATOM  ", "HETATM")):
            ad_type = line[77:80].strip() if len(line) > 77 else ""
            if _DUMMY_GLUE_TYPE_RE.match(ad_type):
                continue
            if _MACROCYCLE_CARBON_TYPE_RE.match(ad_type):
                line = f"{line[:77]}C "
        kept.append(line)
    return "\n".join(kept) + "\n"


def _load_pose_heavy_mol(*, pose_pdbqt_text: str, conformer_sdf_path: Path) -> Any:
    """Parse docked PDBQT pose into an RDKit heavy-atom Mol with verified template bond orders."""
    template = load_reference(conformer_sdf_path)
    cleaned_pdbqt = _strip_macrocycle_pseudoatoms(pose_pdbqt_text)
    pdb_block = pdbqt_to_pdb_block(cleaned_pdbqt, keep_hydrogens=False)
    pose_mol = Chem.MolFromPDBBlock(pdb_block, removeHs=True, sanitize=False)
    if pose_mol is None or pose_mol.GetNumConformers() == 0:
        raise AnkoraDomainError(
            code="ANALOG_MCS_POSE_UNREADABLE",
            stage=_STAGE,
            message="Could not construct a valid RDKit heavy-atom molecule from the docked PDBQT.",
            status_code=422,
        )
    conf = pose_mol.GetConformer()
    for atom_idx in range(pose_mol.GetNumAtoms()):
        pos = conf.GetAtomPosition(atom_idx)
        if not (
            math.isfinite(float(pos.x))
            and math.isfinite(float(pos.y))
            and math.isfinite(float(pos.z))
        ):
            raise AnkoraDomainError(
                code="ANALOG_MCS_POSE_UNREADABLE",
                stage=_STAGE,
                message="Docked pose contains non-finite heavy-atom coordinates.",
                status_code=422,
                details={"atom_index": atom_idx},
            )
    if pose_mol.GetNumAtoms() != template.GetNumAtoms():
        raise AnkoraDomainError(
            code="ANALOG_MCS_TOPOLOGY_MISMATCH",
            stage=_STAGE,
            message=(
                "Docked PDBQT heavy-atom count does not match its reference conformer template; "
                "refusing to compute an unverified MCS core RMSD."
            ),
            status_code=422,
            details={
                "pose_heavy_atoms": int(pose_mol.GetNumAtoms()),
                "template_heavy_atoms": int(template.GetNumAtoms()),
            },
        )
    try:
        assigned = AllChem.AssignBondOrdersFromTemplate(template, pose_mol)
    except Exception as error:  # noqa: BLE001 — RDKit raises bare ValueError/RuntimeError
        raise AnkoraDomainError(
            code="ANALOG_MCS_BOND_ORDER_ASSIGNMENT_FAILED",
            stage=_STAGE,
            message=(
                "Could not transfer verified template bond orders onto the docked PDBQT pose; "
                "refusing to fall back to an all-single-bond PDB graph."
            ),
            status_code=422,
            details={
                "pose_heavy_atoms": int(pose_mol.GetNumAtoms()),
                "template_heavy_atoms": int(template.GetNumAtoms()),
                "technical_message": str(error),
            },
        ) from error
    return Chem.RemoveHs(assigned)


def _reduce_seed_matches_by_query_automorphisms(
    query: Any,
    seed_matches: tuple[tuple[int, ...], ...],
    *,
    target_match_count: int,
) -> tuple[tuple[int, ...], ...]:
    """Quotient seed embeddings by Aut(query) without losing distinct sites or supergraph orbits."""
    if len(seed_matches) <= 1 or target_match_count >= _MAX_SUBSTRUCT_MATCHES:
        return seed_matches
    try:
        query_graph = Chem.Mol(query)
        query_graph.UpdatePropertyCache(strict=False)
        Chem.FastFindRings(query_graph)
        auts = query_graph.GetSubstructMatches(
            query, uniquify=False, maxMatches=_MAX_SUBSTRUCT_MATCHES
        )
    except RuntimeError:
        return seed_matches
    if not auts or len(auts) >= _MAX_SUBSTRUCT_MATCHES:
        return seed_matches
    n_atoms = len(seed_matches[0])
    if any(len(perm) != n_atoms for perm in auts):
        return seed_matches
    orbits: dict[tuple[int, ...], tuple[int, ...]] = {}
    for match in seed_matches:
        canonical = min(tuple(match[perm[idx]] for idx in range(n_atoms)) for perm in auts)
        orbits.setdefault(canonical, match)
    return tuple(orbits.values())


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
    coverage_seed = round(mcs_atoms / seed_heavy, 4) if seed_heavy > 0 else None
    coverage_target = round(mcs_atoms / target_heavy, 4) if target_heavy > 0 else None

    def _result(
        *,
        status: McsCoreRmsdStatus,
        smarts: str | None,
        atom_count: int,
        rmsd_angstrom: float | None,
    ) -> McsCoreRmsdResult:
        return McsCoreRmsdResult(
            seed_pose_artifact_id=seed_pose_artifact_id,
            seed_pose_sha256=seed_pose_sha256,
            target_pose_artifact_id=target_pose_artifact_id,
            target_pose_sha256=target_pose_sha256,
            status=status,
            mcs_smarts=smarts,
            mcs_heavy_atom_count=atom_count,
            seed_heavy_atom_count=seed_heavy,
            target_heavy_atom_count=target_heavy,
            mcs_coverage_seed=0.0 if atom_count == 0 else coverage_seed,
            mcs_coverage_target=0.0 if atom_count == 0 else coverage_target,
            mcs_timed_out=timed_out,
            receptor_frame_rmsd_angstrom=rmsd_angstrom,
            superposition_applied=False,
            timeout_seconds=timeout_seconds,
            atom_compare="CompareElements",
            bond_compare="CompareOrderExact",
            ring_matches_ring_only=ring_matches_ring_only,
            complete_rings_only=complete_rings_only,
            warnings=warnings,
        )

    if mcs_atoms < 1 or not mcs_smarts:
        return _result(
            status=McsCoreRmsdStatus.NO_COMMON_SUBSTRUCTURE,
            smarts=None,
            atom_count=0,
            rmsd_angstrom=None,
        )

    query = Chem.MolFromSmarts(mcs_smarts)
    if query is None:
        return _result(
            status=McsCoreRmsdStatus.NOT_EVALUABLE,
            smarts=mcs_smarts,
            atom_count=mcs_atoms,
            rmsd_angstrom=None,
        )

    seed_matches = seed_mol.GetSubstructMatches(
        query, uniquify=False, maxMatches=_MAX_SUBSTRUCT_MATCHES
    )
    target_matches = target_mol.GetSubstructMatches(
        query, uniquify=False, maxMatches=_MAX_SUBSTRUCT_MATCHES
    )
    if not seed_matches or not target_matches:
        return _result(
            status=McsCoreRmsdStatus.NOT_EVALUABLE,
            smarts=mcs_smarts,
            atom_count=mcs_atoms,
            rmsd_angstrom=None,
        )

    seed_conf = seed_mol.GetConformer()
    target_conf = target_mol.GetConformer()
    reduced_seed_matches = _reduce_seed_matches_by_query_automorphisms(
        query,
        tuple(tuple(int(idx) for idx in match) for match in seed_matches),
        target_match_count=len(target_matches),
    )
    seed_coord_sets = [
        [
            (
                float(seed_conf.GetAtomPosition(idx).x),
                float(seed_conf.GetAtomPosition(idx).y),
                float(seed_conf.GetAtomPosition(idx).z),
            )
            for idx in s_match
        ]
        for s_match in reduced_seed_matches
    ]
    target_coord_sets = [
        [
            (
                float(target_conf.GetAtomPosition(idx).x),
                float(target_conf.GetAtomPosition(idx).y),
                float(target_conf.GetAtomPosition(idx).z),
            )
            for idx in t_match
        ]
        for t_match in target_matches
    ]

    best_rmsd = float("inf")
    for seed_coords in seed_coord_sets:
        n_coords = float(len(seed_coords))
        for target_coords in target_coord_sets:
            sq_sum = 0.0
            for (sx, sy, sz), (tx, ty, tz) in zip(seed_coords, target_coords, strict=True):
                dx = sx - tx
                dy = sy - ty
                dz = sz - tz
                sq_sum += dx * dx + dy * dy + dz * dz
            rmsd = math.sqrt(sq_sum / n_coords)
            if rmsd < best_rmsd:
                best_rmsd = rmsd

    return _result(
        status=McsCoreRmsdStatus.EVALUATED,
        smarts=mcs_smarts,
        atom_count=mcs_atoms,
        rmsd_angstrom=round(best_rmsd, 6),
    )
