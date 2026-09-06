"""Reproducible export of a docking campaign (M8).

`SCOPE.md` asks for *reproducible* export, so a bundle is not a table of
numbers. It is the table plus everything someone would need to know what those
numbers are and how to get them again: which receptor coordinates, which search
space, which map set, which executable at which hash, and the complete search
protocol that was actually asked for.

Three rules the format enforces rather than documents:

* **The value column is named after the engine that produced it.** A column
  called `score` invites a reader to sort two exports together. Vina's empirical
  score and AutoDock4's semi-empirical binding energy are on different scales,
  and `DOCKING_POLICY.md` forbids merging them; a header is where that either
  holds or quietly stops holding.
* **Reproducibility is stated per exact comparison.** Engine family and seed
  are not evidence. A claim is made only when at least two completed records
  share one input fingerprint and their scientific-output fingerprints have
  actually been compared.
* **Molecules that were never docked stay in the table.** A selection of 259
  that produced 257 results is not a table of 257 rows; the two that failed and
  why are part of the result.
"""

import csv
import io
import json
import os
import shutil
import zipfile
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from ankora_backend.domain.errors import AnkoraDomainError
from ankora_backend.domain.project_context import resolve_project_root
from ankora_backend.persistence.autodock4_store import AutoDock4JobStore
from ankora_backend.persistence.autodock_gpu_store import AutoDockGpuJobStore
from ankora_backend.persistence.binding_site_store import BindingSiteArtifactStore
from ankora_backend.persistence.docking_store import DockingArtifactStore
from ankora_backend.schemas.autodock4 import AutoDock4BatchRecord
from ankora_backend.schemas.autodock_gpu import AutoDockGpuBatchRecord
from ankora_backend.schemas.docking import VinaBatchDockingRecord
from ankora_backend.schemas.figures import FigureManifest
from ankora_backend.schemas.pose_interactions import InteractionAnalysisRecord
from ankora_backend.schemas.results_catalog import ReproducibilityAssessment
from ankora_backend.services.export_destinations import (
    free_directory,
    slug,
    validated_destination,
)
from ankora_backend.services.reproducibility import ReproducibilityService

_STAGE = "campaign_export"

_HEADER_COMMON = [
    "rank",
    "molecule",
    "source_index",
    "ligand_id",
    "canonical_smiles",
    "molecular_weight_g_mol",
    "status",
    "failure_code",
    "failure_message",
]


@dataclass(frozen=True, slots=True)
class ExportedCampaign:
    """One campaign, flattened only as far as a table can honestly go."""

    engine: str
    engine_version: str
    backend: str | None
    value_column: str
    """The engine's own measure, named so two engines never share a column."""

    reproducibility: ReproducibilityAssessment
    receptor_id: str
    receptor_sha256: str | None
    binding_site_id: str
    box: dict[str, float]
    map_set_id: str | None
    map_set_identity_key: str | None
    selection_manifest_sha256: str
    library_id: str
    filter_run_id: str
    parameters: dict[str, Any]
    executable_sha256: str | None
    device_name: str | None
    selected_count: int
    succeeded_count: int
    failed_count: int
    rows: list[dict[str, Any]]


@dataclass(frozen=True, slots=True)
class RecordedEvidence:
    """M9 records copied into one campaign bundle without recomputation."""

    analyses: list[dict[str, Any]]
    figures: list[dict[str, Any]]
    collection_warnings: list[dict[str, str]]

    def manifest_payload(self) -> dict[str, Any]:
        return {
            "pose_interaction_analyses": self.analyses,
            "figures": self.figures,
            "collection_warnings": self.collection_warnings,
            "notes": [
                "These files are copies of records and rendered figures that "
                "already existed when this campaign was exported.",
                "No interaction was recomputed and no figure was redrawn for this bundle.",
                "Interaction contacts describe geometric criteria on one exact "
                "pose; they are not measured affinity or biological proof.",
            ],
        }


def _empty_evidence() -> RecordedEvidence:
    return RecordedEvidence(analyses=[], figures=[], collection_warnings=[])


