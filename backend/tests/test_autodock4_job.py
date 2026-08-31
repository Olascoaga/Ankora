"""AutoDock4 DPF/DLG contract tests, anchored to a real captured run.

`autodock4_real_compound1.dlg` is genuine output from `autodock4.exe` 4.2.6 on
the authoritative Windows machine: the real 7AQF co-crystallized-ligand map set
`ebb2a3b0-ca05-4621-bae2-90c08cce9cbc` docked against the real prepared ligand
Compound 1, with `ga_run 3`. It is the reference for every anchor parsed here.
"""

from pathlib import Path

import pytest
from pydantic import ValidationError

from ankora_backend.adapters.engines.autodock4_job import (
    log_reports_success,
    parse_autodock4_log,
    render_autodock4_dpf,
)
from ankora_backend.domain.errors import AnkoraDomainError
from ankora_backend.schemas.autodock4 import AutoDock4BatchParameters

FIXTURES = Path(__file__).parent / "fixtures"
REAL_LOG = (FIXTURES / "autodock4_real_compound1.dlg").read_text(
    encoding="utf-8", errors="replace"
)


def test_real_log_reports_successful_completion() -> None:
    assert log_reports_success(REAL_LOG) is True
    assert log_reports_success("autodock partial output\n") is False


def test_real_log_yields_autodock_own_cluster_ranking() -> None:
    """AutoDock clusters independent runs rather than returning a flat pose
    list, and cluster population is scientifically meaningful, so both the
    histogram and the per-run ranking are preserved."""
    parsed = parse_autodock4_log(REAL_LOG)

    assert [cluster.cluster_rank for cluster in parsed.clusters] == [1, 2]
    assert parsed.clusters[0].lowest_binding_energy_kcal_mol == -3.40
    assert parsed.clusters[0].representative_run == 3
    assert parsed.clusters[0].mean_binding_energy_kcal_mol == -3.40
    assert parsed.clusters[0].run_count == 2
    assert parsed.clusters[1].run_count == 1
    assert sum(cluster.run_count for cluster in parsed.clusters) == 3


def test_real_log_ranking_rows_carry_run_energy_and_both_rmsds() -> None:
    parsed = parse_autodock4_log(REAL_LOG)

    assert len(parsed.ranking) == 3
    first = parsed.ranking[0]
    assert (first.cluster_rank, first.sub_rank, first.run) == (1, 1, 3)
    assert first.binding_energy_kcal_mol == -3.40
    assert first.cluster_rmsd_angstrom == 0.00
    assert first.reference_rmsd_angstrom == 39.29
    second = parsed.ranking[1]
    assert (second.cluster_rank, second.sub_rank, second.run) == (1, 2, 2)
    assert second.cluster_rmsd_angstrom == 0.11
    assert parsed.ranking[2].binding_energy_kcal_mol == -3.16


def test_real_log_poses_round_trip_to_standalone_pdbqt() -> None:
    """Each conformation is embedded with a literal `DOCKED: ` prefix; stripping
    it must reproduce a PDBQT the viewer can load."""
    parsed = parse_autodock4_log(REAL_LOG)

    assert [pose.run for pose in parsed.poses] == [1, 2, 3]
    first = parsed.poses[0].content.decode("utf-8")
    assert first.startswith("MODEL")
    assert first.rstrip().endswith("ENDMDL")
    assert "DOCKED:" not in first
    assert "ATOM      1  N   UNL     1" in first
    assert parsed.poses[0].binding_energy_kcal_mol == -3.16
    # The pose energies agree with the independent ranking table.
    by_run = {row.run: row.binding_energy_kcal_mol for row in parsed.ranking}
    assert all(by_run[pose.run] == pose.binding_energy_kcal_mol for pose in parsed.poses)


def test_log_without_ranking_records_is_rejected() -> None:
    stripped = "\n".join(
        line for line in REAL_LOG.splitlines() if not line.rstrip().endswith("RANKING")
    )

    with pytest.raises(AnkoraDomainError) as failure:
        parse_autodock4_log(stripped)

    assert failure.value.code == "AUTODOCK4_OUTPUT_INVALID"
    assert failure.value.details["reason"] == "no RANKING records"


