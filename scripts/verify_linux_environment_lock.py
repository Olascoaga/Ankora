"""Verify Ankora's Linux scientific environment locks and, optionally, the runtime.

Repository checks are static. Runtime checks only read the active interpreter's
installed distribution metadata and its Conda ``conda-meta`` records; nothing is
installed, repaired, rewritten or executed. The Windows verifier and locks are
separate and unchanged.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import platform
import re
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
PIP_PIN_RE = re.compile(
    r"^(?P<name>[A-Za-z0-9_.-]+)(?:\[[A-Za-z0-9_,.-]+\])?"
    r"==(?P<version>[^\s]+)(?:\s+--hash=sha256:(?P<sha256>[0-9a-f]{64}))?$"
)
CONDA_SPEC_RE = re.compile(
    r"^\s*-\s+(?P<name>[A-Za-z0-9_.-]+)=(?P<version>[^\s#=]+)\s*(?:#.*)?$"
)
SOURCE_WINDOWS_LOCK_RE = re.compile(
    r"^#\s*Source Windows pip lock SHA256:\s*([0-9a-f]{64})\s*$"
)
LOCAL_REFERENCE_RE = re.compile(
    r"(?i)(?:file:|(?:^|[\s'\"=])[a-z]:[\\/]|\\\\|(?:^|[\s'\"=])/(?:home|Users|mnt|tmp)/)"
)

# The accepted scientific Conda versions shared with Windows; equal by review,
# not imported, so a Windows change cannot silently redefine the Linux lock.
EXPECTED_CONDA_PINS = {
    "numpy": "2.5.2",
    "openmm": "8.5.2",
    "pdbfixer": "1.12",
    "pip": "26.2.1",
    "python": "3.12.13",
    "scipy": "1.18.0",
}
# Conda package version → Python distribution metadata (PDBFixer uses PEP 440 1.12.0).
EXPECTED_CONDA_DISTRIBUTIONS = {"openmm": "8.5.2", "pdbfixer": "1.12.0"}
CONDA_HOST = "conda.anaconda.org"
CONDA_CHANNEL = "conda-forge"
CONDA_SUBDIRS = {"linux-64", "noarch"}
WINDOWS_ONLY_DISTRIBUTIONS = {"pywin32", "pywin32-ctypes", "pywinpty", "win32-setctime"}
REQUIRED_PIP_OPTIONS = {"--only-binary=:all:", "--require-hashes"}

CONDA_LOCK = Path("environment") / "linux-64.conda.lock"
ENVIRONMENT_SPEC = Path("environment") / "linux.yml"
PIP_INPUT = Path("requirements") / "linux-py312.in"
PIP_LOCK = Path("requirements") / "linux-py312.lock"
WINDOWS_PIP_LOCK = Path("requirements") / "windows-py312.lock"


class LockValidationError(ValueError):
    pass


@dataclass(frozen=True)
class CondaArtifact:
    url: str
    subdir: str
    filename: str
    name: str
    version: str
    build: str
    sha256: str


@dataclass(frozen=True)
class LockSummary:
    conda_packages: int
    pip_packages: int


def canonical_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _read(path: Path) -> str:
    if not path.is_file():
        raise LockValidationError(f"required environment file is missing: {path}")
    text = path.read_text(encoding="utf-8")
    if LOCAL_REFERENCE_RE.search(text):
        raise LockValidationError(f"{path} contains a local or absolute path")
    return text


def _meaningful_lines(text: str) -> list[str]:
    return [
        line.strip()
        for line in text.splitlines()
        if line.strip() and not line.startswith("#")
    ]


def parse_conda_artifact(line: str) -> CondaArtifact:
    parsed = urlsplit(line)
    parts = parsed.path.split("/")
    if (
        parsed.scheme != "https"
        or parsed.hostname != CONDA_HOST
        or parsed.query
        or len(parts) != 4
        or parts[1] != CONDA_CHANNEL
        or parts[2] not in CONDA_SUBDIRS
    ):
        raise LockValidationError(f"Conda lock contains an untrusted URL: {line}")
    if not SHA256_RE.fullmatch(parsed.fragment):
        raise LockValidationError(f"Conda package is not SHA-256-bound: {line}")
    filename = parts[3]
    for extension in (".conda", ".tar.bz2"):
        if filename.endswith(extension):
            stem = filename.removesuffix(extension)
            break
    else:
        raise LockValidationError(f"Conda lock entry is not a package archive: {line}")
    fields = stem.rsplit("-", 2)
    if len(fields) != 3 or not all(fields):
        raise LockValidationError(
            f"Conda package file name is not name-version-build: {line}"
        )
    name, version, build = fields
    return CondaArtifact(
        url=line.split("#", 1)[0],
        subdir=parts[2],
        filename=filename,
        name=name,
        version=version,
        build=build,
        sha256=parsed.fragment,
    )


def parse_conda_lock(text: str) -> list[CondaArtifact]:
    lines = _meaningful_lines(text)
    if not lines or lines[0] != "@EXPLICIT":
        raise LockValidationError("Conda lock must use the @EXPLICIT format")
    artifacts = [parse_conda_artifact(line) for line in lines[1:]]
    if not artifacts:
        raise LockValidationError("Conda lock contains no packages")
    names = [artifact.name for artifact in artifacts]
    duplicates = sorted({name for name in names if names.count(name) > 1})
    if duplicates:
        raise LockValidationError(
            f"Conda lock lists packages more than once: {duplicates}"
        )
    return artifacts


def parse_pip_pins(text: str, *, source: Path, hashes_required: bool) -> dict[str, str]:
    pins: dict[str, str] = {}
    for line in _meaningful_lines(text):
        if line.startswith("--"):
            continue
        match = PIP_PIN_RE.fullmatch(line)
        if match is None:
            raise LockValidationError(
                f"{source} has an unsupported requirement: {line}"
            )
        if hashes_required and match.group("sha256") is None:
            raise LockValidationError(f"{source} has an unhashed requirement: {line}")
        name = canonical_name(match.group("name"))
        if name in pins:
            raise LockValidationError(f"{source} pins {name} more than once")
        pins[name] = match.group("version")
    if not pins:
        raise LockValidationError(f"{source} contains no pins")
    windows_only = sorted(set(pins) & WINDOWS_ONLY_DISTRIBUTIONS)
    if windows_only:
        raise LockValidationError(
            f"{source} contains Windows-only dependencies: {windows_only}"
        )
    return pins


def validate_repository_locks(root: Path) -> LockSummary:
    artifacts = parse_conda_lock(_read(root / CONDA_LOCK))
    locked_conda = {artifact.name: artifact.version for artifact in artifacts}
    environment_pins = {
        canonical_name(match.group("name")): match.group("version")
        for line in _read(root / ENVIRONMENT_SPEC).splitlines()
        if (match := CONDA_SPEC_RE.match(line)) is not None
    }
    for name, version in EXPECTED_CONDA_PINS.items():
        if locked_conda.get(name) != version:
            raise LockValidationError(f"Conda lock is missing {name}={version}")
        if environment_pins.get(name) != version:
            raise LockValidationError(
                f"{ENVIRONMENT_SPEC} does not preserve {name}={version}"
            )

    lock_text = _read(root / PIP_LOCK)
    options = {line for line in _meaningful_lines(lock_text) if line.startswith("--")}
    if options != REQUIRED_PIP_OPTIONS:
        raise LockValidationError(
            "Pip lock must require hashes and binary wheels without other global options"
        )
    pip_lock = parse_pip_pins(lock_text, source=PIP_LOCK, hashes_required=True)
    input_text = _read(root / PIP_INPUT)
    pip_input = parse_pip_pins(input_text, source=PIP_INPUT, hashes_required=False)
    if pip_input != pip_lock:
        differences = sorted(
            f"{name}: input {pip_input.get(name)} / lock {pip_lock.get(name)}"
            for name in set(pip_input) | set(pip_lock)
            if pip_input.get(name) != pip_lock.get(name)
        )
        raise LockValidationError(
            "Pip lock does not match its input pins:\n  " + "\n  ".join(differences)
        )
    for name, version in EXPECTED_CONDA_PINS.items():
        if name in pip_lock and pip_lock[name] != version:
            raise LockValidationError(
                f"Pip lock {name}=={pip_lock[name]} contradicts Conda {version}"
            )

    windows_lock_path = root / WINDOWS_PIP_LOCK
    windows_lock_bytes = (
        windows_lock_path.read_bytes() if windows_lock_path.is_file() else b""
    )
    recorded = [
        match.group(1)
        for line in input_text.splitlines()
        if (match := SOURCE_WINDOWS_LOCK_RE.match(line)) is not None
    ]
    if recorded != [hashlib.sha256(windows_lock_bytes).hexdigest()]:
        raise LockValidationError(
            f"{PIP_INPUT} must record the SHA-256 of the current {WINDOWS_PIP_LOCK}"
        )
    windows_pins = _windows_pins(windows_lock_bytes.decode("utf-8"))
    drifted = sorted(
        f"{name}: Windows {windows_pins[name]} / Linux {pip_lock[name]}"
        for name in set(windows_pins) & set(pip_lock)
        if windows_pins[name] != pip_lock[name]
    )
    if drifted:
        raise LockValidationError(
            "Common pip versions differ from the accepted Windows lock:\n  "
            + "\n  ".join(drifted)
        )
    return LockSummary(conda_packages=len(artifacts), pip_packages=len(pip_lock))


def _windows_pins(text: str) -> dict[str, str]:
    # The Windows lock legitimately contains Windows-only packages; read versions only.
    pins: dict[str, str] = {}
    for line in _meaningful_lines(text):
        match = PIP_PIN_RE.fullmatch(line)
        if match is not None:
            pins[canonical_name(match.group("name"))] = match.group("version")
    return pins


def validate_runtime(
    root: Path,
    *,
    prefix: Path | None = None,
    platform_name: str | None = None,
    machine: str | None = None,
    python_version: tuple[int, int, int] | None = None,
    distribution_version: Callable[[str], str] = importlib.metadata.version,
) -> None:
    """Compare the active environment with the locks; collect every mismatch."""
    prefix = Path(sys.prefix) if prefix is None else prefix
    platform_name = sys.platform if platform_name is None else platform_name
    machine = platform.machine() if machine is None else machine
    python_version = (
        (sys.version_info.major, sys.version_info.minor, sys.version_info.micro)
        if python_version is None
        else python_version
    )
    if not platform_name.startswith("linux"):
        raise LockValidationError(
            f"runtime verification requires Linux, found {platform_name}"
        )
    if machine.lower() != "x86_64":
        raise LockValidationError(
            f"runtime verification requires x86_64, found {machine}"
        )
    if python_version != (3, 12, 13):
        found = ".".join(str(part) for part in python_version)
        raise LockValidationError(
            f"locked runtime requires Python 3.12.13, found {found}"
        )
    conda_meta = prefix / "conda-meta"
    if not conda_meta.is_dir():
        raise LockValidationError(
            "locked runtime must be a Conda environment (no conda-meta)"
        )

    mismatches: list[str] = []
    pip_pins = parse_pip_pins(
        _read(root / PIP_LOCK), source=PIP_LOCK, hashes_required=True
    )
    for name, expected in sorted({**pip_pins, **EXPECTED_CONDA_DISTRIBUTIONS}.items()):
        try:
            actual = distribution_version(name)
        except importlib.metadata.PackageNotFoundError:
            mismatches.append(f"python {name}: missing (expected {expected})")
            continue
        if actual != expected:
            mismatches.append(f"python {name}: {actual} (expected {expected})")

    artifacts = {item.name: item for item in parse_conda_lock(_read(root / CONDA_LOCK))}
    records: dict[str, dict[str, object]] = {}
    for path in sorted(conda_meta.glob("*.json")):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            mismatches.append(f"conda {path.name}: unreadable record ({error})")
            continue
        package = record.get("name") if isinstance(record, dict) else None
        if not isinstance(package, str):
            mismatches.append(f"conda {path.name}: record has no package name")
            continue
        records[package] = record
    for name, artifact in sorted(artifacts.items()):
        record = records.get(name)
        if record is None:
            mismatches.append(
                f"conda {name}: not installed (expected {artifact.filename})"
            )
            continue
        expected_identity = {
            "version": artifact.version,
            "build": artifact.build,
            "url": artifact.url,
            "sha256": artifact.sha256,
        }
        for field, expected_value in expected_identity.items():
            if record.get(field) != expected_value:
                mismatches.append(
                    f"conda {name}: {field} {record.get(field)!r} (expected {expected_value!r})"
                )
    for name in sorted(set(records) - set(artifacts)):
        mismatches.append(f"conda {name}: installed but not in {CONDA_LOCK}")
    if mismatches:
        raise LockValidationError(
            "runtime differs from lock:\n  " + "\n  ".join(mismatches)
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Verify Ankora's Linux environment locks."
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="repository root (defaults to the parent of scripts/)",
    )
    parser.add_argument(
        "--runtime",
        action="store_true",
        help="also require the active interpreter and Conda prefix to match the locks",
    )
    arguments = parser.parse_args(argv)
    root = arguments.root.resolve()
    try:
        summary = validate_repository_locks(root)
        if arguments.runtime:
            validate_runtime(root)
    except LockValidationError as error:
        print(f"Linux environment lock verification failed: {error}", file=sys.stderr)
        return 1
    scope = (
        "repository locks and active runtime"
        if arguments.runtime
        else "repository locks"
    )
    print(
        f"Linux environment lock verification passed ({scope}): "
        f"{summary.conda_packages} Conda artifacts, {summary.pip_packages} pip wheels."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
