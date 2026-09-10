"""Assemble and verify checksum-indexed Ankora Windows release artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import tomllib

ROOT = Path(__file__).resolve().parents[1]
LEGAL_ROOT = ROOT / "apps" / "desktop" / "src-tauri" / "resources" / "legal"
LEGAL_FILES = (
    "ANKORA_LICENSE.txt",
    "SOURCE_AVAILABILITY.txt",
    "THIRD_PARTY_INVENTORY.json",
    "THIRD_PARTY_NOTICES.txt",
)
LOCK_INPUTS = (
    ROOT / "package-lock.json",
    ROOT / "apps" / "desktop" / "src-tauri" / "Cargo.lock",
    ROOT / "environment" / "windows-64.conda.lock",
    ROOT / "requirements" / "windows-py312.lock",
    ROOT / "requirements" / "windows-packaging.lock",
    LEGAL_ROOT / "THIRD_PARTY_INVENTORY.json",
)
VERSION_RE = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+(?:[-+][0-9A-Za-z.-]+)?$")
CHECKSUM_RE = re.compile(r"^([0-9a-f]{64})  ([A-Za-z0-9][A-Za-z0-9._-]*)$")
REPOSITORY = "https://github.com/Olascoaga/Ankora"


@dataclass(frozen=True)
class SignatureEvidence:
    status: str
    signer_subject: str | None
    signer_thumbprint: str | None
    timestamp_subject: str | None
    timestamp_thumbprint: str | None

    @property
    def publication_ready(self) -> bool:
        return (
            self.status == "Valid"
            and bool(self.signer_subject)
            and bool(self.signer_thumbprint)
            and bool(self.timestamp_subject)
            and bool(self.timestamp_thumbprint)
        )


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run_git(*args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return result.stdout.strip()


def project_version() -> str:
    root_package = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
    desktop_package = json.loads(
        (ROOT / "apps" / "desktop" / "package.json").read_text(encoding="utf-8")
    )
    tauri_config = json.loads(
        (ROOT / "apps" / "desktop" / "src-tauri" / "tauri.conf.json").read_text(
            encoding="utf-8"
        )
    )
    with (ROOT / "apps" / "desktop" / "src-tauri" / "Cargo.toml").open("rb") as stream:
        cargo = tomllib.load(stream)
    with (ROOT / "backend" / "pyproject.toml").open("rb") as stream:
        backend = tomllib.load(stream)
    versions = {
        "package.json": root_package["version"],
        "apps/desktop/package.json": desktop_package["version"],
        "apps/desktop/src-tauri/tauri.conf.json": tauri_config["version"],
        "apps/desktop/src-tauri/Cargo.toml": cargo["package"]["version"],
        "backend/pyproject.toml": backend["project"]["version"],
    }
    unique = set(versions.values())
    if len(unique) != 1:
        details = ", ".join(f"{name}={value}" for name, value in versions.items())
        raise RuntimeError(f"Ankora version declarations disagree: {details}")
    version = str(unique.pop())
    if not VERSION_RE.fullmatch(version):
        raise RuntimeError(f"Unsupported Ankora release version: {version!r}")
    return version


def signature_evidence(installer: Path) -> SignatureEvidence:
    if os.name != "nt":
        raise RuntimeError("Authenticode verification requires Windows.")
    script = """
