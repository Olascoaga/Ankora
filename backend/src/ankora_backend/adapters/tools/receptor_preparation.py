"""Versioned adapters for the optional M2 receptor preparation tools."""

import json
import os
import re
import sys
from collections.abc import Callable
from importlib import import_module, metadata
from math import dist, isfinite
from pathlib import Path
from typing import TypedDict, cast

from ankora_backend.adapters.engines.autodock4 import collect_autodock_atom_types
from ankora_backend.adapters.tools.discovery import (
    discover_python_package,
    discover_tool,
    packaged_console_arguments,
    python_worker_arguments,
)
from ankora_backend.domain.errors import AnkoraDomainError
from ankora_backend.execution.subprocess_runner import ToolExecution, run_tool
from ankora_backend.schemas.receptors import (
    DISALLOWED_FLEX_RESIDUE_NAMES,
    ProtonationOverride,
    ResidueLocator,
)

PqrResidueParser = Callable[[str], object]
PqrBondFinder = Callable[[dict[str, tuple[object, str]]], object]

type _ResiduePosition = tuple[str, int, str]

_FLEX_PROTONATION_ALIASES = {
    "HID": "HIS", "HIE": "HIS", "HIP": "HIS",
    "HSD": "HIS", "HSE": "HIS", "HSP": "HIS",
    "ASH": "ASP", "GLH": "GLU", "LYN": "LYS", "CYM": "CYS",
}
_CYSTEINE_NAMES = {"CYS", "CYM", "CYX"}


class RepairOptions(TypedDict, total=False):
    repair_method: str
    repair_seed: int


def package_version(distribution: str) -> str:
    try:
        return metadata.version(distribution)
    except metadata.PackageNotFoundError:
        return "unknown"


def run_pdbfixer(
    *,
    input_path: Path,
    output_path: Path,
    residues: list[ResidueLocator],
    relaxed_output_path: Path | None = None,
    restraint_force_constant_kcal_mol_a2: float | None = None,
    relax_max_iterations: int | None = None,
    repair_method: str = "legacy",
    repair_seed: int = 20261014,
) -> tuple[ToolExecution, str]:
    discovered = discover_python_package("pdbfixer", "pdbfixer")
    if not discovered.available:
        raise _unavailable("PDBFixer", "pdbfixer", "receptor_repair")
    arguments = python_worker_arguments(
        worker="pdbfixer",
        module="ankora_backend.adapters.tools.pdbfixer_worker",
        arguments=[
            "--input",
            str(input_path),
            "--output",
            str(output_path),
        ],
    )
    for residue in residues:
        arguments.extend(
            [
                "--repair",
                "|".join(
                    (
                        residue.chain_id,
                        residue.residue_name,
                        str(residue.sequence_number),
                        residue.insertion_code,
                    )
                ),
            ]
        )
    if repair_method != "legacy":
        arguments.extend(["--repair-method", repair_method, "--repair-seed", str(repair_seed)])
    if relaxed_output_path is not None:
        assert restraint_force_constant_kcal_mol_a2 is not None
        assert relax_max_iterations is not None
        arguments.extend(
            [
                "--relax",
                "--relaxed-output",
                str(relaxed_output_path),
                "--restraint-force-constant",
                str(restraint_force_constant_kcal_mol_a2),
                "--relax-max-iterations",
                str(relax_max_iterations),
            ]
        )
    execution = run_tool(
        executable=sys.executable,
        arguments=arguments,
        cwd=output_path.parent,
        stage="receptor_repair",
    )
    _require_success(
        execution,
        "PDBFIXER_FAILED",
        "PDBFixer could not repair the selected residues.",
        "receptor_repair",
    )
    _validate_pdbfixer_result(
        execution=execution,
        requested_residue_count=len(residues),
        repaired_output_path=output_path,
        relaxed_output_path=relaxed_output_path,
    )
    if repair_method != "legacy":
        report = json.loads(execution.stdout)
        if (
            report.get("repair_method") != repair_method
            or report.get("repair_seed") != repair_seed
            or report.get("platform") != "Reference"
            or not isinstance(report.get("openmm_version"), str)
            or not report.get("openmm_version")
        ):
            raise AnkoraDomainError(
                code="PDBFIXER_REPAIR_PROTOCOL_MISMATCH",
                stage="receptor_repair",
                status_code=422,
                message="The repair worker did not apply the requested geometry protocol.",
                details={
                    "command": execution.command,
                    "stdout": execution.stdout,
                    "stderr": execution.stderr,
                    "report": report,
                },
            )
    return execution, discovered.version or package_version("pdbfixer")


