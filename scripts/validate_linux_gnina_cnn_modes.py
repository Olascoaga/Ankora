"""Run the predeclared GNINA 1.3.3 CNN modes, ensemble identity, and memory probe."""

from __future__ import annotations

import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path
from statistics import fmean, pvariance
from typing import Any

import psutil
from meeko import PDBQTMolecule, RDKitMolCreate
from rdkit import Chem
from validate_linux_gnina_binary import BINARY, HASHES, LOGS, sha, unique

PROJECT = "logs/linux-crystal-redocking-smoke/exploratory-followup-01/data/projects/default"
INPUTS = {
    "binary": (BINARY, HASHES["binary"]),
    "receptor": (
        unique(PROJECT + "/derived/receptors/*/prepared_receptor.pdbqt"),
        "da4cf4adb8d1af6ed05984bbe39b3b9f5a7bfb13530918741694091048704588",
    ),
    "ligand": (
        unique(
            PROJECT
            + "/derived/ligands/a3b23f57-e4ec-4b91-b309-462848305fa7/"
            + "preparations/*/MK1_prepared.pdbqt"
        ),
        "a578aa8d119e30c6c535e47911dc15f0af3d818f303797a051653c8c4709b9b8",
    ),
    "state": (
        unique(
            PROJECT
            + "/derived/ligands/a3b23f57-e4ec-4b91-b309-462848305fa7/"
            + "states/*/inspected_state.sdf"
        ),
        "0dfcb7d3d6024bbe5572c990ff57fdd38e46cfe20b928acb8601bae3ad550982",
    ),
}

BOX_ARGS = [
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
]

GNINA_1_3_DEFAULT_MEMBERS = (
    "dense_1_3",
    "dense_1_3_PT_KD_3",
    "crossdock_default2018_KD_4",
)

GNINA_1_0_DEFAULT_MEMBERS = (
    "dense",
    "general_default2018_3",
    "dense_3",
    "crossdock_default2018",
    "redock_default2018_2",
)

_REMARK_LINE = re.compile(r"^REMARK\s+(\S+)(?:\s+(.*))?$")


def smiles(mol: Any) -> str:
    return str(Chem.MolToSmiles(Chem.RemoveHs(mol), isomericSmiles=True))


def query_gpu_device_memory_mib() -> dict[str, int]:
    res = subprocess.run(
        [
            "nvidia-smi",
            "--query-gpu=memory.total,memory.used,memory.free",
            "--format=csv,noheader,nounits",
        ],
        capture_output=True,
        text=True,
        timeout=5,
        check=True,
    )
    parts = [int(x.strip()) for x in res.stdout.splitlines()[0].split(",")]
    return {"total_mib": parts[0], "used_mib": parts[1], "free_mib": parts[2]}


def inspect_pdbqt(path: Path, expected_smiles: str) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8", errors="replace")
    models: list[dict[str, Any]] = []
    current_remarks: list[str] = []
    current_scores: dict[str, float] = {}
    in_model = False
    for raw_line in text.splitlines():
        stripped = raw_line.strip()
        if stripped.startswith("MODEL "):
            in_model = True
            current_remarks = []
            current_scores = {}
            continue
        if stripped == "ENDMDL" and in_model:
            models.append({"remark_keys": current_remarks, "numeric_remarks": current_scores})
            in_model = False
            continue
        if in_model and stripped.startswith("REMARK"):
            match = _REMARK_LINE.match(stripped)
            if match:
                key = match.group(1)
                rest = (match.group(2) or "").strip()
                current_remarks.append(key)
                if rest and len(rest.split()) == 1:
                    try:
                        current_scores[key] = float(rest)
                    except ValueError:
                        pass
    pdbqt = PDBQTMolecule.from_file(str(path), skip_typing=True)
    reconstructed = [mol for mol in RDKitMolCreate.from_pdbqt_mol(pdbqt) if mol is not None]
    topo_ok = bool(reconstructed) and all(smiles(mol) == expected_smiles for mol in reconstructed)
    return {
        "model_count": len(models),
        "models": models,
        "meeko_reconstructed_count": len(reconstructed),
        "topology_matches_input_state": topo_ok,
    }


