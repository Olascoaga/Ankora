from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from rdkit import Chem

from ankora_backend.api.app import create_app
from ankora_backend.domain.errors import AnkoraDomainError
from ankora_backend.persistence.artifact_store import StructureArtifactStore
from ankora_backend.persistence.ligand_store import LigandArtifactStore
from ankora_backend.schemas.ligands import (
    ExtractLigandRequest,
    LigandForceField,
    LigandLocator,
    MinimizeLigandRequest,
)
from ankora_backend.schemas.structures import StructureSource
from ankora_backend.services.ligand_extraction import extract_crystallographic_ligand
from ankora_backend.services.ligand_minimization import minimize_ligand
from ankora_backend.services.structure_inspection import import_structure_bytes

FIXTURE = Path(__file__).parent / "fixtures" / "synthetic_ligand_source.cif"
CHIRAL_FIXTURE = (
    Path(__file__).parent / "fixtures" / "synthetic_chiral_ligand_source.cif"
)


def _source(store: StructureArtifactStore) -> str:
    return import_structure_bytes(
        content=FIXTURE.read_bytes(),
        filename=FIXTURE.name,
        source=StructureSource.LOCAL,
        source_uri=None,
        store=store,
    ).artifact.artifact_id


def _request() -> ExtractLigandRequest:
    return ExtractLigandRequest(
        locator=LigandLocator(
            component_name="LIG", chain_id="A", sequence_number=401
        )
    )


def test_extracts_observed_coordinates_with_mmcif_bond_orders(tmp_path: Path) -> None:
    structure_store = StructureArtifactStore(tmp_path)
    ligand_store = LigandArtifactStore(tmp_path)
    source_id = _source(structure_store)

    record = extract_crystallographic_ligand(
        source_artifact_id=source_id,
        request=_request(),
        structure_store=structure_store,
        ligand_store=ligand_store,
    )

    assert record.artifact.source.value == "crystallographic"
    assert record.inspection.formula == "CH3NO"
    assert record.inspection.molecular_weight_g_mol == pytest.approx(45.041, abs=0.001)
    assert record.inspection.exact_mass_da == pytest.approx(45.021464, abs=0.000001)
    assert record.inspection.heavy_atom_count == 3
    assert record.inspection.conformer_count == 1
    molecule = Chem.SDMolSupplier(
        str(ligand_store.content_path(record.artifact.ligand_id)), removeHs=False
    )[0]
    assert molecule is not None
    assert sorted(bond.GetBondTypeAsDouble() for bond in molecule.GetBonds()) == [1.0, 2.0]
    assert molecule.GetConformer().GetAtomPosition(1).x == pytest.approx(1.22)
    assert structure_store.content_path(source_id).read_bytes() == FIXTURE.read_bytes()


def test_extracts_stereochemistry_from_observed_coordinates(tmp_path: Path) -> None:
    structure_store = StructureArtifactStore(tmp_path)
    ligand_store = LigandArtifactStore(tmp_path)
    source_id = import_structure_bytes(
        content=CHIRAL_FIXTURE.read_bytes(),
        filename=CHIRAL_FIXTURE.name,
        source=StructureSource.LOCAL,
        source_uri=None,
        store=structure_store,
    ).artifact.artifact_id

    record = extract_crystallographic_ligand(
        source_artifact_id=source_id,
        request=ExtractLigandRequest(
            locator=LigandLocator(
                component_name="CHI", chain_id="A", sequence_number=401
            )
        ),
        structure_store=structure_store,
        ligand_store=ligand_store,
    )

    assert record.inspection.stereocenter_count == 1
    assert record.inspection.undefined_stereocenter_count == 0
    assert record.inspection.canonical_smiles is not None
    assert "@" in record.inspection.canonical_smiles
    molecule = Chem.SDMolSupplier(
        str(ligand_store.content_path(record.artifact.ligand_id)), removeHs=False
    )[0]
    assert molecule is not None
    assert Chem.FindMolChiralCenters(molecule, includeUnassigned=True) == [(1, "R")]


def test_refuses_coordinates_that_contradict_deposited_stereochemistry(
    tmp_path: Path,
) -> None:
    structure_store = StructureArtifactStore(tmp_path)
    ligand_store = LigandArtifactStore(tmp_path)
    contradictory = CHIRAL_FIXTURE.read_bytes().replace(
        b"CHI C1 C 0 R", b"CHI C1 C 0 S"
    )
    source_id = import_structure_bytes(
        content=contradictory,
        filename=CHIRAL_FIXTURE.name,
        source=StructureSource.LOCAL,
        source_uri=None,
        store=structure_store,
    ).artifact.artifact_id

    with pytest.raises(AnkoraDomainError) as error:
        extract_crystallographic_ligand(
            source_artifact_id=source_id,
            request=ExtractLigandRequest(
                locator=LigandLocator(
                    component_name="CHI", chain_id="A", sequence_number=401
                )
            ),
            structure_store=structure_store,
            ligand_store=ligand_store,
        )

    assert error.value.code == "LIGAND_STEREOCHEMISTRY_MISMATCH"


