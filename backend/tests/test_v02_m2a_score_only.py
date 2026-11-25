"""Tests for M2a cross-engine `--score_only` adapters and PoseRescoringService.

All fixtures in this module are synthetic and explicitly labelled synthetic.
"""

from __future__ import annotations

import os
import subprocess
import sys
from hashlib import sha256
from importlib import import_module
from pathlib import Path
from typing import Any

import pytest

from ankora_backend.adapters.chemistry.flex_pose_complex import split_coupled_pdbqt_model
from ankora_backend.adapters.engines.autodock4 import (
    collect_autodock_atom_types,
    render_autogrid_gpf,
)
from ankora_backend.adapters.engines.autodock4_job import (
    parse_autodock4_epdb_dlg,
    render_autodock4_epdb_dpf,
)
from ankora_backend.adapters.engines.gnina import (
    GninaInstallation,
    build_gnina_score_only_arguments,
    parse_gnina_score_only_stdout,
)
from ankora_backend.adapters.engines.vina import VinaInstallation
from ankora_backend.adapters.engines.vina_v02 import (
    build_vina_score_only_arguments,
    parse_vina_score_only_output,
)
from ankora_backend.adapters.tools.discovery import discover_autogrid4
from ankora_backend.domain.errors import AnkoraDomainError
from ankora_backend.execution.cancellable_subprocess import CancellableToolExecution
from ankora_backend.schemas.binding_sites import BindingBox
from ankora_backend.schemas.receptors import ReceptorFlexMode, ReceptorFlexSpec, ResidueLocator
from ankora_backend.schemas.rescoring import (
    AutoDock4RescoreBackend,
    PoseRescoreContext,
    PoseRescoreRequest,
)
from ankora_backend.schemas.screening_benchmark import ScoreDirection
from ankora_backend.schemas.v02_contracts import (
    ObservationStatus,
    PoseComplexIdentity,
    ProtocolSpec,
    ScoringFamily,
    ScoringFunctionId,
    canonical_contract_sha256,
)
from ankora_backend.services import pose_rescoring as rescoring_module
from ankora_backend.services.pose_rescoring import PoseRescoringService

_SYNTHETIC_BOX = BindingBox(
    center_x=1.0,
    center_y=2.0,
    center_z=3.0,
    size_x=18.0,
    size_y=18.0,
    size_z=18.0,
)
_SYNTHETIC_RIGID_PDBQT = (
    b"ATOM      1  CA  GLY A   1       0.000   0.000   0.000  0.00  0.00     0.000 C \n"
)
_SYNTHETIC_FLEX_PDBQT = (
    b"BEGIN_RES MET A   5\n"
    b"ROOT\n"
    b"ATOM      1  CA  MET A   5       1.000   1.000   1.000  0.00  0.00     0.000 C \n"
    b"ENDROOT\n"
    b"BRANCH   1   2\n"
    b"ATOM      2  SD  MET A   5       2.000   1.000   1.000  0.00  0.00    -0.100 SA\n"
    b"ENDBRANCH   1   2\n"
    b"END_RES MET A   5\n"
)
_SYNTHETIC_LIGAND_POSE_PDBQT = (
    b"MODEL 1\n"
    b"REMARK VINA RESULT:   -6.500      0.000      0.000\n"
    b"REMARK minimizedAffinity -6.50\n"
    b"REMARK CNNscore 0.85\n"
    b"REMARK CNNaffinity 6.10\n"
    b"ROOT\n"
    b"ATOM      1  C1  LIG A   1       1.000   2.000   3.000  0.00  0.00     0.000 C \n"
    b"ATOM      2  O1  LIG A   1       2.200   2.000   3.000  0.00  0.00    -0.300 OA\n"
    b"ENDROOT\n"
    b"TORSDOF 0\n"
    b"ENDMDL\n"
)


def _sha(data: bytes) -> str:
    return sha256(data).hexdigest()


def test_frozen_v01_vina_parser_bytes_remain_untouched() -> None:
    vina_path = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "ankora_backend"
        / "adapters"
        / "engines"
        / "vina.py"
    )
    raw = vina_path.read_bytes()
    assert len(raw) == 7120
    assert _sha(raw) == "e13e32f5b6c401966debe80fe0049f4ae87f1cc3c8eb31f4566c57c1acc50993"


