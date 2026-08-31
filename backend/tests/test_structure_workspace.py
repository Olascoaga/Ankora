from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from ankora_backend.api import routes
from ankora_backend.api.app import create_app
from ankora_backend.persistence.artifact_store import StructureArtifactStore
from ankora_backend.schemas.structures import (
    FetchAlphaFoldStructureRequest,
    StructureFormat,
    StructureSource,
)
from ankora_backend.services.structure_inspection import import_structure_bytes, inspect_structure

FIXTURES = Path(__file__).parent / "fixtures"


def test_synthetic_pdb_inspection_reports_structure_and_stable_warnings() -> None:
    content = (FIXTURES / "synthetic_m1.pdb").read_bytes()

    metadata, warnings = inspect_structure(content, StructureFormat.PDB)

    assert metadata.entry_id == "TST1"
    assert metadata.model_count == 1
    assert metadata.atom_count == 9
    assert metadata.residue_count == 4
    assert metadata.chains[0].chain_id == "A"
    assert metadata.chains[0].polymer_residue_count == 1
    assert {item.kind.value for item in metadata.heterogens} == {"ligand", "water", "metal"}
    assert metadata.alternate_location_atom_count == 2
    assert metadata.missing_residue_count == 1
    assert metadata.missing_atom_count == 1
    assert {warning.code.value for warning in warnings} == {
        "STR_MISSING_RESIDUES",
        "STR_MISSING_ATOMS",
        "STR_ALTERNATE_LOCATIONS",
    }


def test_synthetic_mmcif_is_parsed_without_transforming_coordinates() -> None:
    content = (FIXTURES / "synthetic_m1.cif").read_bytes()

    metadata, warnings = inspect_structure(content, StructureFormat.MMCIF)

    assert metadata.entry_id == "SYN1"
    assert metadata.atom_count == 4
    assert metadata.residue_count == 2
    assert len(metadata.chains) == 1
    assert metadata.chains[0].polymer_residue_count == 1
    assert metadata.heterogens[0].name == "LIG"
    assert warnings == []


def test_reimport_preserves_independent_immutable_originals(tmp_path: Path) -> None:
    content = (FIXTURES / "synthetic_m1.pdb").read_bytes()
    store = StructureArtifactStore(tmp_path)

    first = import_structure_bytes(
        content=content,
        filename="synthetic_m1.pdb",
        source=StructureSource.LOCAL,
        source_uri=None,
        store=store,
    )
    second = import_structure_bytes(
        content=content,
        filename="synthetic_m1.pdb",
        source=StructureSource.LOCAL,
        source_uri=None,
        store=store,
    )

    assert first.artifact.artifact_id != second.artifact.artifact_id
    assert first.artifact.sha256 == second.artifact.sha256
    assert store.content_path(first.artifact.artifact_id).read_bytes() == content
    assert store.content_path(second.artifact.artifact_id).read_bytes() == content
    assert first.provenance.parameters["parser"] == "gemmi"


def test_local_import_and_content_api_round_trip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ANKORA_DATA_DIR", str(tmp_path))
    content = (FIXTURES / "synthetic_m1.pdb").read_bytes()
    client = TestClient(create_app())
    client.headers["Origin"] = "tauri://localhost"

    response = client.post(
        "/api/v1/structures/import",
        files={"file": ("synthetic_m1.pdb", content, "chemical/x-pdb")},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["artifact"]["source"] == "local"
    assert body["artifact"]["sha256"]
    content_response = client.get(
        f"/api/v1/structures/{body['artifact']['artifact_id']}/content"
    )
    assert content_response.status_code == 200
    assert content_response.content == content


def test_fetch_api_records_rcsb_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ANKORA_DATA_DIR", str(tmp_path))
    content = (FIXTURES / "synthetic_m1.cif").read_bytes()

    async def synthetic_fetch(pdb_id: str) -> tuple[bytes, str]:
        assert pdb_id == "7AQF"
        return content, "https://files.rcsb.org/download/7AQF.cif"

    monkeypatch.setattr(routes, "fetch_rcsb_mmcif", synthetic_fetch)

    response = TestClient(create_app()).post(
        "/api/v1/structures/fetch", json={"pdb_id": "7aqf"}
    )

    assert response.status_code == 201
    body = response.json()
    assert body["artifact"]["source"] == "rcsb"
    assert body["artifact"]["source_uri"].endswith("/7AQF.cif")
    assert body["artifact"]["original_filename"] == "7AQF.cif"


def test_invalid_import_uses_stable_error_contract(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ANKORA_DATA_DIR", str(tmp_path))

    response = TestClient(create_app()).post(
        "/api/v1/structures/import",
        headers={"Origin": "tauri://localhost"},
        files={"file": ("notes.txt", b"not a structure", "text/plain")},
    )

    assert response.status_code == 415
    assert response.json() == {
        "code": "UNSUPPORTED_STRUCTURE_FORMAT",
        "stage": "structure_import",
        "message": "Choose a PDB, CIF, or mmCIF coordinate file.",
        "details": {
            "filename": "notes.txt",
            "supported_extensions": [".pdb", ".cif", ".mmcif"],
        },
        "recoverable": True,
    }

def test_alphafold_request_normalizes_valid_accessions() -> None:
    request = FetchAlphaFoldStructureRequest(uniprot_id=" p04637-2 ")

    assert request.uniprot_id == "P04637-2"


@pytest.mark.parametrize(
    "value",
    ["123456", "P0463", "ABCDEFGH", "P046378", "P04637-9999", ""],
)
def test_alphafold_request_rejects_non_uniprot_ids(value: str) -> None:
    with pytest.raises(ValidationError):
        FetchAlphaFoldStructureRequest(uniprot_id=value)


def test_fetch_api_records_alphafold_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ANKORA_DATA_DIR", str(tmp_path))
    content = (FIXTURES / "synthetic_m1.cif").read_bytes()

    async def synthetic_fetch(uniprot_id: str) -> tuple[bytes, str]:
        assert uniprot_id == "P04637"
        return content, "https://alphafold.ebi.ac.uk/files/AF-P04637-F1-model_v6.cif"

    monkeypatch.setattr(routes, "fetch_alphafold_cif", synthetic_fetch)

    response = TestClient(create_app()).post(
        "/api/v1/structures/fetch/alphafold", json={"uniprot_id": "p04637"}
    )

    assert response.status_code == 201
    body = response.json()
    assert body["artifact"]["source"] == "alphafold"
    assert body["artifact"]["source_uri"].endswith("AF-P04637-F1-model_v6.cif")
    assert body["artifact"]["original_filename"] == "AF-P04637-model.cif"
