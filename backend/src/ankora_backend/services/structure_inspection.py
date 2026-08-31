"""Read-only structure import and inspection for M1."""

import hashlib
import re
from collections.abc import Mapping
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path

import gemmi
import httpx

from ankora_backend import __version__
from ankora_backend.domain.errors import AnkoraDomainError
from ankora_backend.persistence.artifact_store import StructureArtifactStore
from ankora_backend.schemas.provenance import ProvenanceEvent, ToolIdentity
from ankora_backend.schemas.structures import (
    ChainSummary,
    HeterogenKind,
    HeterogenSummary,
    StructureArtifact,
    StructureFormat,
    StructureMetadata,
    StructureRecord,
    StructureSource,
)
from ankora_backend.schemas.warnings import StructuredWarning, WarningCode

MAX_STRUCTURE_BYTES = 50 * 1024 * 1024
RCSB_DOWNLOAD_URL = "https://files.rcsb.org/download/{pdb_id}.cif"
ALPHAFOLD_API_URL = "https://alphafold.ebi.ac.uk/api/prediction/{uniprot_id}"

_PDB_MISSING_RESIDUE = re.compile(
    r"^REMARK 465\s+(?:\d+\s+)?[A-Z0-9]{3}\s+\S\s*-?\d+[A-Z]?\s*$"
)
_PDB_MISSING_ATOM = re.compile(
    r"^REMARK 470\s+(?:\d+\s+)?[A-Z0-9]{3}\s+\S\s*-?\d+[A-Z]?\s+\S+"
)


def structure_format_from_filename(filename: str) -> StructureFormat:
    suffix = Path(filename).suffix.lower()
    if suffix == ".pdb":
        return StructureFormat.PDB
    if suffix in {".cif", ".mmcif"}:
        return StructureFormat.MMCIF
    raise AnkoraDomainError(
        code="UNSUPPORTED_STRUCTURE_FORMAT",
        stage="structure_import",
        message="Choose a PDB, CIF, or mmCIF coordinate file.",
        status_code=415,
        details={"filename": filename, "supported_extensions": [".pdb", ".cif", ".mmcif"]},
    )


def import_structure_bytes(
    *,
    content: bytes,
    filename: str,
    source: StructureSource,
    source_uri: str | None,
    store: StructureArtifactStore,
) -> StructureRecord:
    if not content:
        raise AnkoraDomainError(
            code="EMPTY_STRUCTURE_FILE",
            stage="structure_import",
            message="The selected structure file is empty.",
            status_code=422,
        )
    if len(content) > MAX_STRUCTURE_BYTES:
        raise AnkoraDomainError(
            code="STRUCTURE_FILE_TOO_LARGE",
            stage="structure_import",
            message="The structure exceeds Ankora's 50 MB M1 import limit.",
            status_code=413,
            details={"size_bytes": len(content), "limit_bytes": MAX_STRUCTURE_BYTES},
        )

    structure_format = structure_format_from_filename(filename)
    metadata, warnings = inspect_structure(content, structure_format)
    artifact_id = store.new_artifact_id()
    imported_at = datetime.now(UTC)
    artifact = StructureArtifact(
        artifact_id=artifact_id,
        original_filename=filename,
        format=structure_format,
        sha256=hashlib.sha256(content).hexdigest(),
        size_bytes=len(content),
        source=source,
        source_uri=source_uri,
        imported_at=imported_at,
    )
    provenance = ProvenanceEvent(
        event_id=f"structure-import-{artifact_id}",
        event_type="structure_imported",
        timestamp=imported_at,
        output_artifacts=[artifact_id],
        tool=ToolIdentity(name="ankora-structure-inspector", version=__version__),
        parameters={
            "source": source.value,
            "source_uri": source_uri,
            "format": structure_format.value,
            "sha256": artifact.sha256,
            "parser": "gemmi",
            "parser_version": version("gemmi"),
        },
        warnings=warnings,
    )
    record = StructureRecord(
        artifact=artifact,
        metadata=metadata,
        warnings=warnings,
        provenance=provenance,
        content_url=f"/structures/{artifact_id}/content",
    )
    store.create_artifact(artifact=artifact, content=content)
    store.save_record(record)
    return record


