"""100% offline RDKit 2D analog catalog parsing, SQLite FP caching, and similarity search.

Zero network calls and zero new dependencies (`rdkit==2025.9.6` + stdlib `sqlite3`/`csv`).
Search-time normalization (optional salt stripping or tautomer canonicalization) operates
strictly on ephemeral search copies and never modifies immutable catalog bytes or bypasses
ADR-016 screening microstate curation.
"""

from __future__ import annotations

import csv
import sqlite3
from dataclasses import dataclass
from importlib import import_module
from io import BytesIO, StringIO
from pathlib import Path
from typing import Any

from ankora_backend.domain.errors import AnkoraDomainError
from ankora_backend.schemas.analog_expansion import (
    MAX_ANALOG_CATALOG_BYTES,
    MAX_ANALOG_CATALOG_RECORDS,
    AnalogCandidateRole,
    AnalogCatalogEntry,
    AnalogCatalogFormat,
    AnalogFingerprintProfile,
    AnalogSearchHit,
    CsvCatalogSchema,
)
from ankora_backend.schemas.warnings import StructuredWarning, WarningCode

Chem: Any = import_module("rdkit.Chem")
DataStructs: Any = import_module("rdkit.DataStructs")
Descriptors: Any = import_module("rdkit.Chem.Descriptors")
Lipinski: Any = import_module("rdkit.Chem.Lipinski")
rdBase: Any = import_module("rdkit.rdBase")
rdFingerprintGenerator: Any = import_module("rdkit.Chem.rdFingerprintGenerator")
rdMolStandardize: Any = import_module("rdkit.Chem.MolStandardize.rdMolStandardize")

_STAGE = "analog_similarity"

_FORMAT_BY_SUFFIX: dict[str, AnalogCatalogFormat] = {
    ".sdf": AnalogCatalogFormat.SDF,
    ".smi": AnalogCatalogFormat.SMI,
    ".smiles": AnalogCatalogFormat.SMILES,
    ".csv": AnalogCatalogFormat.CSV,
}


@dataclass(frozen=True, slots=True)
class ParsedCatalog:
    source_format: AnalogCatalogFormat
    entries: list[AnalogCatalogEntry]
    valid_records: int
    invalid_records: int


@dataclass(frozen=True, slots=True)
class OfflineSimilarityResult:
    query_canonical_isomeric_smiles: str
    query_search_smiles: str
    rdkit_version: str
    total_evaluated: int
    invalid_skipped: int
    truncated_by_top_k: bool
    cache_hit: bool
    hits: list[AnalogSearchHit]
    warnings: list[StructuredWarning]


def rdkit_version_string() -> str:
    return str(rdBase.rdkitVersion)


def _error(
    code: str,
    message: str,
    *,
    status_code: int = 422,
    details: dict[str, object] | None = None,
) -> AnkoraDomainError:
    return AnkoraDomainError(
        code=code,
        stage=_STAGE,
        message=message,
        status_code=status_code,
        details=details or {},
    )


def build_search_representation(
    mol: Any,
    profile: AnalogFingerprintProfile,
) -> tuple[str, str, bool, int]:
    """Return `(canonical_isomeric_smiles, search_smiles, had_multiple_fragments, undef_stereo)`.

    Search-only standardization runs strictly on a cloned RDKit molecule and never mutates
    the caller's molecule or replaces ADR-016 curation.
    """
    canonical_isomeric = str(Chem.MolToSmiles(mol, isomericSmiles=True, canonical=True))
    fragments = Chem.GetMolFrags(mol, asMols=False)
    had_multiple_fragments = len(fragments) > 1

    chiral_centers = Chem.FindMolChiralCenters(mol, includeUnassigned=True)
    undef_stereo = sum(1 for _, label in chiral_centers if label == "?")

    work = Chem.Mol(mol)
    if profile.strip_salts_for_search_only and had_multiple_fragments:
        chooser = rdMolStandardize.LargestFragmentChooser(preferOrganic=True)
        work = chooser.choose(work)
    if profile.canonicalize_tautomers_for_search_only:
        enumerator = rdMolStandardize.TautomerEnumerator()
        work = enumerator.Canonicalize(work)
    search_smiles = str(Chem.MolToSmiles(work, isomericSmiles=True, canonical=True))
    return canonical_isomeric, search_smiles, had_multiple_fragments, undef_stereo


