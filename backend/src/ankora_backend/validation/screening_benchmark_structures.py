"""Freeze official LIT-PCBA structures and prove coordinate-frame congruence.

The source receptor and ligand MOL2 files remain immutable benchmark evidence.
Official RCSB mmCIF files are inspected independently.  Congruence is measured
in their recorded Cartesian coordinates: this module never fits, rotates, or
translates either structure.
"""

from __future__ import annotations

import hashlib
import json
import math
import tarfile
from dataclasses import dataclass
from importlib.metadata import version as distribution_version
from pathlib import Path, PurePosixPath
from typing import Any

import gemmi

RCSB_DOWNLOAD_URL = "https://files.rcsb.org/download/{pdb_id}.cif"
COORDINATE_MATCH_TOLERANCE_ANGSTROM = 0.001
MIN_RECEPTOR_EXACT_MATCH_FRACTION = 0.98
REQUIRED_LIGAND_EXACT_MATCH_FRACTION = 1.0


class ScreeningBenchmarkStructureError(ValueError):
    """Official structures cannot satisfy the frozen intake contract."""


@dataclass(frozen=True)
class _SourceAtom:
    atom_id: int
    name: str
    element: str
    x: float
    y: float
    z: float
    residue_label: str


@dataclass(frozen=True)
class _OfficialAtom:
    element: str
    x: float
    y: float
    z: float
    chain_id: str
    residue_name: str
    residue_number: int
    insertion_code: str
    atom_name: str
    alternate_location: str


@dataclass(frozen=True)
class _AtomMatch:
    source: _SourceAtom
    official: _OfficialAtom
    distance: float


def build_structure_manifest(
    *,
    archive: Path,
    input_manifest_path: Path,
    template_manifest_path: Path,
    geometry_manifest_path: Path,
    structures_dir: Path,
    retrieved_on: str,
) -> dict[str, Any]:
    """Build a deterministic, path-free official-structure intake manifest."""

    inputs = _load_object(input_manifest_path, "source-population manifest")
    templates = _load_object(template_manifest_path, "template manifest")
    geometry = _load_object(geometry_manifest_path, "geometry/sentinel manifest")
    _verify_manifest_identity(inputs, "source-population manifest")
    _verify_manifest_identity(templates, "template manifest")
    _verify_manifest_identity(geometry, "geometry/sentinel manifest")

    protocol_id = _required_string(inputs, "protocol_id")
    if any(
        _required_string(manifest, "protocol_id") != protocol_id
        for manifest in (templates, geometry)
    ):
        raise ScreeningBenchmarkStructureError(
            "The source, template, and geometry manifests name different protocols."
        )
    _verify_archive(archive, inputs)

    template_targets = _targets_by_id(templates, "template manifest")
    geometry_targets = _targets_by_id(geometry, "geometry/sentinel manifest")
    if set(template_targets) != set(geometry_targets):
        raise ScreeningBenchmarkStructureError(
            "The template and geometry target sets do not match."
        )

    try:
        with tarfile.open(archive, mode="r:*") as source_archive:
            members = _safe_regular_members(source_archive)
            targets = [
                _build_target(
                    source_archive,
                    members,
                    structures_dir=structures_dir,
                    template_target=template_targets[target_id],
                    geometry_target=geometry_targets[target_id],
                )
                for target_id in sorted(template_targets)
            ]
    except (OSError, tarfile.TarError) as error:
        raise ScreeningBenchmarkStructureError(
            "The benchmark source is not a readable tar archive."
        ) from error

    manifest: dict[str, Any] = {
        "schema_version": 1,
        "protocol_id": protocol_id,
        "dependencies": {
            "source_population_manifest_sha256": _required_sha256(
                inputs, "manifest_sha256"
            ),
            "holo_template_manifest_sha256": _required_sha256(
                templates, "manifest_sha256"
            ),
            "geometry_sentinel_manifest_sha256": _required_sha256(
                geometry, "manifest_sha256"
            ),
        },
        "official_structure_source": {
            "url_template": RCSB_DOWNLOAD_URL,
            "retrieved_on": retrieved_on,
            "format": "PDBx/mmCIF",
            "parser": {"name": "gemmi", "version": distribution_version("gemmi")},
        },
        "coordinate_frame_policy": {
            "comparison": (
                "direct same-element Cartesian coordinate matching without "
                "translation, rotation, fitting, or superposition"
            ),
            "tolerance_angstrom": COORDINATE_MATCH_TOLERANCE_ANGSTROM,
            "minimum_source_receptor_heavy_atom_match_fraction": (
                MIN_RECEPTOR_EXACT_MATCH_FRACTION
            ),
            "required_source_ligand_heavy_atom_match_fraction": (
                REQUIRED_LIGAND_EXACT_MATCH_FRACTION
            ),
            "model_policy": "exactly one official coordinate model",
        },
        "targets": targets,
        "receptor_preparation_boundary": {
            "status": "not_yet_executed",
            "required_next": (
                "freeze and execute explicit chain/component, repair, protonation, "
                "and receptor-PDBQT plans for every primary and alternate template"
            ),
            "source_protein_policy": (
                "source protein MOL2 files prove the benchmark frame but are not "
                "silently converted into docking-ready receptors"
            ),
        },
        "result_status": (
            "official_structures_and_coordinate_frames_frozen_no_receptor_"
            "preparation_or_docking_executed"
        ),
    }
    manifest["manifest_sha256"] = hashlib.sha256(_canonical_json(manifest)).hexdigest()
    return manifest