def results_csv(campaign: ExportedCampaign) -> str:
    """One row per selected molecule, in the engine's own ranking order.

    Molecules the engine could not dock keep their row and carry the reason, so
    the table describes the selection rather than only its successes.
    """
    columns = [*_HEADER_COMMON, campaign.value_column]
    if campaign.engine != "AutoDock Vina":
        # Cluster population describes sampling concentration within this
        # execution; it is not evidence that a separate execution will match.
        columns += ["clusters", "top_cluster_runs"]

    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=columns, extrasaction="ignore", lineterminator="\n")
    writer.writeheader()
    for row in campaign.rows:
        writer.writerow(row)
    return buffer.getvalue()


def manifest(
    campaign: ExportedCampaign,
    *,
    exported_at: datetime | None = None,
    evidence: RecordedEvidence | None = None,
    source_kind: str | None = None,
    source_id: str | None = None,
) -> str:
    """Everything needed to know what the table is, and to ask for it again."""
    moment = exported_at or datetime.now(UTC)
    payload: dict[str, Any] = {
        "exported_at": moment.isoformat(),
        "ankora_export_format": 2,
        "source_kind": source_kind,
        "source_id": source_id,
        "engine": {
            "name": campaign.engine,
            "version": campaign.engine_version,
            "backend": campaign.backend,
            "executable_sha256": campaign.executable_sha256,
            "device": campaign.device_name,
        },
        "reproducibility": {
            **campaign.reproducibility.model_dump(mode="json"),
            "note": _reproducibility_note(campaign.reproducibility),
        },
        "inputs": {
            "receptor_id": campaign.receptor_id,
            "receptor_pdbqt_sha256": campaign.receptor_sha256,
            "binding_site_id": campaign.binding_site_id,
            "search_box": campaign.box,
            "map_set_id": campaign.map_set_id,
            "map_set_identity_key": campaign.map_set_identity_key,
            "library_id": campaign.library_id,
            "filter_run_id": campaign.filter_run_id,
            "selection_manifest_sha256": campaign.selection_manifest_sha256,
        },
        "protocol": campaign.parameters,
        "counts": {
            "selected": campaign.selected_count,
            "succeeded": campaign.succeeded_count,
            "failed": campaign.failed_count,
        },
        "recorded_evidence": (evidence or _empty_evidence()).manifest_payload(),
        "scientific_notes": [
            (
                f"{campaign.value_column} is this engine's own measure. It is a "
                "computational estimate in kcal/mol, not an experimental "
                "binding affinity."
            ),
            (
                "Values from different engines are on different scales and must "
                "not be merged, averaged, or combined into a consensus score."
            ),
        ],
    }
    return json.dumps(payload, indent=2, ensure_ascii=False) + "\n"


def readme(campaign: ExportedCampaign, *, evidence: RecordedEvidence | None = None) -> str:
    """A plain-text note for whoever opens the folder without Ankora."""
    lines = [
        "Ankora campaign export",
        "=" * 22,
        "",
        f"Engine        {campaign.engine} {campaign.engine_version}",
    ]
    if campaign.device_name:
        lines.append(f"Device        {campaign.device_name}")
    recorded = evidence or _empty_evidence()
    lines += [
        f"Molecules     {campaign.selected_count} selected, "
        f"{campaign.succeeded_count} docked, {campaign.failed_count} not docked",
        "",
        "results.csv   one row per selected molecule, in the engine's own",
        "              ranking order. Molecules that could not be docked keep",
        "              their row and carry the reason.",
        "manifest.json the receptor, search space, map set, executable hash and",
        "              complete search protocol these numbers came from.",
        "campaign_bundle.zip a portable copy of these files plus every retained",
        "              interaction record and saved figure for this campaign.",
        "",
        f"M9 evidence   {len(recorded.analyses)} interaction analyses, "
        f"{len(recorded.figures)} figure records",
        "              copied as recorded; no interaction was recomputed and",
        "              no figure was redrawn for this export.",
        "",
        f"The column '{campaign.value_column}' is this engine's own measure: a",
        "computational estimate in kcal/mol, not an experimental affinity.",
        "Values from different engines sit on different scales and must not be",
        "merged or averaged into a consensus score.",
        "",
    ]
    lines.append(_reproducibility_note(campaign.reproducibility))
    return "\n".join(lines) + "\n"


