"""Pin and authenticate Tauri's full offline WebView2 installer build input.

Nothing is installed on the build machine. Tauri 2.11.4 resolves an Evergreen
URL during bundling, so detect upstream drift before AND after the build rather
than silently packaging a different installer. End users need no download.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import urllib.request
from pathlib import Path
from typing import Any

try:
    from scripts.windows_scientific_payload import CACHE, ROOT, acquire, verify
except ModuleNotFoundError:
    from windows_scientific_payload import CACHE, ROOT, acquire, verify

LOCK = ROOT / "resources/windows-webview2.lock.json"
EVERGREEN_URL = "https://go.microsoft.com/fwlink/?linkid=2124701"
URL_PATTERN = re.compile(
    r"https://msedge\.sf\.dl\.delivery\.mp\.microsoft\.com/filestreamingservice/files/"
    r"([0-9a-f-]{36})/(MicrosoftEdgeWebView2RuntimeInstallerX64\.exe)"
)


def load_webview_lock(path: Path = LOCK) -> dict[str, Any]:
    entry = json.loads(path.read_text(encoding="utf-8"))
    if (
        entry.get("schema_version") != 1
        or entry.get("architecture") != "x64"
        or not URL_PATTERN.fullmatch(entry.get("url", ""))
        or not re.fullmatch(r"[0-9a-f]{64}", entry.get("sha256", ""))
        or entry.get("filename") != "webview2-offline-x64.exe"
        or not entry.get("signer", "").startswith("CN=Microsoft Corporation,")
    ):
        raise ValueError("Unreviewed WebView2 installer identity")
    return entry


def verify_signature(path: Path, entry: dict[str, Any]) -> None:
    # The file path is data in a child-only environment variable, never shell code.
    environment = os.environ.copy()
    # PowerShell 7's module search path cannot be inherited by Windows
    # PowerShell 5.1: it may try to load incompatible Security assemblies.
    environment.pop("PSMODULEPATH", None)
    environment["ANKORA_WEBVIEW_VERIFY_PATH"] = str(path.resolve())
    command = (
        "$ErrorActionPreference='Stop'; "
        "$s=Get-AuthenticodeSignature -LiteralPath $env:ANKORA_WEBVIEW_VERIFY_PATH; "
        "@{status=$s.Status.ToString();signer=$s.SignerCertificate.Subject} "
        "| ConvertTo-Json -Compress"
    )
    powershell = Path(os.environ["SYSTEMROOT"]) / "System32/WindowsPowerShell/v1.0/powershell.exe"
    result = subprocess.run(
        [str(powershell), "-NoProfile", "-NonInteractive", "-Command", command],
        env=environment,
        capture_output=True,
        text=True,
        check=True,
        timeout=90,
    )
    signature = json.loads(result.stdout)
    if signature.get("status") != "Valid" or signature.get("signer") != entry["signer"]:
        raise ValueError("Offline WebView2 installer is not validly signed by Microsoft")


def prepare(cache: Path, tauri_tools: Path) -> Path:
    entry = load_webview_lock()
    with urllib.request.urlopen(
        urllib.request.Request(EVERGREEN_URL, method="HEAD"), timeout=30
    ) as response:
        if response.url != entry["url"]:
            raise ValueError(
                "Evergreen input changed: explicitly review and refresh the lock first"
            )
    source = acquire(entry, cache)
    verify_signature(source, entry)
    match = URL_PATTERN.fullmatch(entry["url"])
    assert match is not None
    destination = tauri_tools / "x64" / match[1] / match[2]
    if destination.exists():
        verify(destination, entry)
    else:
        destination.parent.mkdir(parents=True, exist_ok=True)
        with source.open("rb") as src, destination.open("xb") as dst:
            shutil.copyfileobj(src, dst)
        verify(destination, entry)
    return destination


def verify_nsis_selection(script: Path) -> None:
    entry = load_webview_lock()
    content = script.read_text(encoding="utf-8-sig")
    if '!define INSTALLWEBVIEW2MODE "offlineInstaller"' not in content:
        raise ValueError("NSIS does not embed the offline WebView2 installer")
    selected = re.findall(r'^!define WEBVIEW2INSTALLERPATH "(.+)"$', content, re.MULTILINE)
    if len(selected) != 1:
        raise ValueError("NSIS has no unique offline WebView2 payload")
    path = Path(selected[0].replace("$$", "$"))
    verify(path, entry)
    verify_signature(path, entry)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", type=Path, default=CACHE)
    parser.add_argument("--tauri-tools", type=Path)
    parser.add_argument("--verify-nsis", type=Path)
    args = parser.parse_args()
    if args.verify_nsis:
        verify_nsis_selection(args.verify_nsis)
        print("NSIS offline WebView2 selection matches the signed, locked input.")
    else:
        tools = args.tauri_tools or Path(os.environ["LOCALAPPDATA"]) / "tauri"
        prepare(args.cache, tools)
        print("Full offline WebView2 input verified and cached for Tauri; nothing installed.")
