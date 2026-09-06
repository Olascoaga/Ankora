"""Incremental campaign persistence and real 10,000-row pagination."""

import json
import sqlite3
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from unittest.mock import patch
from uuid import UUID, uuid4

from ankora_backend.persistence.autodock4_store import AutoDock4JobStore
from ankora_backend.persistence.autodock_gpu_store import AutoDockGpuJobStore
from ankora_backend.persistence.docking_store import DockingArtifactStore
from ankora_backend.persistence.ligand_store import LigandArtifactStore
from ankora_backend.schemas.binding_sites import BindingBox
from ankora_backend.schemas.docking import (
    DockingJobPhase,
    DockingJobStatus,
    DockingPoseArtifact,
    DockingPoseResult,
    VinaBatchDockingParameters,
    VinaBatchDockingRecord,
    VinaBatchDockingRequest,
    VinaBatchLigandResult,
)
from ankora_backend.schemas.provenance import ToolIdentity
from ankora_backend.services.result_catalog import ResultCatalogService


def _ligand_id(index: int) -> str:
    return str(UUID(int=index + 1))


def _pose(index: int, score: float) -> DockingPoseResult:
    return DockingPoseResult(
        mode=1,
        affinity_kcal_mol=score,
        rmsd_lower_bound_angstrom=0,
        rmsd_upper_bound_angstrom=0,
        artifact=DockingPoseArtifact(
            artifact_id=f"synthetic-pose-{index}",
            mode=1,
            filename="pose_1.pdbqt",
            format="pdbqt",
            sha256=f"{index + 1:064x}",
            size_bytes=1,
            content_url=f"/synthetic/{index}",
        ),
    )


def _batch(
    count: int,
    *,
    batch_id: str | None = None,
    running: bool = False,
) -> VinaBatchDockingRecord:
    scored = {1: -7.0, 5_000: -8.0, 9_999: -10.0}
    entries = [
        VinaBatchLigandResult(
            ligand_id=_ligand_id(index),
            parent_compound_id=_ligand_id(index),
            chemical_state_id=f"synthetic-state-{index}",
            chemical_state_formal_charge=0,
            source_index=index,
            name=f"Synthetic compound {index}",
            canonical_smiles=f"C{'C' * (index % 4)}",
            status=(DockingJobStatus.RUNNING if running else DockingJobStatus.COMPLETED),
            phase=(DockingJobPhase.DOCKING if running else DockingJobPhase.COMPLETE),
            poses=(
                []
                if running or index not in scored
                else [_pose(index, scored[index])]
            ),
        )
        for index in range(count)
    ]
    return VinaBatchDockingRecord(
        batch_id=batch_id or str(uuid4()),
        status=DockingJobStatus.RUNNING if running else DockingJobStatus.COMPLETED,
        phase=DockingJobPhase.DOCKING if running else DockingJobPhase.COMPLETE,
        created_at=datetime(2026, 9, 6, tzinfo=UTC),
        request=VinaBatchDockingRequest(
            receptor_id="synthetic-receptor",
            binding_site_id="synthetic-site",
            library_id="synthetic-library",
            filter_run_id="synthetic-filter",
            parameters=VinaBatchDockingParameters(),
            acknowledge_inputs_and_scoring=True,
        ),
        tool=ToolIdentity(name="Synthetic Vina", version="1.2.7-test"),
        receptor_output_artifact_id="synthetic-receptor-pdbqt",
        receptor_sha256="a" * 64,
        selection_manifest_artifact_id="synthetic-selection",
        selection_manifest_sha256="b" * 64,
        selected_count=count,
        worker_count=1,
        threads_per_ligand=1,
        completed_count=0 if running else count,
        succeeded_count=0 if running else count,
        failed_count=0,
        canceled_count=0,
        entries=entries,
    )


