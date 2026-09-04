"""Validation for explicit Vina sampling-purpose labels.

The values are protocol contracts, not claims about convergence or suitability.
"""

import pytest
from pydantic import ValidationError

from ankora_backend.schemas.docking import (
    VinaBatchDockingParameters,
    VinaDockingParameters,
    VinaSamplingProtocol,
)

VinaParameterModel = type[VinaDockingParameters] | type[VinaBatchDockingParameters]


@pytest.mark.parametrize("model", [VinaDockingParameters, VinaBatchDockingParameters])
def test_historical_parameters_remain_unlabelled(model: VinaParameterModel) -> None:
    parameters = model()

    assert parameters.sampling_protocol is None


@pytest.mark.parametrize("model", [VinaDockingParameters, VinaBatchDockingParameters])
@pytest.mark.parametrize(
    ("protocol", "values"),
    [
        (
            VinaSamplingProtocol.SCREENING,
            {
                "exhaustiveness": 8,
                "num_modes": 9,
                "min_rmsd_angstrom": 1.0,
                "energy_range_kcal_mol": 3.0,
            },
        ),
        (
            VinaSamplingProtocol.POSE_REFINEMENT,
            {
                "exhaustiveness": 32,
                "num_modes": 20,
                "min_rmsd_angstrom": 1.0,
                "energy_range_kcal_mol": 5.0,
            },
        ),
    ],
)
def test_named_protocol_requires_its_exact_recorded_values(
    model: VinaParameterModel,
    protocol: VinaSamplingProtocol,
    values: dict[str, float | int],
) -> None:
    parameters = model(sampling_protocol=protocol, **values)

    assert parameters.sampling_protocol is protocol


@pytest.mark.parametrize("model", [VinaDockingParameters, VinaBatchDockingParameters])
def test_edited_named_protocol_must_be_relabelled_custom(
    model: VinaParameterModel,
) -> None:
    with pytest.raises(ValidationError, match="use 'custom'"):
        model(
            sampling_protocol=VinaSamplingProtocol.SCREENING,
            exhaustiveness=16,
        )

    custom = model(
        sampling_protocol=VinaSamplingProtocol.CUSTOM,
        exhaustiveness=16,
    )
    assert custom.sampling_protocol is VinaSamplingProtocol.CUSTOM