def inspect_sdf(path: Path, expected_smiles: str) -> dict[str, Any]:
    molecules = [mol for mol in Chem.SDMolSupplier(str(path), removeHs=False) if mol is not None]
    records: list[dict[str, Any]] = []
    for mol in molecules:
        props = list(mol.GetPropNames())
        numeric: dict[str, float] = {}
        for name in props:
            try:
                numeric[name] = float(mol.GetProp(name).strip())
            except ValueError:
                pass
        records.append(
            {
                "properties": props,
                "numeric_properties": numeric,
                "matches_input_state": smiles(mol) == expected_smiles,
            }
        )
    return {
        "record_count": len(records),
        "records": records,
    }


def run_monitored(
    *,
    command: list[str],
    cwd: Path,
    run_key: str,
    expect_gpu: bool,
    timeout_seconds: int = 600,
    allow_timeout: bool = False,
) -> dict[str, Any]:
    stdout_path = cwd / f"{run_key}.stdout"
    stderr_path = cwd / f"{run_key}.stderr"
    baseline_gpu_used_mib = query_gpu_device_memory_mib()["used_mib"] if expect_gpu else 0
    peak_device_used_mib = baseline_gpu_used_mib
    peak_proc_gpu_mib: int | None = None
    peak_rss_bytes = 0
    gpu_seen = False
    timed_out = False
    observed_uuids: set[str] = set()
    start = time.monotonic()
    with (
        stdout_path.open("x", encoding="utf-8") as stdout_handle,
        stderr_path.open("x", encoding="utf-8") as stderr_handle,
    ):
        process = subprocess.Popen(
            command,
            cwd=cwd,
            stdout=stdout_handle,
            stderr=stderr_handle,
            start_new_session=True,
        )
        proc_info: psutil.Process | None = None
        try:
            proc_info = psutil.Process(process.pid)
        except psutil.Error:
            proc_info = None
        deadline = start + timeout_seconds
        while process.poll() is None:
            if time.monotonic() >= deadline:
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait(timeout=3)
                if not allow_timeout:
                    raise TimeoutError(f"Run {run_key} exceeded {timeout_seconds}s timeout.")
                timed_out = True
                break
            if proc_info is not None:
                try:
                    rss = proc_info.memory_info().rss
                    peak_rss_bytes = max(peak_rss_bytes, rss)
                except psutil.Error:
                    pass
            if expect_gpu:
                query = subprocess.run(
                    [
                        "nvidia-smi",
                        "--query-compute-apps=pid,gpu_uuid,used_gpu_memory",
                        "--format=csv,noheader,nounits",
                    ],
                    capture_output=True,
                    text=True,
                    timeout=5,
                    check=False,
                )
                if query.returncode == 0:
                    for line in query.stdout.splitlines():
                        parts = [item.strip() for item in line.split(",")]
                        if len(parts) == 3 and parts[0] == str(process.pid):
                            gpu_seen = True
                            observed_uuids.add(parts[1])
                            try:
                                mem_mib = int(parts[2])
                                if peak_proc_gpu_mib is None or mem_mib > peak_proc_gpu_mib:
                                    peak_proc_gpu_mib = mem_mib
                            except ValueError:
                                pass
                dev_mem = query_gpu_device_memory_mib()["used_mib"]
                peak_device_used_mib = max(peak_device_used_mib, dev_mem)
            time.sleep(0.08)
        exit_code = process.returncode
    duration = time.monotonic() - start
    return {
        "command": command,
        "exit_code": exit_code,
        "timed_out": timed_out,
        "duration_seconds": round(duration, 4),
        "gpu_process_observed": gpu_seen,
        "observed_gpu_uuids": sorted(observed_uuids),
        "baseline_device_used_gpu_mib": baseline_gpu_used_mib,
        "peak_device_used_gpu_mib": peak_device_used_mib,
        "peak_device_delta_gpu_mib": max(0, peak_device_used_mib - baseline_gpu_used_mib),
        "per_process_reported_gpu_mib": peak_proc_gpu_mib,
        "peak_host_rss_mib": round(peak_rss_bytes / (1024 * 1024), 2),
        "stdout_sha256": sha(stdout_path),
        "stderr_sha256": sha(stderr_path),
    }


