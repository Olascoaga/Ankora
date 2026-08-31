"""Immutable local ligand import and read-only RDKit chemistry inspection."""

from datetime import UTC, datetime
from hashlib import sha256
from importlib import import_module
from io import BytesIO
from pathlib import Path
from typing import Any

from ankora_backend.domain.errors import AnkoraDomainError
from ankora_backend.persistence.ligand_store import LigandArtifactStore
from ankora_backend.schemas.ligands import (
    LigandArtifact,
    LigandChemicalStateArtifact,
    LigandFormat,
    LigandInspection,
    LigandLibraryArtifact,
    LigandLibraryEntry,
    LigandLibraryEntryFailure,
    LigandLibraryEntryStatus,
    LigandLibraryRecord,
    LigandRecord,
    LigandSource,
)
from ankora_backend.schemas.provenance import ProvenanceEvent, ToolIdentity
from ankora_backend.schemas.warnings import StructuredWarning, WarningCode

Chem: Any = import_module("rdkit.Chem")
Descriptors: Any = import_module("rdkit.Chem.Descriptors")
Lipinski: Any = import_module("rdkit.Chem.Lipinski")
rdBase: Any = import_module("rdkit.rdBase")
rdMolDescriptors: Any = import_module("rdkit.Chem.rdMolDescriptors")

MAX_LIGAND_BYTES = 100 * 1024 * 1024
MAX_LIGAND_RECORDS = 10_000
_FORMAT_BY_SUFFIX = {
    ".sdf": LigandFormat.SDF,
    ".mol": LigandFormat.MOL,
    ".smi": LigandFormat.SMILES,
    ".smiles": LigandFormat.SMILES,
}


def import_local_ligand(
    *, content: bytes, filename: str, store: LigandArtifactStore
) -> LigandRecord:
    if not content:
        raise _import_error("LIGAND_FILE_EMPTY", "The selected ligand file is empty.")
    if len(content) > MAX_LIGAND_BYTES:
        raise _import_error(
            "LIGAND_FILE_TOO_LARGE",
            "The ligand file exceeds the 100 MB local import limit.",
            details={"max_bytes": MAX_LIGAND_BYTES, "received_bytes": len(content)},
            status_code=413,
        )
    safe_filename = store.sanitize_filename(filename)
    ligand_format = _FORMAT_BY_SUFFIX.get(Path(safe_filename).suffix.lower())
    if ligand_format is None:
        raise _import_error(
            "LIGAND_FORMAT_UNSUPPORTED",
            "Use a local SDF, MOL, SMI, or SMILES file.",
            details={"filename": safe_filename},
        )
    molecule, supplied_name = _parse(content, ligand_format)
    return _store_local_molecule(
        molecule=molecule,
        supplied_name=supplied_name,
        original_content=content,
        original_filename=safe_filename,
        ligand_format=ligand_format,
        store=store,
        library_id=None,
        record_index=None,
    )


