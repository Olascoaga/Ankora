"""Dimorphite-DL never picks a protonation state silently: a single result means
the pH range is unambiguous, and more than one means the scientist must choose."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from ankora_backend.api.app import create_app
from ankora_backend.domain.errors import AnkoraDomainError
from ankora_backend.persistence.ligand_store import LigandArtifactStore
from ankora_backend.schemas.ligands import (
    GenerateLigandConformerRequest,
    ResolveLigandProtonationRequest,
)
from ankora_backend.services.ligand_import import import_local_ligand
from ankora_backend.services.ligand_minimization import generate_ligand_conformer
from ankora_backend.services.ligand_protonation import (
    protonation_options,
    resolve_ligand_protonation,
)

PH_MIN = 6.4
PH_MAX = 8.4
PRECISION = 1.0


def _import(store: LigandArtifactStore, smiles: str, name: str) -> str:
    ligand = import_local_ligand(
        content=f"{smiles} {name}\n".encode(), filename=f"{name}.smi", store=store
    )
    assert ligand.state is not None
    return ligand.artifact.ligand_id


def test_unambiguous_molecule_returns_a_single_candidate(tmp_path: Path) -> None:
    store = LigandArtifactStore(tmp_path)
    ligand_id = _import(store, "CCO", "ethanol")
    ligand = store.load_record(ligand_id)
    assert ligand.state is not None

    options = protonation_options(
        ligand_id=ligand_id,
        parent_state_id=ligand.state.state_id,
        ph_min=PH_MIN,
        ph_max=PH_MAX,
        precision=PRECISION,
        store=store,
    )

    assert len(options.candidates) == 1
    assert options.candidates[0].formal_charge == 0
    assert options.selection_required is False


def test_ambiguous_molecule_requires_explicit_selection(tmp_path: Path) -> None:
    store = LigandArtifactStore(tmp_path)
    ligand_id = _import(store, "CCN(CC)CC", "triethylamine")
    ligand = store.load_record(ligand_id)
    assert ligand.state is not None

    options = protonation_options(
        ligand_id=ligand_id,
        parent_state_id=ligand.state.state_id,
        ph_min=PH_MIN,
        ph_max=PH_MAX,
        precision=PRECISION,
        store=store,
    )

    assert options.selection_required is True
    assert {candidate.formal_charge for candidate in options.candidates} == {0, 1}


def test_unparseable_dimorphite_variants_are_skipped_not_crashed(tmp_path: Path) -> None:
    store = LigandArtifactStore(tmp_path)
    ligand_id = _import(store, "c1cnc[nH]1", "imidazole")
    ligand = store.load_record(ligand_id)
    assert ligand.state is not None

    options = protonation_options(
        ligand_id=ligand_id,
        parent_state_id=ligand.state.state_id,
        ph_min=PH_MIN,
        ph_max=PH_MAX,
        precision=PRECISION,
        store=store,
    )

    assert len(options.candidates) >= 2
    assert all(candidate.canonical_smiles for candidate in options.candidates)


def test_resolve_creates_a_reproducible_immutable_protonated_state(
    tmp_path: Path,
) -> None:
    store = LigandArtifactStore(tmp_path)
    ligand_id = _import(store, "CCN(CC)CC", "triethylamine")
    ligand = store.load_record(ligand_id)
    assert ligand.state is not None
    options = protonation_options(
        ligand_id=ligand_id,
        parent_state_id=ligand.state.state_id,
        ph_min=PH_MIN,
        ph_max=PH_MAX,
        precision=PRECISION,
        store=store,
    )
    charged_index = next(
        candidate.index for candidate in options.candidates if candidate.formal_charge == 1
    )
    request = ResolveLigandProtonationRequest(
        parent_state_id=ligand.state.state_id,
        ph_min=PH_MIN,
        ph_max=PH_MAX,
        precision=PRECISION,
        candidate_index=charged_index,
    )

    first = resolve_ligand_protonation(ligand_id=ligand_id, request=request, store=store)

    assert first.inspection.formal_charge == 1
    assert first.selection.candidate_count == len(options.candidates)
    assert first.parent_state_id == ligand.state.state_id
    assert first.artifact.state_id != ligand.state.state_id

    second = resolve_ligand_protonation(ligand_id=ligand_id, request=request, store=store)
    assert second.artifact.state_id != first.artifact.state_id
    assert second.artifact.sha256 == first.artifact.sha256


def test_invalid_candidate_index_is_rejected(tmp_path: Path) -> None:
    store = LigandArtifactStore(tmp_path)
    ligand_id = _import(store, "CCO", "ethanol")
    ligand = store.load_record(ligand_id)
    assert ligand.state is not None

    with pytest.raises(AnkoraDomainError) as captured:
        resolve_ligand_protonation(
            ligand_id=ligand_id,
            request=ResolveLigandProtonationRequest(
                parent_state_id=ligand.state.state_id,
                ph_min=PH_MIN,
                ph_max=PH_MAX,
                precision=PRECISION,
                candidate_index=99,
            ),
            store=store,
        )

    assert captured.value.code == "LIGAND_PROTONATION_SELECTION_INVALID"


def test_a_protonated_state_feeds_conformer_generation(tmp_path: Path) -> None:
    """Regression test: conformer generation reads a non-primary state through
    `state_content_path`, which used to assume every such state was a
    `LigandChemicalStateRecord`. A protonation-derived state must work too."""
    store = LigandArtifactStore(tmp_path)
    ligand_id = _import(store, "CCN(CC)CC", "triethylamine")
    ligand = store.load_record(ligand_id)
    assert ligand.state is not None
    options = protonation_options(
        ligand_id=ligand_id,
        parent_state_id=ligand.state.state_id,
        ph_min=PH_MIN,
        ph_max=PH_MAX,
        precision=PRECISION,
        store=store,
    )
    charged_index = next(
        candidate.index for candidate in options.candidates if candidate.formal_charge == 1
    )
    protonated = resolve_ligand_protonation(
        ligand_id=ligand_id,
        request=ResolveLigandProtonationRequest(
            parent_state_id=ligand.state.state_id,
            ph_min=PH_MIN,
            ph_max=PH_MAX,
            precision=PRECISION,
            candidate_index=charged_index,
        ),
        store=store,
    )

    conformer = generate_ligand_conformer(
        ligand_id=ligand_id,
        request=GenerateLigandConformerRequest(
            acknowledge_current_chemical_state=True,
            random_seed=73191,
            state_id=protonated.artifact.state_id,
        ),
        store=store,
    )

    assert conformer.inspection.formal_charge == 1


def test_protonation_endpoints_round_trip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ANKORA_DATA_DIR", str(tmp_path))
    store = LigandArtifactStore.from_environment()
    ligand_id = _import(store, "CCN(CC)CC", "triethylamine")
    ligand = store.load_record(ligand_id)
    assert ligand.state is not None
    client = TestClient(create_app())

    options_response = client.get(
        f"/api/v1/ligands/{ligand_id}/states/{ligand.state.state_id}/protonation-options",
        params={"ph_min": PH_MIN, "ph_max": PH_MAX, "precision": PRECISION},
    )
    assert options_response.status_code == 200
    body = options_response.json()
    assert body["selection_required"] is True
    charged = next(c for c in body["candidates"] if c["formal_charge"] == 1)

    resolve_response = client.post(
        f"/api/v1/ligands/{ligand_id}/states/protonate",
        json={
            "parent_state_id": ligand.state.state_id,
            "ph_min": PH_MIN,
            "ph_max": PH_MAX,
            "precision": PRECISION,
            "candidate_index": charged["index"],
        },
    )
    assert resolve_response.status_code == 201
    assert resolve_response.json()["inspection"]["formal_charge"] == 1


def test_a_single_ph_is_a_valid_window_to_resolve_at() -> None:
    """Asking for "the state at 7.4" is a request, not a malformed range.

    The enumeration endpoint has always accepted ph_min == ph_max, so
    rejecting it when applying the result left the two halves of the contract
    disagreeing about the same window.
    """
    request = ResolveLigandProtonationRequest(
        parent_state_id="state-1", ph_min=7.4, ph_max=7.4, candidate_index=0
    )

    assert request.ph_min == request.ph_max == 7.4


def test_an_inverted_ph_window_is_still_rejected() -> None:
    with pytest.raises(ValidationError, match="ph_max must not be below ph_min"):
        ResolveLigandProtonationRequest(
            parent_state_id="state-1", ph_min=8.4, ph_max=6.4, candidate_index=0
        )
