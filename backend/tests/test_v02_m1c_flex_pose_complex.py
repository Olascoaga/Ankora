"""Tests for E8 coupled PoseComplex materialization and cross-engine flex parsing (M1c-1).

All fixtures in this module are synthetic and explicitly labelled synthetic.
"""

from __future__ import annotations

import math
from pathlib import Path

import pytest

from ankora_backend.adapters.chemistry.flex_pose_complex import (
    materialize_coupled_receptor_pdb,
    parse_gnina_flex_pdb_models,
    reinject_gnina_flex_pdb_into_meeko_template,
    split_coupled_pdbqt_model,
    strip_nul_lines,
)
from ankora_backend.domain.errors import AnkoraDomainError
from ankora_backend.schemas.receptors import ReceptorFlexMode
from ankora_backend.schemas.v02_contracts import PoseComplexIdentity


def _pdb_line(
    serial: int,
    name: str,
    resname: str,
    chain: str,
    resseq: int,
    xyz: tuple[float, float, float],
    element: str,
    *,
    pdbqt_type: str | None = None,
) -> str:
    atom_field = f" {name:<3s}" if len(name) < 4 else f"{name:<4s}"
    if pdbqt_type is not None:
        return (
            f"ATOM  {serial:5d} {atom_field} {resname:>3s} {chain:1s}{resseq:4d}    "
            f"{xyz[0]:8.3f}{xyz[1]:8.3f}{xyz[2]:8.3f}  1.00  0.00     0.000 {pdbqt_type:<2s}\n"
        )
    return (
        f"ATOM  {serial:5d} {atom_field} {resname:>3s} {chain:1s}{resseq:4d}    "
        f"{xyz[0]:8.3f}{xyz[1]:8.3f}{xyz[2]:8.3f}  1.00  0.00          {element:>2s}  \n"
    )


def _rotate_around_axis(
    point: tuple[float, float, float],
    origin: tuple[float, float, float],
    axis_end: tuple[float, float, float],
    angle_deg: float,
) -> tuple[float, float, float]:
    """Rodrigues rotation around directed axis (origin -> axis_end)."""
    ax = axis_end[0] - origin[0]
    ay = axis_end[1] - origin[1]
    az = axis_end[2] - origin[2]
    norm = math.sqrt(ax * ax + ay * ay + az * az)
    ux, uy, uz = ax / norm, ay / norm, az / norm
    px, py, pz = point[0] - origin[0], point[1] - origin[1], point[2] - origin[2]
    theta = math.radians(angle_deg)
    cos_t = math.cos(theta)
    sin_t = math.sin(theta)
    dot = ux * px + uy * py + uz * pz
    cx = uy * pz - uz * py
    cy = uz * px - ux * pz
    cz = ux * py - uy * px
    rx = px * cos_t + cx * sin_t + ux * dot * (1.0 - cos_t)
    ry = py * cos_t + cy * sin_t + uy * dot * (1.0 - cos_t)
    rz = pz * cos_t + cz * sin_t + uz * dot * (1.0 - cos_t)
    return (origin[0] + rx, origin[1] + ry, origin[2] + rz)


