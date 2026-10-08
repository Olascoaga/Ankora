"""Synthetic file compatibility guards; these tests invent no pocket scores."""

import json
from pathlib import Path

import pytest
from scripts import validate_p2rank_variant as variant


def _reference(root: Path, monkeypatch) -> None:
    files = {
        variant.REMOVED: b"synthetic old vecmath",
        variant.RETAINED: b"synthetic new vecmath",
        "p2rank-2.5.1/models/default.model": b"synthetic immutable model",
    }
    for relative, data in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    hashes = {name: variant.sha256(root / name) for name in files}
    monkeypatch.setattr(variant, "REMOVED_SHA", hashes[variant.REMOVED])
    monkeypatch.setattr(variant, "RETAINED_SHA", hashes[variant.RETAINED])
    (root / "payload.json").write_text(json.dumps({"files": hashes, "tools": {"p2rank": {}}}))


def test_variant_only_omits_authorized_file_and_keeps_reference(tmp_path, monkeypatch):
    original, candidate = tmp_path / "original", tmp_path / "candidate"
    _reference(original, monkeypatch)
    original_hash = variant.sha256(original / "payload.json")
    variant.create_variant(original, candidate)
    manifest = variant.verify_tree(candidate)
    assert variant.REMOVED not in manifest["files"]
    assert (original / variant.REMOVED).exists()
    assert variant.sha256(original / "payload.json") == original_hash
    assert manifest["p2rank_variant"]["reference_payload_sha256"] == original_hash
    assert manifest["tools"]["p2rank"]["variant"] == variant.VARIANT
    with pytest.raises(FileExistsError):
        variant.create_variant(original, candidate)


@pytest.mark.parametrize("damage", ["tampered", "unlisted", "missing"])
def test_variant_rejects_unverified_reference(tmp_path, monkeypatch, damage):
    original = tmp_path / "original"
    _reference(original, monkeypatch)
    if damage == "tampered":
        (original / variant.RETAINED).write_bytes(b"changed")
    elif damage == "unlisted":
        (original / "unlisted.jar").write_bytes(b"extra")
    else:
        (original / variant.REMOVED).unlink()
    with pytest.raises(ValueError):
        variant.create_variant(original, tmp_path / "candidate")
    assert not (tmp_path / "candidate").exists()


def test_compare_rejects_changed_model_before_running_java(tmp_path, monkeypatch):
    original, candidate = tmp_path / "original", tmp_path / "candidate"
    _reference(original, monkeypatch)
    variant.create_variant(original, candidate)
    manifest = json.loads((candidate / "payload.json").read_text())
    model = "p2rank-2.5.1/models/default.model"
    (candidate / model).write_bytes(b"different model")
    manifest["files"][model] = variant.sha256(candidate / model)
    (candidate / "payload.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="single authorized omission"):
        variant.compare(original, candidate, tmp_path / "output")
    assert not (tmp_path / "output").exists()
