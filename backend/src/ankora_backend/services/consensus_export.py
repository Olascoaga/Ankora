"""Reproducible Export v5 bundler for ADR-030 consensus runs (M6a).

Packages an immutable `ConsensusRunRecord` (`PC-Q`, `PC-ECR`, optional gated
`PC-L2`) into a self-contained, SHA-256-verifiable Export v5 directory and
portable ZIP archive consumable directly by `scripts/verify_export_bundle.py`
and by external comparison harnesses (`ADR-031 §1`).

Preserves raw immutable records verbatim (`consensus`, `reference_panel`,
optional `calibration` stages, and any existing `M3`/`M4` pose diagnostics
attached to source campaigns) with zero recomputation.
"""

from __future__ import annotations

import csv
import io
import json
import os
import shutil
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any
from uuid import uuid4

from ankora_backend import __version__
from ankora_backend.domain.errors import AnkoraDomainError
from ankora_backend.domain.project_context import resolve_project_root
from ankora_backend.persistence.calibration_store import CalibrationArtifactStore
from ankora_backend.persistence.consensus_store import ConsensusArtifactStore
from ankora_backend.schemas.consensus import ConsensusRunRecord
from ankora_backend.services.campaign_export import (
    _copy_preserved,
    _json_sha256,
    _normalize_display_name,
    _relative,
    _write_portable_bundle,
    collect_analog_expansion_evidence,
    collect_v02_recorded_evidence,
)
from ankora_backend.services.export_destinations import (
    free_directory,
    slug,
    validated_destination,
)
from ankora_backend.services.methods_report import (
    render_analog_expansion_methods,
    render_calibration_methods,
    render_consensus_methods,
    render_interaction_rules_methods,
    render_pose_quality_methods,
)
from ankora_backend.services.project_dependencies import (
    ArtifactFreshness,
    ProjectDependencyService,
)

_STAGE = "consensus_export"
_BUNDLE_IDENTITY_PROTOCOL = "ankora-campaign-bundle-identity-v1"


def consensus_table_columns(record: ConsensusRunRecord) -> list[str]:
    """Stable CSV column list for two-tier E6 consensus results."""
    columns = [
        "tier",
        "rank",
        "parent_compound_id",
        "parent_state_id",
        "pcq_score",
    ]
    if record.core_ranking is not None:
        columns.append("pcq_core_score")
    columns.extend(
        [
            "pc_ecr_score_inv_sigma",
            "inter_family_disagreement",
            "search_convergence_count",
            "search_engine_count",
            "rotatable_bond_count",
            "selected_medoid_cluster_id",
            "selected_pose_complex_sha256",
        ]
    )
    if record.pc_l2_model is not None:
        columns.append("pc_l2_score")
    columns.append("failure_or_exclusion_codes")
    return columns


