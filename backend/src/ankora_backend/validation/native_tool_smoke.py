"""Bounded Windows smoke matrix for every supported process-launching adapter.

The matrix writes create-only local evidence below ``.ankora-data``.  It is a
runtime compatibility check, not a scientific benchmark: receptor and ligand
transformations use fixed fixtures, while docking engines are limited to their
version/device probes and never start a docking calculation.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import importlib.metadata
import json
import os
import shutil
import sys
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from ankora_backend.adapters.engines.autodock4_runner import probe_autodock4
from ankora_backend.adapters.engines.autodock_gpu import probe_autodock_gpu
from ankora_backend.adapters.engines.autogrid import probe_autogrid4
from ankora_backend.adapters.engines.vina import probe_vina
from ankora_backend.adapters.tools.discovery import discover_java_home
from ankora_backend.adapters.tools.ligand_preparation import execute_meeko_ligand
from ankora_backend.adapters.tools.pocket_detection import execute_p2rank
from ankora_backend.adapters.tools.receptor_preparation import (
    run_meeko_receptor,
    run_pdb2pqr_propka,
    run_pdbfixer,
)
from ankora_backend.domain.errors import AnkoraDomainError
from ankora_backend.execution.subprocess_runner import ToolExecution, run_tool
from ankora_backend.persistence.ligand_store import LigandArtifactStore
from ankora_backend.schemas.ligands import GenerateLigandConformerRequest, LigandChargeModel
from ankora_backend.schemas.receptors import ResidueLocator
from ankora_backend.services.ligand_import import import_local_ligand
from ankora_backend.services.ligand_minimization import generate_ligand_conformer

SCHEMA_VERSION = 1
SUPPORTED_ADAPTER_IDS = (
    "python_scientific_runtime",
    "pdbfixer_repair",
    "pdb2pqr_propka",
    "meeko_receptor",
    "meeko_ligand",
    "p2rank",
    "vina",
    "autogrid4",
    "autodock4_cpu",
    "autodock_gpu",
)
DEFERRED_TOOLS = {
    "gnina": "No supported GNINA execution adapter exists in the current release scope."
}
PACKAGE_IMPORTS = {
    "dimorphite_dl": "dimorphite_dl",
    "MDAnalysis": "MDAnalysis",
    "meeko": "meeko",
    "openmm": "openmm",
    "pdb2pqr": "pdb2pqr",
    "pdbfixer": "pdbfixer",
    "prolif": "prolif",
    "propka": "propka",
    "rdkit": "rdkit",
}


@dataclass(frozen=True, slots=True)
class FileEvidence:
    role: str
    path: str
    size_bytes: int
    sha256: str


@dataclass(frozen=True, slots=True)
class ExecutionEvidence:
    command: list[str]
    exit_code: int
    stdout_path: str
    stdout_sha256: str
    stderr_path: str
    stderr_sha256: str


@dataclass(slots=True)
class AdapterResult:
    adapter_id: str
    adapter: str
    scope: str
    status: str = "pending"
    version: str | None = None
    executable_sha256: str | None = None
    fixtures: list[FileEvidence] = field(default_factory=list)
    outputs: list[FileEvidence] = field(default_factory=list)
    executions: list[ExecutionEvidence] = field(default_factory=list)
    details: dict[str, object] = field(default_factory=dict)
    error: str | None = None


class EvidenceWriter:
    """Persist exact tool I/O without mixing it into a scientific project."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        if self.root.exists():
            raise FileExistsError(
                f"Native-tool smoke evidence is create-only: {self.root}"
            )
        self.root.mkdir(parents=True)

    def adapter_directory(self, adapter_id: str) -> Path:
        directory = self.root / adapter_id
        directory.mkdir()
        return directory

    def execution(
        self,
        *,
        result: AdapterResult,
        execution: ToolExecution,
        sequence: int | None = None,
    ) -> None:
        executable_index = 0
        if (
            execution.command
            and Path(execution.command[0]).name.lower() in {"cmd", "cmd.exe"}
            and len(execution.command) > 2
            and execution.command[1].lower() in {"/c", "/k"}
        ):
            executable_index = 2
        if result.executable_sha256 is None and execution.command:
            executable = Path(execution.command[executable_index])
            if executable.is_file():
                result.executable_sha256 = _sha256(executable)
        suffix = f"-{sequence}" if sequence is not None else ""
        stdout = self.root / result.adapter_id / f"execution{suffix}.stdout.txt"
        stderr = self.root / result.adapter_id / f"execution{suffix}.stderr.txt"
        stdout.write_text(execution.stdout, encoding="utf-8", newline="\n")
        stderr.write_text(execution.stderr, encoding="utf-8", newline="\n")
        result.executions.append(
            ExecutionEvidence(
                command=execution.command,
                exit_code=execution.exit_code,
                stdout_path=self._relative(stdout),
                stdout_sha256=_sha256(stdout),
                stderr_path=self._relative(stderr),
                stderr_sha256=_sha256(stderr),
            )
        )

    def file(self, *, path: Path, role: str) -> FileEvidence:
        resolved = path.resolve()
        return FileEvidence(
            role=role,
            path=self._relative(resolved),
            size_bytes=resolved.stat().st_size,
            sha256=_sha256(resolved),
        )

    def finish(self, results: list[AdapterResult]) -> tuple[Path, str]:
        status = "passed" if all(item.status == "passed" for item in results) else "failed"
        manifest = {
            "schema_version": SCHEMA_VERSION,
            "created_at": datetime.now(UTC).isoformat(),
            "platform": sys.platform,
            "python": sys.version,
            "status": status,
            "supported_adapter_ids": list(SUPPORTED_ADAPTER_IDS),
            "deferred_tools": DEFERRED_TOOLS,
            "results": [asdict(item) for item in results],
        }
        path = self.root / "manifest.json"
        path.write_text(
            json.dumps(manifest, indent=2, sort_keys=True),
            encoding="utf-8",
            newline="\n",
        )
        return path, _sha256(path)

    def _relative(self, path: Path) -> str:
        try:
            return path.relative_to(self.root).as_posix()
        except ValueError:
            return str(path)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _copy_fixture(source: Path, destination: Path) -> Path:
    if not source.is_file():
        raise FileNotFoundError(source)
    shutil.copyfile(source, destination)
    return destination


