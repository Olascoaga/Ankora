"""Service tests for a single prepared ligand docking job.

Every receptor, ligand, command result, and score here is synthetic. Real Vina
execution is captured separately as Windows validation evidence.
"""

import threading
import time
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path

import pytest

from ankora_backend.adapters.engines.vina import VinaInstallation
from ankora_backend.execution.cancellable_subprocess import CancellableToolExecution
from ankora_backend.persistence.binding_site_store import BindingSiteArtifactStore
from ankora_backend.persistence.docking_store import DockingArtifactStore
from ankora_backend.persistence.ligand_store import LigandArtifactStore
from ankora_backend.persistence.receptor_store import ReceptorArtifactStore
from ankora_backend.schemas.binding_sites import (
    BindingBox,
    BindingSiteRecord,
    BindingSiteRequest,
    BindingSiteSource,
)
from ankora_backend.schemas.docking import (
    DockingJobStatus,
    VinaBatchDockingParameters,
    VinaBatchDockingRequest,
    VinaBatchLigandResult,
    VinaDockingParameters,
    VinaDockingRequest,
)
from ankora_backend.schemas.ligand_library_preparation import LigandPreparationStatus
from ankora_backend.schemas.ligands import (
    ApplyLigandLibraryFilterRequest,
    GenerateLigandConformerRequest,
    LigandChargeModel,
    LigandPdbqtArtifact,
    LigandPdbqtRecord,
    PrepareLigandPdbqtRequest,
)
from ankora_backend.schemas.provenance import ProvenanceEvent, ToolIdentity
from ankora_backend.schemas.receptors import (
    ComponentAction,
    ProtonationSettings,
    ReceptorOutputArtifact,
    ReceptorOutputStage,
    ReceptorPreparationRecord,
    ReceptorPreparationRequest,
    ReceptorPreparationStatus,
)
from ankora_backend.services import vina_docking as docking_module
from ankora_backend.services.ligand_filtering import apply_library_filters
from ankora_backend.services.ligand_import import import_local_ligand_library
from ankora_backend.services.ligand_minimization import generate_ligand_conformer
from ankora_backend.services.ligand_preparation import prepare_ligand_pdbqt
from ankora_backend.services.vina_docking import VinaDockingService

SYNTHETIC_RECEPTOR = b"REMARK synthetic receptor PDBQT\n"
SYNTHETIC_LIGAND = b"REMARK synthetic ligand PDBQT\nROOT\nENDROOT\nTORSDOF 0\n"
SYNTHETIC_POSES = (
    b"MODEL 1\nREMARK VINA RESULT: -6.500 0.000 0.000\n"
    b"ATOM      1  C   LIG A   1       0.000   0.000   0.000  0.00  0.00    +0.000 C\n"
    b"ENDMDL\n"
    b"MODEL 2\nREMARK VINA RESULT: -6.100 1.200 1.800\n"
    b"ATOM      1  C   LIG A   1       1.000   0.000   0.000  0.00  0.00    +0.000 C\n"
    b"ENDMDL\n"
)


def _provenance(event_id: str) -> ProvenanceEvent:
    return ProvenanceEvent(
        event_id=event_id,
        event_type="synthetic_fixture",
        timestamp=datetime.now(UTC),
        tool=ToolIdentity(name="synthetic test fixture", version="1"),
    )


