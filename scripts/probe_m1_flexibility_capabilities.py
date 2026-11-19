#!/usr/bin/env python3
"""Run the ADR-032 Gate 0 CLI probes in a new directory with the Ankora dev environment.

Evidence records observations, including nonzero exits and missing outputs. A zero
exit from this script means evidence was written. Raw tool files and streams can
contain host paths; evidence.json is the portable summary.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import platform
import re
import shutil
import subprocess
import sys
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass
from importlib import metadata
from itertools import groupby
from pathlib import Path, PurePath
from statistics import mean
from typing import TYPE_CHECKING

from ankora_backend.adapters.engines.autodock4 import (
    collect_autodock_atom_types,
    render_autogrid_gpf,
)
from ankora_backend.adapters.engines.autodock4_job import (
    log_reports_success,
    render_autodock4_dpf,
)
from ankora_backend.adapters.engines.autodock_gpu import run_reports_success
from ankora_backend.adapters.tools import discovery
from ankora_backend.adapters.tools.receptor_preparation import run_pdb2pqr_propka
from ankora_backend.domain.errors import AnkoraDomainError
from ankora_backend.schemas.binding_sites import BindingBox

if TYPE_CHECKING:
    from rdkit.Chem.rdchem import Mol

SEED = 20261118
MACROCYCLE_SMILES = "O=C1CCCCCCCCCCCO1"
AMIDE_SMILES = "CC(=O)NCc1ccc(CCC)cc1"
PEPTIDE_SEQUENCE = "GARYMP"
SELECTED_RESIDUES = ("A:4:TYR", "A:5:MET")
RIGID_NAME = "split_a_rigid.pdbqt"
FLEX_NAME = "split_a_flex.pdbqt"
FLEX_ARGS = ["--receptor", RIGID_NAME, "--flex", FLEX_NAME, "--ligand", "amide_default.pdbqt"]
SEARCH_ARGS = ["--cpu", "1", "--seed", "42", "--exhaustiveness", "2", "--num_modes", "2"]
GNINA_HYDROGEN_ARGS = ["--addH", "0", "--stripH", "0"]
PDBQT_MARKERS = {"ROOT", "ENDROOT", "BRANCH", "ENDBRANCH", "TORSDOF", "BEGIN_RES", "END_RES"}
ATOM_RECORDS = ("ATOM  ", "HETATM")
COORDINATE_TOLERANCE = 0.001
NUMBER = r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?"
SCORE_LINE = re.compile(
    r"^\s*(?:\(\d+\)\s*)?(Estimated Free Energy of Binding|Estimated Free Energy"
    r"|Affinity(?: \([^)]*\))?|(?:Final )?(?:Intermolecular|Intramolecular|Total Internal) Energy"
    r"|Torsional Free Energy|Unbound System's Energy|Energy(?: (?:before|after) minimization)?"
    r"|CNN\w*|RMSD(?:\s+from\s+\w+(?:\s+\w+)*)?)"
    rf"\s*[:=]\s*({NUMBER})(?:\s|$)", re.IGNORECASE
)
REMARK_SCORE = re.compile(
    r"^REMARK\s+(VINA RESULT|CNN\w*|minimizedAffinity|Affinity|Intramol|INTER \+ INTRA"
    rf"|INTER|INTRA|UNBOUND)\s*:?\s+({NUMBER}(?:\s+{NUMBER})*)\s*$", re.IGNORECASE
)
# Quoted paths and Windows directory names may include spaces. Keep relative artifact names.
PATH_TOKEN = r"""[^\s"'<>|,;()\[\]]+"""
WINDOWS_PATH_TAIL = rf"""(?:[^\\/:\r\n"'<>|,;]+\\)*{PATH_TOKEN}"""
QUOTED_ABSOLUTE_PATH = re.compile(
    r"""(?P<quote>["'])(?:[A-Za-z]:[\\/]|[\\/]{1,2})[^"'\r\n]+(?P=quote)"""
)
ABSOLUTE_PATH = re.compile(
    rf"""(?<![\w/\\])(?:[A-Za-z]:\\|\\\\)(?=[^\s/\\]){WINDOWS_PATH_TAIL}"""
    rf"""|(?<![\w/\\])(?:[A-Za-z]:)?/(?=[^\s/\\]){PATH_TOKEN}"""
)


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def package_version(name: str) -> str | None:
    try:
        return metadata.version(name)
    except metadata.PackageNotFoundError:
        return None


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def sanitize_text(text: str, paths: Iterable[PurePath] = ()) -> str:
    text = QUOTED_ABSOLUTE_PATH.sub("<absolute path>", text)
    names = {
        name for path in paths if path.is_absolute() and path != path.parent
        for name in (str(path), path.as_posix())
    }
    for name in sorted(names, key=lambda value: (-len(value), value)):
        if name in text:
            suffix = rf"""(?:\\{WINDOWS_PATH_TAIL}|/{PATH_TOKEN}|(?=$|[\s"'<>|,;()\[\]:]))"""
            text = re.sub(rf"{re.escape(name)}{suffix}", "<absolute path>", text)
    return ABSOLUTE_PATH.sub("<absolute path>", text)


def portable_value(value: object) -> object:
    if isinstance(value, str):
        return sanitize_text(value)
    if isinstance(value, dict):
        return {key: portable_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [portable_value(item) for item in value]
    return value


def excerpt(text: str, limit: int = 6000, *, paths: Iterable[Path] = ()) -> str:
    text = sanitize_text(text, paths)
    if len(text) <= limit:
        return text
    head = limit // 2
    return text[:head] + "\n[excerpt clipped]\n" + text[-head:]


def marker(line: str) -> str:
    return line.split(maxsplit=1)[0] if line.strip() else ""


def pure_nul_line(line: str) -> bool:
    return "\0" in line and not line.replace("\0", "").strip()


def nul_counts(lines: Iterable[str]) -> dict[str, int]:
    byte_counts = [line.count("\0") for line in lines]
    return {
        "nul_line_count": sum(count > 0 for count in byte_counts),
        "nul_byte_count": sum(byte_counts),
    }


def record_counts(lines: Iterable[str]) -> dict[str, int]:
    records = (marker(line.replace("\0", "")) for line in lines)
    return dict(Counter(record for record in records if record))


def atom_coordinates(line: str) -> tuple[float, float, float]:
    return float(line[30:38]), float(line[38:46]), float(line[46:54])


@dataclass(frozen=True)
class Atom:
    serial: int
    name: str
    residue: str
    xyz: tuple[float, float, float]
    charge: float
    atom_type: str

    @property
    def identity(self) -> str:
        return f"{self.residue}:{self.name}"


def parse_atoms(lines: Sequence[str]) -> list[Atom]:
    atoms = []
    for line in lines:
        if not line.startswith(ATOM_RECORDS):
            continue
        xyz = atom_coordinates(line)
        charge, atom_type = line[66:].split()[:2]
        residue = ":".join((line[21].strip(), line[22:27].strip(), line[17:20].strip()))
        atom = Atom(int(line[6:11]), line[12:16].strip(), residue, xyz, float(charge), atom_type)
        if not all(math.isfinite(value) for value in (*xyz, atom.charge)):
            raise ValueError("Non-finite PDBQT atom coordinates or charge")
        atoms.append(atom)
    return atoms


@dataclass(frozen=True)
class Model:
    label: str | None
    lines: list[str]
    has_endmdl: bool


def parse_models(document: str) -> tuple[list[Model], list[str]]:
    """Keep model order, including incomplete models and records outside MODEL."""
    models: list[Model] = []
    outside: list[str] = []
    current: list[str] | None = None
    label = None
    for line in document.splitlines():
        record = marker(line)
        if record == "MODEL":
            if current is not None:
                models.append(Model(label, current, False))
            label = line.strip()[len("MODEL"):].strip()
            current = []
        elif current is None:
            if line.strip():
                outside.append(line)
        elif record == "ENDMDL":
            models.append(Model(label, current, True))
            current = None
        else:
            current.append(line)
    if current is not None:
        models.append(Model(label, current, False))
    if not models and outside:
        return [Model(None, outside, False)], []
    return models, outside


type FlexAtomKey = tuple[str, str, str, str, str]
type FlexCoordinates = dict[FlexAtomKey, tuple[float, float, float]]


def flex_atom_key(line: str) -> FlexAtomKey:
    # PDB and PDBQT share these columns. Atom serials and order can change.
    return line[21], line[22:26].strip(), line[26], line[17:20].strip(), line[12:16].strip()


def flex_coordinates(lines: Iterable[str]) -> FlexCoordinates:
    coordinates: FlexCoordinates = {}
    for line in lines:
        if not line.startswith(ATOM_RECORDS):
            continue
        xyz = atom_coordinates(line)
        key = flex_atom_key(line)
        if key in coordinates:
            raise ValueError(f"Duplicate flex atom {key}")
        if not all(math.isfinite(value) for value in xyz):
            raise ValueError(f"Non-finite coordinates for flex atom {key}")
        coordinates[key] = xyz
    return coordinates


def require_matching_flex_atoms(reference: FlexCoordinates, moved: FlexCoordinates) -> None:
    if not reference:
        raise ValueError("Meeko template contains no flex atoms")
    if reference.keys() != moved.keys():
        missing = sorted(reference.keys() - moved.keys())
        extra = sorted(moved.keys() - reference.keys())
        raise ValueError(f"Flex atom mismatch (missing: {missing}, extra: {extra})")


def pdb_model_number(model: Model) -> int | None:
    if model.label and re.fullmatch(r"[+-]?\d+", model.label):
        return int(model.label)
    return None


def reinject_flex_pdb_coords_into_meeko_pdbqt(
    meeko_flex_pdbqt_text: str, gnina_flex_pdb_model_text: str,
) -> str:
    """Use the GNINA pose's coordinates with Meeko's original flex torsion trees."""
    models, outside = parse_models(gnina_flex_pdb_model_text)
    if (len(models) != 1 or pdb_model_number(models[0]) is None or not models[0].has_endmdl
            or any(line.startswith(ATOM_RECORDS) for line in outside)):
        raise ValueError("Expected one complete GNINA flex PDB MODEL block")
    template = meeko_flex_pdbqt_text.splitlines(keepends=True)
    moved = flex_coordinates(models[0].lines)
    require_matching_flex_atoms(flex_coordinates(template), moved)
    for index, line in enumerate(template):
        if line.startswith(ATOM_RECORDS):
            coordinates = "{:8.3f}{:8.3f}{:8.3f}".format(*moved[flex_atom_key(line)])
            if len(coordinates) != 24:
                raise ValueError(f"Coordinates exceed PDBQT field widths for {flex_atom_key(line)}")
            template[index] = line[:30] + coordinates + line[54:]
    return "".join(template)


def inspect_gnina_flex_pdb(
    document: str, ligand_models: Sequence[Model], template: str,
) -> tuple[list[Model], dict[str, object]]:
    models, outside = parse_models(document)
    reference = flex_coordinates(template.splitlines())
    observations: list[dict[str, object]] = []
    for index, model in enumerate(models):
        entry: dict[str, object] = {
            "pose_index": index, "model": pdb_model_number(model), "has_endmdl": model.has_endmdl,
            "ligand_model": ligand_models[index].label if index < len(ligand_models) else None,
        }
        try:
            moved = flex_coordinates(model.lines)
            entry["atom_count"] = len(moved)
            require_matching_flex_atoms(reference, moved)
            entry["max_displacement_angstrom"] = round(
                max(math.dist(xyz, moved[key]) for key, xyz in reference.items()), 6,
            )
        except ValueError as error:
            entry["parse_error"] = str(error)
        observations.append(entry)
    paired = (
        bool(models) and len(models) == len(ligand_models)
        and all(model.label is not None and model.has_endmdl for model in ligand_models)
        and all(entry["model"] is not None and entry["has_endmdl"] for entry in observations)
        and not any(line.startswith(ATOM_RECORDS) for line in outside)
    )
    return models, {
        "model_count": sum(model.label is not None for model in models),
        "ligand_model_count": sum(model.label is not None for model in ligand_models),
        "one_complete_model_per_mode": paired,
        "models": observations,
        "max_displacement_angstrom": (
            observations[0].get("max_displacement_angstrom") if observations else None
        ),
    }


def partition_pose(lines: Sequence[str]) -> tuple[list[str], list[str], bool]:
    """Separate marked flex residues without altering the recorded torsion trees."""
    ligand: list[str] = []
    flex: list[str] = []
    opened = None
    valid = True
    for line in lines:
        record = marker(line)
        if record == "BEGIN_RES":
            valid = valid and opened is None
            opened = line.split()[1:]
        if opened is None:
            ligand.append(line)
        else:
            flex.append(line)
        if record == "END_RES":
            valid = valid and opened == line.split()[1:]
            opened = None
    return ligand, flex, valid and opened is None


def compare_flex(reference: list[Atom], output: list[Atom]) -> dict[str, object]:
    before = {atom.identity: atom.xyz for atom in reference}
    after = {atom.identity: atom.xyz for atom in output}
    if not before or before.keys() != after.keys() or (
        len(before) != len(reference) or len(after) != len(output)
    ):
        return {
            "moved": None,
            "missing_atoms": sorted(before.keys() - after.keys()),
            "extra_atoms": sorted(after.keys() - before.keys()),
            "duplicate_atom_identities": len(before) != len(reference) or len(after) != len(output),
        }
    distances = {name: math.dist(xyz, after[name]) for name, xyz in before.items()}
    moved = sorted(
        name for name, distance in distances.items() if distance > COORDINATE_TOLERANCE + 1e-9
    )
    return {
        "moved": bool(moved),
        "max_displacement_angstrom": round(max(distances.values()), 6),
        "moved_atoms": moved,
    }


def pdbqt_scores(lines: Sequence[str]) -> dict[str, list[list[float]]]:
    scores: dict[str, list[list[float]]] = {}
    for line in lines:
        match = REMARK_SCORE.match(line)
        if match:
            scores.setdefault(match[1], []).append([float(value) for value in match[2].split()])
        elif line.startswith("USER"):
            match = SCORE_LINE.match(line[4:])
            if match:
                scores.setdefault(match[1], []).append([float(match[2])])
    return scores


def stdout_scores(stdout: str) -> list[dict[str, str | float]]:
    scores = []
    for line in stdout.splitlines():
        match = SCORE_LINE.match(line)
        if match:
            scores.append({"tag": match[1], "value": float(match[2]), "record": line.strip()})
    return scores


def summarize_model(
    model: Model, *, reference: list[Atom] | None, flex_file: bool
) -> dict[str, object]:
    lines = model.lines
    nul_stats = nul_counts(lines)
    summary: dict[str, object] = {
        "model": model.label, "has_endmdl": model.has_endmdl,
        "counts": record_counts(lines), **nul_stats,
    }
    try:
        atoms = parse_atoms(lines)
    except (ValueError, IndexError) as error:
        if not nul_stats["nul_byte_count"]:
            raise
        return {**summary, "parse_error": str(error)}
    ligand_lines, flex_lines, valid_flex_blocks = partition_pose(lines)
    if flex_file:
        flex_atoms = atoms
        flex_source = "separate_file"
        ligand_atoms: list[Atom] = []
    else:
        ligand_atoms = parse_atoms(ligand_lines)
        flex_atoms = parse_atoms(flex_lines)
        flex_source = "residue_markers"
        if not flex_lines and reference:
            residues = {atom.residue for atom in reference}
            flex_atoms = [atom for atom in atoms if atom.residue in residues]
            ligand_atoms = [atom for atom in atoms if atom.residue not in residues]
            flex_source = "residue_identity"
    ordered_records = []
    atom_iter = iter(atoms)
    for line in lines:
        if line.startswith(ATOM_RECORDS):
            atom = next(atom_iter)
            ordered_records.append(f"{marker(line)} {atom.serial} {atom.identity} {atom.atom_type}")
        elif marker(line) in PDBQT_MARKERS:
            ordered_records.append(line.strip())
    ligand_tree = [marker(line) for line in ligand_lines if marker(line) in PDBQT_MARKERS]
    ligand_markers = ("ROOT", "ENDROOT", "TORSDOF")
    has_ligand_tree = False
    if not flex_file and all(token in ligand_tree for token in ligand_markers):
        positions = [ligand_tree.index(token) for token in ligand_markers]
        has_ligand_tree = positions == sorted(positions)
    residue_displacements = None
    if reference is not None and flex_file:
        residue_displacements = {
            residue: compare_flex(
                [atom for atom in reference if atom.residue == residue],
                [atom for atom in flex_atoms if atom.residue == residue],
            )
            for residue in sorted({atom.residue for atom in flex_atoms})
        }
    return {
        **summary,
        "ordered_records": ordered_records,
        "ligand_root_through_torsdof": has_ligand_tree,
        "residue_markers": [
            line.strip() for line in flex_lines if marker(line) in {"BEGIN_RES", "END_RES"}
        ],
        "balanced_flex_blocks": valid_flex_blocks if flex_lines else None,
        "ligand_atom_count": len(ligand_atoms),
        "flex_atom_count": len(flex_atoms),
        "flex_atom_assignment": flex_source if flex_atoms else None,
        "flex_displacement": compare_flex(reference, flex_atoms) if reference is not None else None,
        "flex_displacement_by_residue": residue_displacements,
        "scores": pdbqt_scores(lines),
        "remark_score_records": [
            line for line in lines if line.startswith("REMARK") and REMARK_SCORE.match(line)
        ],
    }


def summarize_pdbqt(
    document: str, *, reference: list[Atom] | None = None, flex_file: bool = False
) -> dict[str, object]:
    models, outside = parse_models(document)
    summaries = [
        summarize_model(model, reference=reference, flex_file=flex_file) for model in models
    ]
    evidence: dict[str, object] = {
        "model_count": sum(model.label is not None for model in models),
        "outside_model_counts": record_counts(outside),
        **nul_counts(document.splitlines()),
        "models": summaries,
    }
    if any("parse_error" in summary for summary in summaries):
        evidence["parse_error"] = "One or more NUL-containing models could not be parsed"
    return evidence


def summarize_dlg(document: str, reference: list[Atom] | None) -> dict[str, object]:
    docked = "\n".join(line[8:] for line in document.splitlines() if line.startswith("DOCKED: "))
    return {
        "successful_completion_marker": log_reports_success(document),
        "dlg_excerpt": excerpt(document, limit=3600),
        "completion_lines": [
            line.strip() for line in document.splitlines() if "Completion" in line
            or "Unsuccessful" in line
        ],
        "docked": summarize_pdbqt(docked, reference=reference),
    }


def first_pose(document: str) -> Model | None:
    models, _ = parse_models(document)
    return next(
        (model for model in models
         if (model.label == "1" and model.has_endmdl) or model.label is None),
        None,
    )


def gnina_first_pose_flex(
    ligand_document: str, flex_document: str, reference: list[Atom],
) -> tuple[list[Model], str]:
    """Identify an exact MODEL 1 or a candidate group of per-residue models."""
    models, _ = parse_models(flex_document)
    if models and len(models) == 1 and models[0].label is None:
        return models, "unwrapped_flex_file"
    groups = [list(group) for _, group in groupby(models, key=lambda model: model.label)]
    if any(not model.has_endmdl for model in models):
        return [], "incomplete_flex_models"
    if len(groups) == 1 and groups[0][0].label == "1":
        return groups[0], "model_1"

    ligand_models, _ = parse_models(ligand_document)
    if len(groups) != len(ligand_models):
        return [], "unequal_ligand_model_and_flex_group_counts"
    expected_atoms = Counter(atom.identity for atom in reference)
    if not groups or not expected_atoms or any(
        Counter(atom.identity for model in group for atom in parse_atoms(model.lines))
        != expected_atoms for group in groups
    ):
        return [], "could_not_match_flex_groups_to_input_atoms"
    # GNINA 1.3.3 can write each residue in its own PDBQT MODEL. The
    # repeated model labels distinguish poses but need not start at 1.
    return groups[0], "file_order_candidate"


@dataclass
class Run:
    exit_code: int | None
    status: str
    stdout: str = ""
    stderr: str = ""


class Case:
    def __init__(self, root: Path, name: str) -> None:
        self.work = root / name
        self.work.mkdir(parents=True)
        self.record: dict[str, object] = {"cwd": name, "status": "not_run"}
        self.commands: list[dict[str, object]] = []
        self.record["commands"] = self.commands
        self.root = root

    def stage(self, *inputs: Path | None) -> bool:
        if not all(path is not None and path.is_file() for path in inputs):
            self.skip("skipped_dependency", "A required input artifact is unavailable")
            return False
        sources = []
        for path in inputs:
            assert path is not None
            shutil.copyfile(path, self.work / path.name)
            sources.append({"path": path.relative_to(self.root).as_posix(), "sha256": digest(path)})
        self.record["inputs"] = sources
        return True

    def skip(self, status: str, reason: str) -> None:
        self.record.update(status=status, reason=reason)

    def save_run(
        self, tag: str, command: list[str], run: Run, *, log: bool = True,
        executable: Path | None = None,
    ) -> None:
        paths = [self.root, Path(sys.executable), Path.home()]
        if executable:
            paths.append(executable)
        item: dict[str, object] = {
            "argv": command, "exit_code": run.exit_code, "status": run.status,
            "stdout_excerpt": excerpt(run.stdout, paths=paths),
            "stderr_excerpt": excerpt(run.stderr, paths=paths),
        }
        if log:
            for stream in ("stdout", "stderr"):
                path = self.work / f"{tag}.{stream}.txt"
                item[stream] = path.relative_to(self.root).as_posix()
        self.commands.append(item)
        self.record["status"] = run.status

    def output(self, filename: str, run: Run) -> Path | None:
        path = self.work / filename
        if not path.is_file() or path.stat().st_size == 0:
            if run.status == "exited_zero":
                self.skip("missing_output", f"Expected nonempty file {filename}")
            return None
        return path

    def finish(self) -> dict[str, object]:
        self.record["files"] = sorted(
            path.relative_to(self.work).as_posix()
            for path in self.work.rglob("*") if path.is_file()
        )
        return self.record


class Probe:
    def __init__(self, root: Path, args: argparse.Namespace) -> None:
        self.root = root
        self.args = args
        self.tools: dict[str, Path | None] = {}
        self.cases: dict[str, Case] = {}

    def case(self, name: str) -> Case:
        case = Case(self.root, name)
        self.cases[name] = case
        return case

    def run(self, case: Case, tool: str, args: list[str], tag: str = "tool") -> Run:
        executable = self.tools[tool]
        requested = [executable.name if executable else tool, *args]
        if executable is None:
            run = Run(None, "skipped_tool_unavailable")
            case.save_run(tag, requested, run, log=False)
            return run
        env = None
        if tool == "gnina" and self.args.gnina_ld_library_path:
            env = os.environ.copy()
            previous = env.get("LD_LIBRARY_PATH")
            addition = self.args.gnina_ld_library_path
            env["LD_LIBRARY_PATH"] = os.pathsep.join([addition, previous]) if previous else addition
        stdout_path = case.work / f"{tag}.stdout.txt"
        stderr_path = case.work / f"{tag}.stderr.txt"
        status = "exited_zero"
        exit_code = None
        launch_error = ""
        with stdout_path.open("xb") as stdout, stderr_path.open("xb") as stderr:
            try:
                result = subprocess.run(
                    [str(executable), *args], cwd=case.work, env=env, check=False,
                    stdout=stdout, stderr=stderr, timeout=30 if tag == "version" else 300,
                )
                exit_code = result.returncode
                if exit_code:
                    status = "exited_nonzero"
            except subprocess.TimeoutExpired:
                status = "timed_out"
            except OSError as error:
                status = "launch_error"
                launch_error = str(error)
        run = Run(exit_code, status, read_text(stdout_path), read_text(stderr_path))
        if launch_error:
            case.record["launch_error"] = launch_error
        case.save_run(tag, requested, run, executable=executable)
        return run

    def tool_inventory(self) -> dict[str, object]:
        engines = (
            ("vina", discovery.discover_vina, "1.2.7", r"AutoDock Vina\s+v?([\d.]+)"),
            ("autogrid4", discovery.discover_autogrid4, "4.2.6", r"AutoGrid\s+([\d.]+)"),
            ("autodock4", discovery.discover_autodock4, "4.2.6", r"AutoDock\s+([\d.]+)"),
            ("autodock_gpu", discovery.discover_autodock_gpu, "1.6",
             r"AutoDock-GPU\s+version:\s*v?([\d.]+)"),
            ("gnina", lambda path: discovery.discover_tool("gnina", path), "1.3.3",
             r"gnina\s+v?([\d.]+)"),
        )
        inventory: dict[str, object] = {}
        for name, discover, expected, pattern in engines:
            case = self.case(f"tools/{name}")
            if name == "gnina" and not sys.platform.startswith("linux"):
                self.tools[name] = None
                inventory[name] = {"status": "skipped_platform", "expected_version": expected}
                case.skip("skipped_platform", "GNINA is Linux-only")
                continue
            explicit = getattr(self.args, name)
            configured = explicit or os.getenv(f"ANKORA_{name.upper()}_PATH")
            if explicit:
                path = Path(explicit).expanduser().resolve()
                executable = path if path.is_file() else None
            else:
                found = discover(configured)
                executable = Path(found.path).resolve() if found.available and found.path else None
            self.tools[name] = executable
            options = ["--help"] if name == "autodock_gpu" else ["--version"]
            run = self.run(case, name, options, "version")
            match = re.search(pattern, run.stdout + "\n" + run.stderr, re.IGNORECASE)
            version = match[1] if match else None
            inventory[name] = {
                "status": run.status, "executable": executable.name if executable else None,
                "version": version, "expected_version": expected,
                "matches_expected_version": version == expected if version is not None else None,
                "sha256": digest(executable) if executable else None,
                "version_probe": case.record["cwd"],
            }

        for name, env, distribution in (
            ("mk_prepare_ligand", "ANKORA_MEEKO_LIGAND_PATH", "meeko"),
            ("mk_prepare_receptor", "ANKORA_MEEKO_PATH", "meeko"),
            ("pdb2pqr", "ANKORA_PDB2PQR_PATH", "pdb2pqr"),
        ):
            found = discovery.discover_tool(name, os.getenv(env))
            executable = Path(found.path).resolve() if found.available and found.path else None
            self.tools[name] = executable
            version = package_version(distribution)
            inventory[name] = {
                "status": "discovered" if executable else "skipped_tool_unavailable",
                "executable": executable.name if executable else None,
                "version": version, "version_source": "Python distribution metadata",
                "sha256": digest(executable) if executable else None,
            }
            if distribution == "meeko":
                entry = inventory[name]
                assert isinstance(entry, dict)
                entry.update(expected_version="0.7.1", matches_expected_version=version == "0.7.1")
        inventory["python"] = {
            "executable": Path(sys.executable).name, "version": platform.python_version(),
            "sha256": digest(Path(sys.executable)),
        }
        for name in ("rdkit", "propka"):
            inventory[name] = {"version": package_version(name)}
        return inventory


def optimize_conformer(molecule: Mol | None, *, peptide: bool = False) -> tuple[Mol, int]:
    from rdkit import Chem
    from rdkit.Chem import rdDistGeom, rdForceFieldHelpers

    if molecule is None:
        raise ValueError("RDKit could not parse the synthetic fixture")
    explicit = Chem.AddHs(molecule, addResidueInfo=peptide)
    params = rdDistGeom.ETKDGv3()
    params.randomSeed = SEED  # type: ignore[assignment]  # RDKit stubs mistype this descriptor.
    if rdDistGeom.EmbedMolecule(explicit, params) != 0:
        raise ValueError("ETKDGv3 failed to embed the synthetic fixture")
    status = rdForceFieldHelpers.MMFFOptimizeMolecule(
        explicit, mmffVariant="MMFF94s", maxIters=2000
    )
    if status != 0:
        raise ValueError(f"MMFF94s optimization did not converge (return code {status})")
    return explicit, int(status)


def ligand_observations(path: Path) -> tuple[int | None, dict[str, object]]:
    lines = read_text(path).splitlines()
    atoms = parse_atoms(lines)
    types = sorted({atom.atom_type for atom in atoms})
    torsdof = [int(line.split()[1]) for line in lines if marker(line) == "TORSDOF"]
    value = torsdof[0] if len(torsdof) == 1 else None
    return value, {
        "torsdof": value, "torsdof_records": torsdof, "atom_types": types,
        "branch_count": sum(marker(line) == "BRANCH" for line in lines),
        "has_macrocycle_glue": bool({"CG0", "G0"}.intersection(types)),
        "atom_count": len(atoms),
    }


def group_l(probe: Probe) -> dict[str, Path]:
    fixtures = probe.case("L/fixtures")
    sources: dict[str, Path] = {}
    fixture_details: dict[str, object] = {}
    fixtures.record["fixtures"] = fixture_details
    smarts_pairs = {
        "amide_rigidify_match": ("[c:1]-[CH2:2]-[CH2:3]-[CH3:4]", (2, 3)),
        "amide_rigidify_no_match": ("[#16]-[CH3]", (1, 2)),
    }
    controls: dict[str, dict[str, object]] = {}
    for name, smiles in (("macrocycle", MACROCYCLE_SMILES), ("amide_flex", AMIDE_SMILES)):
        label = f"SYNTHETIC_GATE0_{name.upper()}"
        detail: dict[str, object] = {"label": label, "smiles": smiles}
        fixture_details[name] = detail
        try:
            from rdkit import Chem

            mol = Chem.MolFromSmiles(smiles)
            explicit, optimization = optimize_conformer(mol)
            assert mol is not None
            explicit.SetProp("_Name", label)
            source_file = fixtures.work / f"{label}.sdf"
            with Chem.SDWriter(str(source_file)) as writer:
                writer.write(explicit)
            detail.update(
                status="generated", mmff94s_return_code=optimization,
                ring_sizes=[len(ring) for ring in mol.GetRingInfo().AtomRings()],
            )
            if name == "amide_flex":
                for case_name, (smarts, (a, b)) in smarts_pairs.items():
                    query = Chem.MolFromSmarts(smarts)
                    if query is None or query.GetBondBetweenAtoms(a - 1, b - 1) is None:
                        raise ValueError(f"Invalid SMARTS control {case_name}")
                    matches = mol.GetSubstructMatches(query)
                    controls[case_name] = {
                        "smarts": smarts, "query_bond_indices_one_based": [a, b],
                        "match_count": len(matches),
                        "matched_bonds_zero_based": [
                            [match[a - 1], match[b - 1]] for match in matches
                        ],
                    }
                    if bool(matches) != (case_name == "amide_rigidify_match"):
                        raise ValueError(f"Unexpected SMARTS matching outcome for {case_name}")
            sources[name] = source_file
        except (ImportError, OSError, RuntimeError, ValueError) as error:
            detail.update(status="fixture_error", error=str(error))
    fixtures.record["status"] = "generated" if len(sources) == 2 else "fixture_error"

    cases: tuple[tuple[str, str, list[str]], ...] = (
        ("macrocycle_default", "macrocycle", []),
        ("macrocycle_rigid", "macrocycle", ["--rigid_macrocycles"]),
        ("amide_default", "amide_flex", []),
        ("amide_rigidify_match", "amide_flex", []),
        ("amide_rigidify_no_match", "amide_flex", []),
        ("amide_flexible_amides", "amide_flex", ["-a"]),
    )
    outputs: dict[str, Path] = {}
    baseline = None
    for name, fixture, options in cases:
        case = probe.case(f"L/{name}")
        source = sources.get(fixture)
        if not case.stage(source):
            continue
        assert source is not None
        if name in smarts_pairs:
            smarts, (a, b) = smarts_pairs[name]
            case.record["rdkit_smarts_control"] = controls[name]
            options = ["-r", smarts, "-b", str(a), str(b)]
        output = f"{name}.pdbqt"
        run = probe.run(
            case, "mk_prepare_ligand",
            ["-i", source.name, "-o", output, "--charge_model", "gasteiger", *options],
        )
        path = case.output(output, run)
        if path is None:
            continue
        try:
            torsdof, summary = ligand_observations(path)
            case.record.update(summary)
            if name == "amide_default" and run.exit_code == 0:
                baseline = torsdof
            if name.startswith("amide_") and name != "amide_default":
                case.record["torsdof_delta_vs_amide_default"] = (
                    torsdof - baseline if torsdof is not None and baseline is not None else None
                )
            if run.exit_code == 0 and torsdof is not None and summary["atom_count"]:
                outputs[name] = path
            elif run.exit_code == 0:
                case.skip("invalid_output", "Expected ligand atoms and one TORSDOF record")
        except (ValueError, IndexError) as error:
            case.record["parse_error"] = str(error)
            case.record["status"] = "parse_error"
    return outputs


def write_peptide(case: Case) -> None:
    from rdkit import Chem

    label = "SYNTHETIC_GATE0_GARYMP"
    case.record.update(label=label, sequence=PEPTIDE_SEQUENCE)
    molecule, optimization = optimize_conformer(
        Chem.MolFromSequence(PEPTIDE_SEQUENCE), peptide=True
    )
    block = Chem.MolToPDBBlock(molecule, flavor=2)
    atoms = [line for line in block.splitlines() if line.startswith(ATOM_RECORDS)]
    atoms.sort(key=lambda line: (line[21], int(line[22:26]), line[26]))

    # RDKit's generic H names do not match PARSE templates. Retain the optimized
    # explicit-H fixture and give PDB2PQR its heavy atoms to assign its own Hs.
    heavy = [line for line in atoms if line[76:78].strip() != "H"]
    if {line[21:27].strip() for line in heavy} != {f"A{i:>4}" for i in range(1, 7)}:
        raise ValueError("Expected a single chain A with all six synthetic residues")
    for filename, records in ((f"{label}_explicit_h.pdb", atoms), ("receptor.pdb", heavy)):
        atom_lines = [f"{line[:6]}{index:5}{line[11:]}" for index, line in enumerate(records, 1)]
        content = "\n".join([f"TITLE     {label}", *atom_lines, "TER", "END", ""])
        (case.work / filename).write_text(content, encoding="ascii", newline="\n")
    case.record.update(mmff94s_return_code=optimization, pdb2pqr_input="heavy_atoms_only")


def protonate(probe: Probe, case: Case) -> Path | None:
    argv = [
        Path(sys.executable).name, "-m", "ankora_backend.adapters.tools.pdb2pqr_worker",
        "--input", "receptor.pdb", "--pqr-output", "receptor.pqr",
        "--pdb-output", "protonated.pdb", "--ph", "7.4", "--force-field", "PARSE",
    ]
    case.record["pdb2pqr_library_arguments"] = [
        "--ff=PARSE", "--keep-chain", "--titration-state-method=propka", "--with-ph=7.4",
        "--pdb-output=protonated.pdb", "receptor.pdb", "receptor.pqr",
    ]
    if probe.tools["pdb2pqr"] is None:
        case.save_run("pdb2pqr", argv, Run(None, "skipped_tool_unavailable"), log=False)
        return None
    try:
        execution, _, report = run_pdb2pqr_propka(
            input_path=Path("receptor.pdb"), pqr_output_path=case.work / "receptor.pqr",
            pdb_output_path=Path("protonated.pdb"), ph=7.4, force_field="PARSE",
        )
        argv = [Path(execution.command[0]).name, *execution.command[1:]]
        run = Run(execution.exit_code, "exited_zero", execution.stdout, execution.stderr)
        case.record["propka_report"] = report
    except AnkoraDomainError as error:
        details = error.details
        code = details.get("exit_code")
        status = "exited_nonzero" if isinstance(code, int) and code else "adapter_error"
        run = Run(
            code if isinstance(code, int) else None, status,
            str(details.get("stdout", "")), str(details.get("stderr", "")),
        )
        case.record["adapter_error"] = {
            "code": error.code, "message": error.message, "reason": details.get("reason"),
        }
        command = details.get("command")
        if isinstance(command, list) and command:
            argv = [Path(str(command[0])).name, *(str(item) for item in command[1:])]
    # The adapter launches the worker in pqr_output_path.parent, so the PQR
    # destination is passed absolute. Record the equivalent local filename.
    argv = ["receptor.pqr" if item == str(case.work / "receptor.pqr") else item for item in argv]
    (case.work / "pdb2pqr.stdout.txt").write_text(run.stdout, encoding="utf-8", newline="\n")
    (case.work / "pdb2pqr.stderr.txt").write_text(run.stderr, encoding="utf-8", newline="\n")
    case.save_run("pdb2pqr", argv, run)
    path = case.output("receptor.pqr", run)
    return path if run.status == "exited_zero" else None


def receptor_observations(path: Path, *, flex_file: bool) -> dict[str, object]:
    document = read_text(path)
    lines = document.splitlines()
    atoms = parse_atoms(lines)
    return {
        "atoms": [asdict(atom) for atom in atoms],
        "total_charge": round(math.fsum(atom.charge for atom in atoms), 6),
        "selected_residue_atoms": {
            residue: [atom.name for atom in atoms if atom.residue == residue]
            for residue in SELECTED_RESIDUES
        },
        "torsdof_records": [line for line in lines if marker(line) == "TORSDOF"],
        "branch_count": sum(marker(line) == "BRANCH" for line in lines),
        "pdbqt": summarize_pdbqt(document, flex_file=flex_file),
    }


@dataclass
class Receptor:
    rigid: Path | None = None
    flex: Path | None = None
    full: Path | None = None
    box: BindingBox | None = None


def group_r(probe: Probe) -> Receptor:
    result = Receptor()
    prep = probe.case("R/protonation")
    pqr = None
    try:
        write_peptide(prep)
        pqr = protonate(probe, prep)
        # Use the optimized coordinates for a common box even if split fails.
        # PDB2PQR's hydrogen placement may change between tool versions.
        lines = read_text(prep.work / "receptor.pdb").splitlines()
        pocket = [line for line in lines if line.startswith(ATOM_RECORDS)
                  and line[21] == "A" and int(line[22:26]) in (4, 5)]
        center = [round(mean(float(line[i:i + 8]) for line in pocket), 3) for i in (30, 38, 46)]
        result.box = BindingBox(
            center_x=center[0], center_y=center[1], center_z=center[2],
            size_x=20, size_y=20, size_z=20,
        )
    except (ImportError, OSError, RuntimeError, ValueError) as error:
        prep.record.update(status="preparation_error", error=str(error))

    cases = (
        ("split_with_o_and_p_bare", ["-o", "split_a", "-p", "-f", "A:4,A:5"]),
        ("split_with_explicit_p_filename", ["-p", "explicit_target.pdbqt", "-f", "A:4"]),
        *[(f"disallowed_and_missing_flexres/{name}", ["-o", "split", "-p", "-f", locator])
          for name, locator in (("gly", "A:1"), ("ala", "A:2"), ("pro", "A:6"),
                                ("missing", "A:999"))],
        ("full_rigid_receptor", ["-o", "receptor_full", "-p", "receptor_full.pdbqt"]),
    )
    for name, args in cases:
        case = probe.case(f"R/{name}")
        if not case.stage(pqr):
            continue
        run = probe.run(
            case, "mk_prepare_receptor",
            ["--read_pqr", "receptor.pqr", "--charge_model", "read", *args],
        )
        files = {}
        for path in sorted(case.work.glob("*.pdbqt")):
            try:
                files[path.name] = receptor_observations(
                    path, flex_file=path.stem.endswith("_flex")
                )
            except (ValueError, IndexError) as error:
                files[path.name] = {"parse_error": str(error)}
        case.record["pdbqt_files"] = files
        if name == "split_with_o_and_p_bare":
            rigid = case.output(RIGID_NAME, run)
            flex = case.output(FLEX_NAME, run)
            if run.exit_code == 0:
                result.rigid, result.flex = rigid, flex
        elif name == "full_rigid_receptor":
            full = case.output("receptor_full.pdbqt", run)
            if run.exit_code == 0:
                result.full = full
    return result


def box_arguments(box: BindingBox) -> list[str]:
    return [
        "--center_x", f"{box.center_x:g}", "--center_y", f"{box.center_y:g}",
        "--center_z", f"{box.center_z:g}", "--size_x", f"{box.size_x:g}",
        "--size_y", f"{box.size_y:g}", "--size_z", f"{box.size_z:g}",
    ]


def observe_pdbqt(
    case: Case, filename: str, run: Run, *, flex: Path | None = None, flex_file: bool = False
) -> Path | None:
    path = case.output(filename, run)
    if path is not None:
        try:
            reference = parse_atoms(read_text(flex).splitlines()) if flex else None
            summary = summarize_pdbqt(
                read_text(path), reference=reference, flex_file=flex_file
            )
            case.record[filename] = summary
            if "parse_error" in summary:
                case.record["status"] = "parse_error"
        except (ValueError, IndexError) as error:
            case.record[filename] = {"parse_error": str(error)}
            case.record["status"] = "parse_error"
    return path if run.exit_code == 0 else None


def prepare_pose_inputs(
    case: Case, ligand_source: Path | None, flex_source: Path | None = None,
    *, gnina_reference: Path | None = None, ligand_name: str, flex_name: str,
) -> tuple[Path | None, Path | None]:
    inputs = (ligand_source, flex_source, gnina_reference) if gnina_reference else (ligand_source,)
    if not case.stage(*inputs):
        return None, None
    assert ligand_source is not None
    ligand_document = read_text(ligand_source)
    model = first_pose(ligand_document)
    if model is None:
        case.skip("skipped_dependency", "No complete MODEL 1 in the ligand source")
        return None, None
    ligand_lines, flex_lines, balanced = partition_pose(model.lines)
    if gnina_reference is not None:
        assert flex_source is not None
        try:
            models, selection = gnina_first_pose_flex(
                ligand_document, read_text(flex_source),
                parse_atoms(read_text(gnina_reference).splitlines()),
            )
        except (IndexError, ValueError) as error:
            case.skip("parse_error", str(error))
            return None, None
        case.record.update(
            flex_selection=selection, source_flex_model_labels=[model.label for model in models],
        )
        if not models:
            case.skip("skipped_dependency", "No complete flex records for ligand MODEL 1")
            return None, None
        # Strip only the model wrappers. The re-ingestion probe passes the
        # observed trees verbatim, even when BEGIN_RES and END_RES are absent.
        ligand_lines = model.lines
        flex_lines = [line for flex_model in models for line in flex_model.lines]
    if not any(line.startswith(ATOM_RECORDS) for line in ligand_lines) or not any(
        line.startswith(ATOM_RECORDS) for line in flex_lines
    ) or not balanced:
        case.skip(
            "skipped_dependency", "MODEL 1 does not contain extractable ligand and flex atoms"
        )
        return None, None
    ligand, flex = case.work / ligand_name, case.work / flex_name
    stripped_nul_lines = 0
    for path, lines in ((ligand, ligand_lines), (flex, flex_lines)):
        if gnina_reference is None:
            clean_lines = [line for line in lines if not pure_nul_line(line)]
            stripped_nul_lines += len(lines) - len(clean_lines)
            lines = clean_lines
        path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    if gnina_reference is None:
        case.record["stripped_nul_lines"] = stripped_nul_lines
    case.record["status"] = "extracted"
    return ligand, flex


def engine_case(
    case: Case, box: BindingBox | None, *inputs: Path | None
) -> list[str] | None:
    if box is None:
        case.skip("skipped_dependency", "Synthetic binding box is unavailable")
        return None
    return box_arguments(box) if case.stage(*inputs) else None


def vina_probes(probe: Probe, receptor: Receptor, amide: Path | None) -> None:
    parent = "E/E1_vina"
    vina_output = None
    for scoring in ("vina", "vinardo"):
        case = probe.case(f"{parent}/vina_flex_{scoring}_scoring")
        box = engine_case(case, receptor.box, receptor.rigid, receptor.flex, amide)
        if box is None:
            continue
        filename = "vina_flex_out.pdbqt" if scoring == "vina" else "vinardo_flex_out.pdbqt"
        run = probe.run(
            case, "vina",
            [*FLEX_ARGS, *box, "--scoring", scoring, *SEARCH_ARGS, "--out", filename],
        )
        output = observe_pdbqt(case, filename, run, flex=receptor.flex)
        if output is not None:
            # VINA RESULT triples supply the score table with PDBQT precision.
            models, _ = parse_models(read_text(output))
            case.record["score_table"] = [
                {"mode": model.label, "affinity_rmsd_lb_rmsd_ub": row}
                for model in models for row in pdbqt_scores(model.lines).get("VINA RESULT", [])
            ]
        if scoring == "vina":
            vina_output = output

    parent += "/vina_score_only_and_local_only_with_flex"
    ligand, flex = prepare_pose_inputs(
        probe.case(f"{parent}/pose1"), vina_output,
        ligand_name="pose1_lig.pdbqt", flex_name="pose1_flex.pdbqt",
    )
    modes = (("score_only", "vina"), ("score_only", "vinardo"), ("local_only", "vina"))
    for mode, scoring in modes:
        case = probe.case(f"{parent}/{mode}_{scoring}")
        box = engine_case(case, receptor.box, receptor.rigid, ligand, flex)
        if box is None:
            continue
        filename = "vina_local_out.pdbqt"
        output_args = ["--out", filename] if mode == "local_only" else []
        run = probe.run(case, "vina", [
            "--receptor", RIGID_NAME, "--flex", "pose1_flex.pdbqt", "--ligand", "pose1_lig.pdbqt",
            *box, "--scoring", scoring, "--cpu", "1", "--seed", "42", f"--{mode}", *output_args,
        ])
        case.record["stdout_scores"] = stdout_scores(run.stdout)
        if mode == "local_only":
            observe_pdbqt(case, filename, run, flex=flex)


def autodock4_probe(
    probe: Probe, case: Case, receptor: Path | None, box: BindingBox | None,
    ligand: Path | None, *, flex: Path | None = None, map_policy: str,
) -> list[Path]:
    inputs = (receptor, ligand) if map_policy == "rigid" else (receptor, ligand, flex)
    if box is None:
        case.skip("skipped_dependency", "Synthetic binding box is unavailable")
        return []
    if not case.stage(*inputs):
        return []
    assert receptor is not None and ligand is not None
    try:
        ligand_text = read_text(ligand)
        flex_text = read_text(flex) if flex else ""
        ligand_types = collect_autodock_atom_types([ligand_text])
        flex_types = collect_autodock_atom_types([flex_text]) if flex else ()
        map_types = (
            collect_autodock_atom_types([ligand_text, flex_text])
            if map_policy == "union" else ligand_types
        )
        case.record.update(
            map_policy=map_policy, ligand_atom_types=ligand_types, flex_atom_types=flex_types,
            affinity_map_atom_types=map_types,
            flex_types_without_maps=sorted(set(flex_types) - set(map_types)),
        )
        gpf, plan = render_autogrid_gpf(
            box, receptor_filename=receptor.name,
            receptor_atom_types=collect_autodock_atom_types([read_text(receptor)]),
            ligand_atom_types=map_types,
        )
        case.record["grid_plan"] = asdict(plan)
        torsdof, _ = ligand_observations(ligand)
        if torsdof is None:
            raise ValueError("Ligand requires one TORSDOF record")
        atoms = parse_atoms(ligand_text.splitlines())
        real_atoms = [atom for atom in atoms if not atom.atom_type.startswith(("G0", "CG0"))]
        about = (
            mean(atom.xyz[0] for atom in real_atoms),
            mean(atom.xyz[1] for atom in real_atoms),
            mean(atom.xyz[2] for atom in real_atoms),
        )
        dpf = render_autodock4_dpf(
            ligand_filename=ligand.name, map_prefix="receptor", ligand_atom_types=map_types,
            about=about, torsional_degrees_of_freedom=torsdof, seed=(42, 43), ga_runs=2,
            ga_population_size=50, ga_energy_evaluations=10000, ga_generations=27000,
            cluster_rmsd_tolerance_angstrom=2.0,
        )
        if flex:
            move = f"move {ligand.name}\n"
            dpf = dpf.replace(move, f"{move}flexres {flex.name}\n", 1)
    except (ValueError, IndexError, AnkoraDomainError) as error:
        case.skip("invalid_input", str(error))
        return []
    (case.work / "receptor.gpf").write_text(gpf, encoding="ascii", newline="\n")
    (case.work / "dock.dpf").write_text(dpf, encoding="ascii", newline="\n")
    grid = probe.run(case, "autogrid4", ["-p", "receptor.gpf", "-l", "receptor.glg"], "autogrid4")
    glg = case.output("receptor.glg", grid)
    grid_completed = glg is not None and log_reports_success(read_text(glg))
    map_names = [
        "receptor.maps.fld", "receptor.maps.xyz", "receptor.e.map", "receptor.d.map",
        *(f"receptor.{atom_type}.map" for atom_type in map_types),
    ]
    maps = [case.work / name for name in map_names]
    missing = [path.name for path in maps if not path.is_file() or path.stat().st_size == 0]
    case.record.update(
        grid_successful_completion_marker=grid_completed, expected_map_files=map_names,
        missing_map_files=missing,
    )
    if grid.exit_code != 0 or not grid_completed or missing:
        case.record["autodock4_status"] = "skipped_grid_incomplete"
        if grid.exit_code == 0:
            case.skip("grid_incomplete", "AutoGrid did not produce a complete map set")
        return []
    run = probe.run(case, "autodock4", ["-p", "dock.dpf", "-l", "dock.dlg"], "autodock4")
    dlg = case.output("dock.dlg", run)
    if dlg:
        observe_dlg(case, dlg, parse_atoms(flex_text.splitlines()) if flex else None)
    return maps


def observe_dlg(case: Case, path: Path, reference: list[Atom] | None) -> None:
    results = case.record.setdefault("dlg_files", {})
    assert isinstance(results, dict)
    try:
        results[path.name] = summarize_dlg(read_text(path), reference)
    except (ValueError, IndexError) as error:
        results[path.name] = {"parse_error": str(error)}
        case.record["status"] = "parse_error"


def autodock_gpu_probes(
    probe: Probe, maps: list[Path], amide: Path | None, flex: Path | None
) -> None:
    parent = "E/E3_autodock_gpu_flex_single_and_filelist"
    for mode in ("single", "filelist"):
        case = probe.case(f"{parent}/{mode}")
        if not maps:
            case.skip("skipped_dependency", "The union AutoGrid map set is unavailable")
            continue
        if not case.stage(amide, flex, *maps):
            continue
        if mode == "single":
            args = ["--ffile", "receptor.maps.fld", "--lfile", "amide_default.pdbqt"]
        else:
            (case.work / "batch.lst").write_text(
                "receptor.maps.fld\namide_default.pdbqt\nbatch_pose\n",
                encoding="ascii", newline="\n",
            )
            args = ["--filelist", "batch.lst"]
        run = probe.run(case, "autodock_gpu", [
            *args, "--flexres", FLEX_NAME, "--nrun", "2", "--seed", "42",
            "--dlgoutput", "1", "--xmloutput", "0",
            "--heuristics", "0", "--autostop", "0", "--nev", "10000",
        ])
        case.record["stdout_reports_success"] = run_reports_success(run.stdout)
        case.record["stdout_verdict_lines"] = [
            line.strip() for line in run.stdout.splitlines()
            if "successful" in line or "jobs ran" in line or "Error" in line
        ]
        assert flex is not None
        reference = parse_atoms(read_text(flex).splitlines())
        dlgs = sorted(case.work.glob("*.dlg"))
        for dlg in dlgs:
            observe_dlg(case, dlg, reference)
        if not dlgs and run.exit_code == 0:
            case.skip("missing_output", "No DLG was emitted")


def gnina_pdb_pose_inputs(
    probe: Probe, case: Case, receptor: Receptor, amide: Path | None,
) -> tuple[Path | None, Path | None]:
    if not sys.platform.startswith("linux"):
        case.skip("skipped_platform", "GNINA is Linux-only")
        return None, None
    box = engine_case(case, receptor.box, receptor.rigid, receptor.flex, amide)
    if box is None:
        return None, None
    ligand_file = "gnina_lig_for_pdb_flex.pdbqt"
    flex_file = "gnina_flex_cpu.pdb"
    run = probe.run(case, "gnina", [
        *FLEX_ARGS, *box, *SEARCH_ARGS, *GNINA_HYDROGEN_ARGS, "--no_gpu",
        "--out", ligand_file, "--out_flex", flex_file,
    ])
    ligand_output = observe_pdbqt(case, ligand_file, run)
    flex_output = case.output(flex_file, run)
    if flex_output is None:
        return None, None
    assert receptor.flex is not None
    try:
        template = receptor.flex.read_bytes().decode("utf-8")
        ligand_models, _ = parse_models(read_text(ligand_output)) if ligand_output else ([], [])
        models, summary = inspect_gnina_flex_pdb(read_text(flex_output), ligand_models, template)
        case.record[flex_file] = summary
        if run.exit_code != 0 or ligand_output is None:
            return None, None
        if not summary["one_complete_model_per_mode"]:
            case.skip("invalid_output", "Expected one complete flex PDB MODEL per ligand mode")
            return None, None
        first_flex_model = "\n".join((f"MODEL {models[0].label}", *models[0].lines, "ENDMDL"))
        updated_template = reinject_flex_pdb_coords_into_meeko_pdbqt(template, first_flex_model)
        if not any(line.startswith(ATOM_RECORDS) for line in ligand_models[0].lines):
            raise ValueError("The first GNINA ligand model contains no atoms")
    except ValueError as error:
        case.skip("parse_error", str(error))
        return None, None
    ligand = case.work / "pose1_lig.pdbqt"
    flex = case.work / "pose1_flex_meeko.pdbqt"
    ligand.write_text("\n".join(ligand_models[0].lines) + "\n", encoding="utf-8", newline="\n")
    flex.write_text(updated_template, encoding="utf-8", newline="")
    case.record["reinjection"] = {
        "pose_index": 0, "ligand_model": ligand_models[0].label,
        "flex_model": pdb_model_number(models[0]),
        "max_displacement_angstrom": summary["max_displacement_angstrom"],
    }
    return ligand, flex


def gnina_meeko_reinjection_probes(
    probe: Probe, parent: str, receptor: Receptor, amide: Path | None,
) -> None:
    ligand, flex = gnina_pdb_pose_inputs(
        probe, probe.case(f"{parent}/gnina_flex_cpu_pdb"), receptor, amide,
    )
    for mode in ("score_only", "local_only"):
        case = probe.case(f"{parent}/gnina_meeko_reinjection/{mode}")
        if not sys.platform.startswith("linux"):
            case.skip("skipped_platform", "GNINA is Linux-only")
            continue
        if not case.stage(receptor.rigid, ligand, flex):
            continue
        ligand_file = "gnina_local_meeko_lig.pdbqt"
        flex_file = "gnina_local_meeko_flex.pdb"
        output_args = ["--out", ligand_file, "--out_flex", flex_file] if mode == "local_only" else []
        run = probe.run(case, "gnina", [
            "--receptor", RIGID_NAME, "--flex", "pose1_flex_meeko.pdbqt",
            "--ligand", "pose1_lig.pdbqt", *GNINA_HYDROGEN_ARGS, "--cpu", "1", "--seed", "42",
            "--no_gpu", f"--{mode}", *output_args,
        ])
        case.record["stdout_scores"] = stdout_scores(run.stdout)
        case.record["max_displacement_angstrom"] = None  # Score-only emits no coordinates.
        if mode == "local_only":
            ligand_output = observe_pdbqt(case, ligand_file, run)
            flex_output = case.output(flex_file, run)
            if flex_output is not None:
                assert flex is not None
                try:
                    ligand_models, _ = (
                        parse_models(read_text(ligand_output)) if ligand_output else ([], [])
                    )
                    _, summary = inspect_gnina_flex_pdb(
                        read_text(flex_output), ligand_models, read_text(flex),
                    )
                    case.record[flex_file] = summary
                    case.record["max_displacement_angstrom"] = summary["max_displacement_angstrom"]
                except ValueError as error:
                    case.record[flex_file] = {"parse_error": str(error)}
                    case.record["status"] = "parse_error"


def gnina_probes(probe: Probe, receptor: Receptor, amide: Path | None) -> None:
    parent = "E/E4_gnina_linux_flex_and_score_only"
    cpu_ligand = cpu_flex = None
    for compute, compute_args in (("cpu", ["--no_gpu"]), ("cuda", ["--device", "0"])):
        case = probe.case(f"{parent}/gnina_flex_{compute}")
        if not sys.platform.startswith("linux"):
            case.skip("skipped_platform", "GNINA is Linux-only")
            continue
        box = engine_case(case, receptor.box, receptor.rigid, receptor.flex, amide)
        if box is None:
            continue
        ligand_file = f"gnina_lig_{compute}.pdbqt"
        flex_file = f"gnina_flex_{compute}.pdbqt"
        run = probe.run(case, "gnina", [
            *FLEX_ARGS, *box, *SEARCH_ARGS, *GNINA_HYDROGEN_ARGS, *compute_args,
            "--out", ligand_file, "--out_flex", flex_file,
        ])
        case.record["requested_compute"] = compute
        case.record["no_gpu_warning"] = "No GPU detected" in run.stdout + run.stderr
        ligand_output = observe_pdbqt(case, ligand_file, run)
        flex_output = observe_pdbqt(case, flex_file, run, flex=receptor.flex, flex_file=True)
        if compute == "cpu":
            cpu_ligand, cpu_flex = ligand_output, flex_output

    gnina_meeko_reinjection_probes(probe, parent, receptor, amide)

    parent += "/gnina_score_only_and_local_only_with_flex"
    extraction = probe.case(f"{parent}/pose1")
    ligand = flex = None
    if sys.platform.startswith("linux"):
        ligand, flex = prepare_pose_inputs(
            extraction, cpu_ligand, cpu_flex, gnina_reference=receptor.flex,
            ligand_name="model1_lig.pdbqt", flex_name="model1_flex.pdbqt",
        )
    else:
        extraction.skip("skipped_platform", "GNINA is Linux-only")
    for mode in ("score_only", "local_only"):
        case = probe.case(f"{parent}/{mode}")
        if not sys.platform.startswith("linux"):
            case.skip("skipped_platform", "GNINA is Linux-only")
            continue
        box = engine_case(case, receptor.box, receptor.rigid, ligand, flex)
        if box is None:
            continue
        output_args = (
            ["--out", "gnina_local_lig.pdbqt", "--out_flex", "gnina_local_flex.pdbqt"]
            if mode == "local_only" else []
        )
        run = probe.run(case, "gnina", [
            "--receptor", RIGID_NAME, "--flex", "model1_flex.pdbqt",
            "--ligand", "model1_lig.pdbqt", *box, *GNINA_HYDROGEN_ARGS, "--cpu", "1",
            "--seed", "42", f"--{mode}", "--no_gpu", *output_args,
        ])
        case.record["stdout_scores"] = stdout_scores(run.stdout)
        if mode == "local_only":
            observe_pdbqt(case, "gnina_local_lig.pdbqt", run)
            observe_pdbqt(case, "gnina_local_flex.pdbqt", run, flex=flex, flex_file=True)


def group_e(probe: Probe, receptor: Receptor, ligands: dict[str, Path]) -> None:
    amide = ligands.get("amide_default")
    vina_probes(probe, receptor, amide)
    parent = "E/E2_autogrid4_flex_types_missing_vs_union"
    autodock4_probe(
        probe, probe.case(f"{parent}/ligand_only"), receptor.rigid, receptor.box,
        amide, flex=receptor.flex, map_policy="ligand_only",
    )
    union_maps = autodock4_probe(
        probe, probe.case(f"{parent}/union"), receptor.rigid, receptor.box,
        amide, flex=receptor.flex, map_policy="union",
    )
    autodock4_probe(
        probe, probe.case("E/E2_autodock4_rigid_macrocycle"), receptor.full, receptor.box,
        ligands.get("macrocycle_rigid"), map_policy="rigid",
    )
    autodock_gpu_probes(probe, union_maps, amide, receptor.flex)
    gnina_probes(probe, receptor, amide)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out-dir", type=Path, required=True, help="New directory for raw evidence"
    )
    for name in ("vina", "autogrid4", "autodock4", "autodock-gpu", "gnina"):
        parser.add_argument(f"--{name}", type=Path, help=f"Path to the {name} executable")
    parser.add_argument("--gnina-ld-library-path", help="Extra LD_LIBRARY_PATH for GNINA only")
    args = parser.parse_args(argv)
    root = args.out_dir.expanduser().resolve()
    try:
        root.mkdir(parents=True, exist_ok=False)
    except OSError as error:
        parser.error(f"Could not create a new --out-dir: {error}")

    probe = Probe(root, args)
    tools = probe.tool_inventory()
    ligands = group_l(probe)
    receptor = group_r(probe)
    group_e(probe, receptor, ligands)
    evidence = {
        "schema_version": 1,
        "probe": "ADR-032 M1 Gate 0",
        "platform": {"system": platform.system(), "machine": platform.machine()},
        "fixture_protocol": {"etkdg": "ETKDGv3", "seed": SEED, "optimization": "MMFF94s"},
        "binding_box": receptor.box.model_dump() if receptor.box else None,
        "box_center_source": "Mean optimized heavy-atom coordinates of TYR A:4 and MET A:5",
        "flex_movement_tolerance_angstrom": COORDINATE_TOLERANCE,
        "gnina_ld_library_path_prepended": bool(
            args.gnina_ld_library_path and sys.platform.startswith("linux")
        ),
        "tools": tools,
        "cases": {name: case.finish() for name, case in probe.cases.items()},
    }
    with (root / "evidence.json").open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(portable_value(evidence), stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")
    counts = Counter(str(case.record["status"]) for case in probe.cases.values())
    summary = ", ".join(f"{key}={counts[key]}" for key in sorted(counts))
    print(f"Wrote evidence.json ({summary})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
