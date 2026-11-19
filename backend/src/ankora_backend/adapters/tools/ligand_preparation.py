"""Versioned Meeko adapter for ligand PDBQT preparation."""

import os
import re
from pathlib import Path
from uuid import uuid4

from rdkit import Chem

from ankora_backend.adapters.chemistry.molecule_files import sdf_supplier
from ankora_backend.adapters.engines.autodock4 import collect_autodock_atom_types
from ankora_backend.adapters.tools.discovery import (
    discover_tool,
    packaged_console_arguments,
)
from ankora_backend.adapters.tools.receptor_preparation import package_version
from ankora_backend.domain.errors import AnkoraDomainError
from ankora_backend.execution.subprocess_runner import ToolExecution, run_tool
from ankora_backend.schemas.ligands import LigandChargeModel, LigandSmartsRigidificationOutcome
from ankora_backend.schemas.v02_contracts import LigandFlexibilitySpec, MacrocyclePolicy
from ankora_backend.schemas.warnings import StructuredWarning, WarningCode


def precheck_ligand_smarts_rigidification(
    *, input_sdf_path: Path, flexibility: LigandFlexibilitySpec
) -> tuple[list[LigandSmartsRigidificationOutcome], list[StructuredWarning]]:
    """Resolve the requested query bonds against the conformer before running Meeko."""
    if len(flexibility.rigidified_smarts) != len(flexibility.rigidified_bond_indices):
        raise AnkoraDomainError(
            code="LIG_RIGIDIFY_SPEC_INVALID",
            stage="ligand_pdbqt",
            status_code=422,
            message="Each rigidification SMARTS requires exactly one bond-index pair.",
        )
    if not flexibility.rigidified_smarts:
        return [], []

    try:
        # RDKit's narrow filename API cannot open some Unicode paths on Windows.
        if os.name == "nt" and not str(input_sdf_path.resolve()).isascii():
            supplier = sdf_supplier(input_sdf_path, remove_hs=False)
        else:
            supplier = Chem.SDMolSupplier(str(input_sdf_path), removeHs=False)
        mol = next((candidate for candidate in supplier if candidate is not None), None)
    except (OSError, RuntimeError, ValueError):
        mol = None
    if mol is None:
        raise AnkoraDomainError(
            code="LIG_RIGIDIFY_INPUT_UNREADABLE",
            stage="ligand_pdbqt",
            status_code=422,
            message="RDKit could not read an input SDF molecule for the rigidification pre-check.",
        )

    outcomes: list[LigandSmartsRigidificationOutcome] = []
    warnings: list[StructuredWarning] = []
    for smarts, (idx1, idx2) in zip(
        flexibility.rigidified_smarts, flexibility.rigidified_bond_indices, strict=True
    ):
        pattern = Chem.MolFromSmarts(smarts)
        details: dict[str, object] = {"smarts": smarts, "bond_indices": [idx1, idx2]}
        if pattern is None:
            raise AnkoraDomainError(
                code="LIG_RIGIDIFY_SMARTS_INVALID",
                stage="ligand_pdbqt",
                status_code=422,
                message="RDKit could not parse the rigidification SMARTS.",
                details=details,
            )
        atom_count = pattern.GetNumAtoms()
        if (
            not 1 <= idx1 <= atom_count
            or not 1 <= idx2 <= atom_count
            or pattern.GetBondBetweenAtoms(idx1 - 1, idx2 - 1) is None
        ):
            raise AnkoraDomainError(
                code="LIG_RIGIDIFY_BOND_INDICES_INVALID",
                stage="ligand_pdbqt",
                status_code=422,
                message="The bond indices must identify two bonded atoms in the SMARTS query.",
                details=details,
            )

        matches: tuple[tuple[int, ...], ...] = mol.GetSubstructMatches(pattern, uniquify=True)
        matched_bonds: set[tuple[int, int]] = set()
        for match in matches:
            a, b = match[idx1 - 1], match[idx2 - 1]
            if mol.GetBondBetweenAtoms(a, b) is not None:
                matched_bonds.add((min(a, b), max(a, b)))
        outcomes.append(
            LigandSmartsRigidificationOutcome(
                smarts=smarts,
                bond_indices=(idx1, idx2),
                match_count=len(matches),
                matched_bonds_zero_based=sorted(matched_bonds),
                applied=bool(matches),
            )
        )
        if not matches:
            warnings.append(
                StructuredWarning(
                    code=WarningCode.LIG_RIGIDIFY_SMARTS_NO_MATCH,
                    stage="ligand_pdbqt",
                    message="The rigidification SMARTS matched no atoms in the input ligand.",
                    details=details,
                )
            )
    return outcomes, warnings


