"""Standalone zero-dependency verifier for Ankora export bundles (Export v2–v6).

Usage:
    python scripts/verify_export_bundle.py path/to/Ankora_..._bundle.zip
    python scripts/verify_export_bundle.py path/to/export_directory --json

Designed for manuscript reviewers, collaborators, external benchmark harnesses
(ADR-031), and CI audits: relies strictly on the Python 3.12 standard library
with zero Ankora or third-party package imports.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import posixpath
import re
import sys
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any, Self

SUPPORTED_EXPORT_FORMATS = frozenset({2, 3, 4, 5, 6})
BUNDLE_IDENTITY_PROTOCOL = "ankora-campaign-bundle-identity-v1"
ALLOWED_SOURCE_INTEGRITY = frozenset({"matches_recorded_sha256", "export_time_digest_only"})
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class BundleVerificationError(ValueError):
    """Raised when an export bundle fails structural or cryptographic verification."""


def _canonical_json_sha256(payload: dict[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _validate_safe_relpath(rel_path: str) -> str:
    if not rel_path or "\\" in rel_path or rel_path.startswith("/"):
        raise BundleVerificationError(f"Unsafe bundle member path: {rel_path!r}")
    if re.match(r"^[A-Za-z]:", rel_path):
        raise BundleVerificationError(f"Drive-prefixed bundle member path: {rel_path!r}")
    parts = rel_path.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise BundleVerificationError(f"Non-normalized bundle member path: {rel_path!r}")
    normalized = posixpath.normpath(rel_path)
    if normalized != rel_path:
        raise BundleVerificationError(f"Non-canonical bundle member path: {rel_path!r}")
    return normalized


class _BundleSource:
    """Uniform read-only view over a portable .zip archive or an export directory."""

    def __init__(self, target: Path) -> None:
        self.target = target.resolve()
        self._zip: zipfile.ZipFile | None = None
        self._members: dict[str, zipfile.ZipInfo] = {}
        self.kind: str
        if self.target.is_file():
            if not zipfile.is_zipfile(self.target):
                raise BundleVerificationError(f"Target file is not a valid ZIP archive: {self.target.name}")
            self.kind = "zip"
            self._zip = zipfile.ZipFile(self.target, mode="r")
            for info in self._zip.infolist():
                if info.is_dir():
                    continue
                safe = _validate_safe_relpath(info.filename)
                if safe in self._members:
                    raise BundleVerificationError(f"Duplicate ZIP member entry: {safe}")
                self._members[safe] = info
        elif self.target.is_dir():
            self.kind = "directory"
            for item in sorted(self.target.rglob("*")):
                if item.is_symlink():
                    raise BundleVerificationError(
                        f"Symlinks are forbidden inside export directories: {item.name}"
                    )
                if item.is_file():
                    rel = _validate_safe_relpath(item.relative_to(self.target).as_posix())
                    self._members[rel] = zipfile.ZipInfo(rel)
        else:
            raise BundleVerificationError(f"Bundle path does not exist: {target}")

    def close(self) -> None:
        if self._zip is not None:
            self._zip.close()
            self._zip = None

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def files(self) -> set[str]:
        return set(self._members)

    def has_file(self, rel_path: str) -> bool:
        return rel_path in self._members

    def read_bytes(self, rel_path: str) -> bytes:
        safe = _validate_safe_relpath(rel_path)
        if safe not in self._members:
            raise BundleVerificationError(f"Missing required file in bundle: {safe}")
        if self._zip is not None:
            return self._zip.read(safe)
        return (self.target / safe).read_bytes()

    def sha256_and_size(self, rel_path: str) -> tuple[str, int]:
        safe = _validate_safe_relpath(rel_path)
        if safe not in self._members:
            raise BundleVerificationError(f"Missing referenced file in bundle: {safe}")
        digest = hashlib.sha256()
        total = 0
        if self._zip is not None:
            with self._zip.open(safe, "r") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
                    total += len(chunk)
        else:
            with (self.target / safe).open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
                    total += len(chunk)
        return digest.hexdigest(), total


def _verify_hash_field(value: Any, label: str) -> str:
    if not isinstance(value, str) or not SHA256_RE.match(value):
        raise BundleVerificationError(f"Invalid SHA-256 hex digest for {label}: {value!r}")
    return value


def _verify_referenced_blob(
    source: _BundleSource,
    *,
    rel_path: Any,
    expected_sha256: Any,
    expected_size: Any,
    label: str,
) -> None:
    if not isinstance(rel_path, str):
        raise BundleVerificationError(f"Missing string path for {label}")
    safe_path = _validate_safe_relpath(rel_path)
    want_sha = _verify_hash_field(expected_sha256, f"{label} ({safe_path})")
    if not isinstance(expected_size, int) or isinstance(expected_size, bool) or expected_size < 0:
        raise BundleVerificationError(f"Invalid size_bytes for {label} ({safe_path}): {expected_size!r}")
    got_sha, got_size = source.sha256_and_size(safe_path)
    if got_size != expected_size:
        raise BundleVerificationError(
            f"Byte size mismatch for {label} ({safe_path}): expected {expected_size}, observed {got_size}"
        )
    if got_sha != want_sha:
        raise BundleVerificationError(
            f"SHA-256 mismatch for {label} ({safe_path}): expected {want_sha}, observed {got_sha}"
        )


def verify_bundle(target: Path, *, require_format: int | None = None) -> dict[str, Any]:
    """Verify structural, tabular, and SHA-256 integrity of an Ankora export bundle."""
    with _BundleSource(target) as source:
        for required in ("manifest.json", "results.csv", "README.txt"):
            if not source.has_file(required):
                raise BundleVerificationError(f"Bundle is missing core file: {required}")

        try:
            manifest = json.loads(source.read_bytes("manifest.json").decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as err:
            raise BundleVerificationError(f"manifest.json is not valid UTF-8 JSON: {err}") from err
        if not isinstance(manifest, dict):
            raise BundleVerificationError("manifest.json root must be a JSON object")

        fmt = manifest.get("ankora_export_format")
        if not isinstance(fmt, int) or isinstance(fmt, bool) or fmt not in SUPPORTED_EXPORT_FORMATS:
            raise BundleVerificationError(f"Unsupported ankora_export_format: {fmt!r}")
        if require_format is not None and fmt != require_format:
            raise BundleVerificationError(
                f"Expected ankora_export_format == {require_format}, observed {fmt}"
            )

        exported_at = manifest.get("exported_at")
        if not isinstance(exported_at, str):
            raise BundleVerificationError("manifest.json missing string exported_at")
        try:
            datetime.fromisoformat(exported_at)
        except ValueError as err:
            raise BundleVerificationError(f"Invalid ISO-8601 exported_at: {exported_at!r}") from err

        for key in ("engine", "reproducibility", "inputs", "protocol", "counts", "recorded_evidence"):
            if not isinstance(manifest.get(key), dict):
                raise BundleVerificationError(f"manifest.json missing object section {key!r}")
        if not isinstance(manifest.get("scientific_notes"), list) or not manifest["scientific_notes"]:
            raise BundleVerificationError("manifest.json missing non-empty scientific_notes list")

        engine = manifest["engine"]
        if not isinstance(engine.get("name"), str) or not engine["name"].strip():
            raise BundleVerificationError("manifest.json engine.name must be a non-empty string")
        if not isinstance(engine.get("version"), str) or not engine["version"].strip():
            raise BundleVerificationError("manifest.json engine.version must be a non-empty string")

        readme_text = source.read_bytes("README.txt").decode("utf-8")
        if not readme_text.strip():
            raise BundleVerificationError("README.txt is empty")
        if source.has_file("methods.md"):
            methods_text = source.read_bytes("methods.md").decode("utf-8")
            if not methods_text.strip():
                raise BundleVerificationError("methods.md is present but empty")

        # Verify cryptographic bundle & input identities (Format >= 3 or whenever bundle is present)
        bundle_section = manifest.get("bundle")
        computed_input_sha256 = _canonical_json_sha256(manifest["inputs"])
        computed_bundle_sha256: str | None = None
        if fmt >= 3 and not isinstance(bundle_section, dict):
            raise BundleVerificationError(f"Format {fmt} bundle requires a 'bundle' identity section")
        if isinstance(bundle_section, dict):
            source_kind = manifest.get("source_kind")
            source_id = manifest.get("source_id")
            expected_catalog_id = f"{source_kind}:{source_id}"
            if bundle_section.get("catalog_id") != expected_catalog_id:
                raise BundleVerificationError(
                    f"bundle.catalog_id mismatch: expected {expected_catalog_id!r}, "
                    f"observed {bundle_section.get('catalog_id')!r}"
                )
            recorded_input_sha = _verify_hash_field(
                bundle_section.get("input_identity_sha256"),
                "bundle.input_identity_sha256",
            )
            if recorded_input_sha != computed_input_sha256:
                raise BundleVerificationError(
                    f"input_identity_sha256 mismatch: manifest inputs hash to {computed_input_sha256}, "
                    f"bundle claims {recorded_input_sha}"
                )
            recorded_bundle_sha = _verify_hash_field(
                bundle_section.get("bundle_identity_sha256"),
                "bundle.bundle_identity_sha256",
            )
            export_id = bundle_section.get("export_id")
            if not isinstance(export_id, str) or not export_id.strip():
                raise BundleVerificationError("bundle.export_id must be a non-empty string")
            display_name = bundle_section.get("display_name")
            if display_name is not None and not isinstance(display_name, str):
                raise BundleVerificationError("bundle.display_name must be string or null")
            computed_bundle_sha256 = _canonical_json_sha256(
                {
                    "protocol": BUNDLE_IDENTITY_PROTOCOL,
                    "export_id": export_id,
                    "exported_at": exported_at,
                    "catalog_id": expected_catalog_id,
                    "display_name": display_name,
                    "input_identity_sha256": computed_input_sha256,
                }
            )
            if recorded_bundle_sha != computed_bundle_sha256:
                raise BundleVerificationError(
                    f"bundle_identity_sha256 mismatch: canonical identity hashes to "
                    f"{computed_bundle_sha256}, bundle claims {recorded_bundle_sha}"
                )

        # Verify results.csv header, row count, and status accounting
        csv_text = source.read_bytes("results.csv").decode("utf-8")
        reader = csv.DictReader(io.StringIO(csv_text))
        if reader.fieldnames is None:
            raise BundleVerificationError("results.csv has no header row")
        csv_columns = list(reader.fieldnames)
        rows = list(reader)
        if any(None in row for row in rows):
            raise BundleVerificationError("results.csv contains row(s) with extra unheadered fields")
        if any(any(v is None for v in row.values()) for row in rows):
            raise BundleVerificationError("results.csv contains truncated row(s) with missing columns")

        table_section = manifest.get("table")
        if fmt >= 4 and not isinstance(table_section, dict):
            raise BundleVerificationError(f"Format {fmt} bundle requires a 'table' section")
        if fmt >= 5 and not isinstance(manifest.get("v02_provenance"), dict):
            raise BundleVerificationError("Format 5 bundle requires a 'v02_provenance' section")
        if "total_parents" in manifest["counts"]:
            row_kind = "consensus_parent"
        elif "poses" in manifest["counts"]:
            row_kind = "pose"
        else:
            row_kind = "molecule"
        if isinstance(table_section, dict):
            if table_section.get("file") != "results.csv":
                raise BundleVerificationError(
                    f"Unsupported table.file: {table_section.get('file')!r}"
                )
            declared_row = table_section.get("row")
            if declared_row not in {"molecule", "pose", "consensus_parent"}:
                raise BundleVerificationError(f"Invalid table.row: {declared_row!r}")
            row_kind = declared_row
            declared_cols = table_section.get("columns")
            if not isinstance(declared_cols, list) or csv_columns != declared_cols:
                raise BundleVerificationError(
                    f"results.csv header {csv_columns} does not match manifest table.columns {declared_cols}"
                )

        counts = manifest["counts"]
        if row_kind == "consensus_parent":
            total_parents = counts.get("total_parents")
            full_profile = counts.get("full_profile")
            partial_unscored = counts.get("partial_or_unscored")
            if (
                not isinstance(total_parents, int)
                or isinstance(total_parents, bool)
                or not isinstance(full_profile, int)
                or isinstance(full_profile, bool)
                or not isinstance(partial_unscored, int)
                or isinstance(partial_unscored, bool)
                or total_parents != full_profile + partial_unscored
                or len(rows) != total_parents
            ):
                raise BundleVerificationError(
                    f"Consensus parent row count ({len(rows)}) disagrees with manifest counts {counts}"
                )
            seen_partial = False
            observed_full = 0
            observed_partial = 0
            prev_rank = 0
            for idx, row in enumerate(rows, start=1):
                tier = row.get("tier")
                if tier == "full_profile":
                    if seen_partial:
                        raise BundleVerificationError(
                            "ADR-030 E6 violation: full_profile row appears after partial_or_unscored row"
                        )
                    observed_full += 1
                    raw_rank = (row.get("rank") or "").strip()
                    raw_pcq = (row.get("pcq_score") or "").strip()
                    if not raw_rank.isdigit() or int(raw_rank) < prev_rank or int(raw_rank) > idx:
                        raise BundleVerificationError(
                            f"Invalid full_profile rank {raw_rank!r} at row {idx}"
                        )
                    prev_rank = int(raw_rank)
                    try:
                        pcq_val = float(raw_pcq)
                    except ValueError as err:
                        raise BundleVerificationError(
                            f"Invalid full_profile pcq_score {raw_pcq!r} at row {idx}"
                        ) from err
                    if not (0.0 <= pcq_val <= 100.0):
                        raise BundleVerificationError(
                            f"Out-of-range pcq_score {pcq_val} at row {idx}"
                        )
                elif tier == "partial_or_unscored":
                    seen_partial = True
                    observed_partial += 1
                    if (row.get("rank") or "").strip() or (row.get("pcq_score") or "").strip():
                        raise BundleVerificationError(
                            f"ADR-030 E6 violation: partial_or_unscored row {idx} carries rank or imputed score"
                        )
                    if not (row.get("failure_or_exclusion_codes") or "").strip():
                        raise BundleVerificationError(
                            f"ADR-030 E6 violation: partial_or_unscored row {idx} lacks failure_or_exclusion_codes"
                        )
                else:
                    raise BundleVerificationError(f"Unknown consensus tier {tier!r} at row {idx}")
            if observed_full != full_profile or observed_partial != partial_unscored:
                raise BundleVerificationError(
                    f"Consensus tier counts (full={observed_full}, partial={observed_partial}) "
                    f"disagree with manifest counts {counts}"
                )
        elif row_kind == "pose":
            if counts.get("ligands") != 1 or counts.get("poses") != len(rows):
                raise BundleVerificationError(
                    f"Pose row count ({len(rows)}) disagrees with manifest counts {counts}"
                )
        else:
            selected = counts.get("selected")
            succeeded = counts.get("succeeded")
            failed = counts.get("failed")
            if (
                not isinstance(selected, int)
                or not isinstance(succeeded, int)
                or not isinstance(failed, int)
                or selected != succeeded + failed
                or len(rows) != selected
            ):
                raise BundleVerificationError(
                    f"Molecule row count ({len(rows)}) disagrees with manifest counts {counts}"
                )
            completed_rows = sum(1 for r in rows if r.get("status") == "completed")
            non_completed_rows = len(rows) - completed_rows
            if completed_rows != succeeded or non_completed_rows != failed:
                raise BundleVerificationError(
                    f"results.csv status breakdown (completed={completed_rows}, other={non_completed_rows}) "
                    f"disagrees with manifest counts (succeeded={succeeded}, failed={failed})"
                )

        # Verify recorded M9 evidence files (pose interactions, figures, redocking verdicts)
        verified_evidence_files = 0
        evidence = manifest["recorded_evidence"]
        for item in evidence.get("pose_interaction_analyses") or []:
            _verify_referenced_blob(
                source,
                rel_path=item.get("path"),
                expected_sha256=item.get("sha256"),
                expected_size=item.get("size_bytes"),
                label=f"pose_interaction {item.get('analysis_id')}",
            )
            verified_evidence_files += 1

        for fig in evidence.get("figures") or []:
            _verify_referenced_blob(
                source,
                rel_path=fig.get("record_path"),
                expected_sha256=fig.get("record_sha256"),
                expected_size=fig.get("record_size_bytes"),
                label=f"figure record {fig.get('figure_id')}",
            )
            verified_evidence_files += 1
            for fitem in fig.get("files") or []:
                _verify_referenced_blob(
                    source,
                    rel_path=fitem.get("path"),
                    expected_sha256=fitem.get("sha256"),
                    expected_size=fitem.get("size_bytes"),
                    label=f"figure file {fig.get('figure_id')}/{fitem.get('filename')}",
                )
                verified_evidence_files += 1

        for val in evidence.get("redocking_validations") or []:
            _verify_referenced_blob(
                source,
                rel_path=val.get("path"),
                expected_sha256=val.get("sha256"),
                expected_size=val.get("size_bytes"),
                label=f"redocking validation {val.get('validation_id')}",
            )
            verified_evidence_files += 1
            ref = val.get("reference")
            if isinstance(ref, dict):
                _verify_referenced_blob(
                    source,
                    rel_path=ref.get("path"),
                    expected_sha256=ref.get("sha256"),
                    expected_size=ref.get("size_bytes"),
                    label=f"redocking reference {val.get('validation_id')}",
                )
                verified_evidence_files += 1

        # Verify v0.2 M2/M3/M4/M5 recorded evidence files (Export v5)
        v02_verified_evidence_files = 0
        for item in evidence.get("pose_quality_assessments") or []:
            _verify_referenced_blob(
                source,
                rel_path=item.get("path"),
                expected_sha256=item.get("sha256"),
                expected_size=item.get("size_bytes"),
                label=f"pose_quality {item.get('assessment_id')}",
            )
            verified_evidence_files += 1
            v02_verified_evidence_files += 1

        for item in evidence.get("interaction_rule_evaluations") or []:
            _verify_referenced_blob(
                source,
                rel_path=item.get("path"),
                expected_sha256=item.get("sha256"),
                expected_size=item.get("size_bytes"),
                label=f"interaction_rule_evaluation {item.get('evaluation_id')}",
            )
            verified_evidence_files += 1
            v02_verified_evidence_files += 1

        for item in evidence.get("interaction_rule_sets") or []:
            _verify_referenced_blob(
                source,
                rel_path=item.get("path"),
                expected_sha256=item.get("sha256"),
                expected_size=item.get("size_bytes"),
                label=f"interaction_rule_set {item.get('rule_set_id')}",
            )
            verified_evidence_files += 1
            v02_verified_evidence_files += 1

        for item in evidence.get("consensus_records") or []:
            _verify_referenced_blob(
                source,
                rel_path=item.get("path"),
                expected_sha256=item.get("sha256"),
                expected_size=item.get("size_bytes"),
                label=f"consensus_record {item.get('consensus_id')}",
            )
            verified_evidence_files += 1
            v02_verified_evidence_files += 1

        for item in evidence.get("reference_panels") or []:
            _verify_referenced_blob(
                source,
                rel_path=item.get("path"),
                expected_sha256=item.get("sha256"),
                expected_size=item.get("size_bytes"),
                label=f"reference_panel {item.get('panel_id')}",
            )
            verified_evidence_files += 1
            v02_verified_evidence_files += 1

        for item in evidence.get("calibration_records") or []:
            _verify_referenced_blob(
                source,
                rel_path=item.get("path"),
                expected_sha256=item.get("sha256"),
                expected_size=item.get("size_bytes"),
                label=f"calibration_record {item.get('calibration_id')}",
            )
            verified_evidence_files += 1
            v02_verified_evidence_files += 1
            for stage_item in item.get("stage_files") or []:
                _verify_referenced_blob(
                    source,
                    rel_path=stage_item.get("path"),
                    expected_sha256=stage_item.get("sha256"),
                    expected_size=stage_item.get("size_bytes"),
                    label=f"calibration stage {item.get('calibration_id')}/{stage_item.get('filename')}",
                )
                verified_evidence_files += 1
                v02_verified_evidence_files += 1

        # Verify ADR-033 Hit-to-Analog & POSE_FOCUSED artifacts (Export v6)
        analog_verified_files = 0
        for item in evidence.get("analog_expansion_artifacts") or []:
            _verify_referenced_blob(
                source,
                rel_path=item.get("path"),
                expected_sha256=item.get("sha256"),
                expected_size=item.get("size_bytes"),
                label=f"analog_expansion {item.get('kind')}:{item.get('artifact_id')}",
            )
            verified_evidence_files += 1
            v02_verified_evidence_files += 1
            analog_verified_files += 1

        if fmt >= 6:
            analog_prov = manifest.get("analog_expansion_provenance")
            if not isinstance(analog_prov, dict) or not analog_prov:
                raise BundleVerificationError(
                    "Export v6 bundle is missing required analog_expansion_provenance metadata"
                )
            if analog_verified_files < 1:
                raise BundleVerificationError(
                    "Export v6 bundle must carry at least one verified analog_expansion artifact"
                )

        # Verify preserved source_files (GNINA single-job & screening bundles)
        verified_source_files = 0
        matched_recorded_hashes = 0
        source_files_section = manifest.get("source_files")
        if source_files_section is not None:
            if not isinstance(source_files_section, dict) or not isinstance(
                source_files_section.get("files"), list
            ):
                raise BundleVerificationError("manifest.json source_files.files must be a list")
            for sfile in source_files_section["files"]:
                if not isinstance(sfile, dict):
                    raise BundleVerificationError("source_files.files entry must be an object")
                integrity = sfile.get("integrity")
                if integrity not in ALLOWED_SOURCE_INTEGRITY:
                    raise BundleVerificationError(
                        f"Invalid source_files integrity mode {integrity!r} for {sfile.get('path')!r}"
                    )
                _verify_referenced_blob(
                    source,
                    rel_path=sfile.get("path"),
                    expected_sha256=sfile.get("sha256"),
                    expected_size=sfile.get("size_bytes"),
                    label=f"source_file {sfile.get('path')}",
                )
                rec_sha = sfile.get("recorded_sha256")
                if integrity == "matches_recorded_sha256":
                    want_rec = _verify_hash_field(
                        rec_sha, f"recorded_sha256 ({sfile.get('path')})"
                    )
                    if want_rec != sfile.get("sha256"):
                        raise BundleVerificationError(
                            f"source_files entry {sfile.get('path')} claims matches_recorded_sha256 "
                            f"but sha256 ({sfile.get('sha256')}) != recorded_sha256 ({want_rec})"
                        )
                    matched_recorded_hashes += 1
                elif rec_sha is not None:
                    raise BundleVerificationError(
                        f"source_files entry {sfile.get('path')} has export_time_digest_only "
                        f"but non-null recorded_sha256"
                    )
                verified_source_files += 1

        # When verifying an export directory that holds its portable .zip archive,
        # cross-check that the embedded ZIP matches the directory contents byte-for-byte.
        embedded_zip_verified = False
        if source.kind == "directory" and isinstance(bundle_section, dict):
            archive_name = bundle_section.get("archive_filename")
            if isinstance(archive_name, str) and source.has_file(archive_name):
                zip_path = source.target / archive_name
                with _BundleSource(zip_path) as embedded_zip:
                    expected_members = source.files() - {archive_name}
                    if embedded_zip.files() != expected_members:
                        raise BundleVerificationError(
                            f"Embedded archive {archive_name} file list differs from export directory"
                        )
                    for member in sorted(expected_members):
                        if embedded_zip.sha256_and_size(member) != source.sha256_and_size(member):
                            raise BundleVerificationError(
                                f"Embedded archive {archive_name} differs from directory on {member}"
                            )
                embedded_zip_verified = True

        return {
            "verified": True,
            "target": str(source.target),
            "bundle_container": source.kind,
            "ankora_export_format": fmt,
            "catalog_id": (
                bundle_section.get("catalog_id")
                if isinstance(bundle_section, dict)
                else f"{manifest.get('source_kind')}:{manifest.get('source_id')}"
            ),
            "engine": f"{engine['name']} {engine['version']}",
            "row_kind": row_kind,
            "row_count": len(rows),
            "input_identity_sha256": computed_input_sha256,
            "bundle_identity_sha256": computed_bundle_sha256,
            "verified_evidence_files": verified_evidence_files,
            "v02_verified_evidence_files": v02_verified_evidence_files,
            "analog_verified_evidence_files": analog_verified_files,
            "verified_source_files": verified_source_files,
            "matched_recorded_hashes": matched_recorded_hashes,
            "embedded_zip_verified": embedded_zip_verified,
        }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "bundle",
        type=Path,
        help="Path to an Ankora *_bundle.zip archive or exported campaign directory.",
    )
    parser.add_argument(
        "--require-format",
        type=int,
        choices=sorted(SUPPORTED_EXPORT_FORMATS),
        default=None,
        help="Require an exact ankora_export_format version (e.g. 4).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON verification report.",
    )
    args = parser.parse_args(argv)

    try:
        report = verify_bundle(args.bundle, require_format=args.require_format)
    except BundleVerificationError as err:
        if args.json:
            print(json.dumps({"verified": False, "error": str(err)}, indent=2))
        else:
            print(f"VERIFICATION FAILED: {err}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(
            f"VERIFIED OK: {Path(report['target']).name} "
            f"(format v{report['ankora_export_format']}, {report['engine']}, "
            f"{report['row_count']} {report['row_kind']} row(s), "
            f"{report['verified_source_files']} source file(s), "
            f"{report['verified_evidence_files']} evidence file(s), "
            f"inputs_sha256={report['input_identity_sha256'][:12]}...)"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
