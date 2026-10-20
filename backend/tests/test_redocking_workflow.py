"""UI-facing validation guards. Routing metadata is synthetic; molecules/poses
are the retained 7AQF/RV2 fixtures, not invented docking or RMSD results.
No scientific executable is launched by these tests.
"""

import hashlib
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from ankora_backend.api.app import create_app
from ankora_backend.domain.errors import AnkoraDomainError
from ankora_backend.persistence.ligand_store import LigandArtifactStore
from ankora_backend.persistence.redocking_store import RedockingValidationStore
from ankora_backend.schemas.ligands import LigandRecord
from ankora_backend.schemas.redocking import RedockingValidationRequest
from ankora_backend.services.redocking_validation import RedockingValidationService

FIXTURES = Path(__file__).parent / "fixtures"
REFERENCE_ID = "00000000-0000-0000-0000-000000000081"
STRUCTURE_ID = "00000000-0000-0000-0000-000000000082"


def reference_record() -> LigandRecord:
    content = (FIXTURES / "redocking_7aqf_rv2_crystal.sdf").read_bytes()
    return LigandRecord.model_validate(
        {
            "artifact": {
                "ligand_id": REFERENCE_ID,
                "source": "crystallographic",
                "source_structure_id": STRUCTURE_ID,
                "locator": {"component_name": "RV2", "chain_id": "A", "sequence_number": 401},
                "filename": "reference.sdf",
                "format": "sdf",
                "sha256": hashlib.sha256(content).hexdigest(),
                "size_bytes": len(content),
                "created_at": datetime.now(UTC),
            },
            "inspection": {
                "name": "RV2",
                "formula": "C20H21N3O5",
                "formal_charge": 0,
                "atom_count": 27,
                "heavy_atom_count": 27,
                "rotatable_bond_count": 0,
                "aromatic_ring_count": 0,
                "stereocenter_count": 0,
                "conformer_count": 1,
                "has_3d_coordinates": True,
            },
            "warnings": [],
            "content_url": "/synthetic/reference",
            "provenance": {
                "event_id": "synthetic-routing",
                "event_type": "ligand_extracted",
                "timestamp": datetime.now(UTC),
                "input_artifacts": [STRUCTURE_ID],
                "output_artifacts": [REFERENCE_ID],
                "parameters": {"synthetic_metadata": True},
                "tool": {"name": "fixture replay", "version": "1"},
                "warnings": [],
                "command": [],
            },
        }
    )


@pytest.fixture
def replay(tmp_path):  # type: ignore[no-untyped-def]
    ligand_store = LigandArtifactStore(tmp_path)
    reference = reference_record()
    ligand_store.create(
        REFERENCE_ID, (FIXTURES / "redocking_7aqf_rv2_crystal.sdf").read_bytes(), reference
    )
    pose_path = tmp_path / "pose.pdbqt"
    pose_path.write_bytes((FIXTURES / "redocking_gpu_top_ranked_pose.pdbqt").read_bytes())
    artifact = SimpleNamespace(
        filename="pose.pdbqt",
        size_bytes=pose_path.stat().st_size,
        sha256=hashlib.sha256(pose_path.read_bytes()).hexdigest(),
    )
    pose = SimpleNamespace(
        mode=1,
        run=9,
        cluster_rank=1,
        sub_rank=1,
        affinity_kcal_mol=-7.1,
        binding_energy_kcal_mol=-7.1,
        artifact=artifact,
    )
    tool = SimpleNamespace(name="synthetic-routing", version="1")
    job = SimpleNamespace(
        status="completed",
        poses=[pose],
        runs=[pose],
        receptor_id="receptor",
        binding_site_id="site",
        request=SimpleNamespace(receptor_id="receptor", binding_site_id="site"),
        tool=tool,
        autodock4=SimpleNamespace(tool=tool),
        autodock_gpu=SimpleNamespace(tool=tool),
        bitwise_reproducible=False,
        warnings=[],
    )
    result_store = SimpleNamespace(
        load_record=lambda _: job, load_job=lambda _: job, output_path=lambda *_: pose_path
    )
    receptor = SimpleNamespace(source_artifact_id=STRUCTURE_ID)
    structure_hashes = {
        STRUCTURE_ID: "a" * 64,
        "duplicate-import": "a" * 64,
        "other-structure": "b" * 64,
    }
    service = RedockingValidationService(
        store=RedockingValidationStore(tmp_path),
        ligand_store=ligand_store,
        docking_store=result_store,
        autodock4_store=result_store,  # type: ignore[arg-type]
        autodock_gpu_store=result_store,  # type: ignore[arg-type]
        receptor_store=SimpleNamespace(load_record=lambda _: receptor),  # type: ignore[arg-type]
        structure_store=SimpleNamespace(
            load_record=lambda identity: SimpleNamespace(  # type: ignore[arg-type]
                artifact=SimpleNamespace(sha256=structure_hashes[identity])
            )
        ),
    )
    return service, job, reference, pose_path, receptor


@pytest.mark.parametrize("kind", ["vina_job", "autodock4_job", "autodock_gpu_job"])
def test_each_engine_records_real_in_place_measurement_and_reopens(replay, kind):  # type: ignore[no-untyped-def]
    service, _, reference, _, _ = replay
    request = RedockingValidationRequest(
        source_kind=kind,
        source_id="synthetic-job",
        reference_ligand_id=REFERENCE_ID,
        threshold_angstrom=1,
    )
    record = service.validate(request)
    assert record.metrics.top1_rmsd_angstrom > 10
    assert not record.metrics.sampling_success
    assert not record.metrics.ranking_success
    assert record.reference_sha256 == reference.artifact.sha256
    assert record.provenance.tool.name == "RDKit"
    assert record.provenance.tool.version
    assert len(record.provenance.parameters["pose_sha256"]) == 1
    assert service.get(record.validation_id) == record
    assert service.list_runs() == [record]


