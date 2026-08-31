"""Publication figures written out of a recorded analysis (M9).

A figure is what leaves Ankora and ends up in a paper, so it is where a claim
about the picture either holds or quietly stops holding: whether it is really
vector, what resolution it really is, and which analysis it really came from.
"""

import base64
import io
import json
from importlib import import_module
from pathlib import Path
from typing import Any

import pytest

from ankora_backend.domain.errors import AnkoraDomainError
from ankora_backend.schemas.figures import FigureExportRequest
from ankora_backend.services.figure_export import FigureExportService

Image: Any = import_module("PIL.Image")

SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 640 390">'
    '<line x1="10" y1="10" x2="90" y2="90" stroke="#1b7f5f"/>'
    "</svg>"
)


def _png(*, size: tuple[int, int] = (64, 48), transparent: bool = False) -> str:
    image = Image.new(
        "RGBA" if transparent else "RGB",
        size,
        (0, 0, 0, 0) if transparent else (12, 90, 70),
    )
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode()


def _request(**overrides: Any) -> FigureExportRequest:
    payload: dict[str, Any] = {
        "source": "interaction_diagram",
        "formats": ["svg", "png", "tiff", "pdf"],
        "svg": SVG,
        "png_base64": _png(),
        "dpi": 300,
        "catalog_id": "vina_job:job-1",
        "ligand_id": "ligand-1",
        "molecule_name": "RV2",
        "pose_artifact_id": "pose-1",
        "pose_label": "Mode 1",
        "analysis_id": "analysis-1",
    }
    payload.update(overrides)
    return FigureExportRequest(**payload)


def _service(tmp_path: Path) -> FigureExportService:
    return FigureExportService(root=tmp_path)


def test_the_diagrams_svg_is_written_exactly_as_it_was_drawn(tmp_path: Path) -> None:
    """The vector figure is the original, not a re-render of it.

    Anything Ankora redrew on the way out could disagree with the screen the
    scientist actually read.
    """
    export = _service(tmp_path).export_figure(_request(formats=["svg"]))

    written = (Path(export.directory) / "interaction_diagram.svg").read_text(encoding="utf-8")
    assert written == SVG
    assert export.files[0].vector is True


def test_the_3d_view_is_never_offered_as_a_vector_figure(tmp_path: Path) -> None:
    """It is a WebGL raster; exporting it as `.svg` would be a lie in a filename."""
    with pytest.raises(AnkoraDomainError) as error:
        _service(tmp_path).export_figure(
            _request(source="pose_view_3d", formats=["svg", "png"], svg=SVG)
        )

    assert error.value.code == "FIGURE_VECTOR_UNAVAILABLE"


def test_the_3d_view_still_exports_every_raster_format(tmp_path: Path) -> None:
    export = _service(tmp_path).export_figure(
        _request(source="pose_view_3d", formats=["png", "tiff", "pdf"], svg=None)
    )

    assert [item.filename for item in export.files] == [
        "pose_view_3d.png",
        "pose_view_3d.tiff",
        "pose_view_3d.pdf",
    ]
    assert all(item.vector is False for item in export.files)


def test_the_png_is_the_pages_own_bytes(tmp_path: Path) -> None:
    """Re-encoding could only lose something; it could never add anything."""
    raster = _png()
    export = _service(tmp_path).export_figure(_request(formats=["png"], png_base64=raster))

    written = (Path(export.directory) / "interaction_diagram.png").read_bytes()
    assert written == base64.b64decode(raster.split(",", 1)[1])


def test_every_raster_records_the_resolution_it_was_written_at(tmp_path: Path) -> None:
    """A TIFF with no DPI is a figure a typesetter has to guess about."""
    export = _service(tmp_path).export_figure(_request(formats=["tiff", "pdf"], dpi=600))

    assert {item.dpi for item in export.files} == {600}
    assert {(item.width_px, item.height_px) for item in export.files} == {(64, 48)}
    with Image.open(Path(export.directory) / "interaction_diagram.tiff") as tiff:
        assert tiff.info["dpi"] == (600, 600)


def test_a_transparent_figure_is_flattened_onto_white_for_pdf(tmp_path: Path) -> None:
    """PDF has no alpha channel, and the encoder's own default turns it black."""
    export = _service(tmp_path).export_figure(
        _request(formats=["pdf"], png_base64=_png(transparent=True))
    )

    document = (Path(export.directory) / "interaction_diagram.pdf").read_bytes()
    assert document.startswith(b"%PDF")
    assert export.files[0].vector is False


def test_a_payload_that_is_not_a_png_is_refused(tmp_path: Path) -> None:
    encoded = base64.b64encode(b"GIF89a not a png").decode()

    with pytest.raises(AnkoraDomainError) as error:
        _service(tmp_path).export_figure(_request(formats=["png"], png_base64=encoded))

    assert error.value.code == "FIGURE_RASTER_INVALID"


def test_a_raster_format_without_a_rendered_figure_is_refused(tmp_path: Path) -> None:
    with pytest.raises(AnkoraDomainError) as error:
        _service(tmp_path).export_figure(_request(formats=["tiff"], png_base64=None))

    assert error.value.code == "FIGURE_RASTER_INVALID"


def test_something_that_is_not_an_svg_document_is_refused(tmp_path: Path) -> None:
    with pytest.raises(AnkoraDomainError) as error:
        _service(tmp_path).export_figure(_request(formats=["svg"], svg="<html>nope</html>"))

    assert error.value.code == "FIGURE_SVG_INVALID"


