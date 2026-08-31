"""Synthetic contract tests for the read-only validation evidence freezer."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from ankora_backend.services.validation_evidence import (
    EvidenceFieldSpec,
    ValidationCaseSpec,
    ValidationEvidenceError,
    freeze_validation_evidence,
    render_validation_matrix,
    serialize_validation_manifest,
)


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _case(tmp_path: Path) -> tuple[ValidationCaseSpec, Path, Path]:
    data_root = tmp_path / "synthetic-data"
    artifact_path = data_root / "records" / "result" / "pose.pdbqt"
    artifact_path.parent.mkdir(parents=True)
    artifact = b"REMARK SYNTHETIC VALIDATION POSE\nEND\n"
    artifact_path.write_bytes(artifact)
    record_path = artifact_path.parent / "record.json"
    record = {
        "validation_id": "synthetic-validation-1",
        "engine": {"name": "SyntheticDock", "version": "0.0"},
        "metrics": {"sampling_success": True, "top1_rmsd_angstrom": 1.25},
        "artifact": {
            "sha256": _sha256(artifact),
            "size_bytes": len(artifact),
        },
    }
    record_path.write_text(json.dumps(record), encoding="utf-8", newline="\n")
    spec = ValidationCaseSpec.model_validate(
        {
            "schema_version": 1,
            "case_id": "SYNTHETIC_CASE",
            "title": "Synthetic evidence fixture",
            "frozen_on": "2026-08-28",
            "scope": "Synthetic records only; no scientific result is asserted.",
            "records": [
                {
                    "role": "synthetic_pose",
                    "label": "Clearly synthetic pose",
                    "path": "records/result/record.json",
                    "identity_pointer": "/validation_id",
                    "identity_value": "synthetic-validation-1",
                    "fields": [
                        {"label": "Engine", "pointer": "/engine/name"},
                        {
                            "label": "Sampling success",
                            "pointer": "/metrics/sampling_success",
                        },
                        {
                            "label": "Metric count",
                            "pointer": "/metrics",
                            "operation": "length",
                        },
                    ],
                    "artifacts": [
                        {
                            "label": "Synthetic pose bytes",
                            "path": "records/result/pose.pdbqt",
                            "sha256_pointer": "/artifact/sha256",
                            "size_bytes_pointer": "/artifact/size_bytes",
                        }
                    ],
                }
            ],
            "interpretations": ["This is a synthetic contract fixture."],
            "gaps": ["It is not scientific evidence."],
        }
    )
    return spec, data_root, record_path


def test_freeze_is_deterministic_and_does_not_mutate_sources(tmp_path: Path) -> None:
    spec, data_root, record_path = _case(tmp_path)
    before = {path: path.read_bytes() for path in data_root.rglob("*") if path.is_file()}

    first = freeze_validation_evidence(spec, data_root=data_root)
    second = freeze_validation_evidence(spec, data_root=data_root)

    assert serialize_validation_manifest(first) == serialize_validation_manifest(second)
    assert first["records"][0]["fields"] == {
        "Engine": "SyntheticDock",
        "Sampling success": True,
        "Metric count": 2,
    }
    assert first["records"][0]["record_sha256"] == _sha256(record_path.read_bytes())
    assert first["record_count"] == 1
    assert first["artifact_count"] == 1
    assert "Synthetic pose bytes" in render_validation_matrix(first)
    after = {path: path.read_bytes() for path in data_root.rglob("*") if path.is_file()}
    assert after == before


def test_freeze_redacts_absolute_paths_but_hashes_original_record(tmp_path: Path) -> None:
    spec, data_root, record_path = _case(tmp_path)
    record = json.loads(record_path.read_text(encoding="utf-8"))
    windows_root = "C:" + "\\Users\\researcher\\Documents\\Ankora"
    record["execution"] = {
        "command": [
            windows_root + "\\.ankora-data\\pose.pdbqt",
            "C:" + "\\Users\\researcher\\tools\\vina.exe",
        ],
        "stdout": "Ligand: " + windows_root + "\\.ankora-data\\pose.pdbqt",
    }
    record_path.write_text(json.dumps(record), encoding="utf-8", newline="\n")
    spec.records[0].fields += (
        EvidenceFieldSpec(label="Execution", pointer="/execution"),
    )

    manifest = freeze_validation_evidence(spec, data_root=data_root)
    serialized = serialize_validation_manifest(manifest)

    assert "researcher" not in serialized
    assert windows_root not in serialized
    assert "<ANKORA_DATA>" in serialized
    assert "<TOOLS_ROOT>\\\\vina.exe" in serialized
    assert manifest["records"][0]["record_sha256"] == _sha256(
        record_path.read_bytes()
    )


def test_identity_mismatch_is_rejected(tmp_path: Path) -> None:
    spec, data_root, _ = _case(tmp_path)
    spec.records[0].identity_value = "another-validation"

    with pytest.raises(ValidationEvidenceError, match="Identity mismatch"):
        freeze_validation_evidence(spec, data_root=data_root)


def test_artifact_hash_mismatch_is_rejected(tmp_path: Path) -> None:
    spec, data_root, _ = _case(tmp_path)
    (data_root / "records" / "result" / "pose.pdbqt").write_bytes(b"changed")

    with pytest.raises(ValidationEvidenceError, match="SHA-256 mismatch"):
        freeze_validation_evidence(spec, data_root=data_root)


def test_missing_evidence_is_rejected(tmp_path: Path) -> None:
    spec, data_root, _ = _case(tmp_path)
    (data_root / "records" / "result" / "pose.pdbqt").unlink()

    with pytest.raises(ValidationEvidenceError, match="unavailable"):
        freeze_validation_evidence(spec, data_root=data_root)


def test_path_traversal_is_rejected(tmp_path: Path) -> None:
    spec, data_root, _ = _case(tmp_path)
    spec.records[0].path = "../outside.json"

    with pytest.raises(ValidationEvidenceError, match="escapes the data root"):
        freeze_validation_evidence(spec, data_root=data_root)


def test_duplicate_roles_are_rejected(tmp_path: Path) -> None:
    spec, data_root, _ = _case(tmp_path)
    spec.records = (spec.records[0], spec.records[0].model_copy(deep=True))

    with pytest.raises(ValidationEvidenceError, match="Duplicate evidence role"):
        freeze_validation_evidence(spec, data_root=data_root)


def test_length_operation_rejects_a_scalar(tmp_path: Path) -> None:
    spec, data_root, _ = _case(tmp_path)
    spec.records[0].fields[1].operation = "length"

    with pytest.raises(ValidationEvidenceError, match="Cannot take the length"):
        freeze_validation_evidence(spec, data_root=data_root)
