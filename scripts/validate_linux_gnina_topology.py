"""Execute the predeclared GNINA PDBQT/SDF topology engineering check."""

from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import time
from typing import Any

from meeko import PDBQTMolecule, RDKitMolCreate
from rdkit import Chem
from validate_linux_gnina_binary import BINARY, HASHES, LOGS, sha, unique

PROJECT = (
    "logs/linux-crystal-redocking-smoke/exploratory-followup-01/data/projects/default"
)
INPUTS = {
    "binary": (BINARY, HASHES["binary"]),
    "receptor": (
        unique(PROJECT + "/derived/receptors/*/prepared_receptor.pdbqt"),
        "da4cf4adb8d1af6ed05984bbe39b3b9f5a7bfb13530918741694091048704588",
    ),
    "ligand": (
        unique(
            PROJECT + "/derived/ligands/a3b23f57-e4ec-4b91-b309-462848305fa7/"
            "preparations/*/MK1_prepared.pdbqt"
        ),
        "a578aa8d119e30c6c535e47911dc15f0af3d818f303797a051653c8c4709b9b8",
    ),
    "state": (
        unique(
            PROJECT + "/derived/ligands/a3b23f57-e4ec-4b91-b309-462848305fa7/"
            "states/*/inspected_state.sdf"
        ),
        "0dfcb7d3d6024bbe5572c990ff57fdd38e46cfe20b928acb8601bae3ad550982",
    ),
}


def smiles(mol: Any) -> str:
    return str(Chem.MolToSmiles(Chem.RemoveHs(mol), isomericSmiles=True))


