"""P2Rank adapter for pocket detection ahead of binding-site definition.

P2Rank ships as `prank.bat` on Windows, not a `.exe`. `subprocess.run` cannot
launch a `.bat` file directly with `shell=False` (Windows' CreateProcess needs
a real executable image), so it is invoked through `cmd /c` instead of the
direct-executable pattern used by every other tool adapter in this project.
"""

import os
import sys
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
    arguments = [
        "predict",
        "-f",
        str(receptor_pdb_path),
        "-o",
        str(output_dir),
        "-visualizations",
        "0",
    ]
    if getattr(sys, "frozen", False):
        # Same heap/classpath/main class as upstream prank.bat, without cmd's
        # special-character expansion (installation paths can contain spaces/&).
        install = Path(discovered.path).parent
        executable = str(java_home / "bin" / "java.exe")
        arguments = [
            "-Xmx2048m",
            "-cp",
            f"{install / 'bin/p2rank.jar'};{install / 'bin/lib/*'}",
            "cz.siret.prank.program.Main",
            *arguments,
        ]
        for key in ("JAVA_TOOL_OPTIONS", "JDK_JAVA_OPTIONS", "_JAVA_OPTIONS", "CLASSPATH"):
            environment.pop(key, None)
    else:
        executable = "cmd"
        arguments = ["/c", discovered.path, *arguments]
    execution = run_tool(
        executable=executable,
        arguments=arguments,
        cwd=output_dir,
        stage="pocket_detection",
        timeout_seconds=P2RANK_TIMEOUT_SECONDS,
        environment=environment,
    )
    # The portable distribution exposes its release in README.md, so
    # discovery can record the version without launching the scientific tool.
    return execution, discovered.version or "unknown"
