"""Typed contracts for the read-only M1 structure workspace."""

import re
from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ankora_backend.schemas.provenance import ProvenanceEvent
from ankora_backend.schemas.warnings import StructuredWarning


class StructureFormat(StrEnum):
    PDB = "pdb"
    MMCIF = "mmcif"


class StructureSource(StrEnum):
    LOCAL = "local"
    RCSB = "rcsb"
    ALPHAFOLD = "alphafold"


class HeterogenKind(StrEnum):
    LIGAND = "ligand"
    WATER = "water"
    METAL = "metal"
    OTHER = "other"


class StructureArtifact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_id: str = Field(min_length=1)
    original_filename: str = Field(min_length=1)
    format: StructureFormat
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size_bytes: int = Field(ge=1)
    source: StructureSource
    source_uri: str | None = None
    imported_at: datetime


class ChainSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    chain_id: str
    residue_count: int = Field(ge=0)
    polymer_residue_count: int = Field(ge=0)
    atom_count: int = Field(ge=0)


class HeterogenSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    chain_id: str
    sequence_number: int | None
    insertion_code: str = ""
    atom_count: int = Field(ge=1)
    kind: HeterogenKind


class StructureMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entry_id: str | None = None
    title: str | None = None
    experimental_method: str | None = None
    resolution_angstrom: float | None = Field(default=None, gt=0)
    model_count: int = Field(ge=1)
    atom_count: int = Field(ge=1)
    residue_count: int = Field(ge=1)
    chains: list[ChainSummary]
    heterogens: list[HeterogenSummary]
    alternate_location_atom_count: int = Field(ge=0)
    missing_residue_count: int = Field(ge=0)
    missing_atom_count: int = Field(ge=0)
    nonstandard_polymer_residues: list[str]


class StructureRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact: StructureArtifact
    metadata: StructureMetadata
    warnings: list[StructuredWarning]
    provenance: ProvenanceEvent
    content_url: str = Field(min_length=1)


class FetchStructureRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pdb_id: str = Field(min_length=4, max_length=4)

    @field_validator("pdb_id")
    @classmethod
    def validate_pdb_id(cls, value: str) -> str:
        normalized = value.strip().upper()
        if len(normalized) != 4 or not normalized.isalnum():
            raise ValueError("PDB ID must contain exactly four letters or digits")
        return normalized

_UNIPROT_ACCESSION_PATTERN = re.compile(r"^([OPQ][0-9][A-Z0-9]{3}[0-9])(-[0-9]{1,3})?$")


class FetchAlphaFoldStructureRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    uniprot_id: str = Field(min_length=6, max_length=10)

    @field_validator("uniprot_id")
    @classmethod
    def validate_uniprot_id(cls, value: str) -> str:
        normalized = value.strip().upper()
        if not _UNIPROT_ACCESSION_PATTERN.fullmatch(normalized):
            raise ValueError("UniProt accession must look like P12345 or P12345-2")
        return normalized
