"""Create and compare the explicitly authorized P2Rank vecmath-only variant.

Never changes the reference payload, models, or existing scientific records.
The acceptance rule is frozen before execution: byte-identical prediction AND
residue CSVs for all seven upstream example structures, with two Java threads.
This is bounded compatibility evidence, not universal numerical equivalence.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import tarfile
from pathlib import Path

from scripts.windows_scientific_payload import (
    CACHE,
    acquire,
    load_lock,
    safe_relative,
    sha256,
)

VARIANT = "ankora-vecmath-1.5.2-only-v1"
REMOVED = "p2rank-2.5.1/bin/lib/vecmath-1.3.1.jar"
REMOVED_SHA = "dbaa088690a23a954eff669a99d2452a24dd9f10d866725ff5d29ff4740a897e"
RETAINED = "p2rank-2.5.1/bin/lib/vecmath-1.5.2.jar"
RETAINED_SHA = "3558e81ca74c60dc01baca7ef05f48594bbaed43af45d4f1b9196e479734e675"
CASES = (
    "1fbl.pdb",
    "2W83.pdb",
    "clean/1t7qa.pdb",
    "clean/1aaxa.pdb",
    "clean/1nlu.pdb",
    "clean/1a82a.pdb",
    "clean/2ck3b.pdb",
)


def verify_tree(root: Path) -> dict:
    payload = json.loads((root / "payload.json").read_text(encoding="utf-8"))
    files = payload["files"]
    actual = {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()}
    if actual != set(files) | {"payload.json"}:
        raise ValueError("Payload contains missing or unlisted files")
    for relative, expected in files.items():
        path = root / safe_relative(relative)
        if (
            not path.resolve().is_relative_to(root.resolve())
            or sha256(path) != expected
        ):
            raise ValueError(f"Payload integrity failure: {relative}")
    return payload


def create_variant(reference: Path, destination: Path) -> None:
    if destination.exists():
        raise FileExistsError("Candidate payload is create-only")
    payload = verify_tree(reference)
    if payload["files"].get(REMOVED) != REMOVED_SHA:
        raise ValueError("Unexpected vecmath 1.3.1 reference")
    if payload["files"].get(RETAINED) != RETAINED_SHA:
        raise ValueError("Unexpected retained vecmath 1.5.2")
    destination.mkdir(parents=True)
    for relative in payload["files"]:
        if relative == REMOVED:
            continue
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(reference / relative, target)
    del payload["files"][REMOVED]
    payload["tools"]["p2rank"]["variant"] = VARIANT
    payload["p2rank_variant"] = {
        "id": VARIANT,
        "reference_payload_sha256": sha256(reference / "payload.json"),
        "omitted_file": REMOVED,
        "omitted_sha256": REMOVED_SHA,
        "models_and_other_files": "byte-identical to reference",
    }
    (destination / "payload.json").write_text(json.dumps(payload, indent=2) + "\n")
    verify_tree(destination)


def compare(reference: Path, candidate: Path, output: Path) -> dict:
    before = verify_tree(reference)
    after = verify_tree(candidate)
    if after["files"] != {k: v for k, v in before["files"].items() if k != REMOVED}:
        raise ValueError("Candidate changes exceed the single authorized omission")
    if after.get("p2rank_variant", {}).get("id") != VARIANT:
        raise ValueError("Candidate has no authorized variant identity")
    output.mkdir(parents=True, exist_ok=False)
    entries = {entry["id"]: entry for entry in load_lock()}
    archive = acquire(entries["p2rank"], CACHE, offline=True)
    inputs = output / "inputs"
    inputs.mkdir()
    with tarfile.open(archive) as source:
        for case in CASES:
            stream = source.extractfile("p2rank_2.5.1/test_data/" + case)
            if stream is None:
                raise ValueError("Missing declared upstream input")
            (inputs / Path(case).name).write_bytes(stream.read())
    plan = {
        "schema_version": 1,
        "variant": VARIANT,
        "acceptance": "all predictions.csv and residues.csv byte-identical; no tolerance",
        "threads": 2,
        "visualizations": 0,
        "reference_payload_sha256": sha256(reference / "payload.json"),
        "candidate_payload_sha256": sha256(candidate / "payload.json"),
        "inputs": {p.name: sha256(p) for p in sorted(inputs.iterdir())},
    }
    (output / "plan.json").write_text(json.dumps(plan, indent=2) + "\n")
    env = {
        k: v
        for k, v in os.environ.items()
        if k.upper()
        not in {
            "JAVA_TOOL_OPTIONS",
            "JDK_JAVA_OPTIONS",
            "_JAVA_OPTIONS",
            "CLASSPATH",
            "JAVA_HOME",
        }
    }
    env["PATH"] = os.path.join(os.environ["WINDIR"], "System32")
    results = []
    for input_path in sorted(inputs.iterdir()):
        executions = {}
        for label, root in (("reference", reference), ("candidate", candidate)):
            run = output / input_path.stem / label
            run.mkdir(parents=True)
            install = root.resolve() / "p2rank-2.5.1"
            command = [
                str(root.resolve() / "java-21/bin/java.exe"),
                "-Xmx2048m",
                "-cp",
                f"{install / 'bin/p2rank.jar'};{install / 'bin/lib/*'}",
                "cz.siret.prank.program.Main",
                "predict",
                "-f",
                str(input_path.resolve()),
                "-o",
                str(run.resolve()),
                "-visualizations",
                "0",
                "-threads",
                "2",
            ]
            process = subprocess.run(
                command, capture_output=True, env=env, cwd=run, timeout=900, check=False
            )
            (run / "stdout.txt").write_bytes(process.stdout)
            (run / "stderr.txt").write_bytes(process.stderr)
            (run / "execution.json").write_text(
                json.dumps(
                    {"command": command, "exit_code": process.returncode}, indent=2
                )
                + "\n"
            )
            if process.returncode:
                raise RuntimeError(
                    f"P2Rank failed: {input_path.name}/{label}; raw evidence retained"
                )
            executions[label] = {
                suffix: sha256(run / f"{input_path.name}_{suffix}.csv")
                for suffix in ("predictions", "residues")
            }
        passed = executions["reference"] == executions["candidate"]
        results.append({"input": input_path.name, "passed": passed, **executions})
        print(
            f"{input_path.name}: {'identical' if passed else 'DIFFERENT'}", flush=True
        )
    result = {
        "plan_sha256": sha256(output / "plan.json"),
        "passed": all(row["passed"] for row in results),
        "results": results,
    }
    (output / "comparison.json").write_text(json.dumps(result, indent=2) + "\n")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    create_variant(args.reference, args.candidate)
    raise SystemExit(
        0 if compare(args.reference, args.candidate, args.output)["passed"] else 1
    )
