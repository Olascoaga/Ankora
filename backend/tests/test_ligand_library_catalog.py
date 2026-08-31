"""Finding a library that was already imported.

Until this listing existed a library was addressable by id but not
enumerable, so it was reachable only while the session that imported it
stayed open. The real project shows what that cost: 38 recorded imports of
four distinct files, one of them imported 33 times.
"""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ankora_backend.persistence.ligand_store import LigandArtifactStore

NOW = datetime(2026, 8, 20, 12, 0, tzinfo=UTC)


def _artifact(library_id: str, *, name: str, minutes: int, records: int = 3) -> dict[str, Any]:
    return {
        "library_id": library_id,
        "filename": name,
        "format": "sdf",
        "sha256": "a" * 64,
        "size_bytes": 4096,
        "record_count": records,
        "created_at": datetime(2026, 8, 20, 12, minutes, tzinfo=UTC).isoformat(),
    }


def _write_library(
    root: Path,
    library_id: str,
    *,
    name: str = "library.sdf",
    minutes: int = 0,
    entries: Any = None,
    filter_runs: int = 0,
) -> Path:
    directory = root / "projects" / "default" / "original" / "ligand_libraries" / library_id
    directory.mkdir(parents=True)
    record = {
        "artifact": _artifact(library_id, name=name, minutes=minutes),
        "entries": [] if entries is None else entries,
        "imported_count": 3,
        "failed_count": 0,
        "provenance": {
            "event_id": "event-1",
            "event_type": "ligand_library_imported",
            "timestamp": NOW.isoformat(),
            "input_artifacts": [],
            "output_artifacts": [library_id],
            "tool": {"name": "RDKit", "version": "2026.3.5"},
            "parameters": {},
        },
        "original_content_url": f"/libraries/{library_id}/content",
    }
    with (directory / "record.json").open("w", encoding="utf-8", newline="\n") as stream:
        json.dump(record, stream, indent=2)
    for index in range(filter_runs):
        run = (
            root / "projects" / "default" / "derived" / "ligand_libraries"
            / library_id / "filter_runs" / f"0000000{index}-0000-0000-0000-000000000000"
        )
        run.mkdir(parents=True)
        (run / "record.json").write_text("{}", encoding="utf-8")
    return directory


def _store(tmp_path: Path) -> LigandArtifactStore:
    return LigandArtifactStore(tmp_path)


def test_every_imported_library_can_be_found_again(tmp_path: Path) -> None:
    _write_library(tmp_path, "00000000-0000-0000-0000-000000000001", name="first.sdf", minutes=0)
    _write_library(tmp_path, "00000000-0000-0000-0000-000000000002", name="second.sdf", minutes=30)

    libraries = _store(tmp_path).list_libraries()

    # Newest first, the way the result catalog orders: there is no other
    # defensible ordering for a list of things that only differ by when.
    assert [item.artifact.filename for item in libraries] == ["second.sdf", "first.sdf"]
    assert libraries[0].artifact.record_count == 3


def test_a_listing_never_reads_a_librarys_molecules(tmp_path: Path) -> None:
    """The 38 libraries here hold 35.7 MiB of records between them.

    Parsing all of it to draw a list would get slower with every import, so
    only the artifact header is read - proven by a record whose entries are
    not valid JSON at all still appearing in the list.
    """
    directory = _write_library(tmp_path, "00000000-0000-0000-0000-000000000001")
    path = directory / "record.json"
    document = path.read_text(encoding="utf-8")
    corrupted = document.replace('"entries": []', '"entries": [ this is not json ')
    path.write_text(corrupted, encoding="utf-8")

    libraries = _store(tmp_path).list_libraries()

    assert len(libraries) == 1
    assert libraries[0].artifact.filename == "library.sdf"


def test_a_record_that_does_not_start_with_its_artifact_still_lists(tmp_path: Path) -> None:
    """The head-read is an optimisation, not the contract.

    A record written in another field order must not vanish from the list; it
    costs a full parse instead.
    """
    directory = _write_library(tmp_path, "00000000-0000-0000-0000-000000000001")
    path = directory / "record.json"
    record = json.loads(path.read_text(encoding="utf-8"))
    reordered = {"entries": record["entries"], **record}
    path.write_text(json.dumps(reordered, indent=2), encoding="utf-8")

    libraries = _store(tmp_path).list_libraries()

    assert [item.artifact.filename for item in libraries] == ["library.sdf"]


def test_a_library_says_whether_a_selection_was_ever_applied(tmp_path: Path) -> None:
    """It is the difference between resuming a screen and starting one."""
    _write_library(
        tmp_path, "00000000-0000-0000-0000-000000000001", name="applied.sdf",
        minutes=10, filter_runs=2,
    )
    _write_library(
        tmp_path, "00000000-0000-0000-0000-000000000002", name="untouched.sdf", minutes=0,
    )

    libraries = {item.artifact.filename: item for item in _store(tmp_path).list_libraries()}

    assert libraries["applied.sdf"].filter_run_count == 2
    assert libraries["applied.sdf"].latest_filter_run_id is not None
    assert libraries["untouched.sdf"].filter_run_count == 0
    assert libraries["untouched.sdf"].latest_filter_run_id is None


def test_an_unreadable_library_does_not_hide_the_rest(tmp_path: Path) -> None:
    """The listing is how a scientist finds their work; one bad directory
    must not take the other thirty-seven with it."""
    _write_library(tmp_path, "00000000-0000-0000-0000-000000000001", name="good.sdf")
    broken = (
        tmp_path / "projects" / "default" / "original" / "ligand_libraries"
        / "00000000-0000-0000-0000-000000000002"
    )
    broken.mkdir(parents=True)
    (broken / "record.json").write_text("not json at all", encoding="utf-8")

    libraries = _store(tmp_path).list_libraries()

    assert [item.artifact.filename for item in libraries] == ["good.sdf"]


def test_a_project_with_no_libraries_lists_nothing(tmp_path: Path) -> None:
    assert _store(tmp_path).list_libraries() == []
