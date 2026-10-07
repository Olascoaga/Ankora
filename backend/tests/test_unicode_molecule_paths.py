"""Synthetic molecule fixtures; no docking score or reference result invented."""

import hashlib
from pathlib import Path

import pytest
from rdkit import Chem

from ankora_backend.adapters.chemistry.molecule_files import sdf_supplier
from ankora_backend.adapters.chemistry.redocking_rmsd import load_reference
from ankora_backend.adapters.tools.discovery import DiscoveredTool
from ankora_backend.adapters.tools.ligand_preparation import execute_meeko_ligand
from ankora_backend.execution.subprocess_runner import ToolExecution
from ankora_backend.persistence.ligand_store import LigandArtifactStore
from ankora_backend.schemas.ligands import GenerateLigandConformerRequest, LigandChargeModel
from ankora_backend.services.ligand_import import import_local_ligand
from ankora_backend.services.ligand_minimization import generate_ligand_conformer


def test_unicode_sdf_preserves_parsing_chemistry_and_original_bytes(tmp_path: Path) -> None:
    molecule = Chem.AddHs(Chem.MolFromSmiles("C[C@H](O)C(=O)[O-]"))
    document = (Chem.MolToMolBlock(molecule) + "\n$$$$\n").encode()
    ascii_path = tmp_path / "reference.sdf"
    unicode_path = tmp_path / "molécula 測試.sdf"
    ascii_path.write_bytes(document)
    unicode_path.write_bytes(document)
    expected = Chem.SDMolSupplier(str(ascii_path), removeHs=False)[0]
    actual = sdf_supplier(unicode_path)[0]
    assert Chem.MolToMolBlock(actual) == Chem.MolToMolBlock(expected)
    assert Chem.MolToSmiles(actual) == Chem.MolToSmiles(expected)
    assert unicode_path.read_bytes() == document
    assert Chem.MolToSmiles(load_reference(unicode_path)) == Chem.MolToSmiles(
        Chem.RemoveHs(expected)
    )


def test_unicode_project_can_generate_and_minimize_ligand(tmp_path: Path) -> None:
    store = LigandArtifactStore(tmp_path / "proyecto á 測試")
    ligand = import_local_ligand(
        content=b"CCO synthetic_ethanol\n", filename="synthetic.smi", store=store
    )
    result = generate_ligand_conformer(
        ligand_id=ligand.artifact.ligand_id,
        request=GenerateLigandConformerRequest(
            acknowledge_current_chemical_state=True, random_seed=73191
        ),
        store=store,
    )
    assert result.minimization.converged
    assert result.inspection.formula == "C2H6O"


def test_meeko_receives_exact_input_with_ascii_relative_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    job = tmp_path / "usuario á 測試"
    job.mkdir()
    original = job / "molécula.sdf"
    document = b"synthetic path fixture only; mock tool does not parse chemistry\n"
    original.write_bytes(document)
    monkeypatch.setattr(
        "ankora_backend.adapters.tools.ligand_preparation.discover_tool",
        lambda *_a: DiscoveredTool(True, "meeko.exe"),
    )

    def run(*, executable, arguments, cwd, **_kwargs):
        relative = arguments[arguments.index("-i") + 1]
        assert relative.isascii() and not Path(relative).is_absolute()
        assert (cwd / relative).read_bytes() == document
        return ToolExecution(command=[executable, *arguments], exit_code=0, stdout="", stderr="")

    monkeypatch.setattr("ankora_backend.adapters.tools.ligand_preparation.run_tool", run)
    execute_meeko_ligand(
        input_sdf_path=original,
        output_pdbqt_path=job / "ligand.pdbqt",
        charge_model=LigandChargeModel.GASTEIGER,
    )
    assert hashlib.sha256(original.read_bytes()).digest() == hashlib.sha256(document).digest()