def _validate_pdbfixer_result(
    *,
    execution: ToolExecution,
    requested_residue_count: int,
    repaired_output_path: Path,
    relaxed_output_path: Path | None,
) -> None:
    details: dict[str, object] = {
        "command": execution.command,
        "exit_code": execution.exit_code,
        "stdout": execution.stdout,
        "stderr": execution.stderr,
        "requested_residue_count": requested_residue_count,
    }
    try:
        report = json.loads(execution.stdout)
    except json.JSONDecodeError as error:
        details["parse_error"] = str(error)
        raise AnkoraDomainError(
            code="PDBFIXER_STRUCTURED_OUTPUT_INVALID",
            stage="receptor_repair",
            message="PDBFixer did not return its required structured repair report.",
            status_code=422,
            details=details,
        ) from error
    if not isinstance(report, dict):
        details["reported_value"] = report
        raise AnkoraDomainError(
            code="PDBFIXER_STRUCTURED_OUTPUT_INVALID",
            stage="receptor_repair",
            message="PDBFixer returned an invalid structured repair report.",
            status_code=422,
            details=details,
        )
    details["report"] = report
    requested = report.get("requested_residues")
    matched = report.get("matched_residues")
    if requested != requested_residue_count or matched != requested_residue_count:
        raise AnkoraDomainError(
            code="PDBFIXER_REPAIR_INCOMPLETE",
            stage="receptor_repair",
            message=(
                "PDBFixer did not match every residue explicitly selected for repair."
            ),
            status_code=422,
            details=details,
        )
    if not repaired_output_path.is_file():
        details["missing_output"] = str(repaired_output_path)
        raise AnkoraDomainError(
            code="PDBFIXER_OUTPUT_MISSING",
            stage="receptor_repair",
            message="PDBFixer reported success without creating the repaired receptor.",
            status_code=422,
            details=details,
        )
    if relaxed_output_path is None:
        return
    relaxation = report.get("relaxation")
    if not isinstance(relaxation, dict) or relaxation.get("relaxed") is not True:
        raise AnkoraDomainError(
            code="RECEPTOR_RELAXATION_NOT_APPLIED",
            stage="receptor_relaxation",
            message=(
                "PDBFixer did not apply the explicitly requested restrained relaxation."
            ),
            status_code=422,
            details=details,
        )
    if not relaxed_output_path.is_file():
        details["missing_output"] = str(relaxed_output_path)
        raise AnkoraDomainError(
            code="PDBFIXER_OUTPUT_MISSING",
            stage="receptor_relaxation",
            message="PDBFixer reported relaxation without creating its receptor output.",
            status_code=422,
            details=details,
        )


def run_pdb2pqr_propka(
    *,
    input_path: Path,
    pqr_output_path: Path,
    pdb_output_path: Path,
    ph: float,
    force_field: str,
    overrides: list[ProtonationOverride] | None = None,
) -> tuple[ToolExecution, str, dict[str, object]]:
    discovered = discover_tool("pdb2pqr", os.getenv("ANKORA_PDB2PQR_PATH"))
    if not discovered.available or discovered.path is None:
        raise _unavailable("PDB2PQR", "pdb2pqr", "receptor_protonation")
    worker_arguments = [
        "--input",
        str(input_path),
        "--pqr-output",
        str(pqr_output_path),
        "--pdb-output",
        str(pdb_output_path),
        "--ph",
        f"{ph:g}",
        "--force-field",
        force_field,
    ]
    for override in overrides or []:
        worker_arguments.extend(
            [
                "--override",
                json.dumps(
                    override.model_dump(mode="json"),
                    separators=(",", ":"),
                    sort_keys=True,
                ),
            ]
        )
    arguments = python_worker_arguments(
        worker="pdb2pqr",
        module="ankora_backend.adapters.tools.pdb2pqr_worker",
        arguments=worker_arguments,
    )
    execution = run_tool(
        executable=sys.executable,
        arguments=arguments,
        cwd=pqr_output_path.parent,
        stage="receptor_protonation",
    )
    _require_success(
        execution,
        "PDB2PQR_PROPKA_FAILED",
        "PDB2PQR/PROPKA could not protonate the selected receptor.",
        "receptor_protonation",
    )
    report = _pdb2pqr_report(execution)
    version = f"pdb2pqr {package_version('pdb2pqr')}; propka {package_version('propka')}"
    return execution, version, report


