"""Pure parser coverage using SYNTHETIC_GATE0 records with no scientific results."""

from __future__ import annotations

import importlib.util
import math
import sys
from argparse import Namespace
from pathlib import Path, PureWindowsPath
from types import SimpleNamespace

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "probe_m1_flexibility_capabilities.py"
SPEC = importlib.util.spec_from_file_location("probe_m1_flexibility_capabilities", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
probe = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = probe
SPEC.loader.exec_module(probe)


def atom(name: str, residue: str, number: int, x: float) -> str:
    return (
        f"ATOM      1 {name:>4} {residue} A{number:4d}    "
        f"{x:8.3f}{0:8.3f}{0:8.3f}  1.00  0.00     0.000 C"
    )


def model(label: int, *lines: str) -> str:
    return "\n".join((f"MODEL {label}", *lines, "ENDMDL", ""))


def test_dlg_preserves_flex_order_and_detects_movement() -> None:
    original = atom("CB", "TYR", 4, 0.0)
    pose = model(
        1, "REMARK SYNTHETIC_GATE0_DLG", "ROOT", atom("C", "UNL", 1, 0.0),
        "ENDROOT", "TORSDOF 0", "BEGIN_RES TYR A 4", "ROOT",
        atom("CB", "TYR", 4, 1.0), "ENDROOT", "END_RES TYR A 4",
    )
    dlg = "\n".join(f"DOCKED: {line}" for line in pose.splitlines())
    summary = probe.summarize_dlg(dlg, probe.parse_atoms([original]))["docked"]
    parsed = summary["models"][0]
    assert summary["model_count"] == 1
    assert parsed["ordered_records"].index("TORSDOF 0") < parsed["ordered_records"].index(
        "BEGIN_RES TYR A 4"
    )
    assert parsed["ligand_root_through_torsdof"]
    assert parsed["balanced_flex_blocks"]
    assert parsed["ligand_atom_count"] == parsed["flex_atom_count"] == 1
    assert parsed["flex_displacement"]["moved_atoms"] == ["A:4:TYR:CB"]


def test_gnina_duplicate_flex_labels_use_file_order_with_complete_atom_groups() -> None:
    tyr = atom("CB", "TYR", 4, 0.0)
    met = atom("CB", "MET", 5, 0.0)
    ligand = model(1, "REMARK SYNTHETIC_GATE0_LIG") + model(2, "REMARK SYNTHETIC_GATE0_LIG")
    flex = model(3, tyr) + model(3, met) + model(4, tyr) + model(4, met)
    reference = probe.parse_atoms([tyr, met])
    models, selection = probe.gnina_first_pose_flex(ligand, flex, reference)
    assert selection == "file_order_candidate"
    assert [entry.label for entry in models] == ["3", "3"]
    summary = probe.summarize_pdbqt(flex, reference=reference, flex_file=True)
    assert summary["model_count"] == 4
    first = summary["models"][0]
    assert first["residue_markers"] == []
    assert first["flex_displacement"]["moved"] is None
    assert first["flex_displacement_by_residue"]["A:4:TYR"]["moved"] is False

    incomplete = model(3, tyr) + model(4, tyr) + model(4, met)
    rejected, reason = probe.gnina_first_pose_flex(ligand, incomplete, reference)
    assert rejected == []
    assert reason == "could_not_match_flex_groups_to_input_atoms"


def test_pdbqt_nul_counts_and_vina_extraction_preserve_raw_output(tmp_path: Path) -> None:
    pure_nul = "\0" * 30
    embedded_nul = "REMARK SYNTHETIC_GATE0_EMBEDDED\0NUL"
    document = model(
        1, embedded_nul, "ROOT", atom("C", "UNL", 1, 0), "ENDROOT", "TORSDOF 4", pure_nul,
        "BEGIN_RES TYR A 4", "ROOT", atom("CB", "TYR", 4, 1), "\0\0",
        "ENDROOT", "END_RES TYR A 4",
    ) + model(2, "REMARK SYNTHETIC_GATE0_WITHOUT_NUL") + "\0\n"
    raw_bytes = document.replace("\n", "\r\n").encode("ascii")
    raw = tmp_path / "vina_flex_out.pdbqt"
    raw.write_bytes(raw_bytes)

    summary = probe.summarize_pdbqt(document)
    assert (summary["nul_line_count"], summary["nul_byte_count"]) == (4, 34)
    assert summary["outside_model_counts"] == {}
    first, second = summary["models"]
    assert (first["nul_line_count"], first["nul_byte_count"]) == (3, 33)
    assert (second["nul_line_count"], second["nul_byte_count"]) == (0, 0)
    assert first["counts"] == {
        "REMARK": 1, "ROOT": 2, "ATOM": 2, "ENDROOT": 2, "TORSDOF": 1,
        "BEGIN_RES": 1, "END_RES": 1,
    }
    clean_summary = probe.summarize_pdbqt(model(1, "REMARK SYNTHETIC_GATE0_WITHOUT_NUL"))
    assert (clean_summary["nul_line_count"], clean_summary["nul_byte_count"]) == (0, 0)

    case = probe.Case(tmp_path, "synthetic_vina_extraction")
    ligand, flex = probe.prepare_pose_inputs(
        case, raw, ligand_name="pose1_lig.pdbqt", flex_name="pose1_flex.pdbqt",
    )
    assert ligand is not None and flex is not None
    assert case.record["stripped_nul_lines"] == 2
    assert ligand.read_text(encoding="ascii").splitlines() == [
        embedded_nul, "ROOT", atom("C", "UNL", 1, 0), "ENDROOT", "TORSDOF 4",
    ]
    assert flex.read_text(encoding="ascii").splitlines() == [
        "BEGIN_RES TYR A 4", "ROOT", atom("CB", "TYR", 4, 1), "ENDROOT", "END_RES TYR A 4",
    ]
    assert raw.read_bytes() == (case.work / raw.name).read_bytes() == raw_bytes


def test_pdbqt_reports_nul_counts_when_an_atom_field_is_corrupted() -> None:
    record = atom("CA", "TYR", 4, 1)
    corrupted = record[:34] + "\0" + record[35:]
    summary = probe.summarize_pdbqt(model(1, "REMARK SYNTHETIC_GATE0_CORRUPTED", corrupted))
    assert (summary["nul_line_count"], summary["nul_byte_count"]) == (1, 1)
    assert "parse_error" in summary
    first = summary["models"][0]
    assert (first["nul_line_count"], first["nul_byte_count"]) == (1, 1)
    assert first["counts"] == {"ATOM": 1, "REMARK": 1}
    assert "parse_error" in first


@pytest.fixture
def synthetic_reinjection() -> tuple[str, str, str]:
    first = atom("CA", "TYR", 4, 1)
    first = first[:26] + "B" + first[27:66] + " -0.125 C"
    second = atom("CB", "TYR", 4, 2)
    second = "HETATM    2" + second[11:26] + "B" + second[27:66] + "  0.250 OA"
    template_lines = [
        "REMARK SYNTHETIC_GATE0_MEEKO_TEMPLATE", "BEGIN_RES TYR A 4B", "ROOT", first, "ENDROOT",
        "BRANCH 1 2", second, "ENDBRANCH 1 2", "END_RES TYR A 4B", "",
    ]
    first_xyz = "  -1.125   2.250   3.375"
    second_xyz = "   4.500  -5.625   6.750"
    moved = model(
        3, "REMARK SYNTHETIC_GATE0_GNINA_FLEX_PDB",
        f"HETATM   22{second[11:30]}{second_xyz}  1.00  0.00           O",
        f"ATOM     21{first[11:30]}{first_xyz}  1.00  0.00           C",
    )
    expected_atoms = {
        first: first[:30] + first_xyz + first[54:],
        second: second[:30] + second_xyz + second[54:],
    }
    expected_lines = [expected_atoms.get(line, line) for line in template_lines]
    return "\r\n".join(template_lines), moved, "\r\n".join(expected_lines)


def test_gnina_reinjection_only_changes_coordinate_columns(
    synthetic_reinjection: tuple[str, str, str],
) -> None:
    template, moved, expected = synthetic_reinjection
    result = probe.reinject_flex_pdb_coords_into_meeko_pdbqt(template, moved)
    assert result == expected
    atoms = probe.parse_atoms(result.splitlines())
    assert [item.xyz for item in atoms] == [(-1.125, 2.250, 3.375), (4.500, -5.625, 6.750)]
    assert [(item.charge, item.atom_type) for item in atoms] == [(-0.125, "C"), (0.250, "OA")]


@pytest.mark.parametrize(
    "error_case", ["missing", "mismatch", "duplicate_pdb", "duplicate_template"],
)
def test_gnina_reinjection_rejects_non_matching_atoms(
    synthetic_reinjection: tuple[str, str, str], error_case: str,
) -> None:
    template, moved, _ = synthetic_reinjection
    moved_atom = next(line for line in moved.splitlines() if line.startswith("HETATM"))
    template_atom = next(line for line in template.splitlines() if line.startswith("HETATM"))
    if error_case == "missing":
        moved = moved.replace(moved_atom + "\n", "")
    elif error_case == "mismatch":
        moved = moved.replace(moved_atom, moved_atom[:26] + "C" + moved_atom[27:])
    elif error_case == "duplicate_pdb":
        moved = moved.replace(moved_atom, f"{moved_atom}\n{moved_atom}")
    else:
        template = template.replace(template_atom, f"{template_atom}\r\n{template_atom}")
    with pytest.raises(ValueError, match="Flex atom mismatch|Duplicate flex atom"):
        probe.reinject_flex_pdb_coords_into_meeko_pdbqt(template, moved)


def test_gnina_flex_pdb_reports_actual_headers_and_pairs_models_by_ordinal(
    synthetic_reinjection: tuple[str, str, str],
) -> None:
    template, moved, _ = synthetic_reinjection
    ligand, _ = probe.parse_models(
        model(1, "REMARK SYNTHETIC_GATE0_LIGAND") + model(2, "REMARK SYNTHETIC_GATE0_LIGAND"),
    )
    two_modes = moved + moved.replace("MODEL 3", "MODEL 4", 1)
    _, summary = probe.inspect_gnina_flex_pdb(two_modes, ligand, template)
    assert summary["model_count"] == summary["ligand_model_count"] == 2
    assert summary["one_complete_model_per_mode"]
    pairs = [
        (row["pose_index"], row["model"], row["ligand_model"]) for row in summary["models"]
    ]
    assert pairs == [(0, 3, "1"), (1, 4, "2")]
    assert summary["max_displacement_angstrom"] == pytest.approx(
        math.dist((2, 0, 0), (4.5, -5.625, 6.75)),
    )
    _, incomplete = probe.inspect_gnina_flex_pdb(
        two_modes.removesuffix("ENDMDL\n"), ligand, template,
    )
    assert not incomplete["one_complete_model_per_mode"]


def test_gnina_meeko_subcases_with_synthetic_outputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, synthetic_reinjection: tuple[str, str, str],
) -> None:
    template, moved, expected = synthetic_reinjection
    rigid, flex, amide = (tmp_path / name for name in (
        probe.RIGID_NAME, probe.FLEX_NAME, "amide_default.pdbqt",
    ))
    flex.write_bytes(template.encode("ascii"))
    ligand_line = atom("C", "UNL", 1, 1)
    ligand = model(1, "REMARK SYNTHETIC_GATE0_LIGAND", ligand_line)
    for path in (rigid, amide):
        path.write_text("REMARK SYNTHETIC_GATE0_INPUT\n", encoding="ascii")
    box = probe.BindingBox(center_x=0, center_y=0, center_z=0, size_x=20, size_y=20, size_z=20)
    workflow = probe.Probe(tmp_path, Namespace())
    score_tags = (
        "Affinity", "CNNscore", "CNNaffinity", "CNNvariance", "Intramolecular energy", "RMSD",
    )

    def fake_run(case: probe.Case, engine: str, args: list[str]) -> probe.Run:
        assert engine == "gnina" and "--no_gpu" in args
        if "--score_only" in args or "--local_only" in args:
            assert (case.work / "pose1_flex_meeko.pdbqt").read_bytes() == expected.encode("ascii")
            assert ligand_line in (case.work / "pose1_lig.pdbqt").read_text(encoding="ascii")
        if "--out" in args:
            output_pdb = moved
            if "--local_only" in args:
                output_pdb = moved.replace("   6.750", "   7.750")
            ligand_path = case.work / args[args.index("--out") + 1]
            flex_path = case.work / args[args.index("--out_flex") + 1]
            ligand_path.write_text(ligand, encoding="ascii")
            flex_path.write_text(output_pdb, encoding="ascii")
        run = probe.Run(0, "exited_zero", "\n".join(f"{tag}: 1" for tag in score_tags))
        case.save_run("synthetic", [engine, *args], run, log=False)
        return run

    monkeypatch.setattr(workflow, "run", fake_run)
    monkeypatch.setattr(probe, "sys", SimpleNamespace(platform="linux", executable=sys.executable))
    parent = "E/E4_gnina_linux_flex_and_score_only"
    probe.gnina_meeko_reinjection_probes(
        workflow, parent, probe.Receptor(rigid, flex, box=box), amide,
    )
    dock = workflow.cases[f"{parent}/gnina_flex_cpu_pdb"]
    assert dock.record["reinjection"]["flex_model"] == 3
    assert (dock.work / "gnina_flex_cpu.pdb").read_text(encoding="ascii") == moved
    assert flex.read_bytes() == template.encode("ascii")
    for mode, displacement in (("score_only", None), ("local_only", 1.0)):
        case = workflow.cases[f"{parent}/gnina_meeko_reinjection/{mode}"]
        assert case.commands[0]["exit_code"] == 0
        assert [score["tag"] for score in case.record["stdout_scores"]] == list(score_tags)
        assert case.record["max_displacement_angstrom"] == displacement