def verify_structure_manifest(
    *,
    archive: Path,
    input_manifest_path: Path,
    template_manifest_path: Path,
    geometry_manifest_path: Path,
    structures_dir: Path,
    structure_manifest_path: Path,
) -> dict[str, Any]:
    """Rebuild and compare a structure-intake manifest without network access."""

    recorded = _load_object(structure_manifest_path, "structure-intake manifest")
    _verify_manifest_identity(recorded, "structure-intake manifest")
    source = _required_object(
        recorded.get("official_structure_source"), "official_structure_source"
    )
    rebuilt = build_structure_manifest(
        archive=archive,
        input_manifest_path=input_manifest_path,
        template_manifest_path=template_manifest_path,
        geometry_manifest_path=geometry_manifest_path,
        structures_dir=structures_dir,
        retrieved_on=_required_string(source, "retrieved_on"),
    )
    if rebuilt != recorded:
        raise ScreeningBenchmarkStructureError(
            "The structure-intake manifest does not reproduce from recorded bytes."
        )
    return recorded


def serialize_structure_manifest(manifest: dict[str, Any]) -> str:
    return json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"


def _build_target(
    source_archive: tarfile.TarFile,
    members: dict[str, tarfile.TarInfo],
    *,
    structures_dir: Path,
    template_target: dict[str, Any],
    geometry_target: dict[str, Any],
) -> dict[str, Any]:
    target_id = _required_string(template_target, "target_id")
    if _required_string(geometry_target, "target_id") != target_id:
        raise ScreeningBenchmarkStructureError("Target identities do not join exactly.")

    primary = _required_object(
        template_target.get("primary_template"), "primary_template"
    )
    alternate = _required_object(
        template_target.get("alternate_template"), "alternate_template"
    )
    if _required_string(geometry_target, "primary_template_id") != _required_string(
        primary, "pdb_id"
    ) or _required_string(
        geometry_target, "alternate_template_id"
    ) != _required_string(alternate, "pdb_id"):
        raise ScreeningBenchmarkStructureError(
            f"Target {target_id} template roles differ from the geometry manifest."
        )

    return {
        "target_id": target_id,
        "primary_template": _inspect_template(
            source_archive,
            members,
            structures_dir=structures_dir,
            template=primary,
            role="primary",
        ),
        "alternate_template": _inspect_template(
            source_archive,
            members,
            structures_dir=structures_dir,
            template=alternate,
            role="alternate",
        ),
    }


