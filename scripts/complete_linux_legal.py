"""Build and verify the complete Linux legal payload and GPL source companion archive.

Covers:
1. Frozen Python/Conda runtime closure from PyInstaller's Analysis-00.toc.
2. Web production dependency closure from package-lock.json.
3. Linux Rust shell dependency graph (`cargo metadata --filter-platform x86_64-unknown-linux-gnu`).
4. Core Linux scientific payload (`vina`, `autodock4`, `autogrid4`, multi-arch `autodock_gpu`,
   `p2rank` + 112 retained JAR dependencies, `Eclipse Temurin OpenJDK 21` per-module notices).
5. Optional offline GNINA 1.3.3 add-on pack corresponding GPL-2.0 sources (`gnina-source.tar.gz`
   and `openbabel-source.tar.gz`) inside `Ankora_0.1.0_linux-sources-companion.zip`.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any, cast

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts.build_linux_autodock_gpu import (
    DEFAULT_OUTPUT_ROOT as DEFAULT_GPU_BUILD_ROOT,
)
from scripts.build_linux_autodock_gpu import (
    verify_built_autodock_gpu,
)
from scripts.generate_third_party_notices import (
    EXTERNAL_TOOLS,
    PYTHON_LICENSE_SUPPLEMENTS,
    Component,
    analysis_sources,
    clean_license,
    distribution_documents,
    license_files,
    node_components,
    normalize_name,
    read_text,
    render_inventory,
    render_notices,
    render_source_availability,
    validate_components,
)
from scripts.linux_scientific_payload import (
    CACHE,
    GNINA_PACK_LOCK,
    ROOT,
    load_gnina_pack_lock,
    load_lock,
    safe_relative,
    sha256,
    verify,
)
from scripts.stage_linux_scientific_payload import (
    AUTODOCK_GPU_VARIANT,
    SLIM_P2RANK_VARIANT,
)
from scripts.stage_linux_scientific_payload import (
    DEFAULT_DESTINATION as DEFAULT_TOOLS_ROOT,
)
from scripts.validate_p2rank_variant import verify_tree

BOOST_LICENSE_SHA256 = "c9bff75738922193e67fa726fa225535870d2aa1059f91452c411736284ad566"
DEFAULT_ANALYSIS = ROOT / "build/linux-runtime/pyinstaller-slim/ankora_backend_linux/Analysis-00.toc"
DEFAULT_P2RANK_COMPANION = ROOT / "build/linux-runtime/p2rank-companion-cache"
DEFAULT_OUTPUT_LEGAL = ROOT / "build/linux-runtime/complete-legal"
DEFAULT_COMPANION_ZIP = ROOT / "build/linux-runtime/Ankora_0.1.0_linux-sources-companion.zip"


def _find_cargo_executable() -> str:
    found = shutil.which("cargo")
    if found:
        return found
    home_cargo = Path.home() / ".cargo/bin/cargo"
    if home_cargo.is_file() and os.access(home_cargo, os.X_OK):
        return str(home_cargo)
    raise FileNotFoundError("cargo executable not found on PATH or ~/.cargo/bin/cargo")


def _discover_site_search_paths(analysis_path: Path, sources: set[Path]) -> list[str]:
    candidates: list[Path] = []
    runtime_root = analysis_path.resolve().parents[2]
    packaging_site = runtime_root / "packaging-site"
    if packaging_site.is_dir():
        candidates.append(packaging_site)
    packaging_venv = runtime_root / "packaging-venv"
    if packaging_venv.is_dir():
        candidates.extend(sorted(packaging_venv.glob("lib/python*/site-packages")))
    for src in sources:
        for parent in src.parents:
            if parent.name in ("site-packages", "dist-packages", "packaging-site"):
                candidates.append(parent)
                break
    for entry in sys.path:
        if entry:
            p = Path(entry)
            if p.is_dir():
                candidates.append(p.resolve())
    seen: set[str] = set()
    ordered: list[str] = []
    for path in candidates:
        resolved = str(path.resolve())
        if resolved not in seen:
            seen.add(resolved)
            ordered.append(resolved)
    return ordered


def _discover_conda_prefixes(sources: set[Path]) -> list[Path]:
    prefixes: list[Path] = []
    seen: set[str] = set()
    current_prefix = Path(sys.prefix).resolve()
    if (current_prefix / "conda-meta").is_dir():
        prefixes.append(current_prefix)
        seen.add(str(current_prefix))
    for src in sources:
        for parent in src.parents:
            if (parent / "conda-meta").is_dir():
                key = str(parent.resolve())
                if key not in seen:
                    seen.add(key)
                    prefixes.append(parent.resolve())
                break
    return prefixes


def linux_python_components(analysis_path: Path) -> tuple[list[Component], set[Path]]:
    module_names, sources = analysis_sources(analysis_path)
    search_paths = _discover_site_search_paths(analysis_path, sources)

    module_distributions: dict[str, list[str]] = {}
    all_dists = list(importlib.metadata.distributions(path=search_paths))
    for dist in all_dists:
        dist_name = dist.metadata.get("Name") or ""
        if not dist_name:
            continue
        top_level = dist.read_text("top_level.txt")
        if top_level:
            for line in top_level.splitlines():
                pkg = line.strip()
                if pkg:
                    module_distributions.setdefault(pkg, []).append(dist_name)
        else:
            for item in dist.files or []:
                top = item.parts[0] if item.parts else ""
                if top and not top.endswith((".dist-info", ".egg-info", ".data")):
                    pkg = top.removesuffix(".py")
                    module_distributions.setdefault(pkg, []).append(dist_name)

    selected = {
        normalize_name(distribution_name)
        for module_name in module_names
        for distribution_name in module_distributions.get(module_name, [])
    }
    selected.add("pyinstaller")

    source_keys = {os.path.normcase(str(path)) for path in sources}
    components: list[Component] = []
    for distribution in all_dists:
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
                evidence="PyInstaller Linux analysis",
            )
        )
    unique: dict[tuple[str, str, str], Component] = {}
    for component in components:
        existing = unique.get(component.key)
        if existing is None or (not existing.license_documents and component.license_documents):
            unique[component.key] = component
    return sorted(unique.values(), key=lambda item: item.key), sources


def linux_conda_components(sources: set[Path]) -> list[Component]:
    source_keys = {os.path.normcase(str(path)) for path in sources}
    components: list[Component] = []
    for prefix in _discover_conda_prefixes(sources):
        metadata_dir = prefix / "conda-meta"
        for metadata_path in sorted(metadata_dir.glob("*.json")):
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            matched = any(
                os.path.normcase(str((prefix / Path(*PurePosixPath(rel).parts)).resolve()))
                in source_keys
                for rel in metadata.get("files", [])
            )
            if not matched:
                continue
            package_root_text = metadata.get("extracted_package_dir")
            package_root = Path(package_root_text) if package_root_text else Path()
            candidates: list[Path] = []
            if package_root.is_dir():
                info_licenses = package_root / "info/licenses"
                if info_licenses.is_dir():
                    candidates.extend(p for p in info_licenses.rglob("*") if p.is_file())
                candidates.extend(p for p in package_root.glob("*LICENSE*") if p.is_file())
                candidates.extend(p for p in package_root.glob("COPYING*") if p.is_file())
            source_url = str(metadata.get("url") or metadata.get("channel") or "")
            recipe = package_root / "info/recipe/meta.yaml"
            recipe_text = read_text(recipe) if recipe.is_file() else None
            if recipe_text:
                git_url_match = re.search(r"(?m)^\s*git_url:\s*(https://\S+?)\s*$", recipe_text)
                git_rev_match = re.search(r"(?m)^\s*git_rev:\s*([^\s#]+)", recipe_text)
                if git_url_match and git_rev_match:
                    repository = git_url_match.group(1).removesuffix(".git")
                    source_url = f"{repository}/tree/{git_rev_match.group(1)}"
            if not source_url.startswith("https://"):
                source_url = f"https://anaconda.org/conda-forge/{metadata['name']}"
            components.append(
                Component(
                    category="native-runtime",
                    name=str(metadata["name"]),
                    version=str(metadata["version"]),
                    license=str(metadata.get("license") or "See bundled vendor terms"),
                    source_url=source_url,
                    license_documents=license_files(package_root, candidates, include_all=True),
                    evidence="PyInstaller file mapped to locked Conda package",
                )
            )
    unique = {c.key: c for c in components}
    return sorted(unique.values(), key=lambda item: item.key)


def linux_rust_components() -> list[Component]:
    cargo = _find_cargo_executable()
    command = [
        cargo,
        "metadata",
        "--format-version",
        "1",
        "--filter-platform",
        "x86_64-unknown-linux-gnu",
        "--manifest-path",
        str(ROOT / "apps/desktop/src-tauri/Cargo.toml"),
    ]
    result = subprocess.run(
        command,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    metadata = cast(dict[str, Any], json.loads(result.stdout))
    root_id = next(
        pkg["id"] for pkg in metadata["packages"] if pkg["name"] == "ankora-desktop"
    )
    nodes = {node["id"]: node for node in metadata["resolve"]["nodes"]}
    selected: set[str] = set()
    pending = [root_id]
    while pending:
        pkg_id = pending.pop()
        if pkg_id in selected:
            continue
        selected.add(pkg_id)
        for dep in nodes.get(pkg_id, {}).get("deps", []):
            kinds = dep.get("dep_kinds") or [{}]
            if any(kind.get("kind") in (None, "normal") for kind in kinds):
                pending.append(dep["pkg"])

    components: list[Component] = []
    for pkg in metadata["packages"]:
        if pkg["id"] not in selected or pkg["id"] == root_id:
            continue
        pkg_root = Path(pkg["manifest_path"]).parent
        candidates = [p for p in pkg_root.iterdir() if p.is_file()]
        source_url = (
            f"https://crates.io/api/v1/crates/{pkg['name']}/{pkg['version']}/download"
        )
        components.append(
            Component(
                category="rust",
                name=str(pkg["name"]),
                version=str(pkg["version"]),
                license=str(pkg.get("license") or "See bundled license text"),
                source_url=source_url,
                license_documents=license_files(pkg_root, candidates),
                evidence="Cargo normal dependency graph for Linux x86-64",
            )
        )
    return sorted(components, key=lambda item: item.key)


def linux_generated_files(analysis_path: Path) -> dict[str, bytes]:
    python, sources = linux_python_components(analysis_path)
    discovered = (
        python
        + linux_conda_components(sources)
        + node_components()
        + linux_rust_components()
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
    inventory_bytes, texts = render_inventory(components)
    inventory = json.loads(inventory_bytes.decode("utf-8"))
    inventory["scope"] = "Components redistributed by the Ankora 0.1.0 Linux installer"
    inventory["inventory_policy"]["rust"] = (
        "exact Cargo normal dependency graph for Linux x86-64"
    )
    inventory["inventory_policy"].pop("webview2", None)
    inventory["inventory_policy"]["system_webview"] = (
        "host Ubuntu/Debian WebKitGTK 4.1 (`libwebkit2gtk-4.1-0`), dynamically linked"
    )
    return {
        "ANKORA_LICENSE.txt": (ROOT / "LICENSE").read_bytes(),
        "SOURCE_AVAILABILITY.txt": render_source_availability(components),
        "THIRD_PARTY_INVENTORY.json": (
            json.dumps(inventory, indent=2, ensure_ascii=False) + "\n"
        ).encode("utf-8"),
        "THIRD_PARTY_NOTICES.txt": render_notices(components, texts),
    }


def verify_p2rank_companion_against_staged_jars(
    tools: Path, p2rank_companion: Path
) -> dict[str, Any]:
    report_path = p2rank_companion / "source-companion.json"
    if not report_path.is_file():
        raise FileNotFoundError(f"Missing P2Rank source-companion.json at {report_path}")
    report = json.loads(report_path.read_text(encoding="utf-8"))
    if report.get("gaps"):
        raise ValueError(f"Unresolved P2Rank source companion gaps: {report['gaps']}")

    staged_jars = {
        p.relative_to(tools).as_posix(): sha256(p)
        for p in sorted((tools / "p2rank-2.5.1/bin").rglob("*.jar"))
        if p.is_file()
    }
    companion_jars = {item["file"]: item for item in report.get("components", [])}
    if set(staged_jars) != set(companion_jars):
        raise ValueError("Staged Linux P2Rank JAR set differs from reviewed source companion")
    for rel_jar, jar_sha in staged_jars.items():
        if companion_jars[rel_jar]["binary_sha256"] != jar_sha:
            raise ValueError(f"Staged P2Rank JAR SHA-256 mismatch: {rel_jar}")

    for source_id, src_record in report["sources"].items():
        src_path = p2rank_companion.joinpath(*safe_relative(src_record["file"]).parts)
        if src_path.is_symlink() or not src_path.is_file():
            raise FileNotFoundError(f"Missing companion source archive ({source_id}): {src_path}")
        if sha256(src_path) != src_record["sha256"]:
            raise ValueError(f"Companion source SHA-256 mismatch ({source_id}): {src_path}")

    for digest in report["documents"]:
        if not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ValueError(f"Invalid companion document digest: {digest}")
        doc_path = p2rank_companion / "documents" / digest
        if doc_path.is_symlink() or not doc_path.is_file() or sha256(doc_path) != digest:
            raise ValueError(f"Companion license document integrity failure: {digest}")

    return report


def assemble_linux_legal(
    *,
    analysis: Path = DEFAULT_ANALYSIS,
    tools: Path = DEFAULT_TOOLS_ROOT,
    gpu_build: Path = DEFAULT_GPU_BUILD_ROOT,
    p2rank_companion: Path = DEFAULT_P2RANK_COMPANION,
    cache: Path = CACHE,
    output_legal: Path = DEFAULT_OUTPUT_LEGAL,
    companion_zip_path: Path = DEFAULT_COMPANION_ZIP,
) -> dict[str, Any]:
    if output_legal.exists():
        raise FileExistsError(f"Output legal directory is create-only: {output_legal}")
    if companion_zip_path.exists():
        raise FileExistsError(f"Companion zip is create-only: {companion_zip_path}")

    verify_tree(tools)
    gpu_manifest = verify_built_autodock_gpu(gpu_build)
    gpu_source_zip = gpu_build / "autodock-gpu-1.6-ankora-source.zip"
    gpu_source_sha256 = sha256(gpu_source_zip)

    p2rank_report = verify_p2rank_companion_against_staged_jars(tools, p2rank_companion)
    lock_entries = {item["id"]: item for item in load_lock()}
    load_gnina_pack_lock()
    gnina_pack_lock_sha256 = sha256(GNINA_PACK_LOCK)

    linux_source_entries = [item for item in lock_entries.values() if item["role"] == "source"]
    for src_entry in linux_source_entries:
        verify(cache / src_entry["filename"], src_entry)

    boost_license_path = cache / "boost-LICENSE_1_0.txt"
    if not boost_license_path.is_file() or sha256(boost_license_path) != BOOST_LICENSE_SHA256:
        raise ValueError("Missing or unverified boost-LICENSE_1_0.txt in upstream cache")

    scientific_payload_sha256 = sha256(tools / "payload.json")
    base = linux_generated_files(analysis)

    # Build unified Linux source-companion manifest covering Core + GNINA + P2Rank JARs
    unified_sources: dict[str, dict[str, Any]] = dict(p2rank_report["sources"])
    for src_entry in linux_source_entries:
        arc_rel = f"sources/{src_entry['sha256'][:16]}-{src_entry['filename']}"
        existing = unified_sources.get(src_entry["id"])
        unified_sources[src_entry["id"]] = {
            "file": arc_rel,
            "sha256": src_entry["sha256"],
            "url": src_entry["url"],
            "documents": existing["documents"] if existing else [],
        }
    unified_sources["autodock-gpu-ankora-linux-source"] = {
        "file": "sources/autodock-gpu-1.6-ankora-source.zip",
        "sha256": gpu_source_sha256,
        "url": lock_entries["autodock-gpu-source"]["url"],
        "documents": [],
    }

    linux_companion_manifest: dict[str, Any] = {
        "schema_version": 1,
        "platform": "linux-x86_64",
        "status": "verified-linux-source-companion",
        "payload_sha256": scientific_payload_sha256,
        "gnina_pack_lock_sha256": gnina_pack_lock_sha256,
        "gpu_source_sha256": gpu_source_sha256,
        "components": p2rank_report["components"],
        "sources": unified_sources,
        "documents": p2rank_report["documents"],
        "gaps": [],
    }
    linux_companion_bytes = (
        json.dumps(linux_companion_manifest, indent=2) + "\n"
    ).encode("utf-8")
    linux_companion_sha256 = hashlib.sha256(linux_companion_bytes).hexdigest()

    inventory = json.loads(base["THIRD_PARTY_INVENTORY.json"].decode("utf-8"))
    inventory["excluded_external_tools"] = ["GNINA"]
    inventory["optional_offline_addon_packs"] = [
        {
            "pack_id": "gnina-1.3.3-cuda12.8-cudnn9.25-linux-x86_64",
            "gnina_version": "1.3.3",
            "lock_sha256": gnina_pack_lock_sha256,
            "corresponding_sources_in_companion": ["gnina-source", "openbabel-source"],
        }
    ]
    inventory["inventory_policy"]["external_scientific_tools"] = (
        "private hash-verified Linux Core payload (default + alphafold P2Rank models); "
        "GNINA 1.3.3 distributed via optional hash-verified offline pack"
    )
    inventory["scientific_payload_sha256"] = scientific_payload_sha256
    inventory["source_companion_sha256"] = linux_companion_sha256
    inventory["gnina_pack_lock_sha256"] = gnina_pack_lock_sha256

    runtime_records = [
        ("AutoDock Vina", "1.2.7", "Apache-2.0", "vina-source"),
        ("AutoGrid4", "4.2.6", "GPL-2.0-or-later", "autodocksuite-source"),
        ("AutoDock4", "4.2.6", "GPL-2.0-or-later", "autodocksuite-source"),
        (
            "AutoDock-GPU",
            f"1.6 {AUTODOCK_GPU_VARIANT}",
            "GPL-2.0-or-later AND LGPL-2.1-or-later",
            "autodock-gpu-ankora-linux-source",
        ),
        (
            "P2Rank",
            f"2.5.1 {SLIM_P2RANK_VARIANT}",
            "MIT; dependencies separately inventoried",
            "p2rank-source",
        ),
        (
            "Eclipse Temurin JRE",
            "21.0.12.1+1",
            "GPL-2.0 WITH Classpath-exception-2.0; per-module notices",
            "java-source",
        ),
    ]
    for name, version, license_name, source_id in runtime_records:
        source = unified_sources[source_id]
        inventory["components"].append(
            {
                "category": "scientific-runtime",
                "name": name,
                "version": version,
                "license": license_name,
                "source_url": source["url"],
                "license_documents": [],
                "source_archive": source["file"],
                "evidence": "SCIENTIFIC_SOURCE_COMPANION.json; exact runtime payload manifest",
            }
        )
    for item in p2rank_report["components"]:
        inventory["components"].append(
            {
                "category": "p2rank-dependency",
                "name": Path(item["file"]).name,
                "version": item["evidence"],
                "license": item["license"],
                "binary_sha256": item["binary_sha256"],
                "source_ids": item["source_ids"],
                "license_documents": [],
                "evidence": "SCIENTIFIC_SOURCE_COMPANION.json; SCIENTIFIC_NOTICES.txt",
            }
        )
    inventory["components"].append(
        {
            "category": "scientific-runtime",
            "name": "Boost linked into official Vina",
            "version": "not reported by upstream binary; build recipe defaults to 1.83.0",
            "license": "BSL-1.0",
            "source_url": "https://www.boost.org/LICENSE_1_0.txt",
            "license_documents": [],
        }
    )

    output_legal.mkdir(parents=True, exist_ok=False)
    for name, content in base.items():
        (output_legal / name).write_bytes(content)
    (output_legal / "THIRD_PARTY_INVENTORY.json").write_text(
        json.dumps(inventory, indent=2) + "\n", encoding="utf-8"
    )
    (output_legal / "SCIENTIFIC_SOURCE_COMPANION.json").write_bytes(linux_companion_bytes)

    notices = base["THIRD_PARTY_NOTICES.txt"].decode("utf-8")
    start = notices.index("The scientific executables AutoDock Vina")
    end = notices.index("COMPONENT INDEX", start)
    notices = (
        notices[:start]
        + "Core scientific runtimes (Vina, AutoDock4/AutoGrid4, AutoDock-GPU, P2Rank, and\n"
        + "Eclipse Temurin OpenJDK 21) ARE included in this Linux package.\n"
        + "See SCIENTIFIC_NOTICES.txt and SCIENTIFIC_SOURCE_COMPANION.json.\n"
        + f"Corresponding source archives are distributed in {companion_zip_path.name}.\n"
        + "GNINA 1.3.3 is not bundled in the Core installer; it may be imported from\n"
        + "Ankora_0.1.0_gnina-cuda12-pack.tar.zst (whose GPL-2.0 sources are also included\n"
        + f"in {companion_zip_path.name}).\n\n"
        + notices[end:]
    )
    (output_legal / "THIRD_PARTY_NOTICES.txt").write_text(notices, encoding="utf-8")

    with (output_legal / "SCIENTIFIC_NOTICES.txt").open("w", encoding="utf-8") as stream:
        stream.write(
            "ANKORA LINUX SCIENTIFIC RUNTIME NOTICES\n"
            "Ankora application code is MIT. Separate tools retain their own licenses.\n\n"
        )
        stream.write(boost_license_path.read_text(encoding="utf-8") + "\n\n")
        for gpu_lic in ("LICENSE", "LICENSE_LGPL"):
            gpu_lic_path = tools / "autodock-gpu-1.6" / gpu_lic
            if gpu_lic_path.is_file():
                stream.write(
                    f"autodock-gpu-1.6/{gpu_lic}\n"
                    + gpu_lic_path.read_text(encoding="utf-8", errors="replace")
                    + "\n\n"
                )
        for digest, labels in sorted(p2rank_report["documents"].items()):
            raw = (p2rank_companion / "documents" / digest).read_bytes()
            stream.write(f"\nSHA-256: {digest}\n" + "\n".join(labels) + "\n")
            stream.write(raw.decode("utf-8", errors="replace") + "\n")
        for path in sorted((tools / "java-21/legal").rglob("*")):
            if path.is_file():
                stream.write(
                    "\n"
                    + path.relative_to(tools).as_posix()
                    + "\n"
                    + path.read_text(encoding="utf-8", errors="replace")
                )

    # Assemble companion zip (omitting only non-reciprocal MIT/Apache duplicates and
    # unpatched upstream autodock-gpu zip superseded by autodock-gpu-1.6-ankora-source.zip)
    companion_zip_path.parent.mkdir(parents=True, exist_ok=True)
    omitted_nonreciprocal_sources = {
        f"sources/{lock_entries['p2rank-source']['sha256'][:16]}-{lock_entries['p2rank-source']['filename']}",
        f"sources/{lock_entries['vina-source']['sha256'][:16]}-{lock_entries['vina-source']['filename']}",
        f"sources/{lock_entries['autodock-gpu-source']['sha256'][:16]}-{lock_entries['autodock-gpu-source']['filename']}",
    }
    linux_source_by_arc = {
        f"sources/{item['sha256'][:16]}-{item['filename']}": cache / item["filename"]
        for item in linux_source_entries
    }

    with zipfile.ZipFile(companion_zip_path, "w", compression=zipfile.ZIP_STORED) as zf:
        zf.writestr("SCIENTIFIC_SOURCE_COMPANION.json", linux_companion_bytes)
        zf.write(gpu_source_zip, arcname="sources/autodock-gpu-1.6-ankora-source.zip")
        written = {
            "SCIENTIFIC_SOURCE_COMPANION.json",
            "sources/autodock-gpu-1.6-ankora-source.zip",
        }
        for source in unified_sources.values():
            rel_file = source["file"]
            if rel_file in omitted_nonreciprocal_sources or rel_file in written:
                continue
            if rel_file in linux_source_by_arc:
                src_disk = linux_source_by_arc[rel_file]
            else:
                src_disk = p2rank_companion.joinpath(*safe_relative(rel_file).parts)
            zf.write(src_disk, arcname=rel_file)
            written.add(rel_file)

    source_text = base["SOURCE_AVAILABILITY.txt"].decode("utf-8")
    source_text = source_text[
        : source_text.index("EXTERNAL SCIENTIFIC TOOLS NOT REDISTRIBUTED")
    ]
    source_text = source_text.replace(
        "No listed reciprocal component\nhas been locally modified by Ankora.",
        "The AutoDock-GPU binary includes Ankora's multi-architecture CUDA build notes.",
    )
    source_text += (
        "\nSCIENTIFIC SOURCES COMPANION ARCHIVE\n"
        "Corresponding source archives, build scripts, multi-arch AutoDock-GPU 1.6 source,\n"
        "OpenJDK 21 sources, P2Rank LGPL/GPL dependency sources, AND GNINA 1.3.3 +\n"
        "OpenBabel 3.1.1 GPL-2.0 sources (for the optional GNINA offline pack) are\n"
        f"distributed alongside the Linux package in {companion_zip_path.name}.\n\n"
        "REBUILDING AND MODIFICATION\n"
        "No restriction is imposed on modification or reverse engineering of LGPL components\n"
        "for debugging modifications. Java dependencies are separate JARs; Java/GPL tools\n"
        "execute as separate processes via argument arrays.\n"
        "After replacing a compatible private tool or library, regenerate tools/payload.json\n"
        "file hashes and record the new variant; never label modified outputs with a\n"
        "historical executable identity.\n"
    )
    (output_legal / "SOURCE_AVAILABILITY.txt").write_text(source_text, encoding="utf-8")

    terms = (
        "ANKORA LINUX INSTALLATION TERMS\n\n"
        "Ankora application code is licensed under MIT (reproduced below). Open-source and\n"
        "reciprocal (GPL/LGPL/MPL/Apache/BSD) dependencies retain their full rights under\n"
        "their respective licenses; see THIRD_PARTY_NOTICES.txt, SCIENTIFIC_NOTICES.txt,\n"
        "and SOURCE_AVAILABILITY.txt.\n\n"
        "The optional Ankora_0.1.0_gnina-cuda12-pack.tar.zst add-on pack contains NVIDIA\n"
        "CUDA 12.8 Runtime and NVIDIA cuDNN 9.25 Runtime shared libraries redistributed\n"
        "under NVIDIA's respective attachment/supplement terms (included inside that pack's\n"
        "licenses/ directory). Those NVIDIA terms apply solely to those NVIDIA shared\n"
        "libraries and never restrict MIT, GPL, or LGPL components.\n\n"
        + base["ANKORA_LICENSE.txt"].decode("utf-8")
    )
    (output_legal / "INSTALLATION_TERMS.txt").write_text(terms, encoding="utf-8")

    companion_zip_sha256 = sha256(companion_zip_path)
    manifest_files = {
        p.relative_to(output_legal).as_posix(): sha256(p)
        for p in sorted(output_legal.rglob("*"))
        if p.is_file()
    }
    legal_manifest = {
        "schema_version": 1,
        "platform": "linux-x86_64",
        "scientific_payload_sha256": scientific_payload_sha256,
        "gnina_pack_lock_sha256": gnina_pack_lock_sha256,
        "source_distribution": "companion-archive",
        "companion_archive_name": companion_zip_path.name,
        "companion_archive_sha256": companion_zip_sha256,
        "gpu_source_sha256": gpu_source_sha256,
        "gpu_binary_sha256": cast(dict[str, Any], gpu_manifest["binary"])["sha256"],
        "files": manifest_files,
    }
    (output_legal / "COMPLETE_LEGAL_MANIFEST.json").write_text(
        json.dumps(legal_manifest, indent=2) + "\n", encoding="utf-8"
    )
    verify_complete_linux_legal(output_legal, tools, companion_zip_path)
    print(
        f"Assembled Linux complete-legal ({len(inventory['components'])} components, "
        f"{len(manifest_files)} files) + {companion_zip_path.name} "
        f"({companion_zip_path.stat().st_size / (1024 * 1024):.2f} MiB)",
        flush=True,
    )
    return legal_manifest


def verify_complete_linux_legal(
    output_legal: Path, tools: Path, companion_zip_path: Path | None = None
) -> dict[str, Any]:
    verify_tree(tools)
    expected_payload_sha = sha256(tools / "payload.json")
    manifest = json.loads(
        (output_legal / "COMPLETE_LEGAL_MANIFEST.json").read_text(encoding="utf-8")
    )
    if manifest.get("platform") != "linux-x86_64":
        raise ValueError("Legal manifest is not for linux-x86_64")
    if manifest.get("scientific_payload_sha256") != expected_payload_sha:
        raise ValueError("Legal payload belongs to a different scientific payload")
    if manifest.get("gnina_pack_lock_sha256") != sha256(GNINA_PACK_LOCK):
        raise ValueError("Legal payload disagrees with GNINA pack lock")

    actual_files = {
        p.relative_to(output_legal).as_posix()
        for p in output_legal.rglob("*")
        if p.is_file()
    }
    if actual_files != set(manifest["files"]) | {"COMPLETE_LEGAL_MANIFEST.json"}:
        raise ValueError("Missing or unlisted file in Linux complete-legal directory")
    for rel_name, expected_digest in manifest["files"].items():
        file_path = output_legal.joinpath(*safe_relative(rel_name).parts)
        if file_path.is_symlink() or sha256(file_path) != expected_digest:
            raise ValueError(f"Linux legal file integrity failure: {rel_name}")

    inventory = json.loads(
        (output_legal / "THIRD_PARTY_INVENTORY.json").read_text(encoding="utf-8")
    )
    required = {
        "AutoDock Vina",
        "AutoGrid4",
        "AutoDock4",
        "AutoDock-GPU",
        "P2Rank",
        "Eclipse Temurin JRE",
    }
    component_names = {c["name"] for c in inventory["components"]}
    if not required <= component_names:
        raise ValueError("Incomplete Linux scientific legal inventory")
    for forbidden_win in ("Microsoft Edge WebView2 Evergreen", "MSVC OpenMP vcomp140"):
        if forbidden_win in component_names:
            raise ValueError(f"Windows component leaked into Linux inventory: {forbidden_win}")
    for external in EXTERNAL_TOOLS:
        if external == "GNINA" and external in component_names:
            raise ValueError("GNINA must not be listed as bundled inside Core installer")

    if companion_zip_path is not None:
        if not companion_zip_path.is_file():
            raise FileNotFoundError(f"Missing Linux companion zip: {companion_zip_path}")
        if sha256(companion_zip_path) != manifest["companion_archive_sha256"]:
            raise ValueError("Linux companion zip SHA-256 mismatch")
        with zipfile.ZipFile(companion_zip_path) as zf:
            names = set(zf.namelist())
            for must_include in (
                "SCIENTIFIC_SOURCE_COMPANION.json",
                "sources/autodock-gpu-1.6-ankora-source.zip",
            ):
                if must_include not in names:
                    raise ValueError(f"Companion zip missing {must_include}")
            if not any(n.endswith("-gnina-source.tar.gz") for n in names):
                raise ValueError("Companion zip missing GNINA GPL-2.0 source archive")
            if not any(n.endswith("-openbabel-source.tar.gz") for n in names):
                raise ValueError("Companion zip missing OpenBabel GPL-2.0 source archive")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--analysis", type=Path, default=DEFAULT_ANALYSIS)
    parser.add_argument("--tools", type=Path, default=DEFAULT_TOOLS_ROOT)
    parser.add_argument("--gpu-build", type=Path, default=DEFAULT_GPU_BUILD_ROOT)
    parser.add_argument("--p2rank-companion", type=Path, default=DEFAULT_P2RANK_COMPANION)
    parser.add_argument("--cache", type=Path, default=CACHE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_LEGAL)
    parser.add_argument("--companion-zip", type=Path, default=DEFAULT_COMPANION_ZIP)
    parser.add_argument("--clean", action="store_true")
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()

    if args.verify:
        verify_complete_linux_legal(args.output, args.tools, args.companion_zip)
        print("Linux complete-legal payload and companion archive verified.", flush=True)
        return

    if args.clean:
        if args.output.exists():
            shutil.rmtree(args.output)
        args.companion_zip.unlink(missing_ok=True)

    assemble_linux_legal(
        analysis=args.analysis,
        tools=args.tools,
        gpu_build=args.gpu_build,
        p2rank_companion=args.p2rank_companion,
        cache=args.cache,
        output_legal=args.output,
        companion_zip_path=args.companion_zip,
    )


if __name__ == "__main__":
    main()
