"""Derive repeat evidence from exact recorded executions.

No engine is declared reproducible (or variable) by type. Two or more
completed records must share one deterministic input fingerprint before their
scientific-output fingerprints are compared. The result is a read model: no
scientific executable runs and no source record is changed.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass
from hashlib import sha256
from typing import Any

from ankora_backend.domain.errors import AnkoraDomainError
from ankora_backend.schemas.results_catalog import (
    ReproducibilityAssessment,
    ReproducibilityExecution,
    ReproducibilityStatus,
)

_VINA_BATCH = "vina_batch"
_AUTODOCK4_BATCH = "autodock4_batch"
_AUTODOCK_GPU_BATCH = "autodock_gpu_batch"
_VINA_JOB = "vina_job"
_AUTODOCK4_JOB = "autodock4_job"
_AUTODOCK_GPU_JOB = "autodock_gpu_job"


@dataclass(frozen=True, slots=True)
class _Execution:
    catalog_id: str
    input_fingerprint_sha256: str
    output_fingerprint_sha256: str | None


class ReproducibilityService:
    def __init__(
        self,
        *,
        docking_store: Any,
        autodock4_store: Any,
        autodock_gpu_store: Any,
    ) -> None:
        self._docking = docking_store
        self._autodock4 = autodock4_store
        self._autodock_gpu = autodock_gpu_store

    def all_assessments(self) -> dict[str, ReproducibilityAssessment]:
        executions = list(self._executions())
        groups: dict[tuple[str, str], list[_Execution]] = {}
        for execution in executions:
            engine_key, _, _ = execution.catalog_id.partition(":")
            groups.setdefault(
                (engine_key, execution.input_fingerprint_sha256), []
            ).append(execution)
        return {
            execution.catalog_id: _assessment(
                execution,
                groups[(
                    execution.catalog_id.partition(":")[0],
                    execution.input_fingerprint_sha256,
                )],
            )
            for execution in executions
        }

    def assessment(self, catalog_id: str) -> ReproducibilityAssessment:
        return self.all_assessments().get(catalog_id, ReproducibilityAssessment())

    def _executions(self) -> Iterable[_Execution]:
        sources = (
            (_VINA_BATCH, self._docking, "list_batch_records"),
            (_AUTODOCK4_BATCH, self._autodock4, "list_batches"),
            (_AUTODOCK_GPU_BATCH, self._autodock_gpu, "list_batches"),
            (_VINA_JOB, self._docking, "list_jobs"),
            (_AUTODOCK4_JOB, self._autodock4, "list_jobs"),
            (_AUTODOCK_GPU_JOB, self._autodock_gpu, "list_jobs"),
        )
        for engine_key, store, loader_name in sources:
            try:
                records = list(getattr(store, loader_name)())
            except (AnkoraDomainError, AttributeError, OSError, TypeError, ValueError):
                continue
            for record in records:
                try:
                    yield _execution(engine_key, record)
                except (AttributeError, TypeError, ValueError):
                    # One historical or damaged record cannot create evidence,
                    # and must not hide the rest of the Results catalog.
                    continue


def _execution(engine_key: str, record: Any) -> _Execution:
    record_id = str(getattr(record, "batch_id", getattr(record, "job_id", "")))
    if not record_id:
        raise ValueError("A reproducibility execution must name its record.")
    return _Execution(
        catalog_id=f"{engine_key}:{record_id}",
        input_fingerprint_sha256=_digest(_input_payload(engine_key, record)),
        output_fingerprint_sha256=(
            _digest(_output_payload(engine_key, record))
            if _text(record.status) == "completed"
            else None
        ),
    )


def _input_payload(engine_key: str, record: Any) -> dict[str, Any]:
    request = record.request.model_dump(mode="json")
    request.pop("acknowledge_inputs_and_scoring", None)
    if engine_key in {_VINA_BATCH, _VINA_JOB}:
        payload = {
            "engine_key": engine_key,
            "tool": record.tool.model_dump(mode="json"),
            "request": request,
            "receptor_sha256": record.receptor_sha256,
        }
        if engine_key == _VINA_BATCH:
            payload["selection_manifest_sha256"] = record.selection_manifest_sha256
        else:
            payload["ligand_sha256"] = record.ligand_sha256
        return payload

    identity = (
        record.autodock4 if engine_key in {_AUTODOCK4_BATCH, _AUTODOCK4_JOB}
        else record.autodock_gpu
    )
    payload = {
        "engine_key": engine_key,
        "tool": identity.model_dump(mode="json"),
        "request": request,
        "map_set_identity_key": record.map_set_identity_key,
    }
    if engine_key in {_AUTODOCK4_BATCH, _AUTODOCK_GPU_BATCH}:
        payload["selection_manifest_sha256"] = record.selection_manifest_sha256
    else:
        payload["ligand_sha256"] = record.ligand_sha256
    return payload


def _output_payload(engine_key: str, record: Any) -> dict[str, Any]:
    if engine_key == _VINA_JOB:
        return {"poses": [_vina_pose(pose) for pose in record.poses]}
    if engine_key == _VINA_BATCH:
        return {
            "entries": [
                {
                    "ligand_id": entry.ligand_id,
                    "source_index": entry.source_index,
                    "status": _text(entry.status),
                    "failure": _failure(entry.failure),
                    "poses": [_vina_pose(pose) for pose in entry.poses],
                }
                for entry in record.entries
            ]
        }
    if engine_key in {_AUTODOCK4_JOB, _AUTODOCK_GPU_JOB}:
        return _autodock_result(record)
    return {
        "entries": [
            {
                "ligand_id": entry.ligand_id,
                "source_index": entry.source_index,
                "status": _text(entry.status),
                "failure": _failure(entry.failure),
                **_autodock_result(entry),
            }
            for entry in record.entries
        ]
    }


def _vina_pose(pose: Any) -> dict[str, Any]:
    return {
        "mode": pose.mode,
        "affinity_kcal_mol": pose.affinity_kcal_mol,
        "rmsd_lower_bound_angstrom": pose.rmsd_lower_bound_angstrom,
        "rmsd_upper_bound_angstrom": pose.rmsd_upper_bound_angstrom,
        "artifact_sha256": pose.artifact.sha256,
    }


def _autodock_result(result: Any) -> dict[str, Any]:
    return {
        "clusters": [cluster.model_dump(mode="json") for cluster in result.clusters],
        "runs": [
            {
                **run.model_dump(mode="json", exclude={"artifact"}),
                "artifact_sha256": run.artifact.sha256,
            }
            for run in result.runs
        ],
    }


def _failure(failure: Any) -> dict[str, Any] | None:
    if failure is None:
        return None
    # Failure details retain commands/log excerpts and may contain timing or
    # machine paths. The stable scientific outcome is that this selected row
    # failed under its recorded code; raw evidence remains in the source record.
    return {"code": str(failure.code)}


def _assessment(
    target: _Execution, group: list[_Execution]
) -> ReproducibilityAssessment:
    completed = sorted(
        (execution for execution in group if execution.output_fingerprint_sha256),
        key=lambda execution: execution.catalog_id,
    )
    evidence = [
        ReproducibilityExecution(
            catalog_id=execution.catalog_id,
            output_fingerprint_sha256=str(execution.output_fingerprint_sha256),
        )
        for execution in completed
    ]
    if target.output_fingerprint_sha256 is None or len(completed) < 2:
        return ReproducibilityAssessment(
            input_fingerprint_sha256=target.input_fingerprint_sha256,
            executions=evidence,
        )
    distinct = {execution.output_fingerprint_sha256 for execution in completed}
    return ReproducibilityAssessment(
        status=(
            ReproducibilityStatus.MEASURED_REPRODUCIBLE
            if len(distinct) == 1
            else ReproducibilityStatus.MEASURED_VARIABLE
        ),
        input_fingerprint_sha256=target.input_fingerprint_sha256,
        executions=evidence,
    )


def _digest(payload: dict[str, Any]) -> str:
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


def _text(value: Any) -> str:
    return str(getattr(value, "value", value))