def _service(tmp_path: Path) -> tuple[VinaDockingService, VinaDockingRequest]:
    receptor_store = ReceptorArtifactStore(tmp_path)
    ligand_store = LigandArtifactStore(tmp_path)
    binding_store = BindingSiteArtifactStore(tmp_path)
    docking_store = DockingArtifactStore(tmp_path)
    now = datetime.now(UTC)

    receptor_id = receptor_store.new_receptor_id()
    receptor_store.create_receptor(receptor_id)
    receptor_store.write_bytes(receptor_id, "receptor.pdbqt", SYNTHETIC_RECEPTOR)
    receptor_output = ReceptorOutputArtifact(
        artifact_id=f"{receptor_id}-pdbqt",
        stage=ReceptorOutputStage.PDBQT,
        filename="receptor.pdbqt",
        format="pdbqt",
        sha256=sha256(SYNTHETIC_RECEPTOR).hexdigest(),
        size_bytes=len(SYNTHETIC_RECEPTOR),
        created_at=now,
        content_url="/synthetic/receptor",
    )
    receptor_store.save_record(
        ReceptorPreparationRecord(
            receptor_id=receptor_id,
            source_artifact_id="synthetic-source",
            created_at=now,
            status=ReceptorPreparationStatus.DOCKING_READY,
            decisions=ReceptorPreparationRequest(
                selected_chains=["A"],
                water_action=ComponentAction.REMOVE,
                component_decisions=[],
                issue_decisions=[],
                protonation=ProtonationSettings(enabled=True),
                generate_pdbqt=True,
            ),
            outputs=[receptor_output],
            warnings=[],
            provenance=[],
            display_output_artifact_id=receptor_output.artifact_id,
        )
    )

    ligand_id = ligand_store.new_ligand_id()
    ligand_directory = tmp_path / "projects" / "default" / "original" / "ligands" / ligand_id
    ligand_directory.mkdir(parents=True)
    preparation_id = ligand_store.new_preparation_id()
    ligand_artifact = LigandPdbqtArtifact(
        preparation_id=preparation_id,
        ligand_id=ligand_id,
        conformer_id="synthetic-conformer",
        filename="ligand.pdbqt",
        format="pdbqt",
        sha256=sha256(SYNTHETIC_LIGAND).hexdigest(),
        size_bytes=len(SYNTHETIC_LIGAND),
        created_at=now,
    )
    ligand_store.create_pdbqt(
        ligand_id,
        preparation_id,
        SYNTHETIC_LIGAND,
        LigandPdbqtRecord(
            artifact=ligand_artifact,
            charge_model=LigandChargeModel.GASTEIGER,
            tool=ToolIdentity(name="synthetic Meeko", version="0"),
            command=["synthetic"],
            stdout="",
            stderr="",
            provenance=_provenance("synthetic-ligand-preparation"),
            content_url="/synthetic/ligand",
        ),
    )

    binding_id = binding_store.new_binding_site_id()
    box = BindingBox(
        center_x=0,
        center_y=0,
        center_z=0,
        size_x=20,
        size_y=20,
        size_z=20,
    )
    binding_store.save_record(
        BindingSiteRecord(
            binding_site_id=binding_id,
            receptor_id=receptor_id,
            source_artifact_id=receptor_output.artifact_id,
            created_at=now,
            decisions=BindingSiteRequest(source=BindingSiteSource.MANUAL, manual_box=box),
            box=box,
            warnings=[],
            provenance=[_provenance("synthetic-binding-site")],
        )
    )
    service = VinaDockingService(
        docking_store=docking_store,
        receptor_store=receptor_store,
        binding_site_store=binding_store,
        ligand_store=ligand_store,
    )
    request = VinaDockingRequest(
        receptor_id=receptor_id,
        binding_site_id=binding_id,
        ligand_id=ligand_id,
        ligand_preparation_id=preparation_id,
        parameters=VinaDockingParameters(cpu_threads=4, seed=12345),
        acknowledge_inputs_and_scoring=True,
    )
    return service, request


def _wait_for_terminal(service: VinaDockingService, job_id: str):  # type: ignore[no-untyped-def]
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        record = service.get(job_id)
        if record.status in {
            DockingJobStatus.COMPLETED,
            DockingJobStatus.CANCELED,
            DockingJobStatus.FAILED,
        }:
            return record
        time.sleep(0.01)
    raise AssertionError("synthetic docking job did not terminate")


def _wait_for_batch_terminal(
    service: VinaDockingService, batch_id: str
):  # type: ignore[no-untyped-def]
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        record = service.get_batch(batch_id)
        if record.status in {
            DockingJobStatus.COMPLETED,
            DockingJobStatus.CANCELED,
            DockingJobStatus.FAILED,
        }:
            return record
        time.sleep(0.01)
    raise AssertionError("synthetic docking batch did not terminate")


