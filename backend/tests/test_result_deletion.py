"""Campaign removal is complete, recoverable, and never partial by design."""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import cast
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from ankora_backend.api.app import create_app
from ankora_backend.domain.errors import AnkoraDomainError
from ankora_backend.schemas.results_catalog import (
    CatalogEntry,
    TrashedResultCampaign,
    TrashResultCampaignsRequest,
    TrashResultCampaignsResponse,
)
from ankora_backend.services.result_catalog import ResultCatalogService
from ankora_backend.services.result_deletion import ResultDeletionService


class _Catalog:
    def __init__(self, entries: list[CatalogEntry]) -> None:
        self._entries = {entry.catalog_id: entry for entry in entries}

    def get_campaign(self, catalog_id: str) -> CatalogEntry:
        try:
            return self._entries[catalog_id]
        except KeyError as error:
            raise AnkoraDomainError(
                code="RESULT_CATALOG_NOT_FOUND",
                stage="results_catalog",
                message="No result exists for this identifier.",
                status_code=404,
            ) from error


def _entry(engine_key: str, record_id: str, *, status: str = "completed") -> CatalogEntry:
    return CatalogEntry(
        catalog_id=f"{engine_key}:{record_id}",
        engine_key=engine_key,
        record_id=record_id,
        mode="screening" if engine_key.endswith("batch") else "single_ligand",
        scoring_family="vina" if engine_key.startswith("vina") else "autodock4",
        engine_label=(
            "AutoDock Vina 1.2.7"
            if engine_key.startswith("vina")
            else "AutoDock 4.2.6 · CPU"
        ),
        engine_version="1.2.7" if engine_key.startswith("vina") else "4.2.6",
        status=status,
        created_at=datetime(2026, 8, 27, tzinfo=UTC),
        receptor_id="receptor-1",
        binding_site_id="site-1",
        selected_count=1,
        succeeded_count=1 if status == "completed" else 0,
        failed_count=1 if status == "failed" else 0,
        canceled_count=1 if status == "canceled" else 0,
    )