def _pdb2pqr_report(execution: ToolExecution) -> dict[str, object]:
    details: dict[str, object] = {
        "command": execution.command,
        "exit_code": execution.exit_code,
        "stdout": execution.stdout,
        "stderr": execution.stderr,
    }
    try:
        report = json.loads(execution.stdout)
    except json.JSONDecodeError as error:
        details["parse_error"] = str(error)
        raise AnkoraDomainError(
            code="PDB2PQR_STRUCTURED_OUTPUT_INVALID",
            stage="receptor_protonation",
            message="PDB2PQR did not return its required structured pKa report.",
            status_code=422,
            details=details,
        ) from error
    if not isinstance(report, dict) or not isinstance(report.get("predictions"), list):
        details["reported_value"] = report
        raise AnkoraDomainError(
            code="PDB2PQR_STRUCTURED_OUTPUT_INVALID",
            stage="receptor_protonation",
            message="PDB2PQR returned an invalid structured pKa report.",
            status_code=422,
            details=details,
        )
    return cast(dict[str, object], report)


def run_meeko_receptor(
    *, input_pqr_path: Path, output_pdbqt_path: Path
) -> tuple[ToolExecution, str]:
    return _run_meeko_receptor(
        input_pqr_path=input_pqr_path,
        output_stem_path=output_pdbqt_path.with_suffix(""),
        output_pdbqt_path=output_pdbqt_path,
    )


def run_meeko_receptor_flex(
    *, input_pqr_path: Path, output_stem_path: Path, flex_residues: list[ResidueLocator]
) -> tuple[ToolExecution, str, Path, Path]:
    execution, version = _run_meeko_receptor(
        input_pqr_path=input_pqr_path,
        output_stem_path=output_stem_path,
        output_pdbqt_path=Path(f"{output_stem_path}.pdbqt"),
        flex_residue_spec=format_meeko_flex_residue_spec(flex_residues),
    )
    rigid_path = output_stem_path.parent / f"{output_stem_path.name}_rigid.pdbqt"
    flex_path = output_stem_path.parent / f"{output_stem_path.name}_flex.pdbqt"
    incomplete = [
        path.name for path in (rigid_path, flex_path)
        if not path.is_file() or path.stat().st_size == 0
    ]
    if incomplete:
        raise _flex_error(
            "MEEKO_FLEXRES_SPLIT_INCOMPLETE",
            "Meeko did not produce both non-empty receptor split files.",
            incomplete_outputs=incomplete,
            command=execution.command,
            exit_code=execution.exit_code,
            stdout=execution.stdout,
            stderr=execution.stderr,
            tool_version=version,
        )
    return execution, version, rigid_path, flex_path


