"""Linux launcher tests use synthetic executables and never start a desktop app."""

import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Linux Tauri launcher")
SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "tauri_linux.sh"


def _executable(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    path.chmod(0o755)


def _run(tmp_path: Path, *, existing: bool = False, custom: bool = False, fallback: bool = True):
    home = tmp_path / "home"
    binaries = tmp_path / "bin"
    cargo_home = tmp_path / "custom cargo" if custom else home / ".cargo"
    _executable(binaries / "tauri", '#!/bin/sh\ncommand -v cargo\nprintf "%s\\n" "$@"\n')
    if fallback:
        _executable(cargo_home / "bin" / "cargo", "#!/bin/sh\nexit 0\n")
    if existing:
        _executable(binaries / "cargo", "#!/bin/sh\nexit 0\n")
    env = {"HOME": str(home), "PATH": str(binaries)}
    if custom:
        env["CARGO_HOME"] = str(cargo_home)
    return (
        subprocess.run(
            ["/bin/sh", str(SCRIPT), "dev", "--config", "file with spaces.json"],
            env=env,
            capture_output=True,
            text=True,
            check=False,
        ),
        binaries,
        cargo_home,
    )


def test_discovers_rustup_cargo_and_preserves_arguments(tmp_path: Path) -> None:
    result, _, cargo_home = _run(tmp_path)
    assert result.returncode == 0
    assert result.stdout.splitlines() == [
        str(cargo_home / "bin" / "cargo"),
        "dev",
        "--config",
        "file with spaces.json",
    ]


def test_respects_existing_cargo_and_custom_cargo_home(tmp_path: Path) -> None:
    existing, binaries, _ = _run(tmp_path / "existing", existing=True)
    assert existing.stdout.splitlines()[0] == str(binaries / "cargo")
    custom, _, cargo_home = _run(tmp_path / "custom", custom=True)
    assert custom.stdout.splitlines()[0] == str(cargo_home / "bin" / "cargo")


def test_reports_missing_cargo_before_starting_tauri(tmp_path: Path) -> None:
    result, _, _ = _run(tmp_path, fallback=False)
    assert result.returncode != 0
    assert "Cargo was not found" in result.stderr
    assert result.stdout == ""
