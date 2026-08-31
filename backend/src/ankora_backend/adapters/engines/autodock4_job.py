"""Pure AutoDock4 CPU job contracts: DPF rendering and DLG parsing.

Every anchor parsed here was read from a real `autodock4.exe` 4.2.6 run before
this module was written, not inferred from documentation. The captured run is
preserved at `backend/tests/fixtures/autodock4_real_compound1.dlg`.
"""

import math
import re
from dataclasses import dataclass, field

from ankora_backend.domain.errors import AnkoraDomainError

_STAGE = "autodock4_docking"
_SUCCESS_MARKER = "Successful Completion"
_DOCKED_PREFIX = "DOCKED: "

# The RMSD table's rows each end in the literal word AutoDock documents as its
# "Grep Pattern". This is the machine-readable ranking record, the AutoDock
# equivalent of Vina's `REMARK VINA RESULT`, and is parsed instead of the
# decorative histogram bars.
_RANKING_PATTERN = re.compile(
    r"^\s*(\d+)\s+(\d+)\s+(\d+)\s+"
    r"(-?\d+(?:\.\d+)?)\s+(\d+(?:\.\d+)?)\s+(\d+(?:\.\d+)?)\s+RANKING\s*$"
)
# `Clus | Lowest Binding Energy | Run | Mean Binding Energy | Num in Clus | bars`
_HISTOGRAM_PATTERN = re.compile(
    r"^\s*(\d+)\s*\|\s*(-?\d+(?:\.\d+)?)\s*\|\s*(\d+)\s*\|\s*"
    r"(-?\d+(?:\.\d+)?)\s*\|\s*(\d+)\s*\|"
)
_RUN_PATTERN = re.compile(r"^USER\s+Run\s+=\s+(\d+)\s*$")
_FREE_ENERGY_PATTERN = re.compile(
    r"^USER\s+Estimated Free Energy of Binding\s+=\s+(-?\d+(?:\.\d+)?)\s+kcal/mol"
)
_MODEL_PATTERN = re.compile(r"^MODEL\s+(\d+)\s*$")


@dataclass(frozen=True, slots=True)
class AutoDock4RankingRow:
    """One run's placement in AutoDock's own cluster ranking."""

    cluster_rank: int
    sub_rank: int
    run: int
    binding_energy_kcal_mol: float
    cluster_rmsd_angstrom: float
    reference_rmsd_angstrom: float


@dataclass(frozen=True, slots=True)
class AutoDock4Cluster:
    cluster_rank: int
    lowest_binding_energy_kcal_mol: float
    representative_run: int
    mean_binding_energy_kcal_mol: float
    run_count: int


@dataclass(frozen=True, slots=True)
class AutoDock4Pose:
    run: int
    binding_energy_kcal_mol: float
    content: bytes


@dataclass(frozen=True, slots=True)
class ParsedAutoDock4Log:
    clusters: list[AutoDock4Cluster] = field(default_factory=list)
    ranking: list[AutoDock4RankingRow] = field(default_factory=list)
    poses: list[AutoDock4Pose] = field(default_factory=list)


def render_autodock4_dpf(
    *,
    ligand_filename: str,
    map_prefix: str,
    ligand_atom_types: tuple[str, ...],
    about: tuple[float, float, float],
    torsional_degrees_of_freedom: int,
    seed: tuple[int, int],
    ga_runs: int,
    ga_population_size: int,
    ga_energy_evaluations: int,
    ga_generations: int,
    cluster_rmsd_tolerance_angstrom: float,
) -> str:
    """Render a stock AD4.2 Lamarckian-GA docking parameter file.

    The keyword order follows AutoDockTools' own
    `genetic_algorithm_local_search_list4_1`; `map` lines must appear in the
    same order as `ligand_types`, which AutoDock matches positionally.
    """
    if not ligand_atom_types:
        raise _invalid_request("a DPF requires at least one ligand atom type")
    if ga_runs < 1:
        raise _invalid_request("a DPF requires at least one GA run")
    if not all(math.isfinite(value) for value in about):
        raise _invalid_request("the ligand centre of rotation must be finite")
    lines = [
        "autodock_parameter_version 4.2",
        "outlev 1",
        "intelec",
        # AutoDock's own default is `pid time`, which would make a run
        # unreproducible; Ankora always records and passes explicit integers.
        f"seed {seed[0]} {seed[1]}",
        f"ligand_types {' '.join(ligand_atom_types)}",
        f"fld {map_prefix}.maps.fld",
        *[f"map {map_prefix}.{atom_type}.map" for atom_type in ligand_atom_types],
        f"elecmap {map_prefix}.e.map",
        f"desolvmap {map_prefix}.d.map",
        f"move {ligand_filename}",
        f"about {about[0]:.4f} {about[1]:.4f} {about[2]:.4f}",
        "tran0 random",
        "quaternion0 random",
        "dihe0 random",
        f"torsdof {torsional_degrees_of_freedom}",
        f"rmstol {cluster_rmsd_tolerance_angstrom:.2f}",
        "extnrg 1000.0",
        "e0max 0.0 10000",
        f"ga_pop_size {ga_population_size}",
        f"ga_num_evals {ga_energy_evaluations}",
        f"ga_num_generations {ga_generations}",
        "ga_elitism 1",
        "ga_mutation_rate 0.02",
        "ga_crossover_rate 0.8",
        "ga_window_size 10",
        "ga_cauchy_alpha 0.0",
        "ga_cauchy_beta 1.0",
        "set_ga",
        "sw_max_its 300",
        "sw_max_succ 4",
        "sw_max_fail 4",
        "sw_rho 1.0",
        "sw_lb_rho 0.01",
        "ls_search_freq 0.06",
        "set_psw1",
        "unbound_model bound",
        f"ga_run {ga_runs}",
        "analysis",
    ]
    return "\n".join(lines) + "\n"


