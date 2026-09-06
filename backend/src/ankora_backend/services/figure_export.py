"""Write a recorded view out as a figure someone can publish (M9).

The scientific content is already fixed by the time this module runs: the
diagram and the 3D view are drawn from one immutable analysis record, and what
arrives here is that exact picture. So this service does the one thing a figure
export should do — put the picture on disk in the formats a journal asks for,
next to a manifest saying which analysis it is — and nothing else.

Two honesties the format carries rather than hides:

* **Only the diagram can be vector.** It is drawn as SVG and is written out as
  SVG unchanged. The 3D view is a WebGL raster; there is no true vector inside
  it to export, so its PDF is a raster at a stated resolution and its manifest
  says so instead of implying otherwise.
* **The resolution is recorded on every raster.** A TIFF with no DPI is a
  figure a typesetter has to guess about.
* **A chosen folder is written to, never written over.** The scientist points
  this at the folder holding a manuscript, where a silently replaced file is a
  figure that changed underneath a paper. Every write is create-only, and a
  name already taken gets the next free one.
"""

import base64
import io
import json
import os
from datetime import UTC, datetime
from importlib import import_module
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from ankora_backend.domain.errors import AnkoraDomainError
from ankora_backend.domain.project_context import resolve_project_root
from ankora_backend.schemas.figures import (
    FigureExport,
    FigureExportRequest,
    FigureFile,
    FigureFormat,
    FigureManifest,
    FigureManifestResult,
    FigureSource,
)
from ankora_backend.services.export_destinations import (
    free_name,
    slug,
    validated_destination,
)

_STAGE = "figure_export"

# A 4K RGBA render is a few megabytes; this leaves generous headroom while
# still refusing a payload that could only be a mistake or an attack.
MAX_RASTER_BYTES = 64 * 1024 * 1024
MAX_SVG_CHARS = 8 * 1024 * 1024

_BASENAME = {
    FigureSource.INTERACTION_DIAGRAM: "interaction_diagram",
    FigureSource.POSE_VIEW_3D: "pose_view_3d",
}
_EXTENSION = {
    FigureFormat.SVG: "svg",
    FigureFormat.PNG: "png",
    FigureFormat.TIFF: "tiff",
    FigureFormat.PDF: "pdf",
}


