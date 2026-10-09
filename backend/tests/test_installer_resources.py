"""Synthetic byte fixtures only; never replace or simulate scientific models."""

import hashlib
import json
import zipfile
from pathlib import Path

import pytest

from ankora_backend import installer_resources as resource


@pytest.fixture
def installed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    source = tmp_path / "legal" / resource.SOURCE_FILE
    source.parent.mkdir(parents=True)
    files = {}
    with zipfile.ZipFile(source, "w", zipfile.ZIP_DEFLATED) as archive:
        for name in resource.MODEL_NAMES:
            content = f"SYNTHETIC model fixture {name}".encode()
            archive.writestr(f"p2rank-2.5.1/distro/models/{name}/model.zst", content)
            files[f"p2rank-2.5.1/models/{name}/model.zst"] = hashlib.sha256(content).hexdigest()
    payload = tmp_path / "backend/tools/payload.json"
    payload.parent.mkdir(parents=True)
    payload.write_text(json.dumps({"files": files}))
    monkeypatch.setattr(resource, "SOURCE_SHA256", resource.digest(source))
    monkeypatch.setattr(resource, "PAYLOAD_SHA256", resource.digest(payload))
    return tmp_path


def test_restores_all_models_exactly_and_is_idempotent(installed: Path):
    resource.materialize(installed)
    models = list((installed / "backend/tools").rglob("model.zst"))
    assert len(models) == 7
    before = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in models}
    resource.materialize(installed)
    assert before == {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in models}
    assert not list(installed.rglob(".ankora-model-*"))


@pytest.mark.parametrize(
    "relative", [f"legal/{resource.SOURCE_FILE}", "backend/tools/payload.json"]
)
def test_rejects_altered_installation_inputs(installed: Path, relative: str):
    (installed / relative).write_bytes(b"tampered synthetic bytes")
    with pytest.raises(ValueError, match="identity mismatch"):
        resource.materialize(installed)
    assert not list(installed.rglob("model.zst"))


def test_does_not_overwrite_modified_model(installed: Path):
    resource.materialize(installed)
    path = next(installed.rglob("model.zst"))
    path.write_bytes(b"scientist-modified synthetic model")
    with pytest.raises(ValueError, match="unexpected bytes"):
        resource.materialize(installed)
    assert path.read_bytes() == b"scientist-modified synthetic model"


def test_rejects_mismatched_model_hash_before_publishing(installed: Path, monkeypatch):
    payload = installed / "backend/tools/payload.json"
    data = json.loads(payload.read_text())
    data["files"][f"p2rank-2.5.1/models/{resource.MODEL_NAMES[0]}/model.zst"] = "0" * 64
    payload.write_text(json.dumps(data))
    monkeypatch.setattr(resource, "PAYLOAD_SHA256", resource.digest(payload))
    with pytest.raises(ValueError, match="differs from runtime"):
        resource.materialize(installed)
    assert not list(installed.rglob("model.zst"))
    assert not list(installed.rglob(".ankora-model-*"))


def test_rejects_destination_outside_install_root(tmp_path):
    with pytest.raises(ValueError):
        resource.contained(tmp_path, "../outside/model.zst")
