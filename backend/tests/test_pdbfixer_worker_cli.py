import subprocess
import sys
from pathlib import Path


def test_relax_without_relaxed_output_fails_via_argparse_not_an_assert(tmp_path: Path) -> None:
    """A bare `assert args.relaxed_output is not None` disappears under
    `python -O` and would otherwise let execution reach OpenMM with
    output_path=None. It must instead fail immediately through argparse's
    own usage-error path (exit code 2, clear stderr message), before ever
    importing PDBFixer/OpenMM or touching the input file."""
    input_path = tmp_path / "input.pdb"
    input_path.write_text("", encoding="utf-8")
    output_path = tmp_path / "output.pdb"

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "ankora_backend.adapters.tools.pdbfixer_worker",
            "--input",
            str(input_path),
            "--output",
            str(output_path),
            "--relax",
        ],
        capture_output=True,
        text=True,
        timeout=30,
        shell=False,
    )

    assert result.returncode == 2
    assert "--relaxed-output" in result.stderr
    assert not output_path.exists()
