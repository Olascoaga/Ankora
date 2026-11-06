"""Synthetic library selection and manifest integrity tests; no docking is run."""

import json
from hashlib import sha256
from pathlib import Path

import pytest
from test_ligand_filtering import _library

from ankora_backend.domain.errors import AnkoraDomainError
from ankora_backend.persistence.ligand_store import LigandArtifactStore
from ankora_backend.schemas.ligands import ApplyLigandLibraryFilterRequest
from ankora_backend.services.gnina_screening_selection import verified_screening_selection
from ankora_backend.services.ligand_filtering import apply_library_filters


@pytest.fixture
def selection(tmp_path: Path):
    store = LigandArtifactStore(tmp_path)
    library = _library(store)
    record = apply_library_filters(
        library_id=library.artifact.library_id,
        request=ApplyLigandLibraryFilterRequest(acknowledge_selection=True),
        store=store,
        worker_limit=1,
    )
    assert len(record.selected_ligand_ids) == 2
    return store, record


def _verify(store, record):
    return verified_screening_selection(
        store=store,
        library_id=record.artifact.library_id,
        filter_run_id=record.artifact.filter_run_id,
    )


def test_preserves_exact_selected_order_and_chemical_states(selection):
    store, record = selection
    loaded = _verify(store, record)
    assert loaded.selected_ligand_ids == record.selected_ligand_ids
    assert [item.state_id for item in loaded.evaluations] == [
        item.state_id for item in record.evaluations
    ]


def test_rejects_altered_manifest(selection):
    store, record = selection
    path = store.filter_run_content_path(record.artifact.library_id, record.artifact.filter_run_id)
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(AnkoraDomainError) as error:
        _verify(store, record)
    assert error.value.code == "GNINA_SELECTION_INTEGRITY_FAILED"


@pytest.mark.parametrize("mutation", ["selected_order", "chemical_state", "library_id"])
def test_rejects_record_that_disagrees_with_hashed_manifest(selection, mutation):
    store, record = selection
    path = store.filter_run_content_path(record.artifact.library_id, record.artifact.filter_run_id)
    record_path = path.parent / "record.json"
    data = json.loads(record_path.read_text(encoding="utf-8"))
    if mutation == "selected_order":
        data["selected_ligand_ids"].reverse()
    elif mutation == "chemical_state":
        data["evaluations"][0]["state_id"] = "a-different-state"
    else:
        data["artifact"]["library_id"] = "another-library"
    record_path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(AnkoraDomainError) as error:
        _verify(store, record)
    assert error.value.code == "GNINA_SELECTION_INTEGRITY_FAILED"


def test_rejects_selection_from_another_project(selection, tmp_path: Path):
    _store, record = selection
    other = LigandArtifactStore(tmp_path, project_id="other")
    with pytest.raises(AnkoraDomainError):
        _verify(other, record)


@pytest.mark.parametrize("mutation", ["duplicate", "empty", "incorrect_count"])
def test_rejects_internally_invalid_selection_even_when_manifest_hash_matches(selection, mutation):
    store, record = selection
    path = store.filter_run_content_path(record.artifact.library_id, record.artifact.filter_run_id)
    record_path = path.parent / "record.json"
    metadata = json.loads(record_path.read_text(encoding="utf-8"))
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if mutation == "duplicate":
        for data in (metadata, manifest):
            data["selected_ligand_ids"].append(data["selected_ligand_ids"][0])
            data["evaluations"].append(data["evaluations"][0])
            data["summary"]["eligible_count"] += 1
    elif mutation == "empty":
        for data in (metadata, manifest):
            data["selected_ligand_ids"] = []
            for evaluation in data["evaluations"]:
                evaluation["disposition"] = "excluded"
            data["summary"]["eligible_count"] = 0
    else:
        for data in (metadata, manifest):
            data["summary"]["eligible_count"] += 1
    content = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode() + b"\n"
    metadata["artifact"]["sha256"] = sha256(content).hexdigest()
    metadata["artifact"]["size_bytes"] = len(content)
    path.write_bytes(content)
    record_path.write_text(json.dumps(metadata), encoding="utf-8")
    with pytest.raises(AnkoraDomainError) as error:
        _verify(store, record)
    assert error.value.code == (
        "GNINA_SELECTION_EMPTY" if mutation == "empty" else "GNINA_SELECTION_INTEGRITY_FAILED"
    )