def _legacy_directory(root: Path, record: VinaBatchDockingRecord) -> Path:
    directory = (
        root
        / "projects"
        / "default"
        / "results"
        / "docking_batches"
        / record.batch_id
    )
    directory.mkdir(parents=True)
    (directory / "record.json").write_text(
        record.model_dump_json(indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    (directory / "retained-scientific-output.bin").write_bytes(b"unchanged evidence")
    return directory


class _BindingSites:
    def load_record(self, _binding_site_id: str) -> object:
        box = BindingBox(
            center_x=0,
            center_y=0,
            center_z=0,
            size_x=20,
            size_y=20,
            size_z=20,
        )
        return type("_Record", (), {"box": box})()


def test_legacy_migration_adds_only_the_index_and_preserves_existing_bytes(
    tmp_path: Path,
) -> None:
    record = _batch(3)
    directory = _legacy_directory(tmp_path, record)
    before = {
        path.name: (path.read_bytes(), sha256(path.read_bytes()).hexdigest())
        for path in directory.iterdir()
    }

    store = DockingArtifactStore(tmp_path)
    loaded = store.load_batch_record(record.batch_id)

    assert loaded == record
    assert (directory / "batch_state.sqlite3").is_file()
    for name, (content, digest) in before.items():
        path = directory / name
        assert path.read_bytes() == content
        assert sha256(path.read_bytes()).hexdigest() == digest


def test_one_ligand_update_changes_one_database_row_not_the_batch_json(
    tmp_path: Path,
) -> None:
    record = _batch(3, running=True)
    directory = _legacy_directory(tmp_path, record)
    original_json = (directory / "record.json").read_bytes()
    store = DockingArtifactStore(tmp_path)
    store.load_batch_overview(record.batch_id)
    database_path = directory / "batch_state.sqlite3"
    with sqlite3.connect(database_path) as database:
        before = dict(
            database.execute("SELECT ligand_id, payload_json FROM entries").fetchall()
        )

    ligand_id = _ligand_id(1)
    entry = store.load_batch_entry(record.batch_id, ligand_id)
    assert entry is not None
    store.update_batch_entry(
        record.batch_id,
        entry.model_copy(
            update={
                "status": DockingJobStatus.COMPLETED,
                "phase": DockingJobPhase.COMPLETE,
                "poses": [_pose(1, -7.5)],
            }
        ),
    )

    with sqlite3.connect(database_path) as database:
        after = dict(
            database.execute("SELECT ligand_id, payload_json FROM entries").fetchall()
        )
    changed = [key for key in before if before[key] != after[key]]
    summary = store.load_batch_summary(record.batch_id)
    assert changed == [ligand_id]
    assert summary["revision"] == 1
    assert summary["completed_count"] == 1
    assert summary["succeeded_count"] == 1
    assert (directory / "record.json").read_bytes() == original_json


def test_unknown_index_schema_fails_closed(tmp_path: Path) -> None:
    record = _batch(2)
    directory = _legacy_directory(tmp_path, record)
    store = DockingArtifactStore(tmp_path)
    store.load_batch_overview(record.batch_id)
    with sqlite3.connect(directory / "batch_state.sqlite3") as database:
        database.execute(
            "UPDATE metadata SET value = 'future' WHERE key = 'schema_version'"
        )
        database.commit()

    with patch.object(
        store._batch_state,  # type: ignore[attr-defined]
        "migrate",
        side_effect=AssertionError("existing incompatible state was rebuilt silently"),
    ):
        try:
            store.load_batch_overview(record.batch_id)
        except ValueError as error:
            assert "Unsupported incremental batch-state schema: future" in str(error)
        else:
            raise AssertionError("An unknown index schema must fail closed")


def test_10_000_entry_campaign_is_filtered_ranked_and_paginated_in_sql(
    tmp_path: Path,
) -> None:
    """Explicitly synthetic load contract for Ankora's current local limit."""
    record = _batch(10_000)
    directory = _legacy_directory(tmp_path, record)
    original_record_sha256 = sha256((directory / "record.json").read_bytes()).hexdigest()
    docking = DockingArtifactStore(tmp_path)
    service = ResultCatalogService(
        docking_store=docking,
        autodock4_store=AutoDock4JobStore(tmp_path),
        autodock_gpu_store=AutoDockGpuJobStore(tmp_path),
        binding_site_store=_BindingSites(),  # type: ignore[arg-type]
        ligand_store=LigandArtifactStore(tmp_path),
    )

    with patch.object(
        docking,
        "load_batch_record",
        side_effect=AssertionError("pagination hydrated the complete campaign"),
    ):
        first_page = service.list_compounds(
            f"vina_batch:{record.batch_id}", offset=0, limit=2
        )
        searched = service.list_compounds(
            f"vina_batch:{record.batch_id}",
            offset=0,
            limit=25,
            search="compound 9999",
        )
        completed = service.list_compounds(
            f"vina_batch:{record.batch_id}",
            offset=9_998,
            limit=2,
            status="completed",
        )

    assert first_page.total == 10_000
    assert [row.source_index for row in first_page.rows] == [9_999, 5_000]
    assert searched.total == 1
    assert searched.rows[0].source_index == 9_999
    assert len(completed.rows) == 2
    assert (completed.offset, completed.limit) == (9_998, 2)
    with sqlite3.connect(directory / "batch_state.sqlite3") as database:
        assert database.execute("SELECT COUNT(*) FROM entries").fetchone()[0] == 10_000
    assert sha256((directory / "record.json").read_bytes()).hexdigest() == (
        original_record_sha256
    )
    assert len(json.dumps(first_page.model_dump(mode="json"))) < 20_000