class FigureExportService:
    def __init__(self, *, root: Path) -> None:
        self._root = root.resolve()
        self._project_root = resolve_project_root(self._root)

    @classmethod
    def from_environment(cls) -> "FigureExportService":
        configured = os.getenv("ANKORA_DATA_DIR")
        root = Path(configured) if configured else Path.cwd() / ".ankora-data"
        return cls(root=root)

    def export_figure(self, request: FigureExportRequest) -> FigureExport:
        formats = _ordered_formats(request)
        if FigureFormat.SVG in formats and request.source is FigureSource.POSE_VIEW_3D:
            raise _failure(
                "FIGURE_VECTOR_UNAVAILABLE",
                "The 3D view is a rendered raster, so it has no vector form to "
                "export. Use the interaction diagram for a vector figure.",
            )

        svg = _validated_svg(request, formats)
        raster = _validated_raster(request, formats)

        figure_id = str(uuid4())
        record_directory = self._figure_dir(figure_id)
        record_directory.mkdir(parents=True, exist_ok=False)
        chosen = validated_destination(request.destination, stage=_STAGE, prefix="FIGURE")
        directory = chosen or record_directory
        exported_at = datetime.now(UTC)
        # Inside the project a figure owns its whole folder, so a plain name is
        # unambiguous. In a folder the scientist already keeps things in, a file
        # called `interaction_diagram.svg` says nothing about which molecule or
        # which pose it is.
        basename = _descriptive_basename(request) if chosen else _BASENAME[request.source]

        files: list[FigureFile] = []
        for figure_format in formats:
            filename = free_name(directory, basename, _EXTENSION[figure_format])
            path = directory / filename
            if figure_format is FigureFormat.SVG:
                assert svg is not None
                with path.open("x", encoding="utf-8", newline="\n") as stream:
                    stream.write(svg)
                files.append(
                    FigureFile(
                        filename=filename,
                        format=figure_format,
                        size_bytes=path.stat().st_size,
                        vector=True,
                    )
                )
                continue
            assert raster is not None
            width, height = _write_raster(path, raster, figure_format, request.dpi)
            files.append(
                FigureFile(
                    filename=filename,
                    format=figure_format,
                    size_bytes=path.stat().st_size,
                    vector=False,
                    width_px=width,
                    height_px=height,
                    dpi=request.dpi,
                )
            )

        export = FigureExport(
            figure_id=figure_id,
            exported_at=exported_at,
            source=request.source,
            catalog_id=request.catalog_id,
            ligand_id=request.ligand_id,
            molecule_name=request.molecule_name,
            pose_artifact_id=request.pose_artifact_id,
            pose_label=request.pose_label,
            analysis_id=request.analysis_id,
            directory=str(directory),
            outside_project=chosen is not None,
            record_directory=str(record_directory),
            files=files,
        )
        # The record always stays in the project: an export is something that
        # happened, and a folder the scientist may later move or tidy is not
        # where that fact can live.
        manifest = _manifest(export)
        with (record_directory / "figure.json").open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(manifest)
        if chosen is not None:
            name = free_name(chosen, basename, "json")
            with (chosen / name).open("x", encoding="utf-8", newline="\n") as stream:
                stream.write(manifest)
        return export

    def file_path(self, figure_id: str, filename: str) -> Path:
        """The filename comes from a URL, so it is an allowlist, not a path."""
        allowed = {"figure.json"} | {
            f"{basename}.{extension}"
            for basename in _BASENAME.values()
            for extension in _EXTENSION.values()
        }
        if filename not in allowed:
            raise self._not_found(figure_id, filename)
        path = self._figure_dir(figure_id) / filename
        if not path.is_file():
            raise self._not_found(figure_id, filename)
        return path

    def _figure_dir(self, figure_id: str) -> Path:
        try:
            normalized = str(UUID(figure_id))
        except ValueError as error:
            raise self._not_found(figure_id, None) from error
        resolved = (self._project_root / "exports" / "figures" / normalized).resolve()
        if self._root not in resolved.parents:
            raise self._not_found(figure_id, None)
        return resolved

    @staticmethod
    def _not_found(figure_id: str, filename: str | None) -> AnkoraDomainError:
        return AnkoraDomainError(
            code="FIGURE_NOT_FOUND",
            stage=_STAGE,
            message="No exported figure file exists for this identifier.",
            status_code=404,
            details={"figure_id": figure_id, "filename": filename},
        )


def _descriptive_basename(request: FigureExportRequest) -> str:
    """`RV2_Mode-1_interaction_diagram` - readable in a folder of its own peers."""
    parts = [request.molecule_name, request.pose_label, _BASENAME[request.source]]
    return "_".join(slug(part) for part in parts if slug(part)) or "figure"


def _ordered_formats(request: FigureExportRequest) -> list[FigureFormat]:
    """Deduplicated, in a fixed order so two identical requests agree."""
    order = [FigureFormat.SVG, FigureFormat.PNG, FigureFormat.TIFF, FigureFormat.PDF]
    requested = set(request.formats)
    return [item for item in order if item in requested]


def _validated_svg(request: FigureExportRequest, formats: list[FigureFormat]) -> str | None:
    if FigureFormat.SVG not in formats:
        return None
    svg = (request.svg or "").strip()
    if not svg.startswith("<svg") or "</svg>" not in svg:
        raise _failure(
            "FIGURE_SVG_INVALID",
            "The vector figure was not a complete SVG document.",
        )
    if len(svg) > MAX_SVG_CHARS:
        raise _failure("FIGURE_TOO_LARGE", "This figure is larger than Ankora will write.")
    return svg


