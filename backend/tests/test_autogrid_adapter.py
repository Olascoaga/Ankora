"""Contract tests for AutoGrid probing and its self-reported execution limits."""

from pathlib import Path

import pytest

from ankora_backend.adapters.engines import autogrid as autogrid_module
from ankora_backend.adapters.engines.autodock4 import plan_autodock_grid
from ankora_backend.adapters.engines.autogrid import (
    AutoGridInstallation,
    probe_autogrid4,
    validate_against_autogrid_limits,
)
from ankora_backend.adapters.tools.discovery import DiscoveredTool
from ankora_backend.domain.errors import AnkoraDomainError
from ankora_backend.execution.subprocess_runner import ToolExecution
from ankora_backend.schemas.binding_sites import BindingBox

# Captured verbatim from the real `autogrid4.exe --version` on the authoritative
# Windows machine, so the parser is pinned to genuine output rather than a guess.
REAL_VERSION_OUTPUT = """AutoGrid 4.2.6
compilation options:
  Double-precision calculations (USE_DOUBLE):  yes
  Non-bond cutoff for internal energy calculation (NBC): 8.00
  Optimize internal energy scoring (USE_8A_NBCUTOFF):  yes
  Maximum number of receptor atom types (NUM_RECEPTOR_TYPES): 20
  Maximum number of atom types (MAX_ATOM_TYPES): 14
  Maximum number of maps (MAX_MAPS): 16
  Maximum dimension of map x, y, or z (MAX_GRID_PTS): 1025
  Size of int 4, long 4, float 4, double 8, Real 8 bytes.

 Copyright (C) 2009 The Scripps Research Institute.
 License GPLv2+: GNU GPL version 2 or later <http://gnu.org/licenses/gpl.html>
"""


def _installation(**overrides: object) -> AutoGridInstallation:
    defaults: dict[str, object] = {
        "executable": "synthetic-autogrid4.exe",
        "version": "4.2.6",
        "sha256": "a" * 64,
        "architecture": "x86",
        "max_receptor_types": 20,
        "max_ligand_types": 14,
        "max_maps": 16,
        "max_grid_points": 1025,
    }
    defaults.update(overrides)
    return AutoGridInstallation(**defaults)  # type: ignore[arg-type]


def _patch_probe(
    monkeypatch: pytest.MonkeyPatch, *, output: str, exit_code: int = 0
) -> None:
    monkeypatch.setattr(
        autogrid_module,
        "discover_autogrid4",
        lambda *_args, **_kwargs: DiscoveredTool(
            available=True,
            path=str(Path("tools/autodock4-4.2.6/autogrid4.exe")),
            version="4.2.6",
            architecture="x86",
            sha256="b" * 64,
        ),
    )
    monkeypatch.setattr(
        autogrid_module,
        "run_tool",
        lambda **_kwargs: ToolExecution(
            command=["autogrid4.exe", "--version"],
            exit_code=exit_code,
            stdout=output,
            stderr="",
        ),
    )


def test_probe_reads_the_limits_autogrid_reports_for_itself(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_probe(monkeypatch, output=REAL_VERSION_OUTPUT)

    installation = probe_autogrid4()

    assert installation.version == "4.2.6"
    assert installation.max_receptor_types == 20
    assert installation.max_ligand_types == 14
    assert installation.max_maps == 16
    assert installation.max_grid_points == 1025
    assert installation.sha256 == "b" * 64


def test_probe_rejects_output_without_the_compiled_limits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A build that does not report its ceilings cannot be validated against
    them, so it must not be trusted to run silently."""
    _patch_probe(monkeypatch, output="AutoGrid 4.2.6\n")

    with pytest.raises(AnkoraDomainError) as failure:
        probe_autogrid4()

    assert failure.value.code == "AUTOGRID_VERSION_UNVERIFIED"
    assert failure.value.details["missing_limits"] == [
        "max_grid_points",
        "max_ligand_types",
        "max_maps",
        "max_receptor_types",
    ]


def test_probe_rejects_an_unvalidated_autogrid_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_probe(
        monkeypatch, output=REAL_VERSION_OUTPUT.replace("AutoGrid 4.2.6", "AutoGrid 4.3.0")
    )

    with pytest.raises(AnkoraDomainError) as failure:
        probe_autogrid4()

    assert failure.value.code == "AUTOGRID_VERSION_UNSUPPORTED"
    assert failure.value.details["detected_version"] == "4.3.0"


def test_a_box_needing_more_intervals_than_autogrid_allows_is_rejected() -> None:
    """`MAX_GRID_PTS` counts points while `npts` counts intervals, so a build
    reporting 1025 points accepts at most 1024 intervals per axis.

    `BindingBox` already caps an axis at 200 A, so this ceiling is reached by
    refining the spacing rather than by enlarging the box.
    """
    plan = plan_autodock_grid(
        BindingBox(center_x=0, center_y=0, center_z=0, size_x=200, size_y=20, size_z=20),
        spacing_angstrom=0.1,
    )

    with pytest.raises(AnkoraDomainError) as failure:
        validate_against_autogrid_limits(
            _installation(),
            plan=plan,
            receptor_atom_types=("C",),
            ligand_atom_types=("C",),
        )

    assert failure.value.code == "AUTOGRID_BOX_EXCEEDS_GRID_LIMIT"
    assert failure.value.details["max_intervals_per_axis"] == 1024
    assert failure.value.details["oversized_axes"] == {"x": 2000}


def test_a_box_exactly_at_the_interval_ceiling_is_accepted() -> None:
    plan = plan_autodock_grid(
        BindingBox(
            center_x=0, center_y=0, center_z=0, size_x=102.4, size_y=20, size_z=20
        ),
        spacing_angstrom=0.1,
    )

    assert plan.npts[0] == 1024
    validate_against_autogrid_limits(
        _installation(),
        plan=plan,
        receptor_atom_types=("C",),
        ligand_atom_types=("C",),
    )


def test_map_count_ceiling_accounts_for_electrostatic_and_desolvation_maps() -> None:
    """A build allowing 14 ligand types but only 16 maps has no room for a
    fifteenth affinity map once the two mandatory maps are counted."""
    plan = plan_autodock_grid(
        BindingBox(center_x=0, center_y=0, center_z=0, size_x=20, size_y=20, size_z=20)
    )

    with pytest.raises(AnkoraDomainError) as failure:
        validate_against_autogrid_limits(
            _installation(max_maps=10),
            plan=plan,
            receptor_atom_types=("C",),
            ligand_atom_types=tuple(f"X{index}" for index in range(9)),
        )

    assert failure.value.code == "AUTOGRID_MAP_COUNT_EXCEEDED"
    assert failure.value.details["required_maps"] == 11