def _inspect_template(
    source_archive: tarfile.TarFile,
    members: dict[str, tarfile.TarInfo],
    *,
    structures_dir: Path,
    template: dict[str, Any],
    role: str,
) -> dict[str, Any]:
    pdb_id = _required_string(template, "pdb_id").lower()
    if len(pdb_id) != 4 or not pdb_id.isalnum():
        raise ScreeningBenchmarkStructureError("A selected template has an invalid PDB ID.")
    source_receptor = _required_object(
        template.get("source_receptor"), "source_receptor"
    )
    source_ligand = _required_object(template.get("source_ligand"), "source_ligand")
    receptor_atoms = _parse_mol2_heavy_atoms(
        _verified_member_bytes(source_archive, members, source_receptor),
        label=f"{pdb_id} source receptor",
    )
    ligand_atoms = _parse_mol2_heavy_atoms(
        _verified_member_bytes(source_archive, members, source_ligand),
        label=f"{pdb_id} source ligand",
    )

    structure_path = structures_dir / f"{pdb_id}.cif"
    official_identity = _official_structure_identity(structure_path, pdb_id)
    try:
        structure = gemmi.read_structure(str(structure_path))
    except (OSError, RuntimeError, ValueError) as error:
        raise ScreeningBenchmarkStructureError(
            f"Official structure {pdb_id} is not readable PDBx/mmCIF."
        ) from error
    if structure.name.lower() != pdb_id:
        raise ScreeningBenchmarkStructureError(
            f"Official structure {pdb_id} reports entry {structure.name!r}."
        )
    if len(structure) != 1:
        raise ScreeningBenchmarkStructureError(
            f"Official structure {pdb_id} must contain exactly one coordinate model."
        )
    official_atoms = _official_heavy_atoms(structure)
    if not official_atoms:
        raise ScreeningBenchmarkStructureError(
            f"Official structure {pdb_id} has no heavy atoms."
        )

    receptor_matches, unmatched_receptor = _match_atoms(
        receptor_atoms, official_atoms
    )
    ligand_matches, unmatched_ligand = _match_atoms(ligand_atoms, official_atoms)
    receptor_fraction = len(receptor_matches) / len(receptor_atoms)
    ligand_fraction = len(ligand_matches) / len(ligand_atoms)
    if receptor_fraction + 1e-12 < MIN_RECEPTOR_EXACT_MATCH_FRACTION:
        raise ScreeningBenchmarkStructureError(
            f"Official structure {pdb_id} matches only {receptor_fraction:.6f} of "
            "source receptor heavy atoms in the recorded frame."
        )
    if ligand_fraction + 1e-12 < REQUIRED_LIGAND_EXACT_MATCH_FRACTION:
        raise ScreeningBenchmarkStructureError(
            f"Official structure {pdb_id} does not exactly recover every source "
            "ligand heavy atom in the recorded frame."
        )

    ligand_residues = {
        (
            match.official.chain_id,
            match.official.residue_name,
            match.official.residue_number,
            match.official.insertion_code,
        )
        for match in ligand_matches
    }
    if len(ligand_residues) != 1:
        raise ScreeningBenchmarkStructureError(
            f"Official structure {pdb_id} ligand coordinates do not map to one residue."
        )
    chain_id, residue_name, residue_number, insertion_code = next(
        iter(ligand_residues)
    )

    return {
        "role": role,
        "pdb_id": pdb_id,
        "source_receptor": _member_identity(source_receptor),
        "source_ligand": _member_identity(source_ligand),
        "official_structure": official_identity,
        "source_receptor_frame_evidence": {
            "source_heavy_atom_count": len(receptor_atoms),
            "exact_element_coordinate_matches": len(receptor_matches),
            "exact_match_fraction": _rounded(receptor_fraction),
            "matched_coordinate_rmsd_angstrom": _rmsd(receptor_matches),
            "matched_author_chain_ids": sorted(
                {match.official.chain_id for match in receptor_matches}
            ),
            "unmatched_source_heavy_atom_count": len(unmatched_receptor),
            "unmatched_source_heavy_atoms": [
                _source_atom_identity(atom) for atom in unmatched_receptor
            ],
        },
        "source_ligand_frame_evidence": {
            "source_heavy_atom_count": len(ligand_atoms),
            "exact_element_coordinate_matches": len(ligand_matches),
            "exact_match_fraction": _rounded(ligand_fraction),
            "matched_coordinate_rmsd_angstrom": _rmsd(ligand_matches),
            "matched_official_residue": {
                "author_chain_id": chain_id,
                "residue_name": residue_name,
                "author_sequence_number": residue_number,
                "insertion_code": insertion_code,
                "alternate_locations": sorted(
                    {
                        match.official.alternate_location
                        for match in ligand_matches
                        if match.official.alternate_location
                    }
                ),
            },
            "unmatched_source_heavy_atom_count": len(unmatched_ligand),
        },
        "coordinate_frame_congruent": True,
    }


