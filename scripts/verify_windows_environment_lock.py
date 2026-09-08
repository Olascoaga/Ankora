from __future__ import annotations

import argparse
import importlib.metadata
import platform
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
PIP_PIN_RE = re.compile(
    r"^(?P<name>[A-Za-z0-9_.-]+)(?:\[[A-Za-z0-9_,.-]+\])?"
    r"==(?P<version>[^\s]+)(?:\s+--hash=sha256:(?P<sha256>[0-9a-f]{64}))?$"
)
CONDA_SPEC_RE = re.compile(r"^\s*-\s+(?P<name>[A-Za-z0-9_.-]+)=(?P<version>[^\s#]+)")
WINDOWS_ABSOLUTE_RE = re.compile(r"(?i)(?:^|[\s'\"])[a-z]:[\\/]")

EXPECTED_CONDA_PINS = {
    "numpy": "2.5.2",
    "openmm": "8.5.2",
    "pdbfixer": "1.12",
    "pip": "26.2.1",
    "python": "3.12.13",
    "scipy": "1.18.0",
}
CONDA_CHANNEL_HOSTS = {"conda.anaconda.org", "repo.anaconda.com"}


class LockValidationError(ValueError):
    pass


@dataclass(frozen=True)
class LockSummary:
    conda_packages: int
    pip_packages: int
    packaging_packages: int


def _canonical_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _meaningful_lines(path: Path) -> list[str]:
    return [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


def _reject_local_references(path: Path, text: str) -> None:
    lowered = text.lower()
    if "file:" in lowered or WINDOWS_ABSOLUTE_RE.search(text) or "\\\\" in text:
        raise LockValidationError(f"{path} contains a local or absolute path")


def _parse_pip_pins(path: Path, *, hashes_required: bool) -> dict[str, str]:
    pins: dict[str, str] = {}
    for line in _meaningful_lines(path):
        if line.startswith("--"):
            continue
        match = PIP_PIN_RE.fullmatch(line)
        if match is None:
            raise LockValidationError(
                f"{path} contains an unpinned requirement: {line}"
            )
        if hashes_required and match.group("sha256") is None:
            raise LockValidationError(
                f"{path} contains a requirement without SHA-256: {line}"
            )
        name = _canonical_name(match.group("name"))
        if name in pins:
            raise LockValidationError(f"{path} contains duplicate package {name}")
        pins[name] = match.group("version")
    return pins


def validate_repository_locks(root: Path) -> LockSummary:
    conda_path = root / "environment" / "windows-64.conda.lock"
    pip_input_path = root / "requirements" / "windows-py312.in"
    pip_lock_path = root / "requirements" / "windows-py312.lock"
    packaging_lock_path = root / "requirements" / "windows-packaging.lock"
    environment_path = root / "environment.yml"

    for path in (
        conda_path,
        pip_input_path,
        pip_lock_path,
        packaging_lock_path,
        environment_path,
    ):
        if not path.is_file():
            raise LockValidationError(f"required environment file is missing: {path}")
        _reject_local_references(path, path.read_text(encoding="utf-8"))

    conda_lines = _meaningful_lines(conda_path)
    if not conda_lines or conda_lines[0] != "@EXPLICIT":
        raise LockValidationError("Conda lock must use the @EXPLICIT format")
    conda_urls = conda_lines[1:]
    if not conda_urls:
        raise LockValidationError("Conda lock contains no packages")
    for package_url in conda_urls:
        parsed = urlsplit(package_url)
        if parsed.scheme != "https" or parsed.hostname not in CONDA_CHANNEL_HOSTS:
            raise LockValidationError(
                f"Conda lock contains an untrusted URL: {package_url}"
            )
        if not SHA256_RE.fullmatch(parsed.fragment):
            raise LockValidationError(
                f"Conda package is not SHA-256-bound: {package_url}"
            )

    for package_name, version in EXPECTED_CONDA_PINS.items():
        marker = f"/{package_name}-{version}-"
        if not any(marker in package_url.lower() for package_url in conda_urls):
            raise LockValidationError(f"Conda lock is missing {package_name}={version}")

    pip_lock_lines = _meaningful_lines(pip_lock_path)
    required_options = {"--only-binary=:all:", "--require-hashes"}
    present_options = {line for line in pip_lock_lines if line.startswith("--")}
    if present_options != required_options:
        raise LockValidationError(
            "Pip lock must require hashes and binary wheels without other global options"
        )
    pip_input = _parse_pip_pins(pip_input_path, hashes_required=False)
    pip_lock = _parse_pip_pins(pip_lock_path, hashes_required=True)
    packaging_lock = _parse_pip_pins(packaging_lock_path, hashes_required=True)
    for name, version in pip_input.items():
        if pip_lock.get(name) != version:
            raise LockValidationError(
                f"Pip lock does not preserve input pin {name}=={version}"
            )

    environment_pins: dict[str, str] = {}
    for line in environment_path.read_text(encoding="utf-8").splitlines():
        match = CONDA_SPEC_RE.match(line)
        if match is not None:
            environment_pins[_canonical_name(match.group("name"))] = match.group(
                "version"
            )
    for name, version in EXPECTED_CONDA_PINS.items():
        if environment_pins.get(name) != version:
            raise LockValidationError(
                f"environment.yml does not preserve {name}={version}"
            )

    if packaging_lock.get("pyinstaller") is None:
        raise LockValidationError("Packaging lock must include PyInstaller")

    return LockSummary(
        conda_packages=len(conda_urls),
        pip_packages=len(pip_lock),
        packaging_packages=len(packaging_lock),
    )


def validate_runtime(root: Path) -> None:
    if sys.platform != "win32":
        raise LockValidationError("runtime verification requires Windows")
    if platform.machine().lower() not in {"amd64", "x86_64"}:
        raise LockValidationError("runtime verification requires Windows x86-64")
    if sys.version_info[:3] != (3, 12, 13):
        raise LockValidationError(
            f"locked runtime requires Python 3.12.13, found {platform.python_version()}"
        )
    if not (Path(sys.prefix) / "conda-meta").is_dir():
        raise LockValidationError("locked runtime must be a Conda environment")

    pip_pins = _parse_pip_pins(
        root / "requirements" / "windows-py312.lock", hashes_required=True
    )
    runtime_pins = dict(pip_pins)
    # Conda's package version is 1.12 while PDBFixer's Python distribution
    # metadata uses the equivalent PEP 440 spelling 1.12.0.
    runtime_pins.update({"openmm": "8.5.2", "pdbfixer": "1.12.0"})
    mismatches: list[str] = []
    for name, expected_version in sorted(runtime_pins.items()):
        try:
            actual_version = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            mismatches.append(f"{name}: missing (expected {expected_version})")
            continue
        if actual_version != expected_version:
            mismatches.append(f"{name}: {actual_version} (expected {expected_version})")
    if mismatches:
        raise LockValidationError(
            "runtime differs from lock:\n  " + "\n  ".join(mismatches)
        )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify Ankora's Windows environment locks."
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
        help="also require the active interpreter to match every locked package",
    )
    args = parser.parse_args()
    root = args.root.resolve()
    try:
        summary = validate_repository_locks(root)
        if args.runtime:
            validate_runtime(root)
    except LockValidationError as error:
        print(f"Windows environment lock verification failed: {error}", file=sys.stderr)
        return 1
    runtime_note = " and active runtime" if args.runtime else ""
    print(
        "Windows environment locks"
        f"{runtime_note} verified: {summary.conda_packages} Conda packages, "
        f"{summary.pip_packages} Python packages, and "
        f"{summary.packaging_packages} packaging tools."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
