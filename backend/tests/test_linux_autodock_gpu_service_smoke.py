"""Synthetic guards for the GPU service smoke; no scientific executable runs."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

from ankora_backend.schemas.autodock_gpu import AutoDockGpuDockingParameters

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"


@pytest.fixture(scope="module")
def smoke() -> ModuleType:
    sys.path.insert(0, str(SCRIPTS))
    try:
        spec = importlib.util.spec_from_file_location(
            "validate_linux_autodock_gpu_service",
            SCRIPTS / "validate_linux_autodock_gpu_service.py",
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(str(SCRIPTS))


def test_declared_parameters_validate_against_gpu_contract(smoke: ModuleType) -> None:
    params = AutoDockGpuDockingParameters.model_validate(smoke.PARAMETERS)
    assert params.runs == 2 and params.energy_evaluations == 5000
    assert not params.heuristics and not params.autostop
    assert params.seed == (20261029, 20261030, 20261031)


def test_output_is_restricted_to_isolated_root(smoke: ModuleType, tmp_path: Path) -> None:
    allowed = tmp_path / "logs" / "linux-autodock-gpu-service-smoke"
    assert smoke.require_output_path(allowed / "new", tmp_path) == (allowed / "new").resolve()
    for forbidden in (tmp_path, allowed, tmp_path / "project"):
        with pytest.raises(ValueError):
            smoke.require_output_path(forbidden, tmp_path)


def test_snapshot_records_exact_bytes_and_refuses_links(smoke: ModuleType, tmp_path: Path) -> None:
    (tmp_path / "synthetic").write_bytes(b"synthetic data\n")
    first = smoke.snapshot(tmp_path)
    assert list(first) == ["synthetic"]
    (tmp_path / "synthetic").write_bytes(b"synthetic data\r\n")
    assert smoke.snapshot(tmp_path) != first
    link = tmp_path / "link"
    try:
        link.symlink_to(tmp_path / "synthetic")
    except OSError:
        pytest.skip("Symbolic links require privileges on this host")
    with pytest.raises(ValueError, match="symbolic link"):
        smoke.snapshot(tmp_path)