def _run_meeko_receptor(
    *,
    input_pqr_path: Path,
    output_stem_path: Path,
    output_pdbqt_path: Path,
    flex_residue_spec: str | None = None,
) -> tuple[ToolExecution, str]:
    discovered = discover_tool("mk_prepare_receptor", os.getenv("ANKORA_MEEKO_PATH"))
    if not discovered.available or discovered.path is None:
        raise _unavailable("Meeko", "mk_prepare_receptor", "receptor_pdbqt")
    tool_arguments = [
        "--read_pqr", str(input_pqr_path), "--charge_model", "read",
        "-o", str(output_stem_path), "-p", str(output_pdbqt_path),
    ]
    if flex_residue_spec is not None:
        tool_arguments.extend(["-f", flex_residue_spec])
    arguments = packaged_console_arguments(
        executable=discovered.path,
        worker="meeko-receptor",
        arguments=tool_arguments,
    )
    execution = run_tool(
        executable=discovered.path,
        arguments=arguments,
        cwd=output_pdbqt_path.parent,
        stage="receptor_pdbqt",
    )
    version = package_version("meeko")
    affected_residues: list[dict[str, object]] = []
    diagnostic_error: str | None = None
    if execution.exit_code != 0:
        try:
            affected_residues = diagnose_meeko_pqr_connectivity(input_pqr_path)
        except Exception as error:  # Never mask the preserved Meeko execution failure.
            diagnostic_error = f"{type(error).__name__}: {error}"
    extra_details: dict[str, object] | None = None
    if execution.exit_code != 0:
        extra_details = {
            "affected_residues": affected_residues,
            "possible_actions": ["remove", "manual_review"],
        }
        if diagnostic_error is not None:
            extra_details["connectivity_diagnostic_error"] = diagnostic_error
        if flex_residue_spec is not None:
            extra_details["tool_version"] = version
    _require_success(
        execution,
        "MEEKO_CONNECTIVITY_FAILURE",
        "Meeko could not generate a docking-ready receptor from the explicit preparation plan.",
        "receptor_pdbqt",
        extra_details=extra_details,
    )
    return execution, version


def _flex_error(code: str, message: str, **details: object) -> AnkoraDomainError:
    return AnkoraDomainError(
        code=code, stage="receptor_pdbqt", message=message, status_code=422, details=details
    )


def _residue_position(residue: ResidueLocator) -> _ResiduePosition:
    return residue.chain_id, residue.sequence_number, residue.insertion_code


def validate_flex_residues_against_pqr(
    pqr_path: Path, flex_residues: list[ResidueLocator]
) -> list[ResidueLocator]:
    """Resolve the explicit selection and reject unsupported side chains before Meeko."""
    if not flex_residues:
        raise _flex_error("RECEPTOR_FLEXRES_EMPTY", "Select at least one flexible residue.")
    requested: set[_ResiduePosition] = set()
    for residue in flex_residues:
        position = _residue_position(residue)
        if position in requested:
            raise _flex_error(
                "RECEPTOR_FLEXRES_DUPLICATE",
                "Flexible residue positions must be unique.",
                residue=residue.model_dump(mode="json"),
            )
        requested.add(position)
        if residue.residue_name.upper() in DISALLOWED_FLEX_RESIDUE_NAMES:
            raise _flex_error(
                "RECEPTOR_FLEXRES_DISALLOWED_RESIDUE",
                "The selected residue is disallowed for side-chain flexibility.",
                residue=residue.model_dump(mode="json"),
            )

    by_position: dict[_ResiduePosition, ResidueLocator] = {}
    ambiguous: set[_ResiduePosition] = set()
    atom_names: set[str] = set()
    previous_position: _ResiduePosition | None = None
    sulfur_atoms: list[tuple[_ResiduePosition, tuple[float, float, float]]] = []
    malformed_sulfurs: set[_ResiduePosition] = set()
    for line in pqr_path.read_text(encoding="utf-8").splitlines():
        locator = _pqr_residue_locator(line)
        if locator is None:
            previous_position = None
            continue
        position = _residue_position(locator)
        if position != previous_position:
            if position in by_position:
                ambiguous.add(position)
            previous_position = position
            atom_names = set()
        tokens = line.split()
        atom_name = tokens[2] if tokens[0] in {"ATOM", "HETATM"} else tokens[1]
        if atom_name in atom_names or by_position.setdefault(position, locator) != locator:
            ambiguous.add(position)
        atom_names.add(atom_name)
        if locator.residue_name.upper() in _CYSTEINE_NAMES and atom_name == "SG":
            try:
                x, y, z = map(float, tokens[-5:-2])
                if not all(map(isfinite, (x, y, z))):
                    raise ValueError("Non-finite sulfur coordinates")
            except ValueError:
                malformed_sulfurs.add(position)
            else:
                sulfur_atoms.append((position, (x, y, z)))

    resolved = []
    for residue in flex_residues:
        position = _residue_position(residue)
        prepared = by_position.get(position)
        if prepared is None or position in ambiguous:
            raise _flex_error(
                "RECEPTOR_FLEXRES_UNRESOLVED",
                "The selected residue does not resolve uniquely in the prepared PQR.",
                residue=residue.model_dump(mode="json"),
            )
        name = residue.residue_name.upper()
        prepared_name = prepared.residue_name.upper()
        if prepared_name in DISALLOWED_FLEX_RESIDUE_NAMES:
            raise _flex_error(
                "RECEPTOR_FLEXRES_DISALLOWED_RESIDUE",
                "The prepared residue is disallowed for side-chain flexibility.",
                residue=residue.model_dump(mode="json"),
                prepared_residue=prepared.model_dump(mode="json"),
            )
        if _FLEX_PROTONATION_ALIASES.get(name, name) != _FLEX_PROTONATION_ALIASES.get(
            prepared_name, prepared_name
        ):
            raise _flex_error(
                "RECEPTOR_FLEXRES_UNRESOLVED",
                "The selected residue name differs from the prepared PQR residue.",
                residue=residue.model_dump(mode="json"),
                prepared_residue=prepared.model_dump(mode="json"),
            )
        if prepared_name in _CYSTEINE_NAMES:
            sulfur = next((xyz for key, xyz in sulfur_atoms if key == position), None)
            if sulfur is None or malformed_sulfurs:
                raise _flex_error(
                    "RECEPTOR_FLEXRES_UNRESOLVED",
                    "The prepared PQR lacks readable cysteine sulfur coordinates.",
                    residue=residue.model_dump(mode="json"),
                )
            partner = next(
                (key for key, xyz in sulfur_atoms if key != position and dist(sulfur, xyz) <= 2.2),
                None,
            )
            if partner is not None:
                raise _flex_error(
                    "RECEPTOR_FLEXRES_DISULFIDE_CYS",
                    "Disulfide-bonded cysteine cannot be selected for side-chain flexibility.",
                    residue=residue.model_dump(mode="json"),
                    partner=by_position[partner].model_dump(mode="json"),
                )
        resolved.append(prepared)
    return resolved


