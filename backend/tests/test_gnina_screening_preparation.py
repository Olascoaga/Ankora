"""Synthetic ligand preparation checks. Meeko execution is explicitly faked."""

import json
from pathlib import Path

import pytest
from test_ligand_library_preparation import _library, _ligand_id

from ankora_backend.domain.errors import AnkoraDomainError
from ankora_backend.execution.subprocess_runner import ToolExecution
from ankora_backend.persistence.ligand_store import LigandArtifactStore
from ankora_backend.schemas.ligand_library_preparation import LigandPreparationStatus
from ankora_backend.schemas.ligands import GenerateLigandConformerRequest, PrepareLigandPdbqtRequest
from ankora_backend.services.gnina_screening_preparation import verified_screening_preparation
from ankora_backend.services.ligand_minimization import generate_ligand_conformer
from ankora_backend.services.ligand_preparation import prepare_ligand_pdbqt


@pytest.fixture
def prepared(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
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

    def fake_meeko(**kwargs):
        kwargs["output_pdbqt_path"].write_bytes(b"ROOT\nENDROOT\nTORSDOF 0\n")
        return ToolExecution(
            command=["synthetic-meeko"], exit_code=0, stdout="", stderr=""
        ), "0.7.1"

    monkeypatch.setattr(
        "ankora_backend.services.ligand_preparation.execute_meeko_ligand", fake_meeko
    )
    pdbqt = prepare_ligand_pdbqt(
        ligand_id=ligand_id,
        conformer_id=conformer.artifact.conformer_id,
        request=PrepareLigandPdbqtRequest(),
        store=store,
    )
    entry = store.load_preparation_status(library.artifact.library_id).entries[ligand_id]
    assert conformer.artifact.chemical_state_id is not None
    return store, ligand_id, entry, pdbqt, conformer


def _verify(prepared, **overrides):
    store, ligand_id, entry, _pdbqt, conformer = prepared
    args = dict(
        store=store,
        ligand_id=ligand_id,
        preparation=entry,
        expected_state_id=conformer.artifact.chemical_state_id,
    )
    return verified_screening_preparation(**(args | overrides))


def test_verified_derivatives_match_the_selected_state(prepared):
    _store, _ligand_id_value, _entry, pdbqt, conformer = prepared
    assert _verify(prepared) == (pdbqt, conformer)


def test_rejects_a_different_selected_chemical_state(prepared):
    with pytest.raises(AnkoraDomainError) as error:
        _verify(prepared, expected_state_id="another-state")
    assert error.value.code == "GNINA_SCREENING_STATE_MISMATCH"


def test_rejects_unprepared_entry(prepared):
    entry = prepared[2].model_copy(update={"status": LigandPreparationStatus.FAILED})
    with pytest.raises(AnkoraDomainError) as error:
        _verify(prepared, preparation=entry)
    assert error.value.code == "GNINA_SCREENING_LIGAND_NOT_PREPARED"


@pytest.mark.parametrize("artifact", ["pdbqt", "conformer"])
def test_rejects_changed_prepared_bytes(prepared, artifact):
    store, ligand_id, entry, _pdbqt, _conformer = prepared
    path = (
        store.pdbqt_content_path(ligand_id, entry.pdbqt_preparation_id)
        if artifact == "pdbqt"
        else store.conformer_content_path(ligand_id, entry.conformer_id)
    )
    path.write_bytes(b"changed synthetic content")
    with pytest.raises(AnkoraDomainError) as error:
        _verify(prepared)
    assert error.value.code == "GNINA_SCREENING_PREPARATION_INTEGRITY_FAILED"


def test_rejects_mismatched_conformer_link(prepared):
    entry = prepared[2].model_copy(update={"conformer_id": "another-conformer"})
    with pytest.raises(AnkoraDomainError) as error:
        _verify(prepared, preparation=entry)
    assert error.value.code == "GNINA_SCREENING_PREPARATION_MISMATCH"


def test_rejects_conformer_record_from_another_chemical_state(prepared):
    store, ligand_id, entry, _pdbqt, _conformer = prepared
    content = store.conformer_content_path(ligand_id, entry.conformer_id)
    record_path = content.parent / "record.json"
    record = json.loads(record_path.read_text(encoding="utf-8"))
    record["artifact"]["chemical_state_id"] = "different-state"
    record_path.write_text(json.dumps(record), encoding="utf-8")
    with pytest.raises(AnkoraDomainError) as error:
        _verify(prepared)
    assert error.value.code == "GNINA_SCREENING_STATE_MISMATCH"