def _outputs(
    writer: EvidenceWriter,
    result: AdapterResult,
    directory: Path,
    *,
    excluded: set[Path],
) -> None:
    for path in sorted(directory.rglob("*"), key=lambda item: item.as_posix()):
        if not path.is_file() or path in excluded or path.name.startswith("execution"):
            continue
        result.outputs.append(writer.file(path=path, role="tool_output"))


def _require_success(execution: ToolExecution, output: Path | None = None) -> None:
    if execution.exit_code != 0:
        raise RuntimeError(f"tool exited with code {execution.exit_code}")
    if output is not None and not output.is_file():
        raise RuntimeError(f"tool did not create required output {output.name}")


def _record_domain_failure(
    writer: EvidenceWriter, result: AdapterResult, error: AnkoraDomainError
) -> None:
    details = error.details or {}
    command = details.get("command")
    exit_code = details.get("exit_code")
    stdout = details.get("stdout")
    stderr = details.get("stderr")
    if (
        isinstance(command, list)
        and all(isinstance(item, str) for item in command)
        and isinstance(exit_code, int)
        and isinstance(stdout, str)
        and isinstance(stderr, str)
    ):
        writer.execution(
            result=result,
            execution=ToolExecution(
                command=command,
                exit_code=exit_code,
                stdout=stdout,
                stderr=stderr,
            ),
        )
    result.status = "failed"
    result.error = f"{error.code}: {error.message}"


def _run_adapter(
    writer: EvidenceWriter,
    result: AdapterResult,
    operation: Callable[[], None],
) -> None:
    try:
        operation()
    except AnkoraDomainError as error:
        _record_domain_failure(writer, result, error)
    except Exception as error:
        result.status = "failed"
        result.error = f"{type(error).__name__}: {error}"
    else:
        result.status = "passed"


def _package_probe_payload() -> dict[str, str]:
    versions: dict[str, str] = {}
    for distribution, module in PACKAGE_IMPORTS.items():
        importlib.import_module(module)
        versions[distribution] = importlib.metadata.version(distribution)
    return versions


