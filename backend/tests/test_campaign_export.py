"""Reproducible campaign export (M8).

The bundle is what leaves Ankora, so it is where the project's scientific rules
either hold or quietly stop holding.
"""

import csv
import io
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from zipfile import ZipFile

import pytest

from ankora_backend.schemas.figures import (
    FigureFile,
    FigureManifest,
    FigureManifestResult,
)
from ankora_backend.schemas.pose_interactions import InteractionAnalysisRecord
from ankora_backend.schemas.results_catalog import (
    ReproducibilityAssessment,
    ReproducibilityExecution,
    ReproducibilityStatus,
)
from ankora_backend.services.campaign_export import (
    ExportedCampaign,
    _write_portable_bundle,
    collect_recorded_evidence,
    manifest,
    readme,
    results_csv,
)


def _campaign(**overrides: Any) -> ExportedCampaign:
    defaults: dict[str, Any] = {
        "engine": "AutoDock",
        "engine_version": "4.2.6",
        "backend": "autodock4_cpu",
        "value_column": "autodock4_binding_energy_kcal_mol",
        "reproducibility": ReproducibilityAssessment(),
        "receptor_id": "receptor-1",
        "receptor_sha256": None,
        "binding_site_id": "site-1",
        "box": {"center_x": 1.0, "size_x": 20.0},
        "map_set_id": "map-set-1",
        "map_set_identity_key": "f" * 64,
        "selection_manifest_sha256": "c" * 64,
        "library_id": "library-1",
        "filter_run_id": "filter-1",
        "parameters": {"ga_runs": 10, "seed_1": 20260824},
        "executable_sha256": "1" * 64,
        "device_name": None,
        "selected_count": 3,
        "succeeded_count": 2,
        "failed_count": 1,
        "rows": [
            {
                "rank": 1,
                "molecule": "Compound A",
                "source_index": 0,
                "ligand_id": "lig-a",
                "canonical_smiles": "CC",
                "molecular_weight_g_mol": "30.000",
                "status": "completed",
                "failure_code": "",
                "failure_message": "",
                "autodock4_binding_energy_kcal_mol": "-5.640",
                "clusters": 3,
                "top_cluster_runs": 7,
            },
            {
                "rank": 2,
                "molecule": "Compound B",
                "source_index": 1,
                "ligand_id": "lig-b",
                "canonical_smiles": "CCO",
                "molecular_weight_g_mol": "46.000",
                "status": "completed",
                "failure_code": "",
                "failure_message": "",
                "autodock4_binding_energy_kcal_mol": "-4.100",
                "clusters": 1,
                "top_cluster_runs": 10,
            },
            {
                "rank": 3,
                "molecule": "Compound C",
                "source_index": 2,
                "ligand_id": "lig-c",
                "canonical_smiles": "",
                "molecular_weight_g_mol": "",
                "status": "failed",
                "failure_code": "AUTODOCK4_LIGAND_NOT_PREPARED",
                "failure_message": "No completed Meeko preparation.",
                "autodock4_binding_energy_kcal_mol": "",
                "clusters": 0,
                "top_cluster_runs": "",
            },
        ],
    }
    defaults.update(overrides)
    return ExportedCampaign(**defaults)


def _rows(document: str) -> list[dict[str, str]]:
    return list(csv.DictReader(io.StringIO(document)))


def test_the_value_column_is_named_after_the_engine_that_produced_it() -> None:
    """A column called `score` invites sorting two engines together.

    Vina's empirical score and AutoDock4's binding energy are on different
    scales, and the header is where that rule holds or stops holding.
    """
    autodock = results_csv(_campaign())
    vina = results_csv(
        _campaign(
            engine="AutoDock Vina",
            value_column="vina_score_kcal_mol",
            rows=[{"rank": 1, "molecule": "A", "vina_score_kcal_mol": "-7.5"}],
        )
    )

    assert "autodock4_binding_energy_kcal_mol" in autodock.splitlines()[0]
    assert "vina_score_kcal_mol" in vina.splitlines()[0]
    for header in (autodock.splitlines()[0], vina.splitlines()[0]):
        assert ",score," not in f",{header},"
        assert ",energy," not in f",{header},"


