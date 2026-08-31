"""Run the recorded AutoGrid4 Phase 0 compatibility smoke against real artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "backend" / "src"))

from ankora_backend.adapters.engines.autodock4 import (
    collect_autodock_atom_types,
    preflight_autodock4_cpu_atom_types,
    render_autogrid_gpf,
)
from ankora_backend.schemas.binding_sites import BindingBox


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--autogrid", type=Path, required=True)
    parser.add_argument("--receptor", type=Path, required=True)
    parser.add_argument("--vina-batch-record", type=Path, required=True)
    parser.add_argument("--binding-site-record", type=Path, action="append", required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    return parser.parse_args()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _ligand_path(entry: dict[str, Any]) -> Path | None:
    command = entry.get("command")
    if not isinstance(command, list) or "--ligand" not in command:
        return None
    index = command.index("--ligand") + 1
    if index >= len(command) or not isinstance(command[index], str):
        return None
    return Path(command[index])


def _classify_ligands(batch: dict[str, Any]) -> tuple[list[dict[str, Any]], tuple[str, ...]]:
    rows: list[dict[str, Any]] = []
    compatible_documents: list[str] = []
    for entry in batch["entries"]:
        path = _ligand_path(entry)
        row: dict[str, Any] = {
            "ligand_id": entry["ligand_id"],
            "source_index": entry["source_index"],
            "name": entry["name"],
        }
        if path is None or not path.is_file():
            row.update({"compatible": False, "reason": "No prepared PDBQT is recorded."})
            rows.append(row)
            continue
        document = path.read_text(encoding="utf-8")
        atom_types = collect_autodock_atom_types((document,))
        row.update(
            {
                "pdbqt_path": str(path),
                "pdbqt_sha256": _sha256(path),
                "atom_types": atom_types,
            }
        )
        try:
            preflight_autodock4_cpu_atom_types(atom_types)
        except ValueError as error:
            row.update({"compatible": False, "reason": str(error)})
        else:
            row["compatible"] = True
            compatible_documents.append(document)
        rows.append(row)
    return rows, preflight_autodock4_cpu_atom_types(
        collect_autodock_atom_types(compatible_documents)
    )


def _run_probe(executable: Path, argument: str) -> dict[str, Any]:
    completed = subprocess.run(
        [str(executable), argument],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    return {
        "command": [str(executable), argument],
        "exit_code": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }


def _validate_site(
    *,
    index: int,
    site_record_path: Path,
    output_root: Path,
    autogrid: Path,
    receptor: Path,
    receptor_types: tuple[str, ...],
    ligand_types: tuple[str, ...],
) -> dict[str, Any]:
    site_record = _load_json(site_record_path)
    box = BindingBox.model_validate(site_record["box"])
    job_dir = output_root / f"site_{index}"
    job_dir.mkdir()
    local_receptor = job_dir / "receptor.pdbqt"
    shutil.copyfile(receptor, local_receptor)
    gpf, grid = render_autogrid_gpf(
        box,
        receptor_filename=local_receptor.name,
        receptor_atom_types=receptor_types,
        ligand_atom_types=ligand_types,
    )
    gpf_path = job_dir / "receptor.gpf"
    gpf_path.write_text(gpf, encoding="ascii", newline="\n")
    command = [str(autogrid), "-p", gpf_path.name, "-l", "receptor.glg"]
    completed = subprocess.run(
        command,
        cwd=job_dir,
        check=False,
        capture_output=True,
        text=True,
        timeout=3600,
    )
    execution = {
        "command": command,
        "exit_code": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }
    (job_dir / "execution.json").write_text(
        json.dumps(execution, indent=2), encoding="utf-8", newline="\n"
    )
    glg_path = job_dir / "receptor.glg"
    successful_log = (
        glg_path.is_file()
        and "Successful Completion" in glg_path.read_text(encoding="utf-8", errors="replace")
    )
    if completed.returncode != 0 or not successful_log:
        raise RuntimeError(
            f"AutoGrid failed for binding site {site_record['binding_site_id']}; "
            f"raw evidence remains in {job_dir}."
        )
    artifacts = []
    for path in sorted(job_dir.iterdir(), key=lambda item: item.name):
        if path.is_file():
            artifacts.append(
                {
                    "filename": path.name,
                    "size_bytes": path.stat().st_size,
                    "sha256": _sha256(path),
                }
            )
    return {
        "binding_site_id": site_record["binding_site_id"],
        "binding_site_source": site_record["decisions"]["source"],
        "requested_box": box.model_dump(mode="json"),
        "npts": grid.npts,
        "realized_size_angstrom": grid.realized_size_angstrom,
        "successful_log": successful_log,
        "artifacts": artifacts,
    }


def main() -> int:
    args = _parse_args()
    for path in (args.autogrid, args.receptor, args.vina_batch_record):
        if not path.is_file():
            raise FileNotFoundError(path)
    if args.output_root.exists():
        raise FileExistsError(args.output_root)
    args.output_root.mkdir(parents=True)

    batch = _load_json(args.vina_batch_record)
    ligand_rows, ligand_types = _classify_ligands(batch)
    receptor_document = args.receptor.read_text(encoding="utf-8")
    receptor_types = collect_autodock_atom_types((receptor_document,))
    preflight = {
        "batch_id": batch["batch_id"],
        "selected_count": batch["selected_count"],
        "prepared_count": sum("pdbqt_path" in row for row in ligand_rows),
        "cpu_compatible_count": sum(row.get("compatible") is True for row in ligand_rows),
        "cpu_incompatible_count": sum(row.get("compatible") is False for row in ligand_rows),
        "receptor_atom_types": receptor_types,
        "compatible_ligand_atom_type_union": ligand_types,
        "ligands": ligand_rows,
    }
    (args.output_root / "selection_preflight.json").write_text(
        json.dumps(preflight, indent=2), encoding="utf-8", newline="\n"
    )

    report = {
        "validated_at": datetime.now(UTC).isoformat(),
        "autogrid_path": str(args.autogrid),
        "autogrid_sha256": _sha256(args.autogrid),
        "autogrid_probe": _run_probe(args.autogrid, "--version"),
        "receptor_path": str(args.receptor),
        "receptor_sha256": _sha256(args.receptor),
        "receptor_atom_types": receptor_types,
        "compatible_ligand_atom_type_union": ligand_types,
        "selected_count": preflight["selected_count"],
        "prepared_count": preflight["prepared_count"],
        "cpu_compatible_count": preflight["cpu_compatible_count"],
        "cpu_incompatible_count": preflight["cpu_incompatible_count"],
        "sites": [],
    }
    for index, site_record_path in enumerate(args.binding_site_record, start=1):
        report["sites"].append(
            _validate_site(
                index=index,
                site_record_path=site_record_path,
                output_root=args.output_root,
                autogrid=args.autogrid,
                receptor=args.receptor,
                receptor_types=receptor_types,
                ligand_types=ligand_types,
            )
        )
    (args.output_root / "report.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8", newline="\n"
    )
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