def inspect_structure(
    content: bytes, structure_format: StructureFormat
) -> tuple[StructureMetadata, list[StructuredWarning]]:
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise _parse_error("The structure is not valid UTF-8 text.", error) from error

    try:
        if structure_format is StructureFormat.PDB:
            structure = gemmi.read_pdb_string(content)
            cif_block = None
        else:
            cif_document = gemmi.cif.read_string(text)
            if len(cif_document) != 1:
                raise ValueError("A coordinate file must contain exactly one CIF data block")
            cif_block = cif_document.sole_block()
            structure = gemmi.make_structure_from_block(cif_block)
        structure.setup_entities()
    except (RuntimeError, ValueError) as error:
        raise _parse_error("Gemmi could not parse this coordinate file.", error) from error

    if len(structure) == 0:
        raise _parse_error("The coordinate file does not contain a structural model.")

    model = structure[0]
    chain_totals: dict[str, list[int]] = {}
    heterogens: list[HeterogenSummary] = []
    nonstandard: set[str] = set()
    atom_count = 0
    residue_count = 0
    alternate_count = 0

    for chain in model:
        chain_atoms = 0
        chain_residues = 0
        polymer_residues = 0
        for residue in chain:
            atoms = list(residue)
            if not atoms:
                continue
            residue_count += 1
            chain_residues += 1
            atom_count += len(atoms)
            chain_atoms += len(atoms)
            alternate_count += sum(1 for atom in atoms if atom.altloc not in {"\x00", " "})

            if residue.entity_type is gemmi.EntityType.Polymer:
                polymer_residues += 1
                residue_info = gemmi.find_tabulated_residue(residue.name)
                if not residue_info.is_standard():
                    nonstandard.add(residue.name.strip().upper())
                continue

            heterogens.append(
                HeterogenSummary(
                    name=residue.name.strip() or "UNK",
                    chain_id=chain.name,
                    sequence_number=residue.seqid.num,
                    insertion_code=_clean_char(residue.seqid.icode),
                    atom_count=len(atoms),
                    kind=_heterogen_kind(residue, atoms),
                )
            )
        totals = chain_totals.setdefault(chain.name, [0, 0, 0])
        totals[0] += chain_residues
        totals[1] += polymer_residues
        totals[2] += chain_atoms

    if atom_count == 0 or residue_count == 0:
        raise _parse_error("The coordinate file does not contain any atoms.")

    missing_residue_count, missing_atom_count = _missing_record_counts(text, cif_block)
    entry_id, title, method = _extract_header_metadata(text, structure_format, cif_block)
    resolution = float(structure.resolution) if structure.resolution > 0 else None
    nonstandard_names = sorted(name for name in nonstandard if name)
    chains = [
        ChainSummary(
            chain_id=chain_id,
            residue_count=totals[0],
            polymer_residue_count=totals[1],
            atom_count=totals[2],
        )
        for chain_id, totals in chain_totals.items()
    ]
    warnings = _build_warnings(
        alternate_count=alternate_count,
        missing_residue_count=missing_residue_count,
        missing_atom_count=missing_atom_count,
        nonstandard_names=nonstandard_names,
    )
    metadata = StructureMetadata(
        entry_id=entry_id,
        title=title,
        experimental_method=method,
        resolution_angstrom=resolution,
        model_count=len(structure),
        atom_count=atom_count,
        residue_count=residue_count,
        chains=chains,
        heterogens=heterogens,
        alternate_location_atom_count=alternate_count,
        missing_residue_count=missing_residue_count,
        missing_atom_count=missing_atom_count,
        nonstandard_polymer_residues=nonstandard_names,
    )
    return metadata, warnings


async def fetch_rcsb_mmcif(pdb_id: str) -> tuple[bytes, str]:
    url = RCSB_DOWNLOAD_URL.format(pdb_id=pdb_id)
    try:
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            response = await client.get(url, headers={"User-Agent": f"Ankora/{__version__}"})
    except httpx.HTTPError as error:
        raise AnkoraDomainError(
            code="RCSB_CONNECTION_FAILED",
            stage="structure_fetch",
            message="Ankora could not reach the RCSB structure archive.",
            status_code=502,
            details={"pdb_id": pdb_id, "reason": str(error)},
        ) from error
    if response.status_code == 404:
        raise AnkoraDomainError(
            code="PDB_ENTRY_NOT_FOUND",
            stage="structure_fetch",
            message=f"RCSB does not have a coordinate entry for {pdb_id}.",
            status_code=404,
            details={"pdb_id": pdb_id, "source_uri": url},
        )
    if not response.is_success:
        raise AnkoraDomainError(
            code="RCSB_DOWNLOAD_FAILED",
            stage="structure_fetch",
            message="RCSB returned an error while downloading the structure.",
            status_code=502,
            details={"pdb_id": pdb_id, "http_status": response.status_code},
        )
    if len(response.content) > MAX_STRUCTURE_BYTES:
        raise AnkoraDomainError(
            code="STRUCTURE_FILE_TOO_LARGE",
            stage="structure_fetch",
            message="The downloaded structure exceeds Ankora's 50 MB M1 import limit.",
            status_code=413,
            details={"pdb_id": pdb_id, "size_bytes": len(response.content)},
        )
    return response.content, url


