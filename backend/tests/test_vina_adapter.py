"""Deterministic tests for the AutoDock Vina adapter.

All molecular text in this file is explicitly synthetic. No score is intended
to represent a real docking calculation.
"""

from pathlib import Path

import pytest
from ankora_backend.adapters.engines import vina
from ankora_backend.adapters.engines.vina import (
    VinaInstallation,
    build_vina_arguments,
    parse_vina_poses,
    probe_vina,
)
from ankora_backend.adapters.tools import discovery
from ankora_backend.adapters.tools.discovery import DiscoveredTool, discover_vina
from ankora_backend.domain.errors import AnkoraDomainError
from ankora_backend.execution.subprocess_runner import ToolExecution
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


@pytest.mark.parametrize(
    "discovered_state",
    [
        DiscoveredTool(available=False, path=None, version=None),
        DiscoveredTool(available=True, path=None, version=None),
        DiscoveredTool(available=False, path="/synthetic/vina", version="1.2.7"),
    ],
)
def test_probe_vina_unavailable_preserves_frozen_error_contract(
    monkeypatch: pytest.MonkeyPatch,
    discovered_state: DiscoveredTool,
) -> None:
    monkeypatch.setenv("ANKORA_VINA_PATH", "/synthetic/configured/vina")
    observed_configured_paths: list[str | Path | None] = []

    def fake_discover_vina(configured_path: str | Path | None = None) -> DiscoveredTool:
        observed_configured_paths.append(configured_path)
        return discovered_state

    def forbid_run_tool(**_: object) -> ToolExecution:
        raise AssertionError("run_tool must not be called when Vina is unavailable")

    monkeypatch.setattr(vina, "discover_vina", fake_discover_vina)
    monkeypatch.setattr(vina, "run_tool", forbid_run_tool)

    with pytest.raises(AnkoraDomainError) as captured:
        probe_vina()

    assert observed_configured_paths == ["/synthetic/configured/vina"]
    assert captured.value.code == "SCIENTIFIC_TOOL_UNAVAILABLE"
    assert captured.value.stage == "docking_configuration"
    assert captured.value.message == "AutoDock Vina is not configured on this Windows system."
    assert captured.value.status_code == 422
    assert captured.value.details == {
        "tool": "AutoDock Vina",
        "expected_version": "1.2.7",
    }
    assert captured.value.recoverable is True


@pytest.mark.parametrize("windows_rules", [True, False])
def test_probe_vina_preserves_original_discovery_failures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    windows_rules: bool,
) -> None:
    missing_path = tmp_path / "missing" / ("vina.exe" if windows_rules else "vina")
    non_executable_file = tmp_path / "plain-file"
    non_executable_file.write_bytes(b"synthetic non-executable data")
    non_executable_file.chmod(0o644)

    monkeypatch.setattr(discovery, "_windows_host", lambda: windows_rules)

    def forbid_run_tool(**_: object) -> ToolExecution:
        raise AssertionError("run_tool must not be called when discovery fails")

    monkeypatch.setattr(vina, "run_tool", forbid_run_tool)

    candidates = [missing_path]
    if not windows_rules:
        candidates.append(non_executable_file)

    for configured in candidates:
        monkeypatch.setenv("ANKORA_VINA_PATH", str(configured))
        direct = discover_vina(str(configured))
        assert direct == DiscoveredTool(available=False, path=None, version=None)

        with pytest.raises(AnkoraDomainError) as captured:
            probe_vina()

        assert captured.value.code == "SCIENTIFIC_TOOL_UNAVAILABLE"
        assert captured.value.stage == "docking_configuration"
        assert captured.value.message == "AutoDock Vina is not configured on this Windows system."
        assert captured.value.status_code == 422
        assert captured.value.details == {
            "tool": "AutoDock Vina",
            "expected_version": "1.2.7",
        }


def test_probe_vina_verifies_version_and_preserves_probe_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    executable = tmp_path / "bin" / "vina"
    monkeypatch.setattr(
        vina,
        "discover_vina",
        lambda _configured: DiscoveredTool(available=True, path=str(executable), version="1.2.7"),
    )
    recorded_calls: list[dict[str, object]] = []

    def fake_run_tool(**kwargs: object) -> ToolExecution:
        recorded_calls.append(kwargs)
        return ToolExecution(
            command=[str(executable), "--version"],
            exit_code=0,
            stdout="AutoDock Vina v1.2.7\n",
            stderr="",
        )

    monkeypatch.setattr(vina, "run_tool", fake_run_tool)
    installation = probe_vina()

    assert installation == VinaInstallation(executable=str(executable), version="1.2.7")
    assert recorded_calls == [
        {
            "executable": str(executable),
            "arguments": ["--version"],
            "cwd": executable.parent,
            "stage": "docking_configuration",
            "timeout_seconds": 30,
        }
    ]

    monkeypatch.setattr(
        vina,
        "run_tool",
        lambda **_kwargs: ToolExecution(
            command=[str(executable), "--version"],
            exit_code=1,
            stdout="",
            stderr="synthetic probe failure",
        ),
    )
    with pytest.raises(AnkoraDomainError) as unverified:
        probe_vina()
    assert unverified.value.code == "VINA_VERSION_UNVERIFIED"
    assert unverified.value.stage == "docking_configuration"
    assert (
        unverified.value.message == "Ankora found Vina but could not verify its executable version."
    )
    assert unverified.value.status_code == 422
    assert unverified.value.details == {
        "command": [str(executable), "--version"],
        "exit_code": 1,
        "stdout": "",
        "stderr": "synthetic probe failure",
    }

    monkeypatch.setattr(
        vina,
        "run_tool",
        lambda **_kwargs: ToolExecution(
            command=[str(executable), "--version"],
            exit_code=0,
            stdout="AutoDock Vina v1.2.5\n",
            stderr="",
        ),
    )
    with pytest.raises(AnkoraDomainError) as unsupported:
        probe_vina()
    assert unsupported.value.code == "VINA_VERSION_UNSUPPORTED"
    assert unsupported.value.stage == "docking_configuration"
    assert unsupported.value.message == "This M5 implementation requires AutoDock Vina 1.2.7."
    assert unsupported.value.status_code == 422
    assert unsupported.value.details == {
        "detected_version": "1.2.5",
        "required_version": "1.2.7",
    }
