"""Versioned Meeko adapter for ligand PDBQT preparation."""

import os
from pathlib import Path
from uuid import uuid4

from ankora_backend.adapters.tools.discovery import (
    discover_tool,
    packaged_console_arguments,
)
from ankora_backend.adapters.tools.receptor_preparation import package_version
from ankora_backend.domain.errors import AnkoraDomainError
from ankora_backend.execution.subprocess_runner import ToolExecution, run_tool
from ankora_backend.schemas.ligands import LigandChargeModel


def execute_meeko_ligand(
    *,
    input_sdf_path: Path,
    output_pdbqt_path: Path,
    charge_model: LigandChargeModel,
) -> tuple[ToolExecution, str]:
    discovered = discover_tool(
        "mk_prepare_ligand", os.getenv("ANKORA_MEEKO_LIGAND_PATH")
    )
    if not discovered.available or discovered.path is None:
        raise AnkoraDomainError(
            code="SCIENTIFIC_TOOL_UNAVAILABLE",
            stage="ligand_pdbqt",
            message="Meeko ligand preparation is not configured on this Windows system.",
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
    arguments = packaged_console_arguments(
        executable=discovered.path,
        worker="meeko-ligand",
        arguments=[
            "-i",
            input_argument,
            "-o",
            str(output_pdbqt_path),
            "--charge_model",
            charge_model.value,
        ],
    )
    execution = run_tool(
        executable=discovered.path,
        arguments=arguments,
        cwd=working_directory,
        stage="ligand_pdbqt",
    )
    return execution, package_version("meeko")
