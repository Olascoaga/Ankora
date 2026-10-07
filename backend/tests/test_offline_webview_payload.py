"""Synthetic installer bytes: tests never install or download a browser."""

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from scripts import prepare_windows_webview2 as webview


def test_offline_input_is_microsoft_x64_and_hash_bound() -> None:
    entry = webview.load_webview_lock()
    assert entry["size_bytes"] > 100_000_000
    assert len(entry["sha256"]) == 64
    assert "RuntimeInstallerX64.exe" in entry["url"]


def test_lock_refuses_non_microsoft_download(tmp_path: Path) -> None:
    entry = webview.load_webview_lock()
    entry["url"] = "https://invalid.example/installer.exe"
    path = tmp_path / "lock.json"
    path.write_text(json.dumps(entry))
    with pytest.raises(ValueError, match="Unreviewed"):
        webview.load_webview_lock(path)


def test_upstream_drift_is_not_accepted_as_a_new_version(tmp_path, monkeypatch) -> None:
    class Response:
        url = "https://invalid.example/changed.exe"

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

    monkeypatch.setattr(webview.urllib.request, "urlopen", lambda *_a, **_k: Response())
    monkeypatch.setattr(webview, "acquire", lambda *_a: pytest.fail("must not download drift"))
    with pytest.raises(ValueError, match="changed"):
        webview.prepare(tmp_path, tmp_path / "tauri")


@pytest.mark.parametrize("status,signer", [("NotSigned", ""), ("Valid", "wrong publisher")])
def test_signature_gate_refuses_unsigned_or_other_publisher(
    tmp_path, monkeypatch, status, signer
) -> None:
    monkeypatch.setenv("SYSTEMROOT", str(tmp_path))
    monkeypatch.setenv("PSMODULEPATH", "incompatible modules")

    def run(command, **kwargs):
        assert "PSMODULEPATH" not in kwargs["env"]
        assert command[-1].find(str(tmp_path)) == -1  # no path interpolated as PowerShell code
        return SimpleNamespace(stdout=json.dumps({"status": status, "signer": signer}))

    monkeypatch.setattr(webview.subprocess, "run", run)
    with pytest.raises(ValueError, match="signed by Microsoft"):
        webview.verify_signature(tmp_path / "synthetic.exe", webview.load_webview_lock())


def test_nsis_selection_must_be_offline_and_match_exact_locked_bytes(tmp_path, monkeypatch) -> None:
    executable = tmp_path / "synthetic.exe"
    executable.write_bytes(b"synthetic installer, not executable")
    entry = {"id": "synthetic", "sha256": hashlib.sha256(executable.read_bytes()).hexdigest()}
    monkeypatch.setattr(webview, "load_webview_lock", lambda: entry)
    checked = []
    monkeypatch.setattr(webview, "verify_signature", lambda p, _e: checked.append(p))
    script = tmp_path / "installer.nsi"
    document = (
        '!define INSTALLWEBVIEW2MODE "offlineInstaller"\n'
        f'!define WEBVIEW2INSTALLERPATH "{executable}"\n'
    )
    script.write_text(document)
    webview.verify_nsis_selection(script)
    assert checked == [executable]
    executable.write_bytes(b"tampered")
    with pytest.raises(ValueError, match="SHA-256"):
        webview.verify_nsis_selection(script)
    script.write_text(document.replace("offlineInstaller", "downloadBootstrapper"))
    with pytest.raises(ValueError, match="does not embed"):
        webview.verify_nsis_selection(script)
