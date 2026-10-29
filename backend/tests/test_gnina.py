"""GNINA engine contracts anchored to a real synthetic-ethanol CUDA run."""

from hashlib import sha256
from pathlib import Path

import pytest

from ankora_backend.adapters.engines import gnina
from ankora_backend.adapters.tools.discovery import DiscoveredTool
from ankora_backend.domain.errors import AnkoraDomainError
from ankora_backend.execution.subprocess_runner import ToolExecution
from ankora_backend.schemas.binding_sites import BindingBox
from ankora_backend.schemas.gnina import GninaDockingParameters

FIXTURE = (Path(__file__).parent / "fixtures" / "gnina_real_synthetic_ethanol.sdf").read_bytes()


def test_real_gnina_sdf_preserves_pose_order_scores_and_original_records() -> None:
    """Expected values are the actual 1.3.3 output, not invented scores."""
    assert (
        sha256(FIXTURE).hexdigest()
        == "6d2256abe89a9c1a73a5a080a697acae76c09b3a6bee19d0c846f4414d347b3f"
    )
    poses = gnina.parse_gnina_sdf(FIXTURE)

    assert [pose.mode for pose in poses] == [1, 2]
    assert [pose.minimized_affinity_kcal_mol for pose in poses] == [-2.48280, -1.06516]
    assert [pose.cnn_score for pose in poses] == [0.8966667056, 0.7800865173]
    assert [pose.cnn_affinity for pose in poses] == [3.0304546356, 2.8093159199]
    assert poses[0].cnn_vs == 2.7173078060
    assert poses[0].cnn_affinity_variance == 0.1869647652
    assert b"".join(pose.sdf for pose in poses) == FIXTURE


@pytest.mark.parametrize(
    "corrupted",
    [
        b"",
        FIXTURE.rsplit(b"$$$$", 1)[0],
        FIXTURE.replace(b"> <CNNscore>", b"> <missing>", 1),
        FIXTURE.replace(b"0.8966667056", b"nan", 1),
        FIXTURE.replace(
            b"> <CNNscore>\n0.8966667056\n", b"> <CNNscore>\n0.8966667056\n\n> <CNNscore>\n0.5\n", 1
        ),
        FIXTURE.replace(b"   17.0904", b"       nan", 1),
    ],
)
def test_malformed_incomplete_or_nonfinite_output_is_rejected(corrupted: bytes) -> None:
    with pytest.raises(AnkoraDomainError) as error:
        gnina.parse_gnina_sdf(corrupted)
    assert error.value.code == "GNINA_OUTPUT_INVALID"


def test_gnina_cannot_be_probed_on_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gnina, "_linux_host", lambda: False)
    monkeypatch.setattr(
        gnina, "discover_tool", lambda *_args, **_kw: pytest.fail("must not discover")
    )
    with pytest.raises(AnkoraDomainError) as error:
        gnina.probe_gnina()
    assert error.value.code == "GNINA_LINUX_ONLY"


def test_linux_probe_verifies_exact_version_and_hash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import hashlib

    header = bytearray(64)
    header[:4] = b"\x7fELF"
    header[4:7] = bytes((2, 1, 1))
    header[18:20] = (0x3E).to_bytes(2, "little")
    binary = tmp_path / "synthetic-gnina"
    binary.write_bytes(header)
    monkeypatch.setattr(gnina, "_linux_host", lambda: True)
    monkeypatch.setattr(
        gnina, "discover_tool", lambda *_args, **_kw: DiscoveredTool(True, str(binary))
    )
    monkeypatch.setattr(
        gnina,
        "run_tool",
        lambda **_kw: ToolExecution(
            command=[str(binary), "--version"],
            exit_code=0,
            stdout="gnina v1.3.3 master:6fe1ce2\n",
            stderr="",
        ),
    )
    found = gnina.probe_gnina()
    assert found.version == "1.3.3"
    assert found.sha256 == hashlib.sha256(header).hexdigest()
    assert found.architecture == "x86_64"


@pytest.mark.parametrize("compute", ["cpu", "cuda"])
def test_command_keeps_scores_and_compute_choice_explicit(tmp_path: Path, compute: str) -> None:
    parameters = GninaDockingParameters(compute=compute, cpu_threads=2, seed=20261029)
    box = BindingBox(
        center_x=11.634,
        center_y=22.47,
        center_z=5.8585,
        size_x=24.854,
        size_y=20.214,
        size_z=18.635,
    )
    args = gnina.build_gnina_arguments(
        receptor_path=tmp_path / "receptor.pdb",
        ligand_path=tmp_path / "ligand.sdf",
        output_path=tmp_path / "poses.sdf",
        box=box,
        parameters=parameters,
    )
    assert args[args.index("--cnn_scoring") + 1] == "rescore"
    assert args[args.index("--seed") + 1] == "20261029"
    assert ("--no_gpu" in args) == (compute == "cpu")
    assert ("--device" in args) == (compute == "cuda")
    assert parameters.cnn_model == "gnina_1_3_3_builtin_default"
    assert parameters.hydrogen_handling == "gnina_1_3_3_default"


def test_command_rejects_nonfinite_box_and_overwriting_input(tmp_path: Path) -> None:
    parameters = GninaDockingParameters(compute="cuda")
    box = BindingBox(center_x=float("nan"), center_y=0, center_z=0, size_x=20, size_y=20, size_z=20)
    with pytest.raises(AnkoraDomainError) as error:
        gnina.build_gnina_arguments(
            receptor_path=tmp_path / "rec.pdb",
            ligand_path=tmp_path / "lig.sdf",
            output_path=tmp_path / "poses.sdf",
            box=box,
            parameters=parameters,
        )
    assert error.value.code == "GNINA_INPUT_INVALID"
    box.center_x = 0
    with pytest.raises(AnkoraDomainError) as error:
        gnina.build_gnina_arguments(
            receptor_path=tmp_path / "rec.pdb",
            ligand_path=tmp_path / "lig.sdf",
            output_path=tmp_path / "lig.sdf",
            box=box,
            parameters=parameters,
        )
    assert error.value.code == "GNINA_INPUT_INVALID"
