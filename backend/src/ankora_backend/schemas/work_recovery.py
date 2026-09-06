"""Durable ownership and startup-recovery evidence for long-running work."""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class WorkKind(StrEnum):
    VINA_JOB = "vina_job"
    VINA_BATCH = "vina_batch"
    AUTOGRID_JOB = "autogrid_job"
    AUTODOCK4_JOB = "autodock4_job"
    AUTODOCK4_BATCH = "autodock4_batch"
    AUTODOCK_GPU_JOB = "autodock_gpu_job"
    AUTODOCK_GPU_BATCH = "autodock_gpu_batch"


class WorkLeaseState(StrEnum):
    ACTIVE = "active"
    RELEASED = "released"
    RECONCILED = "reconciled"


class WorkLeaseRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lease_id: str = Field(min_length=1)
    work_kind: WorkKind
    work_id: str = Field(min_length=1)
    owner_instance_id: str = Field(min_length=1)
    acquired_at: datetime
    heartbeat_at: datetime
    state: WorkLeaseState = WorkLeaseState.ACTIVE
    released_at: datetime | None = None


class RecoveredWorkItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    work_kind: WorkKind
    work_id: str = Field(min_length=1)
    previous_status: str = Field(min_length=1)
    interrupted_entry_count: int = Field(default=0, ge=0)
    completed_entry_count: int = Field(default=0, ge=0)
    last_heartbeat_at: datetime | None = None
    previous_owner_instance_id: str | None = None


class WorkRecoverySummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reconciled_at: datetime
    items: list[RecoveredWorkItem] = Field(default_factory=list)


class WorkRetryRequest(BaseModel):
    """Explicit consent to create a fresh attempt from an interrupted request."""

    model_config = ConfigDict(extra="forbid")

    acknowledge_new_immutable_attempt: bool = False


class WorkRetryResponse(BaseModel):
    """Identity bridge between the preserved interruption and its new attempt."""

    model_config = ConfigDict(extra="forbid")

    work_kind: WorkKind
    interrupted_work_id: str = Field(min_length=1)
    new_work_id: str = Field(min_length=1)
    status: str = Field(min_length=1)
    created_at: datetime
