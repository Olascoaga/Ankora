"""Inventory the exact staged P2Rank dependency bytes for redistribution review.

No JAR is executed, changed, removed or granted redistribution approval. Embedded
POM declarations are evidence, not an assertion that all obligations are met.
Every copied document is content-addressed; upstream archive paths are never
used as filesystem destinations. Missing evidence remains visible in the report.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import xml.etree.ElementTree as ET
import zipfile
from collections import defaultdict
from pathlib import Path, PurePosixPath
from typing import Any

try:
    from scripts.windows_scientific_payload import safe_relative, sha256
except ModuleNotFoundError:
    from windows_scientific_payload import safe_relative, sha256

NOTICE = re.compile(r"^(license|licence|copying|copyright|notice)([._-]|$)", re.I)
MAX_DOCUMENT = 4 * 1024 * 1024
MAX_METADATA = 64 * 1024 * 1024


def pom_declarations(content: bytes) -> dict[str, Any]:
    # POM files are upstream input. Do not resolve entities or remote DTDs.
    text = content.decode("utf-8-sig")
    if "<!DOCTYPE" in text.upper() or "<!ENTITY" in text.upper():
        raise ValueError("POM declarations may not contain DTDs or entities")
    root = ET.fromstring(text)

    def field(element: ET.Element, name: str) -> str:
        return (element.findtext(f"{{*}}{name}") or "").strip()

    parent = root.find("{*}parent")
    return {
        "group": field(root, "groupId"),
        "artifact": field(root, "artifactId"),
        "version": field(root, "version"),
        "parent": (
            {
                key: field(parent, name)
                for key, name in (
                    ("group", "groupId"),
                    ("artifact", "artifactId"),
                    ("version", "version"),
                )
            }
            if parent is not None
            else None
        ),
        "licenses": [
            {"name": field(item, "name"), "url": field(item, "url")}
            for item in root.findall("{*}licenses/{*}license")
        ],
        "project_url": field(root, "url"),
        "scm_url": (root.findtext("{*}scm/{*}url") or "").strip(),
    }


def inspect_jar(path: Path) -> tuple[dict[str, Any], dict[str, bytes], set[str]]:
    documents: dict[str, bytes] = {}
    metadata: list[dict[str, str]] = []
    poms = []
    classes: set[str] = set()
    native_members = []
    source_members = 0
    metadata_size = 0
    with zipfile.ZipFile(path) as jar:
        names: set[str] = set()
        for entry in sorted(jar.infolist(), key=lambda item: item.filename):
            if entry.filename in names:
                raise ValueError(f"Duplicate JAR member in {path.name}")
            names.add(entry.filename)
            if entry.is_dir():
                continue
            member = PurePosixPath(entry.filename)
            if member.suffix == ".class" and member.name != "module-info.class":
                classes.add(entry.filename)
            if member.suffix == ".java":
                source_members += 1
            if member.suffix.lower() in (".dll", ".so", ".dylib", ".jnilib"):
                native_members.append(entry.filename)
            notice = bool(NOTICE.match(member.name))
            if not (notice or member.name in ("pom.xml", "pom.properties", "MANIFEST.MF")):
                continue
            metadata_size += entry.file_size
            if entry.file_size > MAX_DOCUMENT or metadata_size > MAX_METADATA:
                raise ValueError(f"Oversized JAR metadata in {path.name}")
            content = jar.read(entry)
            digest = hashlib.sha256(content).hexdigest()
            documents[digest] = content
            metadata.append(
                {
                    "member": entry.filename,
                    "sha256": digest,
                    "kind": "license_or_notice" if notice else "package_metadata",
                }
            )
            if member.name == "pom.xml":
                poms.append({"member": entry.filename, **pom_declarations(content)})
    return (
        {
            "sha256": sha256(path),
            "size_bytes": path.stat().st_size,
            "class_count": len(classes),
            "source_member_count": source_members,
            "native_members": native_members,
            "documents": metadata,
            "pom_declarations": poms,
            "review_status": "pending",
        },
        documents,
        classes,
    )


def verified_payload_files(tools: Path) -> dict[str, str]:
    root = tools.resolve(strict=True)
    payload = json.loads((root / "payload.json").read_text(encoding="utf-8"))
    if payload.get("schema_version") != 1:
        raise ValueError("Unsupported staged payload schema")
    files = payload.get("files")
    if not isinstance(files, dict) or not files:
        raise ValueError("Missing staged payload file inventory")
    actual = {
        file.relative_to(root).as_posix()
        for file in root.rglob("*")
        if file.is_file() and file != root / "payload.json"
    }
    if actual != set(files):
        raise ValueError("Staged payload contains missing or unlisted files")
    for name, expected in files.items():
        relative = safe_relative(name)
        candidate = root.joinpath(*relative.parts)
        if not candidate.resolve(strict=True).is_relative_to(root):
            raise ValueError("Staged payload escaped its root")
        if any(
            part.is_symlink() or part.is_junction()
            for part in (candidate, *candidate.parents)
            if part != root and part.is_relative_to(root)
        ):
            raise ValueError("Linked files are not payload evidence")
        if not re.fullmatch(r"[0-9a-f]{64}", expected) or sha256(candidate) != expected:
            raise ValueError(f"Staged payload hash mismatch: {name}")
    return files


def build_inventory(tools: Path) -> tuple[dict[str, Any], dict[str, bytes]]:
    files = verified_payload_files(tools)
    prefix = "p2rank-2.5.1/"
    jar_names = sorted(name for name in files if name.startswith(prefix) and name.endswith(".jar"))
    if prefix + "bin/p2rank.jar" not in jar_names:
        raise ValueError("Expected staged P2Rank 2.5.1 executable JAR")
    records = []
    documents = {}
    owners: dict[str, list[str]] = defaultdict(list)
    for name in jar_names:
        record, texts, classes = inspect_jar(tools / name)
        records.append({"path": name, **record})
        documents.update(texts)
        for class_name in classes:
            owners[class_name].append(name)
    duplicate_classes = [
        {"class": name, "jars": sorted(paths)}
        for name, paths in sorted(owners.items())
        if len(paths) > 1
    ]
    models = {name: digest for name, digest in files.items() if name.startswith(prefix + "models/")}
    return (
        {
            "schema_version": 1,
            "component": "P2Rank 2.5.1",
            "scope": "Exact staged JARs, embedded native code, models and metadata",
            "redistribution_status": "pending-review-not-approved",
            "policy": "Embedded declarations do not replace notice/source/compatibility review.",
            "jars": records,
            "models": dict(sorted(models.items())),
            "duplicate_classes": duplicate_classes,
            "missing_embedded_license": [
                record["path"]
                for record in records
                if not any(doc["kind"] == "license_or_notice" for doc in record["documents"])
            ],
        },
        documents,
    )


def write_inventory(report: dict[str, Any], documents: dict[str, bytes], output: Path) -> None:
    if any(hashlib.sha256(content).hexdigest() != digest for digest, content in documents.items()):
        raise ValueError("Document identity does not match its exact bytes")
    output.mkdir(parents=True, exist_ok=False)
    evidence = output / "documents"
    evidence.mkdir()
    for digest, content in sorted(documents.items()):
        with (evidence / f"{digest}.txt").open("xb") as stream:
            stream.write(content)
    with (output / "inventory.json").open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(report, indent=2, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tools-dir", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    report, documents = build_inventory(args.tools_dir)
    write_inventory(report, documents, args.output)
    print(
        f"Inventoried {len(report['jars'])} JARs, {len(documents)} exact documents, "
        f"{len(report['missing_embedded_license'])} without embedded license text. "
        "Redistribution review remains pending."
    )
