"""CI guard enforcing ADR-031 installer-size budgets and benchmark-harness separation.

Usage:
    python scripts/check_v02_installer_budget.py
    python scripts/check_v02_installer_budget.py --windows-installer path/to/setup.exe --json
    python scripts/check_v02_installer_budget.py --linux-deb path/to/pkg.deb --linux-tar-zst path/to/pkg.tar.zst

Strictly relies on the Python 3.12 standard library so it runs inside any CI or
clean-room environment with `python -S`.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
BUDGET_MANIFEST_PATH = ROOT / "environment" / "v02-installer-size-budget.json"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
PIN_RE = re.compile(r"^([A-Za-z0-9_.-]+)==(\S+)")

# External benchmark / container / heavy ML packages strictly forbidden inside
# the shipped offline Ankora desktop product (`ADR-031 §1` and roadmap §3).
FORBIDDEN_PRODUCT_PACKAGES = frozenset(
    {
        "dockm8",
        "docker",
        "podman",
        "streamlit",
        "torch",
        "torchvision",
        "torchaudio",
        "dgl",
        "spyrmsd",
        "oddt",
        "korp-pl",
        "plants",
        "smina",
        "qvina",
        "qvina2",
        "qvina-w",
        "deepcoy",
    }
)

FORBIDDEN_BACKEND_IMPORT_ROOTS = frozenset(
    {
        "benchmarks",
        "dockm8",
        "docker",
        "podman",
        "streamlit",
        "torch",
        "dgl",
        "oddt",
    }
)


class BudgetGuardError(ValueError):
    """Raised when an ADR-031 size budget or separation invariant is violated."""


def _normalize_pkg(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _sha256_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    total = 0
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
            total += len(chunk)
    return digest.hexdigest(), total


def load_budget_manifest(repo_root: Path = ROOT) -> dict[str, Any]:
    path = repo_root / "environment" / "v02-installer-size-budget.json"
    if not path.is_file():
        raise BudgetGuardError(f"Missing ADR-031 budget manifest: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as err:
        raise BudgetGuardError(f"Budget manifest is not valid JSON: {err}") from err
    if not isinstance(data, dict):
        raise BudgetGuardError("Budget manifest root must be a JSON object")
    if data.get("schema_version") != 1 or data.get("adr") != "ADR-031":
        raise BudgetGuardError(
            "Budget manifest must declare schema_version=1 and adr='ADR-031'"
        )
    baseline_commit = str(data.get("baseline_commit", ""))
    if not SHA256_RE.match(baseline_commit) and not re.match(
        r"^[0-9a-f]{40}$", baseline_commit
    ):
        raise BudgetGuardError("Invalid baseline_commit hash in budget manifest")

    published = data.get("published_release_baselines")
    historical = data.get("historical_tracked_doc_baselines")
    if not isinstance(published, dict) or not isinstance(historical, dict):
        raise BudgetGuardError(
            "Budget manifest must reconcile both published_release_baselines and "
            "historical_tracked_doc_baselines"
        )
    for key in ("windows_x64_setup_exe", "linux_x86_64_deb", "linux_x86_64_tar_zst"):
        pub = published.get(key)
        hist = historical.get(key)
        if not isinstance(pub, dict) or not isinstance(hist, dict):
            raise BudgetGuardError(f"Missing baseline entry {key!r} in budget manifest")
        if not isinstance(pub.get("size_bytes"), int) or pub["size_bytes"] <= 0:
            raise BudgetGuardError(f"Invalid published size_bytes for {key!r}")
        if not SHA256_RE.match(str(pub.get("sha256", ""))):
            raise BudgetGuardError(f"Invalid published sha256 for {key!r}")
        if not isinstance(hist.get("size_bytes"), int) or hist["size_bytes"] <= 0:
            raise BudgetGuardError(f"Invalid historical size_bytes for {key!r}")

    milestones = data.get("milestone_budgets_bytes")
    if not isinstance(milestones, dict):
        raise BudgetGuardError("Missing milestone_budgets_bytes in budget manifest")
    for zero_ms in ("M0", "M1", "M2", "M4", "M5", "M6", "M6.5"):
        entry = milestones.get(zero_ms)
        if not isinstance(entry, dict) or entry.get("max_delta_bytes") != 0:
            raise BudgetGuardError(
                f"ADR-031 requires {zero_ms} max_delta_bytes == 0; found {entry!r}"
            )
        if entry.get("new_dependencies"):
            raise BudgetGuardError(
                f"ADR-031 forbids undeclared dependencies in {zero_ms}: {entry['new_dependencies']}"
            )

    m3 = milestones.get("M3")
    if not isinstance(m3, dict):
        raise BudgetGuardError("Missing M3 budget declaration")
    m3_cap = m3.get("max_delta_bytes")
    m3_measured = m3.get("measured_wheel_bytes")
    m3_sha = m3.get("measured_wheel_sha256")
    if (
        not isinstance(m3_cap, int)
        or m3_cap <= 0
        or m3_cap > 1_048_576
        or not isinstance(m3_measured, int)
        or m3_measured <= 0
        or m3_measured > m3_cap
        or not SHA256_RE.match(str(m3_sha or ""))
    ):
        raise BudgetGuardError(f"Invalid or over-budget M3 wheel declaration: {m3!r}")

    return data


def audit_dependency_separation(repo_root: Path = ROOT) -> dict[str, Any]:
    """Verify ADR-031 §1: no benchmark/container deps in product files or backend imports."""
    checked_req_files = [
        repo_root / "backend" / "pyproject.toml",
        repo_root / "requirements" / "windows-py312.in",
        repo_root / "requirements" / "windows-py312.lock",
        repo_root / "requirements" / "linux-py312.in",
        repo_root / "requirements" / "linux-py312.lock",
    ]
    forbidden_hits: list[str] = []
    posebusters_versions: dict[str, str] = {}

    for req_path in checked_req_files:
        if not req_path.is_file():
            raise BudgetGuardError(
                f"Required product dependency file missing: {req_path}"
            )
        rel = req_path.relative_to(repo_root).as_posix()
        text = req_path.read_text(encoding="utf-8")
        for line_no, raw_line in enumerate(text.splitlines(), start=1):
            stripped = raw_line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            pin_match = PIN_RE.match(stripped)
            if pin_match:
                pkg = _normalize_pkg(pin_match.group(1))
                ver = pin_match.group(2)
                if pkg in FORBIDDEN_PRODUCT_PACKAGES:
                    forbidden_hits.append(f"{rel}:{line_no} ({pkg}=={ver})")
                if pkg == "posebusters":
                    posebusters_versions[rel] = ver
            else:
                # Check pyproject.toml dependency strings cleanly
                for token in re.findall(
                    r'"([A-Za-z0-9_.-]+)\s*(?:[=<>!~]|")', stripped
                ):
                    pkg = _normalize_pkg(token)
                    if pkg in FORBIDDEN_PRODUCT_PACKAGES:
                        forbidden_hits.append(f"{rel}:{line_no} ({pkg})")

    # Scan backend Python AST imports for forbidden external harness / container coupling.
    backend_src = repo_root / "backend" / "src" / "ankora_backend"
    scanned_py_files = 0
    if backend_src.is_dir():
        for py_path in sorted(backend_src.rglob("*.py")):
            scanned_py_files += 1
            tree = ast.parse(py_path.read_text(encoding="utf-8"), filename=str(py_path))
            rel = py_path.relative_to(repo_root).as_posix()
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        root_mod = alias.name.split(".", 1)[0].lower()
                        if root_mod in FORBIDDEN_BACKEND_IMPORT_ROOTS:
                            forbidden_hits.append(
                                f"{rel}:{node.lineno} import {alias.name}"
                            )
                elif isinstance(node, ast.ImportFrom) and node.module:
                    root_mod = node.module.split(".", 1)[0].lower()
                    if root_mod in FORBIDDEN_BACKEND_IMPORT_ROOTS:
                        forbidden_hits.append(f"{rel}:{node.lineno} from {node.module}")

    if forbidden_hits:
        raise BudgetGuardError(
            "ADR-031 §1 hard architectural separation violated: "
            + "; ".join(forbidden_hits)
        )

    return {
        "checked_dependency_files": len(checked_req_files),
        "scanned_backend_python_files": scanned_py_files,
        "posebusters_pins": posebusters_versions,
        "forbidden_hits": [],
    }


def check_packaged_artifact(
    *,
    artifact_key: str,
    artifact_path: Path,
    manifest_data: dict[str, Any],
) -> dict[str, Any]:
    """Measure a built installer/archive against baseline + cumulative v0.2 byte cap."""
    resolved = artifact_path.resolve()
    if not resolved.is_file():
        raise BudgetGuardError(
            f"Packaged artifact not found for {artifact_key}: {artifact_path}"
        )
    baseline = manifest_data["published_release_baselines"][artifact_key]
    baseline_bytes = int(baseline["size_bytes"])
    milestones = manifest_data["milestone_budgets_bytes"]
    cumulative_budget_bytes = sum(
        int(entry["max_delta_bytes"])
        for name, entry in milestones.items()
        if name in {"M0", "M1", "M2", "M3", "M4", "M5", "M6", "M6.5"}
        and isinstance(entry, dict)
        and isinstance(entry.get("max_delta_bytes"), int)
    )
    digest, measured_bytes = _sha256_file(resolved)
    delta_bytes = measured_bytes - baseline_bytes
    max_allowed_bytes = baseline_bytes + cumulative_budget_bytes
    if measured_bytes > max_allowed_bytes:
        raise BudgetGuardError(
            f"ADR-031 §4 installer size budget EXCEEDED for {artifact_key}: "
            f"measured {measured_bytes:,} B vs baseline {baseline_bytes:,} B "
            f"(delta {delta_bytes:+,} B > allowed +{cumulative_budget_bytes:,} B)"
        )
    return {
        "artifact_key": artifact_key,
        "filename": resolved.name,
        "baseline_bytes": baseline_bytes,
        "measured_bytes": measured_bytes,
        "delta_bytes": delta_bytes,
        "max_delta_bytes": cumulative_budget_bytes,
        "sha256": digest,
        "within_budget": True,
    }


def run_budget_guard(
    *,
    repo_root: Path = ROOT,
    windows_installer: Path | None = None,
    linux_deb: Path | None = None,
    linux_tar_zst: Path | None = None,
) -> dict[str, Any]:
    manifest_data = load_budget_manifest(repo_root)
    separation = audit_dependency_separation(repo_root)
    measured_artifacts: list[dict[str, Any]] = []
    for key, path in (
        ("windows_x64_setup_exe", windows_installer),
        ("linux_x86_64_deb", linux_deb),
        ("linux_x86_64_tar_zst", linux_tar_zst),
    ):
        if path is not None:
            measured_artifacts.append(
                check_packaged_artifact(
                    artifact_key=key,
                    artifact_path=path,
                    manifest_data=manifest_data,
                )
            )
    milestones = manifest_data["milestone_budgets_bytes"]
    cumulative_budget_bytes = sum(
        int(entry["max_delta_bytes"])
        for name, entry in milestones.items()
        if name in {"M0", "M1", "M2", "M3", "M4", "M5", "M6", "M6.5"}
        and isinstance(entry, dict)
        and isinstance(entry.get("max_delta_bytes"), int)
    )
    return {
        "passed": True,
        "adr": "ADR-031",
        "baseline_tag": manifest_data["baseline_tag"],
        "baseline_commit": manifest_data["baseline_commit"],
        "cumulative_m0_m6_max_delta_bytes": cumulative_budget_bytes,
        "m3_measured_wheel_bytes": milestones["M3"]["measured_wheel_bytes"],
        "separation": separation,
        "measured_artifacts": measured_artifacts,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--windows-installer", type=Path, default=None)
    parser.add_argument("--linux-deb", type=Path, default=None)
    parser.add_argument("--linux-tar-zst", type=Path, default=None)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    try:
        report = run_budget_guard(
            windows_installer=args.windows_installer,
            linux_deb=args.linux_deb,
            linux_tar_zst=args.linux_tar_zst,
        )
    except BudgetGuardError as err:
        if args.json:
            print(json.dumps({"passed": False, "error": str(err)}, indent=2))
        else:
            print(f"BUDGET GUARD FAILED: {err}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        sep = report["separation"]
        print(
            "ADR-031 installer-size budget & separation guard passed: "
            f"M0-M6 cumulative cap {report['cumulative_m0_m6_max_delta_bytes']:,} B "
            f"(M3 wheel {report['m3_measured_wheel_bytes']:,} B), "
            f"{sep['scanned_backend_python_files']} backend Python modules audited, "
            f"{len(report['measured_artifacts'])} packaged artifact(s) checked."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
