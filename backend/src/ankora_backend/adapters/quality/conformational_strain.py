"""Dual MMFF94s conformational strain diagnostic (Ankora v0.2 M3 / ADR-031).

Computes the explicit diagnostic strain difference on a single exact MMFF94s
Hamiltonian and identical explicit-hydrogen protonation state (`parent_state_id`):

    delta_e_ref = E_MMFF94s(locally relaxed pose with heavy-atom position tether)
                  - min_{k=1..N} E_MMFF94s(free ETKDGv3 conformer k)

Scientific safeguards:
- Full MMFF94s parameterization is checked up front (`MMFFHasAllMoleculeParams`);
  when absent (e.g., boron or metal complexes), Ankora returns `strain=None` and
  `DiagnosticStatus.NOT_EVALUABLE` rather than silently downgrading to UFF.
- Heavy-atom position constraints are applied ONLY during local relaxation so
  hydrogens and PDBQT coordinate quantization relax cleanly without moving the
  docked heavy-atom binding mode; final energy is then evaluated on the pure
  unconstrained MMFF94s potential so both terms share the exact same Hamiltonian.
- The original pose molecule is never mutated, and `delta_e_ref` is reported
  strictly as a diagnostic flag — never added to or subtracted from any docking
  score.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from importlib import import_module
from importlib.metadata import PackageNotFoundError, version
from typing import Any

from ankora_backend.schemas.v02_contracts import (
    ConformationalStrainDiagnostic,
    DiagnosticStatus,
    PoseDiagnosticCheck,
)
from ankora_backend.schemas.warnings import StructuredWarning, WarningCode

_STAGE = "pose_quality_strain"
_TOOL_NAME = "RDKit MMFF94s"
HYDROGEN_POLICY = "explicit_hydrogens_parent_state_preserved"
DEFAULT_CONFORMER_SEED = 20261119
DEFAULT_CONFORMER_BUDGET = 50
DEFAULT_STRAIN_FLAG_THRESHOLD_KCAL_MOL = 10.0
_RESTRAINT_FORCE_CONSTANT_KCAL_MOL_A2 = 100.0
_MAX_MINIMIZATION_ITERATIONS = 500


@dataclass(frozen=True, slots=True)
class StrainEvaluationResult:
    """Structured result of dual MMFF94s conformational strain evaluation."""

    diagnostic: ConformationalStrainDiagnostic | None
    check: PoseDiagnosticCheck
    warnings: tuple[StructuredWarning, ...]
    heavy_atom_relaxation_rmsd_angstrom: float | None = None
    converged_free_conformer_count: int = 0


def _rdkit_version() -> str:
    try:
        return version("rdkit")
    except PackageNotFoundError:
        rdkit = import_module("rdkit")
        return str(getattr(rdkit, "__version__", "unknown"))


def evaluate_dual_mmff94s_strain(
    *,
    ligand_mol: Any,
    parent_state_id: str,
    conformer_seed: int = DEFAULT_CONFORMER_SEED,
    conformer_budget: int = DEFAULT_CONFORMER_BUDGET,
    strain_flag_threshold_kcal_mol: float = DEFAULT_STRAIN_FLAG_THRESHOLD_KCAL_MOL,
) -> StrainEvaluationResult:
    """Evaluate dual MMFF94s conformational strain without mutating `ligand_mol`."""
    Chem = import_module("rdkit.Chem")
    AllChem = import_module("rdkit.Chem.AllChem")
    rdkit_ver = _rdkit_version()

    work_pose = Chem.Mol(ligand_mol)
    if work_pose.GetNumConformers() == 0:
        return _not_evaluable(
            rdkit_ver=rdkit_ver,
            threshold=strain_flag_threshold_kcal_mol,
            reason="Input pose molecule carries no 3D coordinates.",
            warning_code=WarningCode.POSE_QUALITY_NOT_EVALUABLE,
            details={"parent_state_id": parent_state_id},
        )

    # Ensure explicit hydrogens exist while preserving exact 3D heavy-atom geometry.
    if any(atom.GetNumImplicitHs() > 0 for atom in work_pose.GetAtoms()):
        work_pose = Chem.AddHs(work_pose, addCoords=True)

    # Strict MMFF94s coverage check — never silently downgrade to UFF.
    if not AllChem.MMFFHasAllMoleculeParams(work_pose):
        return _not_evaluable(
            rdkit_ver=rdkit_ver,
            threshold=strain_flag_threshold_kcal_mol,
            reason=(
                "MMFF94s lacks force-field parameters for at least one atom type in this "
                "chemical state; Ankora refuses silent UFF fallback."
            ),
            warning_code=WarningCode.POSE_QUALITY_MMFF94S_UNPARAMETERIZED,
            details={"parent_state_id": parent_state_id},
        )

    mmff_props = AllChem.MMFFGetMoleculeProperties(work_pose, mmffVariant="MMFF94s")
    if mmff_props is None:
        return _not_evaluable(
            rdkit_ver=rdkit_ver,
            threshold=strain_flag_threshold_kcal_mol,
            reason="RDKit could not initialize MMFF94s molecule properties for this ligand.",
            warning_code=WarningCode.POSE_QUALITY_MMFF94S_UNPARAMETERIZED,
            details={"parent_state_id": parent_state_id},
        )

    # 1. Restrained local relaxation of the docked pose copy (tether heavy atoms).
    before_heavy = _heavy_atom_coords(work_pose)
    restrained_ff = AllChem.MMFFGetMoleculeForceField(work_pose, mmff_props)
    if restrained_ff is None:
        return _not_evaluable(
            rdkit_ver=rdkit_ver,
            threshold=strain_flag_threshold_kcal_mol,
            reason="RDKit could not build the restrained MMFF94s force field for the pose.",
            warning_code=WarningCode.POSE_QUALITY_MMFF94S_UNPARAMETERIZED,
            details={"parent_state_id": parent_state_id},
        )
    for atom in work_pose.GetAtoms():
        if atom.GetAtomicNum() > 1:
            restrained_ff.MMFFAddPositionConstraint(
                atom.GetIdx(),
                0.0,
                _RESTRAINT_FORCE_CONSTANT_KCAL_MOL_A2,
            )
    restrained_ff.Initialize()
    minimize_status = int(restrained_ff.Minimize(maxIts=_MAX_MINIMIZATION_ITERATIONS))
    if minimize_status < 0:
        return _not_evaluable(
            rdkit_ver=rdkit_ver,
            threshold=strain_flag_threshold_kcal_mol,
            reason="Restrained MMFF94s pose minimization encountered a force-field error.",
            warning_code=WarningCode.POSE_QUALITY_NOT_EVALUABLE,
            details={"parent_state_id": parent_state_id, "minimize_status": minimize_status},
        )

    # Measure pure unconstrained MMFF94s energy of the locally relaxed pose geometry.
    pure_pose_ff = AllChem.MMFFGetMoleculeForceField(work_pose, mmff_props)
    if pure_pose_ff is None:
        return _not_evaluable(
            rdkit_ver=rdkit_ver,
            threshold=strain_flag_threshold_kcal_mol,
            reason="RDKit could not evaluate unconstrained MMFF94s energy of the relaxed pose.",
            warning_code=WarningCode.POSE_QUALITY_MMFF94S_UNPARAMETERIZED,
            details={"parent_state_id": parent_state_id},
        )
    pose_energy = float(pure_pose_ff.CalcEnergy())
    after_heavy = _heavy_atom_coords(work_pose)
    relax_rmsd = _in_place_rmsd(before_heavy, after_heavy)
    if not math.isfinite(pose_energy):
        return _not_evaluable(
            rdkit_ver=rdkit_ver,
            threshold=strain_flag_threshold_kcal_mol,
            reason="Restrained MMFF94s pose energy was non-finite.",
            warning_code=WarningCode.POSE_QUALITY_NOT_EVALUABLE,
            details={"parent_state_id": parent_state_id},
        )

    # 2. Deterministic free-conformer reference ensemble on identical parent state & H policy.
    # Perceive 3D tetrahedral & E/Z alkene stereochemistry before clearing conformers so
    # ETKDGv3 cannot silently isomerize untagged 3D inputs (D2-004).
    free_mol = Chem.Mol(work_pose)
    Chem.AssignStereochemistryFrom3D(free_mol)
    Chem.DetectBondStereochemistry(free_mol)
    Chem.AssignStereochemistry(free_mol, cleanIt=True, force=True)
    free_mol.RemoveAllConformers()
    embed_params = AllChem.ETKDGv3()
    embed_params.randomSeed = int(conformer_seed)
    embed_params.numThreads = 1
    embed_params.useRandomCoords = True

    conf_ids = list(
        AllChem.EmbedMultipleConfs(free_mol, numConfs=int(conformer_budget), params=embed_params)
    )
    if not conf_ids:
        return _not_evaluable(
            rdkit_ver=rdkit_ver,
            threshold=strain_flag_threshold_kcal_mol,
            reason="ETKDGv3 could not embed any free reference conformer for this parent state.",
            warning_code=WarningCode.POSE_QUALITY_NOT_EVALUABLE,
            details={
                "parent_state_id": parent_state_id,
                "conformer_seed": conformer_seed,
                "conformer_budget": conformer_budget,
            },
        )

    opt_results = AllChem.MMFFOptimizeMoleculeConfs(
        free_mol,
        numThreads=1,
        maxIters=_MAX_MINIMIZATION_ITERATIONS,
        mmffVariant="MMFF94s",
    )
    converged_energies: list[float] = []
    for status_code, energy in opt_results:
        numeric_energy = float(energy)
        if not math.isfinite(numeric_energy):
            continue
        if int(status_code) == 0:
            converged_energies.append(numeric_energy)

    if not converged_energies:
        return _not_evaluable(
            rdkit_ver=rdkit_ver,
            threshold=strain_flag_threshold_kcal_mol,
            reason=(
                "No free ETKDGv3/MMFF94s reference conformer converged within the "
                "iteration budget; refusing to report an unconverged strain PASS."
            ),
            warning_code=WarningCode.POSE_QUALITY_NOT_EVALUABLE,
            details={"parent_state_id": parent_state_id, "conformer_budget": conformer_budget},
        )

    lowest_free = min(converged_energies)
    delta_e = pose_energy - lowest_free
    diagnostic = ConformationalStrainDiagnostic(
        force_field="MMFF94s",
        parent_state_id=parent_state_id,
        hydrogen_policy=HYDROGEN_POLICY,
        conformer_seed=conformer_seed,
        conformer_budget=conformer_budget,
        pose_restrained_energy_kcal_mol=pose_energy,
        lowest_free_conformer_energy_kcal_mol=lowest_free,
        delta_e_ref_kcal_mol=delta_e,
    )

    high_strain = delta_e > strain_flag_threshold_kcal_mol
    warnings: list[StructuredWarning] = []
    if high_strain:
        warnings.append(
            StructuredWarning(
                code=WarningCode.POSE_QUALITY_HIGH_STRAIN,
                stage=_STAGE,
                message=(
                    f"Dual MMFF94s conformational strain ({delta_e:.2f} kcal/mol) exceeds the "
                    f"advisory threshold ({strain_flag_threshold_kcal_mol:.2f} kcal/mol). "
                    "Reported as a diagnostic flag only; never subtracted from docking scores."
                ),
                details={
                    "delta_e_ref_kcal_mol": delta_e,
                    "threshold_kcal_mol": strain_flag_threshold_kcal_mol,
                    "conformer_budget": conformer_budget,
                    "conformer_seed": conformer_seed,
                },
            )
        )

    note = (
        f"Restrained MMFF94s pose ({pose_energy:.2f} kcal/mol, heavy-atom drift "
        f"{relax_rmsd:.3f} A) minus lowest of {len(converged_energies)}/{conformer_budget} "
        f"free ETKDGv3/MMFF94s conformers ({lowest_free:.2f} kcal/mol). Diagnostic flag only; "
        "finite conformer budget does not claim a global minimum."
    )
    check = PoseDiagnosticCheck(
        check_id="conformational_strain_mmff94s",
        tool_name=_TOOL_NAME,
        tool_version=rdkit_ver,
        status=DiagnosticStatus.FAIL if high_strain else DiagnosticStatus.PASS,
        value=delta_e,
        threshold=strain_flag_threshold_kcal_mol,
        message=note,
    )
    return StrainEvaluationResult(
        diagnostic=diagnostic,
        check=check,
        warnings=tuple(warnings),
        heavy_atom_relaxation_rmsd_angstrom=relax_rmsd,
        converged_free_conformer_count=len(converged_energies),
    )


def _not_evaluable(
    *,
    rdkit_ver: str,
    threshold: float,
    reason: str,
    warning_code: WarningCode,
    details: dict[str, object],
) -> StrainEvaluationResult:
    return StrainEvaluationResult(
        diagnostic=None,
        check=PoseDiagnosticCheck(
            check_id="conformational_strain_mmff94s",
            tool_name=_TOOL_NAME,
            tool_version=rdkit_ver,
            status=DiagnosticStatus.NOT_EVALUABLE,
            value=None,
            threshold=threshold,
            message=reason,
        ),
        warnings=(
            StructuredWarning(
                code=warning_code,
                stage=_STAGE,
                message=reason,
                details=details,
            ),
        ),
    )


def _heavy_atom_coords(mol: Any) -> list[tuple[float, float, float]]:
    conf = mol.GetConformer()
    coords: list[tuple[float, float, float]] = []
    for atom in mol.GetAtoms():
        if atom.GetAtomicNum() > 1:
            pos = conf.GetAtomPosition(atom.GetIdx())
            coords.append((float(pos.x), float(pos.y), float(pos.z)))
    return coords


def _in_place_rmsd(
    before: list[tuple[float, float, float]],
    after: list[tuple[float, float, float]],
) -> float:
    if not before or len(before) != len(after):
        return 0.0
    sq_sum = sum(
        (x1 - x2) ** 2 + (y1 - y2) ** 2 + (z1 - z2) ** 2
        for (x1, y1, z1), (x2, y2, z2) in zip(before, after, strict=True)
    )
    return math.sqrt(sq_sum / len(before))