def _match_atoms(
    source_atoms: list[_SourceAtom], official_atoms: list[_OfficialAtom]
) -> tuple[list[_AtomMatch], list[_SourceAtom]]:
    by_element: dict[str, list[tuple[int, _OfficialAtom]]] = {}
    for index, atom in enumerate(official_atoms):
        by_element.setdefault(atom.element, []).append((index, atom))
    used: set[int] = set()
    matches: list[_AtomMatch] = []
    unmatched: list[_SourceAtom] = []
    tolerance = COORDINATE_MATCH_TOLERANCE_ANGSTROM + 1e-12
    for source in source_atoms:
        candidates: list[tuple[float, int, _OfficialAtom]] = []
        for index, official in by_element.get(source.element, []):
            if index in used:
                continue
            distance = math.sqrt(
                (source.x - official.x) ** 2
                + (source.y - official.y) ** 2
                + (source.z - official.z) ** 2
            )
            if distance <= tolerance:
                candidates.append((distance, index, official))
        if not candidates:
            unmatched.append(source)
            continue
        distance, index, official = min(
            candidates,
            key=lambda value: (
                value[0],
                value[2].chain_id,
                value[2].residue_number,
                value[2].residue_name,
                value[2].atom_name,
                value[2].alternate_location,
                value[1],
            ),
        )
        used.add(index)
        matches.append(_AtomMatch(source, official, distance))
    return matches, unmatched


def _parse_mol2_heavy_atoms(content: bytes, *, label: str) -> list[_SourceAtom]:
    try:
        lines = content.decode("utf-8").splitlines()
    except UnicodeDecodeError as error:
        raise ScreeningBenchmarkStructureError(f"{label} is not UTF-8 MOL2.") from error
    starts = [index for index, line in enumerate(lines) if line.strip() == "@<TRIPOS>ATOM"]
    if len(starts) != 1:
        raise ScreeningBenchmarkStructureError(
            f"{label} must contain exactly one MOL2 atom section."
        )
    atoms: list[_SourceAtom] = []
    seen_ids: set[int] = set()
    for line in lines[starts[0] + 1 :]:
        stripped = line.strip()
        if stripped.startswith("@<TRIPOS>"):
            break
        if not stripped:
            continue
        fields = stripped.split()
        if len(fields) < 8:
            raise ScreeningBenchmarkStructureError(f"{label} has a malformed atom row.")
        try:
            atom_id = int(fields[0])
            x, y, z = (float(fields[index]) for index in (2, 3, 4))
        except ValueError as error:
            raise ScreeningBenchmarkStructureError(
                f"{label} has an invalid atom identifier or coordinate."
            ) from error
        if atom_id in seen_ids or not all(math.isfinite(value) for value in (x, y, z)):
            raise ScreeningBenchmarkStructureError(
                f"{label} has duplicate atoms or non-finite coordinates."
            )
        seen_ids.add(atom_id)
        element = fields[5].split(".", 1)[0].capitalize()
        if element == "H":
            continue
        try:
            gemmi.Element(element)
        except ValueError as error:
            raise ScreeningBenchmarkStructureError(
                f"{label} has unsupported element {element!r}."
            ) from error
        atoms.append(
            _SourceAtom(
                atom_id=atom_id,
                name=fields[1],
                element=element,
                x=x,
                y=y,
                z=z,
                residue_label=fields[7],
            )
        )
    if not atoms:
        raise ScreeningBenchmarkStructureError(f"{label} has no heavy atoms.")
    return atoms


