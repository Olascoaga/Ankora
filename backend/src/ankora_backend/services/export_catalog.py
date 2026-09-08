"""One read-only catalog over everything this project has exported.

Every export already wrote a manifest saying what it was and where it came
from; none of them could be listed. This walks the three export trees and
projects each manifest into a common entry, reading manifests only — never a
results table, a ZIP, an image or a coordinate file.

The manifests are small by design (44 of them total 115 KiB in the real
project), which is what makes a full parse the right choice here and the wrong
one for the library and result catalogs.
"""

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from ankora_backend.domain.errors import AnkoraDomainError
from ankora_backend.domain.project_context import resolve_project_root
from ankora_backend.schemas.exports import (
    ExportEntry,
    ExportFile,
    ExportKind,
    ExportPage,
)
from ankora_backend.schemas.results_catalog import ReproducibilityAssessment

_STAGE = "export_catalog"

# The files each kind serves back, and nothing else: a filename reaching a
# route from a manifest is still a filename that came from disk.
_CAMPAIGN_SERVED = {"results.csv", "manifest.json", "README.txt", "campaign_bundle.zip"}


class ExportCatalogService:
    def __init__(self, *, root: Path) -> None:
        self._root = root.resolve()
        self._project_root = resolve_project_root(self._root)

    @classmethod
    def from_environment(cls) -> "ExportCatalogService":
        configured = os.getenv("ANKORA_DATA_DIR")
        root = Path(configured) if configured else Path.cwd() / ".ankora-data"
        return cls(root=root)

    def list_exports(
        self, *, offset: int = 0, limit: int = 25, kind: ExportKind | None = None
    ) -> ExportPage:
        """Everything sent out of Ankora, newest first."""
        entries = [
            *self._campaigns(),
            *self._figures(),
            *self._pose_complexes(),
        ]
        if kind is not None:
            entries = [entry for entry in entries if entry.kind is kind]
        # The id breaks ties so two exports written in one clock tick keep a
        # stable order between requests.
        entries.sort(key=lambda item: (item.exported_at, item.export_id), reverse=True)
        return ExportPage(
            entries=entries[offset : offset + limit],
            total=len(entries),
            offset=offset,
            limit=limit,
        )

    # --- one projection per kind of export --------------------------------

    def _campaigns(self) -> list[ExportEntry]:
        entries: list[ExportEntry] = []
        for directory in _directories(self._exports_dir()):
            manifest = _manifest(directory / "manifest.json")
            if manifest is None:
                continue
            engine = manifest.get("engine") or {}
            counts = manifest.get("counts") or {}
            reproducibility = manifest.get("reproducibility") or {}
            bundle = manifest.get("bundle") or {}
            assessment = _assessment(reproducibility)
            archive_filename = _archive_filename(bundle)
            served = set(_CAMPAIGN_SERVED)
            if archive_filename is not None:
                served.add(archive_filename)
            display_name = _display_name(bundle)
            source_kind = manifest.get("source_kind")
            source_id = manifest.get("source_id")
            catalog_id = bundle.get("catalog_id") if isinstance(bundle, dict) else None
            if (
                not isinstance(catalog_id, str)
                and isinstance(source_kind, str)
                and isinstance(source_id, str)
            ):
                catalog_id = f"{source_kind}:{source_id}"
            entries.append(
                ExportEntry(
                    export_id=directory.name,
                    kind=ExportKind.CAMPAIGN,
                    exported_at=_moment(manifest.get("exported_at"), directory),
                    title=display_name or _engine_label(engine),
                    subtitle=(
                        f"{counts.get('succeeded', 0)}/{counts.get('selected', 0)} molecules docked"
                    ),
                    catalog_id=catalog_id,
                    source_kind=source_kind,
                    source_id=source_id,
                    display_name=display_name,
                    input_identity_sha256=_sha256_value(
                        bundle.get("input_identity_sha256")
                    ),
                    bundle_identity_sha256=_sha256_value(
                        bundle.get("bundle_identity_sha256")
                    ),
                    archive_filename=archive_filename,
                    reproducibility=assessment,
                    bitwise_reproducible=reproducibility.get("bitwise_reproducible"),
                    directory=str(directory),
                    files=_files(
                        directory,
                        served=served,
                        url_prefix=f"/exports/{directory.name}",
                    ),
                )
            )
        return entries

    def _figures(self) -> list[ExportEntry]:
        entries: list[ExportEntry] = []
        for directory in _directories(self._exports_dir() / "figures"):
            manifest = _manifest(directory / "figure.json")
            if manifest is None:
                continue
            result = manifest.get("result") or {}
            written_to = Path(str(manifest.get("written_to") or directory))
            outside = written_to.resolve() != directory.resolve()
            entries.append(
                ExportEntry(
                    export_id=directory.name,
                    kind=ExportKind.FIGURE,
                    exported_at=_moment(manifest.get("exported_at"), directory),
                    title=_figure_title(manifest, result),
                    subtitle=", ".join(
                        str(item.get("filename")) for item in manifest.get("files") or []
                    ),
                    catalog_id=result.get("catalog_id"),
                    analysis_id=result.get("interaction_analysis_id"),
                    ligand_id=result.get("ligand_id"),
                    directory=str(written_to),
                    outside_project=outside,
                    # Images written into the scientist's own folder are named
                    # rather than linked; the manifest stayed here either way.
                    files=_files(
                        directory,
                        served=None if outside else {"figure.json", *_names(manifest)},
                        url_prefix=f"/results/figures/{directory.name}",
                    ),
                )
            )
        return entries

    def _pose_complexes(self) -> list[ExportEntry]:
        entries: list[ExportEntry] = []
        for directory in _directories(self._exports_dir() / "pose_complexes"):
            manifest = _manifest(directory / "complex.json")
            if manifest is None:
                continue
            written_to = Path(str(manifest.get("written_to") or directory))
            molecule = str(manifest.get("molecule_name") or "Ligand-receptor complex")
            entries.append(
                ExportEntry(
                    export_id=directory.name,
                    kind=ExportKind.POSE_COMPLEX,
                    exported_at=_moment(manifest.get("exported_at"), directory),
                    title=f"{molecule} · complex",
                    subtitle=str(manifest.get("pose_label") or ""),
                    catalog_id=manifest.get("catalog_id"),
                    ligand_id=manifest.get("ligand_id"),
                    directory=str(written_to),
                    outside_project=written_to.resolve() != directory.resolve(),
                    # No route serves a complex, so every file here is named.
                    files=_files(directory, served=None, url_prefix=None),
                )
            )
        return entries

    def _exports_dir(self) -> Path:
        resolved = (self._project_root / "exports").resolve()
        if self._root not in resolved.parents and resolved != self._root:
            raise AnkoraDomainError(
                code="EXPORT_CATALOG_UNAVAILABLE",
                stage=_STAGE,
                message="The project's export directory is not inside its data root.",
                status_code=500,
            )
        return resolved