def test_vina_score_only_arguments_and_ad4_stdout_parsing(tmp_path: Path) -> None:
    rec = tmp_path / "rec.pdbqt"
    lig = tmp_path / "lig.pdbqt"
    flx = tmp_path / "flex.pdbqt"
    maps = tmp_path / "split_rigid"

    vina_args = build_vina_score_only_arguments(
        ligand_path=lig,
        scoring="vinardo",
        receptor_path=rec,
        box=_SYNTHETIC_BOX,
        flex_receptor_path=flx,
        cpu_threads=2,
    )
    assert "--score_only" in vina_args
    assert "--scoring" in vina_args and vina_args[vina_args.index("--scoring") + 1] == "vinardo"
    assert "--flex" in vina_args and vina_args[vina_args.index("--flex") + 1] == str(flx)

    ad4_args = build_vina_score_only_arguments(
        ligand_path=lig,
        scoring="ad4",
        maps_prefix=maps,
        flex_receptor_path=flx,
    )
    assert "--maps" in ad4_args and ad4_args[ad4_args.index("--maps") + 1] == str(maps)
    assert "--receptor" not in ad4_args
    assert "--scoring" in ad4_args and ad4_args[ad4_args.index("--scoring") + 1] == "ad4"

    with pytest.raises(AnkoraDomainError) as missing_maps:
        build_vina_score_only_arguments(ligand_path=lig, scoring="ad4")
    assert missing_maps.value.code == "VINA_SCORE_ONLY_MAPS_REQUIRED"

    # Empirically captured Vina 1.2.7 `--scoring ad4 --maps --score_only` stdout with `[=(2)]`
    ad4_stdout = (
        "Estimated Free Energy of Binding   : -6.123 (kcal/mol) [=(1)+(2)+(3)-(4)]\n"
        "(1) Final Intermolecular Energy    : -6.720 (kcal/mol)\n"
        "(2) Final Total Internal Energy    : -0.249 (kcal/mol)\n"
        "(3) Torsional Free Energy          : 0.597 (kcal/mol)\n"
        "(4) Unbound System's Energy [=(2)] : -0.249 (kcal/mol)\n"
    )
    parsed = parse_vina_score_only_output(stdout=ad4_stdout, scoring="ad4", used_flex=True)
    assert parsed.energy.estimated_free_energy_kcal_mol == pytest.approx(-6.123)
    assert parsed.energy.unbound_system_energy_kcal_mol == pytest.approx(-0.249)
    assert parsed.used_flex is True
    assert parsed.unbound_reference_shifted is True


def test_autodock4_epdb_dpf_and_cross_os_scientific_notation_parsing() -> None:
    dpf = render_autodock4_epdb_dpf(
        ligand_filename="ligand.pdbqt",
        map_prefix="split_rigid",
        ligand_atom_types=("C", "OA", "SA"),
        about=(1.0, 2.0, 3.0),
        flexres_filename="pose_flex.pdbqt",
    )
    assert "flexres pose_flex.pdbqt\n" in dpf
    assert dpf.rstrip().endswith("epdb")

    # Windows 3-digit exponent (+5.30e+005) and flexres Moving Ligand-Moving Receptor section
    win_dlg = (
        b"epdb: USER    Estimated Free Energy of Binding    =  +5.30e+005 kcal/mol\n"
        b"epdb: USER    (1) Final Intermolecular Energy     =  +5.30e+005 kcal/mol\n"
        b"epdb: USER        Moving Ligand-Moving Receptor   =  +9.60e+003 kcal/mol\n"
        b"epdb: USER    (2) Final Total Internal Energy     =   -0.25 kcal/mol\n"
        b"epdb: USER    (3) Torsional Free Energy           =   +0.60 kcal/mol\n"
        b"epdb: USER    (4) Unbound System's Energy         =   +0.00 kcal/mol\n"
        b"autodock4: Successful Completion\n"
    )
    parsed_win = parse_autodock4_epdb_dlg(win_dlg, expect_flex=True)
    assert parsed_win.estimated_free_energy_kcal_mol == pytest.approx(5.30e5)
    assert parsed_win.intermolecular_kcal_mol == pytest.approx(5.30e5)
    assert parsed_win.total_internal_kcal_mol == pytest.approx(-0.25)
    assert parsed_win.torsional_free_energy_kcal_mol == pytest.approx(0.60)
    assert parsed_win.unbound_system_energy_kcal_mol == pytest.approx(0.0)
    assert parsed_win.used_flex is True

    # Missing Moving Ligand-Moving Receptor block when flex was expected fails closed
    rigid_only_dlg = (
        b"epdb: USER    Estimated Free Energy of Binding    =  -7.42 kcal/mol\n"
        b"autodock4: Successful Completion\n"
    )
    with pytest.raises(AnkoraDomainError) as missing_flex:
        parse_autodock4_epdb_dlg(rigid_only_dlg, expect_flex=True)
    assert missing_flex.value.code == "AUTODOCK4_OUTPUT_INVALID"


