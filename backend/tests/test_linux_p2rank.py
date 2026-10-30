"""Native (non-Windows) P2Rank execution contracts.

The `prank` launcher here is a SYNTHETIC stand-in: a `#!` Python script that
records its arguments, working directory and Java environment, then exits. It
never predicts pockets and writes no prediction CSV. The Java home holds a
synthetic ELF header that discovery reads but nothing executes. Real native
discovery and the real POSIX process runner are used; only the tool is synthetic.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

from ankora_backend.adapters.tools import pocket_detection
from ankora_backend.adapters.tools.discovery import DiscoveredTool
from ankora_backend.domain.errors import AnkoraDomainError
from ankora_backend.execution.subprocess_runner import ToolExecution

pytestmark = pytest.mark.skipif(os.name == "nt", reason="native POSIX P2Rank launcher")

METACHARACTERS = "space & $(touch injected) ; `touch injected` 'q' \"dq\" *"
SYNTHETIC_LAUNCHER = """#!{python} -I
# SYNTHETIC stand-in for the P2Rank `prank` launcher; never predicts pockets.
import json, os, sys
from pathlib import Path
Path(os.environ["SYNTHETIC_P2RANK_RECORD"]).write_text(json.dumps({{
    "argv": sys.argv[1:],
    "cwd": os.getcwd(),
    "java_home": os.environ.get("JAVA_HOME"),
    "path_head": os.environ.get("PATH", "").split(os.pathsep)[0],
}}))
sys.stdout.write("synthetic stdout \\u00fc\\n")
sys.stderr.write("synthetic stderr\\n")
sys.exit(int(os.environ.get("SYNTHETIC_P2RANK_EXIT", "0")))
"""


def _java_home(home: Path, version: str = "21.0.5") -> Path:
    """Synthetic ELF header and release metadata; never executed."""
    java = home / "bin" / "java"
    java.parent.mkdir(parents=True)
    header = bytearray(64)
    header[0:4], header[4], header[5] = b"\x7fELF", 2, 1
    header[18:20] = (0x3E).to_bytes(2, "little")
    java.write_bytes(bytes(header) + b"synthetic ELF fixture; never executed")
    java.chmod(0o755)
    (home / "release").write_text(f'JAVA_VERSION="{version}"\n', encoding="utf-8")
    return home


@pytest.fixture
def installation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    if " " in sys.executable:
        pytest.skip("a #! line cannot name an interpreter path containing spaces")
    distribution = tmp_path / f"p2rank_2.5.1 {METACHARACTERS}"
    launcher = distribution / "prank"
    distribution.mkdir()
    launcher.write_text(SYNTHETIC_LAUNCHER.format(python=sys.executable), encoding="utf-8")
    launcher.chmod(0o755)
    (distribution / "README.md").write_text(
        "synthetic P2Rank fixture release-2.5.1-green.svg", encoding="utf-8"
    )
    java_home = _java_home(tmp_path / "jdk-21")
    receptor = tmp_path / f"receptor {METACHARACTERS}.pdb"
    receptor.write_text("REMARK synthetic receptor fixture\n", encoding="utf-8")
    output = tmp_path / f"output {METACHARACTERS}"
    output.mkdir()
    record = tmp_path / "launcher-record.json"
    monkeypatch.setenv("ANKORA_P2RANK_PATH", str(launcher))
    monkeypatch.setenv("JAVA_HOME", str(java_home))
    monkeypatch.setenv("SYNTHETIC_P2RANK_RECORD", str(record))
    monkeypatch.delenv("SYNTHETIC_P2RANK_EXIT", raising=False)
    return {
        "launcher": launcher,
        "java_home": java_home,
        "receptor": receptor,
        "output": output,
        "record": record,
        "root": tmp_path,
    }


def _expected_arguments(paths: dict[str, Path]) -> list[str]:
    return [
        "predict",
        "-f",
        str(paths["receptor"]),
        "-o",
        str(paths["output"]),
        "-visualizations",
        "0",
    ]


def test_native_launcher_runs_directly_with_literal_arguments_and_discovered_java(
    installation: dict[str, Path],
) -> None:
    execution, version = pocket_detection.execute_p2rank(
        receptor_pdb_path=installation["receptor"], output_dir=installation["output"]
    )

    record = json.loads(installation["record"].read_text(encoding="utf-8"))
    launcher = str(installation["launcher"].resolve())
    assert execution.command == [launcher, *_expected_arguments(installation)]
    assert record["argv"] == _expected_arguments(installation)
    assert os.path.realpath(record["cwd"]) == os.path.realpath(installation["output"])
    assert record["java_home"] == str(installation["java_home"].resolve())
    assert record["path_head"] == str(installation["java_home"].resolve() / "bin")
    assert (execution.exit_code, execution.stdout, execution.stderr) == (
        0,
        "synthetic stdout ü\n",
        "synthetic stderr\n",
    )
    assert version == "2.5.1"
    assert not list(installation["root"].rglob("injected")), "a shell interpreted a path"
    assert not list(installation["output"].rglob("*_predictions.csv"))


def test_nonzero_launcher_exit_and_raw_streams_are_returned_unchanged(
    installation: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SYNTHETIC_P2RANK_EXIT", "3")

    execution, version = pocket_detection.execute_p2rank(
        receptor_pdb_path=installation["receptor"], output_dir=installation["output"]
    )

    assert execution.exit_code == 3
    assert execution.stdout == "synthetic stdout ü\n"
    assert execution.stderr == "synthetic stderr\n"
    assert version == "2.5.1"


def _forbid_execution(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(**_: object) -> ToolExecution:
        raise AssertionError("no process may be launched")

    monkeypatch.setattr(pocket_detection, "run_tool", forbidden)


def test_missing_launcher_is_unavailable_with_a_platform_neutral_message(
    installation: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    _forbid_execution(monkeypatch)
    monkeypatch.setenv("ANKORA_P2RANK_PATH", str(installation["root"] / "missing" / "prank"))

    with pytest.raises(AnkoraDomainError) as excinfo:
        pocket_detection.execute_p2rank(
            receptor_pdb_path=installation["receptor"], output_dir=installation["output"]
        )

    assert excinfo.value.code == "SCIENTIFIC_TOOL_UNAVAILABLE"
    assert "Windows" not in excinfo.value.message


def test_incompatible_explicit_java_is_a_missing_dependency(
    installation: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    _forbid_execution(monkeypatch)
    monkeypatch.setenv("JAVA_HOME", str(_java_home(installation["root"] / "jdk-11", "11.0.25")))

    with pytest.raises(AnkoraDomainError) as excinfo:
        pocket_detection.execute_p2rank(
            receptor_pdb_path=installation["receptor"], output_dir=installation["output"]
        )

    assert excinfo.value.code == "SCIENTIFIC_TOOL_DEPENDENCY_UNAVAILABLE"
    assert excinfo.value.details["dependency"] == "Java 17-23"


def test_frozen_backend_never_runs_p2rank_on_linux(
    installation: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    _forbid_execution(monkeypatch)
    monkeypatch.setattr("sys.frozen", True, raising=False)

    with pytest.raises(AnkoraDomainError, match="not configured"):
        pocket_detection.execute_p2rank(
            receptor_pdb_path=installation["receptor"], output_dir=installation["output"]
        )

    # Even if a payload were reported, no Windows classpath command is built.
    monkeypatch.setattr(
        pocket_detection,
        "discover_p2rank",
        lambda _: DiscoveredTool(True, str(installation["launcher"]), "2.5.1"),
    )
    monkeypatch.setattr(pocket_detection, "discover_java_home", lambda _: installation["java_home"])
    with pytest.raises(AnkoraDomainError, match="packaged P2Rank runtime is not available"):
        pocket_detection.execute_p2rank(
            receptor_pdb_path=installation["receptor"], output_dir=installation["output"]
        )


def test_native_call_keeps_stage_cwd_and_timeout(
    installation: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, object] = {}

    def capture(**kwargs: object) -> ToolExecution:
        captured.update(kwargs)
        return ToolExecution(command=[], exit_code=0, stdout="", stderr="")

    monkeypatch.setattr(pocket_detection, "run_tool", capture)

    pocket_detection.execute_p2rank(
        receptor_pdb_path=installation["receptor"], output_dir=installation["output"]
    )

    assert captured["executable"] == str(installation["launcher"].resolve())
    assert captured["arguments"] == _expected_arguments(installation)
    assert captured["stage"] == "pocket_detection"
    assert captured["cwd"] == installation["output"]
    assert captured["timeout_seconds"] == 900
