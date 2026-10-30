from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from ankora_backend.adapters.tools import pocket_detection
from ankora_backend.domain.errors import AnkoraDomainError
from ankora_backend.execution.subprocess_runner import ToolExecution
from ankora_backend.validation import native_tool_smoke
from ankora_backend.validation.native_tool_smoke import (
    DEFERRED_TOOLS,
    SUPPORTED_ADAPTER_IDS,
    AdapterResult,
    EvidenceWriter,
    _run_adapter,
    _run_p2rank_smoke,
    record_p2rank_execution,
    record_p2rank_java_probe,
    validate_matrix_contract,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def test_native_tool_smoke_matrix_covers_every_supported_process_adapter() -> None:
    validate_matrix_contract(REPOSITORY_ROOT)

    assert SUPPORTED_ADAPTER_IDS == (
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
    assert "gnina" in DEFERRED_TOOLS


# Exact synthetic bytes, written without newline translation so the identity is
# the same on every host. The CRLF digest is the historical Windows expectation.
SYNTHETIC_FIXTURES = {
    "fixture-lf.txt": b"explicitly synthetic fixture\n",
    "fixture-crlf.txt": b"explicitly synthetic fixture\r\n",
}
HISTORICAL_CRLF_SHA256 = "d853489ab6b76afcf17ccf3963f0d055a52ad9409d735d57f9d98fb13ce4a2ce"


def test_evidence_writer_preserves_raw_output_commands_and_fixture_hashes(
    tmp_path: Path,
) -> None:
    writer = EvidenceWriter(tmp_path / "evidence")
    directory = writer.adapter_directory("synthetic_adapter")
    result = AdapterResult(
        adapter_id="synthetic_adapter",
        adapter="synthetic adapter",
        scope="Contract test only.",
        status="passed",
        version="1.0",
    )
    for name, content in SYNTHETIC_FIXTURES.items():
        fixture = directory / name
        fixture.write_bytes(content)
        result.fixtures.append(writer.file(path=fixture, role="synthetic_fixture"))
    writer.execution(
        result=result,
        execution=ToolExecution(
            command=["synthetic-tool", "--version"],
            exit_code=0,
            stdout="synthetic stdout\n",
            stderr="synthetic stderr\n",
        ),
    )

    manifest_path, digest = writer.finish([result])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert len(digest) == 64
    assert manifest["results"][0]["executions"][0]["command"] == [
        "synthetic-tool",
        "--version",
    ]
    fixtures = {Path(item["path"]).name: item for item in manifest["results"][0]["fixtures"]}
    for name, content in SYNTHETIC_FIXTURES.items():
        assert fixtures[name]["sha256"] == hashlib.sha256(content).hexdigest()
        assert fixtures[name]["size_bytes"] == len(content)
        assert (directory / name).read_bytes() == content
    assert fixtures["fixture-crlf.txt"]["sha256"] == HISTORICAL_CRLF_SHA256
    assert fixtures["fixture-lf.txt"]["sha256"] != HISTORICAL_CRLF_SHA256
    assert (directory / "execution.stdout.txt").read_bytes() == b"synthetic stdout\n"
    assert (directory / "execution.stderr.txt").read_bytes() == b"synthetic stderr\n"


def test_package_probe_worker_names_this_module_even_when_run_as_main(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert native_tool_smoke.__spec__ is not None
    assert native_tool_smoke.__spec__.name == native_tool_smoke.MODULE_NAME
    monkeypatch.setattr(native_tool_smoke, "__name__", "__main__")

    assert native_tool_smoke.package_probe_arguments() == [
        "-m",
        "ankora_backend.validation.native_tool_smoke",
        "--package-probe",
    ]


def test_java_probe_uses_the_adapter_host_rules() -> None:
    assert native_tool_smoke.java_executable is pocket_detection.java_executable


def test_evidence_writer_refuses_to_overwrite_an_existing_run(tmp_path: Path) -> None:
    output = tmp_path / "existing"
    output.mkdir()

    with pytest.raises(FileExistsError, match="create-only"):
        EvidenceWriter(output)


@pytest.mark.parametrize("use_cmd_wrapper", [False, True])
def test_p2rank_smoke_records_actual_launcher_hash_and_separate_java_hash(
    tmp_path: Path,
    use_cmd_wrapper: bool,
) -> None:
    # Explicitly synthetic executable fixtures with distinct byte contents.
    java_bytes = b"explicitly synthetic java executable\n"
    prank_bytes = b"explicitly synthetic p2rank launcher\n"
    java_path = tmp_path / "synthetic-java"
    prank_path = tmp_path / ("synthetic-prank.bat" if use_cmd_wrapper else "synthetic-prank")
    java_path.write_bytes(java_bytes)
    prank_path.write_bytes(prank_bytes)
    expected_java_sha256 = hashlib.sha256(java_bytes).hexdigest()
    expected_prank_sha256 = hashlib.sha256(prank_bytes).hexdigest()
    assert expected_java_sha256 != expected_prank_sha256

    writer = EvidenceWriter(tmp_path / "evidence")
    directory = writer.adapter_directory("p2rank")
    result = AdapterResult(
        adapter_id="p2rank",
        adapter="execute_p2rank",
        scope="Synthetic P2Rank executable identity test.",
        status="passed",
    )
    java_command = [str(java_path), "-version"]
    p2rank_args = [
        "predict",
        "-f",
        "source_receptor.pdb",
        "-o",
        "prediction",
        "-visualizations",
        "0",
    ]
    p2rank_command = (
        ["cmd", "/c", str(prank_path), *p2rank_args]
        if use_cmd_wrapper
        else [str(prank_path), *p2rank_args]
    )
    java_execution = ToolExecution(
        command=java_command,
        exit_code=0,
        stdout="",
        stderr='openjdk version "21.0.12" 2026-07-15\n',
    )
    p2rank_execution = ToolExecution(
        command=p2rank_command,
        exit_code=0,
        stdout="synthetic p2rank stdout\n",
        stderr="synthetic p2rank stderr\n",
    )

    record_p2rank_java_probe(writer, result, java_execution)
    record_p2rank_execution(writer, result, p2rank_execution, version="2.5.1")
    manifest_path, _ = writer.finish([result])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    recorded = manifest["results"][0]

    assert recorded["executable_sha256"] == expected_prank_sha256
    assert recorded["executable_sha256"] != expected_java_sha256
    assert recorded["version"] == "2.5.1"
    assert recorded["details"] == {
        "java_executable_sha256": expected_java_sha256,
        "java_version_output": 'openjdk version "21.0.12" 2026-07-15',
    }
    assert len(recorded["executions"]) == 2
    assert recorded["executions"][0]["command"] == java_command
    assert recorded["executions"][1]["command"] == p2rank_command
    assert recorded["executions"][0]["stdout_path"] == "p2rank/execution-1.stdout.txt"
    assert recorded["executions"][0]["stderr_path"] == "p2rank/execution-1.stderr.txt"
    assert recorded["executions"][1]["stdout_path"] == "p2rank/execution-2.stdout.txt"
    assert recorded["executions"][1]["stderr_path"] == "p2rank/execution-2.stderr.txt"
    assert (directory / "execution-1.stdout.txt").read_bytes() == b""
    assert (
        directory / "execution-1.stderr.txt"
    ).read_bytes() == b'openjdk version "21.0.12" 2026-07-15\n'
    assert (directory / "execution-2.stdout.txt").read_bytes() == b"synthetic p2rank stdout\n"
    assert (directory / "execution-2.stderr.txt").read_bytes() == b"synthetic p2rank stderr\n"
    assert recorded["executions"][0]["stdout_sha256"] == hashlib.sha256(b"").hexdigest()
    assert (
        recorded["executions"][0]["stderr_sha256"]
        == hashlib.sha256(b'openjdk version "21.0.12" 2026-07-15\n').hexdigest()
    )
    assert (
        recorded["executions"][1]["stdout_sha256"]
        == hashlib.sha256(b"synthetic p2rank stdout\n").hexdigest()
    )
    assert (
        recorded["executions"][1]["stderr_sha256"]
        == hashlib.sha256(b"synthetic p2rank stderr\n").hexdigest()
    )


def test_p2rank_smoke_nonzero_java_exit_preserves_java_evidence_without_setting_adapter_hash(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Explicitly synthetic fixtures simulating a nonzero `java -version` exit.
    java_bytes = b"explicitly synthetic java executable\n"
    java_path = tmp_path / "synthetic-java"
    java_path.write_bytes(java_bytes)
    expected_java_sha256 = hashlib.sha256(java_bytes).hexdigest()
    source_receptor = tmp_path / "synthetic_receptor.pdb"
    source_receptor.write_bytes(b"HEADER SYNTHETIC RECEPTOR FIXTURE\nEND\n")

    java_command = [str(java_path), "-version"]
    monkeypatch.setattr(native_tool_smoke, "discover_java_home", lambda _: tmp_path)
    monkeypatch.setattr(native_tool_smoke, "java_executable", lambda _: java_path)
    monkeypatch.setattr(
        native_tool_smoke,
        "run_tool",
        lambda **_: ToolExecution(
            command=java_command,
            exit_code=1,
            stdout="synthetic java failure stdout\n",
            stderr="synthetic java failure stderr\n",
        ),
    )
    p2rank_called = False

    def fail_if_called(**_: object) -> tuple[ToolExecution, str]:
        nonlocal p2rank_called
        p2rank_called = True
        raise AssertionError("execute_p2rank must not run when java -version fails")

    monkeypatch.setattr(native_tool_smoke, "execute_p2rank", fail_if_called)

    writer = EvidenceWriter(tmp_path / "evidence")
    directory = writer.adapter_directory("p2rank")
    result = AdapterResult(
        adapter_id="p2rank",
        adapter="execute_p2rank",
        scope="Synthetic nonzero Java exit test.",
    )
    _run_adapter(
        writer,
        result,
        lambda: _run_p2rank_smoke(
            writer,
            result,
            directory,
            source_receptor=source_receptor,
        ),
    )
    manifest_path, _ = writer.finish([result])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    recorded = manifest["results"][0]

    assert not p2rank_called
    assert recorded["status"] == "failed"
    assert recorded["error"] == "RuntimeError: tool exited with code 1"
    assert recorded["executable_sha256"] is None
    assert recorded["details"] == {
        "java_executable_sha256": expected_java_sha256,
        "java_version_output": "synthetic java failure stderr",
    }
    assert len(recorded["executions"]) == 1
    assert recorded["executions"][0]["command"] == java_command
    assert recorded["executions"][0]["exit_code"] == 1
    assert (
        directory / "execution-1.stdout.txt"
    ).read_bytes() == b"synthetic java failure stdout\n"
    assert (
        directory / "execution-1.stderr.txt"
    ).read_bytes() == b"synthetic java failure stderr\n"


@pytest.mark.parametrize(
    "failure_mode",
    [
        "domain_launch_error",
        "domain_timeout_error",
        "domain_exit_code_error",
        "nonzero_exit",
    ],
)
def test_p2rank_smoke_failed_p2rank_paths_retain_java_and_adapter_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure_mode: str,
) -> None:
    # Explicitly synthetic fixtures simulating P2Rank launch/execution failures
    # after a passing `java -version` probe.
    java_bytes = b"explicitly synthetic java executable\n"
    prank_bytes = b"explicitly synthetic p2rank launcher\n"
    java_path = tmp_path / "synthetic-java"
    prank_path = tmp_path / "synthetic-prank"
    java_path.write_bytes(java_bytes)
    prank_path.write_bytes(prank_bytes)
    expected_java_sha256 = hashlib.sha256(java_bytes).hexdigest()
    expected_prank_sha256 = hashlib.sha256(prank_bytes).hexdigest()
    source_receptor = tmp_path / "synthetic_receptor.pdb"
    source_receptor.write_bytes(b"HEADER SYNTHETIC RECEPTOR FIXTURE\nEND\n")

    java_command = [str(java_path), "-version"]
    p2rank_command = [
        str(prank_path),
        "predict",
        "-f",
        "source_receptor.pdb",
        "-o",
        "prediction",
        "-visualizations",
        "0",
    ]
    monkeypatch.setattr(native_tool_smoke, "discover_java_home", lambda _: tmp_path)
    monkeypatch.setattr(native_tool_smoke, "java_executable", lambda _: java_path)
    monkeypatch.setattr(
        native_tool_smoke,
        "run_tool",
        lambda **_: ToolExecution(
            command=java_command,
            exit_code=0,
            stdout="",
            stderr='openjdk version "21.0.12" 2026-07-15\n',
        ),
    )

    def fake_execute_p2rank(**_: object) -> tuple[ToolExecution, str]:
        if failure_mode == "domain_launch_error":
            raise AnkoraDomainError(
                code="SCIENTIFIC_TOOL_LAUNCH_FAILED",
                stage="pocket_detection",
                message="Synthetic launch failure before process spawn.",
                status_code=500,
                details={"executable": str(prank_path)},
            )
        if failure_mode == "domain_timeout_error":
            # Exact real `run_tool` SCIENTIFIC_TOOL_TIMEOUT details shape (no `exit_code`).
            raise AnkoraDomainError(
                code="SCIENTIFIC_TOOL_TIMEOUT",
                stage="pocket_detection",
                message="Synthetic timeout during P2Rank execution.",
                status_code=504,
                details={
                    "command": p2rank_command,
                    "timeout_seconds": 900,
                    "stdout": "synthetic partial p2rank stdout\n",
                    "stderr": "synthetic partial p2rank stderr\n",
                },
            )
        if failure_mode == "domain_exit_code_error":
            raise AnkoraDomainError(
                code="SCIENTIFIC_TOOL_FAILED",
                stage="pocket_detection",
                message="Synthetic domain error with integer exit code.",
                status_code=500,
                details={
                    "command": p2rank_command,
                    "exit_code": 3,
                    "stdout": "synthetic domain exit stdout\n",
                    "stderr": "synthetic domain exit stderr\n",
                },
            )
        return (
            ToolExecution(
                command=p2rank_command,
                exit_code=2,
                stdout="synthetic p2rank failure stdout\n",
                stderr="synthetic p2rank failure stderr\n",
            ),
            "2.5.1",
        )

    monkeypatch.setattr(native_tool_smoke, "execute_p2rank", fake_execute_p2rank)

    writer = EvidenceWriter(tmp_path / "evidence")
    directory = writer.adapter_directory("p2rank")
    result = AdapterResult(
        adapter_id="p2rank",
        adapter="execute_p2rank",
        scope="Synthetic P2Rank failure evidence test.",
    )
    _run_adapter(
        writer,
        result,
        lambda: _run_p2rank_smoke(
            writer,
            result,
            directory,
            source_receptor=source_receptor,
        ),
    )
    manifest_path, _ = writer.finish([result])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    recorded = manifest["results"][0]

    assert recorded["status"] == "failed"
    assert recorded["details"] == {
        "java_executable_sha256": expected_java_sha256,
        "java_version_output": 'openjdk version "21.0.12" 2026-07-15',
    }
    assert recorded["executions"][0]["command"] == java_command
    assert recorded["executions"][0]["exit_code"] == 0
    assert (directory / "execution-1.stdout.txt").read_bytes() == b""
    assert (
        directory / "execution-1.stderr.txt"
    ).read_bytes() == b'openjdk version "21.0.12" 2026-07-15\n'

    if failure_mode == "domain_launch_error":
        assert recorded["executable_sha256"] is None
        assert len(recorded["executions"]) == 1
        assert not (directory / "execution.stdout.txt").exists()
        assert not (directory / "execution.stderr.txt").exists()
    elif failure_mode == "domain_timeout_error":
        assert recorded["executable_sha256"] == expected_prank_sha256
        assert len(recorded["executions"]) == 2
        assert recorded["executions"][1]["command"] == p2rank_command
        assert recorded["executions"][1]["exit_code"] is None
        assert (
            directory / "execution.stdout.txt"
        ).read_bytes() == b"synthetic partial p2rank stdout\n"
        assert (
            directory / "execution.stderr.txt"
        ).read_bytes() == b"synthetic partial p2rank stderr\n"
    elif failure_mode == "domain_exit_code_error":
        assert recorded["executable_sha256"] == expected_prank_sha256
        assert len(recorded["executions"]) == 2
        assert recorded["executions"][1]["command"] == p2rank_command
        assert recorded["executions"][1]["exit_code"] == 3
        assert (
            directory / "execution.stdout.txt"
        ).read_bytes() == b"synthetic domain exit stdout\n"
        assert (
            directory / "execution.stderr.txt"
        ).read_bytes() == b"synthetic domain exit stderr\n"
    else:
        assert recorded["executable_sha256"] == expected_prank_sha256
        assert recorded["version"] == "2.5.1"
        assert len(recorded["executions"]) == 2
        assert recorded["executions"][1]["command"] == p2rank_command
        assert recorded["executions"][1]["exit_code"] == 2
        assert (
            directory / "execution-2.stdout.txt"
        ).read_bytes() == b"synthetic p2rank failure stdout\n"
        assert (
            directory / "execution-2.stderr.txt"
        ).read_bytes() == b"synthetic p2rank failure stderr\n"
