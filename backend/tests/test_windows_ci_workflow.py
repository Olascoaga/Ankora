"""Regression contracts for the Windows CI Python environment.

Observed failures this guards against: run 40803611622 resolved unlocked
versions through `pip install -e backend[dev]`, and run 40808598327 failed
`pip check` because the hosted base interpreter's own pipx 1.18.4 conflicted
with the locked filelock/packaging. Hosted CI success is not implied here.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml  # type: ignore[import-untyped]  # PyYAML is locked; its stubs are not.

WORKFLOW = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "ci.yml"
ISOLATE = "Create isolated Python environment"
VERIFY = "Verify the isolated Python environment"


def _steps() -> list[dict[str, Any]]:
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    steps: list[dict[str, Any]] = workflow["jobs"]["verify"]["steps"]
    return steps


def _index(steps: list[dict[str, Any]], name: str) -> int:
    return next(index for index, step in enumerate(steps) if step.get("name") == name)


def _uses_python(step: dict[str, Any]) -> bool:
    return step.get("shell") == "python" or "python" in str(step.get("run", "")).split()


def test_isolated_environment_is_created_from_the_setup_python_interpreter() -> None:
    steps = _steps()
    setup = next(
        i for i, s in enumerate(steps) if str(s.get("uses", "")).startswith("actions/setup-python")
    )
    isolate = _index(steps, ISOLATE)

    assert steps[setup]["id"] == "setup-python"
    assert (isolate, _index(steps, VERIFY)) == (setup + 1, setup + 2)
    command = steps[isolate]["run"]
    assert '& "${{ steps.setup-python.outputs.python-path }}" -m venv $venv' in command
    assert "--system-site-packages" not in command
    assert "if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }" in command
    assert "Out-File -FilePath $env:GITHUB_PATH" in command
    assert "Out-File -FilePath $env:GITHUB_ENV" in command
    assert steps[_index(steps, VERIFY)]["shell"] == "python"


def test_no_step_uses_the_hosted_interpreter() -> None:
    steps = _steps()
    isolate = _index(steps, ISOLATE)

    assert not [step["name"] for step in steps[:isolate] if _uses_python(step)]
    for step in steps[isolate + 1 :]:
        text = str(step.get("run", ""))
        assert "setup-python.outputs" not in text and "pythonLocation" not in text
        assert not text.lstrip().startswith(("py ", "py.exe"))


def test_locked_installs_and_consistency_gates_remain_in_order() -> None:
    steps = _steps()
    runs = [str(step.get("run", "")) for step in steps]
    order = [
        runs.index(
            "python -m pip install --require-hashes --only-binary=:all: "
            "-r requirements/windows-py312.lock"
        ),
        runs.index(
            "python -m pip install --require-hashes --only-binary=:all: "
            "-r requirements/windows-packaging.lock"
        ),
        runs.index("python -m pip install --no-deps --no-build-isolation -e backend"),
        runs.index("python -m pip check"),
        _index(steps, "Verify installed versions match the Windows locks"),
        runs.index("python -m pytest backend"),
    ]

    assert order == sorted(order)
    assert order[0] > _index(steps, VERIFY)
    assert not [run for run in runs if "backend[dev]" in run]


def _verification_script() -> str:
    steps = _steps()
    script = steps[_index(steps, VERIFY)]["run"]
    assert isinstance(script, str)
    return script


def _run_verification(interpreter: Path | str, venv: Path) -> subprocess.CompletedProcess[str]:
    environment = {key: value for key, value in os.environ.items() if key != "PYTHONPATH"}
    environment["VIRTUAL_ENV"] = str(venv)
    return subprocess.run(
        [str(interpreter), "-c", _verification_script()],
        capture_output=True,
        text=True,
        env=environment,
        timeout=60,
        check=False,
    )


def _venv_python(venv: Path) -> Path:
    return venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def _create(venv: Path, *options: str) -> None:
    subprocess.run(
        [sys.executable, "-m", "venv", "--without-pip", *options, str(venv)],
        check=True,
        timeout=120,
    )


def test_verification_accepts_a_clean_environment_and_rejects_the_base_interpreter(
    tmp_path: Path,
) -> None:
    venv = tmp_path / "clean"
    _create(venv)

    accepted = _run_verification(_venv_python(venv), venv)
    rejected = _run_verification(sys.executable, venv)

    assert accepted.returncode == 0, accepted.stderr
    assert "Isolated interpreter" in accepted.stdout
    assert rejected.returncode != 0
    assert "not the isolated environment" in rejected.stderr


def test_verification_rejects_visible_system_packages(tmp_path: Path) -> None:
    venv = tmp_path / "leaky"
    _create(venv, "--system-site-packages")
    visible = subprocess.run(
        [
            str(_venv_python(venv)),
            "-c",
            "import importlib.metadata as m; print(len(list(m.distributions())))",
        ],
        capture_output=True,
        text=True,
        check=True,
        timeout=60,
    )
    if int(visible.stdout) == 0:
        pytest.skip("the base interpreter has no distributions that could leak")

    rejected = _run_verification(_venv_python(venv), venv)

    assert rejected.returncode != 0
    assert "outside the isolated environment" in rejected.stderr or "User site" in rejected.stderr
