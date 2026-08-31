from pathlib import Path

import pytest

from ankora_backend.adapters.tools.discovery import DiscoveredTool
from ankora_backend.adapters.tools.ligand_preparation import execute_meeko_ligand
from ankora_backend.domain.errors import AnkoraDomainError
from ankora_backend.execution.subprocess_runner import ToolExecution
from ankora_backend.persistence.ligand_store import LigandArtifactStore
from ankora_backend.schemas.ligands import (
    GenerateLigandConformerRequest,
    LigandChargeModel,
    PrepareLigandPdbqtRequest,
)
from ankora_backend.services.ligand_import import import_local_ligand
from ankora_backend.services.ligand_minimization import generate_ligand_conformer
from ankora_backend.services.ligand_preparation import prepare_ligand_pdbqt


def _converged_ligand(tmp_path: Path) -> tuple[LigandArtifactStore, str, str]:
    store = LigandArtifactStore(tmp_path)
    ligand = import_local_ligand(
        content=b"CCO synthetic_ethanol\n",
        filename="synthetic_ethanol.smi",
        store=store,
    )
    conformer = generate_ligand_conformer(
        ligand_id=ligand.artifact.ligand_id,
        request=GenerateLigandConformerRequest(
            acknowledge_current_chemical_state=True,
            random_seed=73191,
        ),
        store=store,
    )
    return store, ligand.artifact.ligand_id, conformer.artifact.conformer_id


def test_conformer_filename_from_malicious_molecule_name_stays_inside_its_directory(
    tmp_path: Path,
) -> None:
    """A SMILES/SDF molecule name is attacker-controlled content (it's
    whatever the imported file's own `_Name`/trailing-text field says), and
    it flows unsanitized into the conformer's filename. Confirms it can't
    escape the create-only UUID directory `create_conformer` writes into."""
    store = LigandArtifactStore(tmp_path)
    ligand = import_local_ligand(
        content=b"CCO ../../../escaped_via_name\n",
        filename="synthetic_traversal.smi",
        store=store,
    )
    conformer = generate_ligand_conformer(
        ligand_id=ligand.artifact.ligand_id,
        request=GenerateLigandConformerRequest(
            acknowledge_current_chemical_state=True,
            random_seed=73191,
        ),
        store=store,
    )

    content_path = store.conformer_content_path(
        ligand.artifact.ligand_id, conformer.artifact.conformer_id
    )
    expected_dir = store._conformer_dir(  # noqa: SLF001 - verifying the store's own boundary
        ligand.artifact.ligand_id, conformer.artifact.conformer_id
    )
    assert content_path.parent == expected_dir
    assert content_path.is_file()
    assert not (tmp_path / "escaped_via_name").exists()


def test_meeko_adapter_uses_explicit_input_output_and_charge_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    executable = str(tmp_path / "mk_prepare_ligand.exe")
    monkeypatch.setattr(
        "ankora_backend.adapters.tools.ligand_preparation.discover_tool",
        lambda *_args: DiscoveredTool(True, executable),
    )
    monkeypatch.setattr(
        "ankora_backend.adapters.tools.ligand_preparation.package_version",
        lambda *_args: "0.7.1",
    )

    def fake_run_tool(
        *, executable: str, arguments: list[str], **_kwargs: object
    ) -> ToolExecution:
        return ToolExecution(
            command=[executable, *arguments], exit_code=0, stdout="", stderr=""
        )

    monkeypatch.setattr(
        "ankora_backend.adapters.tools.ligand_preparation.run_tool", fake_run_tool
    )
    execution, version = execute_meeko_ligand(
        input_sdf_path=tmp_path / "converged.sdf",
        output_pdbqt_path=tmp_path / "prepared.pdbqt",
        charge_model=LigandChargeModel.GASTEIGER,
    )

    assert execution.command == [
        executable,
        "-i",
        str(tmp_path / "converged.sdf"),
        "-o",
        str(tmp_path / "prepared.pdbqt"),
        "--charge_model",
        "gasteiger",
    ]
    assert version == "0.7.1"


def test_meeko_pdbqt_is_create_only_and_preserves_raw_execution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, ligand_id, conformer_id = _converged_ligand(tmp_path)

    def fake_execute(**kwargs: object) -> tuple[ToolExecution, str]:
        output_path = kwargs["output_pdbqt_path"]
        assert isinstance(output_path, Path)
        output_path.write_text("ROOT\nENDROOT\nTORSDOF 0\n", encoding="utf-8")
        return (
            ToolExecution(
                command=["mk_prepare_ligand", "-i", "input.sdf", "-o", "output.pdbqt"],
                exit_code=0,
                stdout="prepared one molecule\n",
                stderr="",
            ),
            "0.7.1",
        )

    monkeypatch.setattr(
        "ankora_backend.services.ligand_preparation.execute_meeko_ligand",
        fake_execute,
    )
    record = prepare_ligand_pdbqt(
        ligand_id=ligand_id,
        conformer_id=conformer_id,
        request=PrepareLigandPdbqtRequest(charge_model="gasteiger"),
        store=store,
    )

    assert record.artifact.size_bytes > 0
    assert record.charge_model.value == "gasteiger"
    assert record.tool.version == "0.7.1"
    assert record.stdout == "prepared one molecule\n"
    assert store.pdbqt_content_path(ligand_id, record.artifact.preparation_id).read_text(
        encoding="utf-8"
    ).startswith("ROOT")


def test_meeko_failure_is_preserved_with_raw_logs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, ligand_id, conformer_id = _converged_ligand(tmp_path)

    def fake_execute(**_kwargs: object) -> tuple[ToolExecution, str]:
        return (
            ToolExecution(
                command=["mk_prepare_ligand", "-i", "input.sdf"],
                exit_code=1,
                stdout="read molecule\n",
                stderr="unsupported atom type\n",
            ),
            "0.7.1",
        )

    monkeypatch.setattr(
        "ankora_backend.services.ligand_preparation.execute_meeko_ligand",
        fake_execute,
    )
    with pytest.raises(AnkoraDomainError) as captured:
        prepare_ligand_pdbqt(
            ligand_id=ligand_id,
            conformer_id=conformer_id,
            request=PrepareLigandPdbqtRequest(),
            store=store,
        )

    assert captured.value.code == "MEEKO_LIGAND_PREPARATION_FAILED"
    preparation_id = str(captured.value.details["preparation_id"])
    failure_directory = store._preparation_dir(ligand_id, preparation_id)
    assert (failure_directory / "stdout.log").read_text() == "read molecule\n"
    assert (failure_directory / "stderr.log").read_text() == "unsupported atom type\n"