def test_gnina_score_only_arguments_and_stdout_parsing(tmp_path: Path) -> None:
    rec = tmp_path / "rec.pdbqt"
    lig = tmp_path / "lig.pdbqt"
    flx = tmp_path / "flex.pdbqt"
    args = build_gnina_score_only_arguments(
        receptor_path=rec,
        ligand_path=lig,
        compute="cpu",
        cpu_threads=2,
        cnn_scoring="rescore",
        cnn_model="dense_1_3",
        flex_receptor_path=flx,
    )
    assert "--score_only" in args
    assert "--no_gpu" in args
    assert "--flex" in args and args[args.index("--flex") + 1] == str(flx)
    assert "--out" not in args

    stdout = (
        "Affinity: -7.25000 (kcal/mol)\n"
        "CNNscore: 0.80000\n"
        "CNNaffinity: 6.50000\n"
        "CNNvariance: 0.12500\n"
        "Intramolecular energy: -0.41000\n"
    )
    parsed = parse_gnina_score_only_stdout(stdout, used_flex=True, require_cnn=True)
    assert parsed.minimized_affinity_kcal_mol == pytest.approx(-7.25)
    assert parsed.cnn_score == pytest.approx(0.80)
    assert parsed.cnn_affinity == pytest.approx(6.50)
    assert parsed.cnn_vs == pytest.approx(5.20)
    assert parsed.cnn_affinity_variance == pytest.approx(0.125)
    assert parsed.intramolecular_energy_kcal_mol == pytest.approx(-0.41)
    assert parsed.used_flex is True


def test_pose_rescoring_enforces_e4_context_and_e7_map_binding_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _forbid(*_args: object, **_kwargs: object) -> Any:
        raise AssertionError("No scientific executable may launch on E4/E7 mismatch")

    monkeypatch.setattr(rescoring_module, "execute_vina_score_only", _forbid)
    monkeypatch.setattr(rescoring_module, "execute_autodock4_cancellable", _forbid)
    monkeypatch.setattr(rescoring_module, "execute_gnina_score_only", _forbid)

    rigid_sha = _sha(_SYNTHETIC_RIGID_PDBQT)
    flex_sha = _sha(_SYNTHETIC_FLEX_PDBQT)
    lig_sha = _sha(_SYNTHETIC_LIGAND_POSE_PDBQT)
    box_sha = canonical_contract_sha256(_SYNTHETIC_BOX)
    flex_res = (ResidueLocator(chain_id="A", sequence_number=5, residue_name="MET"),)

    spec = ReceptorFlexSpec(
        mode=ReceptorFlexMode.SIDECHAIN_FLEX,
        receptor_rigid_sha256=rigid_sha,
        receptor_flex_sha256=flex_sha,
        flex_residues=flex_res,
    )
    pose_complex = PoseComplexIdentity(
        mode=ReceptorFlexMode.SIDECHAIN_FLEX,
        receptor_rigid_sha256=rigid_sha,
        pose_flex_sidechains_sha256=flex_sha,
        ligand_pose_sha256=lig_sha,
    )
    service = PoseRescoringService()

    # E4: corrupted ligand bytes fail closed
    ctx = PoseRescoreContext(
        receptor_flex_spec=spec,
        binding_box=_SYNTHETIC_BOX,
        binding_box_sha256=box_sha,
    )
    req = PoseRescoreRequest(
        parent_compound_id="SYNTH_PARENT_1",
        parent_state_id="SYNTH_STATE_1",
        pose_complex=pose_complex,
        scoring_functions=(ScoringFunctionId.VINA,),
    )
    with pytest.raises(AnkoraDomainError) as bad_bytes:
        service.rescore_pose(
            request=req,
            context=ctx,
            receptor_rigid_pdbqt=_SYNTHETIC_RIGID_PDBQT,
            ligand_pose_pdbqt=_SYNTHETIC_LIGAND_POSE_PDBQT + b"REMARK tampered\n",
            pose_flex_sidechains_pdbqt=_SYNTHETIC_FLEX_PDBQT,
        )
    assert bad_bytes.value.code == "CONSENSUS_SHARED_CONTEXT_MISMATCH"

    # E7: missing SA flex atom type in AutoGrid maps fails closed BEFORE execution
    maps_dir = tmp_path / "maps"
    maps_dir.mkdir()
    for suffix in ("maps.fld", "e.map", "d.map", "C.map", "OA.map"):
        (maps_dir / f"rec.{suffix}").write_text("synthetic map\n", encoding="utf-8")

    bad_map_ctx = PoseRescoreContext(
        receptor_flex_spec=spec,
        binding_box=_SYNTHETIC_BOX,
        binding_box_sha256=box_sha,
        autogrid_map_set_sha256="a" * 64,
        autogrid_map_prefix="rec",
        autogrid_map_receptor_sha256=rigid_sha,
        autogrid_map_flex_residues=flex_res,
        autogrid_map_flex_atom_types=("C",),  # Missing SA!
        autogrid_map_affinity_atom_types=("C", "OA"),
        expected_flex_atom_types=("C", "SA"),
    )
    ad4_req = PoseRescoreRequest(
        parent_compound_id="SYNTH_PARENT_1",
        parent_state_id="SYNTH_STATE_1",
        pose_complex=pose_complex,
        scoring_functions=(ScoringFunctionId.AUTODOCK4,),
    )
    with pytest.raises(AnkoraDomainError) as e7_err:
        service.rescore_pose(
            request=ad4_req,
            context=bad_map_ctx,
            receptor_rigid_pdbqt=_SYNTHETIC_RIGID_PDBQT,
            ligand_pose_pdbqt=_SYNTHETIC_LIGAND_POSE_PDBQT,
            pose_flex_sidechains_pdbqt=_SYNTHETIC_FLEX_PDBQT,
            autogrid_maps_dir=maps_dir,
        )
    assert e7_err.value.code == "AUTOGRID_FLEXRES_MAP_MISMATCH"


