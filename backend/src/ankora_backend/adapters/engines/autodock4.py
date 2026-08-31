"""Pure AutoDock4 grid/preflight contracts; no scientific executable is launched here."""

import math
import re
from collections.abc import Iterable
from dataclasses import dataclass

from ankora_backend.schemas.binding_sites import BindingBox

DEFAULT_GRID_SPACING_ANGSTROM = 0.375
DEFAULT_GRID_SMOOTHING_ANGSTROM = 0.5
DEFAULT_DISTANCE_DEPENDENT_DIELECTRIC = -0.1465
MAX_AUTOGRID_LIGAND_TYPES = 14
MAX_AUTOGRID_RECEPTOR_TYPES = 20
_AUTODOCK_ATOM_TYPE_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9]*$")
_MACROCYCLE_GLUE_TYPE_PATTERN = re.compile(r"^(?:CG|G)\d+$")
_ASCII_JOB_FILENAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")


@dataclass(frozen=True, slots=True)
class AutoDockGridPlan:
    requested_size_angstrom: tuple[float, float, float]
    spacing_angstrom: float
    npts: tuple[int, int, int]
    realized_size_angstrom: tuple[float, float, float]


def plan_autodock_grid(
    box: BindingBox,
    *,
    spacing_angstrom: float = DEFAULT_GRID_SPACING_ANGSTROM,
) -> AutoDockGridPlan:
    """Discretize a confirmed box without ever shrinking any requested axis."""
    if not math.isfinite(spacing_angstrom) or spacing_angstrom <= 0:
        raise ValueError("AutoGrid spacing must be a finite positive number.")
    requested = (box.size_x, box.size_y, box.size_z)
    npts = (
        _covering_even_npts(requested[0], spacing_angstrom),
        _covering_even_npts(requested[1], spacing_angstrom),
        _covering_even_npts(requested[2], spacing_angstrom),
    )
    realized = (
        npts[0] * spacing_angstrom,
        npts[1] * spacing_angstrom,
        npts[2] * spacing_angstrom,
    )
    return AutoDockGridPlan(
        requested_size_angstrom=requested,
        spacing_angstrom=spacing_angstrom,
        npts=npts,
        realized_size_angstrom=realized,
    )


def collect_autodock_atom_types(pdbqt_documents: Iterable[str]) -> tuple[str, ...]:
    """Return the deterministic union of atom types in prepared PDBQT inputs."""
    atom_types: set[str] = set()
    atom_records = 0
    for document in pdbqt_documents:
        for line in document.splitlines():
            if not line.startswith(("ATOM  ", "HETATM")):
                continue
            atom_records += 1
            tokens = line.split()
            if not tokens or not _AUTODOCK_ATOM_TYPE_PATTERN.fullmatch(tokens[-1]):
                raise ValueError("A PDBQT atom record has no valid AutoDock atom type.")
            atom_types.add(tokens[-1])
    if atom_records == 0:
        raise ValueError("No PDBQT atom records were found for AutoGrid preflight.")
    return tuple(sorted(atom_types, key=lambda atom_type: (atom_type.casefold(), atom_type)))


def preflight_autodock4_cpu_atom_types(
    atom_types: Iterable[str],
) -> tuple[str, ...]:
    """Validate the ligand-map union accepted by stock AutoGrid/AutoDock4 4.2.6."""
    normalized = _normalize_atom_types(atom_types)
    glue_types = tuple(
        atom_type
        for atom_type in normalized
        if _MACROCYCLE_GLUE_TYPE_PATTERN.fullmatch(atom_type)
    )
    if glue_types:
        joined = ", ".join(glue_types)
        raise ValueError(
            "AutoDock4 CPU 4.2.6 cannot parameterize Meeko macrocycle glue "
            f"atom types: {joined}. The ligand must remain an explicit "
            "engine-incompatible result; its atom types must not be coerced."
        )
    if len(normalized) > MAX_AUTOGRID_LIGAND_TYPES:
        raise ValueError(
            "AutoGrid4 4.2.6 supports at most "
            f"{MAX_AUTOGRID_LIGAND_TYPES} ligand affinity-map atom types; "
            f"the requested union contains {len(normalized)}."
        )
    return normalized


