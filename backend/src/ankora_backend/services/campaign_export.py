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

A single GNINA job is exported through the same endpoint and the same response
contract, but it is **not** described as a screening library. It has one
ligand and N poses, so its table is one row per pose and the library-shaped
columns are absent rather than filled with blanks: an empty `library_id` or
`canonical_smiles` column invites a reader to concatenate a single job with a
screening table, which is the merge this format exists to prevent. Its three
score axes stay three columns, in the engine's own descending CNN order.

A multi-ligand GNINA screening campaign (`gnina_screening`) is exported as one
row per selected molecule: docked molecules are ranked by descending top-pose
`gnina_cnn_score` (ties broken by applied selection order), undocked preflight
or engine failures stay in the table unranked in selection order, and the three
GNINA axes remain three separate columns alongside the verified pinned
selection manifest, campaign records and per-molecule child job artifacts.
"""

import csv
import io
import json
import math
import os
import shutil
import zipfile
from contextlib import suppress
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from ankora_backend.adapters.engines.gnina import pair_gnina_flex_models, parse_gnina_pdbqt
from ankora_backend.domain.errors import AnkoraDomainError
from ankora_backend.domain.project_context import resolve_project_root
from ankora_backend.persistence.analog_expansion_store import AnalogExpansionStore
from ankora_backend.persistence.autodock4_store import AutoDock4JobStore
from ankora_backend.persistence.autodock_gpu_store import AutoDockGpuJobStore
from ankora_backend.persistence.binding_site_store import BindingSiteArtifactStore
from ankora_backend.persistence.docking_store import DockingArtifactStore
from ankora_backend.persistence.gnina_screening_store import GninaScreeningStore
from ankora_backend.persistence.gnina_store import GninaJobStore
from ankora_backend.persistence.ligand_store import LigandArtifactStore
from ankora_backend.schemas.analog_expansion import (
    AnalogSearchRecord,
    AnalogSelectionRecord,
)
from ankora_backend.schemas.autodock4 import AutoDock4BatchRecord
from ankora_backend.schemas.autodock_gpu import AutoDockGpuBatchRecord
from ankora_backend.schemas.binding_sites import BindingSiteRecord, BindingSiteSource
from ankora_backend.schemas.docking import DockingJobStatus, VinaBatchDockingRecord
from ankora_backend.schemas.figures import FigureManifest
from ankora_backend.schemas.gnina import GninaJobRecord
from ankora_backend.schemas.gnina_screening import (
    GninaScreeningCampaignRecord,
    GninaScreeningEntry,
)
from ankora_backend.schemas.interaction_rules import (
    InteractionRuleEvaluationRecord,
    InteractionRuleSetRecord,
)
from ankora_backend.schemas.ligands import LigandSource
from ankora_backend.schemas.pose_interactions import InteractionAnalysisRecord
from ankora_backend.schemas.pose_quality import PoseQualityRecord
from ankora_backend.schemas.receptors import ReceptorFlexMode
from ankora_backend.schemas.redocking import RedockingRunRecord
from ankora_backend.schemas.results_catalog import ReproducibilityAssessment
from ankora_backend.services.export_destinations import (
    free_directory,
    slug,
    validated_destination,
)
from ankora_backend.services.gnina_screening_evidence import verified_campaign_entry_job
from ankora_backend.services.gnina_screening_selection import verified_screening_selection
from ankora_backend.services.project_dependencies import (
    ArtifactFreshness,
    ProjectDependencyService,
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

# A single job's table is about poses of one ligand, so it shares no column
# with a screening table beyond the rank. The three GNINA axes are three
# separate columns, each named with its own unit.
_HEADER_GNINA_POSES = [
    "rank",
    "mode",
    "ligand_id",
    "gnina_cnn_score",
    "gnina_cnn_affinity_pk",
    "gnina_cnn_vs",
    "gnina_cnn_vs_source",
    "gnina_cnn_affinity_variance",
    "gnina_minimized_affinity_kcal_mol",
    "pose_artifact_id",
    "pose_filename",
    "pose_sha256",
]

# A multi-ligand GNINA screening campaign keeps every selected molecule in one
# library table while preserving GNINA axes separately alongside the verified
# top-pose artifact and linked child job identity.
_HEADER_GNINA_SCREENING = [
    *_HEADER_COMMON,
    "gnina_cnn_score",
    "gnina_cnn_affinity_pk",
    "gnina_cnn_vs",
    "gnina_cnn_vs_source",
    "gnina_cnn_affinity_variance",
    "gnina_minimized_affinity_kcal_mol",
    "top_pose_artifact_id",
    "top_pose_sha256",
    "gnina_job_id",
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
    parameters: dict[str, Any]
    executable_sha256: str | None
    device_name: str | None
    rows: list[dict[str, Any]]
    # A screening campaign selected molecules from a filtered library and its
    # table has one row per molecule. A single job has none of those things,
    # and inventing an identifier or a zeroed count for it would describe a
    # library that was never assembled. `None` means absent from the export,
    # not empty.
    selection_manifest_sha256: str | None = None
    library_id: str | None = None
    filter_run_id: str | None = None
    selected_count: int | None = None
    succeeded_count: int | None = None
    failed_count: int | None = None
    canceled_count: int | None = None
    campaign_status: str | None = None
    # One row per pose of one ligand rather than one row per molecule. The
    # table shape is a property of what was run, so it travels with the data
    # instead of being re-derived from the engine name.
    row_kind: str = "molecule"
    pose_count: int | None = None
    ligand_id: str | None = None
    ranking_metric: str | None = None
    cnn_model_identity: dict[str, Any] | None = None
    warnings: list[dict[str, Any]] = field(default_factory=list)
    receptor_flex_mode: str | None = None
    receptor_flex_sha256: str | None = None
    flex_residues: list[dict[str, Any]] = field(default_factory=list)
    flex_atom_types: list[str] = field(default_factory=list)
    dependency_freshness: ArtifactFreshness | None = None


@dataclass(frozen=True, slots=True)
class RecordedEvidence:
    """M9 and v0.2 records copied into one campaign bundle without recomputation."""

    analyses: list[dict[str, Any]]
    figures: list[dict[str, Any]]
    collection_warnings: list[dict[str, str]]
    validations: list[dict[str, Any]] = field(default_factory=list)
    pose_quality_assessments: list[dict[str, Any]] = field(default_factory=list)
    interaction_rule_evaluations: list[dict[str, Any]] = field(default_factory=list)
    interaction_rule_sets: list[dict[str, Any]] = field(default_factory=list)
    analog_expansion_artifacts: list[dict[str, Any]] = field(default_factory=list)
    analog_expansion_provenance: dict[str, Any] | None = None

    @property
    def has_v02_evidence(self) -> bool:
        return bool(
            self.pose_quality_assessments
            or self.interaction_rule_evaluations
            or self.interaction_rule_sets
        )

    @property
    def has_analog_expansion_evidence(self) -> bool:
        return bool(self.analog_expansion_artifacts and self.analog_expansion_provenance)

    def manifest_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "pose_interaction_analyses": self.analyses,
            "figures": self.figures,
            "redocking_validations": self.validations,
            "collection_warnings": self.collection_warnings,
            "notes": [
                "These files are copies of records and rendered figures that "
                "already existed when this campaign was exported.",
                "No interaction was recomputed, no figure was redrawn and no "
                "RMSD was recalculated for this bundle.",
                "Interaction contacts describe geometric criteria on one exact "
                "pose; they are not measured affinity or biological proof.",
                "A redocking verdict concerns one configuration on one reference "
                "system and is not validation of the engine in general.",
            ],
        }
        if self.has_v02_evidence:
            payload["pose_quality_assessments"] = self.pose_quality_assessments
            payload["interaction_rule_evaluations"] = self.interaction_rule_evaluations
            payload["interaction_rule_sets"] = self.interaction_rule_sets
            payload["notes"].append(
                "PoseBusters physical quality assessments, MMFF94s conformational strain "
                "diagnostics, and declarative ProLIF pharmacophoric rule evaluations were "
                "copied verbatim from immutable v0.2 records without recomputation."
            )
        if self.has_analog_expansion_evidence:
            payload["analog_expansion_artifacts"] = self.analog_expansion_artifacts
            payload["notes"].append(
                "ADR-033 Hit-to-Analog similarity search, human curation selection, optional "
                "raw external provider responses, and POSE_FOCUSED binding-site records were "
                "copied verbatim without recomputation."
            )
        return payload


def _empty_evidence() -> RecordedEvidence:
    return RecordedEvidence(analyses=[], figures=[], collection_warnings=[], validations=[])


@dataclass(frozen=True, slots=True)
class CampaignBundleIdentity:
    """Human-visible and machine-verifiable identity of one export event."""

    export_id: str
    catalog_id: str
    display_name: str | None
    input_identity_sha256: str
    bundle_identity_sha256: str
    archive_filename: str

    def manifest_payload(self) -> dict[str, str | None]:
        return {
            "export_id": self.export_id,
            "catalog_id": self.catalog_id,
            "display_name": self.display_name,
            "input_identity_sha256": self.input_identity_sha256,
            "bundle_identity_sha256": self.bundle_identity_sha256,
            "archive_filename": self.archive_filename,
        }


def _table_columns(campaign: ExportedCampaign) -> list[str]:
    if campaign.row_kind == "pose":
        return list(_HEADER_GNINA_POSES)
    if campaign.engine == "GNINA":
        return list(_HEADER_GNINA_SCREENING)
    columns = [*_HEADER_COMMON, campaign.value_column]
    if campaign.engine != "AutoDock Vina":
        # Cluster population describes sampling concentration within this
        # execution; it is not evidence that a separate execution will match.
        columns += ["clusters", "top_cluster_runs"]
    return columns


def results_csv(campaign: ExportedCampaign) -> str:
    """One row per selected molecule, in the engine's own ranking order.

    Molecules the engine could not dock keep their row and carry the reason, so
    the table describes the selection rather than only its successes.

    A single job's table is one row per pose instead, and carries none of the
    library columns: it is a different kind of table and says so in its header.
    """
    columns = _table_columns(campaign)
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
    bundle_identity: CampaignBundleIdentity | None = None,
    source_files: list[dict[str, Any]] | None = None,
    bundle_files: list[dict[str, Any]] | None = None,
) -> str:
    """Everything needed to know what the table is, and to ask for it again."""
    moment = exported_at or datetime.now(UTC)
    table_payload: dict[str, Any] = {
        "file": "results.csv",
        "row": campaign.row_kind,
        "columns": _table_columns(campaign),
    }
    if campaign.ranking_metric is not None:
        table_payload["ranking_metric"] = campaign.ranking_metric
    engine_payload: dict[str, Any] = {
        "name": campaign.engine,
        "version": campaign.engine_version,
        "backend": campaign.backend,
        "executable_sha256": campaign.executable_sha256,
        "device": campaign.device_name,
    }
    if campaign.cnn_model_identity is not None:
        engine_payload["cnn_model_identity"] = campaign.cnn_model_identity
    resolved_evidence = evidence or _empty_evidence()
    has_analog_expansion = resolved_evidence.has_analog_expansion_evidence
    has_v02_features = (
        campaign.receptor_flex_mode == ReceptorFlexMode.SIDECHAIN_FLEX.value
        or resolved_evidence.has_v02_evidence
        or has_analog_expansion
    )
    export_format = (
        (6 if has_analog_expansion else (5 if has_v02_features else 4))
        if bundle_identity is not None
        else 2
    )
    payload: dict[str, Any] = {
        "exported_at": moment.isoformat(),
        "ankora_export_format": export_format,
        "source_kind": source_kind,
        "source_id": source_id,
        "engine": engine_payload,
        "reproducibility": {
            **campaign.reproducibility.model_dump(mode="json"),
            "note": _reproducibility_note(campaign.reproducibility),
        },
        "inputs": _campaign_inputs(campaign),
        "protocol": campaign.parameters,
        "counts": _campaign_counts(campaign),
        "table": table_payload,
        "recorded_evidence": resolved_evidence.manifest_payload(),
        "scientific_notes": _scientific_notes(campaign),
    }
    if export_format >= 5:
        payload["v02_provenance"] = {
            "receptor_flex_mode": campaign.receptor_flex_mode or ReceptorFlexMode.RIGID.value,
            "flex_residue_count": len(campaign.flex_residues),
            "pose_quality_assessment_count": len(resolved_evidence.pose_quality_assessments),
            "interaction_rule_evaluation_count": len(
                resolved_evidence.interaction_rule_evaluations
            ),
            "interaction_rule_set_count": len(resolved_evidence.interaction_rule_sets),
        }
    if export_format >= 6 and resolved_evidence.analog_expansion_provenance is not None:
        payload["analog_expansion_provenance"] = resolved_evidence.analog_expansion_provenance
    warnings_list = list(campaign.warnings)
    if campaign.dependency_freshness is not None:
        payload["dependency_freshness"] = campaign.dependency_freshness.to_dict()
        if campaign.dependency_freshness.stale:
            warnings_list.append(
                {
                    "code": "STALE_SOURCE_ARTIFACT",
                    "stage": _STAGE,
                    "message": (
                        "This exported campaign was marked stale at export time (ADR-011) "
                        "and must not be presented as current."
                    ),
                    "details": campaign.dependency_freshness.to_dict(),
                }
            )
    if warnings_list:
        payload["warnings"] = warnings_list
    if bundle_identity is not None:
        payload["bundle"] = bundle_identity.manifest_payload()
    if bundle_files:
        payload["bundle_files"] = bundle_files
    if source_files:
        if source_kind == "gnina_screening":
            source_notes = [
                "These are copies of the exact bytes preserved by the "
                "screening campaign, its pinned applied selection manifest, "
                "and each attempted molecule's GNINA child job. Nothing was "
                "reparsed, reformatted or regenerated.",
                "`integrity` says what each hash establishes. "
                "`matches_recorded_sha256` means the campaign or child job "
                "recorded a SHA-256 for that file before this export and "
                "the copied bytes still match it. "
                "`export_time_digest_only` means no hash was recorded at "
                "run time, so the digest identifies the copy in this bundle "
                "and is not evidence of a check made at run time.",
                "Per-molecule raw GNINA outputs, captured logs and child "
                "job records live under `jobs/<gnina_job_id>/` and can be "
                "compared against each child job's recorded execution and "
                "published poses.",
            ]
        elif source_kind == "gnina_job":
            source_notes = [
                "These are copies of the exact bytes the job preserved. "
                "Nothing was reparsed, reformatted or regenerated.",
                "`integrity` says what each hash establishes. "
                "`matches_recorded_sha256` means the job recorded a SHA-256 "
                "for that file before this export and the copied bytes still "
                "match it. `export_time_digest_only` means the job records no "
                "hash for that file, so the digest identifies the copy in this "
                "bundle and is not evidence of a check made at run time.",
                "The raw engine output and captured logs are in the second "
                "group. Their content can be compared against the stdout, "
                "stderr and per-pose scores retained inside record.json.",
            ]
        else:
            source_notes = [
                "These are copies of the exact flexible side-chain pose "
                "artifacts preserved by this sidechain_flex campaign. "
                "Nothing was reparsed, reformatted or regenerated.",
                "`matches_recorded_sha256` means the batch record held a "
                "SHA-256 for that moved side-chain file before this export "
                "and the copied bytes still match it.",
            ]
        payload["source_files"] = {
            "files": source_files,
            "notes": source_notes,
        }
    return json.dumps(payload, indent=2, ensure_ascii=False) + "\n"


def _campaign_counts(campaign: ExportedCampaign) -> dict[str, Any]:
    """What was counted, without inventing a selection that never existed."""
    if campaign.row_kind == "pose":
        return {"ligands": 1, "poses": campaign.pose_count}
    counts: dict[str, Any] = {
        "selected": campaign.selected_count,
        "succeeded": campaign.succeeded_count,
        "failed": campaign.failed_count,
    }
    if campaign.canceled_count:
        counts["canceled"] = campaign.canceled_count
    if campaign.campaign_status == "canceled":
        counts["status"] = "canceled"
    return counts


def _gnina_ensemble_and_refinement_notes(campaign: ExportedCampaign) -> list[str]:
    extra: list[str] = []
    if campaign.cnn_model_identity is not None:
        members = list(campaign.cnn_model_identity.get("member_names") or [])
        if len(members) > 1:
            selector = campaign.cnn_model_identity.get("selector")
            cli_arg = campaign.cnn_model_identity.get("cli_argument")
            cli_clause = "omitting --cnn" if cli_arg is None else f"--cnn {cli_arg}"
            extra.append(
                f"CNN ensemble identity: selector '{selector}' ({cli_clause}) "
                f"evaluated {len(members)} built-in networks ({', '.join(members)})."
            )
    if campaign.parameters.get("cnn_scoring") == "refinement":
        extra.append(
            "Under cnn_scoring='refinement' (--cnn_mix_emp_force disabled), GNINA "
            "locally optimized pose coordinates against 3D CNN gradients after "
            "empirical Monte Carlo sampling. gnina_minimized_affinity_kcal_mol was "
            "evaluated on that CNN-refined geometry (where closer CNN-favored "
            "contacts can produce elevated or positive steric repulsion energies in "
            "kcal/mol) and is not an independent empirical energy check."
        )
    return extra


def _flexibility_notes(campaign: ExportedCampaign) -> list[str]:
    notes: list[str] = []
    if campaign.receptor_flex_mode == ReceptorFlexMode.SIDECHAIN_FLEX.value:
        labels = [
            f"{str(item.get('residue_name', '')).upper()} "
            f"{item.get('chain_id', '')}:{item.get('sequence_number', '')}"
            f"{item.get('insertion_code', '')}"
            for item in campaign.flex_residues
        ]
        residue_clause = f" ({', '.join(labels)})" if labels else ""
        notes.append(
            f"Receptor side-chain flexibility (`sidechain_flex`) was enabled for "
            f"{len(labels)} selected residue{'s' if len(labels) != 1 else ''}"
            f"{residue_clause}; backbone coordinates and all non-selected residues "
            "remained rigid, and moved side-chain artifacts are preserved beside each pose."
        )
    if campaign.engine == "AutoDock Vina" and campaign.parameters.get("scoring") == "vinardo":
        notes.append(
            "Vina evaluated the Vinardo empirical scoring function (--scoring vinardo) "
            "rather than the default Vina function; Vinardo scores are not interchangeable "
            "with default Vina scores."
        )
    return notes


def _scientific_notes(campaign: ExportedCampaign) -> list[str]:
    if campaign.row_kind == "pose":
        return [
            (
                "gnina_cnn_score is dimensionless, bounded between 0 and 1, and "
                "is the order GNINA ranked these poses in. It is not an energy "
                "and has no kcal/mol interpretation."
            ),
            (
                "gnina_cnn_affinity_pk is a predicted affinity in pK units, "
                "where higher indicates stronger predicted binding."
            ),
            (
                "gnina_cnn_vs is CNNscore * CNNaffinity (recorded with "
                "gnina_cnn_vs_source and blank on pre-ADR-028 records), while "
                "gnina_cnn_affinity_variance is populated only when emitted by "
                "the GNINA binary and left blank otherwise. Within-ligand poses "
                "remain ordered by descending gnina_cnn_score."
            ),
            (
                "gnina_minimized_affinity_kcal_mol is the minimized affinity "
                "from GNINA's empirical scoring function, in kcal/mol. GNINA "
                "did not rank by it, so the top-ranked pose is not necessarily "
                "the one with the lowest recorded energy."
            ),
            *_gnina_ensemble_and_refinement_notes(campaign),
            *_flexibility_notes(campaign),
            (
                "All of these GNINA quantities are predictions of this engine "
                "for this pose. None is an experimentally measured binding "
                "affinity and none is evidence of biological activity."
            ),
            (
                "None of these values shares a scale with a Vina score or an "
                "AutoDock4 binding energy. They must not be merged, averaged, "
                "or combined into a consensus score."
            ),
            (
                "This bundle is one docking job for one ligand. It is not a "
                "screening library and carries no library, filter-run or "
                "selection identity."
            ),
        ]
    if campaign.engine == "GNINA":
        ranked_by_cnn_vs = campaign.ranking_metric == "gnina_cnn_vs"
        notes = [
            (
                "gnina_cnn_score is dimensionless, bounded between 0 and 1, and "
                + (
                    "orders poses within each individual ligand job; for this "
                    "campaign, between-molecule hit order is set by descending "
                    "top-pose gnina_cnn_vs (CNNscore * CNNaffinity), with exact "
                    "ties broken by applied selection order. "
                    if ranked_by_cnn_vs
                    else "is the primary order in which docked molecules are ranked here "
                    "(descending top-pose CNNscore, with exact ties broken by "
                    "applied selection order). "
                )
                + "It is not an energy and has no kcal/mol interpretation."
            ),
            (
                "gnina_cnn_affinity_pk is the top pose's predicted affinity in "
                "pK units, where higher indicates stronger predicted binding."
            ),
            (
                "gnina_cnn_vs is the top pose's virtual-screening score "
                "(CNNscore * CNNaffinity, recorded with gnina_cnn_vs_source and "
                "blank on pre-ADR-028 records); gnina_cnn_affinity_variance is "
                "populated only when emitted by the GNINA binary and left blank "
                "otherwise."
            ),
            (
                "gnina_minimized_affinity_kcal_mol is the top pose's minimized "
                "affinity from GNINA's empirical scoring function, in kcal/mol. "
                "GNINA did not rank poses or molecules by it, so the top-ranked "
                "molecule is not necessarily the one with the lowest recorded "
                "energy."
            ),
            (
                "All of these GNINA quantities are computational predictions of "
                "this engine. None is an experimentally measured binding affinity "
                "and none is evidence of biological activity."
            ),
            (
                "None of these values shares a scale with a Vina score or an "
                "AutoDock4 binding energy. They must not be merged, averaged, "
                "or combined into a consensus score."
            ),
            (
                "Every selected molecule stays in results.csv; molecules "
                "refused at preflight or failed during execution follow "
                "unranked in selection order with blank score columns and their "
                "recorded failure codes."
            ),
            *_gnina_ensemble_and_refinement_notes(campaign),
            *_flexibility_notes(campaign),
        ]
        for warning in campaign.warnings:
            if warning.get("code") == "GNINA_CNN_VS_NONPOSITIVE_AFFINITY":
                notes.append(
                    "Warning (GNINA_CNN_VS_NONPOSITIVE_AFFINITY): one or more "
                    "completed molecules recorded non-positive predicted "
                    "CNNaffinity (<= 0 pK, K_d >= 1 M), where CNN_VS = "
                    "CNNscore * CNNaffinity becomes zero or negative and inverts "
                    "CNNscore monotonicity among negative-pK decoys."
                )
                break
        return notes
    return [
        (
            f"{campaign.value_column} is this engine's own measure. It is a "
            "computational estimate in kcal/mol, not an experimental "
            "binding affinity."
        ),
        (
            "Values from different engines are on different scales and must "
            "not be merged, averaged, or combined into a consensus score."
        ),
        *_flexibility_notes(campaign),
    ]


def readme(
    campaign: ExportedCampaign,
    *,
    evidence: RecordedEvidence | None = None,
    exported_at: datetime | None = None,
    bundle_identity: CampaignBundleIdentity | None = None,
) -> str:
    """A plain-text note for whoever opens the folder without Ankora."""
    lines = [
        "Ankora campaign export",
        "=" * 22,
        "",
    ]
    if campaign.dependency_freshness is not None and campaign.dependency_freshness.stale:
        reasons_text = (
            "; ".join(campaign.dependency_freshness.stale_reasons)
            or "upstream artifact modified"
        )
        lines += [
            "WARNING: STALE ARTIFACT (ADR-011)",
            "-" * 33,
            "This exported campaign was marked STALE at export time and must not",
            "be presented as current.",
            f"Reasons: {reasons_text}",
            "",
        ]
    lines.append(f"Engine        {campaign.engine} {campaign.engine_version}")
    if campaign.device_name:
        lines.append(f"Device        {campaign.device_name}")
    if campaign.cnn_model_identity is not None:
        members = list(campaign.cnn_model_identity.get("member_names") or [])
        if len(members) > 1:
            lines.append(
                f"CNN ensemble  {campaign.cnn_model_identity.get('selector')} "
                f"({', '.join(members)})"
            )
    if campaign.receptor_flex_mode == ReceptorFlexMode.SIDECHAIN_FLEX.value:
        labels = [
            f"{str(item.get('residue_name', '')).upper()} "
            f"{item.get('chain_id', '')}:{item.get('sequence_number', '')}"
            f"{item.get('insertion_code', '')}"
            for item in campaign.flex_residues
        ]
        lines.append(
            f"FlexRes       sidechain_flex ({', '.join(labels) if labels else 'recorded'})"
        )
    if bundle_identity is not None:
        lines += [
            f"Name          {bundle_identity.display_name or '(not assigned)'}",
            f"Campaign      {bundle_identity.catalog_id}",
            f"Exported      {(exported_at or datetime.now(UTC)).isoformat()}",
            f"Inputs SHA-256 {bundle_identity.input_identity_sha256}",
            f"Bundle identity SHA-256 {bundle_identity.bundle_identity_sha256}",
            f"Archive       {bundle_identity.archive_filename}",
        ]
    recorded = evidence or _empty_evidence()
    if campaign.row_kind == "pose":
        lines += [
            f"Ligand        1 ligand, {campaign.pose_count} poses",
            "",
            "results.csv   one row per pose, in the engine's own ranking order,",
            "              which is descending CNN pose score. This is one",
            "              docking job, not a screening library: it carries no",
            "              library, filter-run or selection identity.",
        ]
    else:
        lines += [
            f"Molecules     {campaign.selected_count} selected, "
            f"{campaign.succeeded_count} docked, {campaign.failed_count} not docked",
            "",
            "results.csv   one row per selected molecule, in the engine's own",
            "              ranking order. Molecules that could not be docked keep",
            "              their row and carry the reason.",
        ]
    lines += [
        "manifest.json the receptor, search space, map set, executable hash and",
        "              complete search protocol these numbers came from.",
        f"{(bundle_identity.archive_filename if bundle_identity else 'campaign_bundle.zip')} ",
        "              is a portable copy of these files plus every retained",
        "              interaction record and saved figure for this campaign.",
        "",
        f"M9 evidence   {len(recorded.analyses)} interaction analyses, "
        f"{len(recorded.figures)} figure records, "
        f"{len(recorded.validations)} redocking verdicts",
        "              copied as recorded; no interaction was recomputed, no",
        "              figure was redrawn and no RMSD was recalculated for",
        "              this export.",
        "",
    ]
    if campaign.row_kind == "pose":
        lines += [
            "The GNINA score columns represent distinct quantities and are not",
            "interchangeable: gnina_cnn_score is dimensionless (0-1) and is the",
            "order GNINA ranked by; gnina_cnn_affinity_pk is a predicted pK;",
            "gnina_cnn_vs is CNNscore * CNNaffinity (with gnina_cnn_vs_source);",
            "gnina_minimized_affinity_kcal_mol is in kcal/mol and did not set",
            "the ranking, so the top pose need not have the lowest energy.",
            "All of these are predictions of this engine for this pose. None is",
            "an experimentally measured affinity, and none shares a scale with a",
            "Vina score or an AutoDock4 binding energy.",
            "",
        ]
        if campaign.parameters.get("cnn_scoring") == "refinement":
            lines += [
                "Refinement note: pose coordinates were locally optimized against",
                "3D CNN gradients (cnn_scoring='refinement', --cnn_mix_emp_force",
                "disabled), so gnina_minimized_affinity_kcal_mol was evaluated on",
                "CNN-refined geometry and is not an independent empirical energy",
                "check.",
                "",
            ]
    elif campaign.engine == "GNINA":
        ranking_clause = (
            "while between-molecule ranking is set by descending gnina_cnn_vs "
            "(CNNscore * CNNaffinity, ties broken by selection order);"
            if campaign.ranking_metric == "gnina_cnn_vs"
            else "and sets the descending molecule ranking (ties broken by selection order);"
        )
        lines += [
            "The GNINA score columns represent distinct quantities and are not",
            "interchangeable: gnina_cnn_score is dimensionless (0-1)",
            f"{ranking_clause}",
            "gnina_cnn_affinity_pk is the top pose's predicted pK; gnina_cnn_vs",
            "is CNNscore * CNNaffinity (with gnina_cnn_vs_source);",
            "gnina_minimized_affinity_kcal_mol is in kcal/mol and did not set",
            "the ranking, so the top-ranked molecule need not have the lowest",
            "energy. Undocked molecules follow unranked in selection order with",
            "blank score columns and their recorded failure codes. None is an",
            "experimentally measured affinity, and none shares a scale with a",
            "Vina score or an AutoDock4 binding energy.",
            "",
        ]
        if campaign.parameters.get("cnn_scoring") == "refinement":
            lines += [
                "Refinement note: pose coordinates were locally optimized against",
                "3D CNN gradients (cnn_scoring='refinement', --cnn_mix_emp_force",
                "disabled), so gnina_minimized_affinity_kcal_mol was evaluated on",
                "CNN-refined geometry and is not an independent empirical energy",
                "check.",
                "",
            ]
        for warning in campaign.warnings:
            if warning.get("code") == "GNINA_CNN_VS_NONPOSITIVE_AFFINITY":
                lines += [
                    "WARNING (GNINA_CNN_VS_NONPOSITIVE_AFFINITY): one or more completed",
                    "molecules recorded CNNaffinity <= 0 pK (K_d >= 1 M), where CNN_VS",
                    "becomes zero or negative and inverts CNNscore monotonicity among",
                    "negative-pK decoys.",
                    "",
                ]
                break
    else:
        lines += [
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


def _flex_export_fields(record: Any) -> dict[str, Any]:
    mode = getattr(record, "receptor_flex_mode", ReceptorFlexMode.RIGID)
    if mode is not ReceptorFlexMode.SIDECHAIN_FLEX:
        return {}
    return {
        "receptor_flex_mode": mode.value,
        "receptor_flex_sha256": getattr(record, "receptor_flex_sha256", None),
        "flex_residues": [
            item.model_dump(mode="json") for item in (getattr(record, "flex_residues", []) or [])
        ],
        "flex_atom_types": list(getattr(record, "flex_atom_types", []) or []),
    }


def _record_warnings(record: Any) -> list[dict[str, Any]]:
    return [item.model_dump(mode="json") for item in (getattr(record, "warnings", []) or [])]


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
        canceled_count=sum(
            1 for entry in record.entries if entry.status.value == "canceled"
        ),
        campaign_status=record.status.value,
        rows=rows,
        warnings=_record_warnings(record),
        **_flex_export_fields(record),
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
        canceled_count=sum(
            1 for entry in record.entries if entry.status.value == "canceled"
        ),
        campaign_status=record.status.value,
        rows=_autodock_rows(list(record.entries)),
        warnings=_record_warnings(record),
        **_flex_export_fields(record),
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
        canceled_count=sum(
            1 for entry in record.entries if entry.status.value == "canceled"
        ),
        campaign_status=record.status.value,
        rows=_autodock_rows(list(record.entries)),
        warnings=_record_warnings(record),
        **_flex_export_fields(record),
    )


def _number(value: float) -> str:
    """A recorded number, written out rather than rounded into a claim."""
    return repr(value)


def from_gnina_job(
    record: GninaJobRecord,
    *,
    reproducibility: ReproducibilityAssessment | None = None,
) -> ExportedCampaign:
    """One GNINA job: one ligand, N poses, three score axes, nothing merged.

    The rows are emitted in the record's own mode order. That order is the
    engine's descending CNN pose score and the record's own validator enforces
    it, so this function never sorts: re-sorting by the minimized affinity
    would publish a ranking GNINA did not produce.
    """
    rows: list[dict[str, Any]] = []
    for pose in record.poses:
        rows.append(
            {
                "rank": pose.mode,
                "mode": pose.mode,
                "ligand_id": record.request.ligand_id,
                "gnina_cnn_score": _number(pose.cnn_score),
                "gnina_cnn_affinity_pk": _number(pose.cnn_affinity),
                "gnina_cnn_vs": _number(pose.cnn_vs) if pose.cnn_vs is not None else "",
                "gnina_cnn_vs_source": pose.cnn_vs_source or "",
                "gnina_cnn_affinity_variance": (
                    _number(pose.cnn_affinity_variance)
                    if pose.cnn_affinity_variance is not None
                    else ""
                ),
                "gnina_minimized_affinity_kcal_mol": _number(pose.minimized_affinity_kcal_mol),
                "pose_artifact_id": pose.artifact.artifact_id,
                "pose_filename": pose.artifact.filename,
                "pose_sha256": pose.artifact.sha256,
            }
        )
    return ExportedCampaign(
        engine="GNINA",
        engine_version=record.tool.version,
        backend=record.request.parameters.compute,
        # Named so it can never be read as the one value column a screening
        # table has; the real axes are separate columns.
        value_column="gnina_minimized_affinity_kcal_mol",
        reproducibility=reproducibility or ReproducibilityAssessment(),
        receptor_id=record.request.receptor_id,
        receptor_sha256=record.receptor_sha256,
        binding_site_id=record.request.binding_site_id,
        box=record.box.model_dump(mode="json"),
        map_set_id=None,
        map_set_identity_key=None,
        parameters=record.request.parameters.model_dump(mode="json"),
        executable_sha256=record.tool.sha256,
        device_name=None,
        rows=rows,
        row_kind="pose",
        pose_count=len(record.poses),
        ligand_id=record.request.ligand_id,
        ranking_metric="gnina_cnn_score",
        cnn_model_identity=(
            record.cnn_model_identity.model_dump(mode="json")
            if record.cnn_model_identity is not None
            else None
        ),
        warnings=_record_warnings(record),
        **_flex_export_fields(record),
    )


def _inspect_screening_ligand(
    entry: GninaScreeningEntry,
    ligand_store: LigandArtifactStore | None,
) -> tuple[str, str, str]:
    """Resolve molecule name, canonical SMILES and MW without failing if gone."""
    fallback_name = entry.name or entry.ligand_id
    if ligand_store is None:
        return fallback_name, "", ""
    try:
        ligand_record = ligand_store.load_record(entry.ligand_id)
    except (AnkoraDomainError, OSError, ValueError):
        return fallback_name, "", ""
    inspection = ligand_record.inspection
    if entry.chemical_state_id is not None and (
        ligand_record.state is None or entry.chemical_state_id != ligand_record.state.state_id
    ):
        with suppress(AnkoraDomainError, OSError, ValueError):
            inspection = ligand_store.load_state_inspection(
                entry.ligand_id, entry.chemical_state_id
            )
    weight = (
        f"{inspection.molecular_weight_g_mol:.3f}"
        if inspection.molecular_weight_g_mol is not None
        else ""
    )
    return (
        entry.name or ligand_record.inspection.name,
        inspection.canonical_smiles or "",
        weight,
    )


def _pose_cnn_vs_for_ranking(pose: Any) -> float:
    return float(pose.cnn_vs if pose.cnn_vs is not None else pose.cnn_score * pose.cnn_affinity)


def from_gnina_screening(
    record: GninaScreeningCampaignRecord,
    *,
    completed_jobs: dict[str, GninaJobRecord],
    attempted_jobs: dict[str, GninaJobRecord] | None = None,
    ligand_store: LigandArtifactStore | None = None,
    reproducibility: ReproducibilityAssessment | None = None,
) -> ExportedCampaign:
    """One multi-ligand GNINA screening campaign, keeping GNINA axes separate.

    Docked molecules are ranked by the campaign's `hit_ranking_metric`
    (descending top-pose `CNNscore` or `CNN_VS`) with exact ties broken by
    applied selection order. Preflight-refused or failed molecules stay in the
    table unranked (`rank` blank) in selection order.
    """
    rank_by_cnn_vs = record.hit_ranking_metric == "cnn_vs"
    indexed: list[tuple[int, GninaScreeningEntry, GninaJobRecord | None]] = [
        (order, entry, completed_jobs.get(entry.ligand_id))
        for order, entry in enumerate(record.entries)
    ]
    indexed.sort(
        key=lambda item: (
            item[2] is None,
            (
                -_pose_cnn_vs_for_ranking(item[2].poses[0])
                if rank_by_cnn_vs
                else -item[2].poses[0].cnn_score
            )
            if item[2] is not None
            else 0.0,
            item[0],
        )
    )
    rows: list[dict[str, Any]] = []
    current_rank = 0
    for selection_order, entry, child_job in indexed:
        molecule, smiles, weight = _inspect_screening_ligand(entry, ligand_store)
        source_index = entry.source_index if entry.source_index is not None else selection_order
        failure = entry.failure
        if child_job is not None:
            current_rank += 1
            top_pose = child_job.poses[0]
            rows.append(
                {
                    "rank": current_rank,
                    "molecule": molecule,
                    "source_index": source_index,
                    "ligand_id": entry.ligand_id,
                    "canonical_smiles": smiles,
                    "molecular_weight_g_mol": weight,
                    "status": entry.status.value,
                    "failure_code": failure.code if failure else "",
                    "failure_message": failure.message if failure else "",
                    "gnina_cnn_score": _number(top_pose.cnn_score),
                    "gnina_cnn_affinity_pk": _number(top_pose.cnn_affinity),
                    "gnina_cnn_vs": (
                        _number(top_pose.cnn_vs) if top_pose.cnn_vs is not None else ""
                    ),
                    "gnina_cnn_vs_source": top_pose.cnn_vs_source or "",
                    "gnina_cnn_affinity_variance": (
                        _number(top_pose.cnn_affinity_variance)
                        if top_pose.cnn_affinity_variance is not None
                        else ""
                    ),
                    "gnina_minimized_affinity_kcal_mol": _number(
                        top_pose.minimized_affinity_kcal_mol
                    ),
                    "top_pose_artifact_id": top_pose.artifact.artifact_id,
                    "top_pose_sha256": top_pose.artifact.sha256,
                    "gnina_job_id": child_job.job_id,
                }
            )
        else:
            rows.append(
                {
                    "rank": "",
                    "molecule": molecule,
                    "source_index": source_index,
                    "ligand_id": entry.ligand_id,
                    "canonical_smiles": smiles,
                    "molecular_weight_g_mol": weight,
                    "status": entry.status.value,
                    "failure_code": failure.code if failure else "",
                    "failure_message": failure.message if failure else "",
                    "gnina_cnn_score": "",
                    "gnina_cnn_affinity_pk": "",
                    "gnina_cnn_vs": "",
                    "gnina_cnn_vs_source": "",
                    "gnina_cnn_affinity_variance": "",
                    "gnina_minimized_affinity_kcal_mol": "",
                    "top_pose_artifact_id": "",
                    "top_pose_sha256": "",
                    "gnina_job_id": entry.gnina_job_id or "",
                }
            )

    observed_gpus: set[str] = set()
    all_jobs = [*completed_jobs.values(), *((attempted_jobs or {}).values())]
    for job in all_jobs:
        if job.execution is not None and job.execution.observed_gpu_uuid is not None:
            observed_gpus.add(job.execution.observed_gpu_uuid)
    device_name = next(iter(observed_gpus)) if len(observed_gpus) == 1 else None
    ranking_column = "gnina_cnn_vs" if rank_by_cnn_vs else "gnina_cnn_score"
    resolved_model_identity = record.cnn_model_identity
    if resolved_model_identity is None:
        for job in all_jobs:
            if job.cnn_model_identity is not None:
                resolved_model_identity = job.cnn_model_identity
                break

    return ExportedCampaign(
        engine="GNINA",
        engine_version=record.tool.version,
        backend=record.request.parameters.compute,
        value_column=ranking_column,
        reproducibility=reproducibility or ReproducibilityAssessment(),
        receptor_id=record.request.receptor_id,
        receptor_sha256=record.receptor_sha256,
        binding_site_id=record.request.binding_site_id,
        box=record.box.model_dump(mode="json"),
        map_set_id=None,
        map_set_identity_key=None,
        selection_manifest_sha256=record.selection.manifest_sha256,
        library_id=record.request.library_id,
        filter_run_id=record.request.filter_run_id,
        parameters={
            **record.request.parameters.model_dump(mode="json"),
            "hit_ranking_metric": record.hit_ranking_metric,
            "worker_count": record.worker_count,
        },
        executable_sha256=record.tool.sha256,
        device_name=device_name,
        selected_count=record.selected_count,
        succeeded_count=record.succeeded_count,
        failed_count=record.failed_count,
        canceled_count=sum(
            1 for entry in record.entries if entry.status.value == "canceled"
        ),
        campaign_status=record.status.value,
        rows=rows,
        ranking_metric=ranking_column,
        cnn_model_identity=(
            resolved_model_identity.model_dump(mode="json")
            if resolved_model_identity is not None
            else None
        ),
        warnings=[warning.model_dump(mode="json") for warning in record.warnings],
        **_flex_export_fields(record),
    )


@dataclass(frozen=True, slots=True)
class _JobArtifact:
    """One file from the job directory, with what the record says about it."""

    filename: str
    destination: str
    recorded_sha256: str | None
    description: str


def _gnina_job_artifacts(record: GninaJobRecord) -> list[_JobArtifact]:
    """Every file the bundle must carry, and which of them have recorded hashes.

    The job record stores SHA-256 for its prepared inputs and for each
    published pose. It does **not** store one for `record.json`, the raw engine
    output or the captured logs, so those are carried with an export-time
    digest only and the manifest says which kind each is. Inventing a
    "recorded" hash for them would turn this bundle into evidence of a check
    that never ran.
    """
    artifacts = [
        _JobArtifact(
            "receptor.pdbqt",
            "inputs/receptor.pdbqt",
            record.receptor_sha256,
            "the prepared receptor PDBQT GNINA was given",
        ),
        _JobArtifact(
            "ligand.pdbqt",
            "inputs/ligand.pdbqt",
            record.ligand_sha256,
            "the prepared ligand PDBQT GNINA was given",
        ),
        _JobArtifact(
            "conformer.sdf",
            "inputs/conformer.sdf",
            record.conformer_sha256,
            "the conformer the prepared ligand came from",
        ),
        _JobArtifact(
            "raw_poses.pdbqt",
            "raw/raw_poses.pdbqt",
            None,
            "the unparsed pose file GNINA wrote",
        ),
        _JobArtifact("stdout.log", "raw/stdout.log", None, "the captured GNINA stdout"),
        _JobArtifact("stderr.log", "raw/stderr.log", None, "the captured GNINA stderr"),
        _JobArtifact(
            "record.json",
            "job/record.json",
            None,
            "the GNINA job record this bundle was built from",
        ),
    ]
    if record.receptor_flex_mode is ReceptorFlexMode.SIDECHAIN_FLEX:
        artifacts.extend(
            [
                _JobArtifact(
                    "receptor_flex.pdbqt",
                    "inputs/receptor_flex.pdbqt",
                    record.receptor_flex_sha256,
                    "the prepared flexible side-chain PDBQT GNINA was given",
                ),
                _JobArtifact(
                    "raw_flex.pdb",
                    "raw/raw_flex.pdb",
                    None,
                    "the unparsed flexible side-chain PDB GNINA wrote",
                ),
            ]
        )
    for pose in record.poses:
        artifacts.append(
            _JobArtifact(
                pose.artifact.filename,
                f"poses/{pose.artifact.filename}",
                pose.artifact.sha256,
                f"the published pose for mode {pose.mode}",
            )
        )
        if pose.artifact.flex_filename is not None:
            artifacts.append(
                _JobArtifact(
                    pose.artifact.flex_filename,
                    f"poses/{pose.artifact.flex_filename}",
                    pose.artifact.pose_flex_sidechains_sha256,
                    f"the preserved moved side chains for mode {pose.mode}",
                )
            )
    return artifacts


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

    validations, validation_warnings = collect_recorded_validations(
        root=resolved_root, catalog_id=catalog_id, export_directory=destination
    )
    (
        pose_quality_assessments,
        interaction_rule_evaluations,
        interaction_rule_sets,
        v02_warnings,
    ) = collect_v02_recorded_evidence(
        root=resolved_root, catalog_ids=[catalog_id], export_directory=destination
    )
    return RecordedEvidence(
        analyses=sorted(analyses, key=lambda item: str(item["analysis_id"])),
        figures=sorted(figures, key=lambda item: str(item["figure_id"])),
        collection_warnings=[*warnings, *validation_warnings, *v02_warnings],
        validations=validations,
        pose_quality_assessments=pose_quality_assessments,
        interaction_rule_evaluations=interaction_rule_evaluations,
        interaction_rule_sets=interaction_rule_sets,
    )


def collect_analog_expansion_evidence(
    *,
    root: Path,
    binding_site_id: str | None,
    library_id: str | None,
    export_directory: Path,
    library_ids: list[str] | None = None,
) -> tuple[
    list[dict[str, Any]],
    dict[str, Any] | None,
    list[dict[str, str]],
    AnalogSearchRecord | None,
    AnalogSelectionRecord | None,
    BindingSiteRecord | None,
]:
    """Copy immutable ADR-033 POSE_FOCUSED / Analog Expansion records verbatim into Export v6."""
    resolved_root = root.resolve()
    destination = export_directory.resolve()
    project_root = resolve_project_root(resolved_root)
    artifacts: list[dict[str, Any]] = []
    seen_artifact_paths: set[str] = set()
    warnings: list[dict[str, str]] = []
    provenance_summary: dict[str, Any] = {}
    focused_site: BindingSiteRecord | None = None
    selection_rec: AnalogSelectionRecord | None = None
    search_rec: AnalogSearchRecord | None = None

    def _record_artifact(entry: dict[str, Any]) -> None:
        rel = str(entry["path"])
        if rel not in seen_artifact_paths:
            seen_artifact_paths.add(rel)
            artifacts.append(entry)

    if binding_site_id:
        site_path = project_root / "derived" / "binding_sites" / binding_site_id / "record.json"
        if site_path.is_file():
            try:
                site = BindingSiteRecord.model_validate_json(site_path.read_text(encoding="utf-8"))
                if site.decisions.source is BindingSiteSource.POSE_FOCUSED:
                    focused_site = site
                    target = (
                        destination
                        / "evidence"
                        / "analog_expansion"
                        / "pose_focused_site"
                        / binding_site_id
                        / "record.json"
                    )
                    digest, size = _copy_preserved(site_path, target)
                    _record_artifact(
                        {
                            "kind": "pose_focused_binding_site",
                            "artifact_id": binding_site_id,
                            "path": _relative(target, destination),
                            "sha256": digest,
                            "size_bytes": size,
                        }
                    )
                    provenance_summary["pose_focused_binding_site_id"] = binding_site_id
                    if site.pose_focused_evidence is not None:
                        provenance_summary["source_pose_artifact_id"] = (
                            site.pose_focused_evidence.pose_artifact_id
                        )
                        provenance_summary["source_pose_sha256"] = (
                            site.pose_focused_evidence.pose_sha256
                        )
            except (OSError, ValueError) as error:
                warnings.append(
                    {
                        "kind": "pose_focused_site_unreadable",
                        "identity": binding_site_id,
                        "reason": str(error),
                    }
                )

    candidate_library_ids: list[str] = []
    for raw_lib_id in [*(library_ids or []), *([library_id] if library_id else [])]:
        if isinstance(raw_lib_id, str):
            cleaned_lib = raw_lib_id.strip()
            if cleaned_lib and cleaned_lib not in candidate_library_ids:
                candidate_library_ids.append(cleaned_lib)

    if candidate_library_ids:
        lig_store = LigandArtifactStore(root=resolved_root)
        analog_store = AnalogExpansionStore(root=resolved_root)
        for cand_lib_id in candidate_library_ids:
            try:
                lib = lig_store.load_library_record(cand_lib_id)
            except AnkoraDomainError:
                lib = None
            if lib is None or not (
                lib.artifact.origin_analog_selection_id or lib.artifact.origin_analog_search_id
            ):
                continue
            sel_id = lib.artifact.origin_analog_selection_id
            search_id = lib.artifact.origin_analog_search_id
            if sel_id:
                sel_path = (
                    project_root
                    / "derived"
                    / "analog_expansion"
                    / "selections"
                    / sel_id
                    / "record.json"
                )
                if sel_path.is_file():
                    try:
                        loaded_sel = analog_store.load_selection(sel_id)
                        if selection_rec is None:
                            selection_rec = loaded_sel
                        target = (
                            destination
                            / "evidence"
                            / "analog_expansion"
                            / "selections"
                            / sel_id
                            / "record.json"
                        )
                        rel_target = _relative(target, destination)
                        if rel_target not in seen_artifact_paths:
                            digest, size = _copy_preserved(sel_path, target)
                            _record_artifact(
                                {
                                    "kind": "analog_selection",
                                    "artifact_id": sel_id,
                                    "path": rel_target,
                                    "sha256": digest,
                                    "size_bytes": size,
                                }
                            )
                        provenance_summary.setdefault("analog_selection_id", sel_id)
                        provenance_summary.setdefault(
                            "include_seed_control", loaded_sel.include_seed_control
                        )
                        if not search_id:
                            search_id = loaded_sel.analog_search_id
                    except (AnkoraDomainError, OSError, ValueError) as error:
                        warnings.append(
                            {
                                "kind": "analog_selection_unreadable",
                                "identity": sel_id,
                                "reason": str(error),
                            }
                        )
            if search_id:
                search_path = (
                    project_root
                    / "derived"
                    / "analog_expansion"
                    / "searches"
                    / search_id
                    / "record.json"
                )
                if search_path.is_file():
                    try:
                        loaded_search = analog_store.load_search(search_id)
                        if search_rec is None:
                            search_rec = loaded_search
                        target = (
                            destination
                            / "evidence"
                            / "analog_expansion"
                            / "searches"
                            / search_id
                            / "record.json"
                        )
                        rel_target = _relative(target, destination)
                        if rel_target not in seen_artifact_paths:
                            digest, size = _copy_preserved(search_path, target)
                            _record_artifact(
                                {
                                    "kind": "analog_search",
                                    "artifact_id": search_id,
                                    "path": rel_target,
                                    "sha256": digest,
                                    "size_bytes": size,
                                }
                            )
                        provenance_summary.setdefault("analog_search_id", search_id)
                        provenance_summary.setdefault("search_mode", loaded_search.mode.value)
                        provenance_summary.setdefault(
                            "rdkit_version", loaded_search.rdkit_version
                        )
                        raw_resp = analog_store.search_raw_response_path(search_id)
                        if raw_resp is not None and raw_resp.is_file():
                            raw_target = (
                                destination
                                / "evidence"
                                / "analog_expansion"
                                / "searches"
                                / search_id
                                / raw_resp.name
                            )
                            rel_raw = _relative(raw_target, destination)
                            if rel_raw not in seen_artifact_paths:
                                r_sha, r_size = _copy_preserved(raw_resp, raw_target)
                                _record_artifact(
                                    {
                                        "kind": "external_provider_raw_response",
                                        "artifact_id": search_id,
                                        "path": rel_raw,
                                        "sha256": r_sha,
                                        "size_bytes": r_size,
                                    }
                                )
                        if loaded_search.analog_catalog_id:
                            cat_id = loaded_search.analog_catalog_id
                            cat_path = (
                                project_root
                                / "derived"
                                / "analog_expansion"
                                / "catalogs"
                                / cat_id
                                / "record.json"
                            )
                            if cat_path.is_file():
                                cat_rec = analog_store.load_catalog(cat_id)
                                cat_target = (
                                    destination
                                    / "evidence"
                                    / "analog_expansion"
                                    / "catalogs"
                                    / cat_id
                                    / "record.json"
                                )
                                rel_cat = _relative(cat_target, destination)
                                if rel_cat not in seen_artifact_paths:
                                    c_sha, c_size = _copy_preserved(cat_path, cat_target)
                                    _record_artifact(
                                        {
                                            "kind": "analog_catalog_record",
                                            "artifact_id": cat_id,
                                            "path": rel_cat,
                                            "sha256": c_sha,
                                            "size_bytes": c_size,
                                        }
                                    )
                                raw_cat = analog_store.catalog_content_path(cat_id)
                                if raw_cat.stat().st_size <= 5 * 1024 * 1024:
                                    raw_cat_dst = (
                                        destination
                                        / "evidence"
                                        / "analog_expansion"
                                        / "catalogs"
                                        / cat_id
                                        / raw_cat.name
                                    )
                                    rel_raw_cat = _relative(raw_cat_dst, destination)
                                    if rel_raw_cat not in seen_artifact_paths:
                                        rc_sha, rc_size = _copy_preserved(raw_cat, raw_cat_dst)
                                        _record_artifact(
                                            {
                                                "kind": "analog_catalog_snapshot",
                                                "artifact_id": cat_id,
                                                "path": rel_raw_cat,
                                                "sha256": rc_sha,
                                                "size_bytes": rc_size,
                                            }
                                        )
                                    provenance_summary.setdefault("catalog_snapshot_embedded", True)
                                else:
                                    provenance_summary.setdefault(
                                        "catalog_snapshot_embedded", False
                                    )
                                    provenance_summary.setdefault(
                                        "catalog_snapshot_omitted_size_policy", True
                                    )
                                    provenance_summary.setdefault("catalog_sha256", cat_rec.sha256)
                    except (AnkoraDomainError, OSError, ValueError) as error:
                        warnings.append(
                            {
                                "kind": "analog_search_unreadable",
                                "identity": search_id,
                                "reason": str(error),
                            }
                        )

    if not artifacts:
        return [], None, warnings, None, None, None
    provenance_summary["artifact_count"] = len(artifacts)
    return artifacts, provenance_summary, warnings, search_rec, selection_rec, focused_site


def collect_v02_recorded_evidence(
    *,
    root: Path,
    catalog_ids: list[str],
    export_directory: Path,
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, str]],
]:
    """Copy existing immutable M3 pose-quality and M4 interaction-rule records verbatim."""
    resolved_root = root.resolve()
    destination = export_directory.resolve()
    project_root = resolve_project_root(resolved_root)
    target_catalogs = set(catalog_ids)

    quality_entries: list[dict[str, Any]] = []
    rule_eval_entries: list[dict[str, Any]] = []
    rule_set_entries: list[dict[str, Any]] = []
    warnings: list[dict[str, str]] = []

    quality_root = project_root / "analysis" / "pose_quality"
    for source in sorted(quality_root.glob("*/record.json")):
        identity = source.parent.name
        try:
            raw = source.read_text(encoding="utf-8")
            qrec = PoseQualityRecord.model_validate_json(raw)
        except (OSError, ValueError) as error:
            warnings.append(
                {
                    "kind": "pose_quality_record_unreadable",
                    "identity": identity,
                    "reason": str(error),
                }
            )
            continue
        if qrec.catalog_id not in target_catalogs:
            continue
        if qrec.assessment_id != identity:
            warnings.append(
                {
                    "kind": "pose_quality_record_identity_mismatch",
                    "identity": identity,
                    "reason": "Folder and record identifiers do not match.",
                }
            )
            continue
        target = destination / "evidence" / "pose_quality" / identity / "record.json"
        digest, size = _copy_preserved(source, target)
        quality_entries.append(
            {
                "assessment_id": qrec.assessment_id,
                "catalog_id": qrec.catalog_id,
                "ligand_id": qrec.ligand_id,
                "pose_artifact_id": qrec.pose.artifact_id,
                "pose_complex_sha256": qrec.assessment.pose_complex.complex_identity_sha256,
                "overall_status": qrec.assessment.overall_status.value,
                "passed_count": qrec.passed_count,
                "failed_count": qrec.failed_count,
                "not_applicable_count": qrec.not_applicable_count,
                "not_evaluable_count": qrec.not_evaluable_count,
                "strain_delta_e_ref_kcal_mol": (
                    qrec.assessment.strain.delta_e_ref_kcal_mol
                    if qrec.assessment.strain is not None
                    else None
                ),
                "posebusters_version": qrec.posebusters_version,
                "path": _relative(target, destination),
                "sha256": digest,
                "size_bytes": size,
            }
        )

    referenced_rule_set_ids: set[str] = set()
    evals_root = project_root / "analysis" / "interaction_rule_evaluations"
    for source in sorted(evals_root.glob("*/record.json")):
        identity = source.parent.name
        try:
            raw = source.read_text(encoding="utf-8")
            erec = InteractionRuleEvaluationRecord.model_validate_json(raw)
        except (OSError, ValueError) as error:
            warnings.append(
                {
                    "kind": "interaction_rule_evaluation_unreadable",
                    "identity": identity,
                    "reason": str(error),
                }
            )
            continue
        if erec.catalog_id not in target_catalogs:
            continue
        if erec.evaluation_id != identity:
            warnings.append(
                {
                    "kind": "interaction_rule_evaluation_identity_mismatch",
                    "identity": identity,
                    "reason": "Folder and record identifiers do not match.",
                }
            )
            continue
        target = (
            destination / "evidence" / "interaction_rule_evaluations" / identity / "record.json"
        )
        digest, size = _copy_preserved(source, target)
        referenced_rule_set_ids.add(erec.rule_set_id)
        rule_eval_entries.append(
            {
                "evaluation_id": erec.evaluation_id,
                "rule_set_id": erec.rule_set_id,
                "rule_set_identity_sha256": erec.rule_set_identity_sha256,
                "catalog_id": erec.catalog_id,
                "ligand_id": erec.ligand_id,
                "pose_artifact_id": erec.pose.artifact_id,
                "pose_complex_sha256": erec.pose_complex.complex_identity_sha256,
                "overall_status": erec.overall_status.value,
                "passed_clause_count": erec.passed_clause_count,
                "failed_clause_count": erec.failed_clause_count,
                "tanimoto_similarity": (
                    erec.tanimoto.similarity if erec.tanimoto is not None else None
                ),
                "path": _relative(target, destination),
                "sha256": digest,
                "size_bytes": size,
            }
        )

    rule_sets_root = project_root / "analysis" / "interaction_rule_sets"
    for rule_set_id in sorted(referenced_rule_set_ids):
        source = rule_sets_root / rule_set_id / "record.json"
        if not source.is_file():
            warnings.append(
                {
                    "kind": "interaction_rule_set_missing",
                    "identity": rule_set_id,
                    "reason": "Referenced sealed rule set record was not found on disk.",
                }
            )
            continue
        try:
            raw = source.read_text(encoding="utf-8")
            rs_rec = InteractionRuleSetRecord.model_validate_json(raw)
        except (OSError, ValueError) as error:
            warnings.append(
                {
                    "kind": "interaction_rule_set_unreadable",
                    "identity": rule_set_id,
                    "reason": str(error),
                }
            )
            continue
        target = destination / "evidence" / "interaction_rule_sets" / rule_set_id / "record.json"
        digest, size = _copy_preserved(source, target)
        rule_set_entries.append(
            {
                "rule_set_id": rs_rec.rule_set_id,
                "name": rs_rec.name,
                "receptor_id": rs_rec.receptor_id,
                "rule_set_identity_sha256": rs_rec.rule_set_identity_sha256,
                "clause_count": len(rs_rec.clauses),
                "path": _relative(target, destination),
                "sha256": digest,
                "size_bytes": size,
            }
        )

    return (
        sorted(quality_entries, key=lambda item: str(item["assessment_id"])),
        sorted(rule_eval_entries, key=lambda item: str(item["evaluation_id"])),
        sorted(rule_set_entries, key=lambda item: str(item["rule_set_id"])),
        warnings,
    )


def collect_gnina_source_files(
    *,
    record: GninaJobRecord,
    export_directory: Path,
    preserved: dict[str, bytes],
) -> list[dict[str, Any]]:
    """Copy the job's own preserved bytes into the bundle, or fail the export.

    These are required inputs, not optional evidence: a bundle that silently
    omitted the raw engine output or one pose would look complete while being
    unreproducible. So anything unreadable, absent, or no longer matching a
    hash the record holds aborts the whole export before a ZIP exists.
    """
    destination = export_directory.resolve()
    carried: list[dict[str, Any]] = []
    for artifact in _gnina_job_artifacts(record):
        content = preserved[artifact.filename]
        digest = sha256(content).hexdigest()
        target = destination / artifact.destination
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("xb") as stream:
            stream.write(content)
        copied_digest, size = digest, len(content)
        carried.append(
            {
                "filename": artifact.filename,
                "path": _relative(target, destination),
                "description": artifact.description,
                "sha256": copied_digest,
                "size_bytes": size,
                # Which claim this hash supports: the record either held a
                # hash for this file before the export, or it did not.
                "integrity": (
                    "matches_recorded_sha256"
                    if artifact.recorded_sha256 is not None
                    else "export_time_digest_only"
                ),
                "recorded_sha256": artifact.recorded_sha256,
            }
        )
    return carried


def _verify_gnina_source(record: GninaJobRecord, store: GninaJobStore) -> dict[str, bytes]:
    """Snapshot and check required bytes before creating any export directory."""
    preserved: dict[str, bytes] = {}
    for artifact in _gnina_job_artifacts(record):
        try:
            content = store.output_path(record.job_id, artifact.filename).read_bytes()
        except (AnkoraDomainError, OSError, ValueError) as error:
            raise _source_incomplete(
                record.job_id,
                artifact.filename,
                f"This export requires {artifact.description}, which could not be read.",
            ) from error
        digest = sha256(content).hexdigest()
        if artifact.recorded_sha256 is not None and digest != artifact.recorded_sha256:
            raise AnkoraDomainError(
                code="EXPORT_SOURCE_TAMPERED",
                stage=_STAGE,
                status_code=409,
                message="A GNINA artifact differs from its recorded hash; no bundle was written.",
                details={
                    "job_id": record.job_id,
                    "filename": artifact.filename,
                    "expected_sha256": artifact.recorded_sha256,
                    "observed_sha256": digest,
                },
            )
        preserved[artifact.filename] = content
    if GninaJobRecord.model_validate_json(preserved["record.json"]) != record:
        raise _source_incomplete(record.job_id, "record.json", "The GNINA job record changed.")
    if record.execution is None:
        raise _source_incomplete(record.job_id, "record.json", "Execution evidence is missing.")
    for filename, expected in (
        ("stdout.log", record.execution.stdout),
        ("stderr.log", record.execution.stderr),
    ):
        if preserved[filename] != expected.encode("utf-8"):
            raise _source_incomplete(
                record.job_id, filename, "The log differs from recorded execution."
            )
    try:
        raw = parse_gnina_pdbqt(preserved["raw_poses.pdbqt"])
    except AnkoraDomainError as error:
        raise _source_incomplete(
            record.job_id, "raw_poses.pdbqt", "The raw output is invalid."
        ) from error
    if len(raw) != len(record.poses) or any(
        item.mode != pose.mode
        or item.cnn_score != pose.cnn_score
        or item.cnn_affinity != pose.cnn_affinity
        or item.minimized_affinity_kcal_mol != pose.minimized_affinity_kcal_mol
        or item.cnn_affinity_variance != pose.cnn_affinity_variance
        or not _raw_cnn_vs_matches(item, pose)
        or sha256(item.pdbqt).hexdigest() != pose.artifact.sha256
        or len(item.pdbqt) != pose.artifact.size_bytes
        for item, pose in zip(raw, record.poses, strict=False)
    ):
        raise _source_incomplete(
            record.job_id, "raw_poses.pdbqt", "Raw output differs from published poses."
        )
    if record.receptor_flex_mode is ReceptorFlexMode.SIDECHAIN_FLEX:
        try:
            paired_flex = pair_gnina_flex_models(
                raw,
                gnina_flex_pdb_text=preserved["raw_flex.pdb"].decode("utf-8"),
                meeko_flex_template_pdbqt=preserved["receptor_flex.pdbqt"].decode("utf-8"),
            )
        except (AnkoraDomainError, UnicodeDecodeError, ValueError) as error:
            raise _source_incomplete(
                record.job_id, "raw_flex.pdb", "The raw flexible side-chain output is invalid."
            ) from error
        if len(paired_flex) != len(record.poses) or any(
            pose.artifact.flex_filename is None
            or sha256(flex_bytes).hexdigest() != pose.artifact.pose_flex_sidechains_sha256
            for flex_bytes, pose in zip(paired_flex, record.poses, strict=False)
        ):
            raise _source_incomplete(
                record.job_id,
                "raw_flex.pdb",
                "Raw flexible side-chain output differs from published flex poses.",
            )
    return preserved


def _raw_cnn_vs_matches(raw_pose: Any, published_pose: Any) -> bool:
    if published_pose.cnn_vs is None:
        return raw_pose.cnn_vs is None
    if published_pose.cnn_vs_source == "engine_emitted":
        return bool(raw_pose.cnn_vs is not None and raw_pose.cnn_vs == published_pose.cnn_vs)
    if published_pose.cnn_vs_source == "derived_from_recorded_axes":
        return bool(
            raw_pose.cnn_vs is None
            and math.isclose(
                published_pose.cnn_vs,
                published_pose.cnn_score * published_pose.cnn_affinity,
                rel_tol=1e-12,
                abs_tol=1e-12,
            )
        )
    return False


def _source_incomplete(job_id: str, filename: str, message: str) -> AnkoraDomainError:
    return AnkoraDomainError(
        code="EXPORT_SOURCE_INCOMPLETE",
        stage=_STAGE,
        message=message,
        status_code=409,
        details={"job_id": job_id, "filename": filename},
    )


def _screening_incomplete(campaign_id: str, filename: str, message: str) -> AnkoraDomainError:
    return AnkoraDomainError(
        code="EXPORT_SOURCE_INCOMPLETE",
        stage=_STAGE,
        message=message,
        status_code=409,
        details={"campaign_id": campaign_id, "filename": filename},
    )


@dataclass(frozen=True, slots=True)
class _VerifiedGninaScreening:
    """In-memory verified snapshot of a completed GNINA screening campaign."""

    record: GninaScreeningCampaignRecord
    snapshot_bytes: bytes
    state_bytes: bytes
    selection_bytes: bytes
    receptor_bytes: bytes
    receptor_flex_bytes: bytes | None
    completed_jobs: dict[str, GninaJobRecord]
    completed_preserved: dict[str, dict[str, bytes]]
    failed_jobs: dict[str, GninaJobRecord]
    failed_preserved: dict[str, dict[str, bytes]]


_SCREENING_SNAPSHOT_FIELDS = (
    "chemical_state_id",
    "source_index",
    "name",
    "ligand_preparation_id",
    "ligand_sha256",
    "conformer_id",
    "conformer_sha256",
)


def _verify_gnina_screening_source(
    *,
    campaign_id: str,
    screening_store: GninaScreeningStore | None,
    job_store: GninaJobStore | None,
    ligand_store: LigandArtifactStore | None,
    root: Path,
) -> _VerifiedGninaScreening:
    """Verify campaign, selection manifest and child jobs before writing anything."""
    if screening_store is None:
        raise AnkoraDomainError(
            code="EXPORT_SOURCE_UNAVAILABLE",
            stage=_STAGE,
            message="GNINA screening storage is unavailable in this installation.",
            status_code=422,
            details={"source_kind": "gnina_screening"},
        )
    resolved_jobs = job_store or screening_store.jobs
    resolved_ligands = ligand_store or LigandArtifactStore(root)

    record = screening_store.load_campaign(campaign_id)
    if record.status is not DockingJobStatus.COMPLETED or record.succeeded_count <= 0:
        raise AnkoraDomainError(
            code="EXPORT_SOURCE_INCOMPLETE",
            stage=_STAGE,
            message=(
                "Only a completed GNINA screening campaign with published poses "
                "can be exported; no bundle was written."
            ),
            status_code=409,
            details={"campaign_id": campaign_id, "status": record.status.value},
        )

    campaign_dir = screening_store.campaign_directory(campaign_id)
    try:
        snapshot_bytes = (campaign_dir / "record.json").read_bytes()
        state_bytes = (campaign_dir / "campaign_state.sqlite3").read_bytes()
        snapshot = GninaScreeningCampaignRecord.model_validate_json(snapshot_bytes)
    except (AnkoraDomainError, OSError, ValueError) as error:
        raise _screening_incomplete(
            campaign_id,
            "record.json",
            "The campaign creation snapshot or state database could not be read.",
        ) from error

    if (
        snapshot.campaign_id != record.campaign_id
        or snapshot.request != record.request
        or snapshot.selection != record.selection
        or snapshot.selected_ligand_ids != record.selected_ligand_ids
        or snapshot.selected_count != record.selected_count
        or snapshot.tool != record.tool
        or snapshot.box != record.box
        or snapshot.receptor_output_artifact_id != record.receptor_output_artifact_id
        or snapshot.receptor_sha256 != record.receptor_sha256
        or snapshot.receptor_flex_mode != record.receptor_flex_mode
        or snapshot.receptor_flex_output_artifact_id != record.receptor_flex_output_artifact_id
        or snapshot.receptor_flex_sha256 != record.receptor_flex_sha256
        or snapshot.flex_residues != record.flex_residues
        or len(snapshot.entries) != len(record.entries)
        or any(
            initial.ligand_id != final.ligand_id
            or any(
                getattr(initial, field) is not None
                and getattr(initial, field) != getattr(final, field)
                for field in _SCREENING_SNAPSHOT_FIELDS
            )
            for initial, final in zip(snapshot.entries, record.entries, strict=True)
        )
    ):
        raise _screening_incomplete(
            campaign_id,
            "record.json",
            "The campaign creation snapshot disagrees with the recorded terminal state.",
        )

    try:
        selection_bytes = resolved_ligands.filter_run_content_path(
            record.request.library_id, record.request.filter_run_id
        ).read_bytes()
    except (AnkoraDomainError, OSError, ValueError) as error:
        raise _screening_incomplete(
            campaign_id,
            "selection_manifest.json",
            "The pinned library selection manifest could not be read.",
        ) from error

    selection_digest = sha256(selection_bytes).hexdigest()
    if selection_digest != record.selection.manifest_sha256:
        raise AnkoraDomainError(
            code="EXPORT_SOURCE_TAMPERED",
            stage=_STAGE,
            status_code=409,
            message=(
                "The pinned selection manifest differs from its recorded hash; "
                "no bundle was written."
            ),
            details={
                "campaign_id": campaign_id,
                "filename": "selection_manifest.json",
                "expected_sha256": record.selection.manifest_sha256,
                "observed_sha256": selection_digest,
            },
        )
    try:
        selection_run = verified_screening_selection(
            store=resolved_ligands,
            library_id=record.request.library_id,
            filter_run_id=record.request.filter_run_id,
        )
    except AnkoraDomainError as error:
        raise _screening_incomplete(
            campaign_id,
            "selection_manifest.json",
            "The pinned library selection manifest failed verification.",
        ) from error
    if (
        selection_run.artifact.filter_run_id != record.selection.manifest_artifact_id
        or list(record.selected_ligand_ids) != selection_run.selected_ligand_ids
    ):
        raise _screening_incomplete(
            campaign_id,
            "selection_manifest.json",
            "The pinned library selection manifest disagrees with the campaign.",
        )

    completed_jobs: dict[str, GninaJobRecord] = {}
    completed_preserved: dict[str, dict[str, bytes]] = {}
    failed_jobs: dict[str, GninaJobRecord] = {}
    failed_preserved: dict[str, dict[str, bytes]] = {}
    receptor_bytes: bytes | None = None
    receptor_flex_bytes: bytes | None = None

    for entry in record.entries:
        if entry.status is DockingJobStatus.COMPLETED:
            if entry.gnina_job_id is None:
                raise _screening_incomplete(
                    campaign_id,
                    "record.json",
                    "A completed screening entry has no linked GNINA job.",
                )
            try:
                child_job = resolved_jobs.load_job(entry.gnina_job_id)
            except (AnkoraDomainError, OSError, ValueError) as error:
                raise _screening_incomplete(
                    campaign_id,
                    entry.gnina_job_id,
                    "A completed screening entry's GNINA job could not be read.",
                ) from error
            preserved_child = _verify_gnina_source(child_job, resolved_jobs)
            hash_checks: list[tuple[str, str | None, str | None]] = [
                ("receptor.pdbqt", record.receptor_sha256, child_job.receptor_sha256),
                ("ligand.pdbqt", entry.ligand_sha256, child_job.ligand_sha256),
                ("conformer.sdf", entry.conformer_sha256, child_job.conformer_sha256),
                ("gnina", record.tool.sha256, child_job.tool.sha256),
            ]
            if record.receptor_flex_mode is ReceptorFlexMode.SIDECHAIN_FLEX:
                hash_checks.append(
                    (
                        "receptor_flex.pdbqt",
                        record.receptor_flex_sha256,
                        child_job.receptor_flex_sha256,
                    )
                )
            for label, expected_hash, observed_hash in hash_checks:
                if expected_hash != observed_hash:
                    raise AnkoraDomainError(
                        code="EXPORT_SOURCE_TAMPERED",
                        stage=_STAGE,
                        status_code=409,
                        message=(
                            "A linked GNINA child job differs from the campaign's "
                            "recorded hash; no bundle was written."
                        ),
                        details={
                            "campaign_id": campaign_id,
                            "job_id": child_job.job_id,
                            "filename": label,
                            "expected_sha256": expected_hash,
                            "observed_sha256": observed_hash,
                        },
                    )
            try:
                verified_job = verified_campaign_entry_job(
                    store=resolved_jobs, campaign=record, entry=entry
                )
            except AnkoraDomainError as error:
                raise _screening_incomplete(
                    campaign_id,
                    child_job.job_id,
                    "A linked GNINA child job disagrees with its campaign entry.",
                ) from error
            if receptor_bytes is None:
                receptor_bytes = preserved_child["receptor.pdbqt"]
            elif preserved_child["receptor.pdbqt"] != receptor_bytes:
                raise AnkoraDomainError(
                    code="EXPORT_SOURCE_TAMPERED",
                    stage=_STAGE,
                    status_code=409,
                    message="Receptor bytes differ across campaign jobs; no bundle was written.",
                    details={"campaign_id": campaign_id, "job_id": verified_job.job_id},
                )
            if record.receptor_flex_mode is ReceptorFlexMode.SIDECHAIN_FLEX:
                child_flex = preserved_child.get("receptor_flex.pdbqt")
                if child_flex is None:
                    raise _screening_incomplete(
                        campaign_id,
                        "receptor_flex.pdbqt",
                        "Flexible receptor bytes were missing from a completed child job.",
                    )
                if receptor_flex_bytes is None:
                    receptor_flex_bytes = child_flex
                elif child_flex != receptor_flex_bytes:
                    raise AnkoraDomainError(
                        code="EXPORT_SOURCE_TAMPERED",
                        stage=_STAGE,
                        status_code=409,
                        message=(
                            "Flexible receptor bytes differ across campaign jobs; "
                            "no bundle was written."
                        ),
                        details={"campaign_id": campaign_id, "job_id": verified_job.job_id},
                    )
            completed_jobs[entry.ligand_id] = verified_job
            completed_preserved[verified_job.job_id] = preserved_child
        elif entry.gnina_job_id is not None:
            try:
                failed_job = resolved_jobs.load_job(entry.gnina_job_id)
                raw_record = resolved_jobs.output_path(
                    entry.gnina_job_id, "record.json"
                ).read_bytes()
            except (AnkoraDomainError, OSError, ValueError) as error:
                raise _screening_incomplete(
                    campaign_id,
                    entry.gnina_job_id,
                    "A failed screening entry's linked GNINA job could not be read.",
                ) from error
            if (
                failed_job.screening_campaign_id != record.campaign_id
                or failed_job.request.ligand_id != entry.ligand_id
            ):
                raise _screening_incomplete(
                    campaign_id,
                    entry.gnina_job_id,
                    "A failed screening entry's linked GNINA job belongs elsewhere.",
                )
            failed_files: dict[str, bytes] = {"record.json": raw_record}
            for optional_name in ("stdout.log", "stderr.log", "raw_poses.pdbqt", "raw_flex.pdb"):
                with suppress(AnkoraDomainError, OSError, ValueError):
                    candidate = resolved_jobs.output_path(entry.gnina_job_id, optional_name)
                    if candidate.is_file():
                        failed_files[optional_name] = candidate.read_bytes()
            failed_jobs[entry.ligand_id] = failed_job
            failed_preserved[failed_job.job_id] = failed_files

    if receptor_bytes is None or sha256(receptor_bytes).hexdigest() != record.receptor_sha256:
        raise _screening_incomplete(
            campaign_id,
            "receptor.pdbqt",
            "Verified receptor PDBQT bytes were not available for this campaign.",
        )
    if record.receptor_flex_mode is ReceptorFlexMode.SIDECHAIN_FLEX and (
        receptor_flex_bytes is None
        or sha256(receptor_flex_bytes).hexdigest() != record.receptor_flex_sha256
    ):
        raise _screening_incomplete(
            campaign_id,
            "receptor_flex.pdbqt",
            "Verified flexible side-chain PDBQT bytes were not available for this campaign.",
        )

    return _VerifiedGninaScreening(
        record=record,
        snapshot_bytes=snapshot_bytes,
        state_bytes=state_bytes,
        selection_bytes=selection_bytes,
        receptor_bytes=receptor_bytes,
        receptor_flex_bytes=receptor_flex_bytes,
        completed_jobs=completed_jobs,
        completed_preserved=completed_preserved,
        failed_jobs=failed_jobs,
        failed_preserved=failed_preserved,
    )


def _write_verified_file(
    *,
    destination: Path,
    relative_path: str,
    filename: str,
    content: bytes,
    recorded_sha256: str | None,
    description: str,
) -> dict[str, Any]:
    target = destination / relative_path
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("xb") as stream:
        stream.write(content)
    digest = sha256(content).hexdigest()
    return {
        "filename": filename,
        "path": _relative(target, destination),
        "description": description,
        "sha256": digest,
        "size_bytes": len(content),
        "integrity": (
            "matches_recorded_sha256"
            if recorded_sha256 is not None
            else "export_time_digest_only"
        ),
        "recorded_sha256": recorded_sha256,
    }


def collect_gnina_screening_source_files(
    *,
    verified: _VerifiedGninaScreening,
    export_directory: Path,
) -> list[dict[str, Any]]:
    """Write campaign snapshot, pinned inputs and per-job artifacts into bundle."""
    destination = export_directory.resolve()
    record = verified.record
    carried: list[dict[str, Any]] = [
        _write_verified_file(
            destination=destination,
            relative_path="inputs/receptor.pdbqt",
            filename="receptor.pdbqt",
            content=verified.receptor_bytes,
            recorded_sha256=record.receptor_sha256,
            description="the prepared receptor PDBQT shared by this GNINA campaign",
        ),
        _write_verified_file(
            destination=destination,
            relative_path="inputs/selection_manifest.json",
            filename="selection_manifest.json",
            content=verified.selection_bytes,
            recorded_sha256=record.selection.manifest_sha256,
            description="the pinned applied library selection manifest",
        ),
        _write_verified_file(
            destination=destination,
            relative_path="campaign/record.json",
            filename="record.json",
            content=verified.snapshot_bytes,
            recorded_sha256=None,
            description="the immutable GNINA campaign creation snapshot",
        ),
        _write_verified_file(
            destination=destination,
            relative_path="campaign/campaign_state.sqlite3",
            filename="campaign_state.sqlite3",
            content=verified.state_bytes,
            recorded_sha256=None,
            description="the terminal GNINA campaign SQLite state database",
        ),
    ]
    if verified.receptor_flex_bytes is not None:
        carried.insert(
            1,
            _write_verified_file(
                destination=destination,
                relative_path="inputs/receptor_flex.pdbqt",
                filename="receptor_flex.pdbqt",
                content=verified.receptor_flex_bytes,
                recorded_sha256=record.receptor_flex_sha256,
                description="the prepared flexible side-chain PDBQT shared by this GNINA campaign",
            ),
        )

    for entry in record.entries:
        completed = verified.completed_jobs.get(entry.ligand_id)
        if completed is not None:
            preserved = verified.completed_preserved[completed.job_id]
            prefix = f"jobs/{completed.job_id}"
            for artifact in _gnina_job_artifacts(completed):
                if artifact.filename in {"receptor.pdbqt", "receptor_flex.pdbqt"}:
                    # Shared across the campaign and already written once under inputs/.
                    continue
                carried.append(
                    _write_verified_file(
                        destination=destination,
                        relative_path=f"{prefix}/{artifact.destination}",
                        filename=artifact.filename,
                        content=preserved[artifact.filename],
                        recorded_sha256=artifact.recorded_sha256,
                        description=f"{artifact.description} ({entry.ligand_id})",
                    )
                )
            continue

        failed = verified.failed_jobs.get(entry.ligand_id)
        if failed is not None:
            failed_files = verified.failed_preserved[failed.job_id]
            prefix = f"jobs/{failed.job_id}"
            carried.append(
                _write_verified_file(
                    destination=destination,
                    relative_path=f"{prefix}/job/record.json",
                    filename="record.json",
                    content=failed_files["record.json"],
                    recorded_sha256=None,
                    description=f"the failed GNINA child job record ({entry.ligand_id})",
                )
            )
            for optional_name in ("raw_poses.pdbqt", "raw_flex.pdb", "stdout.log", "stderr.log"):
                if optional_name in failed_files:
                    carried.append(
                        _write_verified_file(
                            destination=destination,
                            relative_path=f"{prefix}/raw/{optional_name}",
                            filename=optional_name,
                            content=failed_files[optional_name],
                            recorded_sha256=None,
                            description=(
                                f"captured {optional_name} for failed GNINA job ({entry.ligand_id})"
                            ),
                        )
                    )

    return carried


def collect_recorded_validations(
    *, root: Path, catalog_id: str, export_directory: Path
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """Copy existing redocking verdicts for this exact result, byte-for-byte.

    A verdict is a judgement about this run that already happened. It travels
    as the bytes that were recorded; nothing is re-measured, and a malformed
    record becomes a visible warning rather than a silent omission.
    """
    resolved_root = root.resolve()
    destination = export_directory.resolve()
    validations: list[dict[str, Any]] = []
    warnings: list[dict[str, str]] = []

    project_root = resolve_project_root(resolved_root)
    validations_root = project_root / "validation" / "redocking"
    for source in sorted(validations_root.glob("*/record.json")):
        identity = source.parent.name
        try:
            raw = source.read_text(encoding="utf-8")
            verdict = RedockingRunRecord.model_validate_json(raw)
        except (OSError, ValueError) as error:
            warnings.append(
                {
                    "kind": "redocking_record_unreadable",
                    "identity": identity,
                    "reason": str(error),
                }
            )
            continue
        if f"{verdict.source_kind}:{verdict.source_id}" != catalog_id:
            continue
        if verdict.validation_id != identity:
            warnings.append(
                {
                    "kind": "redocking_record_identity_mismatch",
                    "identity": identity,
                    "reason": "Folder and record identifiers do not match.",
                }
            )
            continue
        target = destination / "evidence" / "redocking" / identity / "record.json"
        digest, size = _copy_preserved(source, target)
        reference_info: dict[str, Any] | None = None
        if verdict.source_kind == "gnina_job":
            try:
                ligands = LigandArtifactStore(resolved_root)
                reference = ligands.load_record(verdict.reference_ligand_id)
                reference_bytes = ligands.content_path(verdict.reference_ligand_id).read_bytes()
                if (
                    reference.artifact.source is not LigandSource.CRYSTALLOGRAPHIC
                    or reference.artifact.sha256 != verdict.reference_sha256
                    or sha256(reference_bytes).hexdigest() != verdict.reference_sha256
                    or len(reference_bytes) != reference.artifact.size_bytes
                ):
                    raise ValueError(
                        "The crystallographic reference no longer matches the verdict."
                    )
                reference_path = (
                    destination
                    / "evidence"
                    / "redocking"
                    / identity
                    / "reference"
                    / ligands.sanitize_filename(reference.artifact.filename)
                )
                reference_path.parent.mkdir(parents=True, exist_ok=True)
                with reference_path.open("xb") as stream:
                    stream.write(reference_bytes)
                reference_info = {
                    "path": _relative(reference_path, destination),
                    "sha256": verdict.reference_sha256,
                    "size_bytes": len(reference_bytes),
                }
            except (AnkoraDomainError, OSError, ValueError):
                warnings.append(
                    {
                        "kind": "redocking_reference_unavailable",
                        "identity": identity,
                        "reason": (
                            "The original reference is missing or does not match its recorded hash."
                        ),
                    }
                )
        validations.append(
            {
                "validation_id": verdict.validation_id,
                "reference_ligand_id": verdict.reference_ligand_id,
                "reference_sha256": verdict.reference_sha256,
                "threshold_angstrom": verdict.metrics.threshold_angstrom,
                "outcome": verdict.metrics.outcome.value,
                "sampling_success": verdict.metrics.sampling_success,
                "ranking_success": verdict.metrics.ranking_success,
                "top1_rmsd_angstrom": verdict.metrics.top1_rmsd_angstrom,
                # Null stays null: for GNINA this means repeat behavior was
                # never assessed, which is not the same claim as `false`.
                "bitwise_reproducible": verdict.bitwise_reproducible,
                "path": _relative(target, destination),
                "sha256": digest,
                "size_bytes": size,
                **({"reference": reference_info} if verdict.source_kind == "gnina_job" else {}),
            }
        )
    return (
        sorted(validations, key=lambda item: str(item["validation_id"])),
        warnings,
    )


def _write_portable_bundle(directory: Path, filename: str = "campaign_bundle.zip") -> Path:
    """Zip the complete folder without ever adding the ZIP to itself."""
    if Path(filename).name != filename or not filename.lower().endswith(".zip"):
        raise ValueError("Campaign archive filename must be a plain ZIP filename")
    target = directory / filename
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
        gnina_store: GninaJobStore | None = None,
        gnina_screening_store: GninaScreeningStore | None = None,
        ligand_store: LigandArtifactStore | None = None,
    ) -> None:
        self._root = root.resolve()
        self._project_root = resolve_project_root(self._root)
        self._docking_store = docking_store
        self._autodock4_store = autodock4_store
        self._autodock_gpu_store = autodock_gpu_store
        self._binding_site_store = binding_site_store
        self._gnina_store = gnina_store
        self._gnina_screening_store = gnina_screening_store
        self._ligand_store = ligand_store
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
            gnina_store=GninaJobStore.from_environment(),
            gnina_screening_store=GninaScreeningStore.from_environment(),
            ligand_store=LigandArtifactStore.from_environment(),
        )

    def export_campaign(
        self,
        *,
        source_kind: str,
        batch_id: str,
        destination: str | None = None,
        display_name: str | None = None,
    ) -> dict[str, Any]:
        gnina_record = self._gnina_record(batch_id) if source_kind == "gnina_job" else None
        preserved = (
            _verify_gnina_source(gnina_record, self._gnina_store)
            if gnina_record is not None and self._gnina_store is not None
            else {}
        )
        verified_screening = (
            _verify_gnina_screening_source(
                campaign_id=batch_id,
                screening_store=self._gnina_screening_store,
                job_store=self._gnina_store,
                ligand_store=self._ligand_store,
                root=self._root,
            )
            if source_kind == "gnina_screening"
            else None
        )
        if gnina_record is not None:
            campaign = from_gnina_job(gnina_record)
        elif verified_screening is not None:
            campaign = from_gnina_screening(
                verified_screening.record,
                completed_jobs=verified_screening.completed_jobs,
                attempted_jobs=verified_screening.failed_jobs,
                ligand_store=self._ligand_store or LigandArtifactStore(self._root),
            )
        else:
            campaign = self._load(source_kind, batch_id)
        campaign = replace(
            campaign,
            reproducibility=self._reproducibility.assessment(f"{source_kind}:{batch_id}"),
            dependency_freshness=ProjectDependencyService(
                root=self._root, project_id=self._project_root.name
            ).freshness_for([batch_id, f"{source_kind}:{batch_id}"]),
        )
        campaign = self._with_box(campaign)
        normalized_name = _normalize_display_name(display_name)
        export_id = str(uuid4())
        directory = self._export_dir(export_id)
        directory.mkdir(parents=True, exist_ok=False)
        exported_at = datetime.now(UTC)
        bundle_identity = _bundle_identity(
            campaign=campaign,
            export_id=export_id,
            source_kind=source_kind,
            source_id=batch_id,
            exported_at=exported_at,
            display_name=normalized_name,
        )
        evidence = collect_recorded_evidence(
            root=self._root,
            catalog_id=f"{source_kind}:{batch_id}",
            export_directory=directory,
        )
        (
            analog_artifacts,
            analog_provenance,
            analog_warnings,
            analog_search,
            analog_selection,
            focused_site,
        ) = collect_analog_expansion_evidence(
            root=self._root,
            binding_site_id=campaign.binding_site_id,
            library_id=campaign.library_id,
            export_directory=directory,
        )
        if analog_artifacts or analog_warnings:
            evidence = replace(
                evidence,
                collection_warnings=[*evidence.collection_warnings, *analog_warnings],
                analog_expansion_artifacts=analog_artifacts,
                analog_expansion_provenance=analog_provenance,
            )
        # The single job's or screening campaign's own preserved bytes: required
        # inputs, so a failure aborts the export before any partial bundle exists.
        source_files: list[dict[str, Any]] = []
        if source_kind == "gnina_job":
            source_files = collect_gnina_source_files(
                record=gnina_record,  # type: ignore[arg-type]
                export_directory=directory,
                preserved=preserved,
            )
        elif verified_screening is not None:
            source_files = collect_gnina_screening_source_files(
                verified=verified_screening,
                export_directory=directory,
            )
        elif campaign.receptor_flex_mode == ReceptorFlexMode.SIDECHAIN_FLEX.value:
            source_files = self._collect_batch_flex_source_files(
                source_kind=source_kind,
                batch_id=batch_id,
                export_directory=directory,
            )

        # The Methods section this campaign's own records support. Rendered
        # before manifest.json so its SHA-256 is recorded in bundle_files.
        methods = _methods_markdown(source_kind, batch_id)
        if analog_search is not None or analog_selection is not None or focused_site is not None:
            from ankora_backend.services.methods_report import render_analog_expansion_methods

            analog_methods = render_analog_expansion_methods(
                search=analog_search,
                selection=analog_selection,
                focused_site=focused_site,
            )
            methods = (
                f"{methods.rstrip()}\n\n{analog_methods}" if methods is not None else analog_methods
            )
        if (
            methods is not None
            and campaign.dependency_freshness is not None
            and campaign.dependency_freshness.stale
            and "WARNING — STALE ARTIFACT (ADR-011)" not in methods
        ):
            reasons_text = (
                "; ".join(campaign.dependency_freshness.stale_reasons)
                or "upstream artifact modified"
            )
            methods = (
                f"> **WARNING — STALE ARTIFACT (ADR-011):** This campaign was marked stale "
                f"at export time and must not be presented as current ({reasons_text}).\n\n"
                + methods
            )

        core_files: dict[str, str] = {
            "results.csv": results_csv(campaign),
            "README.txt": readme(
                campaign,
                evidence=evidence,
                exported_at=exported_at,
                bundle_identity=bundle_identity,
            ),
        }
        if methods is not None:
            core_files["methods.md"] = methods
        bundle_files_meta = [
            {
                "path": name,
                "sha256": sha256(content.encode("utf-8")).hexdigest(),
                "size_bytes": len(content.encode("utf-8")),
            }
            for name, content in sorted(core_files.items())
        ]
        files: dict[str, str] = {
            **core_files,
            "manifest.json": manifest(
                campaign,
                exported_at=exported_at,
                evidence=evidence,
                source_kind=source_kind,
                source_id=batch_id,
                bundle_identity=bundle_identity,
                source_files=source_files,
                bundle_files=bundle_files_meta,
            ),
        }
        for name, content in files.items():
            with (directory / name).open("x", encoding="utf-8", newline="\n") as stream:
                stream.write(content)
        portable = _write_portable_bundle(directory, bundle_identity.archive_filename)

        # The bundle is assembled in the project first, so the record and the
        # files it serves back exist whatever happens next; a chosen folder
        # then receives a complete copy under a name that says what it is.
        chosen = validated_destination(destination, stage=_STAGE, prefix="EXPORT")
        written_to = directory
        if chosen is not None:
            written_to = free_directory(
                chosen, _bundle_name(campaign, exported_at, bundle_identity)
            )
            shutil.copytree(directory, written_to)

        return {
            "exported_at": exported_at,
            "source_kind": source_kind,
            "source_id": batch_id,
            **bundle_identity.manifest_payload(),
            "engine": campaign.engine,
            "engine_version": campaign.engine_version,
            "reproducibility": campaign.reproducibility.model_dump(mode="json"),
            "row_count": len(campaign.rows),
            "interaction_analysis_count": len(evidence.analyses),
            "figure_count": len(evidence.figures),
            "redocking_validation_count": len(evidence.validations),
            "directory": str(written_to),
            "outside_project": chosen is not None,
            "record_directory": str(directory),
            "files": sorted([*files, portable.name]),
        }

    def file_path(self, export_id: str, filename: str) -> Path:
        allowed = {
            "results.csv",
            "methods.md",
            "manifest.json",
            "README.txt",
            "campaign_bundle.zip",
        }
        directory = self._export_dir(export_id)
        try:
            payload = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            payload = {}
        bundle = payload.get("bundle") if isinstance(payload, dict) else None
        archive = bundle.get("archive_filename") if isinstance(bundle, dict) else None
        if (
            isinstance(archive, str)
            and Path(archive).name == archive
            and archive.lower().endswith(".zip")
        ):
            allowed.add(archive)
        if filename not in allowed:
            raise self._not_found(export_id, filename)
        path = directory / filename
        if not path.is_file():
            raise self._not_found(export_id, filename)
        return path

    def _collect_batch_flex_source_files(
        self,
        *,
        source_kind: str,
        batch_id: str,
        export_directory: Path,
    ) -> list[dict[str, Any]]:
        """Preserve per-pose moved side-chain artifacts for sidechain_flex batches."""
        destination = export_directory.resolve()
        carried: list[dict[str, Any]] = []
        if source_kind == "vina_batch":
            batch: Any = self._docking_store.load_batch_record(batch_id)
            resolver: Any = self._docking_store.batch_pose_flex_content_path
            entries: list[Any] = list(batch.entries)
            pose_attr = "poses"
        elif source_kind == "autodock4_batch":
            batch = self._autodock4_store.load_batch(batch_id)
            resolver = self._autodock4_store.batch_pose_flex_content_path
            entries = list(batch.entries)
            pose_attr = "runs"
        elif source_kind == "autodock_gpu_batch":
            batch = self._autodock_gpu_store.load_batch(batch_id)
            resolver = self._autodock_gpu_store.batch_pose_flex_content_path
            entries = list(batch.entries)
            pose_attr = "runs"
        else:
            return carried

        for entry in entries:
            for item in getattr(entry, pose_attr, []):
                artifact = item.artifact
                if artifact.flex_filename is None or artifact.pose_flex_sidechains_sha256 is None:
                    continue
                flex_path = resolver(batch_id, entry.ligand_id, artifact.artifact_id)
                if flex_path is None or not flex_path.is_file():
                    continue
                content = flex_path.read_bytes()
                if sha256(content).hexdigest() != artifact.pose_flex_sidechains_sha256:
                    raise AnkoraDomainError(
                        code="EXPORT_SOURCE_TAMPERED",
                        stage=_STAGE,
                        status_code=409,
                        message=(
                            "A flexible side-chain pose artifact differs from its recorded "
                            "hash; no bundle was written."
                        ),
                        details={
                            "batch_id": batch_id,
                            "ligand_id": entry.ligand_id,
                            "filename": artifact.flex_filename,
                        },
                    )
                carried.append(
                    _write_verified_file(
                        destination=destination,
                        relative_path=f"poses/{entry.ligand_id}/{artifact.flex_filename}",
                        filename=artifact.flex_filename,
                        content=content,
                        recorded_sha256=artifact.pose_flex_sidechains_sha256,
                        description=(
                            f"preserved moved side chains for {entry.ligand_id} "
                            f"({artifact.flex_filename})"
                        ),
                    )
                )
        return carried

    def _load(self, source_kind: str, batch_id: str) -> ExportedCampaign:
        if source_kind == "vina_batch":
            return from_vina_batch(self._docking_store.load_batch_record(batch_id))
        if source_kind == "autodock4_batch":
            return from_autodock4_batch(self._autodock4_store.load_batch(batch_id))
        if source_kind == "autodock_gpu_batch":
            return from_autodock_gpu_batch(self._autodock_gpu_store.load_batch(batch_id))
        if source_kind == "gnina_job":
            return from_gnina_job(self._gnina_record(batch_id))
        raise AnkoraDomainError(
            code="EXPORT_SOURCE_UNKNOWN",
            stage=_STAGE,
            message="Ankora does not know how to export this kind of result.",
            status_code=422,
            details={"source_kind": source_kind},
        )

    def _gnina_record(self, job_id: str) -> GninaJobRecord:
        """A GNINA job that is safe to describe as a result.

        An unfinished, failed or canceled job has no published poses and no
        complete raw output, so exporting it would produce a bundle whose
        table and manifest imply a run that did not finish.
        """
        if self._gnina_store is None:
            raise AnkoraDomainError(
                code="EXPORT_SOURCE_UNAVAILABLE",
                stage=_STAGE,
                message="GNINA result storage is unavailable in this installation.",
                status_code=422,
                details={"source_kind": "gnina_job"},
            )
        record = self._gnina_store.load_job(job_id)
        if record.status is not DockingJobStatus.COMPLETED or not record.poses:
            raise AnkoraDomainError(
                code="EXPORT_SOURCE_INCOMPLETE",
                stage=_STAGE,
                message=(
                    "Only a completed GNINA job with published poses can be "
                    "exported; no bundle was written."
                ),
                status_code=409,
                details={"job_id": job_id, "status": record.status.value},
            )
        return record

    def _with_box(self, campaign: ExportedCampaign) -> ExportedCampaign:
        """The search space belongs in the manifest, not only its identifier."""
        if campaign.box:
            # A GNINA job records the box it was actually run with. A binding
            # site can be edited after a run, so the site artifact must not
            # overwrite the box these numbers came from.
            return campaign
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


def _bundle_name(
    campaign: ExportedCampaign,
    exported_at: datetime,
    identity: CampaignBundleIdentity,
) -> str:
    """A compact but complete identity for a folder beside a manuscript.

    A folder called after a UUID says nothing about which campaign it holds,
    and the scientist is about to file it next to a paper.
    """
    label = slug(identity.display_name or campaign.engine)[:40] or "campaign"
    source_kind, source_id = identity.catalog_id.split(":", 1)
    source = f"{slug(source_kind)}-{slug(source_id)[:8]}"
    parts = [
        "Ankora",
        label,
        source,
        f"inputs-{identity.input_identity_sha256[:8]}",
        exported_at.strftime("%Y%m%d-%H%M%S"),
        f"export-{identity.bundle_identity_sha256[:8]}",
    ]
    return "_".join(part for part in parts if part)


def _campaign_inputs(campaign: ExportedCampaign) -> dict[str, Any]:
    """The inputs this result actually had.

    A key that is absent is absent: a single job has no library, no filter run
    and no selection manifest, and emitting those keys as `null` beside a
    screening bundle's real values would invite a reader to treat the two as
    the same kind of thing.
    """
    payload: dict[str, Any] = {
        "receptor_id": campaign.receptor_id,
        "receptor_pdbqt_sha256": campaign.receptor_sha256,
        "binding_site_id": campaign.binding_site_id,
        "search_box": campaign.box,
        "map_set_id": campaign.map_set_id,
        "map_set_identity_key": campaign.map_set_identity_key,
    }
    if campaign.receptor_flex_mode == ReceptorFlexMode.SIDECHAIN_FLEX.value:
        payload["receptor_flex_mode"] = campaign.receptor_flex_mode
        payload["receptor_flex_pdbqt_sha256"] = campaign.receptor_flex_sha256
        payload["flex_residues"] = campaign.flex_residues
        if campaign.flex_atom_types:
            payload["flex_atom_types"] = campaign.flex_atom_types
    if campaign.ligand_id is not None:
        payload["ligand_id"] = campaign.ligand_id
    for key, value in (
        ("library_id", campaign.library_id),
        ("filter_run_id", campaign.filter_run_id),
        ("selection_manifest_sha256", campaign.selection_manifest_sha256),
    ):
        if value is not None:
            payload[key] = value
    return payload


def _json_sha256(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8"
    )
    return sha256(encoded).hexdigest()


def _bundle_identity(
    *,
    campaign: ExportedCampaign,
    export_id: str,
    source_kind: str,
    source_id: str,
    exported_at: datetime,
    display_name: str | None,
) -> CampaignBundleIdentity:
    catalog_id = f"{source_kind}:{source_id}"
    input_identity_sha256 = _json_sha256(_campaign_inputs(campaign))
    bundle_identity_sha256 = _json_sha256(
        {
            "protocol": "ankora-campaign-bundle-identity-v1",
            "export_id": export_id,
            "exported_at": exported_at.isoformat(),
            "catalog_id": catalog_id,
            "display_name": display_name,
            "input_identity_sha256": input_identity_sha256,
        }
    )
    provisional = CampaignBundleIdentity(
        export_id=export_id,
        catalog_id=catalog_id,
        display_name=display_name,
        input_identity_sha256=input_identity_sha256,
        bundle_identity_sha256=bundle_identity_sha256,
        archive_filename="",
    )
    archive_filename = f"{_bundle_name(campaign, exported_at, provisional)}_bundle.zip"
    return replace(provisional, archive_filename=archive_filename)


def _normalize_display_name(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = " ".join(value.split())
    if (
        not normalized
        or len(normalized) > 80
        or any(ord(character) < 32 for character in normalized)
    ):
        raise AnkoraDomainError(
            code="EXPORT_NAME_INVALID",
            stage=_STAGE,
            message="A bundle name must contain between 1 and 80 visible characters.",
            status_code=422,
            details={"display_name": value},
        )
    return normalized


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
