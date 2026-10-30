"""Synthetic native-template and headerless-coordinate inspection regressions."""

from pathlib import Path

import gemmi
import pytest
from fastapi.testclient import TestClient
from test_receptor_geometry import _template_pair

from ankora_backend.api.app import create_app
from ankora_backend.domain.errors import AnkoraDomainError
from ankora_backend.persistence.artifact_store import StructureArtifactStore
from ankora_backend.persistence.receptor_store import ReceptorArtifactStore
from ankora_backend.schemas.receptors import ReceptorPreparationRequest
from ankora_backend.schemas.structures import StructureSource
from ankora_backend.services.receptor_completeness import expected_heavy_atoms
from ankora_backend.services.receptor_inspection import inspect_receptor
from ankora_backend.services.receptor_preparation import prepare_receptor
from ankora_backend.services.structure_inspection import import_structure_bytes


@pytest.mark.parametrize("source_format", ["pdb", "mmcif"])
def test_terminal_oxygen_candidates_are_advisory_and_keep_sources_unchanged(
    tmp_path: Path, source_format: str
) -> None:
    _, complete = _template_pair(tmp_path, insertion="X")
    structure = gemmi.read_structure(str(complete))
    first = structure[0][0]
    if first[0].find_atom("OXT", "\x00"):
        first[0].remove_atom("OXT", "\x00")
    second = first.clone()
    second.name = "B"
    oxygen = gemmi.Atom()
    oxygen.name = "OXT"
    oxygen.element = gemmi.Element("O")
    oxygen.occ = 1.0
    second[0].add_atom(oxygen)
    structure[0].add_chain(second)
    if source_format == "mmcif":
        structure.setup_entities()
        source = structure.make_mmcif_document().as_string().encode()
        filename = "synthetic.cif"
    else:
        source = structure.make_pdb_string().encode()
        filename = "synthetic.pdb"
    store = StructureArtifactStore(tmp_path / "data")
    imported = import_structure_bytes(
        content=source,
        filename=filename,
        source=StructureSource.LOCAL,
        source_uri=None,
        store=store,
    )
    report = inspect_receptor(
        artifact_id=imported.artifact.artifact_id,
        store=store,
        inspection_method="templates_v1",
    )
    assert [candidate.model_dump() for candidate in report.terminal_oxygen_candidates] == [{
        "chain_id": "A", "residue_name": "ALA", "sequence_number": 100,
        "insertion_code": "X", "atom_name": "OXT",
    }]
    assert all("OXT" not in issue.missing_atoms for issue in report.issues)
    assert store.content_path(imported.artifact.artifact_id).read_bytes() == source


