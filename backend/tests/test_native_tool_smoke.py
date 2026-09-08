from __future__ import annotations

import json
from pathlib import Path

import pytest

from ankora_backend.execution.subprocess_runner import ToolExecution
from ankora_backend.validation.native_tool_smoke import (
    DEFERRED_TOOLS,
    SUPPORTED_ADAPTER_IDS,
    AdapterResult,
    EvidenceWriter,
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


def test_evidence_writer_preserves_raw_output_commands_and_fixture_hashes(
    tmp_path: Path,
) -> None:
    writer = EvidenceWriter(tmp_path / "evidence")
    directory = writer.adapter_directory("synthetic_adapter")
    fixture = directory / "fixture.txt"
    fixture.write_text("explicitly synthetic fixture\n", encoding="utf-8")
    result = AdapterResult(
        adapter_id="synthetic_adapter",
        adapter="synthetic adapter",
        scope="Contract test only.",
        status="passed",
        version="1.0",
    )
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
    assert manifest["results"][0]["fixtures"][0]["sha256"] == (
        "d853489ab6b76afcf17ccf3963f0d055a52ad9409d735d57f9d98fb13ce4a2ce"
    )
    assert (directory / "execution.stdout.txt").read_text(encoding="utf-8") == (
        "synthetic stdout\n"
    )
    assert (directory / "execution.stderr.txt").read_text(encoding="utf-8") == (
        "synthetic stderr\n"
    )


def test_evidence_writer_refuses_to_overwrite_an_existing_run(tmp_path: Path) -> None:
    output = tmp_path / "existing"
    output.mkdir()

    with pytest.raises(FileExistsError, match="create-only"):
        EvidenceWriter(output)