async def fetch_alphafold_cif(uniprot_id: str) -> tuple[bytes, str]:
    api_url = ALPHAFOLD_API_URL.format(uniprot_id=uniprot_id)
    try:
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            response = await client.get(
                api_url,
                headers={"User-Agent": f"Ankora/{__version__}", "Accept": "application/json"},
            )
    except httpx.HTTPError as error:
        raise AnkoraDomainError(
            code="ALPHAFOLD_CONNECTION_FAILED",
            stage="structure_fetch",
            message="Ankora could not reach the AlphaFold DB prediction service.",
            status_code=502,
            details={"uniprot_id": uniprot_id, "reason": str(error)},
        ) from error
    if not response.is_success:
        raise AnkoraDomainError(
            code="ALPHAFOLD_LOOKUP_FAILED",
            stage="structure_fetch",
            message="AlphaFold DB returned an error while looking up the prediction.",
            status_code=502,
            details={"uniprot_id": uniprot_id, "http_status": response.status_code},
        )
    payload: object = response.json()
    if not isinstance(payload, list):
        raise AnkoraDomainError(
            code="ALPHAFOLD_LOOKUP_FAILED",
            stage="structure_fetch",
            message="AlphaFold DB returned an unexpected prediction response.",
            status_code=502,
            details={"uniprot_id": uniprot_id},
        )
    entries = [entry for entry in payload if isinstance(entry, dict)]
    entry = next(
        (candidate for candidate in entries if str(candidate.get("entryId", "")).endswith("-F1")),
        entries[0] if entries else None,
    )
    if entry is None:
        raise AnkoraDomainError(
            code="ALPHAFOLD_PREDICTION_NOT_FOUND",
            stage="structure_fetch",
            message=f"AlphaFold DB has no prediction for UniProt accession {uniprot_id}.",
            status_code=404,
            details={"uniprot_id": uniprot_id, "source_uri": api_url},
        )
    cif_url = entry.get("cifUrl")
    if not isinstance(cif_url, str) or not cif_url:
        raise AnkoraDomainError(
            code="ALPHAFOLD_PREDICTION_INCOMPLETE",
            stage="structure_fetch",
            message="The AlphaFold DB prediction record does not include an mmCIF download URL.",
            status_code=502,
            details={"uniprot_id": uniprot_id},
        )
    try:
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            model_response = await client.get(
                cif_url,
                headers={"User-Agent": f"Ankora/{__version__}"},
            )
    except httpx.HTTPError as error:
        raise AnkoraDomainError(
            code="ALPHAFOLD_CONNECTION_FAILED",
            stage="structure_fetch",
            message="Ankora could not download the predicted model from AlphaFold DB.",
            status_code=502,
            details={"uniprot_id": uniprot_id, "source_uri": cif_url, "reason": str(error)},
        ) from error
    if model_response.status_code == 404:
        raise AnkoraDomainError(
            code="ALPHAFOLD_MODEL_NOT_FOUND",
            stage="structure_fetch",
            message=f"AlphaFold DB does not have a downloadable model for {uniprot_id}.",
            status_code=404,
            details={"uniprot_id": uniprot_id, "source_uri": cif_url},
        )
    if not model_response.is_success:
        raise AnkoraDomainError(
            code="ALPHAFOLD_DOWNLOAD_FAILED",
            stage="structure_fetch",
            message="AlphaFold DB returned an error while downloading the predicted model.",
            status_code=502,
            details={"uniprot_id": uniprot_id, "http_status": model_response.status_code},
        )
    if len(model_response.content) > MAX_STRUCTURE_BYTES:
        raise AnkoraDomainError(
            code="STRUCTURE_FILE_TOO_LARGE",
            stage="structure_fetch",
            message="The downloaded structure exceeds Ankora's 50 MB M1 import limit.",
            status_code=413,
            details={"uniprot_id": uniprot_id, "size_bytes": len(model_response.content)},
        )
    return model_response.content, cif_url


