"""AutoDock-GPU adapter.

Every expectation here comes from running the real `AutoDock-GPU.exe` v1.6:
the `.dlg` fixture is genuine output from a real docking against a real map
set, and the stdout verdicts are the tool's own words, captured verbatim from
a successful run and a failed one.
"""

from pathlib import Path

import pytest

from ankora_backend.adapters.engines.autodock4_job import (
    log_reports_success,
    parse_autodock4_log,
)
from ankora_backend.adapters.engines.autodock_gpu import (
    AutoDockGpuInstallation,
    build_arguments,
    require_device,
    run_reports_success,
)
from ankora_backend.domain.errors import AnkoraDomainError

FIXTURES = Path(__file__).parent / "fixtures"
REAL_GPU_LOG = FIXTURES / "autodock_gpu_real_compound252.dlg"


def _installation(device_name: str | None) -> AutoDockGpuInstallation:
    return AutoDockGpuInstallation(
        executable="synthetic", version="1.6", sha256="a" * 64,
        architecture="x86_64", build="Release", device_name=device_name,
    )


def _arguments(**overrides: object) -> list[str]:
    settings: dict[str, object] = {
        "device_number": 1, "runs": 10, "seed": (2, 3, 4), "heuristics": False,
        "autostop": False, "energy_evaluations": 2_500_000, "population_size": 150,
        "local_search_method": "ad", "cluster_rmsd_tolerance_angstrom": 2.0,
    }
    settings.update(overrides)
    return build_arguments(**settings)  # type: ignore[arg-type]


def _value_after(arguments: list[str], flag: str) -> str:
    return arguments[arguments.index(flag) + 1]


# --- the verdict, which the exit code cannot give -------------------------


def test_the_tools_own_words_decide_whether_a_run_worked() -> None:
    """A run whose map file did not exist still returned exit code zero."""
    assert run_reports_success("All jobs ran without errors.") is True
    assert run_reports_success(
        "Error in setup of Job #1\nThe job was not successful."
    ) is False


def test_a_run_that_claims_nothing_is_not_assumed_to_have_worked() -> None:
    assert run_reports_success("Run time 0.479 sec\nIdle time 0.415 sec") is False
    assert run_reports_success("") is False


def test_a_failure_notice_outweighs_a_success_notice() -> None:
    """A batch that reports both did not fully succeed, so it is not a success."""
    assert run_reports_success(
        "All jobs ran without errors.\nThe job was not successful."
    ) is False


# --- the one parser incompatibility, pinned against real output -----------


def test_the_cpu_parser_reads_real_gpu_output_unchanged() -> None:
    """ADR-015 called the shared .dlg format the decisive detail. It holds."""
    parsed = parse_autodock4_log(REAL_GPU_LOG.read_text(encoding="utf-8"))

    assert parsed.clusters, "no clusters parsed from real AutoDock-GPU output"
    assert parsed.ranking, "no ranking rows parsed from real AutoDock-GPU output"
    assert parsed.poses, "no poses parsed from real AutoDock-GPU output"
    # Cluster populations must account for every run the log ranked.
    assert sum(cluster.run_count for cluster in parsed.clusters) == len(parsed.ranking)
    assert parsed.clusters[0].lowest_binding_energy_kcal_mol < 0


def test_the_cpu_success_marker_is_absent_from_real_gpu_output() -> None:
    """This is why the GPU needs its own verdict.

    AutoDock-GPU never writes "Successful Completion"; its log ends at
    `Run time` / `Idle time`. Reusing the CPU check would call every good GPU
    run a failure.
    """
    document = REAL_GPU_LOG.read_text(encoding="utf-8")

    assert log_reports_success(document) is False
    assert "Successful Completion" not in document
    assert "Run time" in document


# --- the command line, which is the recorded protocol ---------------------


def test_every_setting_that_governs_the_search_is_stated_explicitly() -> None:
    """The tool's defaults silently decide how much searching happens.

    Heuristics and automatic stopping are on by default, so a protocol that
    omitted them would not describe the run that was performed.
    """
    arguments = _arguments()

    for flag in (
        "--nrun", "--seed", "--heuristics", "--autostop",
        "--psize", "--lsmet", "--rmstol", "--nev", "--devnum",
    ):
        assert flag in arguments, f"{flag} is not stated"


def test_the_heuristic_and_an_explicit_evaluation_count_are_mutually_exclusive() -> None:
    """With the heuristic on, it is the heuristic that sets the count."""
    heuristic = _arguments(heuristics=True, energy_evaluations=None)
    assert _value_after(heuristic, "--heuristics") == "1"
    assert "--nev" not in heuristic

    explicit = _arguments(heuristics=False, energy_evaluations=2_500_000)
    assert _value_after(explicit, "--heuristics") == "0"
    assert _value_after(explicit, "--nev") == "2500000"


def test_disabling_the_heuristic_without_saying_how_long_to_search_is_refused() -> None:
    with pytest.raises(AnkoraDomainError) as error:
        _arguments(heuristics=False, energy_evaluations=None)

    assert error.value.code == "AUTODOCK_GPU_EVALUATIONS_REQUIRED"


def test_the_three_part_seed_is_passed_the_way_the_tool_expects() -> None:
    """`--seed` takes up to three comma-separated integers."""
    assert _value_after(_arguments(seed=(11, 22, 33)), "--seed") == "11,22,33"


def test_a_whole_number_tolerance_is_not_written_as_a_float() -> None:
    assert _value_after(_arguments(cluster_rmsd_tolerance_angstrom=2.0), "--rmstol") == "2"
    assert _value_after(
        _arguments(cluster_rmsd_tolerance_angstrom=1.5), "--rmstol"
    ) == "1.5"


def test_the_requested_device_is_the_one_named_on_the_command_line() -> None:
    assert _value_after(_arguments(device_number=2), "--devnum") == "2"


def test_the_log_ankora_parses_is_the_one_it_asked_the_tool_to_write() -> None:
    arguments = _arguments()

    assert _value_after(arguments, "--dlgoutput") == "1"
    # The XML duplicates the log Ankora already parses, so it is not requested.
    assert _value_after(arguments, "--xmloutput") == "0"
    assert _value_after(arguments, "--resnam") == "ligand"


# --- refusing to dock without hardware ------------------------------------


def test_a_machine_with_no_device_is_refused_before_docking() -> None:
    with pytest.raises(AnkoraDomainError) as error:
        require_device(_installation(None))

    assert error.value.code == "AUTODOCK_GPU_NO_DEVICE"
    assert error.value.status_code == 422


def test_a_named_device_is_returned_for_the_record() -> None:
    installation = _installation("NVIDIA GeForce RTX 5050 Laptop GPU")

    assert require_device(installation) == "NVIDIA GeForce RTX 5050 Laptop GPU"
    assert installation.device_available is True
