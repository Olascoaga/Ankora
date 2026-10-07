"""Synthetic archives only; no scientific result is fabricated here."""

import hashlib
import io
import tarfile
import zipfile

import pytest
from scripts import windows_scientific_payload as payload


def test_upstream_lock_keeps_restricted_gpu_binary_out_of_runtime() -> None:
    entries = {item["id"]: item for item in payload.load_lock()}
    assert entries["vina"]["version"] == "1.2.7"
    assert entries["autodocksuite"]["version"] == "4.2.6"
    assert entries["p2rank"]["version"] == "2.5.1"
    assert entries["autodock-gpu-reference"]["role"] == "reference-only"
    for item in entries.values():
        if item["role"] == "runtime":
            assert entries[item["source_id"]]["role"] == "source"


@pytest.mark.parametrize(
    "name", ["../escape", "a/../x", "/abs", "a\\b", "x:y", "NUL", "a/COM1.txt", "a./b", "a /b"]
)
def test_unsafe_paths_are_rejected(name: str) -> None:
    with pytest.raises(ValueError, match="Unsafe"):
        payload.safe_relative(name)


def test_cache_is_verified_and_never_silently_repaired(tmp_path, monkeypatch) -> None:
    data = b"synthetic input, not an executable"
    entry = {
        "id": "test",
        "filename": "test.bin",
        "size_bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
    }
    destination = tmp_path / "test.bin"
    destination.write_bytes(data)
    monkeypatch.setattr(payload.urllib.request, "urlopen", lambda *_a, **_k: pytest.fail("network"))
    assert payload.acquire(entry, tmp_path, offline=True) == destination
    destination.write_bytes(b"x" * len(data))
    with pytest.raises(ValueError, match="SHA-256"):
        payload.acquire(entry, tmp_path)
    assert destination.read_bytes() == b"x" * len(data)


def test_missing_cache_fails_offline(tmp_path) -> None:
    with pytest.raises(FileNotFoundError, match="Offline cache"):
        payload.acquire({"id": "test", "filename": "a.zip"}, tmp_path, offline=True)


def test_zip_prefix_is_create_only(tmp_path) -> None:
    archive = tmp_path / "synthetic.zip"
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr("release/sub/data", b"synthetic model")
        z.writestr("other/notice", b"not selected")
    dest = tmp_path / "output"
    payload.extract_archive(archive, dest, prefix="release")
    assert (dest / "sub/data").read_bytes() == b"synthetic model"
    assert not (dest / "other").exists()
    with pytest.raises(FileExistsError):
        payload.extract_archive(archive, dest, prefix="release")


@pytest.mark.parametrize("member", ["../escape", "other/../escape", "release/NUL"])
def test_zip_rejects_unsafe_members_before_writing_even_outside_prefix(tmp_path, member) -> None:
    archive = tmp_path / "synthetic.zip"
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr("release/good", b"good")
        z.writestr(member, b"bad")
    dest = tmp_path / "output"
    with pytest.raises(ValueError):
        payload.extract_archive(archive, dest, prefix="release")
    assert not dest.exists()


def test_zip_rejects_case_collisions(tmp_path) -> None:
    archive = tmp_path / "synthetic.zip"
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr("release/File", "1")
        z.writestr("release/file", "2")
    with pytest.raises(ValueError, match="Duplicate"):
        payload.extract_archive(archive, tmp_path / "output")


def test_tar_rejects_links_before_writing(tmp_path) -> None:
    archive = tmp_path / "synthetic.tar"
    with tarfile.open(archive, "w") as t:
        item = tarfile.TarInfo("release/good")
        item.size = 1
        t.addfile(item, io.BytesIO(b"x"))
        link = tarfile.TarInfo("release/link")
        link.type = tarfile.SYMTYPE
        link.linkname = "../../escape"
        t.addfile(link)
    with pytest.raises(ValueError, match="Non-regular"):
        payload.extract_archive(archive, tmp_path / "output")
    assert not (tmp_path / "output").exists()


def test_runtime_selection_does_not_include_upstream_test_data(tmp_path) -> None:
    archive = tmp_path / "synthetic.zip"
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr("release/bin/app.jar", b"synthetic jar")
        z.writestr("release/models/model.dat", b"synthetic model")
        z.writestr("release/test_data/example.pdb", b"excluded example")
    dest = tmp_path / "runtime"
    payload.extract_archive(archive, dest, prefix="release", include=("bin", "models"))
    assert (dest / "bin/app.jar").is_file()
    assert (dest / "models/model.dat").is_file()
    assert not (dest / "test_data").exists()