def import_local_ligand_library(
    *, content: bytes, filename: str, store: LigandArtifactStore
) -> LigandLibraryRecord:
    if not content:
        raise _import_error("LIGAND_FILE_EMPTY", "The selected ligand file is empty.")
    if len(content) > MAX_LIGAND_BYTES:
        raise _import_error(
            "LIGAND_FILE_TOO_LARGE",
            "The ligand library exceeds the 100 MB local import limit.",
            details={"max_bytes": MAX_LIGAND_BYTES, "received_bytes": len(content)},
            status_code=413,
        )
    safe_filename = store.sanitize_filename(filename)
    ligand_format = _FORMAT_BY_SUFFIX.get(Path(safe_filename).suffix.lower())
    if ligand_format is None:
        raise _import_error(
            "LIGAND_FORMAT_UNSUPPORTED",
            "Use a local SDF, MOL, SMI, or SMILES file.",
            details={"filename": safe_filename},
        )
    molecules = _parse_library_molecules(content, ligand_format)
    if not molecules:
        raise _import_error(
            "LIGAND_LIBRARY_EMPTY",
            "No molecular records were found in the selected ligand library.",
        )
    if len(molecules) > MAX_LIGAND_RECORDS:
        raise _import_error(
            "LIGAND_LIBRARY_RECORD_LIMIT_EXCEEDED",
            "This initial local workflow accepts at most 10,000 records per library.",
            details={
                "record_count": len(molecules),
                "maximum_records": MAX_LIGAND_RECORDS,
            },
            status_code=413,
        )
    library_id = store.new_library_id()
    entries: list[LigandLibraryEntry] = []
    imported_ids: list[str] = []
    stem = Path(safe_filename).stem or "library"
    for record_index, molecule in enumerate(molecules):
        if molecule is None or molecule.GetNumHeavyAtoms() == 0:
            entries.append(
                LigandLibraryEntry(
                    record_index=record_index,
                    status=LigandLibraryEntryStatus.FAILED,
                    failure=LigandLibraryEntryFailure(
                        code="LIGAND_LIBRARY_RECORD_PARSE_FAILED",
                        message="RDKit could not parse and sanitize this molecular record.",
                    ),
                )
            )
            continue
        supplied_name = (
            molecule.GetProp("_Name").strip() if molecule.HasProp("_Name") else None
        )
        record_name = supplied_name or f"{stem}_{record_index + 1}"
        molecule.SetProp("_Name", record_name)
        record_content, record_filename = _library_entry_content(
            molecule, ligand_format, record_name, record_index
        )
        try:
            ligand = _store_local_molecule(
                molecule=molecule,
                supplied_name=record_name,
                original_content=record_content,
                original_filename=record_filename,
                ligand_format=ligand_format,
                store=store,
                library_id=library_id,
                record_index=record_index,
            )
        except AnkoraDomainError as error:
            entries.append(
                LigandLibraryEntry(
                    record_index=record_index,
                    status=LigandLibraryEntryStatus.FAILED,
                    failure=LigandLibraryEntryFailure(
                        code=error.code,
                        message=error.message,
                    ),
                )
            )
            continue
        imported_ids.append(ligand.artifact.ligand_id)
        entries.append(
            LigandLibraryEntry(
                record_index=record_index,
                status=LigandLibraryEntryStatus.IMPORTED,
                ligand=ligand,
            )
        )
    created_at = datetime.now(UTC)
    artifact = LigandLibraryArtifact(
        library_id=library_id,
        filename=safe_filename,
        format=ligand_format,
        sha256=sha256(content).hexdigest(),
        size_bytes=len(content),
        record_count=len(entries),
        created_at=created_at,
    )
    failed_count = sum(item.status is LigandLibraryEntryStatus.FAILED for item in entries)
    provenance = ProvenanceEvent(
        event_id=f"ligand_library_imported-{library_id}",
        event_type="local_ligand_library_imported",
        timestamp=created_at,
        input_artifacts=[],
        output_artifacts=[library_id, *imported_ids],
        tool=ToolIdentity(name="RDKit ligand library importer", version=rdBase.rdkitVersion),
        parameters={
            "original_filename": safe_filename,
            "format": ligand_format.value,
            "record_count": len(entries),
            "imported_count": len(imported_ids),
            "failed_count": failed_count,
            "original_bytes_preserved": True,
        },
        warnings=[],
        command=None,
    )
    record = LigandLibraryRecord(
        artifact=artifact,
        entries=entries,
        imported_count=len(imported_ids),
        failed_count=failed_count,
        provenance=provenance,
        original_content_url=f"/ligand-libraries/{library_id}/content",
    )
    store.create_library(library_id, content, record)
    return record