def consensus_results_csv(record: ConsensusRunRecord) -> str:
    """Render two-tier E6 consensus table preserving unranked parents in denominator."""
    columns = consensus_table_columns(record)
    details_by_parent = {detail.parent_compound_id: detail for detail in record.parent_details}
    core_entries_by_parent = (
        {entry.parent_compound_id: entry for entry in record.core_ranking.entries}
        if record.core_ranking is not None
        else {}
    )
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=columns, extrasaction="ignore", lineterminator="\n")
    writer.writeheader()

    for entry in record.ranking.entries:
        detail = details_by_parent.get(entry.parent_compound_id)
        core_entry = core_entries_by_parent.get(entry.parent_compound_id)
        core_score_val: float | None = None
        if (
            core_entry is not None
            and core_entry.tier == "full_profile"
            and core_entry.score_value is not None
        ):
            core_score_val = core_entry.score_value
        elif detail is not None and detail.pcq_core_score is not None:
            core_score_val = detail.pcq_core_score
        if entry.tier == "full_profile":
            row: dict[str, Any] = {
                "tier": "full_profile",
                "rank": entry.rank,
                "parent_compound_id": entry.parent_compound_id,
                "parent_state_id": entry.parent_state_id,
                "pcq_score": f"{entry.score_value:.6f}" if entry.score_value is not None else "",
                "pcq_core_score": f"{core_score_val:.6f}" if core_score_val is not None else "",
                "pc_ecr_score_inv_sigma": (
                    f"{detail.pc_ecr_score:.8f}"
                    if detail is not None and detail.pc_ecr_score is not None
                    else ""
                ),
                "inter_family_disagreement": (
                    f"{entry.inter_family_disagreement:.6f}"
                    if entry.inter_family_disagreement is not None
                    else ""
                ),
                "search_convergence_count": (
                    entry.search_convergence_count
                    if entry.search_convergence_count is not None
                    else ""
                ),
                "search_engine_count": (
                    entry.search_engine_count if entry.search_engine_count is not None else ""
                ),
                "rotatable_bond_count": (
                    detail.rotatable_bond_count
                    if detail is not None and detail.rotatable_bond_count is not None
                    else ""
                ),
                "selected_medoid_cluster_id": (
                    detail.selected_medoid_cluster_id or "" if detail is not None else ""
                ),
                "selected_pose_complex_sha256": (
                    entry.selected_pose_complex.complex_identity_sha256
                    if entry.selected_pose_complex is not None
                    else ""
                ),
                "pc_l2_score": (
                    f"{detail.pc_l2_score:.6f}"
                    if detail is not None and detail.pc_l2_score is not None
                    else ""
                ),
                "failure_or_exclusion_codes": "",
            }
        else:
            # Preserve primary E6 anti-imputation (blank rank and pcq_score) while
            # retaining independent non-neural pcq_core_score when core_ranking scored
            # this parent (e.g. GNINA failed while Vina/Vinardo/AD4 succeeded, D7-001).
            row = {
                "tier": "partial_or_unscored",
                "rank": "",
                "parent_compound_id": entry.parent_compound_id,
                "parent_state_id": entry.parent_state_id,
                "pcq_score": "",
                "pcq_core_score": f"{core_score_val:.6f}" if core_score_val is not None else "",
                "pc_ecr_score_inv_sigma": "",
                "inter_family_disagreement": "",
                "search_convergence_count": "",
                "search_engine_count": "",
                "rotatable_bond_count": (
                    detail.rotatable_bond_count
                    if detail is not None and detail.rotatable_bond_count is not None
                    else ""
                ),
                "selected_medoid_cluster_id": "",
                "selected_pose_complex_sha256": "",
                "pc_l2_score": "",
                "failure_or_exclusion_codes": ";".join(entry.failure_or_exclusion_codes),
            }
        writer.writerow(row)
    return buffer.getvalue()


def _consensus_inputs(record: ConsensusRunRecord) -> dict[str, Any]:
    return {
        "receptor_id": record.receptor_id,
        "binding_site_id": record.binding_site_id,
        "receptor_flex_spec": record.receptor_flex_spec.model_dump(mode="json"),
        "binding_box_sha256": record.binding_box_sha256,
        "autogrid_map_set_sha256": record.autogrid_map_set_sha256,
        "variant_id": record.variant_id.value,
        "k_max": record.k_max,
        "rmsd_threshold_angstrom": record.rmsd_threshold_angstrom,
        "ecr_tau": record.ecr_tau,
        "enabled_functions": [fn.value for fn in record.enabled_functions],
        "reference_panel_id": record.reference_panel.panel_id,
        "reference_panel_sha256": record.reference_panel.reference_panel_sha256,
        "source_catalog_ids": list(record.source_catalog_ids),
        **(
            {
                "pc_l2_calibration_id": record.pc_l2_model.calibration_id,
                "pc_l2_split_identity_sha256": record.pc_l2_model.split_identity_sha256,
            }
            if record.pc_l2_model is not None
            else {}
        ),
    }


def _consensus_bundle_name(
    record: ConsensusRunRecord,
    *,
    exported_at: datetime,
    display_name: str | None,
    input_identity_sha256: str,
    bundle_identity_sha256: str,
) -> str:
    label = slug(display_name or record.name or record.variant_id.value)[:40] or "consensus"
    source = f"consensus-run-{slug(record.consensus_id)[:8]}"
    parts = [
        "Ankora",
        label,
        source,
        f"inputs-{input_identity_sha256[:8]}",
        exported_at.strftime("%Y%m%d-%H%M%S"),
        f"export-{bundle_identity_sha256[:8]}",
    ]
    return "_".join(part for part in parts if part)


