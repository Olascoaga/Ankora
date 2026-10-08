"""Synthetic file inventories exercise installed-mode isolation, not science."""

import hashlib
import json
import sys
from pathlib import Path

import pytest

from ankora_backend.adapters.tools import bundled, discovery, pocket_detection
from ankora_backend.execution.subprocess_runner import ToolExecution


@pytest.fixture
def installation(tmp_path, monkeypatch):
    executable = tmp_path / "Installación & science" / "ankora-backend.exe"
    root = executable.parent / "tools"
    root.mkdir(parents=True)
    executable.write_bytes(b"synthetic backend")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(executable))
    bundled._inventory.cache_clear()
    paths = {
        name: f"{name}/{name}.exe" for name in ("vina", "autogrid4", "autodock4", "autodock_gpu")
    }
    paths.update(p2rank="p2rank/prank.bat", java="java/bin/java.exe")
    files = {}
    for name, relative in paths.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(f"synthetic {name}".encode())
        files[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    release = root / "java/release"
    release.write_text('JAVA_VERSION="21.0.12.1"\n')
    files["java/release"] = hashlib.sha256(release.read_bytes()).hexdigest()
    manifest = {
        "schema_version": 1,
        "files": files,
        "tools": {
            name: {"path": relative, "version": "test-version"} for name, relative in paths.items()
        },
    }
    (root / "payload.json").write_text(json.dumps(manifest))
    yield root
    bundled._inventory.cache_clear()


@pytest.mark.parametrize(
    "discover",
    [
        discovery.discover_vina,
        discovery.discover_autodock4,
        discovery.discover_autogrid4,
        discovery.discover_autodock_gpu,
        discovery.discover_p2rank,
    ],
)
def test_installed_tool_ignores_environment_and_path(installation, discover):
    found = discover("external.exe", path_lookup=lambda _: pytest.fail("PATH lookup"))
    assert found.available
    assert Path(found.path).is_relative_to(installation)
    assert found.version == "test-version"


def test_private_java_ignores_external_home(installation):
    assert (
        discovery.discover_java_home(
            "external-java", path_lookup=lambda _: pytest.fail("PATH lookup")
        )
        == installation / "java"
    )


def test_identity_records_manifest_and_variant(installation):
    manifest = installation / "payload.json"
    data = json.loads(manifest.read_text())
    data["tools"]["p2rank"]["variant"] = "synthetic-variant"
    manifest.write_text(json.dumps(data))
    assert bundled.bundled_execution_identity("p2rank") == {
        "bundled_payload_sha256": hashlib.sha256(manifest.read_bytes()).hexdigest(),
        "bundled_tool_variant": "synthetic-variant",
    }


def test_unlisted_dependency_fails_closed(installation):
    (installation / "injected.jar").write_bytes(b"synthetic unknown dependency")
    assert bundled.bundled_tool("p2rank") is None
    assert bundled.bundled_execution_identity("p2rank") == {}


@pytest.mark.parametrize("corruption", ["missing", "modified", "escaping", "incomplete"])
def test_corrupt_package_never_falls_through_to_user_tools(installation, corruption):
    manifest = installation / "payload.json"
    if corruption == "missing":
        manifest.unlink()
    elif corruption == "modified":
        (installation / "vina/vina.exe").write_bytes(b"modified")
    else:
        data = json.loads(manifest.read_text())
        if corruption == "escaping":
            data["files"]["../outside"] = "0" * 64
        else:
            del data["tools"]["java"]
        manifest.write_text(json.dumps(data))
    assert not discovery.discover_vina(
        "external.exe", path_lookup=lambda _: pytest.fail("PATH lookup")
    ).available


def test_packaged_python_worker_ignores_configured_console_script(installation, monkeypatch):
    monkeypatch.setattr(
        discovery, "discover_python_package", lambda *_: discovery.DiscoveredTool(True, None)
    )
    found = discovery.discover_tool(
        "mk_prepare_receptor", "external.exe", path_lookup=lambda _: pytest.fail("PATH lookup")
    )
    assert found.path == sys.executable


def test_packaged_p2rank_launches_private_java_without_shell(installation, monkeypatch, tmp_path):
    calls = []

    def execute(**kwargs):
        calls.append(kwargs)
        return ToolExecution([kwargs["executable"], *kwargs["arguments"]], 0, "", "")

    monkeypatch.setattr(pocket_detection, "run_tool", execute)
    monkeypatch.setenv("JAVA_TOOL_OPTIONS", "-agentlib:untrusted")
    receptor = tmp_path / "receptor & molécula.pdb"
    _, version = pocket_detection.execute_p2rank(receptor_pdb_path=receptor, output_dir=tmp_path)
    assert version == "test-version"
    assert calls[0]["executable"] == str(installation / "java/bin/java.exe")
    assert str(receptor) in calls[0]["arguments"]
    assert calls[0]["arguments"][0] == "-Xmx2048m"
    assert "JAVA_TOOL_OPTIONS" not in calls[0]["environment"]
