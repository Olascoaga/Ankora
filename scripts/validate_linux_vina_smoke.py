"""Run the predeclared Linux CPU AutoDock Vina engineering smoke.

See docs/validation/LINUX_VINA_CPU_SMOKE_PLAN.md. This exercises Ankora's real
Vina adapter (probe, argument construction, execution, pose parsing) on fixed
development fixtures and records exact evidence. It is a command, pose and
traceability smoke only: no redocking, efficacy, affinity or validation claim,
and the fixed protocol must not be tuned after scores are observed.

Inputs are hash-pinned. Evidence is create-only below ``--output``, which must
not exist. Every outcome after the output directory is created is recorded in
``evidence.json``; a failure is never reported as success.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import platform
import sys
import threading
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "backend" / "src"))

from ankora_backend.adapters.engines.vina import (  # noqa: E402
    VinaInstallation,
    execute_vina,
    parse_vina_poses,
    probe_vina,
)
from ankora_backend.domain.errors import AnkoraDomainError  # noqa: E402
from ankora_backend.execution.cancellable_subprocess import (  # noqa: E402
    CancellableToolExecution,
)
from ankora_backend.schemas.binding_sites import BindingBox  # noqa: E402
from ankora_backend.schemas.docking import (  # noqa: E402
    VinaDockingParameters,
    VinaSamplingProtocol,
)

SCHEMA_VERSION = 1
PLAN = "docs/validation/LINUX_VINA_CPU_SMOKE_PLAN.md"
VINA_VERSION = "1.2.7"
REQUIRED_HOST = ("linux", "x86_64")
# Rank-1 P2Rank pocket centre, copied exactly from the hash-pinned predictions CSV.
POCKET_CENTER = ("-23.7785", "40.9869", "25.9487")
BOX = BindingBox(
    center_x=float(POCKET_CENTER[0]),
    center_y=float(POCKET_CENTER[1]),
    center_z=float(POCKET_CENTER[2]),
    size_x=20.0,
    size_y=20.0,
    size_z=20.0,
)
PARAMETERS = VinaDockingParameters(
    sampling_protocol=VinaSamplingProtocol.CUSTOM,
    cpu_threads=2,
    seed=20261028,
    exhaustiveness=2,
    num_modes=3,
    min_rmsd_angstrom=1.0,
    energy_range_kcal_mol=3.0,
    timeout_minutes=1,
)
SCORE_INTERPRETATION = (
    "Vina scores are computational estimates in kcal/mol from a deliberately small "
    "engineering smoke on development fixtures; they are not experimental affinities, "
    "efficacy evidence or a validation result."
)


@dataclass(frozen=True)
class PinnedIdentities:
    receptor_sha256: str
    ligand_sha256: str
    pocket_predictions_sha256: str
    vina_sha256: str


PINNED = PinnedIdentities(
    receptor_sha256="21067a2249a5f3f4cc7cb83280b2d2ba1c70bf0b2b0c7a29a94e63c6e72d13b5",
    ligand_sha256="23544379c6b5c396e043f2bce0cc8677987ff930159da505e3afa65e5bb04182",
    pocket_predictions_sha256="42574b705d8a1d6e0fd3a122b05b879e3cc5855bc30b6aa32c777d9eec458e7b",
    vina_sha256="f31f774f723bba7bbe6e9d1c47577020eea9a8da16424284c043d22593570644",
)

Probe = Callable[[], VinaInstallation]
Execute = Callable[..., CancellableToolExecution]


class SmokeFailure(Exception):
    def __init__(self, stage: str, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.stage = stage
        self.details = details or {}


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _file_identity(path: Path) -> dict[str, Any]:
    content = path.read_bytes()
    return {
        "file": path.name,
        "size_bytes": len(content),
        "sha256": sha256_bytes(content),
    }


def _verified_copy(source: Path, destination: Path, role: str, expected: str) -> dict[str, Any]:
    if not source.is_file():
        raise SmokeFailure("input_verification", f"{role} input is missing", {"role": role})
    content = source.read_bytes()
    actual = sha256_bytes(content)
    if actual != expected:
        raise SmokeFailure(
            "input_verification",
            f"{role} input differs from the plan",
            {"role": role, "expected_sha256": expected, "actual_sha256": actual},
        )
    with destination.open("xb") as handle:
        handle.write(content)
    if sha256_bytes(destination.read_bytes()) != expected:
        raise SmokeFailure("input_verification", f"{role} copy changed while copying")
    return {"role": role, **_file_identity(destination)}


def _check_pocket_center(predictions: Path) -> None:
    with predictions.open(encoding="utf-8", newline="") as handle:
        rows = [[field.strip() for field in row] for row in csv.reader(handle)]
    try:
        columns = {name: index for index, name in enumerate(rows[0])}
        rank_one = [row for row in rows[1:] if row[columns["rank"]] == "1"]
        if len(rank_one) != 1:
            raise SmokeFailure("pocket_verification", "predictions have no unique rank-1 pocket")
        center = tuple(rank_one[0][columns[name]] for name in ("center_x", "center_y", "center_z"))
    except (IndexError, KeyError) as error:
        raise SmokeFailure("pocket_verification", "predictions CSV is malformed") from error
    if center != POCKET_CENTER:
        raise SmokeFailure(
            "pocket_verification",
            "rank-1 pocket centre differs from the plan",
            {"expected": list(POCKET_CENTER), "actual": list(center)},
        )


def _write_text(path: Path, content: str) -> None:
    with path.open("x", encoding="utf-8", newline="") as handle:
        handle.write(content)


def run_smoke(
    *,
    receptor: Path,
    ligand: Path,
    pocket_predictions: Path,
    output: Path,
    probe: Probe = probe_vina,
    execute: Execute = execute_vina,
    host: tuple[str, str] | None = None,
    pinned: PinnedIdentities = PINNED,
) -> dict[str, Any]:
    """Run once into a new directory; return the evidence written to evidence.json."""
    output.mkdir(parents=True, exist_ok=False)
    system, machine = host or (sys.platform, platform.machine())
    evidence: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "purpose": "Linux CPU Vina engineering smoke (command, pose and traceability only)",
        "plan": PLAN,
        "started_at": datetime.now(UTC).isoformat(),
        "host": {
            "platform": system,
            "machine": machine,
            "python": platform.python_version(),
        },
        "pinned": asdict(pinned),
        "box": BOX.model_dump(mode="json"),
        "parameters": PARAMETERS.model_dump(mode="json"),
        "score_interpretation": SCORE_INTERPRETATION,
        "inputs": [],
        "status": "failed",
    }
    try:
        if not (system.startswith(REQUIRED_HOST[0]) and machine == REQUIRED_HOST[1]):
            raise SmokeFailure(
                "host_verification",
                "the smoke requires Linux x86_64",
                {"platform": system, "machine": machine},
            )
        inputs = output / "inputs"
        inputs.mkdir()
        receptor_copy = inputs / "receptor.pdbqt"
        ligand_copy = inputs / "ligand.pdbqt"
        predictions_copy = inputs / "pocket_predictions.csv"
        for source, destination, role, expected in (
            (receptor, receptor_copy, "receptor", pinned.receptor_sha256),
            (ligand, ligand_copy, "ligand", pinned.ligand_sha256),
            (
                pocket_predictions,
                predictions_copy,
                "pocket_predictions",
                pinned.pocket_predictions_sha256,
            ),
        ):
            evidence["inputs"].append(_verified_copy(source, destination, role, expected))
        _check_pocket_center(predictions_copy)

        installation = probe()
        executable_sha256 = sha256_bytes(Path(installation.executable).read_bytes())
        evidence["vina"] = {
            "version": installation.version,
            "executable": installation.executable,
            "executable_sha256": executable_sha256,
        }
        if installation.version != VINA_VERSION or executable_sha256 != pinned.vina_sha256:
            raise SmokeFailure(
                "vina_identity",
                "the discovered Vina is not the pinned 1.2.7 Linux binary",
                {
                    "expected_sha256": pinned.vina_sha256,
                    "expected_version": VINA_VERSION,
                },
            )

        vina_output = output / "vina_out.pdbqt"
        execution = execute(
            installation=installation,
            receptor_path=receptor_copy,
            ligand_path=ligand_copy,
            output_path=vina_output,
            box=BOX,
            parameters=PARAMETERS,
            cancel_event=threading.Event(),
        )
        _write_text(output / "vina.stdout.txt", execution.stdout)
        _write_text(output / "vina.stderr.txt", execution.stderr)
        evidence["execution"] = {
            "command": execution.command,
            "exit_code": execution.exit_code,
            "canceled": execution.canceled,
            "timed_out": execution.timed_out,
            "stdout": _file_identity(output / "vina.stdout.txt"),
            "stderr": _file_identity(output / "vina.stderr.txt"),
        }
        if vina_output.is_file():
            evidence["raw_output"] = _file_identity(vina_output)
        if execution.exit_code != 0 or execution.canceled or execution.timed_out:
            raise SmokeFailure("vina_execution", "Vina did not complete successfully")
        if not vina_output.is_file():
            raise SmokeFailure("vina_execution", "Vina reported success but wrote no output")
        poses = parse_vina_poses(vina_output.read_bytes())
        evidence["poses"] = [
            {
                "mode": pose.mode,
                "vina_score_kcal_mol": pose.affinity_kcal_mol,
                "rmsd_lower_bound_angstrom": pose.rmsd_lower_bound_angstrom,
                "rmsd_upper_bound_angstrom": pose.rmsd_upper_bound_angstrom,
                "block_sha256": sha256_bytes(pose.content),
            }
            for pose in poses
        ]
        evidence["status"] = "completed"
    except SmokeFailure as failure:
        evidence["failure"] = {
            "stage": failure.stage,
            "message": str(failure),
            "details": failure.details,
        }
    except AnkoraDomainError as error:
        evidence["failure"] = {
            "stage": error.stage,
            "code": error.code,
            "message": error.message,
            "details": error.details,
        }
    except OSError as error:
        evidence["failure"] = {
            "stage": "filesystem",
            "message": f"{type(error).__name__}: {error}",
        }
    except Exception as error:  # record, never hide, an unexpected failure
        evidence["failure"] = {
            "stage": "unexpected",
            "message": f"{type(error).__name__}: {error}",
        }
    evidence["finished_at"] = datetime.now(UTC).isoformat()
    _write_text(output / "evidence.json", json.dumps(evidence, indent=2, sort_keys=True) + "\n")
    return evidence


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the predeclared Linux CPU Vina smoke.")
    parser.add_argument("--receptor", type=Path, required=True)
    parser.add_argument("--ligand", type=Path, required=True)
    parser.add_argument("--pocket-predictions", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True, help="new evidence directory")
    arguments = parser.parse_args(argv)
    output = arguments.output.absolute()
    if output.exists():
        print(f"Refusing to reuse existing output: {output}", file=sys.stderr)
        return 2
    evidence = run_smoke(
        receptor=arguments.receptor,
        ligand=arguments.ligand,
        pocket_predictions=arguments.pocket_predictions,
        output=output,
    )
    record = output / "evidence.json"
    print(f"Vina smoke status: {evidence['status']}")
    if "failure" in evidence:
        print(f"Failure ({evidence['failure']['stage']}): {evidence['failure']['message']}")
    print(f"Evidence: {record}")
    print(f"Evidence SHA-256: {sha256_bytes(record.read_bytes())}")
    return 0 if evidence["status"] == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