def _reproducibility_note(assessment: ReproducibilityAssessment) -> str:
    if assessment.status.value == "measured_reproducible":
        return (
            f"Measured reproducible across {len(assessment.executions)} exact "
            "recorded executions: parsed scientific outputs and retained "
            "pose-artifact bytes had one output fingerprint."
        )
    if assessment.status.value == "measured_variable":
        return (
            f"Measured variable across {len(assessment.executions)} exact "
            "recorded executions: parsed scientific outputs or retained "
            "pose-artifact bytes had different output fingerprints."
        )
    return (
        "Repeat reproducibility was not assessed for this exact combination of "
        "inputs, recorded tool identity and protocol. A recorded seed is a rerun parameter, "
        "not evidence that outputs will match."
    )


# --- adapting each campaign kind ------------------------------------------


def _common_row(entry: Any, rank: int) -> dict[str, Any]:
    failure = getattr(entry, "failure", None)
    return {
        "rank": rank,
        "molecule": entry.name,
        "source_index": entry.source_index,
        "ligand_id": entry.ligand_id,
        "canonical_smiles": entry.canonical_smiles or "",
        "molecular_weight_g_mol": (
            f"{entry.molecular_weight_g_mol:.3f}"
            if entry.molecular_weight_g_mol is not None
            else ""
        ),
        "status": entry.status.value,
        "failure_code": failure.code if failure else "",
        "failure_message": failure.message if failure else "",
    }


def from_vina_batch(
    record: VinaBatchDockingRecord,
    *,
    reproducibility: ReproducibilityAssessment | None = None,
) -> ExportedCampaign:
    scored: list[tuple[float | None, Any]] = [
        (entry.poses[0].affinity_kcal_mol if entry.poses else None, entry)
        for entry in record.entries
    ]
    # Ranked by the engine's own number; molecules it could not dock keep their
    # row and sort to the end rather than disappearing from the table.
    scored.sort(key=lambda item: (item[0] is None, item[0] if item[0] is not None else 0.0))
    rows: list[dict[str, Any]] = []
    for rank, (value, entry) in enumerate(scored, start=1):
        row = _common_row(entry, rank)
        row["vina_score_kcal_mol"] = f"{value:.3f}" if value is not None else ""
        rows.append(row)
    return ExportedCampaign(
        engine=record.tool.name,
        engine_version=record.tool.version,
        backend=None,
        value_column="vina_score_kcal_mol",
        reproducibility=reproducibility or ReproducibilityAssessment(),
        receptor_id=record.request.receptor_id,
        receptor_sha256=record.receptor_sha256,
        binding_site_id=record.request.binding_site_id,
        box={},
        map_set_id=None,
        map_set_identity_key=None,
        selection_manifest_sha256=record.selection_manifest_sha256,
        library_id=record.request.library_id,
        filter_run_id=record.request.filter_run_id,
        parameters=record.request.parameters.model_dump(mode="json"),
        executable_sha256=None,
        device_name=None,
        selected_count=record.selected_count,
        succeeded_count=record.succeeded_count,
        failed_count=record.failed_count,
        rows=rows,
    )


def _autodock_rows(entries: list[Any]) -> list[dict[str, Any]]:
    scored: list[tuple[float | None, Any]] = [
        (
            min(c.lowest_binding_energy_kcal_mol for c in entry.clusters)
            if entry.clusters
            else None,
            entry,
        )
        for entry in entries
    ]
    scored.sort(key=lambda item: (item[0] is None, item[0] if item[0] is not None else 0.0))
    rows: list[dict[str, Any]] = []
    for rank, (value, entry) in enumerate(scored, start=1):
        row = _common_row(entry, rank)
        row["autodock4_binding_energy_kcal_mol"] = f"{value:.3f}" if value is not None else ""
        row["clusters"] = len(entry.clusters)
        top = next((c for c in entry.clusters if c.cluster_rank == 1), None)
        # The top-cluster population records sampling concentration within this
        # execution and must not be promoted to repeat reproducibility.
        row["top_cluster_runs"] = top.run_count if top else ""
        rows.append(row)
    return rows