def main() -> int:
    output = LOGS / "pdbqt-topology-01"
    output.mkdir(exist_ok=False)
    evidence: dict[str, Any] = {
        "status": "failed",
        "scope": "WSL exploratory topology only",
    }
    try:
        for name, (path, expected) in INPUTS.items():
            if sha(path) != expected:
                raise ValueError(f"Input {name} hash mismatch.")
        for name, filename in (
            ("receptor", "receptor.pdbqt"),
            ("ligand", "ligand.pdbqt"),
            ("state", "state.sdf"),
        ):
            shutil.copyfile(INPUTS[name][0], output / filename)
            if sha(output / filename) != INPUTS[name][1]:
                raise ValueError(f"Copied input {name} hash mismatch.")
        active = subprocess.run(
            ["nvidia-smi", "--query-compute-apps=pid", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        )
        if active.stdout.strip():
            raise RuntimeError("Another GPU compute process is active.")
        state = next(
            (
                item
                for item in Chem.SDMolSupplier(
                    str(output / "state.sdf"), removeHs=False
                )
                if item is not None
            ),
            None,
        )
        if state is None:
            raise ValueError("Input state SDF is unreadable.")
        evidence["input_state"] = {
            "canonical_isomeric_smiles": smiles(state),
            "atoms": state.GetNumAtoms(),
            "heavy_atoms": state.GetNumHeavyAtoms(),
        }
        results: dict[str, Any] = {}
        evidence["runs"] = results
        for fmt in ("sdf", "pdbqt"):
            command = [
                str(BINARY),
                "--receptor",
                "receptor.pdbqt",
                "--ligand",
                "ligand.pdbqt",
                "--center_x",
                "11.634",
                "--center_y",
                "22.47",
                "--center_z",
                "5.8585",
                "--size_x",
                "24.854",
                "--size_y",
                "20.214",
                "--size_z",
                "18.635",
                "--seed",
                "20261029",
                "--cpu",
                "2",
                "--exhaustiveness",
                "1",
                "--num_modes",
                "2",
                "--max_mc_steps",
                "100",
                "--cnn_scoring",
                "rescore",
                "--cnn",
                "dense_1_3",
                "--addH",
                "0",
                "--stripH",
                "0",
                "--device",
                "0",
                "--out",
                f"poses.{fmt}",
            ]
            result: dict[str, Any] = {"command": command}
            results[fmt] = result
            start = time.monotonic()
            with (
                (output / f"{fmt}.stdout").open("x", encoding="utf-8") as stdout,
                (output / f"{fmt}.stderr").open("x", encoding="utf-8") as stderr,
            ):
                process = subprocess.Popen(
                    command,
                    cwd=output,
                    stdout=stdout,
                    stderr=stderr,
                    start_new_session=True,
                )
                observed = False
                deadline = start + 180
                while process.poll() is None:
                    if time.monotonic() >= deadline:
                        os.killpg(process.pid, signal.SIGTERM)
                        try:
                            process.wait(timeout=3)
                        except subprocess.TimeoutExpired:
                            os.killpg(process.pid, signal.SIGKILL)
                            process.wait(timeout=3)
                        raise TimeoutError(f"{fmt} execution exceeded 180 seconds.")
                    query = subprocess.run(
                        [
                            "nvidia-smi",
                            "--query-compute-apps=pid",
                            "--format=csv,noheader,nounits",
                        ],
                        capture_output=True,
                        text=True,
                        timeout=5,
                        check=False,
                    )
                    if (
                        query.returncode == 0
                        and str(process.pid) in query.stdout.split()
                    ):
                        observed = True
                    time.sleep(0.1)
                result.update(
                    {
                        "exit_code": process.returncode,
                        "gpu_process_observed": observed,
                        "duration_seconds": time.monotonic() - start,
                    }
                )
            pose_path = output / f"poses.{fmt}"
            if process.returncode != 0 or not observed or not pose_path.is_file():
                raise RuntimeError(f"{fmt} run failed or GPU execution was unobserved.")
            result["sha256"] = sha(pose_path)
            if fmt == "sdf":
                molecules = [
                    mol
                    for mol in Chem.SDMolSupplier(str(pose_path), removeHs=False)
                    if mol is not None
                ]
                result["poses"] = [
                    {
                        "atoms": mol.GetNumAtoms(),
                        "heavy_atoms": mol.GetNumHeavyAtoms(),
                        "canonical_isomeric_smiles": smiles(mol),
                        "matches_input_state": smiles(mol) == smiles(state),
                        "properties": list(mol.GetPropNames()),
                    }
                    for mol in molecules
                ]
                if not molecules:
                    raise RuntimeError("GNINA SDF contains no valid poses.")
            else:
                text = pose_path.read_text(encoding="utf-8", errors="replace")
                result["meeko_smiles_remark"] = "REMARK SMILES " in text
                try:
                    pdbqt = PDBQTMolecule.from_file(str(pose_path), skip_typing=True)
                    reconstructed = next(
                        (
                            mol
                            for mol in RDKitMolCreate.from_pdbqt_mol(pdbqt)
                            if mol is not None
                        ),
                        None,
                    )
                    result["meeko_reconstructed"] = reconstructed is not None
                    if reconstructed is not None:
                        result["canonical_isomeric_smiles"] = smiles(reconstructed)
                        result["matches_input_state"] = smiles(reconstructed) == smiles(
                            state
                        )
                except Exception as error:  # noqa: BLE001 - retain real reconstruction failure
                    result["reconstruction_error"] = {
                        "type": type(error).__name__,
                        "message": str(error),
                    }
        for name, (path, expected) in INPUTS.items():
            if sha(path) != expected:
                raise RuntimeError(f"Original {name} changed.")
        evidence["status"] = "completed"
    except Exception as error:  # noqa: BLE001 - preserve evidence for any failure
        evidence["error"] = {"type": type(error).__name__, "message": str(error)}
    with (output / "evidence.json").open("x", encoding="utf-8") as handle:
        json.dump(evidence, handle, indent=2, sort_keys=True)
        handle.write("\n")
    print(
        json.dumps(
            {
                "status": evidence["status"],
                "error": evidence.get("error"),
                "evidence_sha256": sha(output / "evidence.json"),
            }
        )
    )
    return 0 if evidence["status"] == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
