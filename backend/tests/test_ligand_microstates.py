"""Synthetic contracts for bounded, scientist-selected screening microstates."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ankora_backend.api.app import create_app
from ankora_backend.domain.errors import AnkoraDomainError
from ankora_backend.persistence.ligand_store import LigandArtifactStore
from ankora_backend.schemas.ligands import (
    ApplyLigandLibraryFilterRequest,
    LigandMicrostateMode,
    LigandMicrostatePlan,
    LigandMicrostateRecord,
    ResolveLigandMicrostateRequest,
)
from ankora_backend.services.ligand_filtering import apply_library_filters
from ankora_backend.services.ligand_import import (
    import_local_ligand,
    import_local_ligand_library,
)
from ankora_backend.services.ligand_microstates import (
    microstate_options,
    resolve_ligand_microstate,
)


def _plan(**changes: object) -> LigandMicrostatePlan:
    return LigandMicrostatePlan(
        mode=LigandMicrostateMode.ENUMERATED_SELECTION,
        **changes,
    )


def test_options_are_bounded_deterministic_and_not_ranked(tmp_path: Path) -> None:
    store = LigandArtifactStore(tmp_path)
    ligand = import_local_ligand(
        content=b"CC(=O)CC(C)=O acetylacetone\n",
        filename="synthetic_acetylacetone.smi",
        store=store,
    )
    assert ligand.state is not None
    plan = _plan(max_tautomers_per_protomer=1, max_microstates_per_parent=2)

    first = microstate_options(
        ligand_id=ligand.artifact.ligand_id,
        parent_state_id=ligand.state.state_id,
        plan=plan,
        store=store,
    )
    second = microstate_options(
        ligand_id=ligand.artifact.ligand_id,
        parent_state_id=ligand.state.state_id,
        plan=plan,
        store=store,
    )

    assert 1 <= len(first.candidates) <= 2
    assert first.candidates == second.candidates
    assert [candidate.index for candidate in first.candidates] == list(
        range(len(first.candidates))
    )
    assert all(len(candidate.microstate_key) == 64 for candidate in first.candidates)
    assert first.enumerated_candidate_count >= len(first.candidates)
    # The deliberately tiny bounds should surface a visible limitation rather
    # than pretending this is a complete population model.
    assert first.truncated is True


def test_selected_microstate_is_create_only_and_feeds_filtering(tmp_path: Path) -> None:
    store = LigandArtifactStore(tmp_path)
    library = import_local_ligand_library(
        content=b"CCN(CC)CC triethylamine\n",
        filename="synthetic_microstate_library.smi",
        store=store,
    )
    ligand = library.entries[0].ligand
    assert ligand is not None and ligand.state is not None
    plan = _plan(max_tautomers_per_protomer=4, max_microstates_per_parent=8)
    options = microstate_options(
        ligand_id=ligand.artifact.ligand_id,
        parent_state_id=ligand.state.state_id,
        plan=plan,
        store=store,
    )
    charged = next(
        candidate for candidate in options.candidates if candidate.formal_charge == 1
    )
    request = ResolveLigandMicrostateRequest(
        parent_state_id=ligand.state.state_id,
        plan=plan,
        candidate_index=charged.index,
        acknowledge_bounded_enumeration=True,
    )

    first = resolve_ligand_microstate(
        ligand_id=ligand.artifact.ligand_id,
        request=request,
        store=store,
    )
    second = resolve_ligand_microstate(
        ligand_id=ligand.artifact.ligand_id,
        request=request,
        store=store,
    )

    assert first.artifact.state_id != second.artifact.state_id
    assert first.artifact.sha256 == second.artifact.sha256
    assert first.inspection.formal_charge == 1
    assert isinstance(
        store.load_state_record(ligand.artifact.ligand_id, first.artifact.state_id),
        LigandMicrostateRecord,
    )
    run = apply_library_filters(
        library_id=library.artifact.library_id,
        request=ApplyLigandLibraryFilterRequest(
            microstate_plan=plan,
            state_overrides={
                ligand.artifact.ligand_id: first.artifact.state_id,
            },
            acknowledge_selection=True,
        ),
        store=store,
    )
    assert run.microstate_plan == plan
    assert run.evaluations[0].state_id == first.artifact.state_id
    assert run.evaluations[0].canonical_isomeric_smiles == (
        first.inspection.canonical_smiles
    )


def test_enumerated_filter_policy_rejects_an_unselected_parent(tmp_path: Path) -> None:
    store = LigandArtifactStore(tmp_path)
    library = import_local_ligand_library(
        content=b"CCO ethanol\n",
        filename="synthetic_unselected_microstate.smi",
        store=store,
    )

    with pytest.raises(AnkoraDomainError) as captured:
        apply_library_filters(
            library_id=library.artifact.library_id,
            request=ApplyLigandLibraryFilterRequest(
                microstate_plan=_plan(),
                acknowledge_selection=True,
            ),
            store=store,
        )

    assert captured.value.code == "LIGAND_MICROSTATE_SELECTION_REQUIRED"
    assert captured.value.details is not None
    assert captured.value.details["missing_ligand_ids"] == [
        library.entries[0].ligand.artifact.ligand_id  # type: ignore[union-attr]
    ]


def test_microstate_endpoints_round_trip(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ANKORA_DATA_DIR", str(tmp_path))
    store = LigandArtifactStore.from_environment()
    ligand = import_local_ligand(
        content=b"CCN(CC)CC triethylamine\n",
        filename="synthetic_api_microstate.smi",
        store=store,
    )
    assert ligand.state is not None
    plan = _plan()
    client = TestClient(create_app())

    options_response = client.post(
        f"/api/v1/ligands/{ligand.artifact.ligand_id}/states/"
        f"{ligand.state.state_id}/microstate-options",
        json=plan.model_dump(mode="json"),
    )
    assert options_response.status_code == 200
    options = options_response.json()
    assert options["candidates"]

    selected = options["candidates"][0]
    resolve_response = client.post(
        f"/api/v1/ligands/{ligand.artifact.ligand_id}/states/select-microstate",
        json={
            "parent_state_id": ligand.state.state_id,
            "plan": plan.model_dump(mode="json"),
            "candidate_index": selected["index"],
            "acknowledge_bounded_enumeration": True,
        },
    )
    assert resolve_response.status_code == 201
    body = resolve_response.json()
    assert body["selection"]["microstate_key"] == selected["microstate_key"]
    assert body["provenance"]["parameters"][
        "candidate_order_is_not_a_population_ranking"
    ] is True