def test_headerless_mmcif_api_exposes_versioned_inspection_without_optional_tools(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ANKORA_DATA_DIR", str(tmp_path))
    source = (Path(__file__).parent / "fixtures/synthetic_m1.cif").read_bytes()
    with TestClient(create_app()) as client:
        client.headers["Origin"] = "tauri://localhost"
        imported = client.post(
            "/api/v1/structures/import",
            files={"file": ("synthetic.cif", source, "chemical/x-mmcif")},
        ).json()
        identity = imported["artifact"]["artifact_id"]
        url = f"/api/v1/structures/{identity}/receptor-inspection"
        report = client.get(url).json()
        missing = [item for item in report["issues"] if item["kind"] == "missing_atoms"]
        assert len(missing) == 1
        assert missing[0]["missing_atoms"] == ["CB", "O"]
        assert report["provenance"]["parameters"]["inspection_method"] == "templates_v1"
        assert not client.get(url + "?inspection_method=reported_only").json()["issues"]
        assert client.get(url + "?inspection_method=unknown").status_code == 422
        assert StructureArtifactStore(tmp_path).content_path(identity).read_bytes() == source


def test_source_and_template_observations_merge_without_duplicate_decisions(tmp_path: Path) -> None:
    source = (Path(__file__).parent / "fixtures/synthetic_m1.pdb").read_bytes()
    store = StructureArtifactStore(tmp_path)
    imported = import_structure_bytes(
        content=source,
        filename="synthetic.pdb",
        source=StructureSource.LOCAL,
        source_uri=None,
        store=store,
    )
    report = inspect_receptor(
        artifact_id=imported.artifact.artifact_id, store=store, inspection_method="templates_v1"
    )
    missing = [item for item in report.issues if item.kind == "missing_atoms"]
    assert len(missing) == 1
    assert missing[0].missing_atoms == ["CB"]


@pytest.mark.parametrize(
    "name",
    [
        "ALA",
        "ARG",
        "ASN",
        "ASP",
        "CYS",
        "GLN",
        "GLU",
        "GLY",
        "HIS",
        "ILE",
        "LEU",
        "LYS",
        "MET",
        "PHE",
        "PRO",
        "SER",
        "THR",
        "TRP",
        "TYR",
        "VAL",
    ],
)
def test_standard_name_templates_match_native_pdbfixer_and_find_headerless_missing_atoms(
    tmp_path: Path, name: str
) -> None:
    incomplete, complete = _template_pair(tmp_path, insertion="X", residue_name=name)
    native = {atom.name for atom in gemmi.read_structure(str(complete))[0][0][0]} - {"OXT"}
    assert expected_heavy_atoms(name) == native
    store = StructureArtifactStore(tmp_path / "data")
    source = incomplete.read_bytes()
    imported = import_structure_bytes(
        content=source,
        filename="synthetic.pdb",
        source=StructureSource.LOCAL,
        source_uri=None,
        store=store,
    )
    original = inspect_receptor(artifact_id=imported.artifact.artifact_id, store=store)
    assert not any(issue.kind == "missing_atoms" for issue in original.issues)
    report = inspect_receptor(
        artifact_id=imported.artifact.artifact_id, store=store, inspection_method="templates_v1"
    )
    issue = next(item for item in report.issues if item.kind == "missing_atoms")
    observed = {atom.name for atom in gemmi.read_structure(str(incomplete))[0][0][0]}
    assert set(issue.missing_atoms) == native - observed
    assert issue.residue.insertion_code == "X"
    assert "Standard-template comparison" in issue.message
    assert report.provenance.parameters["inspection_method"] == "templates_v1"
    assert "rdkit_version" in report.provenance.parameters
    assert store.content_path(imported.artifact.artifact_id).read_bytes() == source


@pytest.mark.parametrize(
    "variant",
    ["complete", "zero_occupancy", "alternate_union", "terminal_synonym", "nonstandard", "mmcif"],
)
def test_template_check_handles_occupancy_altlocs_terminals_and_unsupported_residues(
    tmp_path: Path, variant: str
) -> None:
    _, path = _template_pair(tmp_path)
    structure = gemmi.read_structure(str(path))
    residue = structure[0][0][0]
    if variant == "zero_occupancy":
        residue.find_atom("CB", "\x00").occ = 0
    elif variant == "alternate_union":
        residue.find_atom("CB", "\x00").altloc = "A"
    elif variant == "terminal_synonym":
        residue.find_atom("O", "\x00").name = "OT1"
    elif variant == "nonstandard":
        residue.name = "MSE"
    if variant == "mmcif":
        residue.remove_atom("CB", "\x00")
        structure.setup_entities()
        source = structure.make_mmcif_document().as_string().encode()
        filename = "synthetic.cif"
    else:
        source, filename = structure.make_pdb_string().encode(), "synthetic.pdb"
    store = StructureArtifactStore(tmp_path / "data")
    imported = import_structure_bytes(
        content=source,
        filename=filename,
        source=StructureSource.LOCAL,
        source_uri=None,
        store=store,
    )
    report = inspect_receptor(
        artifact_id=imported.artifact.artifact_id, store=store, inspection_method="templates_v1"
    )
    missing = [item for item in report.issues if item.kind == "missing_atoms"]
    assert len(missing) == (1 if variant in {"zero_occupancy", "mmcif"} else 0)
    if missing:
        assert missing[0].missing_atoms == ["CB"]
    assert all("OXT" not in item.missing_atoms for item in report.issues)


def test_versioned_preparation_requires_inferred_issue_decisions_without_mutating_legacy(
    tmp_path: Path,
) -> None:
    source, _ = _template_pair(tmp_path)
    structures = StructureArtifactStore(tmp_path / "data")
    imported = import_structure_bytes(
        content=source.read_bytes(),
        filename="synthetic.pdb",
        source=StructureSource.LOCAL,
        source_uri=None,
        store=structures,
    )
    request = ReceptorPreparationRequest(
        selected_chains=["A"], water_action="remove", component_decisions=[], issue_decisions=[]
    )
    assert "inspection_method" not in request.model_dump(mode="json")
    new = request.model_copy(update={"inspection_method": "templates_v1"})
    assert new.model_dump(mode="json")["inspection_method"] == "templates_v1"
    receptors = ReceptorArtifactStore(tmp_path / "data")
    with pytest.raises(AnkoraDomainError) as failure:
        prepare_receptor(
            source_artifact_id=imported.artifact.artifact_id,
            request=new,
            structure_store=structures,
            receptor_store=receptors,
        )
    assert failure.value.details["missing_issue_decisions"]
    assert not list((tmp_path / "data").glob("projects/default/derived/receptors/*"))
