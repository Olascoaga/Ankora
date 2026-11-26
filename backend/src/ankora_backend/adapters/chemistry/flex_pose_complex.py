"""Deterministic E8 coupled PoseComplex materialization and cross-engine flex parsing.

Implements the empirically verified contracts from ADR-032 and its Gate 0 Addendum:
- A4: Pure-NUL-line sanitization on derived Windows Vina 1.2.7 flex splits while
  leaving raw engine outputs byte-immutable on disk, plus flat `--local_only`
  pose handling.
- A5: GNINA 1.3.3 `--out_flex .pdb` 0-based ordinal model parsing and 1:1
  coordinate re-injection into the immutable Meeko `receptor_flex.pdbqt` template.
- A6: Engine-agnostic atom matching by `(chain_id, sequence_number, insertion_code,
  canonical_resname, atom_name)` rather than PDBQT serial number (AutoDock4 CPU
  continues serials inside `BEGIN_RES` whereas AutoDock-GPU restarts at 1).
- E8: Deterministic full-atom coupled receptor PDB materialization
  `(receptor_rigid + pose_flex_sidechains)` with exact parent-triad rigid transfer
  of non-polar side-chain hydrogens so downstream `Mol*`, `ProLIF`, `PoseBusters`,
  and `Export` never observe floating hydrogens left at crystal rotamer coordinates.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from hashlib import sha256

from ankora_backend.domain.errors import AnkoraDomainError

_STAGE = "flex_pose_complex"
_MAX_CA_ANCHOR_DRIFT_ANGSTROM = 0.05
_MAX_CH_BOND_ANGSTROM = 1.35
_MAX_HEAVY_BOND_ANGSTROM = 1.95
_MIN_CROSS_NORM = 1e-6

_BACKBONE_ATOM_NAMES = frozenset(
    {"N", "H", "H1", "H2", "H3", "HN", "CA", "HA", "HA2", "HA3", "C", "O", "OXT"}
)

_PROTONATION_CANONICAL_RESNAME: dict[str, str] = {
    "HID": "HIS",
    "HIE": "HIS",
    "HIP": "HIS",
    "HSD": "HIS",
    "HSE": "HIS",
    "HSP": "HIS",
    "ASH": "ASP",
    "GLH": "GLU",
    "LYN": "LYS",
    "CYM": "CYS",
}

type _Vec3 = tuple[float, float, float]
type _ResiduePosition = tuple[str, int, str]
type _AtomKey = tuple[str, int, str, str]


@dataclass(frozen=True, slots=True)
class CoupledPdbqtSplit:
    """Immutable split of one docked pose block into ligand and moved side chains."""

    ligand_pdbqt: bytes
    flex_sidechains_pdbqt: bytes | None
    ligand_sha256: str
    flex_sidechains_sha256: str | None
    flex_residue_markers: tuple[str, ...]
    stripped_nul_line_count: int


@dataclass(frozen=True, slots=True)
class GninaFlexPdbModel:
    """One 0-based ordinal flex model parsed from `gnina --out_flex <file>.pdb`."""

    ordinal_index: int
    raw_model_header: int | None
    pdb_text: str


@dataclass(frozen=True, slots=True)
class FlexResidueDisplacement:
    """Heavy-atom displacement summary for one flexible side chain (angstroms)."""

    residue_key: str
    heavy_atom_count: int
    heavy_atom_rmsd_angstrom: float
    max_heavy_atom_displacement_angstrom: float
    repositioned_nonpolar_hydrogen_count: int


@dataclass(frozen=True, slots=True)
class MaterializedFlexReceptor:
    """Deterministic coupled receptor PDB (`receptor_rigid + pose_flex_sidechains`)."""

    pdb_text: str
    sha256: str
    moved_atom_count: int
    repositioned_nonpolar_hydrogen_count: int
    residue_displacements: dict[str, FlexResidueDisplacement]


@dataclass(frozen=True, slots=True)
class _ParsedAtomRecord:
    line_index: int
    raw_line: str
    chain_id: str
    sequence_number: int
    insertion_code: str
    residue_name: str
    atom_name: str
    element: str
    xyz: _Vec3

    @property
    def position(self) -> _ResiduePosition:
        return (self.chain_id, self.sequence_number, self.insertion_code)

    @property
    def atom_key(self) -> _AtomKey:
        return (self.chain_id, self.sequence_number, self.insertion_code, self.atom_name)


def strip_nul_lines(text: str) -> tuple[str, int]:
    """Remove pure-NUL lines (Windows Vina 1.2.7 `--flex` quirk) cleanly.

    Raw engine outputs remain untouched on disk; this helper operates only on
    in-memory text before writing derived pose splits. If a non-NUL record line
    contains an embedded NUL byte, fail closed rather than silently truncating.
    """
    cleaned: list[str] = []
    stripped_count = 0
    for line in text.splitlines(keepends=True):
        body = line.rstrip("\r\n")
        if "\x00" not in body:
            cleaned.append(line)
            continue
        if body.replace("\x00", "") == "":
            stripped_count += 1
            continue
        raise _error(
            "FLEX_POSE_PDBQT_EMBEDDED_NUL",
            "A PDBQT record contains an unexpected embedded NUL byte inside record text.",
        )
    return "".join(cleaned), stripped_count


def split_coupled_pdbqt_model(model_text: str) -> CoupledPdbqtSplit:
    """Split one PDBQT pose block into ligand PDBQT and optional `BEGIN_RES` flex block.

    Supports both `MODEL ... ENDMDL` wrapped blocks (Vina, AutoDock4, AutoDock-GPU)
    and flat single-pose outputs (`vina --local_only --out`).
    """
    cleaned, stripped_nul = strip_nul_lines(model_text)
    ligand_lines: list[str] = []
    flex_lines: list[str] = []
    markers: list[str] = []

    in_flex_res = False
    open_marker: str | None = None
    flex_block_has_atom = False

    for line in cleaned.splitlines(keepends=True):
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith(("MODEL", "ENDMDL")):
            continue
        if stripped.startswith("BEGIN_RES"):
            if in_flex_res:
                raise _error(
                    "FLEX_POSE_PDBQT_INVALID",
                    "Nested BEGIN_RES markers were found inside a flexible pose block.",
                )
            in_flex_res = True
            open_marker = " ".join(stripped.split()[1:])
            flex_block_has_atom = False
            markers.append(open_marker)
            flex_lines.append(_normalize_newline(line))
            continue
        if stripped.startswith("END_RES"):
            if not in_flex_res:
                raise _error(
                    "FLEX_POSE_PDBQT_INVALID",
                    "Encountered END_RES without a matching BEGIN_RES marker.",
                )
            end_marker = " ".join(stripped.split()[1:])
            if open_marker and end_marker and end_marker != open_marker:
                raise _error(
                    "FLEX_POSE_PDBQT_INVALID",
                    "Mismatched BEGIN_RES and END_RES residue markers in flexible pose.",
                    details={"begin_res": open_marker, "end_res": end_marker},
                )
            if not flex_block_has_atom:
                raise _error(
                    "FLEX_POSE_PDBQT_INVALID",
                    "A BEGIN_RES/END_RES block contained no atom records.",
                    details={"marker": open_marker or ""},
                )
            flex_lines.append(_normalize_newline(line))
            in_flex_res = False
            open_marker = None
            continue

        normalized = _normalize_newline(line)
        if in_flex_res:
            if stripped.startswith(("ATOM", "HETATM")):
                flex_block_has_atom = True
            flex_lines.append(normalized)
        else:
            ligand_lines.append(normalized)

    if in_flex_res:
        raise _error(
            "FLEX_POSE_PDBQT_INVALID",
            "Unterminated BEGIN_RES block in flexible pose output.",
            details={"marker": open_marker or ""},
        )

    if not any(line.startswith(("ATOM  ", "HETATM")) for line in ligand_lines):
        raise _error(
            "FLEX_POSE_PDBQT_INVALID",
            "No ligand ATOM/HETATM records were found in the pose block.",
        )

    ligand_bytes = "".join(ligand_lines).encode("utf-8")
    flex_bytes = "".join(flex_lines).encode("utf-8") if flex_lines else None
    return CoupledPdbqtSplit(
        ligand_pdbqt=ligand_bytes,
        flex_sidechains_pdbqt=flex_bytes,
        ligand_sha256=sha256(ligand_bytes).hexdigest(),
        flex_sidechains_sha256=(
            sha256(flex_bytes).hexdigest() if flex_bytes is not None else None
        ),
        flex_residue_markers=tuple(markers),
        stripped_nul_line_count=stripped_nul,
    )


def parse_gnina_flex_pdb_models(gnina_flex_pdb_text: str) -> tuple[GninaFlexPdbModel, ...]:
    """Parse `gnina --out_flex <file>.pdb` into 0-based ordinal pose models (ADR-032 A5).

    GNINA's OpenBabel writer shares a model counter with `--out`, so `--out_flex`
    frequently labels its models starting at `num_modes + 1` (e.g. `MODEL 3, 4`).
    Callers must therefore align ligand and flex poses by `ordinal_index`, never by
    literal `raw_model_header`.
    """
    cleaned, _ = strip_nul_lines(gnina_flex_pdb_text)
    models: list[GninaFlexPdbModel] = []
    block: list[str] = []
    in_model = False
    current_header: int | None = None
    saw_model_tag = False

    for line in cleaned.splitlines(keepends=True):
        stripped = line.strip()
        if stripped.startswith("MODEL"):
            if in_model:
                raise _error(
                    "GNINA_FLEX_PDB_INVALID",
                    "Nested MODEL records were found in GNINA --out_flex PDB output.",
                )
            saw_model_tag = True
            in_model = True
            block = []
            parts = stripped.split()
            if len(parts) >= 2:
                try:
                    current_header = int(parts[1])
                except ValueError as error:
                    raise _error(
                        "GNINA_FLEX_PDB_INVALID",
                        "Invalid MODEL number in GNINA --out_flex PDB output.",
                    ) from error
            else:
                current_header = None
            continue
        if stripped.startswith("ENDMDL"):
            if not in_model:
                raise _error(
                    "GNINA_FLEX_PDB_INVALID",
                    "Encountered ENDMDL without MODEL in GNINA --out_flex PDB output.",
                )
            pdb_text = "".join(block)
            if not _parse_pdb_atoms(pdb_text):
                raise _error(
                    "GNINA_FLEX_PDB_INVALID",
                    "A GNINA --out_flex PDB MODEL block contained no atoms.",
                )
            models.append(
                GninaFlexPdbModel(
                    ordinal_index=len(models),
                    raw_model_header=current_header,
                    pdb_text=pdb_text,
                )
            )
            in_model = False
            block = []
            current_header = None
            continue
        if in_model:
            block.append(_normalize_newline(line))

    if in_model:
        raise _error(
            "GNINA_FLEX_PDB_INVALID",
            "Unterminated MODEL record in GNINA --out_flex PDB output.",
        )

    if not saw_model_tag:
        # Flat single-model output (for example `--local_only --out_flex`).
        flat_text = "".join(_normalize_newline(line) for line in cleaned.splitlines(keepends=True))
        if not _parse_pdb_atoms(flat_text):
            raise _error(
                "GNINA_FLEX_PDB_INVALID",
                "GNINA --out_flex PDB output contained no ATOM/HETATM records.",
            )
        return (GninaFlexPdbModel(ordinal_index=0, raw_model_header=None, pdb_text=flat_text),)

    if not models:
        raise _error(
            "GNINA_FLEX_PDB_INVALID",
            "GNINA --out_flex PDB output contained no complete MODEL blocks.",
        )
    return tuple(models)


def reinject_gnina_flex_pdb_into_meeko_template(
    *,
    meeko_flex_pdbqt_text: str,
    gnina_flex_pdb_model_text: str,
) -> bytes:
    """Inject moved `(x, y, z)` coordinates from GNINA `.pdb` into immutable Meeko flex PDBQT.

    Preserves all Meeko `BEGIN_RES`/`ROOT`/`BRANCH`/`END_RES` torsion topology,
    partial charges, and AutoDock atom types verbatim so the resulting bytes can be
    passed back to `gnina --flex` for `--score_only` or `--local_only` and hashed as
    `pose_flex_sidechains_sha256` (ADR-032 Addendum A5).
    """
    pdb_atoms = _parse_pdb_atoms(gnina_flex_pdb_model_text)
    if not pdb_atoms:
        raise _error(
            "GNINA_FLEX_TEMPLATE_MISMATCH",
            "GNINA flex PDB model contains no atoms to inject.",
        )

    coords_by_key: dict[_AtomKey, tuple[str, _Vec3]] = {}
    for atom in pdb_atoms:
        if atom.atom_key in coords_by_key:
            raise _error(
                "GNINA_FLEX_TEMPLATE_MISMATCH",
                "Duplicate atom key encountered in GNINA flex PDB model.",
                details={"atom_key": list(atom.atom_key)},
            )
        coords_by_key[atom.atom_key] = (_canonical_resname(atom.residue_name), atom.xyz)

    template_atoms = _parse_pdb_atoms(meeko_flex_pdbqt_text)
    if not template_atoms:
        raise _error(
            "GNINA_FLEX_TEMPLATE_MISMATCH",
            "Meeko flex PDBQT template contains no atoms.",
        )

    template_keys: set[_AtomKey] = set()
    updated_lines = [
        _normalize_newline(line) for line in meeko_flex_pdbqt_text.splitlines(keepends=True)
    ]

    for atom in template_atoms:
        if atom.atom_key in template_keys:
            raise _error(
                "GNINA_FLEX_TEMPLATE_MISMATCH",
                "Duplicate atom key encountered in Meeko flex PDBQT template.",
                details={"atom_key": list(atom.atom_key)},
            )
        template_keys.add(atom.atom_key)
        matched = coords_by_key.get(atom.atom_key)
        if matched is None:
            raise _error(
                "GNINA_FLEX_TEMPLATE_MISMATCH",
                "A Meeko flex template atom is missing from GNINA --out_flex PDB output.",
                details={
                    "missing_atom_key": list(atom.atom_key),
                    "template_residue_name": atom.residue_name,
                },
            )
        pdb_resname, xyz = matched
        template_resname = _canonical_resname(atom.residue_name)
        if pdb_resname != template_resname:
            raise _error(
                "GNINA_FLEX_TEMPLATE_MISMATCH",
                "Residue name mismatch between Meeko flex template and GNINA flex PDB.",
                details={
                    "atom_key": list(atom.atom_key),
                    "template_residue_name": atom.residue_name,
                    "gnina_residue_name": pdb_resname,
                },
            )
        updated_lines[atom.line_index] = _replace_pdb_coordinates(
            updated_lines[atom.line_index], xyz
        )

    extra_keys = sorted(set(coords_by_key) - template_keys)
    if extra_keys:
        raise _error(
            "GNINA_FLEX_TEMPLATE_MISMATCH",
            "GNINA --out_flex PDB contains atoms absent from the Meeko flex template.",
            details={"extra_atom_keys": [list(key) for key in extra_keys[:10]]},
        )

    return "".join(updated_lines).encode("utf-8")


def materialize_coupled_receptor_pdb(
    *,
    protonated_pdb_text: str,
    pose_flex_sidechains_pdbqt: str,
) -> MaterializedFlexReceptor:
    """Deterministically materialize full-atom `(receptor_rigid + pose_flex_sidechains)` PDB.

    Every moved heavy atom and polar hydrogen from `pose_flex_sidechains_pdbqt`
    replaces the corresponding crystal coordinate in `protonated_pdb_text`, matched
    strictly by `(chain_id, sequence_number, insertion_code, atom_name)` (never by
    PDB serial number). Non-polar side-chain hydrogens on moved residues are
    deterministically rotated onto the moved heavy-atom frame via parent-triad rigid
    transfer so no floating crystal-position hydrogens remain.
    """
    cleaned_flex, _ = strip_nul_lines(pose_flex_sidechains_pdbqt)
    flex_atoms = _parse_pdb_atoms(cleaned_flex)
    if not flex_atoms:
        raise _error(
            "POSE_COMPLEX_FLEX_EMPTY",
            "The flexible side-chain PDBQT contains no atom records.",
        )

    pdb_lines = [_normalize_newline(line) for line in protonated_pdb_text.splitlines(keepends=True)]
    receptor_atoms = _parse_pdb_atoms(protonated_pdb_text)
    if not receptor_atoms:
        raise _error(
            "POSE_COMPLEX_RECEPTOR_EMPTY",
            "The protonated receptor PDB contains no atom records.",
        )

    flex_by_pos: dict[_ResiduePosition, dict[str, _ParsedAtomRecord]] = {}
    for atom in flex_atoms:
        res_map = flex_by_pos.setdefault(atom.position, {})
        if atom.atom_name in res_map:
            raise _error(
                "POSE_COMPLEX_FLEX_ATOM_MISMATCH",
                "Duplicate atom record inside flexible side-chain PDBQT.",
                details={"atom_key": list(atom.atom_key)},
            )
        res_map[atom.atom_name] = atom

    receptor_by_pos: dict[_ResiduePosition, dict[str, _ParsedAtomRecord]] = {}
    for atom in receptor_atoms:
        receptor_by_pos.setdefault(atom.position, {})[atom.atom_name] = atom

    moved_atom_count = 0
    total_repositioned_nonpolar_h = 0
    displacements: dict[str, FlexResidueDisplacement] = {}

    for position in sorted(flex_by_pos):
        moved_map = flex_by_pos[position]
        crystal_map = receptor_by_pos.get(position)
        if crystal_map is None:
            raise _error(
                "POSE_COMPLEX_FLEX_RESIDUE_MISSING",
                "A flexible side-chain residue is absent from the protonated receptor PDB.",
                details={"position": list(position)},
            )

        sample_flex = next(iter(moved_map.values()))
        sample_crystal = next(iter(crystal_map.values()))
        if _canonical_resname(sample_flex.residue_name) != _canonical_resname(
            sample_crystal.residue_name
        ):
            raise _error(
                "POSE_COMPLEX_FLEX_ATOM_MISMATCH",
                "Flexible residue name does not match the protonated receptor residue.",
                details={
                    "position": list(position),
                    "flex_residue_name": sample_flex.residue_name,
                    "receptor_residue_name": sample_crystal.residue_name,
                },
            )

        for atom_name, flex_atom in moved_map.items():
            crystal_atom = crystal_map.get(atom_name)
            if crystal_atom is None:
                raise _error(
                    "POSE_COMPLEX_FLEX_ATOM_MISMATCH",
                    "A flexible side-chain atom is absent from the protonated receptor PDB.",
                    details={"atom_key": list(flex_atom.atom_key)},
                )
            if atom_name == "CA":
                ca_drift = _distance(crystal_atom.xyz, flex_atom.xyz)
                if ca_drift > _MAX_CA_ANCHOR_DRIFT_ANGSTROM:
                    raise _error(
                        "POSE_COMPLEX_BACKBONE_DRIFT",
                        "Backbone CA anchor drifted beyond tolerance in flexible side-chain pose.",
                        details={
                            "position": list(position),
                            "ca_drift_angstrom": round(ca_drift, 6),
                            "tolerance_angstrom": _MAX_CA_ANCHOR_DRIFT_ANGSTROM,
                        },
                    )

        # Apply exact coordinates from pose_flex_sidechains.pdbqt.
        moved_heavy_crystal: dict[str, _Vec3] = {}
        moved_heavy_target: dict[str, _Vec3] = {}
        squared_heavy_displacements: list[float] = []
        max_heavy_disp = 0.0

        for atom_name, flex_atom in moved_map.items():
            crystal_atom = crystal_map[atom_name]
            pdb_lines[crystal_atom.line_index] = _replace_pdb_coordinates(
                pdb_lines[crystal_atom.line_index], flex_atom.xyz
            )
            moved_atom_count += 1
            if not _is_hydrogen(crystal_atom):
                moved_heavy_crystal[atom_name] = crystal_atom.xyz
                moved_heavy_target[atom_name] = flex_atom.xyz
                if atom_name != "CA":
                    dist = _distance(crystal_atom.xyz, flex_atom.xyz)
                    squared_heavy_displacements.append(dist * dist)
                    if dist > max_heavy_disp:
                        max_heavy_disp = dist

        # Include rigid backbone heavy atoms as reference anchors if needed by triads
        # (for example, C/N next to CA).
        for bb_name in ("N", "CA", "C"):
            if bb_name in crystal_map and bb_name not in moved_heavy_crystal:
                moved_heavy_crystal[bb_name] = crystal_map[bb_name].xyz
                moved_heavy_target[bb_name] = crystal_map[bb_name].xyz

        # Deterministically transform non-polar side-chain hydrogens on this moved residue.
        repositioned_here = 0
        heavy_neighbors = _build_heavy_adjacency(moved_heavy_crystal)
        for atom_name in sorted(crystal_map):
            if atom_name in moved_map or atom_name in _BACKBONE_ATOM_NAMES:
                continue
            crystal_atom = crystal_map[atom_name]
            if not _is_hydrogen(crystal_atom):
                continue
            parent_name = _find_hydrogen_parent(crystal_atom.xyz, moved_heavy_crystal)
            if parent_name is None:
                raise _error(
                    "POSE_COMPLEX_HYDROGEN_TRANSFER_FAILED",
                    "Could not identify a covalent heavy-atom parent for a side-chain hydrogen.",
                    details={"atom_key": list(crystal_atom.atom_key)},
                )
            transformed_xyz = _transfer_hydrogen_coordinate(
                hydrogen_xyz=crystal_atom.xyz,
                parent_name=parent_name,
                crystal_heavy=moved_heavy_crystal,
                moved_heavy=moved_heavy_target,
                adjacency=heavy_neighbors,
            )
            pdb_lines[crystal_atom.line_index] = _replace_pdb_coordinates(
                pdb_lines[crystal_atom.line_index], transformed_xyz
            )
            repositioned_here += 1
            total_repositioned_nonpolar_h += 1

        chain_id, seq_num, icode = position
        res_key = f"{chain_id}:{seq_num}{icode}:{sample_crystal.residue_name}"
        heavy_count = len(squared_heavy_displacements)
        rmsd = (
            math.sqrt(sum(squared_heavy_displacements) / heavy_count) if heavy_count > 0 else 0.0
        )
        displacements[res_key] = FlexResidueDisplacement(
            residue_key=res_key,
            heavy_atom_count=heavy_count,
            heavy_atom_rmsd_angstrom=round(rmsd, 6),
            max_heavy_atom_displacement_angstrom=round(max_heavy_disp, 6),
            repositioned_nonpolar_hydrogen_count=repositioned_here,
        )

    materialized_text = "".join(pdb_lines)
    return MaterializedFlexReceptor(
        pdb_text=materialized_text,
        sha256=sha256(materialized_text.encode("utf-8")).hexdigest(),
        moved_atom_count=moved_atom_count,
        repositioned_nonpolar_hydrogen_count=total_repositioned_nonpolar_h,
        residue_displacements=displacements,
    )


def _parse_pdb_atoms(text: str) -> list[_ParsedAtomRecord]:
    atoms: list[_ParsedAtomRecord] = []
    for line_index, raw_line in enumerate(text.splitlines(keepends=True)):
        record = raw_line[0:6].strip()
        if record not in {"ATOM", "HETATM"}:
            continue
        if len(raw_line) < 54:
            raise _error(
                "FLEX_POSE_PDBQT_INVALID",
                "Truncated ATOM/HETATM coordinate line in structure document.",
                details={"line_number": line_index + 1},
            )
        atom_name = raw_line[12:16].strip()
        residue_name = raw_line[17:20].strip()
        chain_id = raw_line[21:22].strip()
        seq_text = raw_line[22:26].strip()
        insertion_code = raw_line[26:27].strip()
        try:
            sequence_number = int(seq_text)
            x = float(raw_line[30:38])
            y = float(raw_line[38:46])
            z = float(raw_line[46:54])
        except ValueError as error:
            raise _error(
                "FLEX_POSE_PDBQT_INVALID",
                "Unparseable residue index or XYZ coordinate in structure document.",
                details={"line_number": line_index + 1},
            ) from error
        if not (math.isfinite(x) and math.isfinite(y) and math.isfinite(z)):
            raise _error(
                "FLEX_POSE_PDBQT_INVALID",
                "Non-finite XYZ coordinate in structure document.",
                details={"line_number": line_index + 1},
            )
        element = _extract_element(raw_line, atom_name)
        atoms.append(
            _ParsedAtomRecord(
                line_index=line_index,
                raw_line=raw_line,
                chain_id=chain_id,
                sequence_number=sequence_number,
                insertion_code=insertion_code,
                residue_name=residue_name,
                atom_name=atom_name,
                element=element,
                xyz=(x, y, z),
            )
        )
    return atoms


def _extract_element(line: str, atom_name: str) -> str:
    stripped = line.rstrip("\r\n")
    if len(stripped) >= 78:
        elem_col = stripped[76:78].strip()
        if elem_col and elem_col.isalpha():
            return elem_col.upper()
    cleaned = atom_name.lstrip("0123456789")
    return cleaned[:1].upper() if cleaned else ""


def _is_hydrogen(atom: _ParsedAtomRecord) -> bool:
    if atom.element in {"H", "HD", "HS"}:
        return True
    stripped = atom.atom_name.lstrip("0123456789")
    return stripped.startswith("H") and atom.element not in {"HG", "HO", "HF", "HE"}


def _canonical_resname(name: str) -> str:
    upper = name.strip().upper()
    return _PROTONATION_CANONICAL_RESNAME.get(upper, upper)


def _replace_pdb_coordinates(line: str, xyz: _Vec3) -> str:
    ending = "\n" if line.endswith("\n") else ""
    body = line.rstrip("\r\n")
    coords = f"{xyz[0]:8.3f}{xyz[1]:8.3f}{xyz[2]:8.3f}"
    if len(coords) != 24:
        raise _error(
            "FLEX_POSE_COORDINATE_OVERFLOW",
            "Atom coordinate exceeds fixed-width PDB 8.3f column bounds.",
            details={"xyz": list(xyz)},
        )
    return f"{body[:30]}{coords}{body[54:]}{ending}"


def _normalize_newline(line: str) -> str:
    return line.rstrip("\r\n") + "\n"


def _build_heavy_adjacency(heavy_coords: dict[str, _Vec3]) -> dict[str, list[str]]:
    names = sorted(heavy_coords)
    adjacency: dict[str, list[str]] = {name: [] for name in names}
    for i, left in enumerate(names):
        for right in names[i + 1 :]:
            if _distance(heavy_coords[left], heavy_coords[right]) <= _MAX_HEAVY_BOND_ANGSTROM:
                adjacency[left].append(right)
                adjacency[right].append(left)
    return adjacency


def _find_hydrogen_parent(hydrogen_xyz: _Vec3, heavy_coords: dict[str, _Vec3]) -> str | None:
    best_name: str | None = None
    best_dist = _MAX_CH_BOND_ANGSTROM
    for name in sorted(heavy_coords):
        dist = _distance(hydrogen_xyz, heavy_coords[name])
        if dist < best_dist:
            best_dist = dist
            best_name = name
    return best_name


def _transfer_hydrogen_coordinate(
    *,
    hydrogen_xyz: _Vec3,
    parent_name: str,
    crystal_heavy: dict[str, _Vec3],
    moved_heavy: dict[str, _Vec3],
    adjacency: dict[str, list[str]],
) -> _Vec3:
    # Build ordered candidate reference atoms: 1-hop bonded heavy neighbors first,
    # then 2-hop heavy neighbors, then remaining heavy atoms in the residue.
    one_hop = sorted(adjacency.get(parent_name, []))
    two_hop = sorted(
        {
            grand
            for nbr in one_hop
            for grand in adjacency.get(nbr, [])
            if grand != parent_name and grand not in one_hop
        }
    )
    fallback = [
        name
        for name in sorted(crystal_heavy)
        if name != parent_name and name not in one_hop and name not in two_hop
    ]
    ordered = [*one_hop, *two_hop, *fallback]

    p_c = crystal_heavy[parent_name]
    p_m = moved_heavy[parent_name]

    # Select first non-collinear pair (n1, n2) forming a well-conditioned triad at P.
    for i, n1 in enumerate(ordered):
        for n2 in ordered[i + 1 :]:
            basis_c = _orthonormal_triad(p_c, crystal_heavy[n1], crystal_heavy[n2])
            basis_m = _orthonormal_triad(p_m, moved_heavy[n1], moved_heavy[n2])
            if basis_c is None or basis_m is None:
                continue
            rel = _sub(hydrogen_xyz, p_c)
            # Local coordinates in crystal triad: (rel · e1, rel · e2, rel · e3).
            c1 = _dot(rel, basis_c[0])
            c2 = _dot(rel, basis_c[1])
            c3 = _dot(rel, basis_c[2])
            # Reconstruct in moved triad: P' + c1*e1' + c2*e2' + c3*e3'.
            return (
                p_m[0] + c1 * basis_m[0][0] + c2 * basis_m[1][0] + c3 * basis_m[2][0],
                p_m[1] + c1 * basis_m[0][1] + c2 * basis_m[1][1] + c3 * basis_m[2][1],
                p_m[2] + c1 * basis_m[0][2] + c2 * basis_m[1][2] + c3 * basis_m[2][2],
            )

    raise _error(
        "POSE_COMPLEX_HYDROGEN_TRANSFER_FAILED",
        "Could not construct a non-collinear heavy-atom reference frame for hydrogen transfer.",
        details={"parent_atom": parent_name, "available_heavy_atoms": sorted(crystal_heavy)},
    )


def _orthonormal_triad(
    origin: _Vec3, first: _Vec3, second: _Vec3
) -> tuple[_Vec3, _Vec3, _Vec3] | None:
    u_raw = _sub(first, origin)
    v_raw = _sub(second, origin)
    u = _normalize(u_raw)
    if u is None:
        return None
    w = _normalize(_cross(u, v_raw))
    if w is None:
        return None
    v = _normalize(_cross(w, u))
    if v is None:
        return None
    return (u, v, w)


def _sub(a: _Vec3, b: _Vec3) -> _Vec3:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _dot(a: _Vec3, b: _Vec3) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _cross(a: _Vec3, b: _Vec3) -> _Vec3:
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def _norm(v: _Vec3) -> float:
    return math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2])


def _normalize(v: _Vec3) -> _Vec3 | None:
    length = _norm(v)
    if length < _MIN_CROSS_NORM:
        return None
    return (v[0] / length, v[1] / length, v[2] / length)


def _distance(a: _Vec3, b: _Vec3) -> float:
    return _norm(_sub(a, b))


def _error(
    code: str, message: str, *, details: dict[str, object] | None = None
) -> AnkoraDomainError:
    return AnkoraDomainError(
        code=code,
        stage=_STAGE,
        message=message,
        status_code=422,
        details=details or {},
    )