def from_autodock4_batch(
    record: AutoDock4BatchRecord,
    *,
    reproducibility: ReproducibilityAssessment | None = None,
) -> ExportedCampaign:
    return ExportedCampaign(
        engine=record.autodock4.tool.name,
        engine_version=record.autodock4.tool.version,
        backend="autodock4_cpu",
        value_column="autodock4_binding_energy_kcal_mol",
        reproducibility=reproducibility or ReproducibilityAssessment(),
        receptor_id=record.receptor_id,
        receptor_sha256=None,
        binding_site_id=record.binding_site_id,
        box={},
        map_set_id=record.map_set_id,
        map_set_identity_key=record.map_set_identity_key,
        selection_manifest_sha256=record.selection_manifest_sha256,
        library_id=record.request.library_id,
        filter_run_id=record.request.filter_run_id,
        parameters=record.request.parameters.model_dump(mode="json"),
        executable_sha256=record.autodock4.sha256,
        device_name=None,
        selected_count=record.selected_count,
        succeeded_count=record.succeeded_count,
        failed_count=record.failed_count,
        rows=_autodock_rows(list(record.entries)),
    )


def from_autodock_gpu_batch(
    record: AutoDockGpuBatchRecord,
    *,
    reproducibility: ReproducibilityAssessment | None = None,
) -> ExportedCampaign:
    return ExportedCampaign(
        engine=record.autodock_gpu.tool.name,
        engine_version=record.autodock_gpu.tool.version,
        backend=record.backend.value,
        value_column="autodock4_binding_energy_kcal_mol",
        reproducibility=reproducibility or ReproducibilityAssessment(),
        receptor_id=record.receptor_id,
        receptor_sha256=None,
        binding_site_id=record.binding_site_id,
        box={},
        map_set_id=record.map_set_id,
        map_set_identity_key=record.map_set_identity_key,
        selection_manifest_sha256=record.selection_manifest_sha256,
        library_id=record.request.library_id,
        filter_run_id=record.request.filter_run_id,
        parameters=record.request.parameters.model_dump(mode="json"),
        executable_sha256=record.autodock_gpu.sha256,
        device_name=record.autodock_gpu.device_name,
        selected_count=record.selected_count,
        succeeded_count=record.succeeded_count,
        failed_count=record.failed_count,
        rows=_autodock_rows(list(record.entries)),
    )


