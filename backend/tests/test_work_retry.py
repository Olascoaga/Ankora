"""Interrupted work is retried only as a distinct, explicitly accepted attempt."""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from ankora_backend.domain.errors import AnkoraDomainError
from ankora_backend.schemas.work_recovery import WorkKind, WorkRetryRequest
from ankora_backend.services.work_retry import WorkRetryService


def _service():  # type: ignore[no-untyped-def]
    return WorkRetryService(
        docking_store=MagicMock(),
        autogrid_store=MagicMock(),
        autodock4_store=MagicMock(),
        autodock_gpu_store=MagicMock(),
        vina=MagicMock(),
        autogrid=MagicMock(),
        autodock4=MagicMock(),
        autodock_gpu=MagicMock(),
    )


@pytest.mark.parametrize(
    ("work_kind", "store_name", "load_name", "runner_name", "start_name", "id_name", "code"),
    [
        (
            WorkKind.VINA_JOB,
            "_docking_store",
            "load_record",
            "_vina",
            "start",
            "job_id",
            "VINA_EXECUTION_INTERRUPTED",
        ),
        (
            WorkKind.VINA_BATCH,
            "_docking_store",
            "load_batch_record",
            "_vina",
            "start_batch",
            "batch_id",
            "VINA_CAMPAIGN_INTERRUPTED",
        ),
        (
            WorkKind.AUTOGRID_JOB,
            "_autogrid_store",
            "load_job",
            "_autogrid",
            "start_map_set",
            "job_id",
            "AUTOGRID_EXECUTION_INTERRUPTED",
        ),
        (
            WorkKind.AUTODOCK4_JOB,
            "_autodock4_store",
            "load_job",
            "_autodock4",
            "start",
            "job_id",
            "AUTODOCK4_EXECUTION_INTERRUPTED",
        ),
        (
            WorkKind.AUTODOCK4_BATCH,
            "_autodock4_store",
            "load_batch",
            "_autodock4",
            "start_batch",
            "batch_id",
            "AUTODOCK4_CAMPAIGN_INTERRUPTED",
        ),
        (
            WorkKind.AUTODOCK_GPU_JOB,
            "_autodock_gpu_store",
            "load_job",
            "_autodock_gpu",
            "start",
            "job_id",
            "AUTODOCK_GPU_EXECUTION_INTERRUPTED",
        ),
        (
            WorkKind.AUTODOCK_GPU_BATCH,
            "_autodock_gpu_store",
            "load_batch",
            "_autodock_gpu",
            "start_batch",
            "batch_id",
            "AUTODOCK_GPU_CAMPAIGN_INTERRUPTED",
        ),
    ],
)
def test_retry_dispatches_the_exact_request_under_a_new_identity(
    work_kind,
    store_name,
    load_name,
    runner_name,
    start_name,
    id_name,
    code,
) -> None:  # type: ignore[no-untyped-def]
    service = _service()
    interrupted_id = str(uuid4())
    new_id = str(uuid4())
    recorded_request = object()
    previous = SimpleNamespace(
        failure=SimpleNamespace(code=code),
        request=recorded_request,
    )
    created_at = datetime.now(UTC)
    created = SimpleNamespace(
        **{
            id_name: new_id,
            "status": SimpleNamespace(value="queued"),
            "created_at": created_at,
        }
    )
    load = getattr(getattr(service, store_name), load_name)
    start = getattr(getattr(service, runner_name), start_name)
    load.return_value = previous
    start.return_value = created

    response = service.retry(
        work_kind,
        interrupted_id,
        WorkRetryRequest(acknowledge_new_immutable_attempt=True),
    )

    load.assert_called_once_with(interrupted_id)
    start.assert_called_once_with(recorded_request)
    assert response.interrupted_work_id == interrupted_id
    assert response.new_work_id == new_id
    assert response.new_work_id != response.interrupted_work_id
    assert response.status == "queued"
    assert response.created_at == created_at


def test_retry_requires_explicit_new_attempt_acknowledgement() -> None:
    service = _service()

    with pytest.raises(AnkoraDomainError) as raised:
        service.retry(WorkKind.VINA_JOB, str(uuid4()), WorkRetryRequest())

    assert raised.value.code == "WORK_RETRY_CONFIRMATION_REQUIRED"
    service._docking_store.load_record.assert_not_called()


def test_retry_rejects_an_ordinary_failure() -> None:
    service = _service()
    service._docking_store.load_record.return_value = SimpleNamespace(
        failure=SimpleNamespace(code="VINA_EXECUTION_FAILED"),
        request=object(),
    )

    with pytest.raises(AnkoraDomainError) as raised:
        service.retry(
            WorkKind.VINA_JOB,
            str(uuid4()),
            WorkRetryRequest(acknowledge_new_immutable_attempt=True),
        )

    assert raised.value.code == "WORK_NOT_INTERRUPTED"
    service._vina.start.assert_not_called()