def test_pose_rescoring_batches_gnina_metrics_and_strips_staged_remarks_without_mutating_parent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rigid_sha = _sha(_SYNTHETIC_RIGID_PDBQT)
    lig_sha = _sha(_SYNTHETIC_LIGAND_POSE_PDBQT)
    box_sha = canonical_contract_sha256(_SYNTHETIC_BOX)
    spec = ReceptorFlexSpec(mode=ReceptorFlexMode.RIGID, receptor_rigid_sha256=rigid_sha)
    pose_complex = PoseComplexIdentity(
        mode=ReceptorFlexMode.RIGID,
        receptor_rigid_sha256=rigid_sha,
        ligand_pose_sha256=lig_sha,
    )
    ctx = PoseRescoreContext(
        receptor_flex_spec=spec,
        binding_box=_SYNTHETIC_BOX,
        binding_box_sha256=box_sha,
    )

    gnina_calls = 0
    staged_ligand_seen: list[bytes] = []

    monkeypatch.setattr(
        rescoring_module,
        "probe_vina",
        lambda: VinaInstallation(executable="/synthetic/vina", version="1.2.7"),
    )
    monkeypatch.setattr(
        rescoring_module,
        "probe_gnina",
        lambda: GninaInstallation(
            executable="/synthetic/gnina",
            version="1.3.3",
            sha256="b" * 64,
            architecture="x86_64",
        ),
    )

    def _fake_vina(**kwargs: Any) -> CancellableToolExecution:
        staged_ligand_seen.append(kwargs["ligand_path"].read_bytes())
        scoring = kwargs["scoring"]
        energy = -6.10 if scoring == "vina" else -6.85
        return CancellableToolExecution(
            command=["/synthetic/vina", "--score_only", "--scoring", scoring],
            exit_code=0,
            stdout=(
                f"Estimated Free Energy of Binding   : {energy:.3f} (kcal/mol)\n"
                f"(1) Final Intermolecular Energy    : {energy:.3f} (kcal/mol)\n"
                "(4) Unbound System's Energy        : -0.100 (kcal/mol)\n"
            ),
            stderr="",
            timed_out=False,
            canceled=False,
        )

    def _fake_gnina(**kwargs: Any) -> CancellableToolExecution:
        nonlocal gnina_calls
        gnina_calls += 1
        staged_ligand_seen.append(kwargs["ligand_path"].read_bytes())
        return CancellableToolExecution(
            command=["/synthetic/gnina", "--score_only"],
            exit_code=0,
            stdout=(
                "Affinity: -6.42000 (kcal/mol)\n"
                "CNNscore: 0.75000\n"
                "CNNaffinity: 5.60000\n"
                "Intramolecular energy: -0.22000\n"
            ),
            stderr="",
            timed_out=False,
            canceled=False,
        )

    monkeypatch.setattr(rescoring_module, "execute_vina_score_only", _fake_vina)
    monkeypatch.setattr(rescoring_module, "execute_gnina_score_only", _fake_gnina)

    req = PoseRescoreRequest(
        parent_compound_id="SYNTH_PARENT_1",
        parent_state_id="SYNTH_STATE_1",
        pose_complex=pose_complex,
        scoring_functions=(
            ScoringFunctionId.VINA,
            ScoringFunctionId.VINARDO,
            ScoringFunctionId.GNINA_CNN_SCORE,
            ScoringFunctionId.GNINA_CNN_AFFINITY,
            ScoringFunctionId.GNINA_CNN_VS,
            ScoringFunctionId.GNINA_MINIMIZED_AFFINITY,
        ),
    )
    original_copy = bytes(_SYNTHETIC_LIGAND_POSE_PDBQT)
    result = PoseRescoringService().rescore_pose(
        request=req,
        context=ctx,
        receptor_rigid_pdbqt=_SYNTHETIC_RIGID_PDBQT,
        ligand_pose_pdbqt=original_copy,
    )

    assert gnina_calls == 1, "All 4 GNINA metrics must be emitted from a single GNINA invocation"
    assert len(result.observations) == 6
    assert len(result.evidence) == 3  # vina + vinardo + 1 shared gnina invocation
    assert result.mutated_original_pose is False
    assert _sha(original_copy) == lig_sha
    for staged in staged_ligand_seen:
        assert b"MODEL" not in staged
        assert b"REMARK VINA RESULT" not in staged
        assert b"REMARK CNNscore" not in staged

    by_fn = {obs.scoring_function: obs for obs in result.observations}
    assert by_fn[ScoringFunctionId.VINA].raw_score == pytest.approx(-6.10)
    assert by_fn[ScoringFunctionId.VINA].direction is ScoreDirection.LOWER_IS_BETTER
    assert by_fn[ScoringFunctionId.VINARDO].raw_score == pytest.approx(-6.85)
    assert by_fn[ScoringFunctionId.GNINA_CNN_SCORE].raw_score == pytest.approx(0.75)
    assert by_fn[ScoringFunctionId.GNINA_CNN_SCORE].direction is ScoreDirection.HIGHER_IS_BETTER
    assert by_fn[ScoringFunctionId.GNINA_CNN_SCORE].scoring_family is ScoringFamily.GNINA_NEURAL
    assert by_fn[ScoringFunctionId.GNINA_CNN_AFFINITY].raw_score == pytest.approx(5.60)
    assert by_fn[ScoringFunctionId.GNINA_CNN_VS].raw_score == pytest.approx(4.20)
    assert by_fn[ScoringFunctionId.GNINA_MINIMIZED_AFFINITY].raw_score == pytest.approx(-6.42)
    assert (
        by_fn[ScoringFunctionId.GNINA_MINIMIZED_AFFINITY].direction
        is ScoreDirection.LOWER_IS_BETTER
    )