def _store_local_molecule(
    *,
    molecule: Any,
    supplied_name: str | None,
    original_content: bytes,
    original_filename: str,
    ligand_format: LigandFormat,
    store: LigandArtifactStore,
    library_id: str | None,
    record_index: int | None,
) -> LigandRecord:
    name = supplied_name or Path(original_filename).stem or "ligand"
    molecule.SetProp("_Name", name)
    inspection = inspect_ligand_molecule(molecule, name)
    canonical_content = (Chem.MolToMolBlock(molecule) + "\n$$$$\n").encode("utf-8")
    warnings = _inspection_warnings(molecule, inspection)
    ligand_id = store.new_ligand_id()
    state_id = store.new_state_id()
    created_at = datetime.now(UTC)
    artifact = LigandArtifact(
        ligand_id=ligand_id,
        source=LigandSource.LOCAL,
        filename=store.sanitize_filename(original_filename),
        format=ligand_format,
        sha256=sha256(original_content).hexdigest(),
        size_bytes=len(original_content),
        created_at=created_at,
        library_id=library_id,
        library_record_index=record_index,
    )
    state = LigandChemicalStateArtifact(
        state_id=state_id,
        ligand_id=ligand_id,
        filename="inspected_state.sdf",
        format="sdf",
        sha256=sha256(canonical_content).hexdigest(),
        size_bytes=len(canonical_content),
        created_at=created_at,
    )
    provenance = ProvenanceEvent(
        event_id=f"ligand_imported-{ligand_id}",
        event_type="local_ligand_imported",
        timestamp=created_at,
        input_artifacts=[library_id] if library_id else [],
        output_artifacts=[ligand_id, state_id],
        tool=ToolIdentity(name="RDKit ligand importer", version=rdBase.rdkitVersion),
        parameters={
            "original_filename": artifact.filename,
            "format": ligand_format.value,
            "original_bytes_preserved": library_id is None,
            "library_source_preserved": library_id is not None,
            "library_record_index": record_index,
        },
        warnings=warnings,
        command=None,
    )
    record = LigandRecord(
        artifact=artifact,
        state=state,
        inspection=inspection,
        warnings=warnings,
        provenance=provenance,
        content_url=f"/ligands/{ligand_id}/states/{state_id}/content",
        original_content_url=f"/ligands/{ligand_id}/content",
    )
    store.create(
        ligand_id,
        original_content,
        record,
        state_content=canonical_content,
    )
    return record


def inspect_ligand_molecule(molecule: Any, name: str) -> LigandInspection:
    Chem.AssignStereochemistry(molecule, cleanIt=True, force=True)
    chiral_centers = Chem.FindMolChiralCenters(molecule, includeUnassigned=True)
    conformers = list(molecule.GetConformers())
    return LigandInspection(
        name=name,
        formula=rdMolDescriptors.CalcMolFormula(molecule),
        molecular_weight_g_mol=Descriptors.MolWt(molecule),
        exact_mass_da=rdMolDescriptors.CalcExactMolWt(molecule),
        formal_charge=Chem.GetFormalCharge(molecule),
        atom_count=molecule.GetNumAtoms(),
        heavy_atom_count=molecule.GetNumHeavyAtoms(),
        rotatable_bond_count=Lipinski.NumRotatableBonds(molecule),
        aromatic_ring_count=rdMolDescriptors.CalcNumAromaticRings(molecule),
        stereocenter_count=len(chiral_centers),
        undefined_stereocenter_count=sum(label == "?" for _, label in chiral_centers),
        fragment_count=len(Chem.GetMolFrags(molecule)),
        conformer_count=len(conformers),
        has_3d_coordinates=any(conformer.Is3D() for conformer in conformers),
        canonical_smiles=Chem.MolToSmiles(molecule, isomericSmiles=True),
    )


def _parse_library_molecules(content: bytes, ligand_format: LigandFormat) -> list[Any | None]:
    try:
        if ligand_format is LigandFormat.SDF or (
            ligand_format is LigandFormat.MOL and b"$$$$" in content
        ):
            return list(Chem.ForwardSDMolSupplier(BytesIO(content), removeHs=False))
        if ligand_format is LigandFormat.MOL:
            return [
                Chem.MolFromMolBlock(_decode(content), removeHs=False, sanitize=True)
            ]
        molecules: list[Any | None] = []
        for line in _decode(content).splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            fields = stripped.split(maxsplit=1)
            molecule = Chem.MolFromSmiles(fields[0], sanitize=True)
            if molecule is not None and len(fields) == 2:
                molecule.SetProp("_Name", fields[1].strip())
            molecules.append(molecule)
        return molecules
    except (RuntimeError, ValueError) as error:
        raise _import_error(
            "LIGAND_LIBRARY_PARSE_FAILED",
            "RDKit could not read the selected ligand library.",
            details={"technical_message": str(error)},
        ) from error


