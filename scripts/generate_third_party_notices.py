"""Generate the legal payload shipped by Ankora's Windows installer.

The generator deliberately works from the artifacts that become part of the
application instead of treating the development environment as distributable.
PyInstaller's analysis is authoritative for Python/Conda files, package-lock's
production closure is a conservative inventory for the minified web bundle,
and Cargo's normal dependency graph identifies code linked into the shell.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import importlib.metadata
import json
import os
import re
import subprocess
import sys
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any, cast

from packaging.version import Version

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ANALYSIS = (
    ROOT
    / "build"
    / "windows-runtime"
    / "pyinstaller"
    / "ankora_backend"
    / "Analysis-00.toc"
)
DEFAULT_OUTPUT = ROOT / "apps" / "desktop" / "src-tauri" / "resources" / "legal"
PYTHON_LOCKS = (
    ROOT / "requirements" / "windows-py312.lock",
    ROOT / "requirements" / "windows-packaging.lock",
)
EXTERNAL_TOOLS = (
    "AutoDock Vina",
    "AutoGrid4",
    "AutoDock4",
    "AutoDock-GPU",
    "GNINA",
    "P2Rank",
)
LICENSE_FILE_RE = re.compile(
    r"^(?:license|licence|copying|copyright|notice|third[-_ ]party)", re.IGNORECASE
)
SPDX_OVERRIDES = {
    "griddataformats": "LGPL-3.0-or-later",
    "meeko": "LGPL-2.1-or-later",
    "openmm": "LGPL-3.0-or-later",
    "propka": "LGPL-2.1-or-later",
}
PYTHON_LICENSE_SUPPLEMENTS = {
    "loguru": ROOT / "resources" / "legal-sources" / "loguru-0.7.3-LICENSE.txt",
}


@dataclass
class Component:
    category: str
    name: str
    version: str
    license: str
    source_url: str
    license_documents: list[tuple[str, str]] = field(default_factory=list)
    evidence: str = ""

    @property
    def key(self) -> tuple[str, str, str]:
        return (self.category.casefold(), self.name.casefold(), self.version)


def normalize_name(value: str) -> str:
    return re.sub(r"[-_.]+", "-", value).casefold()


def stable_casefold_key(value: str) -> tuple[str, tuple[tuple[str, bool], ...], str]:
    """Sort case-insensitively with a deterministic lower-before-upper tie break."""
    return (
        value.casefold(),
        tuple((character.casefold(), character.isupper()) for character in value),
        value,
    )


def read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8").replace("\r\n", "\n").strip()
    except (OSError, UnicodeError):
        try:
            return path.read_text(encoding="latin-1").replace("\r\n", "\n").strip()
        except (OSError, UnicodeError):
            return None


def license_files(
    root: Path,
    candidates: Iterable[Path],
    *,
    include_all: bool = False,
) -> list[tuple[str, str]]:
    documents: list[tuple[str, str]] = []
    seen: set[str] = set()
    for candidate in sorted(
        candidates,
        key=lambda item: (item.as_posix().casefold(), item.as_posix()),
    ):
        if not candidate.is_file() or (
            not include_all and not LICENSE_FILE_RE.match(candidate.name)
        ):
            continue
        text = read_text(candidate)
        if not text:
            continue
        digest = hashlib.sha256(text.encode()).hexdigest()
        if digest in seen:
            continue
        seen.add(digest)
        try:
            label = candidate.relative_to(root).as_posix()
        except ValueError:
            label = candidate.name
        documents.append((label, text))
    return documents


def clean_license(metadata: Any, name: str) -> str:
    override = SPDX_OVERRIDES.get(normalize_name(name))
    if override:
        return override
    expression = metadata.get("License-Expression") if metadata else None
    if expression:
        return str(expression).strip()
    classifiers = metadata.get_all("Classifier") if metadata else []
    license_classifiers = [
        value.removeprefix("License :: ").strip()
        for value in classifiers or []
        if value.startswith("License :: ")
    ]
    if license_classifiers:
        return " OR ".join(license_classifiers)
    value = str(metadata.get("License", "") if metadata else "").strip()
    if value and "\n" not in value and len(value) <= 180:
        return value
    return "See bundled license text"


def python_lock_versions() -> dict[str, str]:
    versions: dict[str, str] = {}
    pattern = re.compile(r"^([A-Za-z0-9_.-]+)==([^\s]+)")
    for lock in PYTHON_LOCKS:
        for line in lock.read_text(encoding="utf-8").splitlines():
            match = pattern.match(line)
            if match:
                versions[normalize_name(match.group(1))] = match.group(2)
    return versions


def analysis_sources(path: Path) -> tuple[set[str], set[Path]]:
    payload = ast.literal_eval(path.read_text(encoding="utf-8"))
    module_names: set[str] = set()
    source_paths: set[Path] = set()
    for index in (11, 13, 14, 15, 18, 19):
        for item in payload[index]:
            if not isinstance(item, (tuple, list)) or len(item) < 2:
                continue
            if index in (13, 14, 19):
                module_names.add(str(item[0]).split(".", 1)[0])
            candidate = Path(str(item[1]))
            if candidate.exists():
                source_paths.add(candidate.resolve())
    return module_names, source_paths


def distribution_documents(distribution: importlib.metadata.Distribution) -> list[tuple[str, str]]:
    files = distribution.files or []
    candidates = [
        distribution.locate_file(item) for item in files if LICENSE_FILE_RE.match(item.name)
    ]
    root = Path(str(distribution.locate_file("")))
    return license_files(root, (Path(str(item)) for item in candidates))


def python_components(analysis_path: Path) -> tuple[list[Component], set[Path]]:
    module_names, sources = analysis_sources(analysis_path)
    module_distributions = importlib.metadata.packages_distributions()
    selected = {
        normalize_name(distribution_name)
        for module_name in module_names
        for distribution_name in module_distributions.get(module_name, [])
    }
    selected.add("pyinstaller")  # its bootloader and runtime hooks are redistributed

    source_keys = {os.path.normcase(str(path)) for path in sources}
    components: list[Component] = []
    for distribution in importlib.metadata.distributions():
        name = distribution.metadata.get("Name") or ""
        normalized = normalize_name(name)
        if not name or normalized == "ankora-backend":
            continue
        files = distribution.files or []
        owns_file = any(
            os.path.normcase(str(Path(str(distribution.locate_file(item))).resolve()))
            in source_keys
            for item in files
        )
        if normalized not in selected and not owns_file:
            continue
        version = distribution.version
        documents = distribution_documents(distribution)
        supplement = PYTHON_LICENSE_SUPPLEMENTS.get(normalized)
        if not documents and supplement and supplement.is_file():
            text = read_text(supplement)
            if text:
                documents.append((supplement.name, text))
        components.append(
            Component(
                category="python",
                name=name,
                version=version,
                license=clean_license(distribution.metadata, name),
                source_url=f"https://pypi.org/project/{name}/{version}/",
                license_documents=documents,
                evidence="PyInstaller analysis",
            )
        )
    unique = {component.key: component for component in components}
    return sorted(unique.values(), key=lambda item: item.key), sources


def conda_components(sources: set[Path]) -> list[Component]:
    prefix = Path(sys.prefix).resolve()
    metadata_dir = prefix / "conda-meta"
    if not metadata_dir.is_dir():
        return []
    source_keys = {os.path.normcase(str(path)) for path in sources}
    components: list[Component] = []
    for metadata_path in sorted(metadata_dir.glob("*.json")):
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        matched = False
        for relative in metadata.get("files", []):
            candidate = (prefix / Path(*PurePosixPath(relative).parts)).resolve()
            if os.path.normcase(str(candidate)) in source_keys:
                matched = True
                break
        if not matched:
            continue
        package_root_text = metadata.get("extracted_package_dir")
        package_root = Path(package_root_text) if package_root_text else Path()
        candidates: list[Path] = []
        if package_root.is_dir():
            info_licenses = package_root / "info" / "licenses"
            if info_licenses.is_dir():
                candidates.extend(path for path in info_licenses.rglob("*") if path.is_file())
            candidates.extend(path for path in package_root.glob("*LICENSE*") if path.is_file())
            candidates.extend(path for path in package_root.glob("COPYING*") if path.is_file())
        source_url = str(metadata.get("url") or metadata.get("channel") or "")
        recipe = package_root / "info" / "recipe" / "meta.yaml"
        recipe_text = read_text(recipe) if recipe.is_file() else None
        if recipe_text:
            git_url_match = re.search(r"(?m)^\s*git_url:\s*(https://\S+?)\s*$", recipe_text)
            git_rev_match = re.search(r"(?m)^\s*git_rev:\s*([^\s#]+)", recipe_text)
            if git_url_match and git_rev_match:
                repository = git_url_match.group(1).removesuffix(".git")
                source_url = f"{repository}/tree/{git_rev_match.group(1)}"
        components.append(
            Component(
                category="native-runtime",
                name=str(metadata["name"]),
                version=str(metadata["version"]),
                license=str(metadata.get("license") or "See bundled vendor terms"),
                source_url=source_url,
                license_documents=license_files(
                    package_root,
                    candidates,
                    include_all=True,
                ),
                evidence="PyInstaller file mapped to locked Conda package",
            )
        )
    return components


def node_components() -> list[Component]:
    lock = json.loads((ROOT / "package-lock.json").read_text(encoding="utf-8"))
    components: list[Component] = []
    for package_path, entry in sorted(lock.get("packages", {}).items()):
        if not package_path.startswith("node_modules/") or entry.get("dev") is True:
            continue
        package_root = ROOT / Path(*PurePosixPath(package_path).parts)
        package_json = package_root / "package.json"
        if not package_json.is_file():
            # Optional packages for other operating systems are not redistributed.
            continue
        package = json.loads(package_json.read_text(encoding="utf-8"))
        name = str(package.get("name") or package_path.rsplit("node_modules/", 1)[-1])
        if entry.get("link") is True or name.startswith("@ankora/"):
            continue
        version = str(entry.get("version") or package.get("version") or "unknown")
        license_value = package.get("license") or entry.get("license") or "See bundled license text"
        if isinstance(license_value, dict):
            license_value = license_value.get("type", "See bundled license text")
        source_url = str(entry.get("resolved") or "")
        candidates = [path for path in package_root.iterdir() if path.is_file()]
        components.append(
            Component(
                category="web",
                name=name,
                version=version,
                license=str(license_value),
                source_url=source_url,
                license_documents=license_files(package_root, candidates),
                evidence="installed package in package-lock production closure",
            )
        )
    return components


def cargo_metadata() -> dict[str, Any]:
    command = [
        "cargo",
        "metadata",
        "--format-version",
        "1",
        "--filter-platform",
        "x86_64-pc-windows-msvc",
        "--manifest-path",
        str(ROOT / "apps" / "desktop" / "src-tauri" / "Cargo.toml"),
    ]
    result = subprocess.run(
        command,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return cast(dict[str, Any], json.loads(result.stdout))


def rust_components() -> list[Component]:
    metadata = cargo_metadata()
    root_id = next(
        package["id"] for package in metadata["packages"] if package["name"] == "ankora-desktop"
    )
    nodes = {node["id"]: node for node in metadata["resolve"]["nodes"]}
    selected: set[str] = set()
    pending = [root_id]
    while pending:
        package_id = pending.pop()
        if package_id in selected:
            continue
        selected.add(package_id)
        for dependency in nodes.get(package_id, {}).get("deps", []):
            kinds = dependency.get("dep_kinds") or [{}]
            if any(kind.get("kind") in (None, "normal") for kind in kinds):
                pending.append(dependency["pkg"])

    components: list[Component] = []
    for package in metadata["packages"]:
        if package["id"] not in selected or package["id"] == root_id:
            continue
        package_root = Path(package["manifest_path"]).parent
        candidates = [path for path in package_root.iterdir() if path.is_file()]
        source_url = f"https://crates.io/api/v1/crates/{package['name']}/{package['version']}/download"
        components.append(
            Component(
                category="rust",
                name=str(package["name"]),
                version=str(package["version"]),
                license=str(package.get("license") or "See bundled license text"),
                source_url=source_url,
                license_documents=license_files(package_root, candidates),
                evidence="Cargo normal dependency graph for Windows x86-64",
            )
        )
    return sorted(components, key=lambda item: item.key)


def packaging_components() -> list[Component]:
    nsis_copying = ROOT / "resources" / "legal-sources" / "NSIS_COPYING.txt"
    nsis_documents: list[tuple[str, str]] = []
    if nsis_copying.is_file():
        text = read_text(nsis_copying)
        if text:
            nsis_documents.append(("COPYING", text))
    return [
        Component(
            category="installer",
            name="Nullsoft Scriptable Install System",
            version="3.11",
            license="zlib/libpng and component licenses described in COPYING",
            source_url="https://nsis.sourceforge.io/Download",
            license_documents=nsis_documents,
            evidence="Tauri NSIS installer stub",
        )
    ]


def validate_components(components: list[Component]) -> None:
    if not components:
        raise RuntimeError("No third-party components were identified.")
    duplicates: set[tuple[str, str, str]] = set()
    seen: set[tuple[str, str, str]] = set()
    for component in components:
        if component.key in seen:
            duplicates.add(component.key)
        seen.add(component.key)
        if not component.name or not component.version or not component.license:
            raise RuntimeError(f"Incomplete component metadata: {component!r}")
        if not component.source_url.startswith("https://"):
            raise RuntimeError(f"Missing HTTPS source for {component.name} {component.version}")
    if duplicates:
        raise RuntimeError(f"Duplicate component records: {sorted(duplicates)!r}")
    bundled_names = {normalize_name(item.name) for item in components}
    for tool in EXTERNAL_TOOLS:
        if normalize_name(tool) in bundled_names:
            raise RuntimeError(f"External tool was incorrectly inventoried as bundled: {tool}")


def render_inventory(components: list[Component]) -> tuple[bytes, dict[str, str]]:
    texts: dict[str, str] = {}
    records: list[dict[str, Any]] = []
    for component in sorted(components, key=lambda item: item.key):
        documents = []
        for label, text in component.license_documents:
            digest = hashlib.sha256(text.encode()).hexdigest()
            texts[digest] = text
            documents.append({"name": label, "sha256": digest})
        records.append(
            {
                "category": component.category,
                "name": component.name,
                "version": component.version,
                "license": component.license,
                "source_url": component.source_url,
                "evidence": component.evidence,
                "license_documents": documents,
            }
        )
    payload = {
        "schema_version": 1,
        "scope": "Components redistributed by the Ankora 0.1.0 Windows installer",
        "inventory_policy": {
            "python": "exact PyInstaller analysis plus exact Conda providers of copied files",
            "web": "installed package-lock production closure; conservative for tree-shaking",
            "rust": "exact Cargo normal dependency graph for Windows x86-64",
            "external_scientific_tools": "not bundled",
            "webview2": (
                "Evergreen runtime/bootstrapper not bundled; fetched from Microsoft "
                "only when missing"
            ),
        },
        "excluded_external_tools": list(EXTERNAL_TOOLS),
        "components": records,
    }
    data = (json.dumps(payload, indent=2, ensure_ascii=False) + "\n").encode()
    return data, texts


def render_source_availability(components: list[Component]) -> bytes:
    reciprocal = [
        component
        for component in components
        if any(token in component.license.upper() for token in ("GPL", "MPL"))
    ]
    lines = [
        "ANKORA THIRD-PARTY SOURCE AVAILABILITY",
        "======================================",
        "",
        "Ankora redistributes the unmodified components below in executable form.",
        "The version-specific locations provide the source or the release page from",
        "which source can be obtained. Ankora does not restrict replacement or reverse",
        "engineering of LGPL-covered libraries for debugging modifications to them.",
        "The corresponding Ankora application source and deterministic rebuild scripts",
        "are published at https://github.com/Olascoaga/Ankora and will be frozen with",
        "each release tag (for this package: v0.1.0). No listed reciprocal component",
        "has been locally modified by Ankora.",
        "",
    ]
    for component in sorted(reciprocal, key=lambda item: item.key):
        lines.append(
            f"- [{component.category}] {component.name} {component.version} "
            f"({component.license}): {component.source_url}"
        )
    lines.extend(
        [
            "",
            "EXTERNAL SCIENTIFIC TOOLS NOT REDISTRIBUTED",
            "--------------------------------------------",
            "The following tools may be detected and launched from user-configured paths,",
            "but are not included in the Ankora installer and are not covered by its",
            "third-party inventory:",
            "",
            *(f"- {tool}" for tool in EXTERNAL_TOOLS),
            "",
        ]
    )
    return "\n".join(lines).encode()


def render_notices(components: list[Component], texts: dict[str, str]) -> bytes:
    usage: dict[str, list[str]] = {}
    labels: dict[str, set[str]] = {}
    for component in components:
        identity = f"[{component.category}] {component.name} {component.version}"
        for label, text in component.license_documents:
            digest = hashlib.sha256(text.encode()).hexdigest()
            usage.setdefault(digest, []).append(identity)
            labels.setdefault(digest, set()).add(label)

    lines = [
        "ANKORA THIRD-PARTY NOTICES",
        "==========================",
        "",
        "This file accompanies Ankora 0.1.0. Ankora itself is licensed under MIT; see",
        "ANKORA_LICENSE.txt. The inventory was generated from the frozen backend, the",
        "web production dependency closure, and the Windows Rust dependency graph.",
        "Component names, versions, license identifiers, source locations, and evidence",
        "are recorded in THIRD_PARTY_INVENTORY.json.",
        "",
        f"Components inventoried: {len(components)}",
        f"Unique license/notice documents: {len(texts)}",
        "",
        "The scientific executables AutoDock Vina, AutoGrid4, AutoDock4, AutoDock-GPU,",
        "GNINA, and P2Rank are not distributed by this installer.",
        "The WebView2 Evergreen Runtime and bootstrapper are also not bundled; the",
        "installer requests Microsoft's bootstrapper only when the runtime is absent.",
        "",
        "COMPONENT INDEX",
        "---------------",
    ]
    for component in sorted(components, key=lambda item: item.key):
        lines.append(
            f"- [{component.category}] {component.name} {component.version} | "
            f"{component.license} | {component.source_url}"
        )
    lines.extend(["", "LICENSE AND NOTICE TEXTS", "------------------------", ""])
    for digest in sorted(texts):
        lines.extend(
            [
                "=" * 78,
                f"SHA-256: {digest}",
                "Used by:",
                *(
                    f"  - {identity}"
                    for identity in sorted(
                        usage[digest], key=stable_casefold_key
                    )
                ),
                "Original file name(s): "
                + ", ".join(
                    sorted(labels[digest], key=stable_casefold_key)
                ),
                "=" * 78,
                texts[digest],
                "",
            ]
        )
    return "\n".join(lines).encode()


def generated_files(analysis_path: Path) -> dict[str, bytes]:
    python, sources = python_components(analysis_path)
    discovered = (
        python
        + conda_components(sources)
        + node_components()
        + rust_components()
        + packaging_components()
    )
    merged: dict[tuple[str, str, str], Component] = {}
    for component in discovered:
        existing = merged.get(component.key)
        if existing is None:
            merged[component.key] = component
            continue
        documents = existing.license_documents + component.license_documents
        by_digest = {
            hashlib.sha256(text.encode()).hexdigest(): (label, text)
            for label, text in documents
        }
        existing.license_documents = list(by_digest.values())
    components = list(merged.values())
    validate_components(components)
    inventory, texts = render_inventory(components)
    return {
        "ANKORA_LICENSE.txt": (ROOT / "LICENSE").read_bytes(),
        "SOURCE_AVAILABILITY.txt": render_source_availability(components),
        "THIRD_PARTY_INVENTORY.json": inventory,
        "THIRD_PARTY_NOTICES.txt": render_notices(components, texts),
    }


def verify_static_inventory(output_dir: Path) -> None:
    inventory_path = output_dir / "THIRD_PARTY_INVENTORY.json"
    payload = json.loads(inventory_path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != 1:
        raise RuntimeError("Unsupported third-party inventory schema.")
    components = payload.get("components") or []
    if not components:
        raise RuntimeError("Third-party inventory is empty.")
    by_category: dict[str, set[tuple[str, str]]] = {}
    for component in components:
        by_category.setdefault(component["category"], set()).add(
            (normalize_name(component["name"]), component["version"])
        )
    lock_versions = python_lock_versions()
    native_versions = dict(by_category.get("native-runtime", set()))
    for component in components:
        if component["category"] == "python":
            normalized = normalize_name(component["name"])
            expected = lock_versions.get(normalized) or native_versions.get(normalized)
            if expected is None or Version(expected) != Version(component["version"]):
                raise RuntimeError(
                    f"Python inventory drift for {component['name']}: "
                    f"recorded {component['version']}, lock {expected or 'missing'}"
                )
    expected_web = {(normalize_name(item.name), item.version) for item in node_components()}
    if by_category.get("web", set()) != expected_web:
        raise RuntimeError("Web production dependency inventory drifted from package-lock.json.")
    expected_rust = {(normalize_name(item.name), item.version) for item in rust_components()}
    if by_category.get("rust", set()) != expected_rust:
        raise RuntimeError("Rust runtime inventory drifted from Cargo metadata.")
    inventory_names = {normalize_name(item["name"]) for item in components}
    for tool in EXTERNAL_TOOLS:
        if normalize_name(tool) in inventory_names:
            raise RuntimeError(f"External tool incorrectly listed as bundled: {tool}")
    for required in (
        "ANKORA_LICENSE.txt",
        "SOURCE_AVAILABILITY.txt",
        "THIRD_PARTY_NOTICES.txt",
    ):
        if not (output_dir / required).is_file():
            raise RuntimeError(f"Missing legal payload file: {required}")
    notices = (output_dir / "THIRD_PARTY_NOTICES.txt").read_text(encoding="utf-8")
    for component in components:
        for document in component.get("license_documents", []):
            if f"SHA-256: {document['sha256']}" not in notices:
                raise RuntimeError(
                    f"License text for {component['name']} is missing from notices."
                )
    source_availability = (output_dir / "SOURCE_AVAILABILITY.txt").read_text(
        encoding="utf-8"
    )
    for component in components:
        if (
            any(token in component["license"].upper() for token in ("GPL", "MPL"))
            and component["source_url"] not in source_availability
        ):
            raise RuntimeError(
                f"Source availability missing for {component['name']} {component['version']}."
            )


def write_or_check(files: dict[str, bytes], output_dir: Path, check: bool) -> None:
    mismatches: list[str] = []
    for name, expected in files.items():
        destination = output_dir / name
        if check:
            actual = destination.read_bytes() if destination.is_file() else None
            if actual != expected:
                mismatches.append(name)
        else:
            output_dir.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(expected)
    if mismatches:
        raise RuntimeError(
            "Third-party legal payload is stale: "
            + ", ".join(mismatches)
            + ". Regenerate it with scripts/generate_third_party_notices.py."
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--analysis", type=Path, default=DEFAULT_ANALYSIS)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--check", action="store_true")
    parser.add_argument(
        "--static-check",
        action="store_true",
        help="Verify tracked payload and Python-lock consistency without PyInstaller output.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    output_dir = args.output_dir.resolve()
    if args.static_check:
        verify_static_inventory(output_dir)
        print("Third-party legal payload passed static verification.")
        return 0
    analysis_path = args.analysis.resolve()
    if not analysis_path.is_file():
        raise RuntimeError(f"PyInstaller analysis not found: {analysis_path}")
    files = generated_files(analysis_path)
    write_or_check(files, output_dir, args.check)
    action = "matches" if args.check else "generated at"
    print(f"Third-party legal payload {action} {output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
