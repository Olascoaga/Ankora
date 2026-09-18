"""Synthetic contracts for retained benchmark PROPKA preview evidence."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

import ankora_backend.validation.screening_benchmark_protonation_previews as previews
from ankora_backend.validation.screening_benchmark_protonation_previews import (
    ScreeningBenchmarkProtonationPreviewError,
    run_screening_benchmark_protonation_previews,
    verify_protonation_preview_manifest,
)


def _synthetic_plans() -> dict[str, object]:
    targets: list[dict[str, object]] = []
    for target_index in range(3):
        target: dict[str, object] = {"target_id": f"SYNTHETIC_{target_index + 1}"}
        for role, suffix in (("primary_template", "a"), ("alternate_template", "b")):
            target[role] = {
                "role": role.removesuffix("_template"),
                "pdb_id": f"{target_index + 1}{suffix}aa",
            }
        targets.append(target)
    return {
        "protocol_id": "SYNTHETIC_PROTONATION_PREVIEWS_V1",
        "manifest_sha256": "a" * 64,
        "targets": targets,
    }


def _synthetic_executor(
    task: dict[str, object], _structures: Path, output_root: Path
) -> dict[str, object]:
    sequence = int(task["sequence"])
    task_root = (
        output_root
        / f"{sequence:02d}-{task['target_id']}-{task['role']}-{task['pdb_id']}"
    )
    task_root.mkdir()
    raw = task_root / "synthetic-raw-evidence.txt"
    raw.write_text(f"synthetic preview {sequence}\n", encoding="utf-8")
    relative = raw.relative_to(output_root).as_posix()
    warnings = ["PKA_NEAR_TARGET_PH"] if sequence == 1 else []
    return {
        "sequence": sequence,
        "target_id": task["target_id"],
        "role": task["role"],
        "pdb_id": task["pdb_id"],
        "status": "completed",
        "proposal_count": 1,
        "review_attention_count": len(warnings),
        "review_attention_proposal_ids": (["A|HIS|1||HIS1"] if warnings else []),
        "proposals": [
            {
                "proposal_id": "A|HIS|1||HIS1",
                "warnings": warnings,
            }
        ],
        "raw_evidence_files": [
            {
                "path": relative,
                "size_bytes": raw.stat().st_size,
                "sha256": hashlib.sha256(raw.read_bytes()).hexdigest(),
            }
        ],
        "final_receptor_created": False,
        "final_pdbqt_created": False,
    }


def test_preview_run_is_parallel_create_only_and_path_free(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plans = _synthetic_plans()
    monkeypatch.setattr(
        previews,
        "verify_receptor_plan_manifest",
        lambda **_kwargs: plans,
    )
    output = tmp_path / "raw-preview-evidence"
    public_manifest = tmp_path / "public-preview-manifest.json"

    manifest = run_screening_benchmark_protonation_previews(
        archive=tmp_path / "synthetic.tar.gz",
        structure_manifest_path=tmp_path / "structures.json",
        receptor_plan_manifest_path=tmp_path / "plans.json",
        structures_dir=tmp_path / "structures",
        output_root=output,
        public_manifest_path=public_manifest,
        worker_limit=3,
        _task_executor=_synthetic_executor,
    )

    assert manifest["execution_policy"]["worker_count"] == 3
    assert manifest["preview_census"] == {
        "requested": 6,
        "completed": 6,
        "failed": 0,
        "proposal_count": 6,
        "review_attention_count": 1,
    }
    assert [item["sequence"] for item in manifest["previews"]] == list(range(1, 7))
    assert "scientist_review" in manifest
    assert manifest["scientist_review"]["status"] == "pending"
    assert str(tmp_path) not in public_manifest.read_text(encoding="utf-8")
    assert verify_protonation_preview_manifest(
        public_manifest, evidence_root=output
    ) == manifest

    with pytest.raises(
        ScreeningBenchmarkProtonationPreviewError, match="create-only"
    ):
        run_screening_benchmark_protonation_previews(
            archive=tmp_path / "synthetic.tar.gz",
            structure_manifest_path=tmp_path / "structures.json",
            receptor_plan_manifest_path=tmp_path / "plans.json",
            structures_dir=tmp_path / "structures",
            output_root=output,
            public_manifest_path=tmp_path / "another-manifest.json",
            _task_executor=_synthetic_executor,
        )


def test_preview_verifier_rejects_changed_raw_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        previews,
        "verify_receptor_plan_manifest",
        lambda **_kwargs: _synthetic_plans(),
    )
    output = tmp_path / "raw-preview-evidence"
    public_manifest = tmp_path / "public-preview-manifest.json"
    manifest = run_screening_benchmark_protonation_previews(
        archive=tmp_path / "synthetic.tar.gz",
        structure_manifest_path=tmp_path / "structures.json",
        receptor_plan_manifest_path=tmp_path / "plans.json",
        structures_dir=tmp_path / "structures",
        output_root=output,
        public_manifest_path=public_manifest,
        _task_executor=_synthetic_executor,
    )
    first_file = manifest["previews"][0]["raw_evidence_files"][0]["path"]
    (output / first_file).write_text("changed\n", encoding="utf-8")

    with pytest.raises(
        ScreeningBenchmarkProtonationPreviewError,
        match="(size|SHA-256) changed",
    ):
        verify_protonation_preview_manifest(public_manifest, evidence_root=output)


def test_review_attention_is_derived_only_from_structured_warning_codes() -> None:
    assert previews._attention_proposal_ids(
        [
            {"proposal_id": "review", "warnings": ["METAL_COORDINATION_REVIEW"]},
            {"proposal_id": "ordinary", "warnings": ["UNRELATED_INFORMATION"]},
        ]
    ) == ["review"]
