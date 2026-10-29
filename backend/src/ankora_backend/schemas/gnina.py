"""Explicit GNINA 1.3.3 settings; independent of Vina and AutoDock4 scores."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ankora_backend.schemas.binding_sites import BindingBox
from ankora_backend.schemas.docking import DockingFailure, DockingJobPhase, DockingJobStatus


class GninaDockingParameters(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Choice is explicit: discovering a GPU does not authorize silent fallback.
    compute: Literal["cpu", "cuda"]
    device_index: int = Field(default=0, ge=0, le=63)
    cpu_threads: int = Field(default=2, ge=1, le=256)
    seed: int = Field(default=20261029, ge=1, le=2_147_483_647)
    exhaustiveness: int = Field(default=8, ge=1, le=128)
    num_modes: int = Field(default=9, ge=1, le=100)
    min_rmsd_filter_angstrom: float = Field(default=1.0, ge=0, le=20, allow_inf_nan=False)
    timeout_minutes: int = Field(default=360, ge=1, le=2880)
    cnn_scoring: Literal["rescore"] = "rescore"
    cnn_model: Literal["dense_1_3"] = "dense_1_3"
    hydrogen_handling: Literal["prepared_pdbqt_no_add_no_strip"] = "prepared_pdbqt_no_add_no_strip"
    pose_sort_order: Literal["cnn_score_descending"] = "cnn_score_descending"


class GninaDockingRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    receptor_id: str = Field(min_length=1)
    binding_site_id: str = Field(min_length=1)
    ligand_id: str = Field(min_length=1)
    ligand_preparation_id: str = Field(min_length=1)
    parameters: GninaDockingParameters
    acknowledge_inputs_and_scoring: bool = False

    @model_validator(mode="after")
    def require_explicit_acknowledgement(self) -> "GninaDockingRequest":
        if not self.acknowledge_inputs_and_scoring:
            raise ValueError("acknowledge_inputs_and_scoring must be true before docking")
        return self


class GninaToolIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    architecture: Literal["x86_64"]


class GninaPoseArtifact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_id: str = Field(min_length=1)
    mode: int = Field(ge=1)
    filename: str = Field(pattern=r"^pose_[1-9][0-9]*\.pdbqt$")
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size_bytes: int = Field(ge=1)


class GninaPoseResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: int = Field(ge=1)
    minimized_affinity_kcal_mol: float = Field(allow_inf_nan=False)
    cnn_score: float = Field(ge=0, le=1, allow_inf_nan=False)
    cnn_affinity: float = Field(allow_inf_nan=False)
    artifact: GninaPoseArtifact


class GninaExecutionEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    command: list[str] = Field(min_length=1)
    exit_code: int
    stdout: str
    stderr: str
    timed_out: bool = False
    canceled: bool = False
    gpu_process_observed: bool = False
    gpu_observation: str | None = None


class GninaJobRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: str = Field(min_length=1)
    engine: Literal["gnina"] = "gnina"
    status: DockingJobStatus
    phase: DockingJobPhase
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    request: GninaDockingRequest
    tool: GninaToolIdentity
    box: BindingBox
    receptor_output_artifact_id: str = Field(min_length=1)
    receptor_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    ligand_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    conformer_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    command: list[str] = Field(default_factory=list)
    execution: GninaExecutionEvidence | None = None
    poses: list[GninaPoseResult] = Field(default_factory=list)
    failure: DockingFailure | None = None

    @model_validator(mode="after")
    def guard_pose_publication(self) -> "GninaJobRecord":
        if self.status is not DockingJobStatus.COMPLETED:
            if self.poses:
                raise ValueError("Only a completed GNINA job may publish poses")
            return self
        if not self.poses or self.execution is None:
            raise ValueError("A completed GNINA job requires poses and execution evidence")
        if self.execution.exit_code != 0 or self.execution.canceled or self.execution.timed_out:
            raise ValueError("A failed or canceled GNINA execution cannot publish poses")
        if self.request.parameters.compute == "cuda" and not self.execution.gpu_process_observed:
            raise ValueError("A CUDA job requires observed GPU process evidence")
        artifact_ids = set()
        filenames = set()
        previous_score = float("inf")
        for expected, pose in enumerate(self.poses, start=1):
            if pose.mode != expected or pose.artifact.mode != expected:
                raise ValueError("GNINA poses must preserve the engine's contiguous rank order")
            if pose.cnn_score > previous_score:
                raise ValueError("GNINA poses must retain descending CNN score order")
            previous_score = pose.cnn_score
            artifact_ids.add(pose.artifact.artifact_id)
            filenames.add(pose.artifact.filename)
        if len(artifact_ids) != len(self.poses) or len(filenames) != len(self.poses):
            raise ValueError("GNINA pose artifacts must be unique")
        return self
