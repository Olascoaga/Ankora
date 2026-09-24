"""Synthetic contracts for restartable, loss-preserving Vina execution."""

from __future__ import annotations

import hashlib
import json
import threading
from pathlib import Path
from typing import Any

import pytest

from ankora_backend.adapters.engines.vina import (
    VinaInstallation,
    build_vina_arguments,
)
from ankora_backend.execution.cancellable_subprocess import CancellableToolExecution
from ankora_backend.schemas.binding_sites import BindingBox
from ankora_backend.schemas.docking import VinaDockingParameters, VinaSamplingProtocol
from ankora_backend.validation import screening_benchmark_vina_execution
from ankora_backend.validation.screening_benchmark_vina_execution import (
    ScreeningBenchmarkVinaExecutionError,
    run_screening_benchmark_vina_campaign,
    verify_vina_campaign_manifest,
)


def _digest(value: dict[str, object]) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _identity(path: Path, root: Path) -> dict[str, object]:
    return {
        "path": path.relative_to(root).as_posix(),
        "size_bytes": path.stat().st_size,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


def _entry(sequence: int, ligand: dict[str, object] | None) -> dict[str, object]:
    common: dict[str, object] = {
        "sequence": sequence,
        "target_sequence": sequence,
        "class_label": "active" if sequence == 1 else "inactive",
        "class_index": 1 if sequence < 3 else 2,
        "source_member_path": f"source/{sequence}.smi",
        "source_line_number": sequence,
        "source_identifier": f"compound-{sequence}",
        "source_smiles_sha256": f"{sequence}" * 64,
        "canonical_isomeric_smiles_sha256": f"{sequence + 3}" * 64,
        "preparation_status": "prepared" if ligand is not None else "preparation_failed",
    }
    if ligand is not None:
        return {**common, "docking_disposition": "ready", "ligand_pdbqt": ligand}
    return {
        **common,
        "docking_disposition": "retained_unscored_worst_tie",
        "preparation_failure": {
            "status": "preparation_failed",
            "code": "SYNTHETIC_PREPARATION_FAILURE",
            "stage": "ligand_conformer_generation",
        },
    }


def _fixture(tmp_path: Path) -> dict[str, Any]:
    receptor_root = tmp_path / "receptors"
    ligand_root = tmp_path / "ligands"
    receptor = receptor_root / "target" / "receptor.pdbqt"
    ligand_1 = ligand_root / "target" / "ligand-1.pdbqt"
    ligand_2 = ligand_root / "target" / "ligand-2.pdbqt"
    receptor.parent.mkdir(parents=True)
    ligand_1.parent.mkdir(parents=True)
    receptor.write_bytes(b"SYNTHETIC RECEPTOR\n")
    ligand_1.write_bytes(b"SYNTHETIC LIGAND 1\n")
    ligand_2.write_bytes(b"SYNTHETIC LIGAND 2\n")
    executable = tmp_path / "vina_1.2.7_win.exe"
    parser_source = tmp_path / "vina.py"
    executable.write_bytes(b"SYNTHETIC VINA 1.2.7\n")
    parser_source.write_text("# strict synthetic parser identity\n", encoding="utf-8")
    installation = VinaInstallation(executable=str(executable), version="1.2.7")
    box = BindingBox(
        center_x=1,
        center_y=2,
        center_z=3,
        size_x=10,
        size_y=11,
        size_z=12,
    )
    parameters = VinaDockingParameters(
        sampling_protocol=VinaSamplingProtocol.SCREENING,
        cpu_threads=1,
        seed=20260911,
        exhaustiveness=8,
        num_modes=9,
        min_rmsd_angstrom=1.0,
        energy_range_kcal_mol=3.0,
        timeout_minutes=360,
    )
    argument_template = build_vina_arguments(
        receptor_path=Path("<target_receptor_pdbqt>"),
        ligand_path=Path("<entry_ligand_pdbqt>"),
        output_path=Path("<entry_output_pdbqt>"),
        box=box,
        parameters=parameters,
    )
    entries = [
        _entry(1, _identity(ligand_1, ligand_root)),
        _entry(2, _identity(ligand_2, ligand_root)),
        _entry(3, None),
    ]
    plan: dict[str, Any] = {
        "schema_version": 1,
        "protocol_id": "SYNTHETIC_VINA_EXECUTION_V1",
        "scores_seen": False,
        "dependencies": {
            "primary_run_sha256": "a" * 64,
            "geometry_manifest_sha256": "b" * 64,
            "final_receptor_manifest_sha256": "c" * 64,
            "ligand_preparation_manifest_sha256": "d" * 64,
            "vina_parser": {
                "repository_path": (
                    "backend/src/ankora_backend/adapters/engines/vina.py"
                ),
                "size_bytes": parser_source.stat().st_size,
                "sha256": hashlib.sha256(parser_source.read_bytes()).hexdigest(),
            },
        },
        "engine": {
            "name": "AutoDock Vina",
            "version": "1.2.7",
            "executable_filename": executable.name,
            "executable_size_bytes": executable.stat().st_size,
            "executable_sha256": hashlib.sha256(executable.read_bytes()).hexdigest(),
            "score_field": "affinity_kcal_mol",
            "score_direction": "lower_is_better",
        },
        "parameters": {
            "sampling_protocol": "screening",
            "total_cpu_threads": 2,
            "parallel_ligands": 2,
            "seed": 20260911,
            "exhaustiveness": 8,
            "num_modes": 9,
            "min_rmsd_angstrom": 1.0,
            "energy_range_kcal_mol": 3.0,
            "timeout_minutes_per_ligand": 360,
            "threads_per_ligand": 1,
        },
        "execution_policy": {
            "target_campaign_count": 1,
            "all_source_parents_retained": True,
            "failures_retained_as_unscored_worst_tie": True,
            "restartable_create_only_entry_attempts": True,
            "terminal_entries_persisted_incrementally": True,
            "raw_outputs_preserved": True,
            "stdout_not_used_for_scoring": True,
            "docking_executed": False,
            "scores_or_metrics_computed": False,
        },
        "parser_contract": {
            "pose_container": "sequential MODEL/ENDMDL records starting at one",
            "score_source": "one REMARK VINA RESULT record inside each MODEL",
            "content_outside_models": "forbidden_except_whitespace",
            "raw_output_bytes_retained": True,
        },
        "targets": [
            {
                "campaign_sequence": 1,
                "target_id": "SYNTH",
                "primary_template_id": "1abc",
                "receptor": {
                    "final_receptor_id": "receptor-1",
                    "pdb_id": "1abc",
                    "pdbqt": _identity(receptor, receptor_root),
                },
                "box_angstrom": box.model_dump(),
                "argument_template": argument_template,
                "census": {
                    "source_parents": 3,
                    "prepared_for_docking": 2,
                    "retained_unscored_worst_tie": 1,
                    "by_class": {"active": 1, "inactive": 2},
                    "by_preparation_status": {
                        "preparation_failed": 1,
                        "prepared": 2,
                    },
                },
                "entries": entries,
            }
        ],
        "totals": {
            "target_count": 1,
            "source_parents": 3,
            "prepared_for_docking": 2,
            "retained_unscored_worst_tie": 1,
            "by_class": {"active": 1, "inactive": 2},
            "by_preparation_status": {
                "preparation_failed": 1,
                "prepared": 2,
            },
        },
        "result_status": (
            "primary_vina_campaign_plan_frozen_no_docking_score_or_metric_executed"
        ),
    }
    plan["manifest_sha256"] = _digest(plan)
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(json.dumps(plan), encoding="utf-8")
    return {
        "plan": plan_path,
        "receptor_root": receptor_root,
        "ligand_root": ligand_root,
        "parser": parser_source,
        "installation": installation,
    }


def _pose_output(score: float = -7.5) -> bytes:
    return (
        "MODEL 1\n"
        f"REMARK VINA RESULT: {score:.3f} 0.000 0.000\n"
        "ATOM      1  C   LIG A   1       0.000   0.000   0.000\n"
        "ENDMDL\n"
        "MODEL 2\n"
        f"REMARK VINA RESULT: {score + 0.4:.3f} 1.000 1.500\n"
        "ATOM      1  C   LIG A   1       1.000   0.000   0.000\n"
        "ENDMDL\n"
    ).encode()


def _successful_executor(
    installation: VinaInstallation,
    receptor_path: Path,
    ligand_path: Path,
    output_path: Path,
    box: BindingBox,
    parameters: VinaDockingParameters,
    _cancel_event: threading.Event,
) -> CancellableToolExecution:
    output_path.write_bytes(_pose_output())
    arguments = build_vina_arguments(
        receptor_path=receptor_path,
        ligand_path=ligand_path,
        output_path=output_path,
        box=box,
        parameters=parameters,
    )
    return CancellableToolExecution(
        command=[installation.executable, *arguments],
        exit_code=0,
        stdout="synthetic stdout\n",
        stderr="",
        canceled=False,
        timed_out=False,
    )


def _run(
    fixture: dict[str, Any],
    output: Path,
    public: Path,
    executor: Any,
) -> dict[str, Any]:
    return run_screening_benchmark_vina_campaign(
        plan_manifest_path=fixture["plan"],
        final_receptor_evidence_root=fixture["receptor_root"],
        ligand_preparation_evidence_root=fixture["ligand_root"],
        parser_source_path=fixture["parser"],
        installation=fixture["installation"],
        output_root=output,
        public_manifest_path=public,
        _entry_executor=executor,
    )


def test_campaign_is_incremental_loss_preserving_and_resume_is_a_noop(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path)
    output = tmp_path / "evidence"
    public = tmp_path / "public.json"
    calls: list[tuple[Path, Path, bytes]] = []

    def executor(*args: Any) -> CancellableToolExecution:
        calls.append((Path(args[1]), Path(args[2]), Path(args[2]).read_bytes()))
        return _successful_executor(*args)

    manifest = _run(fixture, output, public, executor)

    assert manifest["campaign_census"] == {
        "requested": 3,
        "terminal": 3,
        "scored": 2,
        "unscored_worst_tie": 1,
        "by_status": {"completed": 2, "preparation_unscored": 1},
    }
    assert sorted(call[2] for call in calls) == [
        b"SYNTHETIC LIGAND 1\n",
        b"SYNTHETIC LIGAND 2\n",
    ]
    assert all(output.resolve() in call[0].resolve().parents for call in calls)
    assert all(output.resolve() in call[1].resolve().parents for call in calls)
    assert all(call[0].name.endswith(".pdbqt") for call in calls)
    assert all(call[1].name == "ligand.pdbqt" for call in calls)
    assert manifest["entries"][0]["best_affinity_kcal_mol"] == -7.5
    assert manifest["entries"][2]["status"] == "preparation_unscored"
    assert str(tmp_path) not in public.read_text(encoding="utf-8")
    assert verify_vina_campaign_manifest(
        public,
        evidence_root=output,
        plan_manifest_path=fixture["plan"],
    ) == manifest

    assert _run(fixture, output, public, executor) == manifest
    assert len(calls) == 2


def test_one_ligand_failure_does_not_abort_its_neighbors(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    output = tmp_path / "evidence"
    public = tmp_path / "public.json"

    def executor(
        installation: VinaInstallation,
        receptor_path: Path,
        ligand_path: Path,
        output_path: Path,
        box: BindingBox,
        parameters: VinaDockingParameters,
        cancel_event: threading.Event,
    ) -> CancellableToolExecution:
        if ligand_path.read_bytes() == b"SYNTHETIC LIGAND 2\n":
            arguments = build_vina_arguments(
                receptor_path=receptor_path,
                ligand_path=ligand_path,
                output_path=output_path,
                box=box,
                parameters=parameters,
            )
            return CancellableToolExecution(
                command=[installation.executable, *arguments],
                exit_code=1,
                stdout="",
                stderr="synthetic failure\n",
                canceled=False,
                timed_out=False,
            )
        return _successful_executor(
            installation,
            receptor_path,
            ligand_path,
            output_path,
            box,
            parameters,
            cancel_event,
        )

    manifest = _run(fixture, output, public, executor)

    assert manifest["campaign_census"]["by_status"] == {
        "completed": 1,
        "docking_failed": 1,
        "preparation_unscored": 1,
    }
    assert manifest["campaign_census"]["unscored_worst_tie"] == 2
    assert manifest["entries"][1]["error"]["code"] == "VINA_EXECUTION_FAILED"


def test_campaign_refuses_an_external_tool_path_over_the_windows_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _fixture(tmp_path)
    output = tmp_path / "evidence"
    public = tmp_path / "public.json"
    calls = 0

    def executor(*args: Any) -> CancellableToolExecution:
        nonlocal calls
        calls += 1
        return _successful_executor(*args)

    monkeypatch.setattr(
        screening_benchmark_vina_execution,
        "WINDOWS_EXTERNAL_TOOL_PATH_LIMIT",
        1,
    )
    with pytest.raises(
        ScreeningBenchmarkVinaExecutionError,
        match="run root is too deep",
    ):
        _run(fixture, output, public, executor)

    assert calls == 0
    assert not (output / "entries").exists()
    assert not public.exists()


def test_malformed_pose_output_is_retained_unscored(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    output = tmp_path / "evidence"
    public = tmp_path / "public.json"

    def executor(
        installation: VinaInstallation,
        receptor_path: Path,
        ligand_path: Path,
        output_path: Path,
        box: BindingBox,
        parameters: VinaDockingParameters,
        _cancel_event: threading.Event,
    ) -> CancellableToolExecution:
        output_path.write_text("MODEL 1\nENDMDL\n", encoding="utf-8")
        arguments = build_vina_arguments(
            receptor_path=receptor_path,
            ligand_path=ligand_path,
            output_path=output_path,
            box=box,
            parameters=parameters,
        )
        return CancellableToolExecution(
            command=[installation.executable, *arguments],
            exit_code=0,
            stdout="",
            stderr="",
            canceled=False,
            timed_out=False,
        )

    manifest = _run(fixture, output, public, executor)

    assert manifest["campaign_census"]["by_status"] == {
        "output_invalid": 2,
        "preparation_unscored": 1,
    }
    assert manifest["campaign_census"]["scored"] == 0
    assert manifest["scores_seen"] is False
    assert all(
        entry["error"]["code"] == "VINA_OUTPUT_INVALID"
        for entry in manifest["entries"][:2]
    )


def test_interrupted_entry_uses_a_new_attempt_and_preserves_the_first(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path)
    output = tmp_path / "evidence"
    public = tmp_path / "public.json"

    def interrupt(*_args: Any) -> CancellableToolExecution:
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        _run(fixture, output, public, interrupt)

    first = output / "entries" / "00001" / "attempt-001"
    assert (first / "started.json").is_file()
    assert (first / "interrupted.json").is_file()
    assert not (first / "terminal.json").exists()
    assert not public.exists()

    manifest = _run(fixture, output, public, _successful_executor)
    assert manifest["campaign_census"]["terminal"] == 3
    assert (output / "entries" / "00001" / "attempt-002" / "terminal.json").is_file()


def test_verifier_rejects_changed_artifact_and_unsafe_path(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    output = tmp_path / "evidence"
    public = tmp_path / "public.json"
    manifest = _run(fixture, output, public, _successful_executor)
    artifact = manifest["entries"][0]["artifacts"][0]
    (output / artifact["path"]).write_text("CHANGED\n", encoding="utf-8")
    with pytest.raises(ScreeningBenchmarkVinaExecutionError, match="evidence changed"):
        verify_vina_campaign_manifest(public, evidence_root=output)

    raw = json.loads(public.read_text(encoding="utf-8"))
    raw["entries"][0]["terminal_evidence"]["path"] = "//server/share/terminal.json"
    raw.pop("manifest_sha256")
    raw["manifest_sha256"] = _digest(raw)
    public.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(ScreeningBenchmarkVinaExecutionError, match="unsafe path"):
        verify_vina_campaign_manifest(public)
