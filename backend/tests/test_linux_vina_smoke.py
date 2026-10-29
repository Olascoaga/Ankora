"""Contracts for the predeclared Linux CPU Vina engineering smoke script.

Every receptor, ligand, prediction table, "Vina" binary and Vina output here is
a SYNTHETIC fake. The probe and execution callables are fakes; no real Vina,
network or scientific project is used, and no fake value is a docking result.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from ankora_backend.adapters.engines.vina import VinaInstallation, build_vina_arguments
from ankora_backend.execution.cancellable_subprocess import CancellableToolExecution
from ankora_backend.schemas.binding_sites import BindingBox

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPOSITORY_ROOT / "scripts" / "validate_linux_vina_smoke.py"
PLAN = REPOSITORY_ROOT / "docs" / "validation" / "LINUX_VINA_CPU_SMOKE_PLAN.md"

RECEPTOR = b"REMARK SYNTHETIC receptor fixture; not a structure\n"
LIGAND = b"REMARK SYNTHETIC ligand fixture; not a molecule\n"
BINARY = b"SYNTHETIC Vina stand-in; never executed"
PREDICTIONS = (
    "name     ,  rank,   score,   center_x,   center_y,   center_z\n"
    "pocket1  ,     1,    0.10,   -23.7785,    40.9869,    25.9487\n"
    "pocket2  ,     2,    0.05,     1.0000,     2.0000,     3.0000\n"
)
# SYNTHETIC fake adapter output: well-formed PDBQT records with made-up numbers.
FAKE_OUTPUT = (
    b"MODEL 1\n"
    b"REMARK VINA RESULT:    -1.000      0.000      0.000\n"
    b"REMARK SYNTHETIC fake adapter output; not a Vina result\n"
    b"ENDMDL\n"
    b"MODEL 2\n"
    b"REMARK VINA RESULT:    -0.500      1.200      2.400\n"
    b"ENDMDL\n"
)


@pytest.fixture(scope="module")
def smoke() -> ModuleType:
    spec = importlib.util.spec_from_file_location("validate_linux_vina_smoke", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class FakeAdapter:
    """Records calls; returns a SYNTHETIC execution and optionally writes output."""

    def __init__(
        self,
        tmp_path: Path,
        *,
        version: str = "1.2.7",
        exit_code: int = 0,
        timed_out: bool = False,
        canceled: bool = False,
        output: bytes | None = FAKE_OUTPUT,
    ) -> None:
        self.binary = tmp_path / "synthetic-vina"
        self.binary.write_bytes(BINARY)
        self.version = version
        self.result = (exit_code, timed_out, canceled)
        self.output = output
        self.calls: list[dict[str, Any]] = []
        self.probed = 0

    def probe(self) -> VinaInstallation:
        self.probed += 1
        return VinaInstallation(executable=str(self.binary), version=self.version)

    def execute(self, **kwargs: Any) -> CancellableToolExecution:
        self.calls.append(kwargs)
        if self.output is not None:
            kwargs["output_path"].write_bytes(self.output)
        exit_code, timed_out, canceled = self.result
        return CancellableToolExecution(
            command=["synthetic-vina", "--out", str(kwargs["output_path"])],
            exit_code=exit_code,
            stdout="synthetic stdout ü\r\nline 2\n",
            stderr="synthetic stderr\n",
            canceled=canceled,
            timed_out=timed_out,
        )


def _fixtures(tmp_path: Path) -> dict[str, Path]:
    paths = {
        "receptor": tmp_path / "receptor.pdbqt",
        "ligand": tmp_path / "ligand.pdbqt",
        "pocket_predictions": tmp_path / "predictions.csv",
    }
    paths["receptor"].write_bytes(RECEPTOR)
    paths["ligand"].write_bytes(LIGAND)
    paths["pocket_predictions"].write_text(PREDICTIONS, encoding="utf-8")
    return paths


def _pinned(smoke: ModuleType, predictions: str = PREDICTIONS) -> Any:
    return smoke.PinnedIdentities(
        receptor_sha256=hashlib.sha256(RECEPTOR).hexdigest(),
        ligand_sha256=hashlib.sha256(LIGAND).hexdigest(),
        pocket_predictions_sha256=hashlib.sha256(predictions.encode()).hexdigest(),
        vina_sha256=hashlib.sha256(BINARY).hexdigest(),
    )


def _run(
    smoke: ModuleType,
    tmp_path: Path,
    adapter: FakeAdapter,
    *,
    host: tuple[str, str] = ("linux", "x86_64"),
    predictions: str = PREDICTIONS,
) -> tuple[dict[str, Any], Path]:
    paths = _fixtures(tmp_path)
    if predictions != PREDICTIONS:
        paths["pocket_predictions"].write_text(predictions, encoding="utf-8")
    output = tmp_path / "evidence"
    returned = smoke.run_smoke(
        **paths,
        output=output,
        probe=adapter.probe,
        execute=adapter.execute,
        host=host,
        pinned=_pinned(smoke, predictions),
    )
    recorded = json.loads((output / "evidence.json").read_text(encoding="utf-8"))
    assert recorded == returned
    return recorded, output


def test_existing_output_is_refused_and_left_untouched(smoke: ModuleType, tmp_path: Path) -> None:
    adapter = FakeAdapter(tmp_path)
    paths = _fixtures(tmp_path)
    output = tmp_path / "evidence"
    output.mkdir()
    (output / "earlier.txt").write_text("earlier run", encoding="utf-8")

    with pytest.raises(FileExistsError):
        smoke.run_smoke(**paths, output=output, probe=adapter.probe, execute=adapter.execute)
    arguments = ["--receptor", str(paths["receptor"]), "--ligand", str(paths["ligand"])]
    arguments += ["--pocket-predictions", str(paths["pocket_predictions"])]
    assert smoke.main([*arguments, "--output", str(output)]) == 2

    assert [path.name for path in output.iterdir()] == ["earlier.txt"]
    assert (adapter.probed, adapter.calls) == (0, [])


@pytest.mark.parametrize("role", ["receptor", "ligand", "pocket_predictions"])
def test_drifted_input_is_recorded_and_vina_never_runs(
    smoke: ModuleType, tmp_path: Path, role: str
) -> None:
    adapter = FakeAdapter(tmp_path)
    paths = _fixtures(tmp_path)
    paths[role].write_bytes(paths[role].read_bytes() + b"drift")
    output = tmp_path / "evidence"

    evidence = smoke.run_smoke(
        **paths,
        output=output,
        probe=adapter.probe,
        execute=adapter.execute,
        host=("linux", "x86_64"),
        pinned=_pinned(smoke),
    )

    assert evidence["status"] == "failed"
    assert evidence["failure"]["stage"] == "input_verification"
    assert evidence["failure"]["details"]["role"] == role
    assert (adapter.probed, adapter.calls) == (0, [])


def test_missing_input_is_recorded(smoke: ModuleType, tmp_path: Path) -> None:
    adapter = FakeAdapter(tmp_path)
    paths = _fixtures(tmp_path)
    paths["ligand"].unlink()

    evidence = smoke.run_smoke(
        **paths,
        output=tmp_path / "evidence",
        probe=adapter.probe,
        execute=adapter.execute,
        host=("linux", "x86_64"),
        pinned=_pinned(smoke),
    )

    assert evidence["failure"]["message"] == "ligand input is missing"
    assert adapter.calls == []


@pytest.mark.parametrize("host", [("darwin", "x86_64"), ("linux", "aarch64"), ("win32", "AMD64")])
def test_non_linux_x86_64_host_is_refused(
    smoke: ModuleType, tmp_path: Path, host: tuple[str, str]
) -> None:
    adapter = FakeAdapter(tmp_path)

    evidence, _ = _run(smoke, tmp_path, adapter, host=host)

    assert evidence["failure"]["stage"] == "host_verification"
    assert (adapter.probed, adapter.calls) == (0, [])


@pytest.mark.parametrize("version", ["1.2.5", "1.2.7"])
def test_unpinned_vina_identity_is_refused(smoke: ModuleType, tmp_path: Path, version: str) -> None:
    adapter = FakeAdapter(tmp_path, version=version)
    if version == "1.2.7":
        adapter.binary.write_bytes(BINARY + b" (different build)")

    evidence, _ = _run(smoke, tmp_path, adapter)

    assert evidence["failure"]["stage"] == "vina_identity"
    assert evidence["vina"]["version"] == version
    assert adapter.calls == []


def test_declared_box_parameters_reach_the_real_argument_builder(
    smoke: ModuleType, tmp_path: Path
) -> None:
    adapter = FakeAdapter(tmp_path)

    _, output = _run(smoke, tmp_path, adapter)

    (call,) = adapter.calls
    assert call["box"] == BindingBox(
        center_x=-23.7785, center_y=40.9869, center_z=25.9487, size_x=20, size_y=20, size_z=20
    )
    assert call["receptor_path"] == output / "inputs" / "receptor.pdbqt"
    assert call["ligand_path"] == output / "inputs" / "ligand.pdbqt"
    assert call["output_path"] == output / "vina_out.pdbqt"
    assert call["installation"] == VinaInstallation(str(adapter.binary), "1.2.7")
    arguments = build_vina_arguments(
        receptor_path=call["receptor_path"],
        ligand_path=call["ligand_path"],
        output_path=call["output_path"],
        box=call["box"],
        parameters=call["parameters"],
    )
    flags = dict(zip(arguments[::2], arguments[1::2], strict=True))
    assert {key: flags[key] for key in flags if key not in {"--receptor", "--ligand", "--out"}} == {
        "--center_x": "-23.7785",
        "--center_y": "40.9869",
        "--center_z": "25.9487",
        "--size_x": "20",
        "--size_y": "20",
        "--size_z": "20",
        "--cpu": "2",
        "--seed": "20261028",
        "--exhaustiveness": "2",
        "--num_modes": "3",
        "--min_rmsd": "1",
        "--energy_range": "3",
        "--verbosity": "1",
    }
    assert call["parameters"].timeout_minutes == 1
    assert call["parameters"].sampling_protocol.value == "custom"


def test_successful_run_preserves_raw_output_streams_and_pose_metadata(
    smoke: ModuleType, tmp_path: Path
) -> None:
    adapter = FakeAdapter(tmp_path)

    evidence, output = _run(smoke, tmp_path, adapter)

    assert evidence["status"] == "completed" and "failure" not in evidence
    assert (output / "vina_out.pdbqt").read_bytes() == FAKE_OUTPUT
    assert evidence["raw_output"]["sha256"] == hashlib.sha256(FAKE_OUTPUT).hexdigest()
    assert [pose["mode"] for pose in evidence["poses"]] == [1, 2]
    assert [pose["vina_score_kcal_mol"] for pose in evidence["poses"]] == [-1.0, -0.5]
    assert evidence["poses"][1]["rmsd_upper_bound_angstrom"] == 2.4
    assert (output / "vina.stdout.txt").read_bytes() == "synthetic stdout ü\r\nline 2\n".encode()
    assert (output / "inputs" / "receptor.pdbqt").read_bytes() == RECEPTOR
    assert evidence["vina"]["executable_sha256"] == hashlib.sha256(BINARY).hexdigest()
    assert evidence["execution"]["exit_code"] == 0
    assert "not experimental affinities" in evidence["score_interpretation"]
    with pytest.raises(FileExistsError):
        smoke.run_smoke(
            receptor=tmp_path / "receptor.pdbqt",
            ligand=tmp_path / "ligand.pdbqt",
            pocket_predictions=tmp_path / "predictions.csv",
            output=output,
            probe=adapter.probe,
            execute=adapter.execute,
        )
    assert len(adapter.calls) == 1


@pytest.mark.parametrize(
    "outcome",
    [{"exit_code": 1}, {"timed_out": True, "exit_code": -9}, {"canceled": True, "exit_code": -15}],
)
def test_failed_execution_keeps_streams_and_claims_no_poses(
    smoke: ModuleType, tmp_path: Path, outcome: dict[str, Any]
) -> None:
    adapter = FakeAdapter(tmp_path, output=b"MODEL 1\n", **outcome)

    evidence, output = _run(smoke, tmp_path, adapter)

    assert evidence["status"] == "failed"
    assert evidence["failure"]["stage"] == "vina_execution"
    assert evidence["execution"]["exit_code"] == outcome["exit_code"]
    assert (output / "vina.stderr.txt").read_text(encoding="utf-8") == "synthetic stderr\n"
    assert evidence["raw_output"]["sha256"] == hashlib.sha256(b"MODEL 1\n").hexdigest()
    assert "poses" not in evidence


def test_unparseable_output_is_a_structured_failure(smoke: ModuleType, tmp_path: Path) -> None:
    adapter = FakeAdapter(tmp_path, output=b"REMARK SYNTHETIC output without models\n")

    evidence, _ = _run(smoke, tmp_path, adapter)

    assert evidence["status"] == "failed"
    assert evidence["failure"]["code"] == "VINA_OUTPUT_INVALID"
    assert "poses" not in evidence


def test_changed_pocket_center_is_refused_before_vina(smoke: ModuleType, tmp_path: Path) -> None:
    adapter = FakeAdapter(tmp_path)
    moved = PREDICTIONS.replace("-23.7785", "-23.7786")

    evidence, _ = _run(smoke, tmp_path, adapter, predictions=moved)

    assert evidence["failure"]["stage"] == "pocket_verification"
    assert adapter.calls == []


def test_pinned_identities_and_protocol_are_those_of_the_plan(smoke: ModuleType) -> None:
    plan = PLAN.read_text(encoding="utf-8")

    for digest in vars(smoke.PINNED).values():
        assert f"`{digest}`" in plan
    assert "(-23.7785, 40.9869, 25.9487)" in plan
    for setting in ("20261028", "exhaustiveness | 2", "num_modes | 3", "cpu_threads | 2"):
        assert setting in plan