def _default_receptor_fixture() -> Path:
    module = importlib.import_module("pdbfixer")
    origin = getattr(module, "__file__", None)
    if not isinstance(origin, str):
        raise FileNotFoundError("PDBFixer package location is unavailable")
    return Path(origin).resolve().parent / "tests" / "data" / "1BHL.pdb"


def validate_matrix_contract(repository_root: Path) -> None:
    if len(SUPPORTED_ADAPTER_IDS) != len(set(SUPPORTED_ADAPTER_IDS)):
        raise ValueError("native-tool smoke adapter identifiers must be unique")
    required = {
        "python_scientific_runtime",
        "pdbfixer_repair",
        "pdb2pqr_propka",
        "meeko_receptor",
        "meeko_ligand",
        "p2rank",
        "vina",
        "autogrid4",
        "autodock4_cpu",
        "autodock_gpu",
    }
    if set(SUPPORTED_ADAPTER_IDS) != required:
        raise ValueError("native-tool smoke matrix does not match the supported adapters")
    if "gnina" not in DEFERRED_TOOLS:
        raise ValueError("the deliberately deferred GNINA scope must remain explicit")
    fixtures = (
        repository_root / "backend" / "tests" / "fixtures" / "synthetic_m1.pdb",
        repository_root
        / "backend"
        / "tests"
        / "fixtures"
        / "synthetic_ethanol.smi",
    )
    missing = [str(path) for path in fixtures if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"native-tool smoke fixture missing: {', '.join(missing)}")