def _official_heavy_atoms(structure: gemmi.Structure) -> list[_OfficialAtom]:
    atoms: list[_OfficialAtom] = []
    model = structure[0]
    for chain in model:
        for residue in chain:
            residue_number = residue.seqid.num
            if residue_number is None:
                raise ScreeningBenchmarkStructureError(
                    "An official structure residue has no author sequence number."
                )
            insertion_code = _normalized_optional_character(str(residue.seqid.icode))
            for atom in residue:
                element = atom.element.name
                if element == "H":
                    continue
                atoms.append(
                    _OfficialAtom(
                        element=element,
                        x=atom.pos.x,
                        y=atom.pos.y,
                        z=atom.pos.z,
                        chain_id=chain.name,
                        residue_name=residue.name,
                        residue_number=residue_number,
                        insertion_code=insertion_code,
                        atom_name=atom.name,
                        alternate_location=_normalized_optional_character(
                            str(atom.altloc)
                        ),
                    )
                )
    return atoms


def _normalized_optional_character(value: str) -> str:
    stripped = value.strip().replace("\x00", "")
    return "" if stripped in {".", "?"} else stripped


def _rmsd(matches: list[_AtomMatch]) -> float:
    if not matches:
        raise ScreeningBenchmarkStructureError("Coordinate matching produced no atoms.")
    return _rounded(math.sqrt(sum(match.distance**2 for match in matches) / len(matches)))


def _source_atom_identity(atom: _SourceAtom) -> dict[str, Any]:
    return {
        "atom_id": atom.atom_id,
        "atom_name": atom.name,
        "element": atom.element,
        "residue_label": atom.residue_label,
    }


def _official_structure_identity(path: Path, pdb_id: str) -> dict[str, Any]:
    if not path.is_file():
        raise ScreeningBenchmarkStructureError(
            f"Official structure file {pdb_id}.cif is unavailable."
        )
    return {
        "filename": path.name,
        "size_bytes": _file_size(path),
        "sha256": _file_sha256(path),
        "source_uri": RCSB_DOWNLOAD_URL.format(pdb_id=pdb_id.upper()),
    }


def _verify_archive(archive: Path, inputs: dict[str, Any]) -> None:
    source = _required_object(inputs.get("source"), "source")
    if _file_size(archive) != _required_nonnegative_int(source, "size_bytes"):
        raise ScreeningBenchmarkStructureError(
            "The source archive size differs from the frozen input manifest."
        )
    if _file_sha256(archive) != _required_sha256(source, "sha256"):
        raise ScreeningBenchmarkStructureError(
            "The source archive SHA-256 differs from the frozen input manifest."
        )


def _safe_regular_members(source: tarfile.TarFile) -> dict[str, tarfile.TarInfo]:
    members: dict[str, tarfile.TarInfo] = {}
    for member in source.getmembers():
        path = PurePosixPath(member.name)
        if path.is_absolute() or ".." in path.parts:
            raise ScreeningBenchmarkStructureError("The source archive has unsafe paths.")
        if not member.isfile():
            continue
        normalized = path.as_posix()
        if normalized in members:
            raise ScreeningBenchmarkStructureError(
                "The source archive repeats a regular-file path."
            )
        members[normalized] = member
    return members