def test_live_score_only_rigid_and_flex_cross_engine(tmp_path: Path) -> None:
    """Live Dual-OS integration test across Vina, Vinardo, AD4 epdb, Vina-AD4, and Linux GNINA.

    Uses explicitly synthetic GARYMP peptide and synthetic amide ligand fixtures.
    """
    Chem: Any = import_module("rdkit.Chem")
    AllChem: Any = import_module("rdkit.Chem.AllChem")
    Geometry: Any = import_module("rdkit.Geometry")

    ag_tool = discover_autogrid4(os.getenv("ANKORA_AUTOGRID4_PATH"))
    if not ag_tool.available or ag_tool.path is None:
        pytest.skip("AutoGrid4 executable unavailable on host")

    rec = Chem.AddHs(Chem.MolFromSequence("GARYMP"))
    params = AllChem.ETKDGv3()
    params.randomSeed = 20261119
    assert AllChem.EmbedMolecule(rec, params) == 0
    AllChem.MMFFOptimizeMolecule(rec)
    rec_pdb = tmp_path / "synthetic_garymp.pdb"
    Chem.MolToPDBFile(rec, str(rec_pdb))
    rec_pqr = tmp_path / "synthetic_garymp.pqr"
    pdb2pqr_exe = (
        str(Path(sys.executable).parent / ("pdb2pqr.exe" if os.name == "nt" else "pdb2pqr"))
    )
    mk_rec_exe = str(
        Path(sys.executable).parent
        / ("mk_prepare_receptor.exe" if os.name == "nt" else "mk_prepare_receptor.py")
    )
    mk_lig_exe = str(
        Path(sys.executable).parent
        / ("mk_prepare_ligand.exe" if os.name == "nt" else "mk_prepare_ligand.py")
    )
    subprocess.run(
        [pdb2pqr_exe, "--ff=PARSE", "--keep-chain", "--with-ph=7.4", str(rec_pdb), str(rec_pqr)],
        check=True,
        capture_output=True,
        text=True,
    )
    full_rigid_path = tmp_path / "full_rigid.pdbqt"
    subprocess.run(
        [
            mk_rec_exe,
            "--read_pqr",
            str(rec_pqr),
            "--charge_model",
            "read",
            "-p",
            str(full_rigid_path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    split_base = tmp_path / "split"
    subprocess.run(
        [
            mk_rec_exe,
            "--read_pqr",
            str(rec_pqr),
            "--charge_model",
            "read",
            "-f",
            "A:4,A:5",
            "-o",
            str(split_base),
            "-p",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    split_rigid_bytes = (tmp_path / "split_rigid.pdbqt").read_bytes()
    split_flex_bytes = (tmp_path / "split_flex.pdbqt").read_bytes()
    full_rigid_bytes = full_rigid_path.read_bytes()

    lig = Chem.AddHs(Chem.MolFromSmiles("CC(=O)NCc1ccccc1"))
    assert AllChem.EmbedMolecule(lig, params) == 0
    AllChem.MMFFOptimizeMolecule(lig)
    conf_r = rec.GetConformer()
    cx = sum(conf_r.GetAtomPosition(i).x for i in range(rec.GetNumAtoms())) / rec.GetNumAtoms()
    cy = sum(conf_r.GetAtomPosition(i).y for i in range(rec.GetNumAtoms())) / rec.GetNumAtoms()
    cz = sum(conf_r.GetAtomPosition(i).z for i in range(rec.GetNumAtoms())) / rec.GetNumAtoms()
    conf_l = lig.GetConformer()
    lx = sum(conf_l.GetAtomPosition(i).x for i in range(lig.GetNumAtoms())) / lig.GetNumAtoms()
    ly = sum(conf_l.GetAtomPosition(i).y for i in range(lig.GetNumAtoms())) / lig.GetNumAtoms()
    lz = sum(conf_l.GetAtomPosition(i).z for i in range(lig.GetNumAtoms())) / lig.GetNumAtoms()
    for i in range(lig.GetNumAtoms()):
        pt = conf_l.GetAtomPosition(i)
        conf_l.SetAtomPosition(i, Geometry.Point3D(pt.x - lx + cx, pt.y - ly + cy, pt.z - lz + cz))
    lig_sdf = tmp_path / "synthetic_lig.sdf"
    writer = Chem.SDWriter(str(lig_sdf))
    writer.write(lig)
    writer.close()
    lig_pdbqt = tmp_path / "synthetic_lig.pdbqt"
    subprocess.run(
        [mk_lig_exe, "-i", str(lig_sdf), "-o", str(lig_pdbqt), "--charge_model", "gasteiger"],
        check=True,
        capture_output=True,
        text=True,
    )
    lig_bytes = lig_pdbqt.read_bytes()

    box = BindingBox(
        center_x=round(cx, 3),
        center_y=round(cy, 3),
        center_z=round(cz, 3),
        size_x=22.0,
        size_y=22.0,
        size_z=22.0,
    )
    box_sha = canonical_contract_sha256(box)

    # Generate real AutoGrid4 union maps on split_rigid.pdbqt
    maps_dir = tmp_path / "maps_flex"
    maps_dir.mkdir()
    (maps_dir / "split_rigid.pdbqt").write_bytes(split_rigid_bytes)
    rec_types = collect_autodock_atom_types([split_rigid_bytes.decode("utf-8")])
    flex_types = collect_autodock_atom_types([split_flex_bytes.decode("utf-8")])
    union_types = collect_autodock_atom_types(
        [lig_bytes.decode("utf-8"), split_flex_bytes.decode("utf-8")]
    )
    gpf_text, _ = render_autogrid_gpf(
        box,
        receptor_filename="split_rigid.pdbqt",
        receptor_atom_types=rec_types,
        ligand_atom_types=union_types,
        map_prefix="split_rigid",
    )
    gpf_path = maps_dir / "split_rigid.gpf"
    gpf_path.write_text(gpf_text, encoding="utf-8")
    subprocess.run(
        [ag_tool.path, "-p", str(gpf_path), "-l", str(maps_dir / "split_rigid.glg")],
        cwd=maps_dir,
        check=True,
        capture_output=True,
        text=True,
    )

    # Verify split helper compatibility
    assert split_coupled_pdbqt_model(lig_bytes.decode("utf-8")).flex_sidechains_pdbqt is None

    flex_locators = (
        ResidueLocator(chain_id="A", sequence_number=4, residue_name="TYR"),
        ResidueLocator(chain_id="A", sequence_number=5, residue_name="MET"),
    )
    flex_spec = ReceptorFlexSpec(
        mode=ReceptorFlexMode.SIDECHAIN_FLEX,
        receptor_rigid_sha256=_sha(split_rigid_bytes),
        receptor_flex_sha256=_sha(split_flex_bytes),
        flex_residues=flex_locators,
    )
    flex_pose = PoseComplexIdentity(
        mode=ReceptorFlexMode.SIDECHAIN_FLEX,
        receptor_rigid_sha256=_sha(split_rigid_bytes),
        pose_flex_sidechains_sha256=_sha(split_flex_bytes),
        ligand_pose_sha256=_sha(lig_bytes),
    )
    map_set_sha = _sha((maps_dir / "split_rigid.maps.fld").read_bytes())
    flex_ctx = PoseRescoreContext(
        receptor_flex_spec=flex_spec,
        binding_box=box,
        binding_box_sha256=box_sha,
        autogrid_map_set_sha256=map_set_sha,
        autogrid_map_prefix="split_rigid",
        autogrid_map_receptor_sha256=_sha(split_rigid_bytes),
        autogrid_map_flex_residues=flex_locators,
        autogrid_map_flex_atom_types=flex_types,
        autogrid_map_affinity_atom_types=union_types,
        expected_flex_atom_types=flex_types,
    )

    gnina_available = sys.platform.startswith("linux") and bool(os.getenv("ANKORA_GNINA_PATH"))
    scoring_fns: list[ScoringFunctionId] = [
        ScoringFunctionId.VINA,
        ScoringFunctionId.VINARDO,
        ScoringFunctionId.AUTODOCK4,
    ]
    if gnina_available:
        scoring_fns.extend(
            [
                ScoringFunctionId.GNINA_CNN_SCORE,
                ScoringFunctionId.GNINA_CNN_AFFINITY,
                ScoringFunctionId.GNINA_CNN_VS,
                ScoringFunctionId.GNINA_MINIMIZED_AFFINITY,
            ]
        )

    service = PoseRescoringService()
    flex_result = service.rescore_pose(
        request=PoseRescoreRequest(
            parent_compound_id="SYNTH_M2A_AMIDE",
            parent_state_id="SYNTH_M2A_AMIDE_S1",
            pose_complex=flex_pose,
            scoring_functions=tuple(scoring_fns),
            autodock4_backend=AutoDock4RescoreBackend.AUTODOCK4_EPDB,
        ),
        context=flex_ctx,
        receptor_rigid_pdbqt=split_rigid_bytes,
        ligand_pose_pdbqt=lig_bytes,
        pose_flex_sidechains_pdbqt=split_flex_bytes,
        autogrid_maps_dir=maps_dir,
    )
    assert all(obs.status is ObservationStatus.SCORED for obs in flex_result.observations)
    vina_evs = [
        ev
        for ev in flex_result.evidence
        if ScoringFunctionId.VINA in ev.scoring_functions
        or ScoringFunctionId.VINARDO in ev.scoring_functions
    ]
    assert len(vina_evs) == 2
    assert all(ev.unbound_reference_shifted is True for ev in vina_evs)
    ad4_ev = next(
        ev for ev in flex_result.evidence if ScoringFunctionId.AUTODOCK4 in ev.scoring_functions
    )
    assert ad4_ev.tool_name == "AutoDock"
    assert ad4_ev.unbound_reference_shifted is False

    # Also test Vina `--scoring ad4 --maps` backend explicitly on the same flex maps
    vina_ad4_result = service.rescore_pose(
        request=PoseRescoreRequest(
            parent_compound_id="SYNTH_M2A_AMIDE",
            parent_state_id="SYNTH_M2A_AMIDE_S1",
            pose_complex=flex_pose,
            scoring_functions=(ScoringFunctionId.AUTODOCK4,),
            autodock4_backend=AutoDock4RescoreBackend.VINA_AD4_MAPS,
        ),
        context=flex_ctx,
        receptor_rigid_pdbqt=split_rigid_bytes,
        ligand_pose_pdbqt=lig_bytes,
        pose_flex_sidechains_pdbqt=split_flex_bytes,
        autogrid_maps_dir=maps_dir,
    )
    assert vina_ad4_result.observations[0].status is ObservationStatus.SCORED
    assert vina_ad4_result.evidence[0].tool_name == "AutoDock Vina (ad4 maps)"
    assert vina_ad4_result.evidence[0].unbound_reference_shifted is True

    # Rigid mode must record unbound_reference_shifted=False
    rigid_spec = ReceptorFlexSpec(
        mode=ReceptorFlexMode.RIGID,
        receptor_rigid_sha256=_sha(full_rigid_bytes),
    )
    rigid_pose = PoseComplexIdentity(
        mode=ReceptorFlexMode.RIGID,
        receptor_rigid_sha256=_sha(full_rigid_bytes),
        ligand_pose_sha256=_sha(lig_bytes),
    )
    rigid_ctx = PoseRescoreContext(
        receptor_flex_spec=rigid_spec,
        binding_box=box,
        binding_box_sha256=box_sha,
    )
    rigid_proto = ProtocolSpec(
        engine="vina",
        scoring_function=ScoringFunctionId.VINARDO,
        receptor_flexibility=rigid_spec,
        binding_box_sha256=box_sha,
    )
    rigid_result = service.rescore_pose(
        request=PoseRescoreRequest(
            parent_compound_id="SYNTH_M2A_AMIDE",
            parent_state_id="SYNTH_M2A_AMIDE_S1",
            pose_complex=rigid_pose,
            scoring_functions=(ScoringFunctionId.VINARDO,),
        ),
        context=rigid_ctx,
        receptor_rigid_pdbqt=full_rigid_bytes,
        ligand_pose_pdbqt=lig_bytes,
        protocol_spec_by_function={ScoringFunctionId.VINARDO: rigid_proto},
    )
    assert rigid_result.observations[0].status is ObservationStatus.SCORED
    assert (
        rigid_result.observations[0].protocol_identity_sha256
        == rigid_proto.protocol_identity_sha256
    )
    assert rigid_result.evidence[0].unbound_reference_shifted is False


def test_strip_pose_envelope_removes_autodock_dlg_user_and_ter_tags_on_staging() -> None:
    """Synthetic AutoDock4/AutoDock-GPU DLG pose tags (USER/NEWDPF/TER) must not break Vina."""
    raw = (
        b"MODEL        1\n"
        b"USER    Run = 1\n"
        b"USER    Estimated Free Energy of Binding = -7.50 kcal/mol\n"
        b"NEWDPF move ligand.pdbqt\n"
        b"REMARK VINA RESULT:   -7.1   0.000   0.000\n"
        b"REMARK SMILES CCO\n"
        b"ROOT\n"
        b"ATOM      1  C1  UNL     1       1.000   2.000   3.000  1.00  0.00     0.000 C \n"
        b"ENDROOT\n"
        b"TORSDOF 0\n"
        b"TER\n"
        b"ENDMDL\n"
    )
    staged = rescoring_module._strip_pose_envelope_for_staging(raw)
    assert b"MODEL" not in staged
    assert b"ENDMDL" not in staged
    assert b"USER" not in staged
    assert b"NEWDPF" not in staged
    assert b"\nTER\n" not in staged
    assert b"REMARK VINA RESULT" not in staged
    assert b"REMARK SMILES CCO\n" in staged
    assert b"ATOM      1  C1" in staged
    assert b"TORSDOF 0\n" in staged


def test_autodock4_epdb_bound_unbound_correction_preserves_raw_terms() -> None:
    """AutoDock4 4.2.6 epdb hardcodes unbound=0.00; bound_unbound_free_energy uses (1)+(3)."""
    zwitterion_dlg = (
        b"epdb: USER    Estimated Free Energy of Binding    =   -5.61 kcal/mol\n"
        b"epdb: USER    (1) Final Intermolecular Energy     =   -4.33 kcal/mol\n"
        b"epdb: USER    (2) Final Total Internal Energy     =   -2.47 kcal/mol\n"
        b"epdb: USER    (3) Torsional Free Energy           =   +1.19 kcal/mol\n"
        b"epdb: USER    (4) Unbound System's Energy         =   +0.00 kcal/mol\n"
        b"autodock4: Successful Completion\n"
    )
    parsed = parse_autodock4_epdb_dlg(zwitterion_dlg, expect_flex=False)
    # Raw tool output is preserved verbatim
    assert parsed.estimated_free_energy_kcal_mol == pytest.approx(-5.61)
    assert parsed.total_internal_kcal_mol == pytest.approx(-2.47)
    assert parsed.unbound_system_energy_kcal_mol == pytest.approx(0.0)
    # Canonical AutoDock4.2 `unbound_model bound` binding free energy = (1) + (3)
    assert parsed.bound_unbound_free_energy_kcal_mol == pytest.approx(-3.14)
