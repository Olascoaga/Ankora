"""Linux environment lock contracts.

The repository check runs against the actual committed locks. Tamper cases edit
copies of those files. Runtime cases use SYNTHETIC conda-meta records and
distribution versions derived from the committed locks; no environment is
installed, inspected beyond those fixtures, or executed.
"""

from __future__ import annotations

import importlib.util
import json
import re
import shutil
import sys
from collections.abc import Callable
from pathlib import Path
from types import ModuleType

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = REPOSITORY_ROOT / "scripts"
LOCK_FILES = (
    Path("environment/linux-64.conda.lock"),
    Path("environment/linux.yml"),
    Path("requirements/linux-py312.in"),
    Path("requirements/linux-py312.lock"),
    Path("requirements/windows-py312.lock"),
)


def _load(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def verifier() -> ModuleType:
    return _load("verify_linux_environment_lock")


@pytest.fixture
def root(tmp_path: Path) -> Path:
    for relative in LOCK_FILES:
        (tmp_path / relative).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(REPOSITORY_ROOT / relative, tmp_path / relative)
    return tmp_path


def _edit(root: Path, relative: str, change: Callable[[str], str]) -> None:
    path = root / relative
    original = path.read_text(encoding="utf-8")
    changed = change(original)
    assert changed != original, "tamper fixture did not change the file"
    path.write_text(changed, encoding="utf-8")


def _replace(old: str, new: str) -> Callable[[str], str]:
    return lambda text: text.replace(old, new, 1)


def _line_with(text: str, marker: str) -> str:
    return next(line for line in text.splitlines() if marker in line)


# --- Actual repository --------------------------------------------------------------


def test_committed_linux_locks_pass_static_verification(verifier: ModuleType) -> None:
    summary = verifier.validate_repository_locks(REPOSITORY_ROOT)

    assert (summary.conda_packages, summary.pip_packages) == (45, 75)
    assert verifier.main(["--root", str(REPOSITORY_ROOT)]) == 0


def test_shared_scientific_conda_versions_equal_the_windows_verifier(
    verifier: ModuleType,
) -> None:
    windows = _load("verify_windows_environment_lock")

    assert verifier.EXPECTED_CONDA_PINS == windows.EXPECTED_CONDA_PINS


def test_every_committed_conda_artifact_is_a_conda_forge_linux_identity(
    verifier: ModuleType,
) -> None:
    text = (REPOSITORY_ROOT / "environment/linux-64.conda.lock").read_text(encoding="utf-8")
    artifacts = verifier.parse_conda_lock(text)

    assert {artifact.subdir for artifact in artifacts} <= {"linux-64", "noarch"}
    assert all(len(artifact.sha256) == 64 for artifact in artifacts)
    assert len({artifact.url for artifact in artifacts}) == len(artifacts)


# --- Static tampering -----------------------------------------------------------------

CONDA = "environment/linux-64.conda.lock"
SPEC = "environment/linux.yml"
PIP_IN = "requirements/linux-py312.in"
PIP_LOCK = "requirements/linux-py312.lock"
WINDOWS_LOCK = "requirements/windows-py312.lock"
UNTRUSTED = "untrusted URL"
# Synthetic private paths, assembled at runtime so this source file itself
# passes scripts/check_public_paths.py.
SYNTHETIC_WINDOWS_PATH = "C" + ":\\Users\\synthetic"
SYNTHETIC_HOME_PATH = "/" + "home/synthetic"


@pytest.mark.parametrize(
    ("relative", "change", "message"),
    [
        (CONDA, _replace("@EXPLICIT\n", ""), "@EXPLICIT"),
        (
            CONDA,
            _replace(
                "https://conda.anaconda.org/conda-forge/", "https://repo.anaconda.com/pkgs/main/"
            ),
            UNTRUSTED,
        ),
        (CONDA, _replace("https://conda.anaconda.org", "http://conda.anaconda.org"), UNTRUSTED),
        (CONDA, _replace("conda-forge/linux-64/libgomp", "conda-forge/win-64/libgomp"), UNTRUSTED),
        (CONDA, _replace("conda-forge/linux-64/libgomp", "bioconda/linux-64/libgomp"), UNTRUSTED),
        (
            CONDA,
            lambda text: text.replace(
                _line_with(text, "libgomp"), _line_with(text, "libgomp")[:-1]
            ),
            "SHA-256-bound",
        ),
        (
            CONDA,
            lambda text: text.replace(
                _line_with(text, "libgomp"), _line_with(text, "libgomp").split("#")[0]
            ),
            "SHA-256-bound",
        ),
        (CONDA, lambda text: text + _line_with(text, "libgomp") + "\n", "more than once"),
        (CONDA, _replace("/numpy-2.5.2-", "/numpy-2.5.1-"), "numpy=2.5.2"),
        (
            CONDA,
            _replace("/libgomp-16.2.0-he0feb66_7.conda", "/libgomp.conda"),
            "name-version-build",
        ),
        (
            CONDA,
            _replace("# platform: linux-64", f"# built in {SYNTHETIC_WINDOWS_PATH}"),
            "local or absolute",
        ),
        (SPEC, _replace("openmm=8.5.2", "openmm=8.5.1"), "openmm=8.5.2"),
        (PIP_LOCK, _replace("--require-hashes\n", ""), "require hashes"),
        (
            PIP_LOCK,
            _replace("--only-binary=:all:\n", "--only-binary=:all:\n--no-deps\n"),
            "require hashes",
        ),
        (
            PIP_LOCK,
            lambda text: text.replace(_line_with(text, "rdkit=="), "rdkit==2025.9.6"),
            "unhashed",
        ),
        (PIP_LOCK, lambda text: text + _line_with(text, "rdkit==") + "\n", "more than once"),
        (
            PIP_LOCK,
            lambda text: text.replace(_line_with(text, "gemmi==") + "\n", ""),
            "does not match its input",
        ),
        (
            PIP_LOCK,
            _replace("# Exact wheels", f"# Built in {SYNTHETIC_HOME_PATH}; exact wheels"),
            "local or absolute",
        ),
        (PIP_IN, _replace("rdkit==2025.9.6\n", ""), "does not match its input"),
        (PIP_IN, _replace("meeko==0.7.1", "meeko==0.7.0"), "does not match its input"),
        (
            PIP_IN,
            _replace("# Source Windows pip lock SHA256", "# Source"),
            "must record the SHA-256",
        ),
        (
            WINDOWS_LOCK,
            lambda text: text + "# synthetic later Windows change\n",
            "must record the SHA-256",
        ),
    ],
)
def test_tampered_repository_locks_are_rejected(
    verifier: ModuleType, root: Path, relative: str, change: Callable[[str], str], message: str
) -> None:
    _edit(root, relative, change)

    with pytest.raises(verifier.LockValidationError, match=message):
        verifier.validate_repository_locks(root)
    assert verifier.main(["--root", str(root)]) == 1


def test_consistent_version_drift_from_windows_is_rejected(
    verifier: ModuleType, root: Path
) -> None:
    _edit(root, PIP_IN, _replace("gemmi==0.7.5", "gemmi==0.7.6"))
    _edit(root, PIP_LOCK, _replace("gemmi==0.7.5", "gemmi==0.7.6"))

    with pytest.raises(verifier.LockValidationError, match="gemmi: Windows 0.7.5 / Linux 0.7.6"):
        verifier.validate_repository_locks(root)


def test_windows_only_dependency_is_rejected_even_when_locked(
    verifier: ModuleType, root: Path
) -> None:
    pin = "win32-setctime==1.2.0"
    _edit(root, PIP_IN, lambda text: text + pin + "\n")
    _edit(root, PIP_LOCK, lambda text: text + f"{pin} --hash=sha256:{'0' * 64}\n")

    with pytest.raises(verifier.LockValidationError, match="Windows-only.*win32-setctime"):
        verifier.validate_repository_locks(root)


def test_missing_lock_file_is_rejected(verifier: ModuleType, root: Path) -> None:
    (root / PIP_LOCK).unlink()

    with pytest.raises(verifier.LockValidationError, match="missing"):
        verifier.validate_repository_locks(root)


# --- Runtime with synthetic installed metadata -----------------------------------------


@pytest.fixture
def runtime(verifier: ModuleType, tmp_path: Path) -> tuple[Path, dict[str, str]]:
    """SYNTHETIC conda-meta records and distribution versions matching the lock."""
    prefix = tmp_path / "synthetic-prefix"
    conda_meta = prefix / "conda-meta"
    conda_meta.mkdir(parents=True)
    text = (REPOSITORY_ROOT / CONDA).read_text(encoding="utf-8")
    for artifact in verifier.parse_conda_lock(text):
        record = {
            "name": artifact.name,
            "version": artifact.version,
            "build": artifact.build,
            "url": artifact.url,
            "sha256": artifact.sha256,
            "fn": artifact.filename,
            "synthetic": True,
        }
        stem = f"{artifact.name}-{artifact.version}-{artifact.build}"
        (conda_meta / f"{stem}.json").write_text(json.dumps(record), encoding="utf-8")
    pins = verifier.parse_pip_pins(
        (REPOSITORY_ROOT / PIP_LOCK).read_text(encoding="utf-8"),
        source=Path(PIP_LOCK),
        hashes_required=True,
    )
    versions = {**pins, **verifier.EXPECTED_CONDA_DISTRIBUTIONS}
    return prefix, versions


def _validate(
    verifier: ModuleType,
    prefix: Path,
    versions: dict[str, str],
    **overrides: object,
) -> None:
    def distribution_version(name: str) -> str:
        if name not in versions:
            raise verifier.importlib.metadata.PackageNotFoundError(name)
        return versions[name]

    arguments: dict[str, object] = {
        "prefix": prefix,
        "platform_name": "linux",
        "machine": "x86_64",
        "python_version": (3, 12, 13),
        "distribution_version": distribution_version,
    }
    arguments.update(overrides)
    verifier.validate_runtime(REPOSITORY_ROOT, **arguments)


def _record(prefix: Path, name: str) -> Path:
    return next(
        path
        for path in (prefix / "conda-meta").glob("*.json")
        if json.loads(path.read_text(encoding="utf-8"))["name"] == name
    )


def _set_field(prefix: Path, name: str, field: str, value: object) -> None:
    path = _record(prefix, name)
    record = json.loads(path.read_text(encoding="utf-8"))
    record[field] = value
    path.write_text(json.dumps(record), encoding="utf-8")


def test_matching_synthetic_runtime_passes(verifier: ModuleType, runtime) -> None:
    prefix, versions = runtime

    _validate(verifier, prefix, versions)


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"platform_name": "win32"}, "requires Linux"),
        ({"machine": "aarch64"}, "requires x86_64"),
        ({"python_version": (3, 12, 3)}, "Python 3.12.13, found 3.12.3"),
    ],
)
def test_wrong_host_or_interpreter_is_rejected(
    verifier: ModuleType, runtime, overrides: dict[str, object], message: str
) -> None:
    prefix, versions = runtime

    with pytest.raises(verifier.LockValidationError, match=message):
        _validate(verifier, prefix, versions, **overrides)