def _verified_member_bytes(
    source: tarfile.TarFile,
    members: dict[str, tarfile.TarInfo],
    identity: dict[str, Any],
) -> bytes:
    path = _required_string(identity, "path")
    safe_path = PurePosixPath(path)
    if safe_path.is_absolute() or ".." in safe_path.parts:
        raise ScreeningBenchmarkStructureError("A source-member path is unsafe.")
    member = members.get(safe_path.as_posix())
    if member is None:
        raise ScreeningBenchmarkStructureError(f"Source member {path} is missing.")
    extracted = source.extractfile(member)
    if extracted is None:
        raise ScreeningBenchmarkStructureError(f"Source member {path} is unreadable.")
    content = extracted.read()
    if len(content) != _required_nonnegative_int(identity, "size_bytes"):
        raise ScreeningBenchmarkStructureError(f"Source member {path} size changed.")
    if hashlib.sha256(content).hexdigest() != _required_sha256(identity, "sha256"):
        raise ScreeningBenchmarkStructureError(f"Source member {path} SHA-256 changed.")
    return content


def _member_identity(value: dict[str, Any]) -> dict[str, Any]:
    return {
        "path": _required_string(value, "path"),
        "size_bytes": _required_nonnegative_int(value, "size_bytes"),
        "sha256": _required_sha256(value, "sha256"),
    }


def _targets_by_id(manifest: dict[str, Any], label: str) -> dict[str, dict[str, Any]]:
    targets: dict[str, dict[str, Any]] = {}
    for raw_target in _required_list(manifest, "targets"):
        target = _required_object(raw_target, f"{label} target")
        target_id = _required_string(target, "target_id")
        if target_id in targets:
            raise ScreeningBenchmarkStructureError(f"{label} repeats {target_id}.")
        targets[target_id] = target
    return targets


def _load_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value: Any = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ScreeningBenchmarkStructureError(
            f"The {label} is unavailable or invalid."
        ) from error
    return _required_object(value, label)


def _verify_manifest_identity(manifest: dict[str, Any], label: str) -> None:
    recorded = _required_sha256(manifest, "manifest_sha256")
    payload = dict(manifest)
    payload.pop("manifest_sha256")
    actual = hashlib.sha256(_canonical_json(payload)).hexdigest()
    if actual != recorded:
        raise ScreeningBenchmarkStructureError(
            f"The {label} content differs from its manifest SHA-256."
        )


def _required_object(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ScreeningBenchmarkStructureError(f"{label} must be an object.")
    return value


def _required_list(value: dict[str, Any], key: str) -> list[Any]:
    raw = value.get(key)
    if not isinstance(raw, list):
        raise ScreeningBenchmarkStructureError(f"{key} must be a list.")
    return raw


def _required_string(value: dict[str, Any], key: str) -> str:
    raw = value.get(key)
    if not isinstance(raw, str) or not raw:
        raise ScreeningBenchmarkStructureError(f"{key} must be a non-empty string.")
    return raw


def _required_nonnegative_int(value: dict[str, Any], key: str) -> int:
    raw = value.get(key)
    if not isinstance(raw, int) or isinstance(raw, bool) or raw < 0:
        raise ScreeningBenchmarkStructureError(f"{key} must be a non-negative integer.")
    return raw


def _required_sha256(value: dict[str, Any], key: str) -> str:
    raw = _required_string(value, key).lower()
    if len(raw) != 64 or any(character not in "0123456789abcdef" for character in raw):
        raise ScreeningBenchmarkStructureError(f"{key} must be a SHA-256 digest.")
    return raw


def _file_size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError as error:
        raise ScreeningBenchmarkStructureError(
            f"Required file {path.name} is unavailable."
        ) from error


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as error:
        raise ScreeningBenchmarkStructureError(
            f"Required file {path.name} is unreadable."
        ) from error
    return digest.hexdigest()


def _rounded(value: float) -> float:
    rounded = round(value, 6)
    return 0.0 if rounded == -0.0 else rounded


def _canonical_json(value: dict[str, Any]) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