def _inspect_entry(
    mol: Any | None,
    *,
    record_index: int,
    identifier: str,
    raw_smiles: str | None,
    profile: AnalogFingerprintProfile,
    parse_error: str | None = None,
) -> AnalogCatalogEntry:
    if mol is None or parse_error is not None:
        return AnalogCatalogEntry(
            record_index=record_index,
            identifier=identifier,
            raw_smiles=raw_smiles,
            parse_error=parse_error or "RDKit failed to parse or sanitize molecule.",
        )
    try:
        canonical_iso, search_smi, multi_frag, undef_stereo = build_search_representation(
            mol, profile
        )
        mw = float(Descriptors.MolWt(mol))
        heavy = int(mol.GetNumHeavyAtoms())
        rot = int(Lipinski.NumRotatableBonds(mol))
        if heavy < 1 or mw <= 0.0:
            raise ValueError("Molecule has zero heavy atoms.")
    except Exception as exc:  # noqa: BLE001
        return AnalogCatalogEntry(
            record_index=record_index,
            identifier=identifier,
            raw_smiles=raw_smiles,
            parse_error=f"Descriptor inspection failed: {exc}",
        )
    return AnalogCatalogEntry(
        record_index=record_index,
        identifier=identifier,
        raw_smiles=raw_smiles,
        canonical_isomeric_smiles=canonical_iso,
        search_smiles=search_smi,
        had_multiple_fragments=multi_frag,
        undefined_stereocenter_count=undef_stereo,
        molecular_weight_g_mol=round(mw, 4),
        heavy_atom_count=heavy,
        rotatable_bond_count=rot,
        parse_error=None,
    )


