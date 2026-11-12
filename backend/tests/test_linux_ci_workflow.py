"""Regression contracts for the Ubuntu 24.04 Linux CI lane and ADR-029 docs."""

from __future__ import annotations

import os
import re
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

import pytest
import yaml  # type: ignore[import-untyped]  # PyYAML is locked; its stubs are not.

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"
CREATE_CONDA = "Create isolated Linux Conda environment"
VERIFY_CONDA = "Verify the isolated Linux Conda environment"

EXPECTED_LINUX_DESELECTS = {
    "tests/test_screening_benchmark_protocol.py::"
    "test_primary_vina_metrics_reproduce_from_the_closed_campaign",
    "tests/test_screening_benchmark_sensitivity_plan.py::"
    "test_sensitivity_plan_is_deterministic_and_loss_preserving",
    "tests/test_screening_benchmark_sensitivity_plan.py::"
    "test_sensitivity_plan_rejects_post_freeze_factor_tampering",
    "tests/test_screening_benchmark_sensitivity_plan.py::"
    "test_recorded_sensitivity_plan_reproduces_exactly",
    "tests/test_screening_benchmark_sensitivity_plan.py::"
    "test_historical_verification_rejects_changed_source_bytes[microstate_schema_path]",
    "tests/test_screening_benchmark_sensitivity_plan.py::"
    "test_historical_verification_rejects_changed_source_bytes[microstate_service_path]",
}


def _workflow() -> dict[str, Any]:
    loaded = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded


def _linux_steps() -> list[dict[str, Any]]:
    job = _workflow()["jobs"]["verify-linux"]
    assert job["runs-on"] == "ubuntu-24.04"
    steps: list[dict[str, Any]] = job["steps"]
    return steps


def _index(steps: list[dict[str, Any]], name: str) -> int:
    return next(index for index, step in enumerate(steps) if step.get("name") == name)


def _uses_python(step: dict[str, Any]) -> bool:
    return step.get("shell") == "python" or "python" in str(step.get("run", "")).split()


def test_windows_and_linux_jobs_coexist_in_ci_workflow() -> None:
    jobs = _workflow()["jobs"]
    assert "verify" in jobs
    assert "verify-linux" in jobs
    assert jobs["verify"]["runs-on"] == "windows-latest"
    assert jobs["verify-linux"]["runs-on"] == "ubuntu-24.04"


def test_linux_ci_creates_and_verifies_locked_conda_environment_before_python_steps() -> None:
    steps = _linux_steps()
    create_idx = _index(steps, CREATE_CONDA)
    verify_idx = _index(steps, VERIFY_CONDA)

    assert verify_idx == create_idx + 1
    assert not [step["name"] for step in steps[:create_idx] if _uses_python(step)]
    assert not [
        step for step in steps if str(step.get("uses", "")).startswith("actions/setup-python")
    ]

    create_cmd = str(steps[create_idx]["run"])
    assert "--file environment/linux-64.conda.lock" in create_cmd
    assert 'CONDA_PREFIX=$conda_env" >> "$GITHUB_ENV"' in create_cmd
    assert 'PYTHONNOUSERSITE=1" >> "$GITHUB_ENV"' in create_cmd
    assert '$conda_env/bin" >> "$GITHUB_PATH"' in create_cmd
    assert steps[verify_idx]["shell"] == "python"


def test_linux_ci_locked_installs_diagnostics_and_gates_follow_strict_order() -> None:
    steps = _linux_steps()
    runs = [str(step.get("run", "")) for step in steps]
    assert not [run for run in runs if "backend[dev]" in run]

    order = [
        _index(steps, CREATE_CONDA),
        _index(steps, VERIFY_CONDA),
        _index(steps, "Reject private absolute paths"),
        _index(steps, "Verify public validation status"),
        _index(steps, "Verify platform status and validation index"),
        _index(steps, "Install hash-locked Linux Python dependencies"),
        _index(steps, "Install backend source without resolving dependencies"),
        _index(steps, "Check installed Linux dependency consistency"),
        _index(steps, "Verify Linux environment locks and active runtime"),
        _index(steps, "Verify isolated Linux packaging lock"),
        _index(steps, "Run cross-platform primary metrics diagnostic"),
        _index(steps, "Run Linux backend tests"),
        _index(steps, "Lint backend and Linux packaging scripts"),
        _index(steps, "Type-check backend"),
        _index(steps, "Run frontend tests"),
        _index(steps, "Type-check frontend"),
        _index(steps, "Build frontend"),
        _index(steps, "Check Rust formatting"),
        _index(steps, "Lint native Linux shell"),
        _index(steps, "Test native Linux shell"),
        _index(steps, "Build native Linux Tauri application"),
    ]
    assert order == sorted(order)

    pip_step = str(steps[_index(steps, "Install hash-locked Linux Python dependencies")]["run"])
    assert "--require-hashes" in pip_step
    assert "--only-binary=:all:" in pip_step
    assert "requirements/linux-py312.lock" in pip_step

    runtime_lock_step = str(
        steps[_index(steps, "Verify Linux environment locks and active runtime")]["run"]
    )
    assert runtime_lock_step == "python scripts/verify_linux_environment_lock.py --runtime"

    pkg_lock_step = str(steps[_index(steps, "Verify isolated Linux packaging lock")]["run"])
    assert "python -m venv" in pkg_lock_step
    assert "--require-hashes --only-binary=:all: -r requirements/linux-packaging.lock" in (
        pkg_lock_step
    )

    tauri_step = str(steps[_index(steps, "Build native Linux Tauri application")]["run"])
    assert tauri_step == "npm run tauri:build:linux"