def test_the_manifest_names_the_analysis_the_figure_came_from(tmp_path: Path) -> None:
    """A figure with no traceable source is the thing Ankora exists not to make."""
    export = _service(tmp_path).export_figure(_request())

    manifest = json.loads((Path(export.directory) / "figure.json").read_text(encoding="utf-8"))

    assert manifest["result"]["interaction_analysis_id"] == "analysis-1"
    assert manifest["result"]["catalog_id"] == "vina_job:job-1"
    assert manifest["result"]["pose_artifact_id"] == "pose-1"
    assert manifest["result"]["pose"] == "Mode 1"
    joined = " ".join(manifest["notes"])
    assert "not a measured binding affinity" in joined
    assert "was not recomputed for export" in joined.replace("\n", " ")


def test_the_manifest_says_which_kind_of_picture_the_pdf_holds(tmp_path: Path) -> None:
    diagram = _service(tmp_path).export_figure(_request(formats=["pdf"]))
    view = _service(tmp_path).export_figure(
        _request(source="pose_view_3d", formats=["pdf"], svg=None)
    )

    diagram_notes = " ".join(
        json.loads((Path(diagram.directory) / "figure.json").read_text(encoding="utf-8"))["notes"]
    )
    view_notes = " ".join(
        json.loads((Path(view.directory) / "figure.json").read_text(encoding="utf-8"))["notes"]
    )

    assert "vector" in diagram_notes
    assert "rendered raster" in view_notes
    assert "rather than vector geometry" in view_notes


def test_only_the_figures_own_files_can_be_read_back(tmp_path: Path) -> None:
    """The filename comes from a URL, so it is an allowlist rather than a path."""
    service = _service(tmp_path)
    export = service.export_figure(_request(formats=["png"]))

    with pytest.raises(AnkoraDomainError) as error:
        service.file_path(export.figure_id, "../../record.json")

    assert error.value.code == "FIGURE_NOT_FOUND"
    assert service.file_path(export.figure_id, "interaction_diagram.png").is_file()


def test_asking_for_one_format_twice_writes_it_once(tmp_path: Path) -> None:
    export = _service(tmp_path).export_figure(_request(formats=["png", "png", "svg"]))

    assert [item.filename for item in export.files] == [
        "interaction_diagram.svg",
        "interaction_diagram.png",
    ]


# --- a folder the scientist chose ------------------------------------------


def test_a_chosen_folder_receives_the_files_and_the_project_keeps_the_record(
    tmp_path: Path,
) -> None:
    """Where the figure goes is the scientist's; that it happened is Ankora's."""
    destination = tmp_path / "manuscript"
    destination.mkdir()

    export = _service(tmp_path).export_figure(
        _request(formats=["svg", "png"], destination=str(destination))
    )

    assert export.outside_project is True
    assert Path(export.directory) == destination
    assert {item.name for item in destination.iterdir()} == {
        "RV2_Mode-1_interaction_diagram.svg",
        "RV2_Mode-1_interaction_diagram.png",
        "RV2_Mode-1_interaction_diagram.json",
    }
    # The project holds the record even though it holds none of the images.
    record = Path(export.record_directory)
    assert {item.name for item in record.iterdir()} == {"figure.json"}
    manifest = json.loads((record / "figure.json").read_text(encoding="utf-8"))
    assert manifest["written_to"] == str(destination)
    assert manifest["result"]["interaction_analysis_id"] == "analysis-1"


def test_a_figure_names_its_molecule_and_pose_outside_the_project(
    tmp_path: Path,
) -> None:
    """`interaction_diagram.svg` says nothing in a folder of its own peers."""
    destination = tmp_path / "figures"
    destination.mkdir()

    export = _service(tmp_path).export_figure(
        _request(formats=["svg"], destination=str(destination), molecule_name="RV2",
                 pose_label="Cluster 1 · run 3")
    )

    assert export.files[0].filename == "RV2_Cluster-1-run-3_interaction_diagram.svg"


def test_exporting_twice_never_replaces_the_first_figure(tmp_path: Path) -> None:
    """A silently replaced file is a figure that changed under a paper."""
    destination = tmp_path / "manuscript"
    destination.mkdir()
    service = _service(tmp_path)

    first = service.export_figure(_request(formats=["svg"], destination=str(destination)))
    second = service.export_figure(_request(formats=["svg"], destination=str(destination)))
    third = service.export_figure(_request(formats=["svg"], destination=str(destination)))

    assert first.files[0].filename == "RV2_Mode-1_interaction_diagram.svg"
    assert second.files[0].filename == "RV2_Mode-1_interaction_diagram (2).svg"
    assert third.files[0].filename == "RV2_Mode-1_interaction_diagram (3).svg"
    assert (destination / "RV2_Mode-1_interaction_diagram.svg").read_text(
        encoding="utf-8"
    ) == SVG


def test_a_folder_that_does_not_exist_is_refused_rather_than_created(
    tmp_path: Path,
) -> None:
    """Creating it would hide a typo as a figure saved somewhere unexpected."""
    with pytest.raises(AnkoraDomainError) as error:
        _service(tmp_path).export_figure(
            _request(destination=str(tmp_path / "not-there"))
        )

    assert error.value.code == "FIGURE_DESTINATION_NOT_FOUND"


def test_a_relative_destination_is_refused(tmp_path: Path) -> None:
    """Relative to what? Not to anything the scientist can see."""
    with pytest.raises(AnkoraDomainError) as error:
        _service(tmp_path).export_figure(_request(destination="figures"))

    assert error.value.code == "FIGURE_DESTINATION_INVALID"


def test_no_destination_keeps_everything_in_the_project(tmp_path: Path) -> None:
    export = _service(tmp_path).export_figure(_request(formats=["svg"]))

    assert export.outside_project is False
    assert export.directory == export.record_directory
    assert export.files[0].filename == "interaction_diagram.svg"
