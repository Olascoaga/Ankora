"""Collect official Maven source/POM evidence for exact P2Rank dependency bytes.

Review helper, NOT automatic license approval. Coordinates inferred from metadata
or explicit hints must reproduce the shipped binary SHA-256. Preserve failures
and raw evidence, including inherited license declarations and source archives.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import tempfile
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from scripts.inventory_p2rank_dependencies import inspect_jar, pom_declarations
from scripts.validate_p2rank_variant import verify_tree
from scripts.windows_scientific_payload import safe_relative, sha256

CENTRAL = "https://repo.maven.apache.org/maven2/"
# Hints are not trusted provenance: every binary is independently hash-matched.
HINTS = {
    "arpack_combined_all": "net.sourceforge.f2j",
    "ejml-core": "org.ejml",
    "euclid": "us.ihmc",
    "flatlaf": "com.formdev",
    "gpars": "org.codehaus.gpars",
    "groovy": "org.apache.groovy",
    "hppc": "com.carrotsearch",
    "jackson-dataformat-msgpack": "org.msgpack",
    "jama": "gov.nist.math",
    "jheaps": "org.jheaps",
    "jspecify": "org.jspecify",
    "jsr166y": "org.codehaus.jsr166-mirror",
    "mmtf-api": "org.rcsb",
    "mmtf-codec": "org.rcsb",
    "mmtf-serialization": "org.rcsb",
    "msgpack-core": "org.msgpack",
    "openchart": "openchart",
    "xom": "xom",
    "xz": "org.tukaani",
    "zstd-jni": "com.github.luben",
    "zt-zip": "org.zeroturnaround",
    "bounce": "nz.ac.waikato.cms.weka.thirdparty",
}


def coordinate(jar: Path, metadata: dict) -> tuple[str, str, str]:
    poms = metadata["pom_declarations"]
    if len(poms) == 1:
        pom = poms[0]
        parent = pom["parent"] or {}
        group = pom["group"] or parent.get("group", "")
        version = pom["version"] or parent.get("version", "")
        artifact = pom["artifact"]
        return HINTS.get(artifact, group), artifact, version
    match = re.fullmatch(r"(.+?)-(\d.+)\.jar", jar.name)
    if match and match[1] in HINTS:
        return HINTS[match[1]], match[1], match[2]
    raise ValueError(
        "No verified Maven coordinate; review pinned upstream source separately"
    )


def fetch(relative: str, output: Path) -> Path:
    safe_relative(relative)
    target = output / relative
    if target.exists():
        return target
    with urllib.request.urlopen(CENTRAL + relative, timeout=60) as response:
        if not response.url.startswith(CENTRAL):
            raise ValueError("Unexpected Maven redirect")
        content = response.read(100 * 1024 * 1024 + 1)
    if len(content) > 100 * 1024 * 1024:
        raise ValueError("Oversized Maven response")
    target.parent.mkdir(parents=True, exist_ok=True)
    publish(target, content)
    return target


def publish(target: Path, content: bytes) -> None:
    """Publish complete bytes create-only; readers never see partial evidence."""
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as stream:
        temporary = Path(stream.name)
        stream.write(content)
    try:
        try:
            target.hardlink_to(temporary)
        except FileExistsError:
            if target.read_bytes() != content:
                raise ValueError("Concurrent Maven evidence mismatch") from None
    finally:
        temporary.unlink()


def maven_path(group: str, artifact: str, version: str) -> str:
    if not all(
        re.fullmatch(r"[A-Za-z0-9_.+-]+", item) for item in (group, artifact, version)
    ):
        raise ValueError("Unresolved or unsafe Maven coordinate")
    return f"{group.replace('.', '/')}/{artifact}/{version}/{artifact}-{version}"


def collect_one(jar: Path, output: Path) -> dict:
    metadata, documents, _ = inspect_jar(jar)
    row = {
        "file": jar.name,
        "binary_sha256": sha256(jar),
        "status": "pending-review",
        "artifacts": [],
        "license_declarations": [],
        "documents": [],
    }
    try:
        group, artifact, version = coordinate(jar, metadata)
        base = maven_path(group, artifact, version)
        classifier = "-natives" if jar.name.endswith("-natives.jar") else ""
        binary = fetch(base + classifier + ".jar", output)
        if sha256(binary) != row["binary_sha256"]:
            raise ValueError("Maven binary differs from shipped bytes")
        row["coordinate"] = f"{group}:{artifact}:{version}{classifier}"
        row["binary_url"] = CENTRAL + base + classifier + ".jar"
        for depth in range(12):
            pom_path = maven_path(group, artifact, version) + ".pom"
            pom_file = fetch(pom_path, output)
            raw = pom_file.read_bytes()
            documents[hashlib.sha256(raw).hexdigest()] = raw
            row["artifacts"].append(
                {"url": CENTRAL + pom_path, "sha256": sha256(pom_file)}
            )
            pom = pom_declarations(raw)
            row["license_declarations"].extend(pom["licenses"])
            parent = pom["parent"]
            if parent is None:
                break
            group, artifact, version = (
                parent["group"],
                parent["artifact"],
                parent["version"],
            )
        else:
            raise ValueError("Excessive Maven parent chain")
        try:
            source = fetch(base + "-sources.jar", output)
            row["artifacts"].append(
                {"url": CENTRAL + base + "-sources.jar", "sha256": sha256(source)}
            )
            _, source_documents, _ = inspect_jar(source)
            documents.update(source_documents)
            row["source_archive"] = source.relative_to(output).as_posix()
        except urllib.error.HTTPError as error:
            if error.code != 404:
                raise
            row["source_gap"] = (
                "No Maven sources JAR; corresponding upstream source required"
            )
    except (ValueError, OSError, urllib.error.URLError) as error:
        row["error"] = str(error)
    evidence_dir = output / "documents"
    evidence_dir.mkdir(exist_ok=True)
    for digest, raw in documents.items():
        target = evidence_dir / digest
        publish(target, raw)
        row["documents"].append(digest)
    print(
        f"{jar.name}: {row.get('error', row.get('source_gap', 'binary/source verified'))}",
        flush=True,
    )
    return row


def collect(tools: Path, output: Path) -> None:
    verify_tree(tools)
    output.mkdir(parents=True, exist_ok=False)
    jars = sorted((tools / "p2rank-2.5.1/bin").rglob("*.jar"))
    with ThreadPoolExecutor(max_workers=4) as workers:
        rows = list(workers.map(lambda jar: collect_one(jar, output), jars))
    manifest = {
        "schema_version": 1,
        "status": "pending-review-not-approved",
        "payload_sha256": sha256(tools / "payload.json"),
        "components": rows,
    }
    (output / "evidence.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tools", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    collect(args.tools, args.output)