def test_report_paths_are_relative_and_excerpts_redact_host_paths(tmp_path: Path) -> None:
    executable = tmp_path / "SYNTHETIC_GATE0 Binary" / "tool"
    windows_path = "Q:" + chr(92) + "SYNTHETIC_GATE0 Private" + chr(92) + "tool.exe"
    message = f'running {executable} or "{windows_path}" with E/E4/pose1.pdbqt'
    redacted = probe.excerpt(message, paths=[executable])
    assert str(executable) not in redacted
    assert windows_path not in redacted
    assert redacted.endswith("with E/E4/pose1.pdbqt")


def test_sanitize_text_redacts_complete_windows_paths_with_or_without_known_prefix() -> None:
    drive = "Q:"
    home = PureWindowsPath(drive + r"\Users\SYNTHETIC_GATE0")
    file = home / "My Documents" / "project" / "file.py"
    message = f"traceback in {file} with E/E4/pose1.pdbqt"
    expected = "traceback in <absolute path> with E/E4/pose1.pdbqt"
    assert probe.sanitize_text(message) == expected
    assert probe.sanitize_text(message, paths=[home]) == expected
    sibling = home.with_name(home.name + "_OTHER") / "Documents" / "file.py"
    assert probe.sanitize_text(f"traceback in {sibling}", [home]) == "traceback in <absolute path>"
    assert probe.sanitize_text(f'File "{file.with_name("my script.py")}", line 42', [home]) == (
        "File <absolute path>, line 42"
    )
