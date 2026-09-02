from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from rdkit import Chem

from ankora_backend.api.app import create_app
from ankora_backend.domain.errors import AnkoraDomainError
from ankora_backend.persistence.ligand_store import LigandArtifactStore
from ankora_backend.schemas.ligands import (
    GenerateLigandConformerRequest,
    LigandChemicalStateRecord,
    MinimizeLigandRequest,
    ResolveLigandStateRequest,
)
from ankora_backend.services import ligand_minimization as minimization_service
from ankora_backend.services.ligand_import import (
    import_local_ligand,
    import_local_ligand_library,
)
from ankora_backend.services.ligand_minimization import (
    generate_ligand_conformer,
    minimize_ligand,
)
from ankora_backend.services.ligand_state_resolution import (
    resolve_ligand_state,
    state_resolution_options,
)

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.mark.parametrize("filename", ["synthetic_library.sdf", "synthetic_library.mol"])
def test_imports_multirecord_sdf_or_mol_as_traceable_library(
    tmp_path: Path, filename: str
) -> None:
    store = LigandArtifactStore(tmp_path)
    content = (FIXTURES / "synthetic_ligand_library.sdf").read_bytes()

    library = import_local_ligand_library(
        content=content, filename=filename, store=store
    )

    assert library.artifact.record_count == 2
    assert library.imported_count == 2
    assert library.failed_count == 0
    assert store.library_content_path(library.artifact.library_id).read_bytes() == content
    ligands = [entry.ligand for entry in library.entries]
    assert all(item is not None for item in ligands)
    assert [item.inspection.name for item in ligands if item] == [
        "synthetic_ethanol",
        "synthetic_acetone",
    ]
    assert [item.inspection.canonical_smiles for item in ligands if item] == [
        "CCO",
        "CC(C)=O",
    ]
    assert [round(item.inspection.molecular_weight_g_mol or 0, 3) for item in ligands if item] == [
        46.069,
        58.080,
    ]
    assert [item.artifact.library_record_index for item in ligands if item] == [0, 1]

    conformers = [
        generate_ligand_conformer(
            ligand_id=item.artifact.ligand_id,
            request=GenerateLigandConformerRequest(
                acknowledge_current_chemical_state=True,
                state_id=item.state.state_id if item.state else None,
                random_seed=73191,
            ),
            store=store,
        )
        for item in ligands
        if item is not None
    ]
    assert len(conformers) == 2
    assert all(item.minimization.converged for item in conformers)
    assert all(item.minimization.final_energy_kcal_mol is not None for item in conformers)


def test_library_keeps_record_level_failures_without_discarding_valid_molecules(
    tmp_path: Path,
) -> None:
    store = LigandArtifactStore(tmp_path)
    library = import_local_ligand_library(
        content=b"CCO valid_ethanol\nnot_a_smiles broken\nCC valid_ethane\n",
        filename="mixed_library.smi",
        store=store,
    )

    assert library.artifact.record_count == 3
    assert library.imported_count == 2
    assert library.failed_count == 1
    assert library.entries[1].status.value == "failed"
    assert library.entries[1].failure is not None
    assert library.entries[1].failure.code == "LIGAND_LIBRARY_RECORD_PARSE_FAILED"


@pytest.mark.parametrize(
    ("filename", "expected_format"),
    [
        ("synthetic_ethanol.sdf", "sdf"),
        ("synthetic_ethanol.mol", "mol"),
        ("synthetic_ethanol.smi", "smiles"),
    ],
)
def test_imports_and_preserves_each_local_format(
    tmp_path: Path, filename: str, expected_format: str
) -> None:
    store = LigandArtifactStore(tmp_path)
    content = (FIXTURES / filename).read_bytes()

    record = import_local_ligand(content=content, filename=filename, store=store)

    assert record.artifact.source.value == "local"
    assert record.artifact.format.value == expected_format
    assert record.inspection.formula == "C2H6O"
    assert record.inspection.molecular_weight_g_mol == pytest.approx(46.069, abs=0.001)
    assert record.inspection.has_3d_coordinates is False
    assert record.inspection.fragment_count == 1
    assert record.state is not None
    assert store.content_path(record.artifact.ligand_id).read_bytes() == content
    state = Chem.SDMolSupplier(
        str(store.state_content_path(record.artifact.ligand_id)), removeHs=False
    )[0]
    assert state is not None
    assert state.GetNumHeavyAtoms() == 3
    assert {warning.code.value for warning in record.warnings} == {
        "LIG_3D_COORDINATES_MISSING"
    }


