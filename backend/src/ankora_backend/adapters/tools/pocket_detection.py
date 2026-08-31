"""P2Rank adapter for pocket detection ahead of binding-site definition.

P2Rank ships as `prank.bat` on Windows, not a `.exe`. `subprocess.run` cannot
launch a `.bat` file directly with `shell=False` (Windows' CreateProcess needs
a real executable image), so it is invoked through `cmd /c` instead of the
direct-executable pattern used by every other tool adapter in this project.
"""

import os
from pathlib import Path

from ankora_backend.adapters.tools.discovery import discover_java_home, discover_p2rank
from ankora_backend.domain.errors import AnkoraDomainError
from ankora_backend.execution.subprocess_runner import ToolExecution, run_tool

P2RANK_TIMEOUT_SECONDS = 900


def execute_p2rank(*, receptor_pdb_path: Path, output_dir: Path) -> tuple[ToolExecution, str]:
    discovered = discover_p2rank(os.getenv("ANKORA_P2RANK_PATH"))
    if not discovered.available or discovered.path is None:
        raise AnkoraDomainError(
            code="SCIENTIFIC_TOOL_UNAVAILABLE",
            stage="pocket_detection",
            message="P2Rank is not configured on this Windows system.",
            status_code=422,
            details={"tool": "P2Rank", "executable": "prank"},
        )
    java_home = discover_java_home(os.getenv("JAVA_HOME"))
    if java_home is None:
        raise AnkoraDomainError(
            code="SCIENTIFIC_TOOL_DEPENDENCY_UNAVAILABLE",
            stage="pocket_detection",
            message="P2Rank is installed, but a compatible Java runtime was not found.",
            status_code=422,
            details={"tool": "P2Rank", "dependency": "Java 17-23"},
        )
    environment = os.environ.copy()
    environment["JAVA_HOME"] = str(java_home)
    execution = run_tool(
        executable="cmd",
        arguments=[
            "/c",
            discovered.path,
            "predict",
            "-f",
            str(receptor_pdb_path),
            "-o",
            str(output_dir),
            "-visualizations",
            "0",
        ],
        cwd=output_dir,
        stage="pocket_detection",
        timeout_seconds=P2RANK_TIMEOUT_SECONDS,
        environment=environment,
    )
    # The portable distribution exposes its release in README.md, so
    # discovery can record the version without launching the scientific tool.
    return execution, discovered.version or "unknown"