@pytest.mark.parametrize("changed", ["reference", "pose"])
def test_changed_input_cannot_produce_a_verdict(replay, changed):  # type: ignore[no-untyped-def]
    service, _, _, pose_path, _ = replay
    target = (
        service._ligand_store.content_path(REFERENCE_ID) if changed == "reference" else pose_path
    )
    target.write_bytes(target.read_bytes() + b"\n")
    with pytest.raises(AnkoraDomainError) as failure:
        service.validate(
            RedockingValidationRequest(
                source_kind="vina_job", source_id="job", reference_ligand_id=REFERENCE_ID
            )
        )
    assert failure.value.code == "REDOCKING_INPUT_HASH_MISMATCH"
    assert service.list_runs() == []


@pytest.mark.parametrize("status", ["running", "failed", "canceled"])
def test_unfinished_results_are_not_validation_inputs(replay, status):  # type: ignore[no-untyped-def]
    service, job, _, _, _ = replay
    job.status = status
    with pytest.raises(AnkoraDomainError) as failure:
        service.references("vina_job", "job")
    assert failure.value.code == "REDOCKING_SOURCE_NOT_COMPLETE"
    assert service.list_runs() == []


def test_reference_listing_and_measurement_require_the_original_frame(replay):  # type: ignore[no-untyped-def]
    service, _, _, _, receptor = replay
    page = service.references("vina_job", "job", offset=0, limit=1)
    assert page.total == 1
    assert page.references[0].ligand_id == REFERENCE_ID
    assert service.references("vina_job", "job", offset=1, limit=1).references == []
    receptor.source_artifact_id = "duplicate-import"
    assert service.references("vina_job", "job").total == 1
    receptor.source_artifact_id = "other-structure"
    assert service.references("vina_job", "job").total == 0
    with pytest.raises(AnkoraDomainError) as failure:
        service.validate(
            RedockingValidationRequest(
                source_kind="vina_job", source_id="job", reference_ligand_id=REFERENCE_ID
            )
        )
    assert failure.value.code == "REDOCKING_REFERENCE_FRAME_MISMATCH"
    assert service.list_runs() == []


def test_reference_store_is_project_scoped(tmp_path):  # type: ignore[no-untyped-def]
    first = LigandArtifactStore(tmp_path, "default")
    second = LigandArtifactStore(tmp_path, "another-project")
    record = reference_record()
    first.create(REFERENCE_ID, (FIXTURES / "redocking_7aqf_rv2_crystal.sdf").read_bytes(), record)
    assert len(first.list_crystallographic_records()) == 1
    assert second.list_crystallographic_records() == []


@pytest.mark.parametrize("invalid", ["local", "no_3d", "no_locator"])
def test_derived_or_noncrystal_references_are_rejected(replay, monkeypatch, invalid):  # type: ignore[no-untyped-def]
    from ankora_backend.schemas.ligands import LigandSource

    service, _, reference, _, _ = replay
    if invalid == "local":
        reference.artifact.source = LigandSource.LOCAL
    elif invalid == "no_3d":
        reference.inspection.has_3d_coordinates = False
    else:
        reference.artifact.locator = None
    monkeypatch.setattr(service._ligand_store, "load_record", lambda _: reference)
    with pytest.raises(AnkoraDomainError) as failure:
        service.validate(
            RedockingValidationRequest(
                source_kind="vina_job",
                source_id="job",
                reference_ligand_id=REFERENCE_ID,
            )
        )
    assert failure.value.code == "REDOCKING_REFERENCE_FRAME_MISMATCH"
    assert service.list_runs() == []


def test_no_poses_produces_no_validation(replay):  # type: ignore[no-untyped-def]
    service, job, _, _, _ = replay
    job.poses = []
    with pytest.raises(AnkoraDomainError) as failure:
        service.validate(
            RedockingValidationRequest(
                source_kind="vina_job",
                source_id="job",
                reference_ligand_id=REFERENCE_ID,
            )
        )
    assert failure.value.code == "REDOCKING_NO_POSES"
    assert service.list_runs() == []


def test_references_route_precedes_record_id_and_roundtrips_validation(
    replay, monkeypatch, tmp_path
):  # type: ignore[no-untyped-def]
    service = replay[0]
    monkeypatch.setenv("ANKORA_DATA_DIR", str(tmp_path / "api"))
    monkeypatch.setattr(
        RedockingValidationService, "from_environment", classmethod(lambda _: service)
    )
    with TestClient(create_app()) as client:
        url = "/api/v1/validation/redocking"
        response = client.get(
            url + "/references",
            params={
                "source_kind": "vina_job",
                "source_id": "job",
            },
        )
        assert response.status_code == 200
        assert response.json()["references"][0]["ligand_id"] == REFERENCE_ID
        for invalid in (0, -1, 21):
            assert (
                client.post(
                    url,
                    json={
                        "source_kind": "vina_job",
                        "source_id": "job",
                        "reference_ligand_id": REFERENCE_ID,
                        "threshold_angstrom": invalid,
                    },
                ).status_code
                == 422
            )
        assert service.list_runs() == []
        saved = client.post(
            url,
            json={
                "source_kind": "vina_job",
                "source_id": "job",
                "reference_ligand_id": REFERENCE_ID,
            },
        )
        assert saved.status_code == 201
        assert client.get(url).json() == [saved.json()]
        assert client.get(url + "/" + saved.json()["validation_id"]).json() == saved.json()