def preflight_autodock4_receptor_atom_types(
    atom_types: Iterable[str],
) -> tuple[str, ...]:
    """Validate the receptor-type union accepted by stock AutoGrid 4.2.6.

    Separate from the ligand preflight because the two limits are different
    (20 receptor types against 14 ligand affinity maps) and because macrocycle
    glue types are a Meeko ligand artifact that never appears in a receptor.
    """
    normalized = _normalize_atom_types(atom_types)
    if len(normalized) > MAX_AUTOGRID_RECEPTOR_TYPES:
        raise ValueError(
            "AutoGrid4 4.2.6 supports at most "
            f"{MAX_AUTOGRID_RECEPTOR_TYPES} receptor atom types; "
            f"the requested union contains {len(normalized)}."
        )
    return normalized


def render_autogrid_gpf(
    box: BindingBox,
    *,
    receptor_filename: str,
    receptor_atom_types: Iterable[str],
    ligand_atom_types: Iterable[str],
    map_prefix: str = "receptor",
    spacing_angstrom: float = DEFAULT_GRID_SPACING_ANGSTROM,
    smoothing_angstrom: float = DEFAULT_GRID_SMOOTHING_ANGSTROM,
    dielectric: float = DEFAULT_DISTANCE_DEPENDENT_DIELECTRIC,
) -> tuple[str, AutoDockGridPlan]:
    """Render a deterministic stock-AD4 GPF in an ASCII-safe job namespace."""
    _validate_ascii_job_filename(receptor_filename, label="receptor filename")
    _validate_ascii_job_filename(map_prefix, label="map prefix")
    if not math.isfinite(smoothing_angstrom) or smoothing_angstrom < 0:
        raise ValueError("AutoGrid smoothing must be a finite non-negative number.")
    if not math.isfinite(dielectric) or dielectric >= 0:
        raise ValueError(
            "The AutoDock4 contract requires a negative distance-dependent dielectric."
        )

    receptor_types = preflight_autodock4_receptor_atom_types(receptor_atom_types)
    ligand_types = preflight_autodock4_cpu_atom_types(ligand_atom_types)
    plan = plan_autodock_grid(box, spacing_angstrom=spacing_angstrom)
    lines = [
        f"npts {plan.npts[0]} {plan.npts[1]} {plan.npts[2]}",
        f"gridfld {map_prefix}.maps.fld",
        f"spacing {spacing_angstrom:.3f}",
        f"receptor_types {' '.join(receptor_types)}",
        f"ligand_types {' '.join(ligand_types)}",
        f"receptor {receptor_filename}",
        (
            "gridcenter "
            f"{box.center_x:.3f} {box.center_y:.3f} {box.center_z:.3f}"
        ),
        f"smooth {smoothing_angstrom:.3f}",
    ]
    lines.extend(f"map {map_prefix}.{atom_type}.map" for atom_type in ligand_types)
    lines.extend(
        (
            f"elecmap {map_prefix}.e.map",
            f"dsolvmap {map_prefix}.d.map",
            f"dielectric {dielectric:.4f}",
        )
    )
    return "\n".join(lines) + "\n", plan


def _covering_even_npts(size_angstrom: float, spacing_angstrom: float) -> int:
    if not math.isfinite(size_angstrom) or size_angstrom <= 0:
        raise ValueError("AutoGrid box sizes must be finite positive numbers.")
    count = math.ceil(size_angstrom / spacing_angstrom)
    return count if count % 2 == 0 else count + 1


def _normalize_atom_types(atom_types: Iterable[str]) -> tuple[str, ...]:
    normalized = set(atom_types)
    if not normalized:
        raise ValueError("At least one AutoDock atom type is required.")
    if any(
        not atom_type or not _AUTODOCK_ATOM_TYPE_PATTERN.fullmatch(atom_type)
        for atom_type in normalized
    ):
        raise ValueError("An invalid AutoDock atom type was requested.")
    return tuple(sorted(normalized, key=lambda atom_type: (atom_type.casefold(), atom_type)))


def _validate_ascii_job_filename(value: str, *, label: str) -> None:
    if (
        not value.isascii()
        or not _ASCII_JOB_FILENAME_PATTERN.fullmatch(value)
        or "/" in value
        or "\\" in value
        or value in {".", ".."}
    ):
        raise ValueError(f"AutoDock {label} must be an ASCII-safe basename.")