def test_autodock_carries_its_cluster_population_and_vina_does_not() -> None:
    """Sampling concentration stays visible without becoming repeat evidence."""
    autodock = _rows(results_csv(_campaign()))
    vina_header = results_csv(
        _campaign(
            engine="AutoDock Vina",
            value_column="vina_score_kcal_mol",
            rows=[{"rank": 1, "molecule": "A", "vina_score_kcal_mol": "-7.5"}],
        )
    ).splitlines()[0]

    assert autodock[0]["top_cluster_runs"] == "7"
    assert "top_cluster_runs" not in vina_header
    assert "clusters" not in vina_header


def test_a_molecule_that_was_never_docked_keeps_its_row() -> None:
    """A selection of 3 that produced 2 results is not a table of 2 rows."""
    rows = _rows(results_csv(_campaign()))

    assert len(rows) == 3
    failed = rows[-1]
    assert failed["status"] == "failed"
    assert failed["failure_code"] == "AUTODOCK4_LIGAND_NOT_PREPARED"
    assert failed["autodock4_binding_energy_kcal_mol"] == ""


def test_the_manifest_carries_what_it_would_take_to_ask_again() -> None:
    payload = json.loads(manifest(_campaign()))

    assert payload["inputs"]["binding_site_id"] == "site-1"
    assert payload["inputs"]["search_box"]["size_x"] == 20.0
    assert payload["inputs"]["map_set_identity_key"] == "f" * 64
    assert payload["inputs"]["selection_manifest_sha256"] == "c" * 64
    assert payload["engine"]["executable_sha256"] == "1" * 64
    # The protocol that was actually asked for, not a summary of it.
    assert payload["protocol"] == {"ga_runs": 10, "seed_1": 20260824}


def _assessment(status: ReproducibilityStatus, *outputs: str) -> ReproducibilityAssessment:
    return ReproducibilityAssessment(
        status=status,
        input_fingerprint_sha256="a" * 64,
        executions=[
            ReproducibilityExecution(
                catalog_id=f"autodock_gpu_batch:batch-{index}",
                output_fingerprint_sha256=output,
            )
            for index, output in enumerate(outputs, start=1)
        ],
    )


def test_measured_variability_carries_its_evidence_into_the_bundle() -> None:
    gpu = _campaign(
        engine="AutoDock-GPU",
        engine_version="1.6",
        backend="autodock_gpu",
        reproducibility=_assessment(
            ReproducibilityStatus.MEASURED_VARIABLE,
            "b" * 64,
            "c" * 64,
        ),
        device_name="NVIDIA RTX 5050",
    )

    payload = json.loads(manifest(gpu))
    note = readme(gpu)

    assert payload["reproducibility"]["status"] == "measured_variable"
    assert len(payload["reproducibility"]["executions"]) == 2
    assert "Measured variable" in payload["reproducibility"]["note"]
    assert payload["engine"]["device"] == "NVIDIA RTX 5050"
    assert "Measured variable" in note
    assert "NVIDIA RTX 5050" in note


def test_an_unassessed_backend_is_not_promoted_to_reproducible() -> None:
    payload = json.loads(manifest(_campaign()))

    assert payload["reproducibility"]["status"] == "not_assessed"
    assert "not assessed" in payload["reproducibility"]["note"]
    assert "not assessed" in readme(_campaign())


def test_measured_reproducibility_requires_recorded_equal_outputs() -> None:
    campaign = _campaign(
        reproducibility=_assessment(
            ReproducibilityStatus.MEASURED_REPRODUCIBLE,
            "b" * 64,
            "b" * 64,
        )
    )
    payload = json.loads(manifest(campaign))

    assert payload["reproducibility"]["status"] == "measured_reproducible"
    assert "Measured reproducible across 2" in payload["reproducibility"]["note"]