def run_native_tool_smoke(
    *, repository_root: Path, output_root: Path, receptor_fixture: Path | None = None
) -> tuple[Path, str, list[AdapterResult]]:
    validate_matrix_contract(repository_root)
    writer = EvidenceWriter(output_root)
    results: list[AdapterResult] = []

    runtime = AdapterResult(
        adapter_id="python_scientific_runtime",
        adapter="locked Python scientific imports",
        scope="Import every Python scientific dependency used by native adapters.",
    )
    results.append(runtime)
    writer.adapter_directory(runtime.adapter_id)

    def run_runtime() -> None:
        execution = run_tool(
            executable=sys.executable,
            arguments=["-m", __name__, "--package-probe"],
            cwd=repository_root,
            stage="native_tool_smoke",
            timeout_seconds=120,
        )
        writer.execution(result=runtime, execution=execution)
        _require_success(execution)
        versions = json.loads(execution.stdout)
        if not isinstance(versions, dict) or set(versions) != set(PACKAGE_IMPORTS):
            raise ValueError("scientific package probe returned an incomplete version map")
        runtime.version = "; ".join(
            f"{name} {versions[name]}" for name in sorted(versions)
        )

    _run_adapter(writer, runtime, run_runtime)

    pdbfixer = AdapterResult(
        adapter_id="pdbfixer_repair",
        adapter="run_pdbfixer",
        scope="Repair one explicitly reported missing atom in a synthetic receptor.",
    )
    results.append(pdbfixer)
    pdbfixer_dir = writer.adapter_directory(pdbfixer.adapter_id)

    def run_pdbfixer_smoke() -> None:
        fixture = _copy_fixture(
            repository_root / "backend" / "tests" / "fixtures" / "synthetic_m1.pdb",
            pdbfixer_dir / "synthetic_m1.pdb",
        )
        pdbfixer.fixtures.append(writer.file(path=fixture, role="synthetic_receptor"))
        output = pdbfixer_dir / "repaired.pdb"
        execution, version = run_pdbfixer(
            input_path=fixture,
            output_path=output,
            residues=[
                ResidueLocator(
                    chain_id="A",
                    residue_name="ALA",
                    sequence_number=1,
                    insertion_code="",
                )
            ],
        )
        writer.execution(result=pdbfixer, execution=execution)
        pdbfixer.version = version
        _require_success(execution, output)
        _outputs(writer, pdbfixer, pdbfixer_dir, excluded={fixture})

    _run_adapter(writer, pdbfixer, run_pdbfixer_smoke)

    source_receptor: Path | None = None
    source_receptor_error: str | None = None
    try:
        source_receptor = (receptor_fixture or _default_receptor_fixture()).resolve()
        if not source_receptor.is_file():
            raise FileNotFoundError(source_receptor)
    except Exception as error:
        source_receptor_error = f"{type(error).__name__}: {error}"
    pdb2pqr = AdapterResult(
        adapter_id="pdb2pqr_propka",
        adapter="run_pdb2pqr_propka",
        scope="Protonate the fixed upstream PDBFixer receptor fixture at pH 7.4.",
    )
    results.append(pdb2pqr)
    pdb2pqr_dir = writer.adapter_directory(pdb2pqr.adapter_id)
    generated_pqr = pdb2pqr_dir / "protonated_receptor.pqr"

    def run_pdb2pqr_smoke() -> None:
        if source_receptor is None:
            raise RuntimeError(
                f"fixed receptor fixture is unavailable: {source_receptor_error}"
            )
        fixture = _copy_fixture(source_receptor, pdb2pqr_dir / "source_receptor.pdb")
        pdb2pqr.fixtures.append(writer.file(path=fixture, role="upstream_receptor"))
        execution, version, _report = run_pdb2pqr_propka(
            input_path=fixture,
            pqr_output_path=generated_pqr,
            pdb_output_path=pdb2pqr_dir / "protonated_receptor.pdb",
            ph=7.4,
            force_field="AMBER",
        )
        writer.execution(result=pdb2pqr, execution=execution)
        pdb2pqr.version = version
        _require_success(execution, generated_pqr)
        _outputs(writer, pdb2pqr, pdb2pqr_dir, excluded={fixture})

    _run_adapter(writer, pdb2pqr, run_pdb2pqr_smoke)

    meeko_receptor = AdapterResult(
        adapter_id="meeko_receptor",
        adapter="run_meeko_receptor",
        scope="Convert the generated PQR while explicitly preserving its charges.",
    )
    results.append(meeko_receptor)
    meeko_receptor_dir = writer.adapter_directory(meeko_receptor.adapter_id)

    def run_meeko_receptor_smoke() -> None:
        if pdb2pqr.status != "passed":
            raise RuntimeError("PDB2PQR/PROPKA prerequisite did not pass")
        fixture = _copy_fixture(generated_pqr, meeko_receptor_dir / "protonated_receptor.pqr")
        meeko_receptor.fixtures.append(writer.file(path=fixture, role="generated_pqr"))
        output = meeko_receptor_dir / "prepared_receptor.pdbqt"
        execution, version = run_meeko_receptor(
            input_pqr_path=fixture, output_pdbqt_path=output
        )
        writer.execution(result=meeko_receptor, execution=execution)
        meeko_receptor.version = version
        _require_success(execution, output)
        _outputs(writer, meeko_receptor, meeko_receptor_dir, excluded={fixture})

    _run_adapter(writer, meeko_receptor, run_meeko_receptor_smoke)

    meeko_ligand = AdapterResult(
        adapter_id="meeko_ligand",
        adapter="execute_meeko_ligand",
        scope="Prepare a fixed 3D ligand fixture with explicit Gasteiger charges.",
    )
    results.append(meeko_ligand)
    meeko_ligand_dir = writer.adapter_directory(meeko_ligand.adapter_id)

    def run_meeko_ligand_smoke() -> None:
        source = _copy_fixture(
            repository_root
            / "backend"
            / "tests"
            / "fixtures"
            / "synthetic_ethanol.smi",
            meeko_ligand_dir / "synthetic_ethanol.smi",
        )
        meeko_ligand.fixtures.append(
            writer.file(path=source, role="synthetic_ligand_source")
        )
        store = LigandArtifactStore(meeko_ligand_dir / "conformer-store")
        ligand = import_local_ligand(
            content=source.read_bytes(), filename=source.name, store=store
        )
        conformer = generate_ligand_conformer(
            ligand_id=ligand.artifact.ligand_id,
            request=GenerateLigandConformerRequest(
                acknowledge_current_chemical_state=True,
                random_seed=20260908,
            ),
            store=store,
        )
        generated = store.conformer_content_path(
            ligand.artifact.ligand_id, conformer.artifact.conformer_id
        )
        fixture = _copy_fixture(generated, meeko_ligand_dir / "ligand.sdf")
        meeko_ligand.details = {
            "conformer_method": "ETKDGv3",
            "minimization": "MMFF94s",
            "random_seed": 20260908,
        }
        meeko_ligand.fixtures.append(
            writer.file(path=fixture, role="generated_minimized_3d_ligand")
        )
        output = meeko_ligand_dir / "ligand.pdbqt"
        execution, version = execute_meeko_ligand(
            input_sdf_path=fixture,
            output_pdbqt_path=output,
            charge_model=LigandChargeModel.GASTEIGER,
        )
        writer.execution(result=meeko_ligand, execution=execution)
        meeko_ligand.version = version
        _require_success(execution, output)
        meeko_ligand.outputs.append(writer.file(path=output, role="tool_output"))

    _run_adapter(writer, meeko_ligand, run_meeko_ligand_smoke)

    p2rank = AdapterResult(
        adapter_id="p2rank",
        adapter="execute_p2rank",
        scope="Run bounded pocket prediction on the fixed upstream receptor fixture.",
    )
    results.append(p2rank)
    p2rank_dir = writer.adapter_directory(p2rank.adapter_id)

    def run_p2rank_smoke() -> None:
        if source_receptor is None:
            raise RuntimeError(
                f"fixed receptor fixture is unavailable: {source_receptor_error}"
            )
        fixture = _copy_fixture(source_receptor, p2rank_dir / "source_receptor.pdb")
        p2rank.fixtures.append(writer.file(path=fixture, role="upstream_receptor"))
        java_home = discover_java_home(os.getenv("JAVA_HOME"))
        if java_home is None:
            raise RuntimeError("compatible Java runtime was not found")
        java_execution = run_tool(
            executable=str(java_home / "bin" / "java.exe"),
            arguments=["-version"],
            cwd=p2rank_dir,
            stage="native_tool_smoke",
            timeout_seconds=30,
        )
        writer.execution(result=p2rank, execution=java_execution, sequence=1)
        _require_success(java_execution)
        output = p2rank_dir / "prediction"
        output.mkdir()
        execution, version = execute_p2rank(
            receptor_pdb_path=fixture, output_dir=output
        )
        writer.execution(result=p2rank, execution=execution, sequence=2)
        p2rank.version = version
        p2rank.details = {"java_version_output": java_execution.stderr.strip()}
        _require_success(execution)
        if not any(output.rglob("*_predictions.csv")):
            raise RuntimeError("P2Rank created no structured predictions CSV")
        _outputs(writer, p2rank, p2rank_dir, excluded={fixture})

    _run_adapter(writer, p2rank, run_p2rank_smoke)

    def engine_result(adapter_id: str, adapter: str, scope: str) -> AdapterResult:
        result = AdapterResult(adapter_id=adapter_id, adapter=adapter, scope=scope)
        results.append(result)
        writer.adapter_directory(adapter_id)
        return result

    vina = engine_result(
        "vina", "probe_vina", "Verify the exact Vina build; no docking is started."
    )

    def run_vina_smoke() -> None:
        installation = probe_vina()
        execution = run_tool(
            executable=installation.executable,
            arguments=["--version"],
            cwd=Path(installation.executable).parent,
            stage="native_tool_smoke",
            timeout_seconds=30,
        )
        writer.execution(result=vina, execution=execution)
        vina.version = installation.version
        vina.executable_sha256 = _sha256(Path(installation.executable))
        _require_success(execution)

    _run_adapter(writer, vina, run_vina_smoke)

    autogrid = engine_result(
        "autogrid4",
        "probe_autogrid4",
        "Verify the exact AutoGrid4 build and compiled limits; no maps are generated.",
    )

    def run_autogrid_smoke() -> None:
        installation = probe_autogrid4()
        execution = run_tool(
            executable=installation.executable,
            arguments=["--version"],
            cwd=Path(installation.executable).parent,
            stage="native_tool_smoke",
            timeout_seconds=30,
        )
        writer.execution(result=autogrid, execution=execution)
        autogrid.version = installation.version
        autogrid.executable_sha256 = installation.sha256
        autogrid.details = {
            "architecture": installation.architecture,
            "max_grid_points": installation.max_grid_points,
            "max_ligand_types": installation.max_ligand_types,
            "max_maps": installation.max_maps,
            "max_receptor_types": installation.max_receptor_types,
        }
        _require_success(execution)

    _run_adapter(writer, autogrid, run_autogrid_smoke)

    autodock4 = engine_result(
        "autodock4_cpu",
        "probe_autodock4",
        "Verify the exact AutoDock4 CPU build and compiled limits; no docking is started.",
    )

    def run_autodock4_smoke() -> None:
        installation = probe_autodock4()
        execution = run_tool(
            executable=installation.executable,
            arguments=["-v"],
            cwd=Path(installation.executable).parent,
            stage="native_tool_smoke",
            timeout_seconds=30,
        )
        writer.execution(result=autodock4, execution=execution)
        autodock4.version = installation.version
        autodock4.executable_sha256 = installation.sha256
        autodock4.details = {
            "architecture": installation.architecture,
            "max_atoms": installation.max_atoms,
            "max_maps": installation.max_maps,
            "max_torsions": installation.max_torsions,
        }
        _require_success(execution)

    _run_adapter(writer, autodock4, run_autodock4_smoke)

    autodock_gpu = engine_result(
        "autodock_gpu",
        "probe_autodock_gpu",
        "Verify build and selected OpenCL device with deliberately missing inputs.",
    )

    def run_autodock_gpu_smoke() -> None:
        installation = probe_autodock_gpu(device_number=1)
        help_execution = run_tool(
            executable=installation.executable,
            arguments=["--help"],
            cwd=Path(installation.executable).parent,
            stage="native_tool_smoke",
            timeout_seconds=30,
        )
        writer.execution(result=autodock_gpu, execution=help_execution, sequence=1)
        device_execution = run_tool(
            executable=installation.executable,
            arguments=[
                "--ffile",
                "ankora-device-probe.fld",
                "--lfile",
                "ankora-device-probe.pdbqt",
                "--devnum",
                "1",
                "--nrun",
                "1",
            ],
            cwd=Path(installation.executable).parent,
            stage="native_tool_smoke",
            timeout_seconds=120,
        )
        writer.execution(result=autodock_gpu, execution=device_execution, sequence=2)
        autodock_gpu.version = installation.version
        autodock_gpu.executable_sha256 = installation.sha256
        autodock_gpu.details = {
            "architecture": installation.architecture,
            "build": installation.build,
            "device_name": installation.device_name,
        }
        _require_success(help_execution)
        if installation.device_name is None:
            raise RuntimeError("AutoDock-GPU selected no OpenCL device")

    _run_adapter(writer, autodock_gpu, run_autodock_gpu_smoke)

    manifest, digest = writer.finish(results)
    return manifest, digest, results