def _service(root: Path, entries: list[CatalogEntry]) -> ResultDeletionService:
    return ResultDeletionService(
        root=root,
        catalog=cast(ResultCatalogService, _Catalog(entries)),
    )


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=False)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_two_results_and_their_dependent_records_move_together(tmp_path: Path) -> None:
    vina_id = str(uuid4())
    cpu_id = str(uuid4())
    analysis_id = str(uuid4())
    validation_id = str(uuid4())
    export_id = str(uuid4())
    vina = _entry("vina_batch", vina_id)
    cpu = _entry("autodock4_job", cpu_id)
    project = tmp_path / "projects" / "default"

    _write_json(
        project / "results" / "docking_batches" / vina_id / "record.json",
        {"batch_id": vina_id},
    )
    _write_json(
        project / "results" / "autodock4_jobs" / cpu_id / "record.json",
        {"job_id": cpu_id},
    )
    _write_json(
        project / "analysis" / "pose_interactions" / analysis_id / "record.json",
        {"analysis_id": analysis_id, "catalog_id": vina.catalog_id},
    )
    _write_json(
        project / "validation" / "redocking" / validation_id / "record.json",
        {
            "validation_id": validation_id,
            "source_kind": cpu.engine_key,
            "source_id": cpu.record_id,
        },
    )
    _write_json(
        project / "exports" / export_id / "manifest.json",
        {"source_kind": vina.engine_key, "source_id": vina.record_id},
    )
    retained_inputs = [
        project / "derived" / "receptors" / "receptor-1" / "record.json",
        project / "derived" / "ligands" / "ligand-1" / "record.json",
        project / "derived" / "binding_sites" / "site-1" / "record.json",
        project / "derived" / "autogrid_maps" / "map-1" / "record.json",
    ]
    for retained in retained_inputs:
        _write_json(retained, {"synthetic_acceptance_fixture": True})

    response = _service(tmp_path, [vina, cpu]).trash(
        TrashResultCampaignsRequest(
            catalog_ids=[vina.catalog_id, cpu.catalog_id],
            acknowledge_removal=True,
        )
    )

    assert [item.catalog_id for item in response.campaigns] == [
        vina.catalog_id,
        cpu.catalog_id,
    ]
    assert response.interaction_analysis_count == 1
    assert response.redocking_validation_count == 1
    assert response.exports_preserved is True
    assert response.recoverable is True
    assert not (project / "results" / "docking_batches" / vina_id).exists()
    assert not (project / "results" / "autodock4_jobs" / cpu_id).exists()
    assert not (project / "analysis" / "pose_interactions" / analysis_id).exists()
    assert not (project / "validation" / "redocking" / validation_id).exists()
    # Export bundles are standalone evidence and are intentionally preserved.
    assert (project / "exports" / export_id / "manifest.json").is_file()
    assert all(path.is_file() for path in retained_inputs)

    operation = project / "trash" / "result_campaigns" / response.operation_id
    manifest = json.loads((operation / "operation.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "completed"
    assert len(manifest["campaigns"]) == 2
    assert (operation / "campaigns" / "vina_batch" / vina_id).is_dir()
    assert (operation / "campaigns" / "autodock4_job" / cpu_id).is_dir()
    assert (
        operation / "dependencies" / "pose_interactions" / analysis_id
    ).is_dir()
    assert (operation / "dependencies" / "redocking" / validation_id).is_dir()


def test_one_result_moves_as_one_recoverable_operation(tmp_path: Path) -> None:
    record_id = str(uuid4())
    entry = _entry("vina_job", record_id)
    project = tmp_path / "projects" / "default"
    source = project / "results" / "docking" / record_id
    _write_json(
        source / "record.json",
        {"job_id": record_id, "synthetic_acceptance_fixture": True},
    )

    response = _service(tmp_path, [entry]).trash(
        TrashResultCampaignsRequest(
            catalog_ids=[entry.catalog_id],
            acknowledge_removal=True,
        )
    )

    assert [campaign.catalog_id for campaign in response.campaigns] == [
        entry.catalog_id
    ]
    assert response.interaction_analysis_count == 0
    assert response.redocking_validation_count == 0
    assert response.recoverable is True
    assert not source.exists()
    operation = project / "trash" / "result_campaigns" / response.operation_id
    assert (operation / "campaigns" / "vina_job" / record_id).is_dir()
    manifest = json.loads((operation / "operation.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "completed"
    assert [campaign["catalog_id"] for campaign in manifest["campaigns"]] == [
        entry.catalog_id
    ]


@pytest.mark.parametrize("status", ["queued", "running", "cancel_requested"])
def test_an_active_result_blocks_the_complete_group(
    tmp_path: Path, status: str
) -> None:
    completed_id = str(uuid4())
    active_id = str(uuid4())
    completed = _entry("vina_batch", completed_id)
    active = _entry("autodock4_batch", active_id, status=status)
    project = tmp_path / "projects" / "default" / "results"
    _write_json(
        project / "docking_batches" / completed_id / "record.json",
        {"batch_id": completed_id},
    )
    _write_json(
        project / "autodock4_batches" / active_id / "record.json",
        {"batch_id": active_id},
    )

    with pytest.raises(AnkoraDomainError) as captured:
        _service(tmp_path, [completed, active]).trash(
            TrashResultCampaignsRequest(
                catalog_ids=[completed.catalog_id, active.catalog_id],
                acknowledge_removal=True,
            )
        )

    assert captured.value.code == "RESULT_TRASH_ACTIVE"
    assert (project / "docking_batches" / completed_id).is_dir()
    assert (project / "autodock4_batches" / active_id).is_dir()
    assert not (tmp_path / "projects" / "default" / "trash").exists()


def test_acknowledgement_and_unique_selection_are_required(tmp_path: Path) -> None:
    record_id = str(uuid4())
    entry = _entry("vina_job", record_id)
    service = _service(tmp_path, [entry])

    with pytest.raises(AnkoraDomainError) as unacknowledged:
        service.trash(TrashResultCampaignsRequest(catalog_ids=[entry.catalog_id]))
    assert unacknowledged.value.code == "RESULT_TRASH_NOT_ACKNOWLEDGED"

    with pytest.raises(AnkoraDomainError) as duplicated:
        service.trash(
            TrashResultCampaignsRequest(
                catalog_ids=[entry.catalog_id, entry.catalog_id],
                acknowledge_removal=True,
            )
        )
    assert duplicated.value.code == "RESULT_TRASH_DUPLICATE_ID"


def test_the_typed_api_accepts_one_bounded_group(monkeypatch: pytest.MonkeyPatch) -> None:
    record_id = str(uuid4())
    catalog_id = f"vina_batch:{record_id}"
    observed: list[TrashResultCampaignsRequest] = []

    class _Deletion:
        def trash(
            self, request: TrashResultCampaignsRequest
        ) -> TrashResultCampaignsResponse:
            observed.append(request)
            return TrashResultCampaignsResponse(
                operation_id=str(uuid4()),
                trashed_at=datetime(2026, 8, 27, tzinfo=UTC),
                campaigns=[
                    TrashedResultCampaign(
                        catalog_id=catalog_id,
                        engine_label="AutoDock Vina 1.2.7",
                        status="completed",
                    )
                ],
                interaction_analysis_count=0,
                redocking_validation_count=0,
            )

    deletion = _Deletion()
    monkeypatch.setattr(
        ResultDeletionService,
        "from_environment",
        classmethod(lambda _cls: cast(ResultDeletionService, deletion)),
    )

    response = TestClient(create_app()).post(
        "/api/v1/results/campaigns/trash",
        json={"catalog_ids": [catalog_id], "acknowledge_removal": True},
    )

    assert response.status_code == 200
    assert response.json()["campaigns"][0]["catalog_id"] == catalog_id
    assert observed[0].catalog_ids == [catalog_id]
    assert observed[0].acknowledge_removal is True


def test_the_typed_api_executes_real_individual_and_group_operations(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    entries = [
        _entry("vina_job", str(uuid4())),
        _entry("vina_batch", str(uuid4())),
        _entry("autodock4_job", str(uuid4())),
    ]
    project = tmp_path / "projects" / "default" / "results"
    locations = {
        entries[0].catalog_id: project / "docking" / entries[0].record_id,
        entries[1].catalog_id: project / "docking_batches" / entries[1].record_id,
        entries[2].catalog_id: project / "autodock4_jobs" / entries[2].record_id,
    }
    for entry in entries:
        _write_json(
            locations[entry.catalog_id] / "record.json",
            {"record_id": entry.record_id, "synthetic_acceptance_fixture": True},
        )
    deletion = _service(tmp_path, entries)
    monkeypatch.setattr(
        ResultDeletionService,
        "from_environment",
        classmethod(lambda _cls: deletion),
    )
    client = TestClient(create_app())

    individual = client.post(
        "/api/v1/results/campaigns/trash",
        json={
            "catalog_ids": [entries[0].catalog_id],
            "acknowledge_removal": True,
        },
    )
    group = client.post(
        "/api/v1/results/campaigns/trash",
        json={
            "catalog_ids": [entries[1].catalog_id, entries[2].catalog_id],
            "acknowledge_removal": True,
        },
    )

    assert individual.status_code == 200
    assert [row["catalog_id"] for row in individual.json()["campaigns"]] == [
        entries[0].catalog_id
    ]
    assert group.status_code == 200
    assert [row["catalog_id"] for row in group.json()["campaigns"]] == [
        entries[1].catalog_id,
        entries[2].catalog_id,
    ]
    assert all(not path.exists() for path in locations.values())
    assert individual.json()["operation_id"] != group.json()["operation_id"]