def _dist(a: tuple[float, float, float], b: tuple[float, float, float]) -> float:
    return math.sqrt((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2)


def _signed_tetra_volume(
    center: tuple[float, float, float],
    a: tuple[float, float, float],
    b: tuple[float, float, float],
    c: tuple[float, float, float],
) -> float:
    ax, ay, az = a[0] - center[0], a[1] - center[1], a[2] - center[2]
    bx, by, bz = b[0] - center[0], b[1] - center[1], b[2] - center[2]
    cx, cy, cz = c[0] - center[0], c[1] - center[1], c[2] - center[2]
    return (
        ax * (by * cz - bz * cy)
        - ay * (bx * cz - bz * cx)
        + az * (bx * cy - by * cx)
    ) / 6.0


def _synthetic_ligand_block() -> str:
    return (
        "REMARK VINA RESULT:    -3.512      0.000      0.000\n"
        "ROOT\n"
        + _pdb_line(1, "C1", "UNL", " ", 1, (1.0, 2.0, 3.0), "C", pdbqt_type="C")
        + "ENDROOT\n"
        "TORSDOF 1\n"
    )


def _synthetic_met_flex_block(
    coords: dict[str, tuple[float, float, float]], *, start_serial: int = 1
) -> str:
    atoms = [
        ("CA", "C"),
        ("CB", "C"),
        ("CG", "C"),
        ("SD", "SA"),
        ("CE", "C"),
    ]
    s = start_serial
    return (
        "BEGIN_RES MET A 5\n"
        "ROOT\n"
        + _pdb_line(s, "CA", "MET", "A", 5, coords["CA"], "C", pdbqt_type=atoms[0][1])
        + "ENDROOT\n"
        f"BRANCH {s:3d} {s + 1:3d}\n"
        + _pdb_line(s + 1, "CB", "MET", "A", 5, coords["CB"], "C", pdbqt_type=atoms[1][1])
        + f"BRANCH {s + 1:3d} {s + 2:3d}\n"
        + _pdb_line(s + 2, "CG", "MET", "A", 5, coords["CG"], "C", pdbqt_type=atoms[2][1])
        + f"BRANCH {s + 2:3d} {s + 3:3d}\n"
        + _pdb_line(s + 3, "SD", "MET", "A", 5, coords["SD"], "S", pdbqt_type=atoms[3][1])
        + _pdb_line(s + 4, "CE", "MET", "A", 5, coords["CE"], "C", pdbqt_type=atoms[4][1])
        + f"ENDBRANCH {s + 2:3d} {s + 3:3d}\n"
        + f"ENDBRANCH {s + 1:3d} {s + 2:3d}\n"
        + f"ENDBRANCH {s:3d} {s + 1:3d}\n"
        "END_RES MET A 5\n"
    )


def test_strip_nul_lines_removes_windows_vina_30_nul_line_and_rejects_mid_line_nul() -> None:
    text = "TORSDOF 4\r\n" + ("\x00" * 30) + "\r\nBEGIN_RES TYR A 4\r\n"
    cleaned, stripped = strip_nul_lines(text)
    assert stripped == 1
    assert "\x00" not in cleaned
    assert "TORSDOF 4" in cleaned
    assert "BEGIN_RES TYR A 4" in cleaned

    with pytest.raises(AnkoraDomainError) as exc_info:
        strip_nul_lines("ATOM      1  CA  TYR\x00A   4\n")
    assert exc_info.value.code == "FLEX_POSE_PDBQT_EMBEDDED_NUL"
    assert exc_info.value.status_code == 422


def test_split_coupled_pdbqt_handles_windows_vina_nul_line_and_flat_local_only() -> None:
    met_coords = {
        "CA": (0.0, 0.0, 0.0),
        "CB": (1.53, 0.0, 0.0),
        "CG": (2.05, 1.44, 0.0),
        "SD": (3.85, 1.44, 0.0),
        "CE": (4.20, 3.18, 0.40),
    }
    wrapped = (
        "MODEL 1\r\n"
        + _synthetic_ligand_block().replace("\n", "\r\n")
        + ("\x00" * 30)
        + "\r\n"
        + _synthetic_met_flex_block(met_coords).replace("\n", "\r\n")
        + "ENDMDL\r\n"
    )
    split_wrapped = split_coupled_pdbqt_model(wrapped)
    assert split_wrapped.stripped_nul_line_count == 1
    assert split_wrapped.flex_sidechains_pdbqt is not None
    assert split_wrapped.flex_sidechains_sha256 is not None
    assert split_wrapped.flex_residue_markers == ("MET A 5",)
    assert b"\x00" not in split_wrapped.ligand_pdbqt
    assert b"\x00" not in split_wrapped.flex_sidechains_pdbqt
    assert b"BEGIN_RES" not in split_wrapped.ligand_pdbqt
    assert b"TORSDOF 1" in split_wrapped.ligand_pdbqt

    # Flat vina --local_only output (0 MODEL/ENDMDL tags) yields identical split bytes.
    flat = _synthetic_ligand_block() + _synthetic_met_flex_block(met_coords)
    split_flat = split_coupled_pdbqt_model(flat)
    assert split_flat.ligand_sha256 == split_wrapped.ligand_sha256
    assert split_flat.flex_sidechains_sha256 == split_wrapped.flex_sidechains_sha256


def test_split_coupled_pdbqt_rigid_only_and_fail_closed_malformed() -> None:
    rigid = split_coupled_pdbqt_model("MODEL 1\n" + _synthetic_ligand_block() + "ENDMDL\n")
    assert rigid.flex_sidechains_pdbqt is None
    assert rigid.flex_sidechains_sha256 is None
    assert rigid.flex_residue_markers == ()

    with pytest.raises(AnkoraDomainError) as exc_unbalanced:
        split_coupled_pdbqt_model(_synthetic_ligand_block() + "BEGIN_RES MET A 5\nROOT\n")
    assert exc_unbalanced.value.code == "FLEX_POSE_PDBQT_INVALID"

    with pytest.raises(AnkoraDomainError) as exc_mismatch:
        split_coupled_pdbqt_model(
            _synthetic_ligand_block()
            + "BEGIN_RES MET A 5\n"
            + _pdb_line(1, "CA", "MET", "A", 5, (0.0, 0.0, 0.0), "C", pdbqt_type="C")
            + "END_RES TYR A 4\n"
        )
    assert exc_mismatch.value.code == "FLEX_POSE_PDBQT_INVALID"


def test_gnina_flex_pdb_ordinal_pairing_and_meeko_template_reinjection() -> None:
    crystal = {
        "CA": (0.0, 0.0, 0.0),
        "CB": (1.53, 0.0, 0.0),
        "CG": (2.05, 1.44, 0.0),
        "SD": (3.85, 1.44, 0.0),
        "CE": (4.20, 3.18, 0.40),
    }
    moved = {
        "CA": (0.0, 0.0, 0.0),
        "CB": (1.53, 0.0, 0.0),
        "CG": _rotate_around_axis(crystal["CG"], crystal["CA"], crystal["CB"], 95.0),
        "SD": _rotate_around_axis(crystal["SD"], crystal["CA"], crystal["CB"], 95.0),
        "CE": _rotate_around_axis(crystal["CE"], crystal["CA"], crystal["CB"], 95.0),
    }
    template_pdbqt = _synthetic_met_flex_block(crystal, start_serial=1)

    # GNINA labels flex models starting at MODEL 3, MODEL 4 after ligand MODEL 1, MODEL 2.
    gnina_pdb = (
        "MODEL        3\n"
        + _pdb_line(1, "CA", "MET", "A", 5, moved["CA"], "C")
        + _pdb_line(2, "CB", "MET", "A", 5, moved["CB"], "C")
        + _pdb_line(3, "CG", "MET", "A", 5, moved["CG"], "C")
        + _pdb_line(4, "SD", "MET", "A", 5, moved["SD"], "S")
        + _pdb_line(5, "CE", "MET", "A", 5, moved["CE"], "C")
        + "ENDMDL\n"
        "MODEL        4\n"
        + _pdb_line(1, "CA", "MET", "A", 5, crystal["CA"], "C")
        + _pdb_line(2, "CB", "MET", "A", 5, crystal["CB"], "C")
        + _pdb_line(3, "CG", "MET", "A", 5, crystal["CG"], "C")
        + _pdb_line(4, "SD", "MET", "A", 5, crystal["SD"], "S")
        + _pdb_line(5, "CE", "MET", "A", 5, crystal["CE"], "C")
        + "ENDMDL\n"
    )
    models = parse_gnina_flex_pdb_models(gnina_pdb)
    assert len(models) == 2
    assert models[0].ordinal_index == 0
    assert models[0].raw_model_header == 3
    assert models[1].ordinal_index == 1
    assert models[1].raw_model_header == 4

    reinjected = reinject_gnina_flex_pdb_into_meeko_template(
        meeko_flex_pdbqt_text=template_pdbqt,
        gnina_flex_pdb_model_text=models[0].pdb_text,
    ).decode("utf-8")
    assert "BEGIN_RES MET A 5" in reinjected
    assert "BRANCH   1   2" in reinjected
    assert " SA" in reinjected
    assert f"{moved['CE'][0]:8.3f}{moved['CE'][1]:8.3f}{moved['CE'][2]:8.3f}" in reinjected

    # Missing atom must fail closed with 422.
    missing_ce_pdb = "\n".join(
        line for line in models[0].pdb_text.splitlines() if " CE " not in line
    ) + "\n"
    with pytest.raises(AnkoraDomainError) as exc_missing:
        reinject_gnina_flex_pdb_into_meeko_template(
            meeko_flex_pdbqt_text=template_pdbqt,
            gnina_flex_pdb_model_text=missing_ce_pdb,
        )
    assert exc_missing.value.code == "GNINA_FLEX_TEMPLATE_MISMATCH"
    assert exc_missing.value.status_code == 422


def test_materialize_coupled_receptor_preserves_ch_geometry_and_serial_invariance() -> None:
    """Synthetic MET A:5 rotated by chi1=120 deg, chi2=-75 deg: verify non-polar H transfer."""
    # Synthetic right-handed tetrahedral MET geometry (labelled synthetic).
    n_xyz = (-0.500, -1.350, 0.250)
    ca_xyz = (0.000, 0.000, 0.000)
    c_xyz = (-0.550, 0.500, -1.320)
    o_xyz = (-0.100, 1.550, -1.780)
    ha_xyz = (-0.350, 0.650, 0.780)
    cb_xyz = (1.530, 0.000, 0.000)
    cg_xyz = (2.040, 1.440, 0.000)
    sd_xyz = (3.850, 1.440, 0.000)
    ce_xyz = (4.200, 3.190, 0.250)

    # Non-polar hydrogens attached to CB, CG, CE (1.09 A bond lengths).
    hb2_xyz = (1.894, -0.514, 0.890)
    hb3_xyz = (1.894, -0.514, -0.890)
    hg2_xyz = (1.676, 1.954, 0.890)
    hg3_xyz = (1.676, 1.954, -0.890)
    he1_xyz = (5.280, 3.310, 0.250)
    he2_xyz = (3.780, 3.620, 1.158)
    he3_xyz = (3.780, 3.620, -0.658)

    crystal_all = {
        "N": (n_xyz, "N"),
        "CA": (ca_xyz, "C"),
        "C": (c_xyz, "C"),
        "O": (o_xyz, "O"),
        "HA": (ha_xyz, "H"),
        "CB": (cb_xyz, "C"),
        "CG": (cg_xyz, "C"),
        "SD": (sd_xyz, "S"),
        "CE": (ce_xyz, "C"),
        "HB2": (hb2_xyz, "H"),
        "HB3": (hb3_xyz, "H"),
        "HG2": (hg2_xyz, "H"),
        "HG3": (hg3_xyz, "H"),
        "HE1": (he1_xyz, "H"),
        "HE2": (he2_xyz, "H"),
        "HE3": (he3_xyz, "H"),
    }
    crystal_pdb = "".join(
        _pdb_line(idx, name, "MET", "A", 5, xyz, elem)
        for idx, (name, (xyz, elem)) in enumerate(crystal_all.items(), start=1)
    )

    # Apply exact chi1=+120 deg (around CA->CB) then chi2=-75 deg (around CB->CG) to side chain.
    def _move(pt: tuple[float, float, float], apply_chi2: bool) -> tuple[float, float, float]:
        p1 = _rotate_around_axis(pt, ca_xyz, cb_xyz, 120.0)
        if not apply_chi2:
            return p1
        cg1 = _rotate_around_axis(cg_xyz, ca_xyz, cb_xyz, 120.0)
        return _rotate_around_axis(p1, cb_xyz, cg1, -75.0)

    moved_heavy = {
        "CA": ca_xyz,
        "CB": cb_xyz,
        "CG": _move(cg_xyz, apply_chi2=False),
        "SD": _move(sd_xyz, apply_chi2=True),
        "CE": _move(ce_xyz, apply_chi2=True),
    }

    # Verify ADR-032 A6: AutoDock4 CPU (serials 16..20) vs AutoDock-GPU (serials 1..5)
    # yield bit-identical materialized coupled receptor PDBs.
    flex_ad4_cpu = _synthetic_met_flex_block(moved_heavy, start_serial=16)
    flex_ad4_gpu = _synthetic_met_flex_block(moved_heavy, start_serial=1)

    mat_cpu = materialize_coupled_receptor_pdb(
        protonated_pdb_text=crystal_pdb,
        pose_flex_sidechains_pdbqt=flex_ad4_cpu,
    )
    mat_gpu = materialize_coupled_receptor_pdb(
        protonated_pdb_text=crystal_pdb,
        pose_flex_sidechains_pdbqt=flex_ad4_gpu,
    )
    assert mat_cpu.pdb_text == mat_gpu.pdb_text
    assert mat_cpu.sha256 == mat_gpu.sha256
    assert mat_cpu.moved_atom_count == 5
    assert mat_cpu.repositioned_nonpolar_hydrogen_count == 7

    disp = mat_cpu.residue_displacements["A:5:MET"]
    assert disp.heavy_atom_count == 4  # CB, CG, SD, CE (CA excluded)
    assert disp.max_heavy_atom_displacement_angstrom > 3.0
    assert disp.repositioned_nonpolar_hydrogen_count == 7

    # Parse back materialized coordinates and verify exact physical invariants.
    parsed: dict[str, tuple[float, float, float]] = {}
    for line in mat_cpu.pdb_text.splitlines():
        if line.startswith("ATOM  "):
            name = line[12:16].strip()
            parsed[name] = (float(line[30:38]), float(line[38:46]), float(line[46:54]))

    # Backbone atoms stay strictly fixed.
    for bb in ("N", "CA", "C", "O", "HA"):
        assert _dist(parsed[bb], crystal_all[bb][0]) < 1e-6

    # Every transferred non-polar H keeps its exact C-H bond length (within PDB 0.003 A rounding)
    # and matches the exact analytical Rodrigues rotation!
    expected_h = {
        "HB2": ("CB", _move(hb2_xyz, apply_chi2=False)),
        "HB3": ("CB", _move(hb3_xyz, apply_chi2=False)),
        "HG2": ("CG", _move(hg2_xyz, apply_chi2=True)),
        "HG3": ("CG", _move(hg3_xyz, apply_chi2=True)),
        "HE1": ("CE", _move(he1_xyz, apply_chi2=True)),
        "HE2": ("CE", _move(he2_xyz, apply_chi2=True)),
        "HE3": ("CE", _move(he3_xyz, apply_chi2=True)),
    }
    for h_name, (parent, analytic_xyz) in expected_h.items():
        orig_len = _dist(crystal_all[h_name][0], crystal_all[parent][0])
        new_len = _dist(parsed[h_name], parsed[parent])
        assert abs(new_len - orig_len) < 0.005, (
            f"{h_name}-{parent} drifted: {new_len} vs {orig_len}"
        )
        assert _dist(parsed[h_name], analytic_xyz) < 0.01, (
            f"{h_name} diverged from exact rotation: {parsed[h_name]} vs {analytic_xyz}"
        )

    # Chirality / prochirality at CB is strictly preserved (proper rotation det=+1).
    orig_vol = _signed_tetra_volume(cb_xyz, ca_xyz, cg_xyz, hb2_xyz)
    new_vol = _signed_tetra_volume(parsed["CB"], parsed["CA"], parsed["CG"], parsed["HB2"])
    assert math.copysign(1.0, orig_vol) == math.copysign(1.0, new_vol)
    assert abs(new_vol - orig_vol) < 0.01


def test_materialize_coupled_receptor_rejects_backbone_ca_drift_and_missing_residue() -> None:
    crystal_pdb = (
        _pdb_line(1, "CA", "MET", "A", 5, (0.0, 0.0, 0.0), "C")
        + _pdb_line(2, "CB", "MET", "A", 5, (1.53, 0.0, 0.0), "C")
        + _pdb_line(3, "CG", "MET", "A", 5, (2.05, 1.44, 0.0), "C")
        + _pdb_line(4, "SD", "MET", "A", 5, (3.85, 1.44, 0.0), "S")
        + _pdb_line(5, "CE", "MET", "A", 5, (4.20, 3.18, 0.40), "C")
    )
    drifted_flex = _synthetic_met_flex_block(
        {
            "CA": (0.25, 0.0, 0.0),  # > 0.05 A CA drift!
            "CB": (1.78, 0.0, 0.0),
            "CG": (2.30, 1.44, 0.0),
            "SD": (4.10, 1.44, 0.0),
            "CE": (4.45, 3.18, 0.40),
        }
    )
    with pytest.raises(AnkoraDomainError) as exc_drift:
        materialize_coupled_receptor_pdb(
            protonated_pdb_text=crystal_pdb,
            pose_flex_sidechains_pdbqt=drifted_flex,
        )
    assert exc_drift.value.code == "POSE_COMPLEX_BACKBONE_DRIFT"
    assert exc_drift.value.status_code == 422

    wrong_res_flex = drifted_flex.replace("MET A   5", "MET A  99").replace("MET A 5", "MET A 99")
    with pytest.raises(AnkoraDomainError) as exc_missing:
        materialize_coupled_receptor_pdb(
            protonated_pdb_text=crystal_pdb,
            pose_flex_sidechains_pdbqt=wrong_res_flex,
        )
    assert exc_missing.value.code == "POSE_COMPLEX_FLEX_RESIDUE_MISSING"
    assert exc_missing.value.status_code == 422


def test_coupled_split_binds_directly_to_e8_pose_complex_identity(tmp_path: Path) -> None:
    """End-to-end E8 identity construction from coupled split hashes."""
    _ = tmp_path
    met_coords = {
        "CA": (0.0, 0.0, 0.0),
        "CB": (1.53, 0.0, 0.0),
        "CG": (2.05, 1.44, 0.0),
        "SD": (3.85, 1.44, 0.0),
        "CE": (4.20, 3.18, 0.40),
    }
    split = split_coupled_pdbqt_model(
        _synthetic_ligand_block() + _synthetic_met_flex_block(met_coords)
    )
    assert split.flex_sidechains_sha256 is not None
    identity = PoseComplexIdentity(
        mode=ReceptorFlexMode.SIDECHAIN_FLEX,
        receptor_rigid_sha256="a" * 64,
        pose_flex_sidechains_sha256=split.flex_sidechains_sha256,
        ligand_pose_sha256=split.ligand_sha256,
    )
    assert len(identity.complex_identity_sha256) == 64
