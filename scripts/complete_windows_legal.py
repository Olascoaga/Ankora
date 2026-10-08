"""Build the complete installer legal payload from exact reviewed inputs.

The historical tracked Python-only inventory remains reproducible. The complete
installer MUST use this superset, including unchanged corresponding sources.
No runtime hash, source archive or upstream license may drift implicitly.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import xml.etree.ElementTree as ET
import zipfile
from html.parser import HTMLParser
from pathlib import Path

from scripts.generate_third_party_notices import generated_files
from scripts.prepare_windows_webview2 import load_webview_lock
from scripts.validate_p2rank_variant import verify_tree
from scripts.windows_scientific_payload import CACHE, safe_relative, sha256

PAYLOAD_SHA256 = "e83f404b38e20345806c19e3e811d764d0e1c476324ddfdd544f7e36a52c6c7c"
COMPANION_SHA256 = "be756aaa95624b078dff9cd0e99c0f520c92c952736caa2e9b52d9488eb9f5b8"
GPU_SOURCE_SHA256 = "76f64f65988546d2c418e7769a27a6f452eaf55eedd2256031261ad0c3480a5e"
VENDOR_FILES = {
    "webview2-license.json": "e15b53f476b66f8335c18436998256dc9862b210242a8e4c7f7e14d2de53591d",
    "vs2022-community-terms.docx": "41a207b10c8ab91d0d2f10a854715f73dca54509581692d2fe179aa3ffcb8540",
    "vs2022-redist.html": "090792e3634327db47b563385c830add3c195e8056cae87a0661b0a5b6139217",
    "boost-LICENSE_1_0.txt": "c9bff75738922193e67fa726fa225535870d2aa1059f91452c411736284ad566",
}


class PlainText(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def html_text(value: str) -> str:
    parser = PlainText()
    parser.feed(value)
    return "\n".join(part.strip() for part in parser.parts if part.strip())


def vendor_terms() -> tuple[str, str]:
    for name, expected in VENDOR_FILES.items():
        if sha256(CACHE / name) != expected:
            raise ValueError(f"Vendor terms changed: {name}")
    web = json.loads((CACHE / "webview2-license.json").read_text(encoding="utf-8"))
    web_text = html_text(web["evergreenHtml"])
    with zipfile.ZipFile(CACHE / "vs2022-community-terms.docx") as doc:
        root = ET.fromstring(doc.read("word/document.xml"))
        ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
        visual_studio = "\n".join(
            "".join(t.text or "" for t in p.findall(".//w:t", ns))
            for p in root.findall(".//w:p", ns)
        )
    return web_text, visual_studio


def verify_companion(tools: Path, companion: Path, gpu_source: Path) -> dict:
    verify_tree(tools)
    if sha256(tools / "payload.json") != PAYLOAD_SHA256:
        raise ValueError("Scientific payload is not the reviewed variant")
    if sha256(companion / "source-companion.json") != COMPANION_SHA256:
        raise ValueError("Source companion identity was not reviewed")
    if sha256(gpu_source) != GPU_SOURCE_SHA256:
        raise ValueError("GPU corresponding source does not match the rebuilt binary")
    report = json.loads(
        (companion / "source-companion.json").read_text(encoding="utf-8")
    )
    if report["gaps"] or report["payload_sha256"] != PAYLOAD_SHA256:
        raise ValueError("Unresolved source companion gap")
    for source in report["sources"].values():
        path = companion.joinpath(*safe_relative(source["file"]).parts)
        if path.is_symlink() or sha256(path) != source["sha256"]:
            raise ValueError("Corresponding source integrity failure")
    for digest in report["documents"]:
        if not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ValueError("Invalid document identity")
        if sha256(companion / "documents" / digest) != digest:
            raise ValueError("License document integrity failure")
    return report


def assemble(
    analysis: Path, tools: Path, companion: Path, gpu_source: Path, output: Path
) -> None:
    report = verify_companion(tools, companion, gpu_source)
    web_text, visual_studio = vendor_terms()
    base = generated_files(analysis)
    inventory = json.loads(base["THIRD_PARTY_INVENTORY.json"])
    # Replace historical subset wording only in the newly generated full payload.
    inventory["excluded_external_tools"] = ["GNINA"]
    inventory["inventory_policy"]["external_scientific_tools"] = (
        "private hash-verified payload"
    )
    inventory["inventory_policy"]["webview2"] = (
        "embedded signed offline Evergreen installer"
    )
    inventory["scientific_payload_sha256"] = PAYLOAD_SHA256
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
            "2.5.1 ankora-vecmath-1.5.2-only-v1",
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
    output.mkdir(parents=True, exist_ok=False)
    for name, content in base.items():
        (output / name).write_bytes(content)
    (output / "THIRD_PARTY_INVENTORY.json").write_text(
        json.dumps(inventory, indent=2) + "\n", encoding="utf-8"
    )
    notices = base["THIRD_PARTY_NOTICES.txt"].decode()
    start = notices.index("The scientific executables AutoDock Vina")
    end = notices.index("COMPONENT INDEX", start)
    notices = (
        notices[:start]
        + "Scientific runtimes and offline WebView2 ARE included.\nSee SCIENTIFIC_NOTICES.txt and SCIENTIFIC_SOURCE_COMPANION.json.\nGNINA remains deferred and is not included.\n\n"
        + notices[end:]
    )
    (output / "THIRD_PARTY_NOTICES.txt").write_text(notices, encoding="utf-8")
    with (output / "SCIENTIFIC_NOTICES.txt").open("w", encoding="utf-8") as stream:
        stream.write(
            "ANKORA SCIENTIFIC RUNTIME NOTICES\nAnkora application code is MIT. Separate tools retain their own licenses.\n\n"
        )
        stream.write((CACHE / "boost-LICENSE_1_0.txt").read_text() + "\n\n")
        stream.write(web_text + "\n\n" + visual_studio + "\n\n")
        for digest, labels in sorted(report["documents"].items()):
            raw = (companion / "documents" / digest).read_bytes()
            stream.write(f"\nSHA-256: {digest}\n" + "\n".join(labels) + "\n")
            stream.write(raw.decode("utf-8", errors="replace") + "\n")
        # The Java distribution contains authoritative module-specific notices.
        for path in sorted((tools / "java-21/legal").rglob("*")):
            if path.is_file():
                stream.write(
                    "\n"
                    + path.relative_to(tools).as_posix()
                    + "\n"
                    + path.read_text(errors="replace")
                )
    for source in report["sources"].values():
        destination = output / source["file"]
        destination.parent.mkdir(parents=True, exist_ok=True)
        if not destination.exists():
            shutil.copyfile(companion / source["file"], destination)
    shutil.copyfile(gpu_source, output / "sources/autodock-gpu-1.6-ankora-source.zip")
    shutil.copyfile(
        companion / "source-companion.json", output / "SCIENTIFIC_SOURCE_COMPANION.json"
    )
    source_text = base["SOURCE_AVAILABILITY.txt"].decode()
    source_text = source_text[
        : source_text.index("EXTERNAL SCIENTIFIC TOOLS NOT REDISTRIBUTED")
    ]
    source_text = source_text.replace(
        "No listed reciprocal component\nhas been locally modified by Ankora.",
        "The AutoDock-GPU variant includes the explicitly recorded compiler portability changes.",
    )
    source_text += "\nSCIENTIFIC SOURCES INCLUDED\nThe sources/ directory contains the exact pinned sources, build files and patched GPU source.\nSCIENTIFIC_SOURCE_COMPANION.json maps P2Rank dependencies to source archives.\nGNINA is not distributed.\n\nREBUILDING AND MODIFICATION\nNo restriction is imposed on modification or reverse engineering of LGPL components for debugging modifications.\nJava dependencies are separate JARs; Java/GPL tools execute as separate processes.\nUse the shipped source build files and Ankora's public build scripts.\nAfter replacing a compatible private tool or library, regenerate tools/payload.json file hashes and record the new variant; the manifest is not signed or locked with a secret.\nNever label modified outputs with a historical executable identity.\n"
    (output / "SOURCE_AVAILABILITY.txt").write_text(source_text, encoding="utf-8")
    # NSIS displays these component-scoped terms; they do not replace MIT/GPL.
    terms = (
        "ANKORA INSTALLATION TERMS\n\nAnkora is licensed under MIT (below). Open-source dependencies retain their own rights.\nMicrosoft WebView2 and MSVC runtimes are separate Microsoft components. Their terms apply only to those components, not to Ankora or GPL/LGPL components.\nBy proceeding you accept the applicable Microsoft component terms reproduced below, including restrictions on redistribution of those components. Microsoft privacy notice: https://aka.ms/privacy\n\n"
        + base["ANKORA_LICENSE.txt"].decode()
        + "\n\n"
        + web_text
        + "\n\n"
        + visual_studio
    )
    (output / "INSTALLATION_TERMS.txt").write_text(terms, encoding="utf-8")
    manifest = {
        p.relative_to(output).as_posix(): sha256(p)
        for p in sorted(output.rglob("*"))
        if p.is_file()
    }
    (output / "COMPLETE_LEGAL_MANIFEST.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "scientific_payload_sha256": PAYLOAD_SHA256,
                "files": manifest,
            },
            indent=2,
        )
        + "\n"
    )
    print(
        f"Complete legal payload assembled: {len(inventory['components'])} components, {len(manifest)} files"
    )


def verify_complete(output: Path, tools: Path) -> None:
    verify_tree(tools)
    if sha256(tools / "payload.json") != PAYLOAD_SHA256:
        raise ValueError("Wrong scientific payload")
    manifest = json.loads((output / "COMPLETE_LEGAL_MANIFEST.json").read_text())
    if manifest["scientific_payload_sha256"] != PAYLOAD_SHA256:
        raise ValueError("Legal payload belongs to another runtime")
    actual = {
        p.relative_to(output).as_posix() for p in output.rglob("*") if p.is_file()
    }
    if actual != set(manifest["files"]) | {"COMPLETE_LEGAL_MANIFEST.json"}:
        raise ValueError("Missing or unlisted legal payload file")
    for name, digest in manifest["files"].items():
        path = output.joinpath(*safe_relative(name).parts)
        if path.is_symlink() or sha256(path) != digest:
            raise ValueError("Legal payload integrity failure")
    inventory = json.loads(
        (output / "THIRD_PARTY_INVENTORY.json").read_text(encoding="utf-8")
    )
    if inventory.get("scientific_payload_sha256") != PAYLOAD_SHA256:
        raise ValueError("Inventory belongs to another runtime")
    if inventory.get("excluded_external_tools") != ["GNINA"]:
        raise ValueError("Incorrect bundled capability declaration")
    if sha256(output / "SCIENTIFIC_SOURCE_COMPANION.json") != COMPANION_SHA256:
        raise ValueError("Installed source companion identity changed")
    if (
        sha256(output / "sources/autodock-gpu-1.6-ankora-source.zip")
        != GPU_SOURCE_SHA256
    ):
        raise ValueError("Installed GPU source identity changed")
    required = {
        "AutoDock Vina",
        "AutoGrid4",
        "AutoDock4",
        "AutoDock-GPU",
        "P2Rank",
        "Eclipse Temurin JRE",
        "Microsoft Edge WebView2 Evergreen",
    }
    if not required <= {c["name"] for c in inventory["components"]}:
        raise ValueError("Incomplete scientific legal inventory")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--analysis", type=Path)
    parser.add_argument("--tools", type=Path, required=True)
    parser.add_argument("--companion", type=Path)
    parser.add_argument("--gpu-source", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    if args.verify:
        verify_complete(args.output, args.tools)
    else:
        assemble(
            args.analysis, args.tools, args.companion, args.gpu_source, args.output
        )
