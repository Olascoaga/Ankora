"""Versioned Meeko adapter for ligand PDBQT preparation."""

import os
from pathlib import Path

from ankora_backend.adapters.tools.discovery import discover_tool
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
    execution = run_tool(
        executable=discovered.path,
        arguments=[
            "-i",
            str(input_sdf_path),
            "-o",
            str(output_pdbqt_path),
            "--charge_model",
            charge_model.value,
        ],
        cwd=output_pdbqt_path.parent,
        stage="ligand_pdbqt",
    )
    return execution, package_version("meeko")
