"""Synthetic acquisition tests; no network or scientific result is fabricated."""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

import pytest
from scripts import collect_p2rank_maven_evidence as evidence


def test_parallel_publication_never_changes_existing_bytes(tmp_path: Path) -> None:
    target = tmp_path / "artifact"
    content = b"synthetic" * 100_000
    with ThreadPoolExecutor(max_workers=4) as workers:
        list(workers.map(lambda _: evidence.publish(target, content), range(12)))
    assert target.read_bytes() == content
    with pytest.raises(ValueError, match="mismatch"):
        evidence.publish(target, b"changed")
    assert list(tmp_path.iterdir()) == [target]


@pytest.mark.parametrize("value", ["../escape", "${version}", "x/y", "", "a:b"])
def test_unresolved_coordinates_are_rejected(value: str) -> None:
    with pytest.raises(ValueError, match="coordinate"):
        evidence.maven_path("org.synthetic", "example", value)


def test_hint_is_only_a_candidate_not_provenance() -> None:
    assert evidence.coordinate(Path("flatlaf-2.0.jar"), {"pom_declarations": []}) == (
        "com.formdev",
        "flatlaf",
        "2.0",
    )
    with pytest.raises(ValueError, match="No verified"):
        evidence.coordinate(Path("unknown.jar"), {"pom_declarations": []})


def test_mismatched_binary_stops_before_pom_or_source(tmp_path: Path) -> None:
    binary = tmp_path / "download.jar"
    binary.write_bytes(b"synthetic wrong download")
    metadata = {"pom_declarations": []}
    with (
        patch.object(evidence, "inspect_jar", return_value=(metadata, {}, set())),
        patch.object(evidence, "sha256", side_effect=["a" * 64, "b" * 64]),
        patch.object(evidence, "fetch", return_value=binary) as fetch,
    ):
        row = evidence.collect_one(Path("flatlaf-2.0.jar"), tmp_path)
    assert row["error"] == "Maven binary differs from shipped bytes"
    assert "coordinate" not in row
    assert "source_archive" not in row
    fetch.assert_called_once()


def test_traversal_is_rejected_before_network(tmp_path: Path) -> None:
    with (
        patch.object(evidence.urllib.request, "urlopen") as request,
        pytest.raises(ValueError, match="Unsafe"),
    ):
        evidence.fetch("../escape", tmp_path)
    request.assert_not_called()