def _heterogen_kind(residue: gemmi.Residue, atoms: list[gemmi.Atom]) -> HeterogenKind:
    if residue.is_water():
        return HeterogenKind.WATER
    if len(atoms) == 1 and atoms[0].element.is_metal:
        return HeterogenKind.METAL
    if residue.entity_type is gemmi.EntityType.NonPolymer:
        return HeterogenKind.LIGAND
    return HeterogenKind.OTHER


def _missing_record_counts(
    text: str, cif_block: gemmi.cif.Block | None
) -> tuple[int, int]:
    if cif_block is None:
        lines = text.splitlines()
        return (
            sum(bool(_PDB_MISSING_RESIDUE.match(line)) for line in lines),
            sum(bool(_PDB_MISSING_ATOM.match(line)) for line in lines),
        )
    return (
        _category_row_count(cif_block, "_pdbx_unobs_or_zero_occ_residues."),
        _category_row_count(cif_block, "_pdbx_unobs_or_zero_occ_atoms."),
    )


def _category_row_count(block: gemmi.cif.Block, prefix: str) -> int:
    category = block.get_mmcif_category(prefix)
    if not category:
        return 0
    first_column: list[str] = next(iter(category.values()), [])
    return len(first_column)


def _extract_header_metadata(
    text: str,
    structure_format: StructureFormat,
    cif_block: gemmi.cif.Block | None,
) -> tuple[str | None, str | None, str | None]:
    if structure_format is StructureFormat.PDB:
        lines = text.splitlines()
        header = next((line for line in lines if line.startswith("HEADER")), "")
        entry_id = header[62:66].strip() or None
        title_parts = [line[10:].strip() for line in lines if line.startswith("TITLE ")]
        method_parts = [line[10:].strip() for line in lines if line.startswith("EXPDTA")]
        return entry_id, _joined(title_parts), _joined(method_parts)
    assert cif_block is not None
    entry_id = _cif_value(cif_block, "_entry.id")
    title = _cif_value(cif_block, "_struct.title")
    method = _cif_value(cif_block, "_exptl.method")
    return entry_id, title, method


def _cif_value(block: gemmi.cif.Block, tag: str) -> str | None:
    value = block.find_value(tag)
    if value is None:
        return None
    normalized = gemmi.cif.as_string(str(value)).strip()
    return normalized if normalized not in {"", ".", "?"} else None


def _joined(parts: list[str]) -> str | None:
    return " ".join(part for part in parts if part).strip() or None


def _clean_char(value: str) -> str:
    return "" if value in {"\x00", " ", ".", "?"} else value


def _build_warnings(
    *,
    alternate_count: int,
    missing_residue_count: int,
    missing_atom_count: int,
    nonstandard_names: list[str],
) -> list[StructuredWarning]:
    warning_specs: list[tuple[WarningCode, str, Mapping[str, object]]] = []
    if missing_residue_count:
        warning_specs.append(
            (
                WarningCode.STR_MISSING_RESIDUES,
                "The source reports residues without observed coordinates.",
                {"count": missing_residue_count},
            )
        )
    if missing_atom_count:
        warning_specs.append(
            (
                WarningCode.STR_MISSING_ATOMS,
                "The source reports atoms without observed coordinates.",
                {"count": missing_atom_count},
            )
        )
    if alternate_count:
        warning_specs.append(
            (
                WarningCode.STR_ALTERNATE_LOCATIONS,
                "The structure contains alternate atom locations.",
                {"atom_count": alternate_count},
            )
        )
    if nonstandard_names:
        warning_specs.append(
            (
                WarningCode.STR_NONSTANDARD_POLYMER_RESIDUES,
                "The polymer contains nonstandard residue names.",
                {"residue_names": nonstandard_names},
            )
        )
    return [
        StructuredWarning(
            code=code,
            message=message,
            stage="structure_inspection",
            details=dict(details),
        )
        for code, message, details in warning_specs
    ]


def _parse_error(message: str, error: Exception | None = None) -> AnkoraDomainError:
    details: dict[str, object] = {}
    if error is not None:
        details["parser_message"] = str(error)
    return AnkoraDomainError(
        code="STRUCTURE_PARSE_FAILED",
        stage="structure_inspection",
        message=message,
        status_code=422,
        details=details,
    )