def format_meeko_flex_residue_spec(residues: list[ResidueLocator]) -> str:
    return ",".join(f"{r.chain_id}:{r.sequence_number}{r.insertion_code}" for r in residues)


def inspect_receptor_flex_pdbqt(flex_pdbqt_text: str) -> tuple[int, tuple[str, ...]]:
    """Read Meeko's residue blocks, torsion branches, and AutoDock atom types."""
    open_residue: list[str] | None = None
    block_count = 0
    added_chi_torsion_count = 0
    try:
        for line in flex_pdbqt_text.splitlines():
            tokens = line.split()
            if not tokens:
                continue
            record, *fields = tokens
            if record == "BEGIN_RES":
                if open_residue is not None:
                    raise ValueError("Nested BEGIN_RES markers")
                open_residue = fields
            elif record == "END_RES":
                if open_residue != fields:
                    raise ValueError("END_RES does not match an open BEGIN_RES")
                open_residue = None
                block_count += 1
            elif record == "BRANCH":
                if open_residue is None:
                    raise ValueError("BRANCH outside a flexible residue block")
                added_chi_torsion_count += 1
        if open_residue is not None or not block_count or not added_chi_torsion_count:
            raise ValueError("Expected complete flexible residue blocks with torsion branches")
        atom_types = collect_autodock_atom_types((flex_pdbqt_text,))
    except ValueError as error:
        raise _flex_error(
            "MEEKO_FLEXRES_OUTPUT_INVALID",
            "Meeko produced invalid flexible receptor PDBQT.",
            reason=str(error),
        ) from error
    return added_chi_torsion_count, atom_types


def diagnose_meeko_pqr_connectivity(input_pqr_path: Path) -> list[dict[str, object]]:
    """Identify residue blocks that Meeko cannot convert into valid RDKit molecules."""
    return diagnose_meeko_pqr_content(input_pqr_path.read_text())