def _consensus_readme(
    record: ConsensusRunRecord,
    *,
    export_format: int,
    exported_at: datetime,
    archive_filename: str,
    input_identity_sha256: str,
    bundle_identity_sha256: str,
    freshness: ArtifactFreshness | None = None,
) -> str:
    header = f"Ankora Export v{export_format} — ADR-030 Rank-Space Consensus Bundle"
    lines = [
        header,
        "=" * len(header),
        "",
    ]
    if freshness is not None and freshness.stale:
        reasons_text = (
            "; ".join(freshness.stale_reasons) or "upstream artifact modified"
        )
        lines += [
            "WARNING: STALE ARTIFACT (ADR-011)",
            "-" * 33,
            "This exported consensus run was marked STALE at export time and must",
            "not be presented as current.",
            f"Reasons: {reasons_text}",
            "",
        ]
    lines += [
        f"Run name: {record.name}",
        f"Consensus ID: {record.consensus_id}",
        f"Variant: {record.variant_id.value}",
        f"Exported at: {exported_at.isoformat()}",
        f"Reference panel SHA-256: {record.reference_panel.reference_panel_sha256}",
        f"Input identity SHA-256: {input_identity_sha256}",
        f"Bundle identity SHA-256: {bundle_identity_sha256}",
        f"Portable archive: {archive_filename}",
        "",
        "Scientific interpretation notes:",
        "- PC-Q (0-100) is dimensionless inter-family rank-quantile concordance, NEVER",
        "  binding free energy (delta-G) or experimentally measured affinity.",
        f"- PC-ECR (tau = {record.ecr_tau}) stays on its separate Palacio-Rodriguez 1/sigma scale.",
        "- Partial or unscored parent compounds remain explicitly retained in results.csv",
        "  under tier='partial_or_unscored' with zero score imputation and no rank (E6).",
        "",
        "Independent verification (Python 3.12 stdlib, zero dependencies):",
        (
            f"  python scripts/verify_export_bundle.py {archive_filename} "
            f"--require-format {export_format}"
        ),
        "",
    ]
    return "\n".join(lines)