def _sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _copy_preserved(source: Path, destination: Path) -> tuple[str, int]:
    """Copy one already-recorded file, create-only, and identify copied bytes."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    with source.open("rb") as input_stream, destination.open("xb") as output_stream:
        shutil.copyfileobj(input_stream, output_stream, length=1024 * 1024)
    return _sha256(destination), destination.stat().st_size


def _relative(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def collect_recorded_evidence(
    *, root: Path, catalog_id: str, export_directory: Path
) -> RecordedEvidence:
    """Copy existing M9 evidence for one exact catalog result into its export.

    The collector only reads immutable records and already-rendered files. A
    missing or malformed optional figure becomes an explicit warning in the
    bundle rather than causing a scientific analysis to be rerun during export.
    """
    resolved_root = root.resolve()
    destination = export_directory.resolve()
    analyses: list[dict[str, Any]] = []
    figures: list[dict[str, Any]] = []
    warnings: list[dict[str, str]] = []

    project_root = resolve_project_root(resolved_root)
    analyses_root = project_root / "analysis" / "pose_interactions"
    for source in sorted(analyses_root.glob("*/record.json")):
        identity = source.parent.name
        try:
            raw = source.read_text(encoding="utf-8")
            analysis_record = InteractionAnalysisRecord.model_validate_json(raw)
        except (OSError, ValueError) as error:
            warnings.append(
                {
                    "kind": "interaction_record_unreadable",
                    "identity": identity,
                    "reason": str(error),
                }
            )
            continue
        if analysis_record.catalog_id != catalog_id:
            continue
        if analysis_record.analysis_id != identity:
            warnings.append(
                {
                    "kind": "interaction_record_identity_mismatch",
                    "identity": identity,
                    "reason": "Folder and record identifiers do not match.",
                }
            )
            continue
        target = destination / "evidence" / "pose_interactions" / identity / "record.json"
        digest, size = _copy_preserved(source, target)
        analyses.append(
            {
                "analysis_id": analysis_record.analysis_id,
                "ligand_id": analysis_record.ligand_id,
                "pose_artifact_id": analysis_record.pose.artifact_id,
                "pose_sha256": analysis_record.pose.sha256,
                "contact_count": len(analysis_record.contacts),
                "detector": analysis_record.detector.model_dump(mode="json"),
                "profile_id": analysis_record.profile.profile_id,
                "path": _relative(target, destination),
                "sha256": digest,
                "size_bytes": size,
            }
        )

    analysis_ids = {item["analysis_id"] for item in analyses}
    figures_root = project_root / "exports" / "figures"
    for source in sorted(figures_root.glob("*/figure.json")):
        identity = source.parent.name
        try:
            raw = source.read_text(encoding="utf-8")
            figure_record = FigureManifest.model_validate_json(raw)
        except (OSError, ValueError) as error:
            warnings.append(
                {
                    "kind": "figure_record_unreadable",
                    "identity": identity,
                    "reason": str(error),
                }
            )
            continue
        if figure_record.result.catalog_id != catalog_id:
            continue
        if figure_record.figure_id != identity:
            warnings.append(
                {
                    "kind": "figure_record_identity_mismatch",
                    "identity": identity,
                    "reason": "Folder and record identifiers do not match.",
                }
            )
            continue

        record_target = destination / "evidence" / "figures" / identity / "figure.json"
        record_digest, record_size = _copy_preserved(source, record_target)
        included_files: list[dict[str, Any]] = []
        unavailable_files: list[dict[str, str]] = []
        # The earliest in-project M9 records predate the explicit path fields;
        # their rendered files are beside figure.json. Do not invent a missing
        # external location, but do retain bytes that are still in the record.
        written_to = (
            Path(figure_record.written_to)
            if figure_record.written_to is not None
            else source.parent
        )
        for item in figure_record.files:
            if Path(item.filename).name != item.filename or not written_to.is_absolute():
                unavailable_files.append(
                    {
                        "filename": item.filename,
                        "reason": "The recorded figure path is not a safe absolute file path.",
                    }
                )
                continue
            figure_source = (written_to / item.filename).resolve()
            try:
                actual_size = figure_source.stat().st_size
            except OSError:
                unavailable_files.append(
                    {
                        "filename": item.filename,
                        "reason": "The already-rendered figure is no longer available.",
                    }
                )
                continue
            if actual_size != item.size_bytes:
                unavailable_files.append(
                    {
                        "filename": item.filename,
                        "reason": "The figure size no longer matches its recorded manifest.",
                    }
                )
                continue
            file_target = destination / "evidence" / "figures" / identity / item.filename
            digest, size = _copy_preserved(figure_source, file_target)
            included_files.append(
                {
                    **item.model_dump(mode="json"),
                    "path": _relative(file_target, destination),
                    "sha256": digest,
                    "size_bytes": size,
                }
            )

        analysis_id = figure_record.result.interaction_analysis_id
        figures.append(
            {
                "figure_id": figure_record.figure_id,
                "source": figure_record.source.value,
                "ligand_id": figure_record.result.ligand_id,
                "pose_artifact_id": figure_record.result.pose_artifact_id,
                "pose_label": figure_record.result.pose,
                "interaction_analysis_id": analysis_id,
                "interaction_record_included": (analysis_id is None or analysis_id in analysis_ids),
                "record_path": _relative(record_target, destination),
                "record_sha256": record_digest,
                "record_size_bytes": record_size,
                "files": included_files,
                "unavailable_files": unavailable_files,
            }
        )

    return RecordedEvidence(
        analyses=sorted(analyses, key=lambda item: str(item["analysis_id"])),
        figures=sorted(figures, key=lambda item: str(item["figure_id"])),
        collection_warnings=warnings,
    )


def _write_portable_bundle(directory: Path) -> Path:
    """Zip the complete folder without ever adding the ZIP to itself."""
    target = directory / "campaign_bundle.zip"
    with zipfile.ZipFile(
        target, mode="x", compression=zipfile.ZIP_DEFLATED, compresslevel=9
    ) as archive:
        for source in sorted(directory.rglob("*")):
            if source.is_file() and source != target:
                archive.write(source, source.relative_to(directory).as_posix())
    return target


class CampaignExportService:
    """Write an export bundle into the project, as a preserved artifact.

    The bundle is not handed straight to a download: it is written where every
    other Ankora artifact lives, so an export is itself something that happened
    and can be found again.
    """

    def __init__(
        self,
        *,
        root: Path,
        docking_store: DockingArtifactStore,
        autodock4_store: AutoDock4JobStore,
        autodock_gpu_store: AutoDockGpuJobStore,
        binding_site_store: BindingSiteArtifactStore,
    ) -> None:
        self._root = root.resolve()
        self._project_root = resolve_project_root(self._root)
        self._docking_store = docking_store
        self._autodock4_store = autodock4_store
        self._autodock_gpu_store = autodock_gpu_store
        self._binding_site_store = binding_site_store
        self._reproducibility = ReproducibilityService(
            docking_store=docking_store,
            autodock4_store=autodock4_store,
            autodock_gpu_store=autodock_gpu_store,
        )

    @classmethod
    def from_environment(cls) -> "CampaignExportService":
        configured = os.getenv("ANKORA_DATA_DIR")
        root = Path(configured) if configured else Path.cwd() / ".ankora-data"
        return cls(
            root=root,
            docking_store=DockingArtifactStore.from_environment(),
            autodock4_store=AutoDock4JobStore.from_environment(),
            autodock_gpu_store=AutoDockGpuJobStore.from_environment(),
            binding_site_store=BindingSiteArtifactStore.from_environment(),
        )

    def export_campaign(
        self, *, source_kind: str, batch_id: str, destination: str | None = None
    ) -> dict[str, Any]:
        campaign = self._load(source_kind, batch_id)
        campaign = replace(
            campaign,
            reproducibility=self._reproducibility.assessment(f"{source_kind}:{batch_id}"),
        )
        campaign = self._with_box(campaign)
        export_id = str(uuid4())
        directory = self._export_dir(export_id)
        directory.mkdir(parents=True, exist_ok=False)
        exported_at = datetime.now(UTC)
        evidence = collect_recorded_evidence(
            root=self._root,
            catalog_id=f"{source_kind}:{batch_id}",
            export_directory=directory,
        )

        files = {
            "results.csv": results_csv(campaign),
            "manifest.json": manifest(
                campaign,
                exported_at=exported_at,
                evidence=evidence,
                source_kind=source_kind,
                source_id=batch_id,
            ),
            "README.txt": readme(campaign, evidence=evidence),
        }
        # The Methods section this campaign's own records support. Rendered
        # here rather than left for the author to reconstruct from the
        # manifest, and omitted rather than faked if it cannot be produced.
        methods = _methods_markdown(source_kind, batch_id)
        if methods is not None:
            files["methods.md"] = methods
        for name, content in files.items():
            with (directory / name).open("x", encoding="utf-8", newline="\n") as stream:
                stream.write(content)
        portable = _write_portable_bundle(directory)

        # The bundle is assembled in the project first, so the record and the
        # files it serves back exist whatever happens next; a chosen folder
        # then receives a complete copy under a name that says what it is.
        chosen = validated_destination(destination, stage=_STAGE, prefix="EXPORT")
        written_to = directory
        if chosen is not None:
            written_to = free_directory(chosen, _bundle_name(campaign, exported_at))
            shutil.copytree(directory, written_to)

        return {
            "export_id": export_id,
            "exported_at": exported_at,
            "source_kind": source_kind,
            "source_id": batch_id,
            "engine": campaign.engine,
            "engine_version": campaign.engine_version,
            "reproducibility": campaign.reproducibility.model_dump(mode="json"),
            "row_count": len(campaign.rows),
            "interaction_analysis_count": len(evidence.analyses),
            "figure_count": len(evidence.figures),
            "directory": str(written_to),
            "outside_project": chosen is not None,
            "record_directory": str(directory),
            "files": sorted([*files, portable.name]),
        }

    def file_path(self, export_id: str, filename: str) -> Path:
        if filename not in {
            "results.csv",
            "methods.md",
            "manifest.json",
            "README.txt",
            "campaign_bundle.zip",
        }:
            raise self._not_found(export_id, filename)
        path = self._export_dir(export_id) / filename
        if not path.is_file():
            raise self._not_found(export_id, filename)
        return path

    def _load(self, source_kind: str, batch_id: str) -> ExportedCampaign:
        if source_kind == "vina_batch":
            return from_vina_batch(self._docking_store.load_batch_record(batch_id))
        if source_kind == "autodock4_batch":
            return from_autodock4_batch(self._autodock4_store.load_batch(batch_id))
        if source_kind == "autodock_gpu_batch":
            return from_autodock_gpu_batch(self._autodock_gpu_store.load_batch(batch_id))
        raise AnkoraDomainError(
            code="EXPORT_SOURCE_UNKNOWN",
            stage=_STAGE,
            message="Ankora does not know how to export this kind of result.",
            status_code=422,
            details={"source_kind": source_kind},
        )

    def _with_box(self, campaign: ExportedCampaign) -> ExportedCampaign:
        """The search space belongs in the manifest, not only its identifier."""
        try:
            site = self._binding_site_store.load_record(campaign.binding_site_id)
        except AnkoraDomainError:
            return campaign
        return replace(campaign, box=site.box.model_dump(mode="json"))

    def _export_dir(self, export_id: str) -> Path:
        try:
            normalized = str(UUID(export_id))
        except ValueError as error:
            raise self._not_found(export_id, None) from error
        resolved = (self._project_root / "exports" / normalized).resolve()
        if self._root not in resolved.parents:
            raise self._not_found(export_id, None)
        return resolved

    @staticmethod
    def _not_found(export_id: str, filename: str | None) -> AnkoraDomainError:
        return AnkoraDomainError(
            code="EXPORT_NOT_FOUND",
            stage=_STAGE,
            message="No export artifact exists for this identifier.",
            status_code=404,
            details={"export_id": export_id, "filename": filename},
        )


def _bundle_name(campaign: ExportedCampaign, exported_at: datetime) -> str:
    """`Ankora_AutoDock-GPU_1.6_20260828-2311` - readable beside a manuscript.

    A folder called after a UUID says nothing about which campaign it holds,
    and the scientist is about to file it next to a paper.
    """
    parts = [
        "Ankora",
        slug(campaign.engine),
        slug(campaign.engine_version),
        exported_at.strftime("%Y%m%d-%H%M%S"),
    ]
    return "_".join(part for part in parts if part)


def _methods_markdown(source_kind: str, batch_id: str) -> str | None:
    """The campaign's Methods section, or nothing if it cannot be rendered.

    Imported inside the function: the renderer reaches into every store the
    campaign touched, and an export must not fail because one of those records
    has been removed since.
    """
    from ankora_backend.services.methods_report import MethodsReportService

    try:
        report = MethodsReportService.from_environment().render(f"{source_kind}:{batch_id}")
    except (AnkoraDomainError, OSError, ValueError):
        return None
    return report.markdown