def diagnose_meeko_pqr_content(content: str, *, required: bool = False) -> list[dict[str, object]]:
    tools = _load_meeko_pqr_tools()
    if tools is None:
        if required:
            raise AnkoraDomainError(
                code="RECEPTOR_GEOMETRY_CHECK_UNAVAILABLE",
                stage="receptor_geometry",
                status_code=422,
                message="The required Meeko geometry check is unavailable.",
                details={},
            )
        return []
    parser, bond_finder = tools
    try:
        return _diagnose_pqr_connectivity(content, parser, bond_finder, required=required)
    except AnkoraDomainError:
        raise
    except Exception as error:
        if not required:
            raise
        raise AnkoraDomainError(
            code="RECEPTOR_GEOMETRY_CHECK_FAILED", stage="receptor_geometry",
            status_code=422, message="The required PQR connectivity check failed.",
            details={"diagnostic_error": f"{type(error).__name__}: {error}"},
        ) from error


def _diagnose_pqr_connectivity(
    pqr_text: str,
    parser: PqrResidueParser,
    bond_finder: PqrBondFinder | None = None,
    *, required: bool = False,
) -> list[dict[str, object]]:
    residue_blocks: dict[tuple[str, str, int, str], list[str]] = {}
    for line in pqr_text.splitlines(keepends=True):
        locator = _pqr_residue_locator(line)
        if locator is None:
            continue
        key = (
            locator.chain_id,
            locator.residue_name,
            locator.sequence_number,
            locator.insertion_code,
        )
        residue_blocks.setdefault(key, []).append(line)

    if required and not residue_blocks:
        raise AnkoraDomainError(
            code="RECEPTOR_GEOMETRY_CHECK_FAILED", stage="receptor_geometry",
            status_code=422, message="The geometry check found no readable PQR residues.",
            details={},
        )

    affected: list[dict[str, object]] = []
    affected_keys: set[tuple[str, str, int, str]] = set()
    parsed_residues: dict[str, tuple[object, str]] = {}
    locators_by_meeko_key: dict[str, ResidueLocator] = {}
    for (chain_id, residue_name, sequence_number, insertion_code), lines in residue_blocks.items():
        locator = ResidueLocator(
            chain_id=chain_id,
            residue_name=residue_name,
            sequence_number=sequence_number,
            insertion_code=insertion_code,
        )
        meeko_key = f"{chain_id}:{sequence_number}{insertion_code}"
        locators_by_meeko_key[meeko_key] = locator
        try:
            parsed = parser("".join(lines))
            if isinstance(parsed, dict):
                payload = parsed.get(meeko_key)
                if (
                    isinstance(payload, tuple)
                    and len(payload) >= 2
                    and payload[0] is not None
                    and isinstance(payload[1], str)
                ):
                    parsed_residues[meeko_key] = (payload[0], payload[1])
                    continue
            if required:
                raise ValueError("Meeko did not return the expected residue molecule")
        except Exception as error:  # Meeko/RDKit exposes several versioned exception types.
            affected.append(_affected_residue(locator, f"{type(error).__name__}: {error}"))
            affected_keys.add((chain_id, residue_name, sequence_number, insertion_code))

    if bond_finder is not None and parsed_residues:
        bonds = bond_finder(parsed_residues)
        if required and not isinstance(bonds, dict):
            raise AnkoraDomainError(
                code="RECEPTOR_GEOMETRY_CHECK_FAILED", stage="receptor_geometry",
                status_code=422, message="Meeko did not return structured inter-residue bonds.",
                details={},
            )
        if isinstance(bonds, dict):
            for pair, atom_pairs in bonds.items():
                if (
                    not isinstance(pair, tuple)
                    or len(pair) != 2
                    or not all(isinstance(item, str) for item in pair)
                    or not isinstance(atom_pairs, (list, tuple))
                ):
                    continue
                left_key, right_key = pair
                left_locator = locators_by_meeko_key.get(left_key)
                right_locator = locators_by_meeko_key.get(right_key)
                if left_locator is None or right_locator is None:
                    continue
                atom_names = _inter_residue_atom_names(
                    parsed_residues, left_key, right_key, atom_pairs
                )
                if not _is_unexpected_inter_residue_bond(
                    left_locator, right_locator, atom_names, len(atom_pairs)
                ):
                    continue
                for residue_key in (left_key, right_key):
                    locator = locators_by_meeko_key.get(residue_key)
                    if locator is None:
                        continue
                    key = (
                        locator.chain_id,
                        locator.residue_name,
                        locator.sequence_number,
                        locator.insertion_code,
                    )
                    if key in affected_keys:
                        continue
                    affected.append(
                        _affected_residue(
                            locator,
                            (
                                f"Meeko inferred {len(atom_pairs)} inter-residue "
                                f"{'bond' if len(atom_pairs) == 1 else 'bonds'} "
                                f"between {left_key} and {right_key}."
                            ),
                            related_residue_keys=[left_key, right_key],
                            inter_residue_bond_count=len(atom_pairs),
                            inter_residue_bonds=[
                                f"{left_atom or '?'}-{right_atom or '?'}"
                                for left_atom, right_atom in atom_names
                            ],
                        )
                    )
                    affected_keys.add(key)
    return affected


