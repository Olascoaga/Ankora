"""P2Rank adapter discovery and dependency contracts.

All files are explicitly synthetic and no external tool is launched here.
"""

from pathlib import Path

import pytest

from ankora_backend.adapters.tools import pocket_detection
from ankora_backend.adapters.tools.discovery import DiscoveredTool
from ankora_backend.execution.subprocess_runner import ToolExecution


def test_execute_p2rank_uses_portable_install_version_and_discovered_java(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    p2rank_path = tmp_path / "p2rank_2.5.1" / "prank.bat"
    p2rank_path.parent.mkdir()
    p2rank_path.write_text("synthetic fixture; never executed", encoding="utf-8")
    java_home = tmp_path / "jdk-21"
    receptor = tmp_path / "receptor.pdb"
    receptor.write_text("REMARK synthetic receptor fixture\n", encoding="utf-8")
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        pocket_detection,
        "discover_p2rank",
        lambda configured: DiscoveredTool(
            available=True,
            path=str(p2rank_path),
            version="2.5.1",
        ),
    )
    monkeypatch.setattr(
        pocket_detection,
        "discover_java_home",
        lambda configured: java_home,
    )

    def fake_run_tool(**kwargs: object) -> ToolExecution:
        captured.update(kwargs)
        return ToolExecution(
            command=["cmd", "/c", str(p2rank_path)],
            exit_code=0,
            stdout="",
            stderr="",
        )

    monkeypatch.setattr(pocket_detection, "run_tool", fake_run_tool)

    execution, version = pocket_detection.execute_p2rank(
        receptor_pdb_path=receptor,
        output_dir=output_dir,
    )

    assert execution.exit_code == 0
    assert version == "2.5.1"
    assert captured["executable"] == "cmd"
    assert captured["environment"] is not None
    environment = captured["environment"]
    assert isinstance(environment, dict)
    assert environment["JAVA_HOME"] == str(java_home)