def _batch_request(
    tmp_path: Path,
    service: VinaDockingService,
    single_request: VinaDockingRequest,
    monkeypatch: pytest.MonkeyPatch,
) -> VinaBatchDockingRequest:
    store = LigandArtifactStore(tmp_path)
    library = import_local_ligand_library(
        content=b"CCO synthetic_alpha\nCCN synthetic_beta\n",
        filename="synthetic_docking_library.smi",
        store=store,
    )
    filter_run = apply_library_filters(
        library_id=library.artifact.library_id,
        request=ApplyLigandLibraryFilterRequest(acknowledge_selection=True),
        store=store,
    )

    def synthetic_meeko(**kwargs: object) -> tuple[object, str]:
        output_path = kwargs["output_pdbqt_path"]
        assert isinstance(output_path, Path)
        output_path.write_bytes(SYNTHETIC_LIGAND)
        from ankora_backend.execution.subprocess_runner import ToolExecution

        return ToolExecution(
            command=["synthetic-meeko"], exit_code=0, stdout="", stderr=""
        ), "0.7.1"

    monkeypatch.setattr(
        "ankora_backend.services.ligand_preparation.execute_meeko_ligand",
        synthetic_meeko,
    )
    for ligand_id in filter_run.selected_ligand_ids:
        ligand = store.load_record(ligand_id)
        assert ligand.state is not None
        conformer = generate_ligand_conformer(
            ligand_id=ligand_id,
            request=GenerateLigandConformerRequest(
                acknowledge_current_chemical_state=True,
                state_id=ligand.state.state_id,
                random_seed=991,
            ),
            store=store,
        )
        prepare_ligand_pdbqt(
            ligand_id=ligand_id,
            conformer_id=conformer.artifact.conformer_id,
            request=PrepareLigandPdbqtRequest(),
            store=store,
        )

    return VinaBatchDockingRequest(
        receptor_id=single_request.receptor_id,
        binding_site_id=single_request.binding_site_id,
        library_id=library.artifact.library_id,
        filter_run_id=filter_run.artifact.filter_run_id,
        parameters=VinaBatchDockingParameters(
            total_cpu_threads=6,
            parallel_ligands=2,
            seed=45678,
            num_modes=2,
        ),
        acknowledge_inputs_and_scoring=True,
    )


def test_vina_job_preserves_raw_output_and_pose_artifacts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service, request = _service(tmp_path)
    monkeypatch.setattr(
        docking_module,
        "probe_vina",
        lambda: VinaInstallation(executable="synthetic-vina.exe", version="1.2.7"),
    )

    def synthetic_execution(**kwargs):  # type: ignore[no-untyped-def]
        kwargs["output_path"].write_bytes(SYNTHETIC_POSES)
        return CancellableToolExecution(
            command=["synthetic-vina.exe", "--synthetic"],
            exit_code=0,
            stdout="synthetic stdout",
            stderr="synthetic stderr",
            canceled=False,
            timed_out=False,
        )

    monkeypatch.setattr(docking_module, "execute_vina", synthetic_execution)
    queued = service.start(request)
    record = _wait_for_terminal(service, queued.job_id)
    service.shutdown()

    assert record.status is DockingJobStatus.COMPLETED
    assert record.tool.version == "1.2.7"
    assert record.request.parameters.cpu_threads == 4
    assert record.request.parameters.seed == 12345
    assert record.execution is not None
    assert record.execution.stdout == "synthetic stdout"
    assert [pose.affinity_kcal_mol for pose in record.poses] == [-6.5, -6.1]
    assert record.provenance is not None
    assert record.provenance.command == ["synthetic-vina.exe", "--synthetic"]
    first = record.poses[0].artifact
    assert service.pose_content_path(record.job_id, first.artifact_id).read_bytes().startswith(
        b"MODEL 1\n"
    )


def test_vina_job_can_be_canceled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service, request = _service(tmp_path)
    monkeypatch.setattr(
        docking_module,
        "probe_vina",
        lambda: VinaInstallation(executable="synthetic-vina.exe", version="1.2.7"),
    )

    def cancelable_execution(**kwargs):  # type: ignore[no-untyped-def]
        event = kwargs["cancel_event"]
        assert event.wait(timeout=2)
        return CancellableToolExecution(
            command=["synthetic-vina.exe"],
            exit_code=1,
            stdout="partial synthetic output",
            stderr="",
            canceled=True,
            timed_out=False,
        )

    monkeypatch.setattr(docking_module, "execute_vina", cancelable_execution)
    queued = service.start(request)
    service.cancel(queued.job_id)
    record = _wait_for_terminal(service, queued.job_id)
    service.shutdown()

    assert record.status is DockingJobStatus.CANCELED
    assert record.execution is not None
    assert record.execution.canceled is True
    assert record.execution.stdout == "partial synthetic output"
    assert record.poses == []