def _library_entry_content(
    molecule: Any,
    ligand_format: LigandFormat,
    name: str,
    record_index: int,
) -> tuple[bytes, str]:
    safe_stem = LigandArtifactStore.sanitize_filename(name).rsplit(".", maxsplit=1)[0]
    suffix = f"{record_index + 1:05d}"
    if ligand_format is LigandFormat.SMILES:
        smiles = Chem.MolToSmiles(molecule, isomericSmiles=True)
        return f"{smiles} {name}\n".encode(), f"{safe_stem}_{suffix}.smi"
    mol_block = Chem.MolToMolBlock(molecule).encode("utf-8")
    if ligand_format is LigandFormat.SDF:
        return mol_block + b"\n$$$$\n", f"{safe_stem}_{suffix}.sdf"
    return mol_block + b"\n", f"{safe_stem}_{suffix}.mol"


def _parse(content: bytes, ligand_format: LigandFormat) -> tuple[Any, str | None]:
    try:
        if ligand_format is LigandFormat.SDF:
            molecules = list(Chem.ForwardSDMolSupplier(BytesIO(content), removeHs=False))
            if len(molecules) != 1:
                raise _import_error(
                    "LIGAND_RECORD_SELECTION_REQUIRED",
                    "The SDF must contain exactly one molecule for this import step.",
                    details={"record_count": len(molecules)},
                )
            molecule = molecules[0]
        elif ligand_format is LigandFormat.MOL:
            molecule = Chem.MolFromMolBlock(_decode(content), removeHs=False, sanitize=True)
        else:
            lines = [
                line.strip()
                for line in _decode(content).splitlines()
                if line.strip() and not line.lstrip().startswith("#")
            ]
            if len(lines) != 1:
                raise _import_error(
                    "LIGAND_RECORD_SELECTION_REQUIRED",
                    "The SMILES file must contain exactly one non-comment molecule line.",
                    details={"record_count": len(lines)},
                )
            fields = lines[0].split(maxsplit=1)
            molecule = Chem.MolFromSmiles(fields[0], sanitize=True)
            if molecule is not None and len(fields) == 2:
                molecule.SetProp("_Name", fields[1].strip())
    except AnkoraDomainError:
        raise
    except (RuntimeError, ValueError) as error:
        raise _import_error(
            "LIGAND_PARSE_FAILED",
            "RDKit could not parse and sanitize the selected ligand file.",
            details={"technical_message": str(error)},
        ) from error
    if molecule is None or molecule.GetNumHeavyAtoms() == 0:
        raise _import_error(
            "LIGAND_PARSE_FAILED",
            "RDKit could not parse a non-empty molecular graph from the selected file.",
        )
    supplied_name = molecule.GetProp("_Name").strip() if molecule.HasProp("_Name") else None
    return molecule, supplied_name or None


def _inspection_warnings(
    molecule: Any, inspection: LigandInspection
) -> list[StructuredWarning]:
    warnings: list[StructuredWarning] = []
    if inspection.undefined_stereocenter_count:
        centers = [
            index
            for index, label in Chem.FindMolChiralCenters(
                molecule, includeUnassigned=True
            )
            if label == "?"
        ]
        warnings.append(
            StructuredWarning(
                code=WarningCode.LIG_STEREOCHEMISTRY_UNDEFINED,
                message="The imported ligand contains undefined stereocenters.",
                stage="ligand_import",
                details={"atom_indices": centers},
                recoverable=True,
            )
        )
    if inspection.fragment_count > 1:
        warnings.append(
            StructuredWarning(
                code=WarningCode.LIG_MULTICOMPONENT_STATE,
                message="The imported ligand contains multiple disconnected components.",
                stage="ligand_import",
                details={"fragment_count": inspection.fragment_count},
                recoverable=True,
            )
        )
    if not inspection.has_3d_coordinates:
        warnings.append(
            StructuredWarning(
                code=WarningCode.LIG_3D_COORDINATES_MISSING,
                message="The imported ligand has no authoritative 3D coordinates.",
                stage="ligand_import",
                details={"conformer_count": inspection.conformer_count},
                recoverable=True,
            )
        )
    return warnings


def _decode(content: bytes) -> str:
    try:
        return content.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise _import_error(
            "LIGAND_TEXT_ENCODING_UNSUPPORTED",
            "Text ligand files must use UTF-8 encoding.",
        ) from error


def _import_error(
    code: str,
    message: str,
    *,
    details: dict[str, object] | None = None,
    status_code: int = 422,
) -> AnkoraDomainError:
    return AnkoraDomainError(
        code=code,
        stage="ligand_import",
        message=message,
        status_code=status_code,
        details=details,
    )