def score_only_pdbqt(
    *,
    cwd: Path,
    pose_file: str,
    run_key: str,
    cnn_args: list[str],
) -> dict[str, Any]:
    cmd = [
        str(BINARY),
        "--receptor",
        "receptor.pdbqt",
        "--ligand",
        pose_file,
        "--score_only",
        *cnn_args,
        "--addH",
        "0",
        "--stripH",
        "0",
        "--device",
        "0",
    ]
    info = run_monitored(command=cmd, cwd=cwd, run_key=run_key, expect_gpu=True)
    stdout_text = (cwd / f"{run_key}.stdout").read_text(encoding="utf-8", errors="replace")
    score_match = re.search(r"CNNscore:\s*([0-9.eE+-]+)", stdout_text)
    aff_match = re.search(r"CNNaffinity:\s*([0-9.eE+-]+)", stdout_text)
    var_match = re.search(r"CNNvariance:\s*([0-9.eE+-]+)", stdout_text)
    if info["exit_code"] != 0 or score_match is None or aff_match is None:
        raise RuntimeError(f"--score_only failed for {run_key}: {stdout_text}")
    info["cnn_score"] = float(score_match.group(1))
    info["cnn_affinity"] = float(aff_match.group(1))
    info["cnn_variance_stdout"] = float(var_match.group(1)) if var_match else None
    return info