def test_vina_library_batch_coordinates_cpu_and_preserves_source_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service, single_request = _service(tmp_path)
    request = _batch_request(tmp_path, service, single_request, monkeypatch)
    monkeypatch.setattr(
        docking_module,
        "probe_vina",
        lambda: VinaInstallation(executable="synthetic-vina.exe", version="1.2.7"),
    )
    barrier = threading.Barrier(2)
    observed_cpu_threads: list[int] = []

    def parallel_execution(**kwargs):  # type: ignore[no-untyped-def]
        observed_cpu_threads.append(kwargs["parameters"].cpu_threads)
        barrier.wait(timeout=2)
        kwargs["output_path"].write_bytes(SYNTHETIC_POSES)
        return CancellableToolExecution(
            command=["synthetic-vina.exe", "--cpu", "3"],
            exit_code=0,
            stdout="synthetic batch stdout",
            stderr="",
            canceled=False,
            timed_out=False,
        )

    monkeypatch.setattr(docking_module, "execute_vina", parallel_execution)
    queued = service.start_batch(request)
    duplicate = service.start_batch(request)
    assert duplicate.batch_id == queued.batch_id
    record = _wait_for_batch_terminal(service, queued.batch_id)
    progress = service.get_batch_progress(queued.batch_id, after_revision=0)
    unchanged = service.get_batch_progress(
        queued.batch_id, after_revision=progress.revision
    )
    latest = service.latest_batch(
        library_id=request.library_id,
        receptor_id=request.receptor_id,
        binding_site_id=request.binding_site_id,
    )
    service.shutdown()

    assert record.status is DockingJobStatus.COMPLETED
    assert record.selected_count == 2
    assert record.worker_count == 2
    assert record.threads_per_ligand == 3
    assert observed_cpu_threads == [3, 3]
    assert latest.batch_id == queued.batch_id
    assert progress.revision > 0
    assert len(progress.entries) == 2
    assert unchanged.entries == []
    assert [entry.source_index for entry in record.entries] == [0, 1]
    assert [entry.status for entry in record.entries] == [
        DockingJobStatus.COMPLETED,
        DockingJobStatus.COMPLETED,
    ]
    assert record.completed_count == 2
    assert record.succeeded_count == 2
    assert record.failed_count == 0
    assert all(entry.poses[0].affinity_kcal_mol == -6.5 for entry in record.entries)
    assert all(entry.preparation_initial_energy_kcal_mol is not None for entry in record.entries)
    assert all(entry.preparation_energy_kcal_mol is not None for entry in record.entries)
    for entry in record.entries:
        assert entry.preparation_initial_energy_kcal_mol is not None
        assert entry.preparation_energy_kcal_mol is not None
        assert entry.preparation_energy_kcal_mol < entry.preparation_initial_energy_kcal_mol
    historical_payload = record.entries[0].model_dump()
    historical_payload.pop("preparation_initial_energy_kcal_mol")
    assert (
        VinaBatchLigandResult.model_validate(
            historical_payload
        ).preparation_initial_energy_kcal_mol
        is None
    )
    first = record.entries[0].poses[0].artifact
    assert service.batch_pose_content_path(
        record.batch_id, record.entries[0].ligand_id, first.artifact_id
    ).read_bytes().startswith(b"MODEL 1\n")


def test_vina_library_batch_accounts_for_an_unprepared_manifest_entry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service, single_request = _service(tmp_path)
    request = _batch_request(tmp_path, service, single_request, monkeypatch)
    store = LigandArtifactStore(tmp_path)
    filter_run = store.load_filter_run(request.library_id, request.filter_run_id)
    unavailable_id = filter_run.selected_ligand_ids[-1]
    preparation = store.load_preparation_status(request.library_id)
    store.upsert_preparation_entry(
        request.library_id,
        preparation.entries[unavailable_id].model_copy(
            update={
                "status": LigandPreparationStatus.NONCONVERGED,
                "pdbqt_preparation_id": None,
                "updated_at": datetime.now(UTC),
            }
        ),
    )
    monkeypatch.setattr(
        docking_module,
        "probe_vina",
        lambda: VinaInstallation(executable="synthetic-vina.exe", version="1.2.7"),
    )
    executed_ligands = 0

    def successful_execution(**kwargs):  # type: ignore[no-untyped-def]
        nonlocal executed_ligands
        executed_ligands += 1
        kwargs["output_path"].write_bytes(SYNTHETIC_POSES)
        return CancellableToolExecution(
            command=["synthetic-vina.exe"],
            exit_code=0,
            stdout="",
            stderr="",
            canceled=False,
            timed_out=False,
        )

    monkeypatch.setattr(docking_module, "execute_vina", successful_execution)
    queued = service.start_batch(request)
    record = _wait_for_batch_terminal(service, queued.batch_id)
    service.shutdown()

    assert executed_ligands == 1
    assert record.status is DockingJobStatus.COMPLETED
    assert record.selected_count == 2
    assert record.completed_count == 2
    assert record.succeeded_count == 1
    assert record.failed_count == 1
    unavailable = next(entry for entry in record.entries if entry.ligand_id == unavailable_id)
    assert unavailable.failure is not None
    assert unavailable.failure.code == "DOCKING_LIGAND_NOT_PREPARED"


