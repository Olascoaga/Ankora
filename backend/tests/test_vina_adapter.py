"""Deterministic tests for the AutoDock Vina adapter.

All molecular text in this file is explicitly synthetic. No score is intended
to represent a real docking calculation.
"""

from pathlib import Path

import pytest

from ankora_backend.adapters.engines.vina import build_vina_arguments, parse_vina_poses
from ankora_backend.domain.errors import AnkoraDomainError
from ankora_backend.schemas.binding_sites import BindingBox
from ankora_backend.schemas.docking import VinaDockingParameters


def test_build_vina_arguments_records_every_scientific_parameter(tmp_path: Path) -> None:
    receptor = tmp_path / "receptor.pdbqt"
    ligand = tmp_path / "ligand.pdbqt"
    output = tmp_path / "poses.pdbqt"
    arguments = build_vina_arguments(
        receptor_path=receptor,
        ligand_path=ligand,
        output_path=output,
        box=BindingBox(
            center_x=1.25,
            center_y=-2.5,
            center_z=3.75,
            size_x=20,
            size_y=22,
            size_z=24,
        ),
        parameters=VinaDockingParameters(
            cpu_threads=7,
            seed=991,
            exhaustiveness=16,
            num_modes=12,
            min_rmsd_angstrom=1.5,
            energy_range_kcal_mol=4.5,
            timeout_minutes=60,
        ),
    )

    assert arguments == [
        "--receptor",
        str(receptor),
        "--ligand",
        str(ligand),
        "--center_x",
        "1.25",
        "--center_y",
        "-2.5",
        "--center_z",
        "3.75",
        "--size_x",
        "20",
        "--size_y",
        "22",
        "--size_z",
        "24",
        "--cpu",
        "7",
        "--seed",
        "991",
        "--exhaustiveness",
        "16",
        "--num_modes",
        "12",
        "--min_rmsd",
        "1.5",
        "--energy_range",
        "4.5",
        "--verbosity",
        "1",
        "--out",
        str(output),
    ]


def test_parse_vina_poses_uses_exact_synthetic_result_records() -> None:
    content = (
        b"MODEL 1\n"
        b"REMARK VINA RESULT: -7.500 0.000 0.000\n"
        b"ATOM      1  C   LIG A   1       0.000   0.000   0.000  0.00  0.00    +0.000 C\n"
        b"ENDMDL\n"
        b"MODEL 2\n"
        b"REMARK VINA RESULT: -7.100 1.250 2.000\n"
        b"ATOM      1  C   LIG A   1       1.000   0.000   0.000  0.00  0.00    +0.000 C\n"
        b"ENDMDL\n"
    )

    poses = parse_vina_poses(content)

    assert [pose.mode for pose in poses] == [1, 2]
    assert poses[0].affinity_kcal_mol == pytest.approx(-7.5)
    assert poses[1].rmsd_lower_bound_angstrom == pytest.approx(1.25)
    assert poses[1].rmsd_upper_bound_angstrom == pytest.approx(2.0)
    assert poses[0].content.startswith(b"MODEL 1\n")
    assert poses[0].content.endswith(b"ENDMDL\n")
    assert b"MODEL 2" not in poses[0].content


def test_parse_vina_poses_rejects_output_without_structured_result() -> None:
    with pytest.raises(AnkoraDomainError) as captured:
        parse_vina_poses(b"MODEL 1\nREMARK human prose only\nENDMDL\n")

    assert captured.value.code == "VINA_OUTPUT_INVALID"