def test_every_bundle_states_that_the_number_is_not_an_affinity() -> None:
    payload = json.loads(manifest(_campaign()))
    note = readme(_campaign())

    joined = " ".join(payload["scientific_notes"])
    assert "not an experimental" in joined
    assert "must not be merged" in joined
    assert "not an experimental affinity" in note


def test_the_bundle_refuses_a_kind_of_result_it_does_not_understand() -> None:
    from ankora_backend.domain.errors import AnkoraDomainError
    from ankora_backend.services.campaign_export import CampaignExportService

    service = CampaignExportService.from_environment()

    with pytest.raises(AnkoraDomainError) as error:
        service.export_campaign(source_kind="gnina_batch", batch_id="whatever")

    assert error.value.code == "EXPORT_SOURCE_UNKNOWN"


def test_only_the_bundles_own_files_can_be_read_back() -> None:
    """The filename comes from a URL, so it is an allowlist rather than a path."""
    from ankora_backend.domain.errors import AnkoraDomainError
    from ankora_backend.services.campaign_export import CampaignExportService

    service = CampaignExportService.from_environment()

    with pytest.raises(AnkoraDomainError) as error:
        service.file_path("00000000-0000-0000-0000-000000000001", "../../record.json")

    assert error.value.code == "EXPORT_NOT_FOUND"


# --- M9 evidence travels with the campaign ---------------------------------

CATALOG_ID = "vina_batch:synthetic-batch"
ANALYSIS_ID = "00000000-0000-0000-0000-000000000101"
FIGURE_ID = "00000000-0000-0000-0000-000000000102"


def _write_synthetic_m9_evidence(root: Path) -> bytes:
    """Create explicitly synthetic records; no detector or renderer runs here."""
    analysis = InteractionAnalysisRecord.model_validate(
        {
            "analysis_id": ANALYSIS_ID,
            "created_at": "2026-08-27T12:00:00Z",
            "catalog_id": CATALOG_ID,
            "engine_key": "vina_batch",
            "record_id": "synthetic-batch",
            "engine_label": "synthetic Vina 1.2.7",
            "ligand_id": "synthetic-ligand",
            "ligand_preparation_id": "synthetic-preparation",
            "conformer_id": "synthetic-conformer",
            "conformer_sha256": "a" * 64,
            "pose": {
                "artifact_id": "synthetic-pose-1",
                "kind": "vina_mode",
                "ordinal": 1,
                "label": "Mode 1",
                "result_kcal_mol": -6.25,
                "value_label": "Vina score",
                "sha256": "b" * 64,
                "content_url": "/synthetic/pose-1",
            },
            "receptor_id": "synthetic-receptor",
            "docking_receptor_artifact_id": "synthetic-receptor-pdbqt",
            "docking_receptor_sha256": "c" * 64,
            "analysis_receptor_artifact_id": "synthetic-receptor-pdb",
            "analysis_receptor_sha256": "d" * 64,
            "analysis_receptor_content_url": "/synthetic/receptor.pdb",
            "detector": {"name": "synthetic ProLIF", "version": "2.2.test"},
            "profile": {},
            "contacts": [],
            "ligand_diagram": {
                "atoms": [{"atom_index": 0, "element": "C", "label": "C1", "x": 0, "y": 0}],
                "bonds": [],
            },
            "provenance": {
                "event_id": "synthetic-event",
                "event_type": "pose_interactions_analyzed",
                "timestamp": "2026-08-27T12:00:00Z",
                "tool": {"name": "synthetic ProLIF", "version": "2.2.test"},
            },
        }
    )
    analysis_dir = root / "projects" / "default" / "analysis" / "pose_interactions" / ANALYSIS_ID
    analysis_dir.mkdir(parents=True)
    (analysis_dir / "record.json").write_text(analysis.model_dump_json(indent=2), encoding="utf-8")

    figure_dir = root / "projects" / "default" / "exports" / "figures" / FIGURE_ID
    figure_dir.mkdir(parents=True)
    svg = b'<svg xmlns="http://www.w3.org/2000/svg"><circle r="1"/></svg>'
    (figure_dir / "interaction_diagram.svg").write_bytes(svg)
    figure = FigureManifest(
        figure_id=FIGURE_ID,
        exported_at=datetime(2026, 8, 27, 12, 5, tzinfo=UTC),
        source="interaction_diagram",
        result=FigureManifestResult(
            catalog_id=CATALOG_ID,
            ligand_id="synthetic-ligand",
            molecule="Synthetic molecule",
            pose_artifact_id="synthetic-pose-1",
            pose="Mode 1",
            interaction_analysis_id=ANALYSIS_ID,
        ),
        written_to=str(figure_dir),
        recorded_in=str(figure_dir),
        files=[
            FigureFile(
                filename="interaction_diagram.svg",
                format="svg",
                size_bytes=len(svg),
                vector=True,
            )
        ],
        notes=["Explicitly synthetic saved figure."],
    )
    (figure_dir / "figure.json").write_text(figure.model_dump_json(indent=2), encoding="utf-8")
    return svg


