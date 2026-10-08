"""Assemble a create-only, hash-verified source/notice companion for review.

This does not approve redistribution. The inventory binds every P2Rank JAR to
its own evidence and retains explicit gaps. Sources are copied unchanged, never
executed or extracted to upstream-controlled filesystem paths.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import tarfile
import zipfile
from pathlib import Path, PurePosixPath

from scripts.collect_p2rank_maven_evidence import CENTRAL, publish
from scripts.inventory_p2rank_dependencies import inspect_jar
from scripts.validate_p2rank_variant import verify_tree
from scripts.windows_scientific_payload import (
    CACHE,
    ROOT,
    load_lock,
    safe_relative,
    sha256,
    verify,
)

SUPPLEMENTS = ROOT / "resources/windows-scientific-source-supplements.lock.json"
NOTICE = re.compile(
    r"^(license|licence|copying|copyright|notice|authors)([._-]|$)", re.IGNORECASE
)
MAX_NOTICE = 4 * 1024 * 1024
SOURCE_MAP = {
    "p2rank.jar": ("p2rank-source", "MIT"),
    "biojava-structure-7.2.2-rdk.1.jar": ("p2rank-biojava-source", "LGPL-2.1-or-later"),
    "FasterForest-2.5.2.jar": ("p2rank-fasterforest-source", "GPL-2.0-or-later"),
    "faster-molecular-surface-1.0.jar": (
        "p2rank-molecularsurface-source",
        "LGPL-2.1-or-later",
    ),
    "FastRandomForest_0.99.jar": ("p2rank-source", "GPL; see original COPYING"),
    "FastRandomForest_0.99_src.jar": ("p2rank-source", "GPL; see original COPYING"),
    "openchart-1.4.2.jar": ("openchart-source", "LGPL-2.1-or-later"),
    "arpack_combined_all-0.1.jar": ("jarpack-source", "BSD; see original notices"),
}
LICENSE_OVERRIDES = {
    "forester-1.039.jar": "LGPL-2.1-or-later (source headers)",
    "jsr166y-1.7.0.jar": "Public domain / CC0 (source headers)",
    "multiverse-core-0.7.0.jar": "Apache-2.0 (upstream release LICENSE)",
    "jniloader-1.1.jar": "LGPL-3.0 (upstream release LICENSE)",
}


def archive_notices(path: Path) -> list[tuple[str, bytes]]:
    """Read named notices and copyright-bearing source preambles without extraction."""
    found = []

    def wanted(name: str, size: int) -> bool:
        member = PurePosixPath(name)
        if NOTICE.match(member.name) and size > MAX_NOTICE:
            raise ValueError("License document exceeds the reviewed size limit")
        return size <= MAX_NOTICE and (
            bool(NOTICE.match(member.name))
            or member.suffix in (".java", ".c", ".h", ".cpp")
        )

    def retain(name: str, content: bytes) -> None:
        if NOTICE.match(PurePosixPath(name).name):
            found.append((name, content))
        else:
            # Only a leading comment, not arbitrary embedded sample text.
            match = re.match(rb"\s*(?:/\*.*?\*/|(?://[^\n]*\n)+)", content, re.DOTALL)
            if match and re.search(
                rb"copyright|license|public domain", match[0], re.IGNORECASE
            ):
                found.append((name + " (source preamble)", match[0]))

    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as archive:
            for member in archive.infolist():
                if not member.is_dir() and wanted(member.filename, member.file_size):
                    retain(member.filename, archive.read(member))
    else:
        with tarfile.open(path) as archive:
            for member in archive:
                if member.isfile() and wanted(member.name, member.size):
                    stream = archive.extractfile(member)
                    assert stream is not None
                    with stream:
                        retain(member.name, stream.read(MAX_NOTICE + 1))
    return found


def copy_source(source: Path, output: Path, expected: str) -> str:
    if source.is_symlink() or sha256(source) != expected:
        raise ValueError("Source archive changed after evidence collection")
    name = expected[:16] + "-" + source.name
    safe_relative(name)
    target = output / "sources" / name
    target.parent.mkdir(exist_ok=True)
    # The output is create-only. Shared archives are copied once.
    if not target.exists():
        with source.open("rb") as src, target.open("xb") as dst:
            shutil.copyfileobj(src, dst)
    if sha256(target) != expected:
        raise ValueError("Source companion copy mismatch")
    return "sources/" + name


def prepare(tools: Path, evidence: Path, output: Path) -> dict:
    verify_tree(tools)
    report = json.loads((evidence / "evidence.json").read_text(encoding="utf-8"))
    if report["payload_sha256"] != sha256(tools / "payload.json"):
        raise ValueError("Maven evidence belongs to another scientific payload")
    jars = {p.name: p for p in (tools / "p2rank-2.5.1/bin").rglob("*.jar")}
    rows = report["components"]
    if len(rows) != len(jars) or {r["file"] for r in rows} != set(jars):
        raise ValueError("Incomplete or duplicate JAR evidence")
    for row in rows:
        if row["binary_sha256"] != sha256(jars[row["file"]]):
            raise ValueError("JAR evidence mismatch")
    supplements = json.loads(SUPPLEMENTS.read_text(encoding="utf-8"))["artifacts"]
    entries = [e for e in load_lock() if e["role"] == "source"] + supplements
    for entry in entries:
        verify(CACHE / entry["filename"], entry)
    output.mkdir(parents=True, exist_ok=False)
    documents: dict[str, bytes] = {}
    origins: dict[str, list[str]] = {}

    def add_documents(label: str, pairs: list[tuple[str, bytes]]) -> list[str]:
        digests = []
        for name, raw in pairs:
            digest = hashlib.sha256(raw).hexdigest()
            documents[digest] = raw
            origins.setdefault(digest, []).append(f"{label}: {name}")
            digests.append(digest)
        return sorted(set(digests))

    sources = {}
    for entry in entries:
        source = CACHE / entry["filename"]
        copied = copy_source(source, output, entry["sha256"])
        sources[entry["id"]] = {
            "file": copied,
            "sha256": entry["sha256"],
            "url": entry["url"],
            "documents": add_documents(entry["id"], archive_notices(source)),
        }
    components = []
    gaps = []
    for row in rows:
        name = row["file"]
        metadata, embedded, _ = inspect_jar(jars[name])
        notices = [
            (d["member"], embedded[d["sha256"]])
            for d in metadata["documents"]
            if d["kind"] == "license_or_notice"
        ]
        component = {
            "file": jars[name].relative_to(tools).as_posix(),
            "binary_sha256": row["binary_sha256"],
            "license": LICENSE_OVERRIDES.get(name)
            or "; ".join(
                dict.fromkeys(item["name"] for item in row["license_declarations"])
            ),
            "source_ids": [],
            "evidence": row.get("coordinate", "pinned upstream source"),
        }
        if name in SOURCE_MAP:
            source_id, license_name = SOURCE_MAP[name]
            component["source_ids"].append(source_id)
            component["license"] = license_name
        if row.get("source_archive"):
            relative = str(safe_relative(row["source_archive"]))
            url = CENTRAL + relative
            artifact = next(a for a in row["artifacts"] if a["url"] == url)
            source = evidence / relative
            source_id = "maven:" + row["coordinate"]
            sources[source_id] = {
                "file": copy_source(source, output, artifact["sha256"]),
                "sha256": artifact["sha256"],
                "url": url,
                "documents": add_documents(source_id, archive_notices(source)),
            }
            component["source_ids"].append(source_id)
        if name == "jniloader-1.1.jar":
            component["source_ids"].append("jniloader-source")
        if name == "multiverse-core-0.7.0.jar":
            component["source_ids"].append("multiverse-source")
        if (
            name.startswith(("netlib-", "native_ref-", "native_system-"))
            or name == "core-1.1.2.jar"
        ):
            component["source_ids"].append("netlib-source")
        component["documents"] = add_documents(name, notices)
        if not component["source_ids"]:
            # Guava deliberately ships this empty conflict-avoidance artifact.
            if (
                name.startswith("listenablefuture-9999")
                and metadata["class_count"] == 0
            ):
                component["source_note"] = (
                    "Empty compatibility JAR, no classes to rebuild"
                )
            else:
                gaps.append(f"Missing corresponding source: {name}")
        if not component["license"]:
            gaps.append(f"Missing license declaration: {name}")
        components.append(component)
    for digest, raw in documents.items():
        publish(output / "documents" / digest, raw)
    result = {
        "schema_version": 1,
        "status": "source-evidence-not-legal-approval",
        "payload_sha256": report["payload_sha256"],
        "components": components,
        "sources": sources,
        "documents": origins,
        "gaps": gaps,
    }
    (output / "source-companion.json").write_text(
        json.dumps(result, indent=2) + "\n", encoding="utf-8"
    )
    print(
        f"Source companion: {len(components)} JARs, {len(sources)} sources, {len(gaps)} gaps"
    )
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tools", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    prepare(args.tools, args.evidence, args.output)