def test_linux_ci_deselects_only_the_six_documented_frozen_bedroc_nodeids() -> None:
    steps = _linux_steps()
    diag_cmd = str(steps[_index(steps, "Run cross-platform primary metrics diagnostic")]["run"])
    assert (
        diag_cmd
        == "python -m pytest backend/tests/test_screening_benchmark_primary_metrics_diagnostic.py"
    )

    pytest_cmd = str(steps[_index(steps, "Run Linux backend tests")]["run"])
    tokens = shlex.split(pytest_cmd)
    assert tokens[:4] == ["python", "-m", "pytest", "backend"]
    assert not [tok for tok in tokens if tok.startswith("--ignore")]

    deselected: list[str] = []
    idx = 4
    while idx < len(tokens):
        assert tokens[idx] == "--deselect", f"Unexpected pytest flag in Linux CI: {tokens[idx]}"
        deselected.append(tokens[idx + 1])
        idx += 2

    assert set(deselected) == EXPECTED_LINUX_DESELECTS
    assert len(deselected) == 6

    collected = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-o",
            "addopts=",
            "--collect-only",
            "-q",
            str(ROOT / "backend" / "tests" / "test_screening_benchmark_protocol.py"),
            str(ROOT / "backend" / "tests" / "test_screening_benchmark_sensitivity_plan.py"),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
        timeout=60,
    )
    collected_nodeids = {
        line.strip()
        for line in collected.stdout.splitlines()
        if line.strip().startswith("tests/")
    }
    assert collected_nodeids >= EXPECTED_LINUX_DESELECTS


def test_linux_conda_isolation_snippet_enforces_conda_meta_and_prefix(tmp_path: Path) -> None:
    steps = _linux_steps()
    script = str(steps[_index(steps, VERIFY_CONDA)]["run"])

    venv = tmp_path / "synthetic-conda"
    subprocess.run(
        [sys.executable, "-m", "venv", "--without-pip", str(venv)],
        check=True,
        timeout=120,
    )
    venv_python = venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    base_env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    base_env["CONDA_PREFIX"] = str(venv)
    base_env["PYTHONNOUSERSITE"] = "1"

    # Without conda-meta/, even a matching venv prefix must be rejected.
    missing_meta = subprocess.run(
        [str(venv_python), "-c", script],
        capture_output=True,
        text=True,
        env=base_env,
        timeout=60,
        check=False,
    )
    assert missing_meta.returncode != 0
    assert "not the isolated Conda prefix" in missing_meta.stderr

    # With synthetic conda-meta/ and CPython 3.12.13, clean prefix succeeds; base python fails.
    (venv / "conda-meta").mkdir()
    if sys.version_info[:3] == (3, 12, 13):
        accepted = subprocess.run(
            [str(venv_python), "-c", script],
            capture_output=True,
            text=True,
            env=base_env,
            timeout=60,
            check=False,
        )
        assert accepted.returncode == 0, accepted.stderr
        assert "Isolated Conda interpreter" in accepted.stdout

    rejected_base = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        env=base_env,
        timeout=60,
        check=False,
    )
    assert rejected_base.returncode != 0
    assert "not the isolated Conda prefix" in rejected_base.stderr


@pytest.mark.parametrize(
    "document",
    [
        ROOT / "docs" / "DEVELOPMENT_LINUX.md",
        ROOT / "docs" / "architecture" / "ADR" / "ADR-029-linux-offline-distribution.md",
        ROOT / "docs" / "validation" / "LINUX_OFFLINE_PACKAGE_SMOKE.md",
        ROOT / "docs" / "validation" / "LINUX_NATIVE_WORKSTATION_PROTOCOL.md",
    ],
    ids=[
        "development-linux",
        "adr-029",
        "offline-package-smoke",
        "native-workstation-protocol",
    ],
)
def test_linux_packaging_docs_links_resolve_and_have_no_personal_paths(document: Path) -> None:
    content = document.read_text(encoding="utf-8")
    assert not re.search(r"(?<![A-Za-z0-9])[A-Z]:[\\/]", content)
    assert not re.search(r"/(?:home|Users)/[^/\s]+", content)

    for target in re.findall(r"\]\(([^)\s]+)\)", content):
        parsed = urlsplit(target)
        if parsed.scheme or parsed.netloc:
            continue
        resolved = (document.parent / unquote(parsed.path)).resolve() if parsed.path else document
        assert resolved.is_relative_to(ROOT), target
        assert resolved.exists(), f"{document.name} -> {target}"