def parse_ligand_pdbqt_summary(content: bytes) -> tuple[int, list[str]]:
    """Read effective torsional degrees of freedom and atom types from Meeko's PDBQT."""
    document = content.decode("utf-8", errors="replace")
    lines = document.splitlines()
    torsdof_values: set[int] = set()
    try:
        for line in lines:
            fields = line.split()
            if not fields or fields[0] != "TORSDOF":
                continue
            if len(fields) != 2 or re.fullmatch(r"[+-]?[0-9]+", fields[1]) is None:
                raise ValueError("Malformed TORSDOF record")
            torsdof_values.add(int(fields[1]))
        if len(torsdof_values) != 1 or min(torsdof_values) < 0:
            raise ValueError("Expected one consistent non-negative TORSDOF value")
    except ValueError as error:
        raise AnkoraDomainError(
            code="MEEKO_LIGAND_TORSDOF_INVALID",
            stage="ligand_pdbqt",
            status_code=422,
            message="Meeko's ligand PDBQT must contain a consistent non-negative integer TORSDOF.",
        ) from error

    atom_types: list[str] = []
    # Existing minimal PDBQT fixtures can report TORSDOF without atom records.
    if any(line.startswith(("ATOM  ", "HETATM")) for line in lines):
        try:
            atom_types = list(collect_autodock_atom_types((document,)))
        except ValueError as error:
            raise AnkoraDomainError(
                code="MEEKO_LIGAND_ATOM_TYPES_INVALID",
                stage="ligand_pdbqt",
                status_code=422,
                message=str(error),
            ) from error
    return torsdof_values.pop(), atom_types


def execute_meeko_ligand(
    *,
    input_sdf_path: Path,
    output_pdbqt_path: Path,
    charge_model: LigandChargeModel,
    flexibility: LigandFlexibilitySpec | None = None,
) -> tuple[ToolExecution, str]:
    discovered = discover_tool(
        "mk_prepare_ligand", os.getenv("ANKORA_MEEKO_LIGAND_PATH")
    )
    if not discovered.available or discovered.path is None:
        raise AnkoraDomainError(
            code="SCIENTIFIC_TOOL_UNAVAILABLE",
            stage="ligand_pdbqt",
            message="Meeko ligand preparation is not configured on this system.",
            status_code=422,
            details={"tool": "Meeko", "executable": "mk_prepare_ligand"},
        )
    working_directory = output_pdbqt_path.resolve().parent
    # Meeko's SDF reader uses RDKit's narrow Windows filename API. A relative
    # ASCII input avoids losing Unicode parent directories; unusual filenames
    # or different drives get an exact, create-only byte copy in the job folder.
    try:
        input_argument = os.path.relpath(input_sdf_path.resolve(), working_directory)
    except ValueError:
        input_argument = ""
    if not input_argument or not input_argument.isascii():
        input_argument = f"meeko-input-{uuid4().hex}.sdf"
        with (working_directory / input_argument).open("xb") as staged:
            staged.write(input_sdf_path.read_bytes())
    arguments = [
        "-i", input_argument, "-o", str(output_pdbqt_path), "--charge_model", charge_model.value
    ]
    if flexibility is not None:
        if flexibility.macrocycle_policy is MacrocyclePolicy.RIGID_INPUT_CONFORMATION:
            arguments.append("--rigid_macrocycles")
        if flexibility.flexible_amides:
            arguments.append("--flexible_amides")
        for smarts, (idx1, idx2) in zip(
            flexibility.rigidified_smarts, flexibility.rigidified_bond_indices, strict=True
        ):
            arguments.extend(
                [
                    "--rigidify_bonds_smarts",
                    smarts,
                    "--rigidify_bonds_indices",
                    str(idx1),
                    str(idx2),
                ]
            )
    execution = run_tool(
        executable=discovered.path,
        arguments=packaged_console_arguments(
            executable=discovered.path, worker="meeko-ligand", arguments=arguments
        ),
        cwd=working_directory,
        stage="ligand_pdbqt",
    )
    return execution, package_version("meeko")