def parse_local_analog_catalog(
    *,
    content: bytes,
    filename: str,
    csv_schema: CsvCatalogSchema | None = None,
    profile: AnalogFingerprintProfile | None = None,
) -> ParsedCatalog:
    """Parse local SDF, SMI/SMILES, or explicit-schema CSV catalog without silent drops."""
    if not content:
        raise _error("ANALOG_CATALOG_EMPTY", "The selected analog catalog file is empty.")
    if len(content) > MAX_ANALOG_CATALOG_BYTES:
        raise _error(
            "ANALOG_CATALOG_TOO_LARGE",
            f"The analog catalog exceeds the {MAX_ANALOG_CATALOG_BYTES // (1024 * 1024)} MiB cap.",
            status_code=413,
            details={"max_bytes": MAX_ANALOG_CATALOG_BYTES, "received_bytes": len(content)},
        )

    suffix = Path(filename).suffix.lower()
    source_format = _FORMAT_BY_SUFFIX.get(suffix)
    if source_format is None:
        raise _error(
            "ANALOG_CATALOG_FORMAT_UNSUPPORTED",
            "Use a local .sdf, .smi, .smiles, or .csv analog catalog.",
            details={"filename": filename},
        )
    active_profile = profile or AnalogFingerprintProfile()
    entries: list[AnalogCatalogEntry] = []

    if source_format is AnalogCatalogFormat.SDF:
        supplier = Chem.ForwardSDMolSupplier(BytesIO(content), sanitize=True, removeHs=False)
        for idx, mol in enumerate(supplier):
            if idx >= MAX_ANALOG_CATALOG_RECORDS:
                raise _error(
                    "ANALOG_CATALOG_TOO_MANY_RECORDS",
                    f"Analog catalog exceeds the v0.2 limit of {MAX_ANALOG_CATALOG_RECORDS} rows.",
                    details={"max_records": MAX_ANALOG_CATALOG_RECORDS},
                )
            ident = f"record_{idx + 1}"
            if mol is not None and mol.HasProp("_Name"):
                prop_name = str(mol.GetProp("_Name")).strip()
                if prop_name:
                    ident = prop_name
            entries.append(
                _inspect_entry(
                    mol,
                    record_index=idx,
                    identifier=ident,
                    raw_smiles=None,
                    profile=active_profile,
                )
            )
    elif source_format in {AnalogCatalogFormat.SMI, AnalogCatalogFormat.SMILES}:
        try:
            decoded = content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise _error(
                "ANALOG_CATALOG_ENCODING_INVALID",
                "SMILES catalog must be valid UTF-8 text.",
            ) from exc
        idx = 0
        for raw_line in decoded.splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if idx >= MAX_ANALOG_CATALOG_RECORDS:
                raise _error(
                    "ANALOG_CATALOG_TOO_MANY_RECORDS",
                    f"Analog catalog exceeds the v0.2 limit of {MAX_ANALOG_CATALOG_RECORDS} rows.",
                    details={"max_records": MAX_ANALOG_CATALOG_RECORDS},
                )
            parts = line.split()
            smi = parts[0]
            ident = " ".join(parts[1:]).strip() if len(parts) > 1 else f"record_{idx + 1}"
            mol = Chem.MolFromSmiles(smi)
            entries.append(
                _inspect_entry(
                    mol,
                    record_index=idx,
                    identifier=ident,
                    raw_smiles=smi,
                    profile=active_profile,
                    parse_error=None if mol is not None else "Invalid SMILES string.",
                )
            )
            idx += 1
    else:
        if csv_schema is None:
            raise _error(
                "ANALOG_CSV_SCHEMA_REQUIRED",
                "CSV analog catalogs require an explicit CsvCatalogSchema (smiles_column, etc.).",
            )
        try:
            decoded = content.decode(csv_schema.encoding)
        except (LookupError, UnicodeDecodeError) as exc:
            raise _error(
                "ANALOG_CATALOG_ENCODING_INVALID",
                f"Could not decode CSV catalog with encoding '{csv_schema.encoding}'.",
                details={"encoding": csv_schema.encoding},
            ) from exc
        reader = csv.DictReader(StringIO(decoded), delimiter=csv_schema.delimiter)
        fieldnames = reader.fieldnames or []
        if csv_schema.smiles_column not in fieldnames:
            raise _error(
                "ANALOG_CSV_COLUMN_MISSING",
                f"CSV catalog does not contain SMILES column '{csv_schema.smiles_column}'.",
                details={"available_columns": list(fieldnames)},
            )
        if csv_schema.id_column is not None and csv_schema.id_column not in fieldnames:
            raise _error(
                "ANALOG_CSV_COLUMN_MISSING",
                f"CSV catalog does not contain ID column '{csv_schema.id_column}'.",
                details={"available_columns": list(fieldnames)},
            )
        for idx, row in enumerate(reader):
            if idx >= MAX_ANALOG_CATALOG_RECORDS:
                raise _error(
                    "ANALOG_CATALOG_TOO_MANY_RECORDS",
                    f"Analog catalog exceeds the v0.2 limit of {MAX_ANALOG_CATALOG_RECORDS} rows.",
                    details={"max_records": MAX_ANALOG_CATALOG_RECORDS},
                )
            raw_smi = (row.get(csv_schema.smiles_column) or "").strip()
            raw_id = (
                (row.get(csv_schema.id_column) or "").strip()
                if csv_schema.id_column is not None
                else ""
            )
            ident = raw_id or f"row_{idx + 1}"
            if not raw_smi:
                entries.append(
                    _inspect_entry(
                        None,
                        record_index=idx,
                        identifier=ident,
                        raw_smiles="",
                        profile=active_profile,
                        parse_error="Blank SMILES cell in CSV row.",
                    )
                )
                continue
            mol = Chem.MolFromSmiles(raw_smi)
            entries.append(
                _inspect_entry(
                    mol,
                    record_index=idx,
                    identifier=ident,
                    raw_smiles=raw_smi,
                    profile=active_profile,
                    parse_error=None if mol is not None else "Invalid SMILES string in CSV row.",
                )
            )

    if not entries:
        raise _error("ANALOG_CATALOG_EMPTY", "The analog catalog contained zero molecular records.")
    valid_count = sum(1 for item in entries if item.parse_error is None)
    invalid_count = len(entries) - valid_count
    return ParsedCatalog(
        source_format=source_format,
        entries=entries,
        valid_records=valid_count,
        invalid_records=invalid_count,
    )