def test_ligand_api_round_trip_is_create_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ANKORA_DATA_DIR", str(tmp_path))
    client = TestClient(create_app())
    client.headers["Origin"] = "tauri://localhost"
    imported = client.post(
        "/api/v1/structures/import",
        files={"file": (FIXTURE.name, FIXTURE.read_bytes(), "chemical/x-mmcif")},
    ).json()

    response = client.post(
        f"/api/v1/structures/{imported['artifact']['artifact_id']}/ligands/extract",
        json=_request().model_dump(mode="json"),
    )

    assert response.status_code == 201
    record = response.json()
    content = client.get(f"/api/v1/ligands/{record['artifact']['ligand_id']}/content")
    assert content.status_code == 200
    assert b"V2000" in content.content
    second = client.post(
        f"/api/v1/structures/{imported['artifact']['artifact_id']}/ligands/extract",
        json=_request().model_dump(mode="json"),
    ).json()
    assert second["artifact"]["ligand_id"] != record["artifact"]["ligand_id"]
    assert second["artifact"]["sha256"] == record["artifact"]["sha256"]


def test_minimizes_to_an_immutable_mmff_conformer(tmp_path: Path) -> None:
    structure_store = StructureArtifactStore(tmp_path)
    ligand_store = LigandArtifactStore(tmp_path)
    source_id = _source(structure_store)
    original = extract_crystallographic_ligand(
        source_artifact_id=source_id,
        request=_request(),
        structure_store=structure_store,
        ligand_store=ligand_store,
    )
    original_bytes = ligand_store.content_path(original.artifact.ligand_id).read_bytes()

    minimized = minimize_ligand(
        ligand_id=original.artifact.ligand_id,
        request=MinimizeLigandRequest(
            force_field=LigandForceField.MMFF94S,
            max_iterations=500,
            acknowledge_current_chemical_state=True,
        ),
        store=ligand_store,
    )

    assert minimized.artifact.ligand_id == original.artifact.ligand_id
    assert minimized.artifact.conformer_id != original.artifact.ligand_id
    assert minimized.minimization.force_field == LigandForceField.MMFF94S
    assert minimized.minimization.converged is True
    assert (
        minimized.minimization.final_energy_kcal_mol
        < minimized.minimization.initial_energy_kcal_mol
    )
    assert minimized.inspection.molecular_weight_g_mol == pytest.approx(
        original.inspection.molecular_weight_g_mol
    )
    assert ligand_store.content_path(original.artifact.ligand_id).read_bytes() == original_bytes
    minimized_molecule = Chem.SDMolSupplier(
        str(
            ligand_store.conformer_content_path(
                original.artifact.ligand_id, minimized.artifact.conformer_id
            )
        ),
        removeHs=False,
    )[0]
    assert minimized_molecule is not None
    assert minimized_molecule.GetNumAtoms() > minimized_molecule.GetNumHeavyAtoms()

    limited = minimize_ligand(
        ligand_id=original.artifact.ligand_id,
        request=MinimizeLigandRequest(
            force_field=LigandForceField.MMFF94S,
            max_iterations=1,
            acknowledge_current_chemical_state=True,
        ),
        store=ligand_store,
    )
    assert limited.minimization.converged is False
    assert limited.warnings[0].code.value == "LIG_MINIMIZATION_NOT_CONVERGED"


def test_minimization_api_requires_state_confirmation_and_serves_derivative(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ANKORA_DATA_DIR", str(tmp_path))
    client = TestClient(create_app())
    client.headers["Origin"] = "tauri://localhost"
    imported = client.post(
        "/api/v1/structures/import",
        files={"file": (FIXTURE.name, FIXTURE.read_bytes(), "chemical/x-mmcif")},
    ).json()
    ligand = client.post(
        f"/api/v1/structures/{imported['artifact']['artifact_id']}/ligands/extract",
        json=_request().model_dump(mode="json"),
    ).json()
    ligand_id = ligand["artifact"]["ligand_id"]

    blocked = client.post(
        f"/api/v1/ligands/{ligand_id}/conformers/minimize",
        json={"force_field": "MMFF94s", "max_iterations": 500},
    )
    assert blocked.status_code == 422
    assert blocked.json()["code"] == "LIGAND_STATE_CONFIRMATION_REQUIRED"

    response = client.post(
        f"/api/v1/ligands/{ligand_id}/conformers/minimize",
        json={
            "force_field": "MMFF94s",
            "max_iterations": 500,
            "acknowledge_current_chemical_state": True,
        },
    )
    assert response.status_code == 201
    conformer = response.json()
    content = client.get(f"/api/v1{conformer['content_url']}")
    assert content.status_code == 200
    assert b"V2000" in content.content
