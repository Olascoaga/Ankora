"""Synthetic guards and contracts; these tests do not run scientific tools."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

from ankora_backend.schemas.binding_sites import BindingSiteRequest
from ankora_backend.schemas.docking import VinaDockingParameters
from ankora_backend.schemas.ligands import ExtractLigandRequest
from ankora_backend.schemas.receptors import ReceptorPreparationRequest
from ankora_backend.schemas.redocking import RedockingValidationRequest

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"


@pytest.fixture(scope="module")
def smoke() -> ModuleType:
    sys.path.insert(0, str(SCRIPTS))
    try:
        spec = importlib.util.spec_from_file_location(
            "validate_linux_crystal_redocking", SCRIPTS / "validate_linux_crystal_redocking.py"
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(str(SCRIPTS))


def test_fixed_requests_match_api_schemas(smoke: ModuleType) -> None:
    receptor = ReceptorPreparationRequest.model_validate(smoke.PLAN)
    assert receptor.selected_chains == ["A", "B"]
    assert not receptor.issue_decisions
    assert not receptor.protonation.authorized_terminal_heavy_atom_additions
    assert receptor.component_decisions[0].component_id == smoke.COMPONENT_ID
    locator = ExtractLigandRequest.model_validate({"locator": smoke.LOCATOR})
    assert locator.locator.sequence_number == 902
    box = BindingSiteRequest.model_validate(
        {
            "source": "co_crystallized_ligand",
            "ligand_origin": {
                "heterogen": {
                    "chain_id": "B",
                    "residue_name": "MK1",
                    "sequence_number": 902,
                    "insertion_code": "",
                },
                "padding_angstrom": 5,
            },
        }
    )
    assert box.ligand_origin is not None and box.ligand_origin.padding_angstrom == 5
    parameters = VinaDockingParameters.model_validate(smoke.PARAMETERS)
    assert parameters.cpu_threads == 2 and parameters.exhaustiveness == 8
    request = RedockingValidationRequest.model_validate(
        {
            "source_kind": "vina_job",
            "source_id": "synthetic",
            "reference_ligand_id": "synthetic",
            "threshold_angstrom": 2,
        }
    )
    assert request.threshold_angstrom == 2


def test_output_cannot_escape_or_overwrite(
    smoke: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(smoke, "ROOT", tmp_path)
    allowed = tmp_path / "logs" / "linux-crystal-redocking-smoke"
    for forbidden in (tmp_path, allowed, tmp_path / "user-project"):
        with pytest.raises(ValueError):
            smoke.run(tmp_path / "synthetic.cif", forbidden)
    existing = allowed / "existing"
    existing.mkdir(parents=True)
    with pytest.raises(FileExistsError):
        smoke.run(tmp_path / "synthetic.cif", existing)


@pytest.mark.skipif(sys.platform != "linux", reason="The recorded smoke protocol targets Linux")
def test_wrong_input_is_recorded_without_running_tools(
    smoke: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(smoke, "ROOT", tmp_path)
    source = tmp_path / "synthetic.cif"
    source.write_bytes(b"synthetic")
    output = tmp_path / "logs" / "linux-crystal-redocking-smoke" / "new"
    result = smoke.run(source, output)
    assert result["status"] == "failed"
    assert result["failure"]["stage"] == "initialization"
    assert result["failure"]["type"] == "ValueError"
    assert result["events"] == []
    assert (output / "evidence.json").is_file()
