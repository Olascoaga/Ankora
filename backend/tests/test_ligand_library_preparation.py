"""The aggregate library preparation status must survive beyond a single request:
each conformer/PDBQT call for a library ligand should durably update it, and a
ligand imported outside a library must never create one."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ankora_backend.api.app import create_app
from ankora_backend.domain.errors import AnkoraDomainError
from ankora_backend.execution.subprocess_runner import ToolExecution
from ankora_backend.persistence.ligand_store import LigandArtifactStore
from ankora_backend.schemas.ligand_library_preparation import LigandPreparationEntry
from ankora_backend.schemas.ligands import (
    GenerateLigandConformerRequest,
    LigandLibraryRecord,
    PrepareLigandPdbqtRequest,
)
from ankora_backend.services.ligand_import import import_local_ligand, import_local_ligand_library
from ankora_backend.services.ligand_minimization import generate_ligand_conformer
from ankora_backend.services.ligand_preparation import prepare_ligand_pdbqt

SYNTHETIC_LIBRARY = b"""CCO ethanol
CCO.[Na+] unresolved_salt
"""


def _library(store: LigandArtifactStore) -> LigandLibraryRecord:
    return import_local_ligand_library(
        content=SYNTHETIC_LIBRARY,
        filename="synthetic_preparation_library.smi",
        store=store,
    )


def _ligand_id(library: LigandLibraryRecord, name: str) -> str:
    for entry in library.entries:
        if entry.ligand and entry.ligand.inspection.name == name:
            return entry.ligand.artifact.ligand_id
    raise AssertionError(f"{name} was not imported")


def test_successful_conformer_records_minimized_status(tmp_path: Path) -> None:
    store = LigandArtifactStore(tmp_path)
    library = _library(store)
    ligand_id = _ligand_id(library, "ethanol")

    conformer = generate_ligand_conformer(
        ligand_id=ligand_id,
        request=GenerateLigandConformerRequest(
            acknowledge_current_chemical_state=True, random_seed=73191
        ),
        store=store,
    )

    status = store.load_preparation_status(library.artifact.library_id)
    entry = status.entries[ligand_id]
    assert entry.status.value == "minimized"
    assert entry.conformer_id == conformer.artifact.conformer_id
    assert entry.initial_energy_kcal_mol == pytest.approx(
        conformer.minimization.initial_energy_kcal_mol
    )
    assert entry.final_energy_kcal_mol == pytest.approx(
        conformer.minimization.final_energy_kcal_mol
    )
    assert entry.error_message is None
    historical_payload = entry.model_dump()
    historical_payload.pop("initial_energy_kcal_mol")
    assert (
        LigandPreparationEntry.model_validate(historical_payload).initial_energy_kcal_mol
        is None
    )


def test_multicomponent_ligand_records_needs_decision_not_failed(
    tmp_path: Path,
) -> None:
    store = LigandArtifactStore(tmp_path)
    library = _library(store)
    ligand_id = _ligand_id(library, "unresolved_salt")

    with pytest.raises(AnkoraDomainError) as captured:
        generate_ligand_conformer(
            ligand_id=ligand_id,
            request=GenerateLigandConformerRequest(
                acknowledge_current_chemical_state=True, random_seed=73191
            ),
            store=store,
        )
    assert captured.value.code == "LIGAND_MULTICOMPONENT_REQUIRES_DECISION"

    status = store.load_preparation_status(library.artifact.library_id)
    entry = status.entries[ligand_id]
    assert entry.status.value == "needs_decision"
    assert entry.conformer_id is None
    assert entry.error_message == captured.value.message


def test_prepared_pdbqt_updates_status_to_prepared(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = LigandArtifactStore(tmp_path)
    library = _library(store)
    ligand_id = _ligand_id(library, "ethanol")
    conformer = generate_ligand_conformer(
        ligand_id=ligand_id,
        request=GenerateLigandConformerRequest(
            acknowledge_current_chemical_state=True, random_seed=73191
        ),
        store=store,
    )

    def fake_execute(**kwargs: object) -> tuple[ToolExecution, str]:
        output_path = kwargs["output_pdbqt_path"]
        assert isinstance(output_path, Path)
        output_path.write_text("ROOT\nENDROOT\nTORSDOF 0\n", encoding="utf-8")
        return (
            ToolExecution(command=["mk_prepare_ligand"], exit_code=0, stdout="", stderr=""),
            "0.7.1",
        )

    monkeypatch.setattr(
        "ankora_backend.services.ligand_preparation.execute_meeko_ligand", fake_execute
    )
    pdbqt = prepare_ligand_pdbqt(
        ligand_id=ligand_id,
        conformer_id=conformer.artifact.conformer_id,
        request=PrepareLigandPdbqtRequest(charge_model="gasteiger"),
        store=store,
    )

    status = store.load_preparation_status(library.artifact.library_id)
    entry = status.entries[ligand_id]
    assert entry.status.value == "prepared"
    assert entry.conformer_id == conformer.artifact.conformer_id
    assert entry.pdbqt_preparation_id == pdbqt.artifact.preparation_id
    assert entry.initial_energy_kcal_mol == pytest.approx(
        conformer.minimization.initial_energy_kcal_mol
    )
    assert entry.final_energy_kcal_mol == pytest.approx(
        conformer.minimization.final_energy_kcal_mol
    )


def test_failed_pdbqt_records_failed_status_and_keeps_raising(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = LigandArtifactStore(tmp_path)
    library = _library(store)
    ligand_id = _ligand_id(library, "ethanol")
    conformer = generate_ligand_conformer(
        ligand_id=ligand_id,
        request=GenerateLigandConformerRequest(
            acknowledge_current_chemical_state=True, random_seed=73191
        ),
        store=store,
    )

    def fake_execute(**_kwargs: object) -> tuple[ToolExecution, str]:
        return (
            ToolExecution(command=["mk_prepare_ligand"], exit_code=1, stdout="", stderr="boom"),
            "0.7.1",
        )

    monkeypatch.setattr(
        "ankora_backend.services.ligand_preparation.execute_meeko_ligand", fake_execute
    )
    with pytest.raises(AnkoraDomainError):
        prepare_ligand_pdbqt(
            ligand_id=ligand_id,
            conformer_id=conformer.artifact.conformer_id,
            request=PrepareLigandPdbqtRequest(),
            store=store,
        )

    status = store.load_preparation_status(library.artifact.library_id)
    entry = status.entries[ligand_id]
    assert entry.status.value == "failed"
    assert entry.error_message is not None


def test_single_ligand_import_never_creates_a_library_status(tmp_path: Path) -> None:
    store = LigandArtifactStore(tmp_path)
    ligand = import_local_ligand(
        content=b"CCO synthetic_ethanol\n", filename="synthetic_ethanol.smi", store=store
    )

    generate_ligand_conformer(
        ligand_id=ligand.artifact.ligand_id,
        request=GenerateLigandConformerRequest(
            acknowledge_current_chemical_state=True, random_seed=73191
        ),
        store=store,
    )

    assert ligand.artifact.library_id is None


def test_preparation_endpoint_returns_the_aggregate_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ANKORA_DATA_DIR", str(tmp_path))
    store = LigandArtifactStore.from_environment()
    library = _library(store)
    ligand_id = _ligand_id(library, "ethanol")
    generate_ligand_conformer(
        ligand_id=ligand_id,
        request=GenerateLigandConformerRequest(
            acknowledge_current_chemical_state=True, random_seed=73191
        ),
        store=store,
    )

    client = TestClient(create_app())
    response = client.get(
        f"/api/v1/ligand-libraries/{library.artifact.library_id}/preparation"
    )

    assert response.status_code == 200
    body = response.json()
    assert body["entries"][ligand_id]["status"] == "minimized"


def test_preparation_endpoint_404s_for_unknown_library(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ANKORA_DATA_DIR", str(tmp_path))
    LigandArtifactStore.from_environment()

    client = TestClient(create_app())
    response = client.get(
        "/api/v1/ligand-libraries/00000000-0000-0000-0000-000000000000/preparation"
    )

    assert response.status_code == 404
