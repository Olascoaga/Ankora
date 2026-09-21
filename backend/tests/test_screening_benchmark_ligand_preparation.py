"""Synthetic contracts for restartable loss-preserving ligand preparation."""

from __future__ import annotations

import hashlib
import io
import json
import tarfile
from pathlib import Path
from typing import Any

import pytest

from ankora_backend.validation.screening_benchmark_ligand_plan import (
    build_ligand_preparation_plan,
    serialize_ligand_preparation_plan,
)
from ankora_backend.validation.screening_benchmark_ligand_preparation import (
    ScreeningBenchmarkLigandPreparationError,
    run_screening_benchmark_ligand_preparation,
    verify_ligand_preparation_manifest,
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


def _write_archive(path: Path, files: dict[str, bytes]) -> None:
    with tarfile.open(path, mode="w:gz") as archive:
        for name, content in files.items():
            info = tarfile.TarInfo(name=name)
            info.size = len(content)
            archive.addfile(info, io.BytesIO(content))


def _fixture(
    tmp_path: Path,
    *,
    rows: tuple[bytes, bytes, bytes, bytes] = (
        b"CCO active-1\n",
        b"CCN active-2\n",
        b"CCC inactive-1\n",
        b"CCCl inactive-2\n",
    ),
) -> tuple[Path, Path, Path]:
    root = "LIT-PCBA_SYNTHETIC/SYNTH"
    filenames = ("active_T.smi", "active_V.smi", "inactive_T.smi", "inactive_V.smi")
    files = {f"{root}/{name}": content for name, content in zip(filenames, rows, strict=True)}
    archive = tmp_path / "synthetic.tar.gz"
    _write_archive(archive, files)
    active_rows = sum(bool(line.strip()) for content in rows[:2] for line in content.splitlines())
    inactive_rows = sum(bool(line.strip()) for content in rows[2:] for line in content.splitlines())
    inputs: dict[str, object] = {
        "schema_version": 1,
        "protocol_id": "SYNTHETIC_LIGAND_PREPARATION_V1",
        "source": {
            "filename": archive.name,
            "size_bytes": archive.stat().st_size,
            "sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
        },
        "targets": [
            {
                "target_id": "SYNTH",
                "source_directory": "SYNTH",
                "source_census": {
                    "active_rows": active_rows,
                    "inactive_rows": inactive_rows,
                },
                "members": [
                    {
                        "path": name,
                        "size_bytes": len(content),
                        "sha256": hashlib.sha256(content).hexdigest(),
                    }
                    for name, content in files.items()
                ],
            }
        ],
        "totals": {
            "target_count": 1,
            "evaluation_active_units": active_rows,
            "evaluation_inactive_units": inactive_rows,
        },
    }
    inputs["manifest_sha256"] = _digest(inputs)
    inputs_path = tmp_path / "inputs.json"
    inputs_path.write_text(json.dumps(inputs), encoding="utf-8")
    plan = build_ligand_preparation_plan(
        archive=archive,
        input_manifest_path=inputs_path,
    )
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(serialize_ligand_preparation_plan(plan), encoding="utf-8")
    return archive, inputs_path, plan_path


def _evidence(path: Path, output_root: Path, stage: str) -> dict[str, object]:
    return {
        "stage": stage,
        "path": path.relative_to(output_root).as_posix(),
        "size_bytes": path.stat().st_size,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


def _successful_executor(
    task: dict[str, Any], _store: object, output_root: Path, _workers: int
) -> dict[str, Any]:
    root = output_root / "synthetic-artifacts" / f"{int(task['sequence']):05d}"
    root.mkdir(parents=True)
    conformer = root / "conformer.sdf"
    pdbqt = root / "ligand.pdbqt"
    conformer.write_text("SYNTHETIC CONFORMER\n", encoding="utf-8")
    pdbqt.write_text("SYNTHETIC PDBQT\n", encoding="utf-8")
    return {
        "status": "prepared",
        "prepared": True,
        "conformer": {
            "conformer_id": f"conformer-{task['sequence']}",
            "converged": True,
        },
        "pdbqt": {
            "preparation_id": f"preparation-{task['sequence']}",
            "tool_name": "Synthetic Meeko",
            "tool_version": "0.7.1",
        },
        "error": None,
        "artifacts": [
            _evidence(conformer, output_root, "conformer_sdf"),
            _evidence(pdbqt, output_root, "ligand_pdbqt"),
        ],
    }


def test_all_parents_become_path_free_terminal_rows_and_resume_is_a_noop(
    tmp_path: Path,
) -> None:
    archive, inputs, plan = _fixture(tmp_path)
    output = tmp_path / "evidence"
    public = tmp_path / "public.json"
    calls: list[int] = []

    def executor(
        task: dict[str, Any], store: object, output_root: Path, workers: int
    ) -> dict[str, Any]:
        calls.append(int(task["sequence"]))
        return _successful_executor(task, store, output_root, workers)

    manifest = run_screening_benchmark_ligand_preparation(
        archive=archive,
        input_manifest_path=inputs,
        plan_manifest_path=plan,
        output_root=output,
        public_manifest_path=public,
        worker_limit=2,
        _task_executor=executor,
    )

    assert manifest["preparation_census"] == {
        "requested": 4,
        "terminal": 4,
        "prepared": 4,
        "unscored_worst_tie": 0,
        "by_status": {"prepared": 4},
    }
    assert sorted(calls) == [1, 2, 3, 4]
    serialized = public.read_text(encoding="utf-8")
    assert "CCO" not in serialized
    assert str(tmp_path) not in serialized
    assert (
        verify_ligand_preparation_manifest(
            public,
            evidence_root=output,
            plan_manifest_path=plan,
        )
        == manifest
    )

    resumed = run_screening_benchmark_ligand_preparation(
        archive=archive,
        input_manifest_path=inputs,
        plan_manifest_path=plan,
        output_root=output,
        public_manifest_path=public,
        worker_limit=2,
        _task_executor=executor,
    )
    assert resumed == manifest
    assert sorted(calls) == [1, 2, 3, 4]


def test_ambiguous_states_are_retained_without_calling_preparation(
    tmp_path: Path,
) -> None:
    archive, inputs, plan = _fixture(
        tmp_path,
        rows=(
            b"CC(F)Cl undefined-stereo\n",
            b"CCO.[Na+] multicomponent\n",
            b"CCC eligible-1\n",
            b"CCN eligible-2\n",
        ),
    )
    output = tmp_path / "evidence"
    public = tmp_path / "public.json"
    calls: list[int] = []

    def executor(
        task: dict[str, Any], store: object, output_root: Path, workers: int
    ) -> dict[str, Any]:
        calls.append(int(task["sequence"]))
        return _successful_executor(task, store, output_root, workers)

    manifest = run_screening_benchmark_ligand_preparation(
        archive=archive,
        input_manifest_path=inputs,
        plan_manifest_path=plan,
        output_root=output,
        public_manifest_path=public,
        worker_limit=2,
        _task_executor=executor,
    )

    assert sorted(calls) == [3, 4]
    assert manifest["preparation_census"] == {
        "requested": 4,
        "terminal": 4,
        "prepared": 2,
        "unscored_worst_tie": 2,
        "by_status": {"prepared": 2, "unresolved_chemical_state": 2},
    }
    assert manifest["entries"][0]["error"]["code"] == ("STEREOCHEMISTRY_REQUIRES_DECISION")
    assert manifest["entries"][1]["error"]["code"] == ("MULTICOMPONENT_STATE_REQUIRES_DECISION")


def test_interrupted_parent_uses_a_new_attempt_without_deleting_the_first(
    tmp_path: Path,
) -> None:
    archive, inputs, plan = _fixture(
        tmp_path,
        rows=(b"CCO only-parent\n", b"", b"", b""),
    )
    output = tmp_path / "evidence"
    public = tmp_path / "public.json"

    def interrupt(
        _task: dict[str, Any], _store: object, _output: Path, _workers: int
    ) -> dict[str, Any]:
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        run_screening_benchmark_ligand_preparation(
            archive=archive,
            input_manifest_path=inputs,
            plan_manifest_path=plan,
            output_root=output,
            public_manifest_path=public,
            worker_limit=1,
            _task_executor=interrupt,
        )

    first = output / "entries" / "00001" / "attempt-001"
    assert (first / "started.json").is_file()
    assert not (first / "terminal.json").exists()
    assert not public.exists()

    run_screening_benchmark_ligand_preparation(
        archive=archive,
        input_manifest_path=inputs,
        plan_manifest_path=plan,
        output_root=output,
        public_manifest_path=public,
        worker_limit=1,
        _task_executor=_successful_executor,
    )
    assert (first / "started.json").is_file()
    assert (output / "entries" / "00001" / "attempt-002" / "terminal.json").is_file()


def test_verifier_rejects_changed_artifact_and_unsafe_path(tmp_path: Path) -> None:
    archive, inputs, plan = _fixture(
        tmp_path,
        rows=(b"CCO only-parent\n", b"", b"", b""),
    )
    output = tmp_path / "evidence"
    public = tmp_path / "public.json"
    manifest = run_screening_benchmark_ligand_preparation(
        archive=archive,
        input_manifest_path=inputs,
        plan_manifest_path=plan,
        output_root=output,
        public_manifest_path=public,
        _task_executor=_successful_executor,
    )
    artifact = manifest["entries"][0]["artifacts"][0]
    (output / artifact["path"]).write_text("CHANGED\n", encoding="utf-8")
    with pytest.raises(ScreeningBenchmarkLigandPreparationError, match="(size|SHA-256) changed"):
        verify_ligand_preparation_manifest(public, evidence_root=output)

    raw = json.loads(public.read_text(encoding="utf-8"))
    raw["entries"][0]["terminal_evidence"]["path"] = "//server/share/terminal.json"
    raw.pop("manifest_sha256")
    raw["manifest_sha256"] = _digest(raw)
    public.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(ScreeningBenchmarkLigandPreparationError, match="unsafe path"):
        verify_ligand_preparation_manifest(public)
