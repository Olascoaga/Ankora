"""Build the streamlined Option A Windows installer in a new directory.

Preserves the existing full installer untouched, keeps the offline WebView2
installer embedded, retains P2Rank 'default' and 'alphafold' models, removes
unused P2Rank conservation/rescoring models and redundant Java CDS dumps, and
moves the 555 MB source archives out of the installed runtime into a companion
archive alongside the installer.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import zipfile
from pathlib import Path

from scripts.complete_windows_legal import (
    COMPANION_SHA256,
    GPU_SOURCE_SHA256,
    PAYLOAD_SHA256,
    vendor_terms,
    verify_companion,
)
from scripts.generate_third_party_notices import generated_files
from scripts.prepare_windows_webview2 import load_webview_lock, verify_nsis_selection
from scripts.validate_p2rank_variant import verify_tree
from scripts.windows_scientific_payload import CACHE, sha256

SLIM_VARIANT = "ankora-vecmath-1.5.2-default-alphafold-v1"
OMITTED_P2RANK_MODELS = (
    "p2rank-2.5.1/models/alphafold_conservation_hmm/model.zst",
    "p2rank-2.5.1/models/conservation_hmm/model.zst",
    "p2rank-2.5.1/models/default_rescore/model.zst",
    "p2rank-2.5.1/models/rescore_2024/model.zst",
    "p2rank-2.5.1/models/rescore_conservation/model.zst",
)
RETAINED_P2RANK_MODELS = (
    "p2rank-2.5.1/models/default/model.zst",
    "p2rank-2.5.1/models/alphafold/model.zst",
)
OMITTED_JAVA_FILES = (
    "java-21/bin/server/classes.jsa",
    "java-21/bin/server/classes_nocoops.jsa",
    "java-21/lib/jvm.lib",
)
OMITTED_TOOLS_FILES = set(OMITTED_P2RANK_MODELS) | set(OMITTED_JAVA_FILES)


def stage_slim_tools(reference_tools: Path, destination_tools: Path) -> str:
    if destination_tools.exists():
        raise FileExistsError(f"Destination tools directory already exists: {destination_tools}")
    payload = verify_tree(reference_tools)
    if sha256(reference_tools / "payload.json") != PAYLOAD_SHA256:
        raise ValueError("Reference tools payload is not the reviewed variant")
    for required_model in RETAINED_P2RANK_MODELS:
        if required_model not in payload["files"]:
            raise ValueError(f"Missing required retained P2Rank model: {required_model}")
    for omitted in OMITTED_TOOLS_FILES:
        if omitted not in payload["files"]:
            raise ValueError(f"Expected omitted file not found in reference: {omitted}")

    destination_tools.mkdir(parents=True, exist_ok=False)
    retained_files: dict[str, str] = {}
    for relative, digest in payload["files"].items():
        if relative in OMITTED_TOOLS_FILES:
            continue
        target = destination_tools / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(reference_tools / relative, target)
        retained_files[relative] = digest

    payload["files"] = retained_files
    payload["tools"]["p2rank"]["variant"] = SLIM_VARIANT
    payload["p2rank_variant"] = {
        "id": SLIM_VARIANT,
        "reference_payload_sha256": PAYLOAD_SHA256,
        "retained_models": list(RETAINED_P2RANK_MODELS),
        "omitted_unused_models": list(OMITTED_P2RANK_MODELS),
        "omitted_java_cache_files": list(OMITTED_JAVA_FILES),
    }
    (destination_tools / "payload.json").write_text(
        json.dumps(payload, indent=2) + "\n", encoding="utf-8"
    )
    verify_tree(destination_tools)
    return sha256(destination_tools / "payload.json")


def assemble_slim_legal(
    analysis: Path,
    ref_tools: Path,
    slim_tools: Path,
    companion: Path,
    gpu_source: Path,
    output_legal: Path,
    companion_zip_path: Path,
) -> None:
    report = verify_companion(ref_tools, companion, gpu_source)
    slim_payload_sha256 = sha256(slim_tools / "payload.json")
    web_text, visual_studio = vendor_terms()
    base = generated_files(analysis)
    inventory = json.loads(base["THIRD_PARTY_INVENTORY.json"])
    inventory["excluded_external_tools"] = ["GNINA"]
    inventory["inventory_policy"]["external_scientific_tools"] = (
        "private hash-verified payload (default + alphafold P2Rank models)"
    )
    inventory["inventory_policy"]["webview2"] = (
        "embedded signed offline Evergreen installer"
    )
    inventory["scientific_payload_sha256"] = slim_payload_sha256
    inventory["source_companion_sha256"] = COMPANION_SHA256
    inventory["webview2_installer_sha256"] = load_webview_lock()["sha256"]

    records = [
        ("AutoDock Vina", "1.2.7", "Apache-2.0", "vina-source"),
        ("AutoGrid4", "4.2.6", "GPL-2.0-or-later", "autodocksuite-source"),
        ("AutoDock4", "4.2.6", "GPL-2.0-or-later", "autodocksuite-source"),
        (
            "AutoDock-GPU",
            "1.6 ankora-msvc-openmp-v1",
            "GPL-2.0-or-later AND LGPL-2.1-or-later",
            "autodock-gpu-source",
        ),
        (
            "P2Rank",
            f"2.5.1 {SLIM_VARIANT}",
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
    for name, version, license_name, source_id in records:
        source = report["sources"][source_id]
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
    for item in report["components"]:
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
    inventory["components"].extend(
        [
            {
                "category": "scientific-runtime",
                "name": "MSVC OpenMP vcomp140",
                "version": "14.44.35112",
                "license": "Microsoft Visual Studio 2022 Distributable Code",
                "source_url": "https://learn.microsoft.com/en-us/visualstudio/releases/2022/redistribution",
                "license_documents": [],
            },
            {
                "category": "installer",
                "name": "Microsoft Edge WebView2 Evergreen",
                "version": "locked installer " + load_webview_lock()["sha256"],
                "license": "Microsoft WebView2 Runtime terms",
                "source_url": "https://developer.microsoft.com/microsoft-edge/api/eula/webview2?locale=en-us",
                "license_documents": [],
            },
            {
                "category": "scientific-runtime",
                "name": "Boost linked into official Vina",
                "version": "not reported by upstream binary; build recipe defaults to 1.83.0",
                "license": "BSL-1.0",
                "source_url": "https://www.boost.org/LICENSE_1_0.txt",
                "license_documents": [],
            },
        ]
    )

    output_legal.mkdir(parents=True, exist_ok=False)
    for name, content in base.items():
        (output_legal / name).write_bytes(content)
    (output_legal / "THIRD_PARTY_INVENTORY.json").write_text(
        json.dumps(inventory, indent=2) + "\n", encoding="utf-8"
    )
    notices = base["THIRD_PARTY_NOTICES.txt"].decode()
    start = notices.index("The scientific executables AutoDock Vina")
    end = notices.index("COMPONENT INDEX", start)
    notices = (
        notices[:start]
        + "Scientific runtimes and offline WebView2 ARE included.\n"
        + "See SCIENTIFIC_NOTICES.txt and SCIENTIFIC_SOURCE_COMPANION.json.\n"
        + "Corresponding source archives are distributed in Ankora_0.1.0_x64-sources-companion.zip.\n"
        + "GNINA remains deferred and is not included.\n\n"
        + notices[end:]
    )
    (output_legal / "THIRD_PARTY_NOTICES.txt").write_text(notices, encoding="utf-8")

    with (output_legal / "SCIENTIFIC_NOTICES.txt").open("w", encoding="utf-8") as stream:
        stream.write(
            "ANKORA SCIENTIFIC RUNTIME NOTICES\n"
            "Ankora application code is MIT. Separate tools retain their own licenses.\n\n"
        )
        stream.write((CACHE / "boost-LICENSE_1_0.txt").read_text() + "\n\n")
        stream.write(web_text + "\n\n" + visual_studio + "\n\n")
        for digest, labels in sorted(report["documents"].items()):
            raw = (companion / "documents" / digest).read_bytes()
            stream.write(f"\nSHA-256: {digest}\n" + "\n".join(labels) + "\n")
            stream.write(raw.decode("utf-8", errors="replace") + "\n")
        for path in sorted((slim_tools / "java-21/legal").rglob("*")):
            if path.is_file():
                stream.write(
                    "\n"
                    + path.relative_to(slim_tools).as_posix()
                    + "\n"
                    + path.read_text(errors="replace")
                )

    shutil.copyfile(
        companion / "source-companion.json",
        output_legal / "SCIENTIFIC_SOURCE_COMPANION.json",
    )

    # Package reciprocal/companion source archives into the external companion zip
    # rather than inside the end-user installation directory.
    companion_zip_path.parent.mkdir(parents=True, exist_ok=True)
    omitted_redundant_sources = {
        "sources/cad17d3051f4d0ad-p2rank-source.zip",  # MIT; duplicates 207 MB of models
        "sources/08143c35ee5a5a53-vina-source.zip",  # Apache-2.0
        "sources/840959163266bd57-autodock-gpu-source.zip",  # Unpatched duplicate of autodock-gpu-1.6-ankora-source.zip
    }
    with zipfile.ZipFile(companion_zip_path, "w", compression=zipfile.ZIP_STORED) as zf:
        zf.write(
            companion / "source-companion.json",
            arcname="SCIENTIFIC_SOURCE_COMPANION.json",
        )
        zf.write(
            gpu_source,
            arcname="sources/autodock-gpu-1.6-ankora-source.zip",
        )
        written_arcnames = {
            "SCIENTIFIC_SOURCE_COMPANION.json",
            "sources/autodock-gpu-1.6-ankora-source.zip",
        }
        for source in report["sources"].values():
            rel_file = source["file"]
            if rel_file in omitted_redundant_sources or rel_file in written_arcnames:
                continue
            zf.write(companion / rel_file, arcname=rel_file)
            written_arcnames.add(rel_file)

    source_text = base["SOURCE_AVAILABILITY.txt"].decode()
    source_text = source_text[
        : source_text.index("EXTERNAL SCIENTIFIC TOOLS NOT REDISTRIBUTED")
    ]
    source_text = source_text.replace(
        "No listed reciprocal component\nhas been locally modified by Ankora.",
        "The AutoDock-GPU variant includes the explicitly recorded compiler portability changes.",
    )
    source_text += (
        "\nSCIENTIFIC SOURCES COMPANION ARCHIVE\n"
        "Corresponding source archives, build scripts, and the patched AutoDock-GPU source\n"
        "are distributed alongside the installer in Ankora_0.1.0_x64-sources-companion.zip.\n"
        "SCIENTIFIC_SOURCE_COMPANION.json maps P2Rank dependencies to source archives.\n"
        "GNINA is not distributed.\n\n"
        "REBUILDING AND MODIFICATION\n"
        "No restriction is imposed on modification or reverse engineering of LGPL components for debugging modifications.\n"
        "Java dependencies are separate JARs; Java/GPL tools execute as separate processes.\n"
        "Use the shipped source build files and Ankora's public build scripts.\n"
        "After replacing a compatible private tool or library, regenerate tools/payload.json file hashes and record the new variant; the manifest is not signed or locked with a secret.\n"
        "Never label modified outputs with a historical executable identity.\n"
    )
    (output_legal / "SOURCE_AVAILABILITY.txt").write_text(source_text, encoding="utf-8")

    terms = (
        "ANKORA INSTALLATION TERMS\n\n"
        "Ankora is licensed under MIT (below). Open-source dependencies retain their own rights.\n"
        "Microsoft WebView2 and MSVC runtimes are separate Microsoft components. Their terms apply only to those components, not to Ankora or GPL/LGPL components.\n"
        "By proceeding you accept the applicable Microsoft component terms reproduced below, including restrictions on redistribution of those components. Microsoft privacy notice: https://aka.ms/privacy\n\n"
        + base["ANKORA_LICENSE.txt"].decode()
        + "\n\n"
        + web_text
        + "\n\n"
        + visual_studio
    )
    (output_legal / "INSTALLATION_TERMS.txt").write_text(terms, encoding="utf-8")

    manifest = {
        p.relative_to(output_legal).as_posix(): sha256(p)
        for p in sorted(output_legal.rglob("*"))
        if p.is_file()
    }
    (output_legal / "COMPLETE_LEGAL_MANIFEST.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "scientific_payload_sha256": slim_payload_sha256,
                "source_distribution": "companion-archive",
                "companion_archive_name": companion_zip_path.name,
                "companion_archive_sha256": sha256(companion_zip_path),
                "gpu_source_sha256": GPU_SOURCE_SHA256,
                "files": manifest,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def rewrite_nsis_script(
    template_nsi: str,
    slim_resources: Path,
    desktop_exe: Path,
    dictionary_mb: int = 128,
) -> str:
    if dictionary_mb not in (32, 64, 128):
        raise ValueError("Unsupported LZMA dictionary size")
    if '!define INSTALLWEBVIEW2MODE "offlineInstaller"' not in template_nsi:
        raise ValueError("Option A installer requires embedded offline WebView2")

    mappings = (
        ("backend", slim_resources / "backend"),
        ("legal", slim_resources / "complete-legal"),
    )
    all_dirs: set[str] = set()
    all_files: list[tuple[str, Path]] = []
    total_bytes = desktop_exe.stat().st_size

    for prefix, root_dir in mappings:
        all_dirs.add(prefix)
        for item in sorted(root_dir.rglob("*")):
            rel_win = f"{prefix}\\{item.relative_to(root_dir)}".replace("/", "\\")
            if item.is_dir():
                all_dirs.add(rel_win)
            elif item.is_file():
                total_bytes += item.stat().st_size
                all_files.append((rel_win, item.resolve()))
                parent = item.parent
                while parent != root_dir:
                    all_dirs.add(
                        f"{prefix}\\{parent.relative_to(root_dir)}".replace("/", "\\")
                    )
                    parent = parent.parent

    sorted_dirs_asc = sorted(all_dirs, key=lambda d: (d.count("\\"), d.lower()))
    sorted_dirs_desc = sorted(all_dirs, key=lambda d: (-d.count("\\"), d.lower()))

    install_lines = [f'    CreateDirectory "$INSTDIR\\{d}"' for d in sorted_dirs_asc]
    for rel_win, abs_src in all_files:
        install_lines.append(f'    File /a "/oname={rel_win}" "{abs_src}"')
    install_block = "  ; Copy resources\n" + "\n".join(install_lines) + "\n\n  ; Copy external binaries"

    uninstall_lines = [f'    Delete "$INSTDIR\\{rel_win}"' for rel_win, _ in all_files]
    rmdir_lines = [f'  RMDir /REBOOTOK "$INSTDIR\\{d}"' for d in sorted_dirs_desc]
    uninstall_block = (
        "  ; Delete resources\n"
        + "\n".join(uninstall_lines)
        + "\n\n  ; Delete external binaries\n\n  ; Delete app associations\n\n  ; Delete deep links\n\n\n  ; Delete uninstaller\n  Delete \"$INSTDIR\\uninstall.exe\"\n\n"
        + "\n".join(rmdir_lines)
        + '\n  RMDir "$INSTDIR"'
    )

    install_pattern = re.compile(
        r"  ; Copy resources\n.*?\n  ; Copy external binaries", re.DOTALL
    )
    uninstall_pattern = re.compile(
        r"  ; Delete resources\n.*?\n  RMDir \"\$INSTDIR\"", re.DOTALL
    )
    if not install_pattern.search(template_nsi):
        raise ValueError("Could not locate '; Copy resources' section in NSIS template")
    if not uninstall_pattern.search(template_nsi):
        raise ValueError("Could not locate '; Delete resources' section in NSIS template")

    rewritten = install_pattern.sub(lambda _m: install_block, template_nsi, count=1)
    rewritten = uninstall_pattern.sub(lambda _m: uninstall_block, rewritten, count=1)

    compressor = '  SetCompressor /SOLID "lzma"'
    if rewritten.count(compressor) != 1:
        raise ValueError("Unexpected NSIS compressor directive")
    rewritten = rewritten.replace(
        compressor, f'{compressor}\n  SetCompressorDictSize {dictionary_mb}'
    )
    rewritten = rewritten.replace(
        '!define OUTFILE "nsis-output.exe"',
        '!define OUTFILE "Ankora_0.1.0_x64-setup.exe"',
    )
    estimated_kb = total_bytes // 1024
    rewritten = re.sub(
        r'!define ESTIMATEDSIZE "\d+"',
        f'!define ESTIMATEDSIZE "{estimated_kb}"',
        rewritten,
        count=1,
    )
    return rewritten


def build_slim_release(
    *,
    project_root: Path,
    built_backend: Path,
    reference_tools: Path,
    companion_dir: Path,
    gpu_source: Path,
    analysis_toc: Path,
    template_nsi_path: Path,
    makensis_path: Path,
    slim_resources_dir: Path,
    release_dir: Path,
    preserve_installers: list[Path],
) -> dict:
    preserved_hashes = {str(p.resolve()): sha256(p.resolve()) for p in preserve_installers}
    if not preserved_hashes:
        raise ValueError("At least one existing installer must be preserved")

    if slim_resources_dir.exists():
        shutil.rmtree(slim_resources_dir)
    if release_dir.exists():
        if any(release_dir.iterdir()):
            raise FileExistsError(f"New release directory is create-only: {release_dir}")
    else:
        release_dir.mkdir(parents=True, exist_ok=False)

    slim_backend = slim_resources_dir / "backend"
    shutil.copytree(built_backend, slim_backend)
    slim_tools = slim_backend / "tools"
    slim_payload_sha256 = stage_slim_tools(reference_tools, slim_tools)

    companion_zip = release_dir / "Ankora_0.1.0_x64-sources-companion.zip"
    slim_legal = slim_resources_dir / "complete-legal"
    assemble_slim_legal(
        analysis=analysis_toc,
        ref_tools=reference_tools,
        slim_tools=slim_tools,
        companion=companion_dir,
        gpu_source=gpu_source,
        output_legal=slim_legal,
        companion_zip_path=companion_zip,
    )

    desktop_exe = (
        project_root / "apps/desktop/src-tauri/target/release/ankora-desktop.exe"
    ).resolve()
    if not desktop_exe.is_file():
        raise FileNotFoundError(f"Built desktop executable not found: {desktop_exe}")

    nsis_work_dir = slim_resources_dir / "nsis-build"
    nsis_work_dir.mkdir(parents=True, exist_ok=False)
    for item in template_nsi_path.parent.iterdir():
        if item.is_file() and (item.suffix == ".nsh" or item.name == "license_file"):
            shutil.copyfile(item, nsis_work_dir / item.name)
    # Update license_file with the freshly generated INSTALLATION_TERMS.txt
    shutil.copyfile(
        slim_legal / "INSTALLATION_TERMS.txt", nsis_work_dir / "license_file"
    )

    template_text = template_nsi_path.read_text(encoding="utf-8")
    rewritten_nsi = rewrite_nsis_script(
        template_text,
        slim_resources=slim_resources_dir,
        desktop_exe=desktop_exe,
        dictionary_mb=128,
    )
    generated_nsi = nsis_work_dir / "installer.nsi"
    generated_nsi.write_text(rewritten_nsi, encoding="utf-8")
    verify_nsis_selection(generated_nsi)

    build_log = nsis_work_dir / "build.log"
    with build_log.open("w", encoding="utf-8") as log_stream:
        subprocess.run(
            [str(makensis_path.resolve()), "/V3", str(generated_nsi.resolve())],
            cwd=nsis_work_dir,
            stdout=log_stream,
            stderr=subprocess.STDOUT,
            check=True,
        )

    built_installer = nsis_work_dir / "Ankora_0.1.0_x64-setup.exe"
    if not built_installer.is_file():
        raise FileNotFoundError("makensis did not produce Ankora_0.1.0_x64-setup.exe")

    final_installer = release_dir / "Ankora_0.1.0_x64-setup.exe"
    shutil.move(str(built_installer), str(final_installer))

    for legal_file in slim_legal.iterdir():
        if legal_file.is_file():
            shutil.copyfile(legal_file, release_dir / legal_file.name)

    for orig_path, orig_sha in preserved_hashes.items():
        if sha256(Path(orig_path)) != orig_sha:
            raise ValueError(f"Protected original installer changed: {orig_path}")

    summary = {
        "schema_version": 1,
        "variant": SLIM_VARIANT,
        "dictionary_mib": 128,
        "scientific_payload_sha256": slim_payload_sha256,
        "installer": {
            "path": str(final_installer),
            "size_bytes": final_installer.stat().st_size,
            "size_mb": round(final_installer.stat().st_size / (1024 * 1024), 2),
            "sha256": sha256(final_installer),
        },
        "companion_sources_zip": {
            "path": str(companion_zip),
            "size_bytes": companion_zip.stat().st_size,
            "size_mb": round(companion_zip.stat().st_size / (1024 * 1024), 2),
            "sha256": sha256(companion_zip),
        },
        "preserved_original_installers": preserved_hashes,
    }
    (release_dir / "slim-build-evidence.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8"
    )

    indexed = [p for p in sorted(release_dir.iterdir()) if p.is_file() and p.name != "SHA256SUMS"]
    (release_dir / "SHA256SUMS").write_text(
        "\n".join(f"{sha256(p)}  {p.name}" for p in indexed) + "\n",
        encoding="ascii",
        newline="\n",
    )
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    root = Path(__file__).resolve().parents[1]
    parser.add_argument("--project-root", type=Path, default=root)
    parser.add_argument(
        "--built-backend",
        type=Path,
        default=root / "build/windows-runtime/dist-slim/ankora-backend",
    )
    parser.add_argument(
        "--reference-tools",
        type=Path,
        default=root / "build/windows-runtime/installer-resources-20261015/backend/tools",
    )
    parser.add_argument(
        "--companion",
        type=Path,
        default=root / "build/windows-runtime/source-companion-02",
    )
    parser.add_argument(
        "--gpu-source",
        type=Path,
        default=root
        / "build/windows-runtime/installer-resources-20261015/complete-legal/sources/autodock-gpu-1.6-ankora-source.zip",
    )
    parser.add_argument(
        "--analysis",
        type=Path,
        default=root / "build/windows-runtime/pyinstaller-slim/ankora_backend/Analysis-00.toc",
    )
    parser.add_argument(
        "--template-nsi",
        type=Path,
        default=root / "apps/desktop/src-tauri/target/release/nsis/x64/installer.nsi",
    )
    parser.add_argument(
        "--makensis",
        type=Path,
        default=Path.home() / "AppData/Local/tauri/NSIS/makensis.exe",
    )
    parser.add_argument(
        "--slim-resources",
        type=Path,
        default=root / "build/windows-runtime/installer-resources-slim-20261017",
    )
    parser.add_argument(
        "--release-dir",
        type=Path,
        default=root / "build/windows-runtime/private-beta-slim-20261017",
    )
    parser.add_argument(
        "--preserve",
        type=Path,
        action="append",
        default=[
            root / "build/windows-runtime/private-beta-20261015/Ankora_0.1.0_x64-setup.exe"
        ],
    )
    args = parser.parse_args()
    summary = build_slim_release(
        project_root=args.project_root,
        built_backend=args.built_backend,
        reference_tools=args.reference_tools,
        companion_dir=args.companion,
        gpu_source=args.gpu_source,
        analysis_toc=args.analysis,
        template_nsi_path=args.template_nsi,
        makensis_path=args.makensis,
        slim_resources_dir=args.slim_resources,
        release_dir=args.release_dir,
        preserve_installers=args.preserve,
    )
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

