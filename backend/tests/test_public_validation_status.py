from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
CHECKER = REPOSITORY_ROOT / "scripts" / "check_public_validation_status.py"
STATUS_FILES = (
    Path("README.md"),
    Path("docs/validation/VALIDATION_STATUS.json"),
    Path("docs/validation/VALIDATION_STATUS.md"),
    Path("docs/validation/reference_cases/SERPINE1_7AQF_RV2.manifest.json"),
    Path("docs/validation/reference_cases/SERPINE1_7AQF_RV2.md"),
    Path("docs/validation/reference_cases/PIK3CD_6OCO_M5V_RESULTS.manifest.json"),
    Path("docs/validation/reference_cases/PIK3CD_6OCO_M5V_RESULTS.md"),
)


def _run_checker(root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(CHECKER), "--root", str(root)],
        check=False,
        capture_output=True,
        text=True,
    )


def _copy_status_contract(destination: Path) -> None:
    for relative_path in STATUS_FILES:
        target = destination / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPOSITORY_ROOT / relative_path, target)


def test_repository_public_validation_status_is_synchronized() -> None:
    result = _run_checker(REPOSITORY_ROOT)

    assert result.returncode == 0, result.stderr
    assert "2 frozen cases, 1 completed independent case" in result.stdout


def test_checker_rejects_stale_readme_summary(tmp_path: Path) -> None:
    _copy_status_contract(tmp_path)
    readme = tmp_path / "README.md"
    readme.write_text(
        readme.read_text(encoding="utf-8").replace(
            "Frozen completed evidence exists", "Execution remains pending", 1
        ),
        encoding="utf-8",
    )

    result = _run_checker(tmp_path)

    assert result.returncode == 1
    assert "README public validation block is stale" in result.stderr


def test_checker_rejects_manifest_count_drift(tmp_path: Path) -> None:
    _copy_status_contract(tmp_path)
    status_path = tmp_path / "docs/validation/VALIDATION_STATUS.json"
    status = json.loads(status_path.read_text(encoding="utf-8"))
    status["reference_cases"][1]["artifact_count"] = 121
    status_path.write_text(json.dumps(status), encoding="utf-8")

    result = _run_checker(tmp_path)

    assert result.returncode == 1
    assert "artifact_count differs" in result.stderr


def test_checker_requires_completed_6oco_m5v_evidence(tmp_path: Path) -> None:
    _copy_status_contract(tmp_path)
    status_path = tmp_path / "docs/validation/VALIDATION_STATUS.json"
    status = json.loads(status_path.read_text(encoding="utf-8"))
    status["reference_cases"][1]["status"] = "frozen_with_known_gaps"
    status_path.write_text(json.dumps(status), encoding="utf-8")

    result = _run_checker(tmp_path)

    assert result.returncode == 1
    assert "PIK3CD_6OCO_M5V_RESULTS" in result.stderr