class SqliteFingerprintCache:
    """Workspace-local SQLite fingerprint cache keyed by catalog/profile/RDKit digests."""

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS analog_fingerprints (
                    catalog_sha256 TEXT NOT NULL,
                    profile_sha256 TEXT NOT NULL,
                    rdkit_version TEXT NOT NULL,
                    record_index INTEGER NOT NULL,
                    fp_binary BLOB NOT NULL,
                    PRIMARY KEY (catalog_sha256, profile_sha256, rdkit_version, record_index)
                )
                """
            )
            conn.commit()

    def load_all(
        self, *, catalog_sha256: str, profile_sha256: str, rdkit_version: str
    ) -> dict[int, Any]:
        with sqlite3.connect(self._db_path) as conn:
            rows = conn.execute(
                """
                SELECT record_index, fp_binary
                FROM analog_fingerprints
                WHERE catalog_sha256 = ? AND profile_sha256 = ? AND rdkit_version = ?
                """,
                (catalog_sha256, profile_sha256, rdkit_version),
            ).fetchall()
        out: dict[int, Any] = {}
        for rec_idx, blob in rows:
            bv = DataStructs.ExplicitBitVect(blob)
            out[int(rec_idx)] = bv
        return out

    def store_batch(
        self,
        *,
        catalog_sha256: str,
        profile_sha256: str,
        rdkit_version: str,
        fps_by_index: dict[int, Any],
    ) -> None:
        if not fps_by_index:
            return
        with sqlite3.connect(self._db_path) as conn:
            conn.executemany(
                """
                INSERT OR REPLACE INTO analog_fingerprints
                (catalog_sha256, profile_sha256, rdkit_version, record_index, fp_binary)
                VALUES (?, ?, ?, ?, ?)
                """,
                [
                    (catalog_sha256, profile_sha256, rdkit_version, idx, fp.ToBinary())
                    for idx, fp in fps_by_index.items()
                ],
            )
            conn.commit()


def _make_morgan_generator(profile: AnalogFingerprintProfile) -> Any:
    return rdFingerprintGenerator.GetMorganGenerator(
        radius=profile.radius,
        fpSize=profile.fp_size,
        includeChirality=profile.include_chirality,
    )


def run_offline_similarity_search(
    *,
    query_smiles: str,
    seed_name: str,
    catalog_sha256: str,
    entries: list[AnalogCatalogEntry],
    profile: AnalogFingerprintProfile,
    min_tanimoto: float,
    top_k: int,
    smarts_filter: str | None = None,
    cache: SqliteFingerprintCache | None = None,
) -> OfflineSimilarityResult:
    """Execute deterministic 100% offline RDKit Morgan Tanimoto + optional graph SMARTS search."""
    q_mol = Chem.MolFromSmiles(query_smiles)
    if q_mol is None:
        raise _error(
            "ANALOG_QUERY_SMILES_INVALID",
            "Seed chemical state SMILES could not be parsed by RDKit.",
            details={"query_smiles": query_smiles},
        )
    q_iso, q_search, q_multi, q_undef = build_search_representation(q_mol, profile)
    q_work = Chem.MolFromSmiles(q_search)
    if q_work is None:
        raise _error("ANALOG_QUERY_SMILES_INVALID", "Normalized query SMILES failed RDKit parsing.")

    smarts_mol: Any | None = None
    if smarts_filter is not None:
        smarts_mol = Chem.MolFromSmarts(smarts_filter)
        if smarts_mol is None:
            raise _error(
                "ANALOG_SMARTS_INVALID",
                f"Substructure SMARTS pattern '{smarts_filter}' is invalid.",
                details={"smarts_filter": smarts_filter},
            )

    rdkit_ver = rdkit_version_string()
    profile_sha = profile.profile_sha256()
    gen = _make_morgan_generator(profile)
    q_fp = gen.GetFingerprint(q_work)

    cached_fps = (
        cache.load_all(
            catalog_sha256=catalog_sha256,
            profile_sha256=profile_sha,
            rdkit_version=rdkit_ver,
        )
        if cache is not None
        else {}
    )
    valid_entries = [e for e in entries if e.parse_error is None and e.canonical_isomeric_smiles]
    invalid_skipped = len(entries) - len(valid_entries)
    cache_hit = bool(valid_entries) and all(e.record_index in cached_fps for e in valid_entries)

    new_fps: dict[int, Any] = {}
    target_entries: list[AnalogCatalogEntry] = []
    target_fps: list[Any] = []
    search_smiles_by_idx: dict[int, str] = {}

    for entry in valid_entries:
        assert entry.canonical_isomeric_smiles is not None
        # Recompute search_smiles under the active profile (catalog may have been ingested
        # under a different search normalization profile!)
        mol = Chem.MolFromSmiles(entry.canonical_isomeric_smiles)
        if mol is None:
            invalid_skipped += 1
            continue
        _, s_smi, _, _ = build_search_representation(mol, profile)
        search_smiles_by_idx[entry.record_index] = s_smi
        fp = cached_fps.get(entry.record_index)
        if fp is None:
            s_mol = Chem.MolFromSmiles(s_smi)
            if s_mol is None:
                invalid_skipped += 1
                continue
            fp = gen.GetFingerprint(s_mol)
            new_fps[entry.record_index] = fp
        target_entries.append(entry)
        target_fps.append(fp)

    if cache is not None and new_fps:
        cache.store_batch(
            catalog_sha256=catalog_sha256,
            profile_sha256=profile_sha,
            rdkit_version=rdkit_ver,
            fps_by_index=new_fps,
        )

    sims = (
        list(DataStructs.BulkTanimotoSimilarity(q_fp, target_fps)) if target_fps else []
    )

    seed_hit = AnalogSearchHit(
        hit_id="seed-control",
        role=AnalogCandidateRole.SEED_CONTROL,
        identifier=seed_name,
        source_record_index=None,
        canonical_isomeric_smiles=q_iso,
        search_smiles=q_search,
        local_rdkit_tanimoto=1.0,
        provider_similarity=None,
        provider_compound_id=None,
        smarts_matched=(
            bool(q_mol.HasSubstructMatch(smarts_mol)) if smarts_mol is not None else None
        ),
        molecular_weight_g_mol=round(float(Descriptors.MolWt(q_mol)), 4),
        heavy_atom_count=int(q_mol.GetNumHeavyAtoms()),
        rotatable_bond_count=int(Lipinski.NumRotatableBonds(q_mol)),
        undefined_stereocenter_count=q_undef,
        had_multiple_fragments=q_multi,
        duplicate_of_hit_id=None,
    )

    matched_raw: list[tuple[float, str, int, AnalogCatalogEntry, bool | None]] = []
    for entry, sim_val in zip(target_entries, sims, strict=True):
        sim = min(1.0, max(0.0, float(sim_val)))
        if sim + 1e-12 < min_tanimoto:
            continue
        assert entry.canonical_isomeric_smiles is not None
        # Do not duplicate the exact stereochemical seed as a "new analog"
        if entry.canonical_isomeric_smiles == q_iso:
            continue
        smarts_ok: bool | None = None
        if smarts_mol is not None:
            cand_mol = Chem.MolFromSmiles(entry.canonical_isomeric_smiles)
            smarts_ok = bool(cand_mol is not None and cand_mol.HasSubstructMatch(smarts_mol))
            if not smarts_ok:
                continue
        matched_raw.append(
            (sim, entry.canonical_isomeric_smiles, entry.record_index, entry, smarts_ok)
        )

    # Deterministic order: highest Tanimoto, then canonical isomeric SMILES, then record index
    matched_raw.sort(key=lambda item: (-round(item[0], 12), item[1], item[2]))

    # Stereochemistry-preserving deduplication on canonical isomeric SMILES
    first_hit_by_iso: dict[str, str] = {}
    unique_analogs: list[AnalogSearchHit] = []
    for sim, iso_smi, rec_idx, entry, smarts_ok in matched_raw:
        hit_id = f"analog-{rec_idx}"
        dup_of = first_hit_by_iso.get(iso_smi)
        if dup_of is None:
            first_hit_by_iso[iso_smi] = hit_id
        else:
            # Skip duplicate exact isomeric structures from consuming top_k slots while keeping
            # the first deterministic representative (ADR-033 §4).
            continue
        assert entry.heavy_atom_count is not None
        assert entry.rotatable_bond_count is not None
        unique_analogs.append(
            AnalogSearchHit(
                hit_id=hit_id,
                role=AnalogCandidateRole.ANALOG,
                identifier=entry.identifier,
                source_record_index=rec_idx,
                canonical_isomeric_smiles=iso_smi,
                search_smiles=search_smiles_by_idx[rec_idx],
                local_rdkit_tanimoto=round(sim, 6),
                provider_similarity=None,
                provider_compound_id=None,
                smarts_matched=smarts_ok,
                molecular_weight_g_mol=entry.molecular_weight_g_mol,
                heavy_atom_count=entry.heavy_atom_count,
                rotatable_bond_count=entry.rotatable_bond_count,
                undefined_stereocenter_count=entry.undefined_stereocenter_count,
                had_multiple_fragments=entry.had_multiple_fragments,
                duplicate_of_hit_id=None,
            )
        )

    truncated = len(unique_analogs) > top_k
    retained_analogs = unique_analogs[:top_k]
    warnings: list[StructuredWarning] = []
    if truncated:
        warnings.append(
            StructuredWarning(
                code=WarningCode.ANALOG_SEARCH_TRUNCATED,
                stage=_STAGE,
                message=(
                    f"{len(unique_analogs)} analogs passed min_tanimoto >= {min_tanimoto:g}, "
                    f"capped to top_k={top_k} deterministic results."
                ),
                details={
                    "total_matched_unique": len(unique_analogs),
                    "top_k": top_k,
                    "min_tanimoto": min_tanimoto,
                },
            )
        )

    return OfflineSimilarityResult(
        query_canonical_isomeric_smiles=q_iso,
        query_search_smiles=q_search,
        rdkit_version=rdkit_ver,
        total_evaluated=len(target_entries),
        invalid_skipped=invalid_skipped,
        truncated_by_top_k=truncated,
        cache_hit=cache_hit,
        hits=[seed_hit, *retained_analogs],
        warnings=warnings,
    )
