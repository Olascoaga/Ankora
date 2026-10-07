"""Synthetic JAR bytes only; no chemistry, Java execution or license approval."""

import hashlib
import json
import zipfile
from pathlib import Path

import pytest
from scripts import inventory_p2rank_dependencies as inventory


def _jar(path: Path, entries: dict[str, bytes]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as archive:
        for name, content in entries.items():
            archive.writestr(name, content)


def _payload(root: Path) -> None:
    files = {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in root.rglob("*")
        if path.is_file() and path.name != "payload.json"
    }
    (root / "payload.json").write_text(json.dumps({"schema_version": 1, "files": files}))


def test_inventory_keeps_verbatim_evidence_and_does_not_approve_licenses(tmp_path: Path) -> None:
    tools = tmp_path / "tools"
    main = tools / "p2rank-2.5.1/bin/p2rank.jar"
    notice = b"synthetic notice\r\n  exact whitespace \r\n"
    _jar(
        main,
        {
            "META-INF/LICENSE.txt": notice,
            "META-INF/maven/example/pom.xml": (
                b'<project xmlns="http://maven.apache.org/POM/4.0.0"><artifactId>synthetic</artifactId>'
                b"<licenses><license><name>synthetic label</name></license></licenses></project>"
            ),
            "example/Same.class": b"synthetic non-executable class",
            "native/windows/example.dll": b"synthetic non-executable native library",
        },
    )
    other = tools / "p2rank-2.5.1/bin/lib/other.jar"
    _jar(other, {"example/Same.class": b"different bytes", "example/Source.java": b"source"})
    _payload(tools)
    before = main.read_bytes()
    report, documents = inventory.build_inventory(tools)
    digest = hashlib.sha256(notice).hexdigest()
    assert documents[digest] == notice
    assert report["redistribution_status"] == "pending-review-not-approved"
    assert len(report["duplicate_classes"]) == 1
    assert len(report["duplicate_classes"][0]["jars"]) == 2
    assert report["missing_embedded_license"] == [other.relative_to(tools).as_posix()]
    main_record = next(item for item in report["jars"] if item["path"].endswith("/p2rank.jar"))
    assert main_record["native_members"] == ["native/windows/example.dll"]
    assert main_record["pom_declarations"][0]["licenses"][0]["name"] == "synthetic label"
    assert main.read_bytes() == before
    output = tmp_path / "report"
    inventory.write_inventory(report, documents, output)
    assert (output / "documents" / f"{digest}.txt").read_bytes() == notice
    with pytest.raises(FileExistsError):
        inventory.write_inventory(report, documents, output)


@pytest.mark.parametrize("change", ["tamper", "unlisted", "missing"])
def test_inventory_rejects_payload_drift(tmp_path: Path, change: str) -> None:
    main = tmp_path / "p2rank-2.5.1/bin/p2rank.jar"
    _jar(main, {"META-INF/MANIFEST.MF": b"synthetic"})
    _payload(tmp_path)
    if change == "tamper":
        main.write_bytes(b"changed")
    elif change == "unlisted":
        main.with_name("extra.jar").write_bytes(b"unexpected")
    else:
        main.unlink()
    with pytest.raises(ValueError, match="payload"):
        inventory.build_inventory(tmp_path)


def test_pom_does_not_expand_entities() -> None:
    with pytest.raises(ValueError, match="DTDs or entities"):
        inventory.pom_declarations(b'<!DOCTYPE project [<!ENTITY x "payload">]><project/>')


def test_non_utf8_pom_cannot_hide_a_dtd() -> None:
    with pytest.raises(ValueError):
        inventory.pom_declarations(
            '<!DOCTYPE project [<!ENTITY x "payload">]><project/>'.encode("utf-16")
        )


def test_report_documents_require_content_addressed_names(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="Document identity"):
        inventory.write_inventory({}, {"../bad": b"synthetic"}, tmp_path / "not-created")
    assert not (tmp_path / "not-created").exists()


def test_embedded_paths_never_become_output_paths(tmp_path: Path) -> None:
    path = tmp_path / "synthetic.jar"
    _jar(path, {"../../LICENSE.txt": b"synthetic"})
    report, documents, _classes = inventory.inspect_jar(path)
    assert report["documents"][0]["member"] == "../../LICENSE.txt"
    output = tmp_path / "safe"
    inventory.write_inventory(report, documents, output)
    assert not (tmp_path / "LICENSE.txt").exists()
    assert len(list((output / "documents").iterdir())) == 1


def test_metadata_size_is_bounded(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "synthetic.jar"
    _jar(path, {"LICENSE.txt": b"12345"})
    monkeypatch.setattr(inventory, "MAX_DOCUMENT", 4)
    with pytest.raises(ValueError, match="Oversized"):
        inventory.inspect_jar(path)


def test_duplicate_members_are_not_silently_selected(tmp_path: Path) -> None:
    path = tmp_path / "synthetic.jar"
    _jar(path, {"LICENSE.txt": b"one"})
    with zipfile.ZipFile(path, "a") as archive, pytest.warns(UserWarning, match="Duplicate"):
        archive.writestr("LICENSE.txt", b"two")
    with pytest.raises(ValueError, match="Duplicate JAR"):
        inventory.inspect_jar(path)
