"""Synthetic contract tests for AutoDock4 grid and PDBQT preflight behavior."""

import pytest

from ankora_backend.adapters.engines.autodock4 import (
    collect_autodock_atom_types,
    plan_autodock_grid,
    preflight_autodock4_cpu_atom_types,
    preflight_autodock4_receptor_atom_types,
    render_autogrid_gpf,
)
from ankora_backend.schemas.binding_sites import BindingBox


def test_full_protein_grid_covers_the_confirmed_7aqf_box() -> None:
    box = BindingBox(
        center_x=0,
        center_y=0,
        center_z=0,
        size_x=58.521,
        size_y=85.371,
        size_z=68.626,
    )

    plan = plan_autodock_grid(box)

    assert plan.npts == (158, 228, 184)
    assert plan.realized_size_angstrom == pytest.approx((59.25, 85.5, 69.0))
    assert all(count % 2 == 0 for count in plan.npts)
    assert all(
        realized >= requested
        for requested, realized in zip(
            plan.requested_size_angstrom, plan.realized_size_angstrom, strict=True
        )
    )


def test_atom_type_preflight_builds_a_deterministic_library_union() -> None:
    receptor = "ATOM      1  C   SYN A   1       0.0 0.0 0.0  0.00  0.00     0.000 C\n"
    ligand_one = "HETATM    1  O   SYN L   1       0.0 0.0 0.0  0.00  0.00    -0.100 OA\n"
    ligand_two = (
        "HETATM    1  N   SYN L   1       0.0 0.0 0.0  0.00  0.00    -0.100 NA\n"
        "HETATM    2  C   SYN L   1       1.0 0.0 0.0  0.00  0.00     0.100 C\n"
    )

    assert collect_autodock_atom_types((receptor, ligand_one, ligand_two)) == (
        "C",
        "NA",
        "OA",
    )


def test_atom_type_preflight_rejects_a_document_without_atoms() -> None:
    with pytest.raises(ValueError, match="No PDBQT atom records"):
        collect_autodock_atom_types(("REMARK SYNTHETIC EMPTY PDBQT\n",))


def test_cpu_preflight_rejects_macrocycle_glue_without_coercion() -> None:
    with pytest.raises(ValueError, match=r"CG0, G0.*must not be coerced"):
        preflight_autodock4_cpu_atom_types(("C", "CG0", "G0", "OA"))


def test_cpu_preflight_rejects_more_than_fourteen_affinity_maps() -> None:
    with pytest.raises(ValueError, match="at most 14"):
        preflight_autodock4_cpu_atom_types(f"X{index}" for index in range(15))


def test_receptor_preflight_accepts_exactly_twenty_receptor_types() -> None:
    """AutoGrid 4.2.6's real `--version` probe reports 20 receptor types, so
    twenty must pass; this pins the boundary against an off-by-one."""
    requested = tuple(f"X{index}" for index in range(20))

    assert preflight_autodock4_receptor_atom_types(requested) == tuple(sorted(requested))


def test_receptor_preflight_rejects_more_than_twenty_receptor_types() -> None:
    with pytest.raises(ValueError, match="at most 20 receptor atom types"):
        preflight_autodock4_receptor_atom_types(f"X{index}" for index in range(21))


def test_gpf_renderer_rejects_a_receptor_exceeding_the_autogrid_type_limit() -> None:
    box = BindingBox(
        center_x=0,
        center_y=0,
        center_z=0,
        size_x=20,
        size_y=20,
        size_z=20,
    )

    with pytest.raises(ValueError, match="at most 20 receptor atom types"):
        render_autogrid_gpf(
            box,
            receptor_filename="receptor.pdbqt",
            receptor_atom_types=(f"X{index}" for index in range(21)),
            ligand_atom_types=("C",),
        )


def test_gpf_renderer_uses_covering_grid_and_calibrated_ad4_defaults() -> None:
    box = BindingBox(
        center_x=35.4305,
        center_y=-2.967,
        center_z=-0.7905,
        size_x=21.597,
        size_y=19.87,
        size_z=19.317,
    )

    gpf, plan = render_autogrid_gpf(
        box,
        receptor_filename="receptor.pdbqt",
        receptor_atom_types=("SA", "A", "C", "OA", "HD", "N", "NA"),
        ligand_atom_types=("OA", "C", "A", "NA"),
    )

    assert plan.npts == (58, 54, 52)
    assert "npts 58 54 52\n" in gpf
    assert "receptor_types A C HD N NA OA SA\n" in gpf
    assert "ligand_types A C NA OA\n" in gpf
    assert "gridcenter 35.431 -2.967 -0.790\n" in gpf
    assert "smooth 0.500\n" in gpf
    assert gpf.endswith("dielectric -0.1465\n")
    assert gpf.index("map receptor.A.map") < gpf.index("map receptor.OA.map")


def test_gpf_renderer_rejects_paths_in_external_tool_filenames() -> None:
    box = BindingBox(
        center_x=0,
        center_y=0,
        center_z=0,
        size_x=20,
        size_y=20,
        size_z=20,
    )

    with pytest.raises(ValueError, match="ASCII-safe basename"):
        render_autogrid_gpf(
            box,
            receptor_filename="folder/receptor.pdbqt",
            receptor_atom_types=("C",),
            ligand_atom_types=("C",),
        )