def log_reports_success(document: str) -> bool:
    """AutoDock can exit zero on an incomplete run, so the log is the verdict."""
    return _SUCCESS_MARKER in document


def parse_autodock4_log(document: str) -> ParsedAutoDock4Log:
    """Parse clusters, ranking, and per-run poses from a real DLG."""
    clusters = _parse_clusters(document)
    ranking = _parse_ranking(document)
    poses = _parse_poses(document)
    if not ranking:
        raise _invalid_output("no RANKING records")
    if not clusters:
        raise _invalid_output("no clustering histogram")
    if not poses:
        raise _invalid_output("no DOCKED conformations")
    ranked_runs = {row.run for row in ranking}
    pose_runs = {pose.run for pose in poses}
    if ranked_runs != pose_runs:
        raise _invalid_output(
            f"ranked runs {sorted(ranked_runs)} do not match "
            f"docked runs {sorted(pose_runs)}"
        )
    clustered = sum(cluster.run_count for cluster in clusters)
    if clustered != len(ranking):
        raise _invalid_output(
            f"clustering histogram accounts for {clustered} runs while the "
            f"ranking table lists {len(ranking)}"
        )
    return ParsedAutoDock4Log(clusters=clusters, ranking=ranking, poses=poses)


def _parse_ranking(document: str) -> list[AutoDock4RankingRow]:
    rows: list[AutoDock4RankingRow] = []
    for line in document.splitlines():
        match = _RANKING_PATTERN.match(line)
        if match is None:
            continue
        rows.append(
            AutoDock4RankingRow(
                cluster_rank=int(match.group(1)),
                sub_rank=int(match.group(2)),
                run=int(match.group(3)),
                binding_energy_kcal_mol=float(match.group(4)),
                cluster_rmsd_angstrom=float(match.group(5)),
                reference_rmsd_angstrom=float(match.group(6)),
            )
        )
    return rows


def _parse_clusters(document: str) -> list[AutoDock4Cluster]:
    lines = document.splitlines()
    try:
        start = next(
            index
            for index, line in enumerate(lines)
            if line.strip() == "CLUSTERING HISTOGRAM"
        )
    except StopIteration:
        return []
    clusters: list[AutoDock4Cluster] = []
    for line in lines[start:]:
        if line.strip() == "RMSD TABLE":
            break
        match = _HISTOGRAM_PATTERN.match(line)
        if match is None:
            continue
        clusters.append(
            AutoDock4Cluster(
                cluster_rank=int(match.group(1)),
                lowest_binding_energy_kcal_mol=float(match.group(2)),
                representative_run=int(match.group(3)),
                mean_binding_energy_kcal_mol=float(match.group(4)),
                run_count=int(match.group(5)),
            )
        )
    return clusters


def _parse_poses(document: str) -> list[AutoDock4Pose]:
    """Recover each docked conformation as a standalone PDBQT.

    AutoDock embeds every pose in the log with a literal `DOCKED: ` prefix on
    each line; stripping it reproduces the PDBQT the viewer and any downstream
    tool expect.
    """
    poses: list[AutoDock4Pose] = []
    block: list[str] = []
    in_model = False
    run: int | None = None
    energy: float | None = None
    for raw in document.splitlines():
        if not raw.startswith(_DOCKED_PREFIX):
            continue
        line = raw[len(_DOCKED_PREFIX) :]
        if _MODEL_PATTERN.match(line):
            if in_model:
                raise _invalid_output("nested DOCKED MODEL records")
            in_model = True
            block = [line]
            run = None
            energy = None
            continue
        if not in_model:
            continue
        block.append(line)
        run_match = _RUN_PATTERN.match(line)
        if run_match is not None:
            run = int(run_match.group(1))
        energy_match = _FREE_ENERGY_PATTERN.match(line)
        if energy_match is not None:
            energy = float(energy_match.group(1))
        if line.startswith("ENDMDL"):
            if run is None or energy is None:
                raise _invalid_output(
                    "a DOCKED conformation has no run number or binding energy"
                )
            poses.append(
                AutoDock4Pose(
                    run=run,
                    binding_energy_kcal_mol=energy,
                    content=("\n".join(block) + "\n").encode("utf-8"),
                )
            )
            in_model = False
            block = []
    if in_model:
        raise _invalid_output("unterminated DOCKED MODEL record")
    return poses


def _invalid_output(reason: str) -> AnkoraDomainError:
    return AnkoraDomainError(
        code="AUTODOCK4_OUTPUT_INVALID",
        stage="autodock4_log_parsing",
        message="AutoDock4 produced an output Ankora could not validate.",
        status_code=500,
        details={"reason": reason},
        recoverable=False,
    )


def _invalid_request(reason: str) -> AnkoraDomainError:
    return AnkoraDomainError(
        code="AUTODOCK4_REQUEST_INVALID",
        stage=_STAGE,
        message="This AutoDock4 job cannot be expressed as a valid DPF.",
        status_code=422,
        details={"reason": reason},
    )
