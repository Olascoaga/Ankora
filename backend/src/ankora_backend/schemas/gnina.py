"""Explicit GNINA 1.3.3 settings; independent of Vina and AutoDock4 scores."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


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
