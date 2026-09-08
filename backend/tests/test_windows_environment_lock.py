from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
CHECKER = REPOSITORY_ROOT / "scripts" / "verify_windows_environment_lock.py"


def _run_checker(root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(CHECKER), "--root", str(root)],
        check=False,
        capture_output=True,
        text=True,
    )


def _copy_environment_contract(destination: Path) -> None:
    (destination / "environment").mkdir()
    (destination / "requirements").mkdir()
    shutil.copy2(REPOSITORY_ROOT / "environment.yml", destination / "environment.yml")
    shutil.copy2(
        REPOSITORY_ROOT / "environment" / "windows-64.conda.lock",
        destination / "environment" / "windows-64.conda.lock",
    )
    for name in (
        "windows-py312.in",
        "windows-py312.lock",
        "windows-packaging.lock",
    ):
        shutil.copy2(
            REPOSITORY_ROOT / "requirements" / name,
            destination / "requirements" / name,
        )


def test_repository_windows_environment_locks_are_complete() -> None:
    result = _run_checker(REPOSITORY_ROOT)

    assert result.returncode == 0, result.stderr
    assert "36 Conda packages, 74 Python packages, and 7 packaging tools" in result.stdout


def test_conda_lock_rejects_a_package_without_sha256(tmp_path: Path) -> None:
    _copy_environment_contract(tmp_path)
    lock = tmp_path / "environment" / "windows-64.conda.lock"
    lock.write_text(lock.read_text(encoding="utf-8").replace("#95e8e740", "#95e8e74x", 1))

    result = _run_checker(tmp_path)

    assert result.returncode == 1
    assert "not SHA-256-bound" in result.stderr


def test_pip_lock_rejects_an_unhashed_requirement(tmp_path: Path) -> None:
    _copy_environment_contract(tmp_path)
    lock = tmp_path / "requirements" / "windows-py312.lock"
    lock.write_text(
        lock.read_text(encoding="utf-8").replace(
            " --hash=sha256:117bac03a25ede5df5440e855b32d556049ca169ead221505badf432fed4b101",
            "",
            1,
        ),
        encoding="utf-8",
    )

    result = _run_checker(tmp_path)

    assert result.returncode == 1
    assert "without SHA-256" in result.stderr


def test_environment_contract_rejects_local_paths(tmp_path: Path) -> None:
    _copy_environment_contract(tmp_path)
    pip_input = tmp_path / "requirements" / "windows-py312.in"
    private_drive_url = "local @ file:///" + chr(67) + ":/private/package.whl"
    pip_input.write_text(
        pip_input.read_text(encoding="utf-8") + f"\n{private_drive_url}\n",
        encoding="utf-8",
    )

    result = _run_checker(tmp_path)

    assert result.returncode == 1
    assert "local or absolute path" in result.stderr
