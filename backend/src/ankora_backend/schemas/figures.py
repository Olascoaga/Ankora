"""Publication figures written out of a recorded analysis (M9).

A figure is a *copy* of evidence that already exists, in a format someone can
put in a paper. Nothing here recomputes a contact, re-renders a pose from
scratch, or decides what is worth showing: the page produced the picture, and
this module only writes it down and says exactly which analysis it came from.
"""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class FigureSource(StrEnum):
    """Which of the two views the picture came from.

    Kept apart because only one of them can be vector: the diagram is drawn as
    SVG and stays SVG, while the 3D view is a WebGL raster and cannot be
    turned into one by exporting it.
    """

    INTERACTION_DIAGRAM = "interaction_diagram"
    POSE_VIEW_3D = "pose_view_3d"


class FigureFormat(StrEnum):
    SVG = "svg"
    PNG = "png"
    TIFF = "tiff"
    PDF = "pdf"


class FigureExportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: FigureSource
    formats: list[FigureFormat] = Field(min_length=1)
    # The picture itself, made by the page that was showing it. SVG for the
    # diagram; a PNG data URI for anything rasterized, including the 3D view.
    svg: str | None = None
    png_base64: str | None = None
    dpi: int = Field(default=300, ge=72, le=1200)

    catalog_id: str = Field(min_length=1)
    ligand_id: str = Field(min_length=1)
    molecule_name: str = Field(min_length=1)
    pose_artifact_id: str = Field(min_length=1)
    pose_label: str = Field(min_length=1)
    analysis_id: str | None = None

    # Where the figure files go. Left unset they stay inside the project, which
    # is where an export can always be found again; named, they land in the
    # folder the scientist actually keeps the manuscript in. Either way the
    # project keeps the record of what was exported.
    destination: str | None = Field(default=None, min_length=1)


class FigureFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    filename: str = Field(min_length=1)
    format: FigureFormat
    size_bytes: int = Field(ge=0)
    # Stated per file, because it is the difference between a figure a journal
    # can rescale and one it cannot.
    vector: bool
    width_px: int | None = None
    height_px: int | None = None
    dpi: int | None = None


class FigureExport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    figure_id: str = Field(min_length=1)
    exported_at: datetime
    source: FigureSource
    catalog_id: str = Field(min_length=1)
    ligand_id: str = Field(min_length=1)
    molecule_name: str = Field(min_length=1)
    pose_artifact_id: str = Field(min_length=1)
    pose_label: str = Field(min_length=1)
    analysis_id: str | None = None
    directory: str = Field(min_length=1)
    """Where the image files were written."""

    # True when `directory` is a folder the scientist chose rather than the
    # project's own, so the interface can say which it was.
    outside_project: bool = False
    record_directory: str = Field(min_length=1)
    """Where the project kept its record of this export."""

    files: list[FigureFile] = Field(default_factory=list)


class FigureManifestResult(BaseModel):
    """The exact result and pose represented by a saved figure.

    ``pose_artifact_id`` is optional only so manifests written before this
    identity was added remain readable. New manifests always carry it.
    """

    model_config = ConfigDict(extra="forbid")

    catalog_id: str = Field(min_length=1)
    ligand_id: str = Field(min_length=1)
    molecule: str = Field(min_length=1)
    pose_artifact_id: str | None = None
    pose: str = Field(min_length=1)
    interaction_analysis_id: str | None = None


class FigureManifest(BaseModel):
    """Project-retained record of a figure written by Ankora."""

    model_config = ConfigDict(extra="forbid")

    figure_id: str = Field(min_length=1)
    exported_at: datetime
    source: FigureSource
    result: FigureManifestResult
    # Optional only for manifests created by the first M9 figure slice. Those
    # figures lived beside ``figure.json`` but did not yet record both paths.
    written_to: str | None = Field(default=None, min_length=1)
    recorded_in: str | None = Field(default=None, min_length=1)
    files: list[FigureFile] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