$ErrorActionPreference = 'Stop'
Import-Module Microsoft.PowerShell.Security
$signature = Microsoft.PowerShell.Security\\Get-AuthenticodeSignature -LiteralPath $env:ANKORA_SIGNATURE_TARGET
[ordered]@{
  status = [string]$signature.Status
  signer_subject = if ($signature.SignerCertificate) { $signature.SignerCertificate.Subject } else { $null }
  signer_thumbprint = if ($signature.SignerCertificate) { $signature.SignerCertificate.Thumbprint } else { $null }
  timestamp_subject = if ($signature.TimeStamperCertificate) { $signature.TimeStamperCertificate.Subject } else { $null }
  timestamp_thumbprint = if ($signature.TimeStamperCertificate) { $signature.TimeStamperCertificate.Thumbprint } else { $null }
} | ConvertTo-Json -Compress
"""
    environment = os.environ.copy()
    environment["ANKORA_SIGNATURE_TARGET"] = str(installer.resolve())
    windows_root = Path(environment.get("WINDIR", r"C:\Windows"))
    system_modules = windows_root / "System32" / "WindowsPowerShell" / "v1.0" / "Modules"
    program_files = Path(environment.get("ProgramFiles", r"C:\Program Files"))
    shared_modules = program_files / "WindowsPowerShell" / "Modules"
    environment["PSModulePath"] = os.pathsep.join((str(shared_modules), str(system_modules)))
    powershell = windows_root / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
    result = subprocess.run(
        [str(powershell), "-NoProfile", "-NonInteractive", "-Command", script],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8-sig",
        env=environment,
    )
    payload = json.loads(result.stdout.strip())
    evidence = SignatureEvidence(
        status=str(payload.get("status") or "UnknownError"),
        signer_subject=payload.get("signer_subject"),
        signer_thumbprint=payload.get("signer_thumbprint"),
        timestamp_subject=payload.get("timestamp_subject"),
        timestamp_thumbprint=payload.get("timestamp_thumbprint"),
    )
    if evidence.status not in {"NotSigned", "Valid"}:
        raise RuntimeError(f"Installer Authenticode status is {evidence.status}, not Valid.")
    return evidence


def require_clean_worktree() -> None:
    status = run_git("status", "--porcelain", "--untracked-files=all")
    if status:
        raise RuntimeError("Release assembly requires a clean Git worktree.")


def source_identity(source_ref: str) -> tuple[str, str]:
    commit = run_git("rev-parse", "--verify", f"{source_ref}^{{commit}}")
    tree = run_git("rev-parse", "--verify", f"{commit}^{{tree}}")
    return commit, tree


def verify_tag(tag: str, commit: str, required: bool) -> bool:
    try:
        tag_commit = run_git("rev-parse", "--verify", f"refs/tags/{tag}^{{commit}}")
    except subprocess.CalledProcessError:
        if required:
            raise RuntimeError(f"Required release tag {tag!r} does not exist.") from None
        return False
    if tag_commit != commit:
        if required:
            raise RuntimeError(f"Release tag {tag!r} does not point to source commit {commit}.")
        return False
    return True


def artifact_record(path: Path, role: str) -> dict[str, Any]:
    return {
        "name": path.name,
        "role": role,
        "size_bytes": path.stat().st_size,
        "sha256": sha256(path),
    }


def prepare(args: argparse.Namespace) -> None:
    installer = args.installer.resolve()
    output_dir = args.output_dir.resolve()
    if not installer.is_file():
        raise RuntimeError(f"Windows installer not found: {installer}")
    if args.require_clean:
        require_clean_worktree()

    version = project_version()
    expected_installer = f"Ankora_{version}_x64-setup.exe"
    if installer.name != expected_installer:
        raise RuntimeError(
            f"Installer name must be {expected_installer!r}, found {installer.name!r}."
        )
    commit, tree = source_identity(args.source_ref)
    tag = f"v{version}"
    tag_verified = verify_tag(tag, commit, args.require_tag)
    signature = signature_evidence(installer)
    publication_ready = tag_verified and signature.publication_ready
    if args.require_signed and not signature.publication_ready:
        raise RuntimeError(
            "Publication requires a Valid Authenticode signature with a timestamp certificate."
        )
    if args.require_signed and not tag_verified:
        raise RuntimeError("Publication requires the exact version tag at the source commit.")

    output_dir.parent.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(exist_ok=False)
    copied_installer = output_dir / installer.name
    shutil.copyfile(installer, copied_installer)
    payload_records = [artifact_record(copied_installer, "windows-installer")]
    for name in LEGAL_FILES:
        source = LEGAL_ROOT / name
        if not source.is_file():
            raise RuntimeError(f"Required legal payload is missing: {source}")
        destination = output_dir / name
        shutil.copyfile(source, destination)
        payload_records.append(artifact_record(destination, "legal-notice"))

    lock_records = []
    for path in LOCK_INPUTS:
        if not path.is_file():
            raise RuntimeError(f"Release lock input is missing: {path}")
        lock_records.append(
            {
                "path": path.relative_to(ROOT).as_posix(),
                "sha256": sha256(path),
            }
        )
    manifest = {
        "schema_version": 1,
        "product": "Ankora",
        "version": version,
        "tag": tag,
        "tag_verified": tag_verified,
        "publication_ready": publication_ready,
        "source": {
            "repository": REPOSITORY,
            "commit": commit,
            "tree": tree,
        },
        "authenticode": {
            "status": signature.status,
            "signer_subject": signature.signer_subject,
            "signer_thumbprint": signature.signer_thumbprint,
            "timestamp_subject": signature.timestamp_subject,
            "timestamp_thumbprint": signature.timestamp_thumbprint,
        },
        "lock_inputs": lock_records,
        "artifacts": payload_records,
        "reproducibility_claim": (
            "These exact bytes are checksum-indexed. Independent bit-for-bit rebuild "
            "reproducibility is not claimed."
        ),
    }
    manifest_path = output_dir / "release-manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    indexed = [path for path in output_dir.iterdir() if path.name != "SHA256SUMS"]
    checksum_lines = [f"{sha256(path)}  {path.name}" for path in sorted(indexed)]
    (output_dir / "SHA256SUMS").write_text(
        "\n".join(checksum_lines) + "\n", encoding="ascii", newline="\n"
    )
    print(f"Windows release artifacts prepared at {output_dir}")
    print(f"Publication ready: {str(publication_ready).lower()}")


def read_checksums(path: Path) -> dict[str, str]:
    checksums: dict[str, str] = {}
    for line_number, line in enumerate(path.read_text(encoding="ascii").splitlines(), 1):
        match = CHECKSUM_RE.fullmatch(line)
        if not match:
            raise RuntimeError(f"Invalid SHA256SUMS line {line_number}.")
        digest, name = match.groups()
        if name in checksums:
            raise RuntimeError(f"Duplicate checksum entry: {name}")
        checksums[name] = digest
    if not checksums:
        raise RuntimeError("SHA256SUMS is empty.")
    return checksums


def verify(args: argparse.Namespace) -> None:
    release_dir = args.release_dir.resolve()
    checksums_path = release_dir / "SHA256SUMS"
    manifest_path = release_dir / "release-manifest.json"
    if not checksums_path.is_file() or not manifest_path.is_file():
        raise RuntimeError("Release directory must contain SHA256SUMS and release-manifest.json.")
    checksums = read_checksums(checksums_path)
    actual_names = {path.name for path in release_dir.iterdir() if path.is_file()}
    expected_names = set(checksums) | {"SHA256SUMS"}
    if actual_names != expected_names:
        missing = sorted(expected_names - actual_names)
        extra = sorted(actual_names - expected_names)
        raise RuntimeError(f"Release file set mismatch; missing={missing}, extra={extra}.")
    for name, expected in checksums.items():
        actual = sha256(release_dir / name)
        if actual != expected:
            raise RuntimeError(f"Checksum mismatch for {name}.")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != 1:
        raise RuntimeError("Unsupported release manifest schema.")
    version = str(manifest.get("version") or "")
    if version != project_version():
        raise RuntimeError("Release manifest version does not match the checked-out source.")
    expected_tag = f"v{version}"
    if manifest.get("tag") != expected_tag:
        raise RuntimeError("Release manifest tag does not match its version.")
    source = manifest.get("source") or {}
    source_commit = str(source.get("commit") or "")
    source_tree = str(source.get("tree") or "")
    resolved_commit, resolved_tree = source_identity(source_commit)
    if resolved_commit != source_commit or resolved_tree != source_tree:
        raise RuntimeError("Release manifest source identity cannot be verified in Git.")
    expected_locks = {
        path.relative_to(ROOT).as_posix(): sha256(path) for path in LOCK_INPUTS
    }
    recorded_locks = {
        record.get("path"): record.get("sha256") for record in manifest.get("lock_inputs") or []
    }
    if recorded_locks != expected_locks:
        raise RuntimeError("Release manifest lock inputs do not match the checked-out source.")
    installer_name = f"Ankora_{version}_x64-setup.exe"
    required = {installer_name, *LEGAL_FILES, "release-manifest.json"}
    if set(checksums) != required:
        raise RuntimeError("SHA256SUMS does not contain the exact required release payload.")
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, list):
        raise TypeError("Release manifest artifacts must be a list.")
    records = {record.get("name"): record for record in artifacts}
    if set(records) != required - {"release-manifest.json"}:
        raise RuntimeError("Release manifest artifact set is incomplete or contains extras.")
    for name, record in records.items():
        path = release_dir / name
        if record.get("sha256") != checksums[name] or record.get("size_bytes") != path.stat().st_size:
            raise RuntimeError(f"Release manifest evidence mismatch for {name}.")

    signature = signature_evidence(release_dir / installer_name)
    recorded = manifest.get("authenticode") or {}
    observed = {
        "status": signature.status,
        "signer_subject": signature.signer_subject,
        "signer_thumbprint": signature.signer_thumbprint,
        "timestamp_subject": signature.timestamp_subject,
        "timestamp_thumbprint": signature.timestamp_thumbprint,
    }
    if recorded != observed:
        raise RuntimeError("Recorded Authenticode evidence does not match the installer.")
    expected_ready = bool(manifest.get("tag_verified")) and signature.publication_ready
    if manifest.get("publication_ready") is not expected_ready:
        raise RuntimeError("Release manifest publication_ready state is inconsistent.")
    if args.require_signed:
        head_commit, _head_tree = source_identity("HEAD")
        if head_commit != source_commit:
            raise RuntimeError("Public release verification must run at the recorded source commit.")
        verify_tag(expected_tag, source_commit, required=True)
        if not expected_ready:
            raise RuntimeError("This artifact set is not eligible for public release.")
    print(f"Windows release artifacts verified at {release_dir}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    prepare_parser = subparsers.add_parser("prepare")
    prepare_parser.add_argument("--installer", type=Path, required=True)
    prepare_parser.add_argument("--output-dir", type=Path, required=True)
    prepare_parser.add_argument("--source-ref", default="HEAD")
    prepare_parser.add_argument("--require-clean", action="store_true")
    prepare_parser.add_argument("--require-tag", action="store_true")
    prepare_parser.add_argument("--require-signed", action="store_true")
    verify_parser = subparsers.add_parser("verify")
    verify_parser.add_argument("--release-dir", type=Path, required=True)
    verify_parser.add_argument("--require-signed", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.command == "prepare":
        prepare(args)
    else:
        verify(args)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (
        OSError,
        RuntimeError,
        TypeError,
        ValueError,
        KeyError,
        json.JSONDecodeError,
        subprocess.CalledProcessError,
    ) as error:
        print(f"Release verification failed: {error}", file=sys.stderr)
        raise SystemExit(1) from error
