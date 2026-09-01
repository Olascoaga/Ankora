"""Finding what has already left Ankora (workflow step 8).

Every export wrote a manifest saying what it was and where it came from —
that is why they are written into the project rather than streamed away — but
nothing could enumerate them. These fix what a listing may claim: it reads
manifests, never payloads, and it never offers a file the project cannot hand
back.
"""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ankora_backend.schemas.exports import ExportKind
from ankora_backend.schemas.results_catalog import ReproducibilityStatus
from ankora_backend.services.export_catalog import ExportCatalogService

CAMPAIGN = "11111111-1111-1111-1111-111111111111"
FIGURE = "22222222-2222-2222-2222-222222222222"
COMPLEX = "33333333-3333-3333-3333-333333333333"


def _exports(root: Path) -> Path:
    return root / "projects" / "default" / "exports"


def _write(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _campaign(
    root: Path, *, minute: int = 0, evidence_aware: bool = True
) -> Path:
    directory = _exports(root) / CAMPAIGN
    _write(directory / "manifest.json", {
        "exported_at": datetime(2026, 8, 28, 5, minute, tzinfo=UTC).isoformat(),
        "ankora_export_format": 2,
        "source_kind": "autodock_gpu_batch",
        "source_id": "batch-1",
        "engine": {
            "name": "AutoDock-GPU", "version": "1.6",
            "device": "NVIDIA GeForce RTX 5050 Laptop GPU",
        },
        "reproducibility": (
            {
                "status": "measured_variable",
                "protocol": "ankora-reproducibility-v1",
                "scope": "parsed scientific outputs and retained pose-artifact bytes",
                "input_fingerprint_sha256": "a" * 64,
                "executions": [
                    {
                        "catalog_id": "autodock_gpu_batch:batch-1",
                        "output_fingerprint_sha256": "b" * 64,
                    },
                    {
                        "catalog_id": "autodock_gpu_batch:batch-2",
                        "output_fingerprint_sha256": "c" * 64,
                    },
                ],
                "note": "Measured variable.",
            }
            if evidence_aware
            else {"bitwise_reproducible": True, "note": "Legacy assumption."}
        ),
        "counts": {"selected": 25, "succeeded": 25, "failed": 0},
    })
    (directory / "results.csv").write_text("rank,molecule\n", encoding="utf-8")
    (directory / "README.txt").write_text("note\n", encoding="utf-8")
    (directory / "campaign_bundle.zip").write_bytes(b"PK\x03\x04")
    return directory


def _figure(root: Path, *, minute: int = 30, written_to: Path | None = None) -> Path:
    directory = _exports(root) / "figures" / FIGURE
    destination = written_to or directory
    _write(directory / "figure.json", {
        "figure_id": FIGURE,
        "exported_at": datetime(2026, 8, 28, 5, minute, tzinfo=UTC).isoformat(),
        "source": "interaction_diagram",
        "result": {
            "catalog_id": "autodock_gpu_batch:batch-1",
            "ligand_id": "ligand-1",
            "molecule": "Compound 231",
            "pose": "Cluster 1 · run 1",
            "interaction_analysis_id": "analysis-1",
        },
        "written_to": str(destination),
        "recorded_in": str(directory),
        "files": [{"filename": "interaction_diagram.svg", "vector": True}],
    })
    if destination == directory:
        (directory / "interaction_diagram.svg").write_text("<svg/>", encoding="utf-8")
    return directory


def _complex(root: Path, *, minute: int = 45) -> Path:
    directory = _exports(root) / "pose_complexes" / COMPLEX
    _write(directory / "complex.json", {
        "export_id": COMPLEX,
        "exported_at": datetime(2026, 8, 28, 5, minute, tzinfo=UTC).isoformat(),
        "catalog_id": "autodock_gpu_batch:batch-1",
        "ligand_id": "ligand-1",
        "molecule_name": "Compound 231",
        "pose_label": "Cluster 1 · run 1",
        "written_to": str(directory),
        "recorded_in": str(directory),
    })
    (directory / "ligand_receptor_complex.pdb").write_text("END\n", encoding="utf-8")
    return directory


def _service(root: Path) -> ExportCatalogService:
    return ExportCatalogService(root=root)


def test_all_three_kinds_of_export_are_listed_newest_first(tmp_path: Path) -> None:
    _campaign(tmp_path, minute=0)
    _figure(tmp_path, minute=30)
    _complex(tmp_path, minute=45)

    page = _service(tmp_path).list_exports()

    assert page.total == 3
    assert [entry.kind for entry in page.entries] == [
        ExportKind.POSE_COMPLEX, ExportKind.FIGURE, ExportKind.CAMPAIGN
    ]
    assert page.entries[0].title == "Compound 231 · complex"
    assert page.entries[1].title == "Compound 231 · interaction diagram"
    assert page.entries[2].title.startswith("AutoDock-GPU 1.6 · NVIDIA")


def test_every_export_says_what_it_came_from(tmp_path: Path) -> None:
    """An export with no traceable source is what Ankora exists not to make."""
    _campaign(tmp_path)
    _figure(tmp_path)

    entries = {entry.kind: entry for entry in _service(tmp_path).list_exports().entries}

    assert entries[ExportKind.CAMPAIGN].source_id == "batch-1"
    assert entries[ExportKind.CAMPAIGN].source_kind == "autodock_gpu_batch"
    assert entries[ExportKind.FIGURE].catalog_id == "autodock_gpu_batch:batch-1"
    assert entries[ExportKind.FIGURE].analysis_id == "analysis-1"


def test_measured_variability_survives_into_the_export_catalog(tmp_path: Path) -> None:
    _campaign(tmp_path)

    entry = _service(tmp_path).list_exports().entries[0]

    assert entry.reproducibility is not None
    assert entry.reproducibility.status is ReproducibilityStatus.MEASURED_VARIABLE
    assert len(entry.reproducibility.executions) == 2


def test_a_legacy_boolean_is_read_but_not_upgraded_into_evidence(tmp_path: Path) -> None:
    _campaign(tmp_path, evidence_aware=False)

    entry = _service(tmp_path).list_exports().entries[0]

    assert entry.bitwise_reproducible is True
    assert entry.reproducibility is None


def test_files_the_project_holds_are_offered_and_the_rest_are_named(
    tmp_path: Path,
) -> None:
    """A download link that 404s is worse than no link.

    A figure written into a manuscript folder is not Ankora's to serve; the
    project recorded that it happened and has no claim to hand it back.
    """
    _campaign(tmp_path)
    destination = tmp_path / "manuscript"
    destination.mkdir()
    _figure(tmp_path, written_to=destination)
    _complex(tmp_path)

    entries = {entry.kind: entry for entry in _service(tmp_path).list_exports().entries}

    campaign = entries[ExportKind.CAMPAIGN]
    assert {file.filename for file in campaign.files if file.content_url} == {
        "manifest.json", "results.csv", "README.txt", "campaign_bundle.zip",
    }
    readme = next(file for file in campaign.files if file.filename == "README.txt")
    assert readme.content_url == f"/exports/{CAMPAIGN}/README.txt"

    figure = entries[ExportKind.FIGURE]
    assert figure.outside_project is True
    assert figure.directory == str(destination)
    assert all(file.content_url is None for file in figure.files)

    # No route serves a complex, so it is named rather than linked either way.
    assert all(file.content_url is None for file in entries[ExportKind.POSE_COMPLEX].files)


def test_a_listing_carries_no_payloads(tmp_path: Path) -> None:
    """A bundle holds a table and a ZIP; an entry holds names and sizes."""
    directory = _campaign(tmp_path)
    (directory / "results.csv").write_text("rank,molecule\n1,RV2\n" * 5000, encoding="utf-8")

    entry = _service(tmp_path).list_exports().entries[0]
    table = next(file for file in entry.files if file.filename == "results.csv")

    assert table.size_bytes > 50_000
    assert "RV2" not in entry.model_dump_json()


def test_the_catalog_can_be_narrowed_to_one_kind(tmp_path: Path) -> None:
    _campaign(tmp_path)
    _figure(tmp_path)
    _complex(tmp_path)

    page = _service(tmp_path).list_exports(kind=ExportKind.FIGURE)

    assert page.total == 1
    assert page.entries[0].kind is ExportKind.FIGURE


def test_an_unreadable_manifest_hides_one_export_not_the_rest(tmp_path: Path) -> None:
    _campaign(tmp_path)
    broken = _exports(tmp_path) / "44444444-4444-4444-4444-444444444444"
    broken.mkdir(parents=True)
    (broken / "manifest.json").write_text("not json", encoding="utf-8")

    page = _service(tmp_path).list_exports()

    assert page.total == 1
    assert page.entries[0].kind is ExportKind.CAMPAIGN


def test_the_figures_and_complexes_folders_are_not_mistaken_for_bundles(
    tmp_path: Path,
) -> None:
    """They sit beside the campaign directories, and are not campaigns."""
    _figure(tmp_path)
    _complex(tmp_path)

    page = _service(tmp_path).list_exports()

    assert page.total == 2
    assert ExportKind.CAMPAIGN not in {entry.kind for entry in page.entries}


def test_a_project_that_has_exported_nothing_lists_nothing(tmp_path: Path) -> None:
    assert _service(tmp_path).list_exports().total == 0