def test_ranking_and_docked_run_disagreement_is_rejected() -> None:
    """A log whose ranking table and conformations describe different runs is
    not a partially usable result; it means the parse anchors drifted."""
    corrupted = REAL_LOG.replace("DOCKED: USER    Run = 3", "DOCKED: USER    Run = 9")

    with pytest.raises(AnkoraDomainError) as failure:
        parse_autodock4_log(corrupted)

    assert "do not match" in failure.value.details["reason"]


def test_rendered_dpf_matches_the_real_accepted_parameter_file() -> None:
    """The captured DPF actually produced the real DLG above, so the renderer is
    checked against a parameter file AutoDock4 already accepted."""
    real_dpf = (FIXTURES / "autodock4_real_compound1.dpf").read_text(encoding="ascii")

    rendered = render_autodock4_dpf(
        ligand_filename="ligand.pdbqt",
        map_prefix="receptor",
        # Order of first appearance in the prepared PDBQT, which is what the
        # accepted real DPF carries; AutoDock matches `map` lines positionally.
        ligand_atom_types=("NA", "N", "A", "HD"),
        about=(-0.4971, -0.0833, -0.0233),
        torsional_degrees_of_freedom=0,
        seed=(20260824, 20260824),
        ga_runs=3,
        ga_population_size=150,
        ga_energy_evaluations=250_000,
        ga_generations=27_000,
        cluster_rmsd_tolerance_angstrom=2.0,
    )

    assert rendered == real_dpf


def test_map_lines_follow_ligand_type_order_because_autodock_matches_positionally() -> None:
    rendered = render_autodock4_dpf(
        ligand_filename="ligand.pdbqt",
        map_prefix="receptor",
        ligand_atom_types=("OA", "C"),
        about=(0.0, 0.0, 0.0),
        torsional_degrees_of_freedom=4,
        seed=(1, 2),
        ga_runs=10,
        ga_population_size=150,
        ga_energy_evaluations=2_500_000,
        ga_generations=27_000,
        cluster_rmsd_tolerance_angstrom=2.0,
    )

    lines = rendered.splitlines()
    assert "ligand_types OA C" in lines
    assert lines.index("map receptor.OA.map") < lines.index("map receptor.C.map")
    assert "seed 1 2" in lines
    assert "torsdof 4" in lines
    assert "ga_run 10" in lines


def test_a_dpf_without_ligand_types_is_refused() -> None:
    with pytest.raises(AnkoraDomainError) as failure:
        render_autodock4_dpf(
            ligand_filename="ligand.pdbqt",
            map_prefix="receptor",
            ligand_atom_types=(),
            about=(0.0, 0.0, 0.0),
            torsional_degrees_of_freedom=0,
            seed=(1, 2),
            ga_runs=1,
            ga_population_size=150,
            ga_energy_evaluations=250_000,
            ga_generations=27_000,
            cluster_rmsd_tolerance_angstrom=2.0,
        )

    assert failure.value.code == "AUTODOCK4_REQUEST_INVALID"


def test_a_single_run_log_is_rejected_rather_than_invented() -> None:
    """AutoDock4 4.2.6 emits no clustering, RMSD table or RANKING records for a
    single run. Ankora must refuse to build a cluster-native result from that
    instead of inventing a one-member cluster the tool never reported."""
    single_run = "\n".join(
        line
        for line in REAL_LOG.splitlines()
        if not line.rstrip().endswith("RANKING")
        and "CLUSTERING HISTOGRAM" not in line
    )

    with pytest.raises(AnkoraDomainError) as failure:
        parse_autodock4_log(single_run)

    assert failure.value.code == "AUTODOCK4_OUTPUT_INVALID"


def test_a_seed_autodock4_refuses_outright_is_rejected_before_launching_it() -> None:
    """AutoDock4 fatals on a seed of zero or one, verified against 4.2.6:
    "Random number seed cannot be zero or one, or negative". Accepting 1 and
    letting the tool die mid-campaign is not validation.
    """
    for seed in (0, 1):
        with pytest.raises(ValidationError):
            AutoDock4BatchParameters(seed_1=seed)
        with pytest.raises(ValidationError):
            AutoDock4BatchParameters(seed_2=seed)

    # Two is the first value the tool accepts, confirmed by a real run.
    assert AutoDock4BatchParameters(seed_1=2, seed_2=2).seed_1 == 2