def _resolve_source_library_ids(
    project_root: Path, source_catalog_ids: list[str]
) -> list[str]:
    """Resolve all distinct originating ligand library_ids from consensus sources (D5-017)."""
    folder_by_kind = {
        "vina_batch": ("results", "docking_batches"),
        "autodock4_batch": ("results", "autodock4_batches"),
        "autodock_gpu_batch": ("results", "autodock_gpu_batches"),
        "gnina_screening": ("results", "gnina_screening_campaigns"),
    }
    resolved: list[str] = []
    for catalog_id in source_catalog_ids:
        if ":" not in catalog_id:
            continue
        kind, record_id = catalog_id.split(":", 1)
        rel_parts = folder_by_kind.get(kind)
        if rel_parts is None:
            continue
        record_path = project_root.joinpath(*rel_parts, record_id, "record.json")
        if not record_path.is_file():
            continue
        try:
            payload = json.loads(record_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        req = payload.get("request") if isinstance(payload, dict) else None
        lib_id = req.get("library_id") if isinstance(req, dict) else None
        if isinstance(lib_id, str) and lib_id.strip():
            cleaned = lib_id.strip()
            if cleaned not in resolved:
                resolved.append(cleaned)
    return resolved


class ConsensusExportService:
    """Export an immutable ADR-030 consensus run as a verified Export v5 bundle."""

    def __init__(
        self,
        *,
        root: Path,
        consensus_store: ConsensusArtifactStore,
        calibration_store: CalibrationArtifactStore,
    ) -> None:
        self._root = root.resolve()
        self._project_root = resolve_project_root(self._root)
        self._consensus_store = consensus_store
        self._calibration_store = calibration_store

    @classmethod
    def from_environment(cls) -> ConsensusExportService:
        configured = os.getenv("ANKORA_DATA_DIR")
        root = Path(configured) if configured else Path.cwd() / ".ankora-data"
        return cls(
            root=root,
            consensus_store=ConsensusArtifactStore.from_environment(),
            calibration_store=CalibrationArtifactStore.from_environment(),
        )

    def export_consensus_run(
        self,
        consensus_id: str,
        *,
        destination: str | None = None,
        display_name: str | None = None,
    ) -> dict[str, Any]:
        record = self._consensus_store.load_run(consensus_id)
        normalized_name = _normalize_display_name(display_name)
        chosen = validated_destination(destination, stage=_STAGE, prefix="EXPORT")
        export_id = str(uuid4())
        directory = (self._project_root / "exports" / export_id).resolve()
        directory.mkdir(parents=True, exist_ok=False)
        exported_at = datetime.now(UTC)

        catalog_id = f"consensus_run:{record.consensus_id}"
        inputs_payload = _consensus_inputs(record)
        input_identity_sha256 = _json_sha256(inputs_payload)
        bundle_identity_sha256 = _json_sha256(
            {
                "protocol": _BUNDLE_IDENTITY_PROTOCOL,
                "export_id": export_id,
                "exported_at": exported_at.isoformat(),
                "catalog_id": catalog_id,
                "display_name": normalized_name,
                "input_identity_sha256": input_identity_sha256,
            }
        )
        bundle_stem = _consensus_bundle_name(
            record,
            exported_at=exported_at,
            display_name=normalized_name,
            input_identity_sha256=input_identity_sha256,
            bundle_identity_sha256=bundle_identity_sha256,
        )
        archive_filename = f"{bundle_stem}_bundle.zip"

        # Copy immutable consensus record + hash-locked reference panel verbatim.
        consensus_src = (
            self._project_root / "analysis" / "consensus" / record.consensus_id / "record.json"
        )
        consensus_dst = directory / "evidence" / "consensus" / record.consensus_id / "record.json"
        cons_sha, cons_size = _copy_preserved(consensus_src, consensus_dst)
        consensus_records_evidence = [
            {
                "consensus_id": record.consensus_id,
                "variant_id": record.variant_id.value,
                "reference_panel_sha256": record.reference_panel.reference_panel_sha256,
                "path": _relative(consensus_dst, directory),
                "sha256": cons_sha,
                "size_bytes": cons_size,
            }
        ]

        panel_src = (
            self._project_root
            / "analysis"
            / "consensus_panels"
            / record.reference_panel.panel_id
            / "record.json"
        )
        panel_dst = (
            directory
            / "evidence"
            / "consensus_panels"
            / record.reference_panel.panel_id
            / "record.json"
        )
        panel_sha, panel_size = _copy_preserved(panel_src, panel_dst)
        reference_panels_evidence = [
            {
                "panel_id": record.reference_panel.panel_id,
                "reference_panel_sha256": record.reference_panel.reference_panel_sha256,
                "total_panel_parents": record.reference_panel.total_panel_parents,
                "path": _relative(panel_dst, directory),
                "sha256": panel_sha,
                "size_bytes": panel_size,
            }
        ]

        # Copy immutable calibration evidence if PC-L2 is attached.
        calibration_records_evidence: list[dict[str, Any]] = []
        collection_warnings: list[dict[str, str]] = []
        if record.pc_l2_model is not None:
            cal_id = record.pc_l2_model.calibration_id
            cal_dir = self._calibration_store.root / cal_id
            cal_record_src = cal_dir / "record.json"
            if cal_record_src.is_file():
                cal_dst = directory / "evidence" / "calibrations" / cal_id / "record.json"
                cal_sha, cal_size = _copy_preserved(cal_record_src, cal_dst)
                stage_files: list[dict[str, Any]] = []
                for stage_name in ("split.json", "selection.json", "confirmation.json"):
                    stage_src = cal_dir / stage_name
                    if stage_src.is_file():
                        stage_dst = directory / "evidence" / "calibrations" / cal_id / stage_name
                        st_sha, st_size = _copy_preserved(stage_src, stage_dst)
                        stage_files.append(
                            {
                                "filename": stage_name,
                                "path": _relative(stage_dst, directory),
                                "sha256": st_sha,
                                "size_bytes": st_size,
                            }
                        )
                calibration_records_evidence.append(
                    {
                        "calibration_id": cal_id,
                        "split_identity_sha256": record.pc_l2_model.split_identity_sha256,
                        "promoted": record.pc_l2_model.promoted,
                        "path": _relative(cal_dst, directory),
                        "sha256": cal_sha,
                        "size_bytes": cal_size,
                        "stage_files": stage_files,
                    }
                )
            else:
                collection_warnings.append(
                    {
                        "kind": "calibration_record_missing",
                        "identity": cal_id,
                        "reason": "Referenced PC-L2 calibration record was not found on disk.",
                    }
                )

        # Copy any existing M3 pose-quality & M4 interaction-rule evidence from source campaigns.
        (
            pose_quality_assessments,
            interaction_rule_evaluations,
            interaction_rule_sets,
            v02_warnings,
        ) = collect_v02_recorded_evidence(
            root=self._root,
            catalog_ids=list(record.source_catalog_ids),
            export_directory=directory,
        )
        collection_warnings.extend(v02_warnings)

        source_library_ids = _resolve_source_library_ids(
            self._project_root, list(record.source_catalog_ids)
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
            binding_site_id=record.binding_site_id,
            library_id=source_library_ids[0] if source_library_ids else None,
            library_ids=source_library_ids,
            export_directory=directory,
        )
        collection_warnings.extend(analog_warnings)
        export_format = 6 if (analog_artifacts and analog_provenance) else 5
        freshness = ProjectDependencyService(
            root=self._root, project_id=self._project_root.name
        ).freshness_for(
            [
                record.consensus_id,
                f"consensus_run:{record.consensus_id}",
                *record.source_catalog_ids,
            ]
        )

        columns = consensus_table_columns(record)
        manifest_payload: dict[str, Any] = {
            "exported_at": exported_at.isoformat(),
            "ankora_export_format": export_format,
            "source_kind": "consensus_run",
            "source_id": record.consensus_id,
            "engine": {
                "name": "Ankora PC-Q Consensus",
                "version": __version__,
                "backend": record.variant_id.value,
                "executable_sha256": None,
                "device": None,
                "enabled_functions": [fn.value for fn in record.enabled_functions],
            },
            "reproducibility": {
                "status": "deterministic_rank_space_consensus",
                "reference_panel_sha256": record.reference_panel.reference_panel_sha256,
                "tie_policy": record.ranking.tie_policy,
                "failure_policy": record.ranking.failure_policy,
                "note": (
                    "PC-Q and PC-ECR are deterministic functions of the hash-locked "
                    "ReferencePanelArtifact and verified per-medoid --score_only scores."
                ),
            },
            "inputs": inputs_payload,
            "protocol": {
                "variant_id": record.variant_id.value,
                "k_max": record.k_max,
                "rmsd_threshold_angstrom": record.rmsd_threshold_angstrom,
                "ecr_tau": record.ecr_tau,
                "block_weights": {k.value: v for k, v in record.block_weights.items()},
                "within_block_weights": {
                    k.value: v for k, v in record.within_block_weights.items()
                },
                "enabled_functions": [fn.value for fn in record.enabled_functions],
                "pc_l2_promoted": (
                    record.pc_l2_model.promoted if record.pc_l2_model is not None else None
                ),
                "pc_l2_verdict_text": (
                    record.pc_l2_model.promotion_verdict_text
                    if record.pc_l2_model is not None
                    else None
                ),
            },
            "counts": {
                "total_parents": record.ranking.total_parents,
                "full_profile": record.ranking.full_profile_count,
                "partial_or_unscored": record.ranking.partial_or_unscored_count,
            },
            "table": {
                "file": "results.csv",
                "row": "consensus_parent",
                "columns": columns,
            },
            "v02_provenance": {
                "receptor_flex_mode": record.receptor_flex_spec.mode.value,
                "flex_residue_count": len(record.receptor_flex_spec.flex_residues),
                "variant_id": record.variant_id.value,
                "reference_panel_sha256": record.reference_panel.reference_panel_sha256,
                "pc_l2_attached": record.pc_l2_model is not None,
                "pc_l2_promoted": (
                    record.pc_l2_model.promoted if record.pc_l2_model is not None else None
                ),
                "pose_quality_assessment_count": len(pose_quality_assessments),
                "interaction_rule_evaluation_count": len(interaction_rule_evaluations),
                "interaction_rule_set_count": len(interaction_rule_sets),
                "calibration_record_count": len(calibration_records_evidence),
            },
            "recorded_evidence": {
                "pose_interaction_analyses": [],
                "figures": [],
                "redocking_validations": [],
                "consensus_records": consensus_records_evidence,
                "reference_panels": reference_panels_evidence,
                "calibration_records": calibration_records_evidence,
                "pose_quality_assessments": pose_quality_assessments,
                "interaction_rule_evaluations": interaction_rule_evaluations,
                "interaction_rule_sets": interaction_rule_sets,
                "collection_warnings": collection_warnings,
                "notes": [
                    "Every consensus, reference panel, calibration, pose-quality, and "
                    "interaction-rule artifact in this bundle was copied verbatim from "
                    "immutable project records without recomputation.",
                ],
            },
            "scientific_notes": [
                "PC-Q (0-100) is a dimensionless inter-family rank-quantile concordance index; "
                "it is not a binding free energy (kcal/mol) or experimental potency estimate.",
                f"PC-ECR (tau = {record.ecr_tau}) is reported on its separate Palacio-Rodriguez "
                "1/sigma scale and is never blended with PC-Q (ADR-030 E5).",
                "Family block weights are fixed published constants; native scores from "
                "distinct scoring families are never pooled or averaged in native units.",
                "Partial or unscored parent compounds remain explicitly retained under "
                "tier='partial_or_unscored' in the campaign denominator with zero imputation (E6).",
            ],
            "bundle": {
                "export_id": export_id,
                "catalog_id": catalog_id,
                "display_name": normalized_name,
                "input_identity_sha256": input_identity_sha256,
                "bundle_identity_sha256": bundle_identity_sha256,
                "archive_filename": archive_filename,
            },
        }
        if export_format >= 6 and analog_provenance is not None:
            manifest_payload["analog_expansion_provenance"] = analog_provenance
            manifest_payload["recorded_evidence"]["analog_expansion_artifacts"] = analog_artifacts
        manifest_payload["dependency_freshness"] = freshness.to_dict()
        warnings_list: list[dict[str, Any]] = [
            warning.model_dump(mode="json") for warning in record.warnings
        ]
        if freshness.stale:
            warnings_list.append(
                {
                    "code": "STALE_SOURCE_ARTIFACT",
                    "stage": _STAGE,
                    "message": (
                        "This exported consensus run was marked stale at export time (ADR-011) "
                        "and must not be presented as current."
                    ),
                    "details": freshness.to_dict(),
                }
            )
        if warnings_list:
            manifest_payload["warnings"] = warnings_list

        methods_markdown = render_consensus_methods(record)
        # Wire embedded M2 calibration, M3 pose quality, and M4 interaction rules
        # into consensus methods.md whenever those artifacts were bundled (D5-018).
        if record.pc_l2_model is not None:
            try:
                cal_record = self._calibration_store.get_run(record.pc_l2_model.calibration_id)
                methods_markdown = (
                    f"{methods_markdown.rstrip()}\n\n"
                    + render_calibration_methods(cal_record)
                )
            except (AnkoraDomainError, OSError, ValueError) as error:
                collection_warnings.append(
                    {
                        "kind": "calibration_methods_unreadable",
                        "identity": record.pc_l2_model.calibration_id,
                        "reason": str(error),
                    }
                )
        if pose_quality_assessments:
            from ankora_backend.schemas.pose_quality import PoseQualityRecord

            pq_records: list[PoseQualityRecord] = []
            for pq_entry in pose_quality_assessments:
                pq_path = directory / str(pq_entry["path"])
                try:
                    pq_records.append(
                        PoseQualityRecord.model_validate_json(pq_path.read_text(encoding="utf-8"))
                    )
                except (OSError, ValueError) as error:
                    collection_warnings.append(
                        {
                            "kind": "pose_quality_methods_unreadable",
                            "identity": str(
                                pq_entry.get("assessment_id", pq_entry.get("path", ""))
                            ),
                            "reason": str(error),
                        }
                    )
                    continue
            if pq_records:
                methods_markdown = (
                    f"{methods_markdown.rstrip()}\n\n"
                    + render_pose_quality_methods(pq_records)
                )
        if interaction_rule_sets or interaction_rule_evaluations:
            from ankora_backend.schemas.interaction_rules import (
                InteractionRuleEvaluationRecord,
                InteractionRuleSetRecord,
            )

            rs_records: list[InteractionRuleSetRecord] = []
            for rs_entry in interaction_rule_sets:
                rs_path = directory / str(rs_entry["path"])
                try:
                    rs_records.append(
                        InteractionRuleSetRecord.model_validate_json(
                            rs_path.read_text(encoding="utf-8")
                        )
                    )
                except (OSError, ValueError) as error:
                    collection_warnings.append(
                        {
                            "kind": "interaction_rule_set_methods_unreadable",
                            "identity": str(rs_entry.get("rule_set_id", rs_entry.get("path", ""))),
                            "reason": str(error),
                        }
                    )
                    continue
            ev_records: list[InteractionRuleEvaluationRecord] = []
            for ev_entry in interaction_rule_evaluations:
                ev_path = directory / str(ev_entry["path"])
                try:
                    ev_records.append(
                        InteractionRuleEvaluationRecord.model_validate_json(
                            ev_path.read_text(encoding="utf-8")
                        )
                    )
                except (OSError, ValueError) as error:
                    collection_warnings.append(
                        {
                            "kind": "interaction_rule_evaluation_methods_unreadable",
                            "identity": str(
                                ev_entry.get("evaluation_id", ev_entry.get("path", ""))
                            ),
                            "reason": str(error),
                        }
                    )
                    continue
            if rs_records or ev_records:
                methods_markdown = (
                    f"{methods_markdown.rstrip()}\n\n"
                    + render_interaction_rules_methods(rs_records, ev_records)
                )
        if analog_search is not None or analog_selection is not None or focused_site is not None:
            methods_markdown = (
                f"{methods_markdown.rstrip()}\n\n"
                + render_analog_expansion_methods(
                    search=analog_search,
                    selection=analog_selection,
                    focused_site=focused_site,
                )
            )
        if freshness.stale:
            reasons_text = (
                "; ".join(freshness.stale_reasons) or "upstream artifact modified"
            )
            methods_markdown = (
                f"> **WARNING — STALE ARTIFACT (ADR-011):** This consensus run was marked stale "
                f"at export time and must not be presented as current ({reasons_text}).\n\n"
                + methods_markdown
            )
        core_files = {
            "results.csv": consensus_results_csv(record),
            "methods.md": methods_markdown,
            "README.txt": _consensus_readme(
                record,
                export_format=export_format,
                exported_at=exported_at,
                archive_filename=archive_filename,
                input_identity_sha256=input_identity_sha256,
                bundle_identity_sha256=bundle_identity_sha256,
                freshness=freshness,
            ),
        }
        manifest_payload["bundle_files"] = [
            {
                "path": name,
                "sha256": sha256(content.encode("utf-8")).hexdigest(),
                "size_bytes": len(content.encode("utf-8")),
            }
            for name, content in sorted(core_files.items())
        ]
        files = {
            **core_files,
            "manifest.json": json.dumps(manifest_payload, indent=2, ensure_ascii=False) + "\n",
        }
        for name, content in files.items():
            with (directory / name).open("x", encoding="utf-8", newline="\n") as stream:
                stream.write(content)

        portable = _write_portable_bundle(directory, archive_filename)

        written_to = directory
        if chosen is not None:
            written_to = free_directory(
                chosen,
                _consensus_bundle_name(
                    record,
                    exported_at=exported_at,
                    display_name=normalized_name,
                    input_identity_sha256=input_identity_sha256,
                    bundle_identity_sha256=bundle_identity_sha256,
                ),
            )
            shutil.copytree(directory, written_to)

        return {
            "exported_at": exported_at,
            "ankora_export_format": export_format,
            "source_kind": "consensus_run",
            "source_id": record.consensus_id,
            "export_id": export_id,
            "catalog_id": catalog_id,
            "display_name": normalized_name,
            "input_identity_sha256": input_identity_sha256,
            "bundle_identity_sha256": bundle_identity_sha256,
            "archive_filename": archive_filename,
            "variant_id": record.variant_id.value,
            "row_count": record.ranking.total_parents,
            "full_profile_count": record.ranking.full_profile_count,
            "partial_or_unscored_count": record.ranking.partial_or_unscored_count,
            "pose_quality_count": len(pose_quality_assessments),
            "interaction_rule_evaluation_count": len(interaction_rule_evaluations),
            "directory": str(written_to),
            "outside_project": chosen is not None,
            "record_directory": str(directory),
            "files": sorted([*files, portable.name]),
            "stale": freshness.stale,
            "stale_reasons": list(freshness.stale_reasons),
        }