def _affected_residue(
    locator: ResidueLocator,
    diagnostic: str,
    *,
    related_residue_keys: list[str] | None = None,
    inter_residue_bond_count: int | None = None,
    inter_residue_bonds: list[str] | None = None,
) -> dict[str, object]:
    result: dict[str, object] = {
        **locator.model_dump(),
        "diagnostic": diagnostic,
    }
    if related_residue_keys is not None:
        result["related_residue_keys"] = related_residue_keys
    if inter_residue_bond_count is not None:
        result["inter_residue_bond_count"] = inter_residue_bond_count
    if inter_residue_bonds is not None:
        result["inter_residue_bonds"] = inter_residue_bonds
    return result


def _inter_residue_atom_names(
    parsed_residues: dict[str, tuple[object, str]],
    left_key: str,
    right_key: str,
    atom_pairs: list[object] | tuple[object, ...],
) -> list[tuple[str | None, str | None]]:
    left_molecule = parsed_residues[left_key][0]
    right_molecule = parsed_residues[right_key][0]
    names: list[tuple[str | None, str | None]] = []
    for pair in atom_pairs:
        if (
            not isinstance(pair, tuple)
            or len(pair) != 2
            or not all(isinstance(index, int) for index in pair)
        ):
            names.append((None, None))
            continue
        names.append(
            (
                _rdkit_atom_name(left_molecule, pair[0]),
                _rdkit_atom_name(right_molecule, pair[1]),
            )
        )
    return names


def _rdkit_atom_name(molecule: object, atom_index: int) -> str | None:
    try:
        # Meeko supplies a dynamically imported RDKit molecule at this optional boundary.
        atom_getter = getattr(molecule, "GetAtomWithIdx")  # noqa: B009
        atom = atom_getter(atom_index)
        residue_info = atom.GetPDBResidueInfo()
        return str(residue_info.GetName()).strip()
    except (AttributeError, IndexError, TypeError):
        return None


def _is_unexpected_inter_residue_bond(
    left: ResidueLocator,
    right: ResidueLocator,
    atom_names: list[tuple[str | None, str | None]],
    bond_count: int,
) -> bool:
    if bond_count > 1:
        return True
    if bond_count != 1:
        return False
    left_atom, right_atom = atom_names[0] if atom_names else (None, None)
    if {left_atom, right_atom} == {"C", "N"}:
        return False
    if (
        left.residue_name == "CYS"
        and right.residue_name == "CYS"
        and left_atom == "SG"
        and right_atom == "SG"
    ):
        return False
    if left_atom is not None and right_atom is not None:
        return True
    return not (
        left.chain_id == right.chain_id
        and abs(left.sequence_number - right.sequence_number) <= 1
    )