def test_non_conda_prefix_is_rejected(verifier: ModuleType, runtime, tmp_path: Path) -> None:
    _, versions = runtime

    with pytest.raises(verifier.LockValidationError, match="Conda environment"):
        _validate(verifier, tmp_path / "plain-venv", versions)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("sha256", "0" * 64),
        ("url", "https://conda.anaconda.org/conda-forge/linux-64/openmm-8.5.2-other_0.conda"),
        ("build", "py312_other_0"),
        ("version", "8.5.1"),
    ],
)
def test_installed_conda_artifact_identity_must_match_the_lock(
    verifier: ModuleType, runtime, field: str, value: str
) -> None:
    prefix, versions = runtime
    _set_field(prefix, "openmm", field, value)

    with pytest.raises(verifier.LockValidationError, match=f"conda openmm: {field}"):
        _validate(verifier, prefix, versions)


def test_missing_extra_and_unreadable_conda_records_are_all_reported(
    verifier: ModuleType, runtime
) -> None:
    prefix, versions = runtime
    _record(prefix, "pdbfixer").unlink()
    (prefix / "conda-meta" / "unlocked-1.0-0.json").write_text(
        json.dumps({"name": "unlocked", "version": "1.0", "build": "0"}), encoding="utf-8"
    )
    (prefix / "conda-meta" / "broken.json").write_text("{", encoding="utf-8")

    with pytest.raises(verifier.LockValidationError) as excinfo:
        _validate(verifier, prefix, versions)

    message = str(excinfo.value)
    assert "conda pdbfixer: not installed" in message
    assert "conda unlocked: installed but not in" in message
    assert "conda broken.json: unreadable record" in message


@pytest.mark.parametrize(
    ("name", "version", "message"),
    [
        ("packaging", "26.3", "python packaging: 26.3 (expected 26.2)"),
        ("pdbfixer", "1.12", "python pdbfixer: 1.12 (expected 1.12.0)"),
        ("openmm", "8.5.1", "python openmm: 8.5.1 (expected 8.5.2)"),
        ("rdkit", None, "python rdkit: missing"),
    ],
)
def test_installed_python_metadata_must_match_the_lock(
    verifier: ModuleType, runtime, name: str, version: str | None, message: str
) -> None:
    prefix, versions = runtime
    if version is None:
        del versions[name]
    else:
        versions[name] = version

    with pytest.raises(verifier.LockValidationError, match=re.escape(message)):
        _validate(verifier, prefix, versions)
