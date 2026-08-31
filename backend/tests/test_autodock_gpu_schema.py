"""AutoDock-GPU contracts.

The interesting expectations here are not shapes, they are honesty: that a GPU
result says which backend produced it, that it does not claim a reproducibility
the hardware cannot deliver, and that only settings verified to work are
offered.
"""

import pytest
from pydantic import ValidationError

from ankora_backend.schemas.autodock4 import (
    AutoDock4ClusterResult,
    AutoDock4DockingParameters,
    AutoDock4RunResult,
)
from ankora_backend.schemas.autodock_gpu import (
    AutoDockBackend,
    AutoDockClusterResult,
    AutoDockGpuDockingParameters,
    AutoDockGpuLocalSearch,
    AutoDockRunResult,
)


def test_a_gpu_result_never_claims_to_be_reproducible() -> None:
    """Six repeats of one seed on one machine gave six different rankings.

    Ankora's provenance model promises that recorded inputs reproduce a result.
    On this backend that promise cannot be kept, so the record says so rather
    than letting a reader infer determinism from the presence of a seed.
    """
    from ankora_backend.schemas.autodock_gpu import AutoDockGpuDockingJobRecord

    field = AutoDockGpuDockingJobRecord.model_fields["bitwise_reproducible"]

    assert field.default is False


def test_a_record_names_its_backend_without_being_asked() -> None:
    from ankora_backend.schemas.autodock_gpu import AutoDockGpuDockingJobRecord

    assert (
        AutoDockGpuDockingJobRecord.model_fields["backend"].default
        is AutoDockBackend.GPU
    )
    assert AutoDockBackend.CPU.value == "autodock4_cpu"
    assert AutoDockBackend.GPU.value == "autodock_gpu"


def test_the_result_shape_is_shared_with_the_cpu_engine_because_the_science_is()  -> None:
    """Both backends run AutoDock4's force field and write the same log.

    Copying the cluster and run models would invent a distinction the science
    does not have, and would let the two drift apart.
    """
    assert AutoDockClusterResult is AutoDock4ClusterResult
    assert AutoDockRunResult is AutoDock4RunResult


def test_only_local_search_methods_that_actually_run_are_offered() -> None:
    """The parser names five; two of them cannot be used.

    `adam` is refused at runtime by the OpenCL build, and `sd` did not finish
    50,000 evaluations in 180 s where the others take about a second.
    """
    offered = {method.value for method in AutoDockGpuLocalSearch}

    assert offered == {"ad", "sw", "fire"}
    assert "adam" not in offered
    assert "sd" not in offered


def test_the_default_protocol_is_stated_rather_than_adaptive() -> None:
    """The tool's own defaults decide how much searching happens silently."""
    parameters = AutoDockGpuDockingParameters()

    assert parameters.heuristics is False
    assert parameters.autostop is False
    # A stated budget, matching the CPU engine's, so the two backends are at
    # least asked for comparable effort.
    assert parameters.energy_evaluations == (
        AutoDock4DockingParameters().ga_energy_evaluations
    )


def test_one_run_carries_no_reproducibility_evidence_so_two_is_the_floor() -> None:
    """Unlike the CPU build, this tool would happily cluster a single run.

    The floor is Ankora's own and scientific: a cluster of one says nothing
    about whether the search kept finding the same answer.
    """
    with pytest.raises(ValidationError):
        AutoDockGpuDockingParameters(runs=1)

    assert AutoDockGpuDockingParameters(runs=2).runs == 2


def test_the_seed_this_backend_accepts_is_not_the_seed_the_cpu_accepts() -> None:
    """AutoDock-GPU takes zero and one; AutoDock4 fatals on both."""
    assert AutoDockGpuDockingParameters(seed_1=0, seed_2=0, seed_3=0).seed == (0, 0, 0)

    with pytest.raises(ValidationError):
        AutoDock4DockingParameters(seed_1=0)


def test_the_seed_is_handed_over_as_the_three_values_the_tool_takes() -> None:
    parameters = AutoDockGpuDockingParameters(seed_1=11, seed_2=22, seed_3=33)

    assert parameters.seed == (11, 22, 33)


def test_the_device_is_part_of_the_record_because_hardware_changes_the_run() -> None:
    from ankora_backend.schemas.autodock_gpu import AutoDockGpuToolIdentity

    fields = AutoDockGpuToolIdentity.model_fields

    assert "device_name" in fields
    assert "device_number" in fields
    assert fields["device_name"].is_required()


def test_the_execution_evidence_records_where_the_verdict_came_from() -> None:
    """Not from the exit code, which is zero even when the run failed."""
    from ankora_backend.schemas.autodock_gpu import AutoDockGpuExecutionEvidence

    fields = AutoDockGpuExecutionEvidence.model_fields

    assert "success_reported_on_stdout" in fields
    assert "successful_completion_logged" not in fields


def test_an_unknown_search_setting_is_refused_rather_than_ignored() -> None:
    with pytest.raises(ValidationError):
        AutoDockGpuDockingParameters(local_search_method="adam")  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        AutoDockGpuDockingParameters(nev=1000)  # type: ignore[call-arg]