def test_independent_etkdg_conformer_is_reproducible_and_create_only(
    tmp_path: Path,
) -> None:
    store = LigandArtifactStore(tmp_path)
    source = (FIXTURES / "synthetic_ethanol.smi").read_bytes()
    ligand = import_local_ligand(
        content=source, filename="synthetic_ethanol.smi", store=store
    )
    request = GenerateLigandConformerRequest(
        force_field="MMFF94s",
        max_iterations=500,
        acknowledge_current_chemical_state=True,
        random_seed=73191,
    )

    first = generate_ligand_conformer(
        ligand_id=ligand.artifact.ligand_id, request=request, store=store
    )
    second = generate_ligand_conformer(
        ligand_id=ligand.artifact.ligand_id, request=request, store=store
    )

    assert first.artifact.stage == "generated_minimized"
    assert first.artifact.conformer_id != second.artifact.conformer_id
    assert first.artifact.sha256 == second.artifact.sha256
    assert first.minimization.embedding_method == "ETKDGv3"
    assert first.minimization.random_seed == 73191
    assert first.minimization.independent_from_source_coordinates is True
    assert first.minimization.converged is True
    assert first.inspection.has_3d_coordinates is True
    assert first.inspection.molecular_weight_g_mol == pytest.approx(46.069, abs=0.001)
    assert store.content_path(ligand.artifact.ligand_id).read_bytes() == source


