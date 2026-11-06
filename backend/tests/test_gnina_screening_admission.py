"""Synthetic admission tests: no GNINA or Meeko process is executed."""

from pathlib import Path
from types import SimpleNamespace

import pytest
from test_gnina_campaign_link import _BOX, _stub_input_stores
from test_gnina_screening_preflight import one_prepared as one_prepared
from test_gnina_screening_preflight import screening as screening

from ankora_backend.adapters.engines.gnina import GninaInstallation
from ankora_backend.domain.errors import AnkoraDomainError
from ankora_backend.persistence.gnina_screening_store import GninaScreeningStore
from ankora_backend.schemas.docking import DockingJobStatus
from ankora_backend.schemas.gnina import GninaDockingParameters
from ankora_backend.schemas.gnina_screening import GninaScreeningRequest
from ankora_backend.services.gnina_screening_admission import admit_screening


def _setup(tmp_path: Path, one_prepared, monkeypatch):
    screening_data, _conformer, _pdbqt = one_prepared
    ligands, library, selection = screening_data
    receptors, sites, _ = _stub_input_stores(tmp_path)
    sites.project_root = tmp_path / "projects" / "default"
    seen = []
    monkeypatch.setattr(
        "ankora_backend.services.gnina_screening_admission._linux_host", lambda: True
    )
    monkeypatch.setattr(
        "ankora_backend.services.gnina_screening_admission.probe_gnina",
        lambda: GninaInstallation("/synthetic/gnina", "1.3.3", "a" * 64, "x86_64"),
    )
    monkeypatch.setattr(
        "ankora_backend.services.gnina_screening_admission.ProjectDependencyService.for_project_root",
        lambda root: SimpleNamespace(require_current=lambda ids: seen.append((root, ids))),
    )
    resources = SimpleNamespace(validate=lambda claim: seen.append(claim))
    store = GninaScreeningStore(tmp_path)
    request = GninaScreeningRequest(
        receptor_id="receptor",
        binding_site_id="site",
        library_id=library.artifact.library_id,
        filter_run_id=selection.artifact.filter_run_id,
        parameters=GninaDockingParameters(compute="cpu"),
        acknowledge_inputs_and_scoring=True,
    )
    args = dict(
        request=request,
        store=store,
        receptors=receptors,
        sites=sites,
        ligands=ligands,
        resources=resources,
        enable_experimental_cuda=True,
    )
    return args, selection, seen


def test_admission_pins_real_selection_and_keeps_unprepared_entry(
    tmp_path, one_prepared, monkeypatch
):
    args, selection, seen = _setup(tmp_path, one_prepared, monkeypatch)
    record = admit_screening(**args)
    assert record.tool.version == "1.3.3" and record.tool.sha256 == "a" * 64
    assert record.box == _BOX
    assert record.selection.manifest_sha256 == selection.artifact.sha256
    assert [item.ligand_id for item in record.entries] == selection.selected_ligand_ids
    assert (record.selected_count, record.failed_count) == (2, 1)
    assert [item.status for item in record.entries] == [
        DockingJobStatus.QUEUED,
        DockingJobStatus.FAILED,
    ]
    assert args["store"].load_campaign(record.campaign_id) == record
    assert args["store"].jobs.list_jobs() == []
    assert args["request"].filter_run_id in seen[0][1]
    assert seen[1].cpu_threads == args["request"].parameters.cpu_threads


def test_changed_receptor_refused_without_creating_campaign(tmp_path, one_prepared, monkeypatch):
    args, _selection, _seen = _setup(tmp_path, one_prepared, monkeypatch)
    args["receptors"].content_path("receptor", "receptor-output").write_bytes(b"altered")
    with pytest.raises(AnkoraDomainError) as error:
        admit_screening(**args)
    assert error.value.code == "GNINA_INPUT_CHANGED"
    assert args["store"].list_campaign_ids() == []


def test_windows_and_unavailable_gpu_are_refused_before_creating_campaign(
    tmp_path, one_prepared, monkeypatch
):
    args, _selection, _seen = _setup(tmp_path, one_prepared, monkeypatch)
    monkeypatch.setattr(
        "ankora_backend.services.gnina_screening_admission._linux_host", lambda: False
    )
    with pytest.raises(AnkoraDomainError) as error:
        admit_screening(**args)
    assert error.value.code == "GNINA_LINUX_ONLY"
    monkeypatch.setattr(
        "ankora_backend.services.gnina_screening_admission._linux_host", lambda: True
    )
    args["request"] = args["request"].model_copy(
        update={"parameters": GninaDockingParameters(compute="cuda")}
    )
    args["enable_experimental_cuda"] = False
    with pytest.raises(AnkoraDomainError) as error:
        admit_screening(**args)
    assert error.value.code == "GNINA_CUDA_VERIFICATION_UNAVAILABLE"
    assert args["store"].list_campaign_ids() == []