def _directories(parent: Path) -> list[Path]:
    """Only UUID-named directories: `figures` and `pose_complexes` live here too."""
    if not parent.is_dir():
        return []
    found: list[Path] = []
    for candidate in parent.iterdir():
        if not candidate.is_dir():
            continue
        try:
            UUID(candidate.name)
        except ValueError:
            continue
        found.append(candidate)
    return found


def _manifest(path: Path) -> dict[str, Any] | None:
    """A manifest that cannot be read hides one export, never the rest."""
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return loaded if isinstance(loaded, dict) else None


def _assessment(value: Any) -> ReproducibilityAssessment | None:
    """Read evidence-aware manifests without upgrading legacy booleans."""
    if not isinstance(value, dict) or "status" not in value:
        return None
    evidence = {key: item for key, item in value.items() if key != "note"}
    try:
        return ReproducibilityAssessment.model_validate(evidence)
    except ValueError:
        return None


def _display_name(bundle: Any) -> str | None:
    if not isinstance(bundle, dict):
        return None
    value = bundle.get("display_name")
    return value if isinstance(value, str) and 1 <= len(value) <= 80 else None


def _sha256_value(value: Any) -> str | None:
    if not isinstance(value, str) or len(value) != 64:
        return None
    return value if all(character in "0123456789abcdef" for character in value) else None


def _archive_filename(bundle: Any) -> str | None:
    if not isinstance(bundle, dict):
        return None
    value = bundle.get("archive_filename")
    if not isinstance(value, str):
        return None
    if Path(value).name != value or not value.lower().endswith(".zip"):
        return None
    return value


def _names(manifest: dict[str, Any]) -> set[str]:
    return {
        str(item.get("filename")) for item in manifest.get("files") or [] if item.get("filename")
    }


def _files(directory: Path, *, served: set[str] | None, url_prefix: str | None) -> list[ExportFile]:
    try:
        found = sorted(item for item in directory.iterdir() if item.is_file())
    except OSError:
        return []
    return [
        ExportFile(
            filename=item.name,
            size_bytes=item.stat().st_size,
            content_url=(
                f"{url_prefix}/{item.name}"
                if url_prefix and served and item.name in served
                else None
            ),
        )
        for item in found
    ]


def _engine_label(engine: dict[str, Any]) -> str:
    name = str(engine.get("name") or "Unknown engine")
    version = str(engine.get("version") or "")
    device = engine.get("device")
    label = f"{name} {version}".strip()
    return f"{label} · {device}" if device else label


def _figure_title(manifest: dict[str, Any], result: dict[str, Any]) -> str:
    molecule = str(result.get("molecule") or "Figure")
    source = str(manifest.get("source") or "")
    kind = "interaction diagram" if source == "interaction_diagram" else "3D view"
    return f"{molecule} · {kind}"


def _moment(value: Any, directory: Path) -> datetime:
    """The manifest's own timestamp, or the folder's if it has none."""
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            pass
    return datetime.fromtimestamp(directory.stat().st_mtime, tz=UTC)
