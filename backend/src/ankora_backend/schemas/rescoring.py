"""Frozen contracts for cross-engine `--score_only` pose rescoring (M2a / M5)."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from ankora_backend.schemas.binding_sites import BindingBox
from ankora_backend.schemas.gnina import GninaCnnModelSelector
from ankora_backend.schemas.receptors import ReceptorFlexSpec, ResidueLocator
from ankora_backend.schemas.v02_contracts import (
    LigandFlexibilitySpec,
    PoseComplexIdentity,
    ScoreObservation,
    ScoringFunctionId,
)

type _Sha256 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
type _NonBlank = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class AutoDock4RescoreBackend(StrEnum):
    """Explicit backend choice for evaluating the AutoDock4 scoring family in place."""

    AUTODOCK4_EPDB = "autodock4_epdb"
    VINA_AD4_MAPS = "vina_ad4_maps"


class PoseRescoreContext(BaseModel):
    """Shared receptor, box, and optional AutoGrid4 map context verified by E4 and E7."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    receptor_flex_spec: ReceptorFlexSpec
    binding_box: BindingBox
    binding_box_sha256: _Sha256
    ligand_flexibility: LigandFlexibilitySpec = Field(default_factory=LigandFlexibilitySpec)
    autogrid_map_set_sha256: _Sha256 | None = None
    autogrid_map_prefix: _NonBlank | None = None
    autogrid_map_receptor_sha256: _Sha256 | None = None
    autogrid_map_flex_residues: tuple[ResidueLocator, ...] = ()
    autogrid_map_flex_atom_types: tuple[str, ...] = ()
    autogrid_map_affinity_atom_types: tuple[str, ...] | None = None
    expected_flex_atom_types: tuple[str, ...] = ()


class PoseRescoreRequest(BaseModel):
    """Explicit opt-in request to evaluate one fixed PoseComplex across scoring functions."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    parent_compound_id: _NonBlank
    parent_state_id: _NonBlank
    pose_complex: PoseComplexIdentity
    scoring_functions: tuple[ScoringFunctionId, ...] = Field(min_length=1)
    autodock4_backend: AutoDock4RescoreBackend = AutoDock4RescoreBackend.AUTODOCK4_EPDB
    gnina_compute: Literal["cpu", "cuda"] = "cpu"
    gnina_device_index: int = Field(default=0, ge=0)
    gnina_cnn_model: GninaCnnModelSelector = "dense_1_3"
    cpu_threads: int = Field(default=1, ge=1)
    timeout_minutes: int = Field(default=10, ge=1, le=240)

    @model_validator(mode="after")
    def validate_unique_scoring_functions(self) -> Self:
        if len(set(self.scoring_functions)) != len(self.scoring_functions):
            raise ValueError("scoring_functions must not contain duplicate entries")
        return self


class PoseRescoreFunctionEvidence(BaseModel):
    """Recorded raw execution provenance for one `--score_only` engine invocation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    scoring_functions: tuple[ScoringFunctionId, ...] = Field(min_length=1)
    tool_name: _NonBlank
    tool_version: _NonBlank
    tool_sha256: _Sha256 | None = None
    command: tuple[str, ...] = Field(min_length=1)
    exit_code: int
    stdout_sha256: _Sha256
    stderr_sha256: _Sha256
    used_flex: bool = False
    unbound_reference_shifted: bool = False
    intermolecular_kcal_mol: float | None = Field(default=None, allow_inf_nan=False)
    total_internal_kcal_mol: float | None = Field(default=None, allow_inf_nan=False)
    torsional_free_energy_kcal_mol: float | None = Field(default=None, allow_inf_nan=False)
    unbound_system_energy_kcal_mol: float | None = Field(default=None, allow_inf_nan=False)
    intramolecular_energy_kcal_mol: float | None = Field(default=None, allow_inf_nan=False)
    cnn_affinity_variance: float | None = Field(default=None, ge=0.0, allow_inf_nan=False)


class PoseRescoreResult(BaseModel):
    """Immutable cross-scoring output emitting canonical M0 ScoreObservation records."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    pose_complex: PoseComplexIdentity
    observations: tuple[ScoreObservation, ...] = Field(min_length=1)
    evidence: tuple[PoseRescoreFunctionEvidence, ...] = Field(min_length=1)
    mutated_original_pose: Literal[False] = False


class SavedPoseRescoreRequest(BaseModel):
    """HTTP request to cross-score one saved docking pose by immutable artifact IDs."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source_engine: Literal["vina", "autodock4", "autodock_gpu", "gnina"]
    job_id: _NonBlank
    pose_artifact_id: _NonBlank
    scoring_functions: tuple[ScoringFunctionId, ...] = Field(min_length=1)
    autogrid_job_id: _NonBlank | None = None
    autodock4_backend: AutoDock4RescoreBackend = AutoDock4RescoreBackend.AUTODOCK4_EPDB
    gnina_compute: Literal["cpu", "cuda"] = "cpu"
    gnina_device_index: int = Field(default=0, ge=0)
    gnina_cnn_model: GninaCnnModelSelector = "dense_1_3"
    cpu_threads: int = Field(default=1, ge=1)
    timeout_minutes: int = Field(default=10, ge=1, le=240)

    @model_validator(mode="after")
    def validate_unique_functions(self) -> Self:
        if len(set(self.scoring_functions)) != len(self.scoring_functions):
            raise ValueError("scoring_functions must not contain duplicate entries")
        return self