def main() -> int:
    cpu_followup = "--cpu-followup" in sys.argv[1:]
    output = LOGS / "cnn-modes-04"
    output.mkdir(exist_ok=False)
    evidence: dict[str, Any] = {
        "status": "failed",
        "scope": "WSL exploratory GNINA 1.3.3 CNN modes, ensemble member proof, and memory probe",
    }
    try:
        if not sys.platform.startswith("linux"):
            raise ValueError("This probe requires Linux.")
        for name, (path, expected) in INPUTS.items():
            if sha(path) != expected:
                raise ValueError(f"Declared input {name} hash mismatch.")
        for name, filename in (
            ("receptor", "receptor.pdbqt"),
            ("ligand", "ligand.pdbqt"),
            ("state", "state.sdf"),
        ):
            shutil.copyfile(INPUTS[name][0], output / filename)
            if sha(output / filename) != INPUTS[name][1]:
                raise ValueError(f"Copied {name} hash mismatch.")

        gpu_idle = subprocess.run(
            ["nvidia-smi", "--query-compute-apps=pid", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        )
        if gpu_idle.stdout.strip():
            raise RuntimeError("Another GPU compute process is active; aborting probe.")

        gpu_meta = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=name,uuid,driver_version,memory.total,memory.free",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        )
        evidence["gpu_device"] = gpu_meta.stdout.strip()

        state_mol = next(
            mol for mol in Chem.SDMolSupplier(str(output / "state.sdf"), removeHs=False) if mol
        )
        expected_smiles = smiles(state_mol)
        evidence["expected_isomeric_smiles"] = expected_smiles

        # 1. Verify `--cnn default` is rejected by GNINA 1.3.3
        invalid_default = run_monitored(
            command=[
                str(BINARY),
                "--receptor",
                "receptor.pdbqt",
                "--ligand",
                "ligand.pdbqt",
                "--score_only",
                "--cnn",
                "default",
                "--addH",
                "0",
                "--stripH",
                "0",
                "--no_gpu",
            ],
            cwd=output,
            run_key="invalid_cnn_default",
            expect_gpu=False,
        )
        invalid_stderr = (output / "invalid_cnn_default.stderr").read_text(
            encoding="utf-8", errors="replace"
        )
        evidence["invalid_cnn_default_check"] = {
            **invalid_default,
            "stderr_excerpt": invalid_stderr.strip(),
        }
        if invalid_default["exit_code"] == 0:
            raise RuntimeError("Expected `--cnn default` to be rejected by GNINA 1.3.3.")

        # 2. Prove exact ensemble membership on static input `ligand.pdbqt` via `--score_only`
        omitted_eval = score_only_pdbqt(
            cwd=output, pose_file="ligand.pdbqt", run_key="score_omitted_default", cnn_args=[]
        )
        members_1_3 = {
            member: score_only_pdbqt(
                cwd=output,
                pose_file="ligand.pdbqt",
                run_key=f"score_1_3_{member}",
                cnn_args=["--cnn", member],
            )
            for member in GNINA_1_3_DEFAULT_MEMBERS
        }
        mean_score_1_3 = fmean(item["cnn_score"] for item in members_1_3.values())
        mean_aff_1_3 = fmean(item["cnn_affinity"] for item in members_1_3.values())
        var_aff_1_3 = pvariance(item["cnn_affinity"] for item in members_1_3.values())

        default1_0_eval = score_only_pdbqt(
            cwd=output,
            pose_file="ligand.pdbqt",
            run_key="score_default1_0",
            cnn_args=["--cnn", "default1.0"],
        )
        members_1_0 = {
            member: score_only_pdbqt(
                cwd=output,
                pose_file="ligand.pdbqt",
                run_key=f"score_1_0_{member}",
                cnn_args=["--cnn", member],
            )
            for member in GNINA_1_0_DEFAULT_MEMBERS
        }
        mean_score_1_0 = fmean(item["cnn_score"] for item in members_1_0.values())
        mean_aff_1_0 = fmean(item["cnn_affinity"] for item in members_1_0.values())
        var_aff_1_0 = pvariance(item["cnn_affinity"] for item in members_1_0.values())

        evidence["ensemble_membership_proof"] = {
            "omitted_cnn_default_1_3": {
                "declared_members": list(GNINA_1_3_DEFAULT_MEMBERS),
                "ensemble_eval": omitted_eval,
                "member_evals": members_1_3,
                "member_mean_cnn_score": mean_score_1_3,
                "member_mean_cnn_affinity": mean_aff_1_3,
                "member_population_var_cnn_affinity": var_aff_1_3,
                "abs_diff_cnn_score": abs(mean_score_1_3 - omitted_eval["cnn_score"]),
                "abs_diff_cnn_affinity": abs(mean_aff_1_3 - omitted_eval["cnn_affinity"]),
                "abs_diff_cnn_variance": abs(
                    var_aff_1_3 - (omitted_eval["cnn_variance_stdout"] or 0.0)
                ),
            },
            "cnn_default1_0": {
                "declared_members": list(GNINA_1_0_DEFAULT_MEMBERS),
                "ensemble_eval": default1_0_eval,
                "member_evals": members_1_0,
                "member_mean_cnn_score": mean_score_1_0,
                "member_mean_cnn_affinity": mean_aff_1_0,
                "member_population_var_cnn_affinity": var_aff_1_0,
                "abs_diff_cnn_score": abs(mean_score_1_0 - default1_0_eval["cnn_score"]),
                "abs_diff_cnn_affinity": abs(mean_aff_1_0 - default1_0_eval["cnn_affinity"]),
                "abs_diff_cnn_variance": abs(
                    var_aff_1_0 - (default1_0_eval["cnn_variance_stdout"] or 0.0)
                ),
            },
        }
        if (
            abs(mean_score_1_3 - omitted_eval["cnn_score"]) > 1e-4
            or abs(mean_aff_1_3 - omitted_eval["cnn_affinity"]) > 1e-4
            or abs(var_aff_1_3 - (omitted_eval["cnn_variance_stdout"] or -1.0)) > 1e-4
        ):
            raise RuntimeError("GNINA 1.3 default ensemble did not match 3 declared members!")
        if (
            abs(mean_score_1_0 - default1_0_eval["cnn_score"]) > 1e-4
            or abs(mean_aff_1_0 - default1_0_eval["cnn_affinity"]) > 1e-4
            or abs(var_aff_1_0 - (default1_0_eval["cnn_variance_stdout"] or -1.0)) > 1e-4
        ):
            raise RuntimeError("GNINA default1.0 ensemble did not match 5 declared members!")

        # 3. Matrix across {cuda, cpu} x {rescore, refinement} x {dense_1_3, default_ensemble, default1_0}
        matrix_runs: dict[str, Any] = {}
        evidence["matrix_runs"] = matrix_runs
        models_spec: list[tuple[str, list[str]]] = [
            ("dense_1_3", ["--cnn", "dense_1_3"]),
            ("default_ensemble", []),
            ("default1_0", ["--cnn", "default1.0"]),
        ]
        compute_specs = (
            (("cpu", ["--no_gpu"], False),)
            if cpu_followup
            else (("cuda", ["--device", "0"], True), ("cpu", ["--no_gpu"], False))
        )
        for compute, compute_args, expect_gpu in compute_specs:
            formats = ("pdbqt", "sdf") if compute == "cuda" else ("pdbqt",)
            for scoring in ("rescore", "refinement"):
                for model_key, model_args in models_spec:
                    if cpu_followup and not (
                        (scoring == "rescore" and model_key == "default1_0")
                        or (scoring == "refinement" and model_key == "dense_1_3")
                    ):
                        continue
                    if not cpu_followup and compute == "cpu" and scoring == "refinement" and model_key != "dense_1_3":
                        continue
                    for fmt in formats:
                        if fmt == "sdf" and model_key == "default1_0":
                            continue
                        run_id = f"{compute}_{scoring}_{model_key}_{fmt}"
                        out_name = f"{run_id}.{fmt}"
                        is_cpu_refinement = compute == "cpu" and scoring == "refinement"
                        exhaustiveness = (
                            "1"
                            if is_cpu_refinement
                            else ("2" if cpu_followup else "4")
                        )
                        num_modes = "1" if is_cpu_refinement else "5"
                        cmd = [
                            str(BINARY),
                            "--receptor",
                            "receptor.pdbqt",
                            "--ligand",
                            "ligand.pdbqt",
                            *BOX_ARGS,
                            "--seed",
                            "20261029",
                            "--cpu",
                            "4" if compute == "cpu" else "2",
                            "--exhaustiveness",
                            exhaustiveness,
                            "--num_modes",
                            num_modes,
                            "--min_rmsd_filter",
                            "1.0",
                            "--cnn_scoring",
                            scoring,
                            *model_args,
                            "--addH",
                            "0",
                            "--stripH",
                            "0",
                            *compute_args,
                            "--out",
                            out_name,
                        ]
                        info = run_monitored(
                            command=cmd,
                            cwd=output,
                            run_key=run_id,
                            expect_gpu=expect_gpu,
                            timeout_seconds=60 if is_cpu_refinement else 600,
                            allow_timeout=is_cpu_refinement,
                        )
                        out_path = output / out_name
                        if info["timed_out"]:
                            matrix_runs[run_id] = info
                            continue
                        if info["exit_code"] != 0 or not out_path.is_file():
                            raise RuntimeError(
                                f"Matrix run {run_id} failed with exit_code={info['exit_code']}."
                            )
                        if expect_gpu and not info["gpu_process_observed"]:
                            raise RuntimeError(f"CUDA matrix run {run_id} was not observed on GPU.")
                        info["output_sha256"] = sha(out_path)
                        if fmt == "pdbqt":
                            insp = inspect_pdbqt(out_path, expected_smiles)
                            if not insp["topology_matches_input_state"]:
                                raise RuntimeError(f"Topology mismatch on {run_id}.")
                            info["pdbqt_inspection"] = insp
                        else:
                            insp = inspect_sdf(out_path, expected_smiles)
                            info["sdf_inspection"] = insp
                        matrix_runs[run_id] = info

        for name, (path, expected) in INPUTS.items():
            if sha(path) != expected:
                raise RuntimeError(f"Original {name} modified during probe!")

        evidence["status"] = "completed"
    except Exception as error:  # noqa: BLE001 - retain structured failure evidence
        evidence["error"] = {"type": type(error).__name__, "message": str(error)}

    evidence_path = output / "evidence.json"
    with evidence_path.open("x", encoding="utf-8") as handle:
        json.dump(evidence, handle, indent=2, sort_keys=True)
        handle.write("\n")
    print(
        json.dumps(
            {
                "status": evidence["status"],
                "error": evidence.get("error"),
                "evidence_sha256": sha(evidence_path),
            }
        )
    )
    return 0 if evidence["status"] == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