def test_synthetic_pool_prefers_the_lowest_energy_converged_outcome(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A lower-energy nonconverged geometry cannot displace a usable one."""
    store = LigandArtifactStore(tmp_path)
    ligand = import_local_ligand(
        content=(FIXTURES / "synthetic_ethanol.smi").read_bytes(),
        filename="synthetic_ethanol.smi",
        store=store,
    )
    observed_ids: list[int] = []

    def synthetic_outcome(
        _molecule: object, conf_id: int, _request: object
    ) -> minimization_service._MinimizationOutcome:
        index = len(observed_ids)
        observed_ids.append(conf_id)
        if index == 0:
            energy, converged = -100.0, False
        elif index == 1:
            energy, converged = -5.0, True
        else:
            energy, converged = float(index), True
        return minimization_service._MinimizationOutcome(
            conf_id=conf_id,
            initial_energy_kcal_mol=energy + 10.0,
            final_energy_kcal_mol=energy,
            converged=converged,
            warnings=[],
        )

    monkeypatch.setattr(
        minimization_service, "_run_mmff_minimization", synthetic_outcome
    )
    record = generate_ligand_conformer(
        ligand_id=ligand.artifact.ligand_id,
        request=GenerateLigandConformerRequest(
            acknowledge_current_chemical_state=True,
            random_seed=73191,
        ),
        store=store,
    )

    assert len(observed_ids) > 1
    assert record.minimization.converged is True
    assert record.minimization.final_energy_kcal_mol == -5.0
    assert record.minimization.conformer_pool_converged_count == len(observed_ids) - 1
    assert record.minimization.conformer_selection_policy.value == (
        "lowest_energy_converged"
    )
    assert record.provenance.parameters["selected_conformer_id"] == observed_ids[1]
    assert record.provenance.parameters["conformer_selection_policy"] == (
        "lowest_energy_converged"
    )
    assert record.provenance.parameters["conformer_pool_converged_count"] == (
        len(observed_ids) - 1
    )
    assert record.warnings == []


def test_synthetic_pool_preserves_an_explicit_fallback_when_none_converge(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = LigandArtifactStore(tmp_path)
    ligand = import_local_ligand(
        content=(FIXTURES / "synthetic_ethanol.smi").read_bytes(),
        filename="synthetic_ethanol.smi",
        store=store,
    )
    observed_ids: list[int] = []

    def synthetic_outcome(
        _molecule: object, conf_id: int, _request: object
    ) -> minimization_service._MinimizationOutcome:
        index = len(observed_ids)
        observed_ids.append(conf_id)
        energy = -float(index)
        return minimization_service._MinimizationOutcome(
            conf_id=conf_id,
            initial_energy_kcal_mol=energy + 10.0,
            final_energy_kcal_mol=energy,
            converged=False,
            warnings=[],
        )

    monkeypatch.setattr(
        minimization_service, "_run_mmff_minimization", synthetic_outcome
    )
    record = generate_ligand_conformer(
        ligand_id=ligand.artifact.ligand_id,
        request=GenerateLigandConformerRequest(
            acknowledge_current_chemical_state=True,
            random_seed=73191,
        ),
        store=store,
    )

    assert record.minimization.converged is False
    assert record.minimization.final_energy_kcal_mol == -float(len(observed_ids) - 1)
    assert record.minimization.conformer_pool_converged_count == 0
    assert record.minimization.conformer_selection_policy.value == (
        "lowest_energy_nonconverged_fallback"
    )
    assert record.provenance.parameters["conformer_selection_policy"] == (
        "lowest_energy_nonconverged_fallback"
    )
    assert record.provenance.parameters["conformer_pool_converged_count"] == 0
    warning = record.warnings[0]
    assert warning.code.value == "LIG_MINIMIZATION_NOT_CONVERGED"
    assert f"None of the {len(observed_ids)} embedded conformers converged" in (
        warning.message
    )
    assert warning.details["selected_conformer_id"] == observed_ids[-1]


def test_two_dimensional_state_requires_generation_not_direct_minimization(
    tmp_path: Path,
) -> None:
    store = LigandArtifactStore(tmp_path)
    ligand = import_local_ligand(
        content=(FIXTURES / "synthetic_ethanol.mol").read_bytes(),
        filename="synthetic_ethanol.mol",
        store=store,
    )

    with pytest.raises(AnkoraDomainError) as captured:
        minimize_ligand(
            ligand_id=ligand.artifact.ligand_id,
            request=MinimizeLigandRequest(
                acknowledge_current_chemical_state=True
            ),
            store=store,
        )

    assert captured.value.code == "LIGAND_3D_CONFORMER_REQUIRED"


@pytest.mark.parametrize(
    ("smiles", "expected_code"),
    [
        ("CC(O)F undefined_stereo\n", "LIG_STEREOCHEMISTRY_UNDEFINED"),
        ("CCO.[Na+] multicomponent\n", "LIGAND_MULTICOMPONENT_REQUIRES_DECISION"),
    ],
)
def test_generation_blocks_unresolved_chemical_state_decisions(
    tmp_path: Path, smiles: str, expected_code: str
) -> None:
    store = LigandArtifactStore(tmp_path)
    ligand = import_local_ligand(
        content=smiles.encode("utf-8"), filename="decision.smi", store=store
    )

    with pytest.raises(AnkoraDomainError) as captured:
        generate_ligand_conformer(
            ligand_id=ligand.artifact.ligand_id,
            request=GenerateLigandConformerRequest(
                acknowledge_current_chemical_state=True
            ),
            store=store,
        )

    assert captured.value.code == expected_code


def test_explicit_component_and_stereoisomer_selection_creates_resolved_state(
    tmp_path: Path,
) -> None:
    store = LigandArtifactStore(tmp_path)
    ligand = import_local_ligand(
        content=b"CC(O)F.[Na+] unresolved_state\n",
        filename="unresolved_state.smi",
        store=store,
    )
    assert ligand.state is not None

    unresolved = state_resolution_options(
        ligand_id=ligand.artifact.ligand_id,
        parent_state_id=ligand.state.state_id,
        component_index=None,
        store=store,
    )
    assert unresolved.component_selection_required is True
    assert len(unresolved.component_options) == 2
    assert unresolved.stereoisomer_options == []

    selected_component = state_resolution_options(
        ligand_id=ligand.artifact.ligand_id,
        parent_state_id=ligand.state.state_id,
        component_index=0,
        store=store,
    )
    assert selected_component.stereoisomer_selection_required is True
    assert len(selected_component.stereoisomer_options) == 2

    resolved = resolve_ligand_state(
        ligand_id=ligand.artifact.ligand_id,
        request=ResolveLigandStateRequest(
            parent_state_id=ligand.state.state_id,
            component_index=0,
            stereoisomer_index=1,
        ),
        store=store,
    )
    assert resolved.artifact.state_id != ligand.state.state_id
    assert resolved.parent_state_id == ligand.state.state_id
    assert resolved.inspection.fragment_count == 1
    assert resolved.inspection.undefined_stereocenter_count == 0
    assert resolved.selection.component_index == 0
    assert resolved.selection.stereoisomer_index == 1
    assert isinstance(
        store.load_state_record(ligand.artifact.ligand_id, resolved.artifact.state_id),
        LigandChemicalStateRecord,
    )

    conformer = generate_ligand_conformer(
        ligand_id=ligand.artifact.ligand_id,
        request=GenerateLigandConformerRequest(
            acknowledge_current_chemical_state=True,
            state_id=resolved.artifact.state_id,
            random_seed=73191,
        ),
        store=store,
    )
    assert conformer.provenance.input_artifacts == [resolved.artifact.state_id]


def test_state_resolution_api_serves_create_only_derivative(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ANKORA_DATA_DIR", str(tmp_path))
    client = TestClient(create_app())
    client.headers["Origin"] = "tauri://localhost"
    imported = client.post(
        "/api/v1/ligands/import",
        files={
            "file": (
                "unresolved.smi",
                b"CC(O)F.[Na+] unresolved\n",
                "chemical/x-daylight-smiles",
            )
        },
    ).json()
    ligand_id = imported["artifact"]["ligand_id"]
    parent_state_id = imported["state"]["state_id"]
    options = client.get(
        f"/api/v1/ligands/{ligand_id}/states/{parent_state_id}/resolution-options",
        params={"component_index": 0},
    )
    assert options.status_code == 200
    assert len(options.json()["stereoisomer_options"]) == 2

    response = client.post(
        f"/api/v1/ligands/{ligand_id}/states/resolve",
        json={
            "parent_state_id": parent_state_id,
            "component_index": 0,
            "stereoisomer_index": 0,
        },
    )
    assert response.status_code == 201
    resolved = response.json()
    assert resolved["inspection"]["fragment_count"] == 1
    assert client.get(f"/api/v1{resolved['content_url']}").status_code == 200


def test_local_import_and_generation_api_round_trip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ANKORA_DATA_DIR", str(tmp_path))
    client = TestClient(create_app())
    client.headers["Origin"] = "tauri://localhost"
    source = (FIXTURES / "synthetic_ethanol.smi").read_bytes()

    imported = client.post(
        "/api/v1/ligands/import",
        files={"file": ("synthetic_ethanol.smi", source, "chemical/x-daylight-smiles")},
    )

    assert imported.status_code == 201
    ligand = imported.json()
    original = client.get(f"/api/v1{ligand['original_content_url']}")
    state = client.get(f"/api/v1{ligand['content_url']}")
    assert original.content == source
    assert b"V2000" in state.content
    generated = client.post(
        f"/api/v1/ligands/{ligand['artifact']['ligand_id']}/conformers/generate",
        json={
            "force_field": "MMFF94s",
            "max_iterations": 500,
            "acknowledge_current_chemical_state": True,
            "random_seed": 73191,
        },
    )
    assert generated.status_code == 201
    record = generated.json()
    assert record["minimization"]["embedding_method"] == "ETKDGv3"
    assert client.get(f"/api/v1{record['content_url']}").status_code == 200


def test_multirecord_library_api_preserves_source_and_returns_rows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ANKORA_DATA_DIR", str(tmp_path))
    client = TestClient(create_app())
    client.headers["Origin"] = "tauri://localhost"
    source = (FIXTURES / "synthetic_ligand_library.sdf").read_bytes()

    response = client.post(
        "/api/v1/ligand-libraries/import",
        files={
            "file": (
                "synthetic_ligand_library.sdf",
                source,
                "chemical/x-mdl-sdfile",
            )
        },
    )

    assert response.status_code == 201
    library = response.json()
    assert library["imported_count"] == 2
    assert [entry["ligand"]["inspection"]["name"] for entry in library["entries"]] == [
        "synthetic_ethanol",
        "synthetic_acetone",
    ]
    assert client.get(f"/api/v1{library['original_content_url']}").content == source