def test_vina_library_batch_isolates_one_ligand_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service, single_request = _service(tmp_path)
    request = _batch_request(tmp_path, service, single_request, monkeypatch)
    monkeypatch.setattr(
        docking_module,
        "probe_vina",
        lambda: VinaInstallation(executable="synthetic-vina.exe", version="1.2.7"),
    )
    calls = 0
    calls_lock = threading.Lock()

    def isolated_execution(**kwargs):  # type: ignore[no-untyped-def]
        nonlocal calls
        with calls_lock:
            calls += 1
            should_fail = calls == 1
        if not should_fail:
            kwargs["output_path"].write_bytes(SYNTHETIC_POSES)
        return CancellableToolExecution(
            command=["synthetic-vina.exe"],
            exit_code=1 if should_fail else 0,
            stdout="",
            stderr="synthetic isolated failure" if should_fail else "",
            canceled=False,
            timed_out=False,
        )

    monkeypatch.setattr(docking_module, "execute_vina", isolated_execution)
    queued = service.start_batch(request)
    record = _wait_for_batch_terminal(service, queued.batch_id)
    service.shutdown()

    assert record.status is DockingJobStatus.COMPLETED
    assert record.completed_count == 2
    assert record.succeeded_count == 1
    assert record.failed_count == 1
    failed = next(
        entry for entry in record.entries if entry.status is DockingJobStatus.FAILED
    )
    assert failed.failure is not None
    assert failed.failure.code == "VINA_EXECUTION_FAILED"
    completed = next(
        entry for entry in record.entries if entry.status is DockingJobStatus.COMPLETED
    )
    assert completed.poses


def test_vina_library_batch_cancels_running_and_queued_ligands(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service, single_request = _service(tmp_path)
    request = _batch_request(tmp_path, service, single_request, monkeypatch)
    monkeypatch.setattr(
        docking_module,
        "probe_vina",
        lambda: VinaInstallation(executable="synthetic-vina.exe", version="1.2.7"),
    )

    def cancelable_execution(**kwargs):  # type: ignore[no-untyped-def]
        event = kwargs["cancel_event"]
        assert event.wait(timeout=2)
        return CancellableToolExecution(
            command=["synthetic-vina.exe"],
            exit_code=1,
            stdout="partial batch output",
            stderr="",
            canceled=True,
            timed_out=False,
        )

    monkeypatch.setattr(docking_module, "execute_vina", cancelable_execution)
    queued = service.start_batch(request)
    service.cancel_batch(queued.batch_id)
    record = _wait_for_batch_terminal(service, queued.batch_id)
    service.shutdown()

    assert record.status is DockingJobStatus.CANCELED
    assert record.canceled_count == 2
    assert record.completed_count == 2
    assert all(entry.status is DockingJobStatus.CANCELED for entry in record.entries)


def test_latest_batch_prefers_preserved_results_to_a_later_empty_cancel(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service, single_request = _service(tmp_path)
    request = _batch_request(tmp_path, service, single_request, monkeypatch)
    monkeypatch.setattr(
        docking_module,
        "probe_vina",
        lambda: VinaInstallation(executable="synthetic-vina.exe", version="1.2.7"),
    )

    def successful_execution(**kwargs):  # type: ignore[no-untyped-def]
        kwargs["output_path"].write_bytes(SYNTHETIC_POSES)
        return CancellableToolExecution(
            command=["synthetic-vina.exe"],
            exit_code=0,
            stdout="",
            stderr="",
            canceled=False,
            timed_out=False,
        )

    monkeypatch.setattr(docking_module, "execute_vina", successful_execution)
    completed = service.start_batch(request)
    _wait_for_batch_terminal(service, completed.batch_id)

    canceled = service.start_batch(request)
    service.cancel_batch(canceled.batch_id)
    canceled_record = _wait_for_batch_terminal(service, canceled.batch_id)
    latest = service.latest_batch(
        library_id=request.library_id,
        receptor_id=request.receptor_id,
        binding_site_id=request.binding_site_id,
    )
    service.shutdown()

    assert canceled_record.status is DockingJobStatus.CANCELED
    assert canceled_record.succeeded_count == 0
    assert latest.batch_id == completed.batch_id
    assert latest.succeeded_count == 2