def _pqr_residue_locator(line: str) -> ResidueLocator | None:
    # PDB2PQR uses PDB-style fixed columns. Once a residue reaches four digits,
    # the human-readable split token is compact (for example `A1000`) rather
    # than `A 1000`; fixed columns remain unambiguous.
    record = line[0:6].strip()
    if record not in {"ATOM", "HETATM"}:
        return None
    if len(line) >= 27:
        residue_name = line[17:20].strip()
        chain_id = line[21:22].strip()
        sequence_text = line[22:26].strip()
        insertion_code = line[26:27].strip()
        # Ankora inserts spaces at compact locator boundaries for Meeko.
        # Those forms shift the fixed columns, so read them as tokens.
        normalized_sequence = line[22:23] == " " and line[23:27].isdigit()
        normalized_insertion = line[26:27] == " " and line[27:28].isalpha()
        if residue_name and sequence_text and not (normalized_sequence or normalized_insertion):
            try:
                return ResidueLocator(
                    chain_id=chain_id,
                    residue_name=residue_name,
                    sequence_number=int(sequence_text),
                    insertion_code=insertion_code,
                )
            except ValueError:
                pass

    # Keep a guarded fallback for non-column-aligned PQR writers. It accepts
    # separate or compact one-character chains and optional insertion codes,
    # but malformed coordinate text is never reinterpreted as a residue id.
    items = line.split()
    if not items:
        return None
    items.pop(0)
    if len(items) < 8:
        return None
    items.pop(0)  # serial
    items.pop(0)  # atom name
    residue_name = items.pop(0)
    chain_or_number = items.pop(0)
    parsed = _parse_pqr_residue_token(chain_or_number)
    if parsed is None:
        chain_id = chain_or_number
        if not items:
            return None
        parsed = _parse_pqr_residue_token(items.pop(0))
        if parsed is None or parsed[0]:
            return None
        _, sequence_number, insertion_code = parsed
    else:
        parsed_chain, sequence_number, insertion_code = parsed
        chain_id = parsed_chain
    if not insertion_code and items:
        try:
            float(items[0])
        except ValueError:
            insertion_code = items.pop(0)
    return ResidueLocator(
        chain_id=chain_id,
        residue_name=residue_name,
        sequence_number=sequence_number,
        insertion_code=insertion_code,
    )


_PQR_RESIDUE_TOKEN = re.compile(
    r"^(?:(?P<chain>[^0-9+\-.]))?(?P<number>[+-]?\d+)(?P<insertion>[A-Za-z]?)$"
)


def _parse_pqr_residue_token(token: str) -> tuple[str, int, str] | None:
    matched = _PQR_RESIDUE_TOKEN.fullmatch(token)
    if matched is None:
        return None
    return (
        matched.group("chain") or "",
        int(matched.group("number")),
        matched.group("insertion") or "",
    )


def _load_meeko_pqr_tools() -> tuple[PqrResidueParser, PqrBondFinder] | None:
    try:
        module = import_module("meeko.polymer")
    except ImportError:
        return None
    polymer = getattr(module, "Polymer", None)
    parser = getattr(polymer, "_pqr_to_residue_mols", None)
    bond_finder = getattr(module, "find_inter_mols_bonds", None)
    if not callable(parser) or not callable(bond_finder):
        return None
    return cast(PqrResidueParser, parser), cast(PqrBondFinder, bond_finder)


def _unavailable(display_name: str, tool_name: str, stage: str) -> AnkoraDomainError:
    return AnkoraDomainError(
        code="RECEPTOR_TOOL_UNAVAILABLE",
        stage=stage,
        message=(
            f"{display_name} is required for this requested preparation stage "
            "but is not configured."
        ),
        status_code=409,
        details={"tool": tool_name},
    )


def _require_success(
    execution: ToolExecution,
    code: str,
    message: str,
    stage: str,
    extra_details: dict[str, object] | None = None,
) -> None:
    if execution.exit_code == 0:
        return
    details: dict[str, object] = {
        "command": execution.command,
        "exit_code": execution.exit_code,
        "stdout": execution.stdout,
        "stderr": execution.stderr,
    }
    if extra_details:
        details.update(extra_details)
    raise AnkoraDomainError(
        code=code,
        stage=stage,
        message=message,
        status_code=422,
        details=details,
    )
