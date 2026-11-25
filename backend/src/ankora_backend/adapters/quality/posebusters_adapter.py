"""Versioned PoseBusters adapter for coupled PoseComplex physical validity (M3).

Implements ADR-031 / ADR-032 E8:
- Evaluates every PoseBusters `dock` check against the exact receptor geometry
  the pose lived in (`protonated.pdb` for rigid poses, or the deterministically
  materialized coupled `receptor_rigid + pose_flex_sidechains` PDB for
  `sidechain_flex` poses).
- Preserves honest 4-state diagnostic semantics (`pass`, `fail`,
  `not_applicable`, `not_evaluable`): absent features (e.g., 0 waters or 0
  double bonds) are reported as `not_applicable` rather than misleading `pass`,
  and un-evaluable metrics (`NaN`/`<NA>`) are reported as `not_evaluable`.
- Never mutates the original pose file or caller-supplied RDKit molecules.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from importlib import import_module
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

from ankora_backend.adapters.chemistry.molecule_files import sdf_supplier
from ankora_backend.adapters.chemistry.redocking_rmsd import pdbqt_to_pdb_block
from ankora_backend.domain.errors import AnkoraDomainError
from ankora_backend.schemas.v02_contracts import DiagnosticStatus, PoseDiagnosticCheck

_STAGE = "pose_quality_assessment"
_TOOL_NAME = "PoseBusters"


@dataclass(frozen=True, slots=True)
class PoseBustersEvaluation:
    """Structured output of one PoseBusters `dock` execution."""

    tool_version: str
    checks: tuple[PoseDiagnosticCheck, ...]
    ligand_heavy_atom_count: int
    ligand_canonical_smiles: str


def detect_posebusters_version() -> str:
    """Return the exact installed PoseBusters distribution version."""
    try:
        return version("posebusters")
    except PackageNotFoundError as error:
        raise AnkoraDomainError(
            code="POSE_QUALITY_TOOL_MISSING",
            stage=_STAGE,
            message="PoseBusters is required for pose-quality assessment but is not installed.",
            status_code=503,
            details={"package": "posebusters"},
        ) from error


def reconstruct_ligand_mol_from_pose(
    *,
    pose_path: Path,
    conformer_path: Path,
) -> tuple[Any, str]:
    """Reconstruct a full-valence explicit-H RDKit Mol from PDBQT pose + conformer SDF.

    Validates that the reconstructed pose matches the exact minimized conformer's
    canonical isomeric SMILES so topology drift fails closed.
    """
    Chem = import_module("rdkit.Chem")
    AllChem = import_module("rdkit.Chem.AllChem")

    supplier = sdf_supplier(conformer_path)
    template = next((item for item in supplier if item is not None), None)
    if template is None:
        raise AnkoraDomainError(
            code="POSE_QUALITY_CONFORMER_INVALID",
            stage=_STAGE,
            message="The exact minimized conformer SDF could not be read for topology validation.",
            status_code=422,
            details={"conformer_path": conformer_path.name},
        )
    template_smiles = _canonical_smiles(Chem, template)

    ligand: Any | None = None
    meeko_error: str | None = None
    try:
        meeko = import_module("meeko")
        pdbqt = meeko.PDBQTMolecule.from_file(str(pose_path), skip_typing=True)
        reconstructed = meeko.RDKitMolCreate.from_pdbqt_mol(pdbqt)
        ligand = next((item for item in reconstructed if item is not None), None)
    except Exception as error:
        meeko_error = str(error)

    if ligand is None:
        # Explicit fallback for non-Meeko PDBQT fixtures: preserve exact heavy-atom
        # coordinates and assign bond orders strictly from the immutable conformer SDF.
        try:
            pdb_block = pdbqt_to_pdb_block(pose_path.read_text(encoding="utf-8", errors="replace"))
            raw_mol = Chem.MolFromPDBBlock(pdb_block, removeHs=True, sanitize=False)
            if raw_mol is None:
                raise ValueError("PDBQT coordinate block could not be parsed by RDKit.")
            template_no_h = Chem.RemoveHs(Chem.Mol(template))
            assigned = AllChem.AssignBondOrdersFromTemplate(template_no_h, raw_mol)
            Chem.SanitizeMol(assigned)
            ligand = Chem.AddHs(assigned, addCoords=True)
        except Exception as error:
            raise AnkoraDomainError(
                code="POSE_QUALITY_LIGAND_RECONSTRUCTION_FAILED",
                stage=_STAGE,
                message=(
                    "The selected PDBQT pose could not be reconstructed with its recorded "
                    "chemical topology."
                ),
                status_code=422,
                details={
                    "meeko_reason": meeko_error,
                    "template_fallback_reason": str(error),
                },
            ) from error

    pose_smiles = _canonical_smiles(Chem, ligand)
    if pose_smiles != template_smiles:
        raise AnkoraDomainError(
            code="POSE_QUALITY_TOPOLOGY_MISMATCH",
            stage=_STAGE,
            message=(
                "The reconstructed pose topology does not match the exact minimized "
                "conformer that produced it."
            ),
            status_code=422,
            details={"pose_smiles": pose_smiles, "conformer_smiles": template_smiles},
        )

    # Ensure explicit hydrogens match parent state without altering heavy-atom coordinates.
    if ligand.GetNumAtoms() < template.GetNumAtoms():
        ligand = Chem.AddHs(ligand, addCoords=True)

    return ligand, template_smiles


def load_receptor_mol_from_pdb(receptor_pdb_path: Path) -> Any:
    """Load an immutable receptor PDB (rigid or coupled FlexRes) with explicit hydrogens."""
    Chem = import_module("rdkit.Chem")
    try:
        protein = Chem.MolFromPDBBlock(
            receptor_pdb_path.read_bytes(),
            removeHs=False,
            sanitize=True,
            proximityBonding=True,
        )
    except Exception as error:
        raise AnkoraDomainError(
            code="POSE_QUALITY_RECEPTOR_INVALID",
            stage=_STAGE,
            message="The prepared receptor PDB could not be loaded for pose-quality assessment.",
            status_code=422,
            details={"reason": str(error)},
        ) from error
    if protein is None:
        raise AnkoraDomainError(
            code="POSE_QUALITY_RECEPTOR_INVALID",
            stage=_STAGE,
            message="The prepared receptor PDB could not be loaded for pose-quality assessment.",
            status_code=422,
        )
    return protein


def evaluate_posebusters_dock(
    *,
    ligand_mol: Any,
    receptor_mol: Any,
    ligand_canonical_smiles: str | None = None,
) -> PoseBustersEvaluation:
    """Run PoseBusters `config='dock'` on copies of `(ligand_mol, receptor_mol)`.

    Returns all individual checks with honest 4-state classification (`pass`,
    `fail`, `not_applicable`, `not_evaluable`) and upstream thresholds read
    directly from `PoseBusters(config='dock').config`.
    """
    tool_version = detect_posebusters_version()
    Chem = import_module("rdkit.Chem")
    pb_module = import_module("posebusters")

    ligand_copy = Chem.Mol(ligand_mol)
    receptor_copy = Chem.Mol(receptor_mol)
    canonical_smiles = (
        ligand_canonical_smiles
        if ligand_canonical_smiles is not None
        else _canonical_smiles(Chem, ligand_copy)
    )

    try:
        buster = pb_module.PoseBusters(config="dock")
        report_df = buster.bust([ligand_copy], None, receptor_copy, full_report=True)
    except Exception as error:
        raise AnkoraDomainError(
            code="POSE_QUALITY_EXECUTION_FAILED",
            stage=_STAGE,
            message="PoseBusters failed while evaluating the coupled pose complex.",
            status_code=500,
            details={"reason": str(error), "tool_version": tool_version},
        ) from error

    if report_df is None or len(report_df) != 1:
        raise AnkoraDomainError(
            code="POSE_QUALITY_EXECUTION_FAILED",
            stage=_STAGE,
            message="PoseBusters did not return a single-pose evaluation row.",
            status_code=500,
            details={"tool_version": tool_version},
        )

    row: dict[str, Any] = report_df.iloc[0].to_dict()
    thresholds = _extract_dock_thresholds(buster.config)
    checks = _map_posebusters_row(row=row, thresholds=thresholds, tool_version=tool_version)

    heavy_atoms = sum(1 for atom in ligand_copy.GetAtoms() if atom.GetAtomicNum() > 1)
    return PoseBustersEvaluation(
        tool_version=tool_version,
        checks=checks,
        ligand_heavy_atom_count=heavy_atoms,
        ligand_canonical_smiles=canonical_smiles,
    )


def _canonical_smiles(chem: Any, molecule: Any) -> str:
    copy = chem.Mol(molecule)
    if copy.GetNumConformers() > 0:
        chem.AssignStereochemistryFrom3D(copy)
    return str(chem.MolToSmiles(chem.RemoveHs(copy), isomericSmiles=True))


def _finite_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric if math.isfinite(numeric) else None


def _int_value(value: Any) -> int | None:
    numeric = _finite_float(value)
    if numeric is None:
        return None
    return int(round(numeric))


def _bool_value(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    # Handle numpy.bool_ cleanly without importing numpy at module top level.
    if type(value).__name__ in {"bool_", "bool"}:
        return bool(value)
    return None


def _extract_dock_thresholds(config: dict[str, Any]) -> dict[str, float]:
    """Read upstream PoseBusters thresholds directly from its loaded YAML config."""
    thresholds: dict[str, float] = {}
    for module in config.get("modules", []):
        name = str(module.get("name", ""))
        params = module.get("parameters", {}) or {}
        if name == "Geometry":
            if "threshold_bad_bond_length" in params:
                thresholds["bond_lengths"] = float(params["threshold_bad_bond_length"])
            if "threshold_bad_angle" in params:
                thresholds["bond_angles"] = float(params["threshold_bad_angle"])
            if "threshold_clash" in params:
                thresholds["internal_steric_clash"] = float(params["threshold_clash"])
        elif name == "Ring flatness" and "threshold_flatness" in params:
            thresholds["aromatic_ring_flatness"] = float(params["threshold_flatness"])
        elif name == "Ring non-flatness" and "threshold_flatness" in params:
            thresholds["non_aromatic_ring_non_flatness"] = float(params["threshold_flatness"])
        elif name == "Double bond flatness" and "threshold_flatness" in params:
            thresholds["double_bond_flatness"] = float(params["threshold_flatness"])
        elif name == "Energy ratio" and "threshold_energy_ratio" in params:
            thresholds["internal_energy"] = float(params["threshold_energy_ratio"])
        elif name == "Distance to protein":
            if "max_distance" in params:
                thresholds["protein_ligand_maximum_distance"] = float(params["max_distance"])
            if "clash_cutoff" in params:
                thresholds["minimum_distance_to_protein"] = float(params["clash_cutoff"])
        elif name == "Distance to organic cofactors" and "clash_cutoff" in params:
            thresholds["minimum_distance_to_organic_cofactors"] = float(params["clash_cutoff"])
        elif name == "Distance to inorganic cofactors" and "clash_cutoff" in params:
            thresholds["minimum_distance_to_inorganic_cofactors"] = float(params["clash_cutoff"])
        elif name == "Distance to waters" and "clash_cutoff" in params:
            thresholds["minimum_distance_to_waters"] = float(params["clash_cutoff"])
        elif name == "Volume overlap with protein" and "clash_cutoff" in params:
            thresholds["volume_overlap_with_protein"] = float(params["clash_cutoff"])
        elif name == "Volume overlap with organic cofactors" and "clash_cutoff" in params:
            thresholds["volume_overlap_with_organic_cofactors"] = float(params["clash_cutoff"])
        elif name == "Volume overlap with inorganic cofactors" and "clash_cutoff" in params:
            thresholds["volume_overlap_with_inorganic_cofactors"] = float(params["clash_cutoff"])
        elif name == "Volume overlap with waters" and "clash_cutoff" in params:
            thresholds["volume_overlap_with_waters"] = float(params["clash_cutoff"])
    return thresholds


def _map_posebusters_row(
    *,
    row: dict[str, Any],
    thresholds: dict[str, float],
    tool_version: str,
) -> tuple[PoseDiagnosticCheck, ...]:
    checks: list[PoseDiagnosticCheck] = []

    def add_check(
        check_id: str,
        raw_pass: Any,
        *,
        value: float | None = None,
        threshold: float | None = None,
        applicable: bool = True,
        evaluable: bool = True,
        message: str | None = None,
    ) -> None:
        if not applicable:
            status = DiagnosticStatus.NOT_APPLICABLE
        elif not evaluable:
            status = DiagnosticStatus.NOT_EVALUABLE
        else:
            parsed = _bool_value(raw_pass)
            if parsed is None:
                status = DiagnosticStatus.NOT_EVALUABLE
            else:
                status = DiagnosticStatus.PASS if parsed else DiagnosticStatus.FAIL
        checks.append(
            PoseDiagnosticCheck(
                check_id=check_id,
                tool_name=_TOOL_NAME,
                tool_version=tool_version,
                status=status,
                value=value if status not in (DiagnosticStatus.NOT_APPLICABLE,) else None,
                threshold=threshold,
                message=message,
            )
        )

    # 1. Loading & Chemistry (always applicable)
    add_check("pb_mol_pred_loaded", row.get("mol_pred_loaded"))
    add_check("pb_mol_cond_loaded", row.get("mol_cond_loaded"))
    add_check("pb_sanitization", row.get("sanitization"))
    add_check("pb_inchi_convertible", row.get("inchi_convertible"))
    add_check("pb_all_atoms_connected", row.get("all_atoms_connected"))
    add_check("pb_no_radicals", row.get("no_radicals"))

    # 2. Intramolecular Geometry
    n_bonds = _int_value(row.get("number_bonds"))
    short_rel = _finite_float(row.get("shortest_bond_relative_length"))
    long_rel = _finite_float(row.get("longest_bond_relative_length"))
    worst_bond_rel = _most_deviant_from_one(short_rel, long_rel)
    add_check(
        "pb_bond_lengths",
        row.get("bond_lengths"),
        value=worst_bond_rel,
        threshold=thresholds.get("bond_lengths"),
        applicable=(n_bonds is None or n_bonds > 0),
        message=(
            f"short outliers: {_int_value(row.get('number_short_outlier_bonds')) or 0}, "
            f"long outliers: {_int_value(row.get('number_long_outlier_bonds')) or 0}"
            if n_bonds
            else "No covalent heavy-atom bonds to evaluate."
        ),
    )

    n_angles = _int_value(row.get("number_angles"))
    add_check(
        "pb_bond_angles",
        row.get("bond_angles"),
        value=_finite_float(row.get("most_extreme_relative_angle")),
        threshold=thresholds.get("bond_angles"),
        applicable=(n_angles is None or n_angles > 0),
        message=(
            f"outlier angles: {_int_value(row.get('number_outlier_angles')) or 0}"
            if n_angles
            else "No heavy-atom bond angles to evaluate."
        ),
    )

    n_noncov = _int_value(row.get("number_noncov_pairs"))
    add_check(
        "pb_internal_steric_clash",
        row.get("internal_steric_clash"),
        value=_finite_float(row.get("shortest_noncovalent_relative_distance")),
        threshold=thresholds.get("internal_steric_clash"),
        applicable=(n_noncov is None or n_noncov > 0),
        message=(
            f"internal clashes: {_int_value(row.get('number_clashes')) or 0}"
            if n_noncov
            else "No non-covalent heavy-atom pairs to evaluate."
        ),
    )

    # 3. Ring & Double-Bond Flatness (explicitly NOT_APPLICABLE when 0 motifs checked)
    n_arom = _int_value(row.get("number_aromatic_rings_checked")) or 0
    add_check(
        "pb_aromatic_ring_flatness",
        row.get("aromatic_ring_flatness"),
        value=_finite_float(row.get("aromatic_ring_maximum_distance_from_plane")),
        threshold=thresholds.get("aromatic_ring_flatness"),
        applicable=n_arom > 0,
        message=(
            f"{n_arom} aromatic ring(s) checked"
            if n_arom > 0
            else "No 5- or 6-membered sp2 aromatic rings present in ligand."
        ),
    )

    n_non_arom = _int_value(row.get("number_non-aromatic_rings_checked")) or 0
    add_check(
        "pb_non_aromatic_ring_non_flatness",
        row.get("non-aromatic_ring_non-flatness"),
        value=_finite_float(row.get("non-aromatic_ring_maximum_distance_from_plane")),
        threshold=thresholds.get("non_aromatic_ring_non_flatness"),
        applicable=n_non_arom > 0,
        message=(
            f"{n_non_arom} non-aromatic 6-membered ring(s) checked"
            if n_non_arom > 0
            else "No non-aromatic 6-membered rings present in ligand."
        ),
    )

    n_double = _int_value(row.get("number_double_bonds_checked")) or 0
    add_check(
        "pb_double_bond_flatness",
        row.get("double_bond_flatness"),
        value=_finite_float(row.get("double_bond_maximum_distance_from_plane")),
        threshold=thresholds.get("double_bond_flatness"),
        applicable=n_double > 0,
        message=(
            f"{n_double} trigonal double bond(s) checked"
            if n_double > 0
            else "No trigonal planar carbon-carbon double bonds present in ligand."
        ),
    )

    # 4. PoseBusters Internal Energy Ratio (NOT_EVALUABLE if energy_ratio is NaN)
    energy_ratio = _finite_float(row.get("energy_ratio"))
    add_check(
        "pb_internal_energy",
        row.get("internal_energy"),
        value=energy_ratio,
        threshold=thresholds.get("internal_energy"),
        evaluable=energy_ratio is not None,
        message=(
            "PoseBusters UFF energy ratio against internal random-conformer ensemble."
            if energy_ratio is not None
            else "PoseBusters internal energy ratio could not be evaluated."
        ),
    )

    # 5. Intermolecular Distance & Volume Overlap vs Protein (always applicable when receptor loads)
    prot_min_dist = _finite_float(row.get("smallest_distance_protein"))
    prot_rel_dist = _finite_float(row.get("most_extreme_relative_distance_protein"))
    prot_clashes = _int_value(row.get("num_pairwise_clashes_protein")) or 0
    prot_vol = _finite_float(row.get("volume_overlap_protein"))
    cond_loaded = _bool_value(row.get("mol_cond_loaded")) is True

    add_check(
        "pb_protein_ligand_maximum_distance",
        row.get("protein-ligand_maximum_distance"),
        value=prot_min_dist,
        threshold=thresholds.get("protein_ligand_maximum_distance"),
        evaluable=cond_loaded,
        message=(
            f"minimum protein-ligand heavy-atom distance: {prot_min_dist:.3f} A"
            if prot_min_dist is not None
            else "No protein atoms within PoseBusters distance evaluation window."
        ),
    )
    add_check(
        "pb_minimum_distance_to_protein",
        row.get("minimum_distance_to_protein"),
        value=prot_rel_dist,
        threshold=thresholds.get("minimum_distance_to_protein"),
        evaluable=cond_loaded,
        message=f"pairwise protein clashes: {prot_clashes}",
    )
    add_check(
        "pb_volume_overlap_with_protein",
        row.get("volume_overlap_with_protein"),
        value=prot_vol,
        threshold=thresholds.get("volume_overlap_with_protein"),
        evaluable=cond_loaded,
        message=(
            f"protein van der Waals volume overlap fraction: {prot_vol:.4f}"
            if prot_vol is not None
            else "Ligand is outside protein van der Waals overlap envelope (0.0 overlap)."
        ),
    )

    # 6. Cofactors & Waters (honestly NOT_APPLICABLE when receptor contains none!)
    for suffix, label in (
        ("organic_cofactors", "organic cofactors"),
        ("inorganic_cofactors", "inorganic cofactors"),
        ("waters", "waters"),
    ):
        dist_min = _finite_float(row.get(f"smallest_distance_{suffix}"))
        dist_rel = _finite_float(row.get(f"most_extreme_relative_distance_{suffix}"))
        clashes = _int_value(row.get(f"num_pairwise_clashes_{suffix}")) or 0
        vol = _finite_float(row.get(f"volume_overlap_{suffix}"))
        dist_pass = _bool_value(row.get(f"minimum_distance_to_{suffix}"))
        vol_pass = _bool_value(row.get(f"volume_overlap_with_{suffix}"))
        # If PoseBusters reports NaN distance AND passed (no clash), that chemical species
        # was absent (or outside the interaction shell) in the prepared receptor.
        species_present_dist = dist_min is not None or dist_pass is False
        species_present_vol = vol is not None or vol_pass is False

        add_check(
            f"pb_minimum_distance_to_{suffix}",
            dist_pass,
            value=dist_rel,
            threshold=thresholds.get(f"minimum_distance_to_{suffix}"),
            applicable=species_present_dist,
            message=(
                f"pairwise clashes with {label}: {clashes}"
                if species_present_dist
                else f"No {label} within the prepared receptor evaluation window."
            ),
        )
        add_check(
            f"pb_volume_overlap_with_{suffix}",
            vol_pass,
            value=vol,
            threshold=thresholds.get(f"volume_overlap_with_{suffix}"),
            applicable=species_present_vol,
            message=(
                f"volume overlap with {label}: {vol:.4f}"
                if species_present_vol and vol is not None
                else f"No {label} overlapping the ligand in the prepared receptor."
            ),
        )

    return tuple(checks)


def _most_deviant_from_one(first: float | None, second: float | None) -> float | None:
    candidates = [item for item in (first, second) if item is not None]
    if not candidates:
        return None
    return max(candidates, key=lambda val: abs(val - 1.0))