def test_existing_interactions_and_figures_are_copied_without_recomputation(
    tmp_path: Path,
) -> None:
    svg = _write_synthetic_m9_evidence(tmp_path)
    destination = tmp_path / "bundle"
    destination.mkdir()

    evidence = collect_recorded_evidence(
        root=tmp_path, catalog_id=CATALOG_ID, export_directory=destination
    )

    assert len(evidence.analyses) == 1
    assert evidence.analyses[0]["pose_artifact_id"] == "synthetic-pose-1"
    assert evidence.analyses[0]["sha256"] == _digest(destination / evidence.analyses[0]["path"])
    assert len(evidence.figures) == 1
    assert evidence.figures[0]["interaction_record_included"] is True
    copied = destination / evidence.figures[0]["files"][0]["path"]
    assert copied.read_bytes() == svg
    assert evidence.collection_warnings == []


def test_a_missing_saved_figure_is_reported_instead_of_recreated(tmp_path: Path) -> None:
    _write_synthetic_m9_evidence(tmp_path)
    (
        tmp_path
        / "projects"
        / "default"
        / "exports"
        / "figures"
        / FIGURE_ID
        / "interaction_diagram.svg"
    ).unlink()
    destination = tmp_path / "bundle"
    destination.mkdir()

    evidence = collect_recorded_evidence(
        root=tmp_path, catalog_id=CATALOG_ID, export_directory=destination
    )

    figure = evidence.figures[0]
    assert figure["files"] == []
    assert "no longer available" in figure["unavailable_files"][0]["reason"]


def test_an_early_m9_figure_without_recorded_paths_still_travels(tmp_path: Path) -> None:
    svg = _write_synthetic_m9_evidence(tmp_path)
    manifest_path = (
        tmp_path / "projects" / "default" / "exports" / "figures" / FIGURE_ID / "figure.json"
    )
    legacy = json.loads(manifest_path.read_text(encoding="utf-8"))
    legacy.pop("written_to")
    legacy.pop("recorded_in")
    legacy["result"].pop("pose_artifact_id")
    manifest_path.write_text(json.dumps(legacy), encoding="utf-8")
    destination = tmp_path / "bundle"
    destination.mkdir()

    evidence = collect_recorded_evidence(
        root=tmp_path, catalog_id=CATALOG_ID, export_directory=destination
    )

    figure = evidence.figures[0]
    assert figure["pose_artifact_id"] is None
    assert (destination / figure["files"][0]["path"]).read_bytes() == svg


