"""Synthetic guard and request-contract tests; no scientific executable runs."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

from ankora_backend.schemas.binding_sites import BindingSiteRequest
from ankora_backend.schemas.docking import VinaDockingParameters
from ankora_backend.schemas.receptors import ReceptorPreparationRequest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "validate_linux_api_preparation.py"


@pytest.fixture(scope="module")
def smoke() -> ModuleType:
    spec = importlib.util.spec_from_file_location("validate_linux_api_preparation", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_output_is_restricted_to_isolated_smoke_root(smoke: ModuleType, tmp_path: Path) -> None:
    permitted = tmp_path / "logs" / "linux-api-preparation-smoke" / "new"
    assert smoke.require_output_path(permitted, tmp_path) == permitted.resolve()
    for forbidden in (tmp_path, tmp_path / "user-project", permitted.parent):
        with pytest.raises(ValueError):
            smoke.require_output_path(forbidden, tmp_path)


def test_input_identity_checks_exact_bytes(smoke: ModuleType, tmp_path: Path) -> None:
    sample = tmp_path / "synthetic"
    sample.write_bytes(b"synthetic\n")
    expected = smoke.digest_bytes(b"synthetic\n")
    assert smoke.require_input(sample, expected) == b"synthetic\n"
    sample.write_bytes(b"synthetic\r\n")
    with pytest.raises(ValueError):
        smoke.require_input(sample, expected)


def test_predeclared_requests_match_real_api_schemas(smoke: ModuleType) -> None:
    receptor = ReceptorPreparationRequest.model_validate(smoke.RECEPTOR_PLAN)
    assert receptor.selected_chains == ["A"]
    assert receptor.generate_pdbqt and receptor.protonation.enabled
    assert receptor.inspection_method == "templates_v1"
    assert not receptor.issue_decisions
    assert not receptor.protonation.authorized_terminal_heavy_atom_additions
    box = BindingSiteRequest.model_validate({"source": "manual", "manual_box": smoke.BOX})
    assert box.manual_box is not None and box.manual_box.size_x == 20
    parameters = VinaDockingParameters.model_validate(smoke.PARAMETERS)
    assert parameters.cpu_threads == 2 and parameters.exhaustiveness == 2