def _default_output_root(repository_root: Path) -> Path:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return (
        repository_root
        / ".ankora-data"
        / "validation"
        / "native-tool-smoke"
        / f"{stamp}-{uuid4().hex[:8]}"
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run Ankora's bounded Windows native-tool smoke matrix."
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[4],
        help="repository root",
    )
    parser.add_argument("--output", type=Path, help="create-only local evidence directory")
    parser.add_argument("--receptor-fixture", type=Path)
    parser.add_argument("--check", action="store_true", help="validate the matrix only")
    parser.add_argument("--package-probe", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.package_probe:
        print(json.dumps(_package_probe_payload(), sort_keys=True))
        return 0
    root = args.root.resolve()
    try:
        validate_matrix_contract(root)
        if args.check:
            print(
                f"Native-tool smoke matrix verified: {len(SUPPORTED_ADAPTER_IDS)} "
                "supported adapters; GNINA explicitly deferred."
            )
            return 0
        output = (args.output or _default_output_root(root)).resolve()
        manifest, digest, results = run_native_tool_smoke(
            repository_root=root,
            output_root=output,
            receptor_fixture=args.receptor_fixture,
        )
    except Exception as error:
        print(f"Native-tool smoke failed before manifest completion: {error}", file=sys.stderr)
        return 1
    passed = sum(result.status == "passed" for result in results)
    print(f"Native-tool smoke: {passed}/{len(results)} adapters passed.")
    print(f"Evidence: {manifest}")
    print(f"Manifest SHA-256: {digest}")
    for result in results:
        if result.status != "passed":
            print(f"  {result.adapter_id}: {result.error}", file=sys.stderr)
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