def test_the_portable_zip_contains_the_complete_nested_evidence(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    evidence = bundle / "evidence" / "pose_interactions" / ANALYSIS_ID
    evidence.mkdir(parents=True)
    (bundle / "results.csv").write_text("rank,molecule\n", encoding="utf-8")
    (evidence / "record.json").write_text("{}\n", encoding="utf-8")

    archive = _write_portable_bundle(bundle)

    with ZipFile(archive) as opened:
        assert set(opened.namelist()) == {
            "results.csv",
            f"evidence/pose_interactions/{ANALYSIS_ID}/record.json",
        }


def test_a_campaign_export_indexes_and_zips_its_existing_m9_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The exported campaign is portable, and exporting never calls a detector."""
    from ankora_backend.services.campaign_export import CampaignExportService

    _write_synthetic_m9_evidence(tmp_path)
    monkeypatch.setattr(
        CampaignExportService,
        "_load",
        lambda self, source_kind, batch_id: _campaign(
            engine="AutoDock Vina", value_column="vina_score_kcal_mol"
        ),
    )
    monkeypatch.setattr(CampaignExportService, "_with_box", lambda self, campaign: campaign)
    unused = object()
    service = CampaignExportService(
        root=tmp_path,
        docking_store=unused,  # type: ignore[arg-type]
        autodock4_store=unused,  # type: ignore[arg-type]
        autodock_gpu_store=unused,  # type: ignore[arg-type]
        binding_site_store=unused,  # type: ignore[arg-type]
    )

    exported = service.export_campaign(source_kind="vina_batch", batch_id="synthetic-batch")

    assert exported["interaction_analysis_count"] == 1
    assert exported["figure_count"] == 1
    archive_filename = str(exported["archive_filename"])
    assert archive_filename in exported["files"]
    exported_manifest = json.loads(
        (Path(str(exported["directory"])) / "manifest.json").read_text(encoding="utf-8")
    )
    assert exported_manifest["ankora_export_format"] == 3
    assert exported_manifest["source_kind"] == "vina_batch"
    assert exported_manifest["source_id"] == "synthetic-batch"
    assert exported_manifest["bundle"] == {
        "export_id": exported["export_id"],
        "catalog_id": "vina_batch:synthetic-batch",
        "display_name": None,
        "input_identity_sha256": exported["input_identity_sha256"],
        "bundle_identity_sha256": exported["bundle_identity_sha256"],
        "archive_filename": archive_filename,
    }
    assert len(exported_manifest["recorded_evidence"]["pose_interaction_analyses"]) == 1
    archive = service.file_path(str(exported["export_id"]), archive_filename)
    with ZipFile(archive) as opened:
        names = set(opened.namelist())
    assert "manifest.json" in names
    assert f"evidence/pose_interactions/{ANALYSIS_ID}/record.json" in names
    assert f"evidence/figures/{FIGURE_ID}/interaction_diagram.svg" in names


def _digest(path: Path) -> str:
    from hashlib import sha256

    return sha256(path.read_bytes()).hexdigest()


# --- a folder the scientist chose ------------------------------------------


def _exporter(tmp_path: Path, campaign: ExportedCampaign) -> Any:
    """A real service over a temporary project, with one campaign to export."""
    from ankora_backend.services.campaign_export import CampaignExportService

    service = CampaignExportService(
        root=tmp_path,
        docking_store=None,  # type: ignore[arg-type]
        autodock4_store=None,  # type: ignore[arg-type]
        autodock_gpu_store=None,  # type: ignore[arg-type]
        binding_site_store=None,  # type: ignore[arg-type]
    )
    service._load = lambda source_kind, batch_id: campaign  # type: ignore[method-assign]
    service._with_box = lambda item: item  # type: ignore[method-assign]
    return service


def test_a_chosen_folder_receives_the_whole_bundle(tmp_path: Path) -> None:
    """A bundle is a folder, not a file: it travels intact or not at all."""
    destination = tmp_path / "manuscript"
    destination.mkdir()
    service = _exporter(tmp_path, _campaign())

    result = service.export_campaign(
        source_kind="vina_batch",
        batch_id="batch-1",
        destination=str(destination),
        display_name="PIK3CD validation · repeat 2",
    )

    written = Path(result["directory"])
    assert result["outside_project"] is True
    assert written.parent == destination
    # Named for the campaign rather than a UUID: it is about to sit beside a
    # paper. The shared slug turns the version's dots into hyphens, which keeps
    # one sanitizer for every kind of export rather than two.
    assert written.name.startswith("Ankora_PIK3CD-validation-repeat-2_vina_batch-batch-1_")
    assert f"inputs-{str(result['input_identity_sha256'])[:8]}" in written.name
    assert f"export-{str(result['bundle_identity_sha256'])[:8]}" in written.name
    assert {"results.csv", "manifest.json", "README.txt"} <= {
        item.name for item in written.iterdir()
    }
    # And the project keeps its own complete copy, which is what it serves back.
    record = Path(result["record_directory"])
    assert record != written
    assert (record / "results.csv").read_text(encoding="utf-8") == (
        written / "results.csv"
    ).read_text(encoding="utf-8")


def test_exporting_twice_into_one_folder_never_replaces_the_first(
    tmp_path: Path,
) -> None:
    """That folder holds work; a silently replaced bundle is data loss."""
    destination = tmp_path / "manuscript"
    destination.mkdir()
    service = _exporter(tmp_path, _campaign())

    first = service.export_campaign(
        source_kind="vina_batch", batch_id="batch-1", destination=str(destination)
    )
    second = service.export_campaign(
        source_kind="vina_batch", batch_id="batch-1", destination=str(destination)
    )

    assert Path(first["directory"]) != Path(second["directory"])
    assert first["input_identity_sha256"] == second["input_identity_sha256"]
    assert first["bundle_identity_sha256"] != second["bundle_identity_sha256"]
    assert first["archive_filename"] != second["archive_filename"]
    assert len(list(destination.iterdir())) == 2


def test_no_destination_keeps_the_bundle_in_the_project(tmp_path: Path) -> None:
    service = _exporter(tmp_path, _campaign())

    result = service.export_campaign(source_kind="vina_batch", batch_id="batch-1")

    assert result["outside_project"] is False
    assert result["directory"] == result["record_directory"]


def test_bundle_name_is_normalized_without_becoming_scientific_evidence(
    tmp_path: Path,
) -> None:
    service = _exporter(tmp_path, _campaign())

    result = service.export_campaign(
        source_kind="vina_batch",
        batch_id="batch-1",
        display_name="  PIK3CD   validation repeat 2  ",
    )

    assert result["display_name"] == "PIK3CD validation repeat 2"
    directory = Path(str(result["record_directory"]))
    payload = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    assert payload["bundle"]["display_name"] == "PIK3CD validation repeat 2"
    readme_text = (
        directory / "README.txt"
    ).read_text(encoding="utf-8")
    assert "Name          PIK3CD validation repeat 2" in readme_text
    assert "Bundle identity SHA-256" in readme_text
    assert str(result["archive_filename"]) in readme_text


def test_an_empty_bundle_name_is_rejected_before_an_export_directory_exists(
    tmp_path: Path,
) -> None:
    from ankora_backend.domain.errors import AnkoraDomainError

    service = _exporter(tmp_path, _campaign())

    with pytest.raises(AnkoraDomainError) as error:
        service.export_campaign(
            source_kind="vina_batch", batch_id="batch-1", display_name="   "
        )

    assert error.value.code == "EXPORT_NAME_INVALID"
    assert not (tmp_path / "projects" / "default" / "exports").exists()


def test_a_destination_that_does_not_exist_is_refused(tmp_path: Path) -> None:
    """Creating it would hide a typo as a bundle saved somewhere unexpected."""
    from ankora_backend.domain.errors import AnkoraDomainError
    from ankora_backend.services.export_destinations import validated_destination

    with pytest.raises(AnkoraDomainError) as error:
        validated_destination(str(tmp_path / "absent"), stage="s", prefix="EXPORT")

    assert error.value.code == "EXPORT_DESTINATION_NOT_FOUND"


def test_a_relative_destination_is_refused(tmp_path: Path) -> None:
    from ankora_backend.domain.errors import AnkoraDomainError
    from ankora_backend.services.export_destinations import validated_destination

    with pytest.raises(AnkoraDomainError) as error:
        validated_destination("bundles", stage="s", prefix="EXPORT")

    assert error.value.code == "EXPORT_DESTINATION_INVALID"