def _validated_raster(request: FigureExportRequest, formats: list[FigureFormat]) -> bytes | None:
    if not any(item is not FigureFormat.SVG for item in formats):
        return None
    payload = request.png_base64 or ""
    # A browser hands over a data URI; the prefix is not part of the image.
    _, _, encoded = payload.rpartition(",")
    try:
        raster = base64.b64decode(encoded or payload, validate=True)
    except (ValueError, TypeError) as error:
        raise _failure(
            "FIGURE_RASTER_INVALID",
            "The rendered figure could not be decoded.",
        ) from error
    if not raster:
        raise _failure(
            "FIGURE_RASTER_INVALID",
            "A raster format was requested but no rendered figure was sent.",
        )
    if len(raster) > MAX_RASTER_BYTES:
        raise _failure("FIGURE_TOO_LARGE", "This figure is larger than Ankora will write.")
    if not raster.startswith(b"\x89PNG\r\n\x1a\n"):
        raise _failure(
            "FIGURE_RASTER_INVALID",
            "The rendered figure was not a PNG.",
        )
    return raster


def _write_raster(
    path: Path, raster: bytes, figure_format: FigureFormat, dpi: int
) -> tuple[int, int]:
    if figure_format is FigureFormat.PNG:
        # Written byte for byte: re-encoding the page's own PNG could only
        # lose something, never add anything.
        with path.open("xb") as stream:
            stream.write(raster)
        image = _open(raster)
        return int(image.width), int(image.height)

    image = _open(raster)
    width, height = int(image.width), int(image.height)
    try:
        if figure_format is FigureFormat.TIFF:
            image.save(path, format="TIFF", compression="tiff_lzw", dpi=(dpi, dpi))
        else:
            # PDF has no alpha channel, so transparency is flattened onto white
            # rather than silently turned black by the encoder.
            _flattened(image).save(path, format="PDF", resolution=float(dpi))
    except OSError as error:
        raise _failure(
            "FIGURE_WRITE_FAILED",
            "The figure could not be written in this format.",
            details={"format": figure_format.value, "reason": str(error)},
        ) from error
    return width, height


def _open(raster: bytes) -> Any:
    try:
        image_module = import_module("PIL.Image")
    except ImportError as error:  # pragma: no cover - Pillow ships with RDKit
        raise _failure(
            "FIGURE_ENCODER_MISSING",
            "Pillow is required to write TIFF and PDF figures.",
        ) from error
    try:
        image = image_module.open(io.BytesIO(raster))
        image.load()
    except OSError as error:
        raise _failure(
            "FIGURE_RASTER_INVALID",
            "The rendered figure could not be read as an image.",
        ) from error
    return image


def _flattened(image: Any) -> Any:
    if image.mode not in {"RGBA", "LA", "P"}:
        return image.convert("RGB")
    image_module = import_module("PIL.Image")
    rgba = image.convert("RGBA")
    canvas = image_module.new("RGBA", rgba.size, (255, 255, 255, 255))
    canvas.alpha_composite(rgba)
    return canvas.convert("RGB")


def _manifest(export: FigureExport) -> str:
    payload = FigureManifest(
        figure_id=export.figure_id,
        exported_at=export.exported_at,
        source=export.source,
        result=FigureManifestResult(
            catalog_id=export.catalog_id,
            ligand_id=export.ligand_id,
            molecule=export.molecule_name,
            pose_artifact_id=export.pose_artifact_id,
            pose=export.pose_label,
            interaction_analysis_id=export.analysis_id,
        ),
        written_to=export.directory,
        recorded_in=export.record_directory,
        files=export.files,
        notes=[
            "This figure is a copy of one recorded interaction analysis. It was "
            "not recomputed for export.",
            "Contacts are geometric criteria evaluated on one exact pose. They "
            "are not a measured binding affinity.",
            (
                "The interaction diagram is vector; its SVG is the original and "
                "every raster here was made from it."
                if export.source is FigureSource.INTERACTION_DIAGRAM
                else "The 3D view is a rendered raster. Its PDF embeds that "
                "raster at the stated resolution rather than vector geometry."
            ),
        ],
    )
    return json.dumps(payload.model_dump(mode="json"), indent=2, sort_keys=False) + "\n"


def _failure(
    code: str, message: str, *, details: dict[str, object] | None = None
) -> AnkoraDomainError:
    return AnkoraDomainError(
        code=code,
        stage=_STAGE,
        message=message,
        status_code=422,
        details=details,
    )
