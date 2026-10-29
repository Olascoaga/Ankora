"""Synthetic tests for the isolated service smoke; no Vina or molecule is run."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "validate_linux_vina_service.py"


@pytest.fixture(scope="module")
def smoke() -> ModuleType:
    sys.path.insert(0, str(SCRIPT.parent))
    spec = importlib.util.spec_from_file_location("validate_linux_vina_service", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_existing_output_is_not_touched(smoke: ModuleType, tmp_path: Path) -> None:
    output = tmp_path / "existing"
    output.mkdir()
    marker = output / "marker"
    marker.write_bytes(b"earlier evidence")
    with pytest.raises(FileExistsError):
        smoke.run(tmp_path / "missing", tmp_path / "missing", tmp_path / "missing", output)
    assert marker.read_bytes() == b"earlier evidence"
    assert sorted(p.name for p in output.iterdir()) == ["marker"]


def test_unmatched_inputs_fail_before_engine_and_preserve_evidence(
    smoke: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "synthetic"
    source.write_bytes(b"synthetic invalid fixture")
    monkeypatch.setattr(smoke, "probe_vina", lambda: pytest.fail("engine must not be probed"))
    output = tmp_path / "new"
    result = smoke.run(source, source, source, output)
    assert result["status"] == "failed"
    assert "failure" in result
    assert json.loads((output / "evidence.json").read_text()) == result
    assert source.read_bytes() == b"synthetic invalid fixture"


def test_seeded_records_explicitly_identify_their_fixture_origin(
    smoke: ModuleType, tmp_path: Path
) -> None:
    receptor, ligand = b"synthetic receptor", b"synthetic ligand"
    receptors, ligands, sites, _jobs, request = smoke.seed_fixture_stores(
        tmp_path, receptor, ligand
    )
    record = receptors.load_record(request.receptor_id)
    assert record.source_artifact_id == "development-fixture-no-import-record"
    assert record.provenance[0].event_type == "development_fixture_seed"
    prepared = ligands.load_pdbqt_record(request.ligand_id, request.ligand_preparation_id)
    assert prepared.tool.name == "development fixture seeded for service smoke"
    assert sites.load_record(request.binding_site_id).box == smoke.adapter_smoke.BOX
