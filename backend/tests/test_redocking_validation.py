"""Redocking validation (M7).

The fixtures are real: the crystallographic RV2 pose from 7AQF as Ankora
preserved it, and two poses AutoDock-GPU actually produced against it - the one
the engine ranked first, and the one that recovered the crystal.
"""

from pathlib import Path
from types import SimpleNamespace

import pytest

from ankora_backend.adapters.chemistry.redocking_rmsd import (
    PoseRmsd,
    autodock_type_to_element,
    in_place_rmsd,
    load_pose,
    load_reference,
    pdbqt_to_pdb_block,
)
from ankora_backend.domain.errors import AnkoraDomainError
from ankora_backend.schemas.provenance import ToolIdentity
from ankora_backend.schemas.redocking import RedockingOutcome, RedockingValidationRequest
from ankora_backend.services.redocking_validation import (
    RedockingValidationService,
    summarize,
)

FIXTURES = Path(__file__).parent / "fixtures"
CRYSTAL = FIXTURES / "redocking_7aqf_rv2_crystal.sdf"
TOP_RANKED = FIXTURES / "redocking_gpu_top_ranked_pose.pdbqt"
RECOVERING = FIXTURES / "redocking_gpu_recovering_pose.pdbqt"


def _pose(rank: int, rmsd: float, *, run: int = 1, energy: float = -5.0) -> PoseRmsd:
    return PoseRmsd(
        run=run, rank=rank, binding_energy_kcal_mol=energy, rmsd_angstrom=rmsd
    )


# --- the two traps, against real files ------------------------------------


def test_an_autodock_type_is_not_an_element() -> None:
    """`A` is aromatic carbon, `OA` an acceptor oxygen, `HD` a polar hydrogen.

    Handing these columns straight to a PDB parser fails, or worse invents
    elements and changes the molecular graph the RMSD is computed over.
    """
    assert autodock_type_to_element("A") == "C"
    assert autodock_type_to_element("OA") == "O"
    assert autodock_type_to_element("NA") == "N"
    assert autodock_type_to_element("HD") == "H"
    # Unknown is reported, never guessed.
    assert autodock_type_to_element("XX") is None


def test_an_unmappable_atom_type_is_refused_rather_than_guessed() -> None:
    line = (
        "ATOM      1  C   LIG A 401      10.000  10.000  10.000  0.00  0.00"
        "    +0.000 Xx"
    )

    with pytest.raises(AnkoraDomainError) as error:
        pdbqt_to_pdb_block(line)

    assert error.value.code == "REDOCKING_UNKNOWN_ATOM_TYPE"


def test_the_real_pose_parses_once_its_types_are_mapped() -> None:
    block = pdbqt_to_pdb_block(TOP_RANKED.read_text(encoding="utf-8"))

    reference = load_reference(CRYSTAL)
    # Hydrogens are dropped: crystallographic ones are usually inferred.
    assert "  H  " not in block
    assert len(block.splitlines()) == reference.GetNumAtoms()


def test_superimposing_would_pass_a_pose_that_is_in_the_wrong_place() -> None:
    """The reason this module only exposes an in-place RMSD.

    AutoDock-GPU's top-ranked pose sits about 10.7 A from the crystal. Aligned
    first, it measures under 1.5 A - a validator built on `GetBestRMS` would
    call a completely wrong binding mode a success.
    """
    from rdkit.Chem import rdMolAlign

    reference = load_reference(CRYSTAL)
    pose = load_pose(TOP_RANKED.read_text(encoding="utf-8"), reference)

    in_place = in_place_rmsd(pose, reference)
    superimposed = rdMolAlign.GetBestRMS(pose, reference)

    assert in_place > 10.0, "the top-ranked pose is far from the crystal"
    assert superimposed < 1.5, "and superimposing hides exactly that"


def test_the_recovering_pose_is_measured_close_to_the_crystal() -> None:
    reference = load_reference(CRYSTAL)
    pose = load_pose(RECOVERING.read_text(encoding="utf-8"), reference)

    rmsd = in_place_rmsd(pose, reference)

    # Real measurement, not a synthetic number: this pose recovers the crystal.
    assert 1.0 < rmsd < 1.6


def test_a_different_molecule_is_refused_rather_than_measured() -> None:
    """An RMSD between two different molecules is not a number worth having."""
    reference = load_reference(CRYSTAL)
    atoms = [
        line
        for line in TOP_RANKED.read_text(encoding="utf-8").splitlines()
        if line.startswith(("ATOM", "HETATM"))
    ]
    # Half a molecule is a different molecule.
    half = chr(10).join(atoms[: len(atoms) // 2])

    with pytest.raises(AnkoraDomainError) as error:
        load_pose(half, reference)

    assert error.value.code == "REDOCKING_POSE_NOT_THE_REFERENCE_MOLECULE"


# --- the two verdicts -----------------------------------------------------


def test_finding_the_pose_and_ranking_it_are_reported_separately() -> None:
    """On the project's own reference case these disagreed.

    AutoDock4 recovered 7AQF/RV2 to 0.490 A and then ranked a 3.139 A pose
    first. One pass/fail would have had to lie about one of them.
    """
    metrics, _ = summarize([_pose(1, 3.139), _pose(2, 0.490), _pose(3, 0.530)])

    assert metrics.sampling_success is True
    assert metrics.ranking_success is False
    assert metrics.outcome is RedockingOutcome.RECOVERED_BUT_MISRANKED


def test_a_top_pose_on_the_crystal_passes_both() -> None:
    metrics, _ = summarize([_pose(1, 0.8), _pose(2, 3.0)])

    assert metrics.sampling_success is True
    assert metrics.ranking_success is True
    assert metrics.outcome is RedockingOutcome.RECOVERED_AND_RANKED


def test_a_search_that_never_found_it_says_so() -> None:
    metrics, _ = summarize([_pose(1, 5.2), _pose(2, 4.8)])

    assert metrics.sampling_success is False
    assert metrics.ranking_success is False
    assert metrics.outcome is RedockingOutcome.NOT_RECOVERED
    assert metrics.first_recovering_rank is None


def test_how_far_down_the_scientist_would_have_had_to_look() -> None:
    metrics, _ = summarize([_pose(1, 6.0), _pose(2, 5.0), _pose(3, 1.2)])

    assert metrics.first_recovering_rank == 3
    assert metrics.recovered_pose_count == 1


def test_best_of_top_five_does_not_reach_past_the_fifth_pose() -> None:
    """It is the measure a scientist inspecting five poses would actually get."""
    poses = [_pose(rank, 4.0) for rank in range(1, 6)] + [_pose(6, 0.3)]

    metrics, _ = summarize(poses)

    assert metrics.best_top5_rmsd_angstrom == 4.0
    assert metrics.best_overall_rmsd_angstrom == 0.3


def test_the_threshold_is_stated_on_the_result_it_produced() -> None:
    strict, _ = summarize([_pose(1, 1.5)], threshold_angstrom=1.0)
    default, _ = summarize([_pose(1, 1.5)])

    assert strict.threshold_angstrom == 1.0
    assert strict.ranking_success is False
    assert default.threshold_angstrom == 2.0
    assert default.ranking_success is True


def test_ranking_is_judged_on_the_engines_own_order_not_on_rmsd() -> None:
    """Passing poses sorted by RMSD would make ranking_success meaningless."""
    metrics, poses = summarize([_pose(3, 0.4), _pose(1, 4.0), _pose(2, 0.6)])

    assert [pose.rank for pose in poses] == [1, 2, 3]
    assert metrics.top1_rmsd_angstrom == 4.0
    assert metrics.ranking_success is False


def test_a_result_with_no_poses_is_refused() -> None:
    with pytest.raises(AnkoraDomainError) as error:
        summarize([])

    assert error.value.code == "REDOCKING_NO_POSES"


def test_vina_modes_use_the_same_recorded_in_place_validation_path() -> None:
    """A real Vina pose is measured through M7, not by a validation-only script."""

    class CaptureStore:
        created = None

        def new_validation_id(self) -> str:
            return "vina-validation"

        def create(self, record: object) -> None:
            self.created = record

    class VinaStore:
        def load_record(self, source_id: str) -> SimpleNamespace:
            assert source_id == "vina-job"
            return SimpleNamespace(
                poses=[
                    SimpleNamespace(
                        mode=1,
                        affinity_kcal_mol=-7.1,
                        artifact=SimpleNamespace(filename="pose_1.pdbqt"),
                    )
                ],
                request=SimpleNamespace(
                    receptor_id="receptor", binding_site_id="binding-site"
                ),
                tool=ToolIdentity(name="AutoDock Vina", version="1.2.7"),
                warnings=[],
            )

        def output_path(self, source_id: str, filename: str) -> Path:
            assert (source_id, filename) == ("vina-job", "pose_1.pdbqt")
            return TOP_RANKED

    class LigandStore:
        def load_record(self, ligand_id: str) -> SimpleNamespace:
            assert ligand_id == "reference"
            return SimpleNamespace(artifact=SimpleNamespace(sha256="a" * 64))

        def content_path(self, ligand_id: str) -> Path:
            assert ligand_id == "reference"
            return CRYSTAL

    capture = CaptureStore()
    service = RedockingValidationService(
        store=capture,  # type: ignore[arg-type]
        ligand_store=LigandStore(),  # type: ignore[arg-type]
        docking_store=VinaStore(),  # type: ignore[arg-type]
        autodock4_store=SimpleNamespace(),  # type: ignore[arg-type]
        autodock_gpu_store=SimpleNamespace(),  # type: ignore[arg-type]
    )

    record = service.validate(
        RedockingValidationRequest(
            source_kind="vina_job",
            source_id="vina-job",
            reference_ligand_id="reference",
            reference_case="synthetic-service-routing",
        )
    )

    assert capture.created is record
    assert record.source_kind == "vina_job"
    assert record.engine == "AutoDock Vina"
    assert record.bitwise_reproducible is True
    assert record.poses[0].run == 1
    assert record.poses[0].binding_energy_kcal_mol == -7.1
    assert record.metrics.ranking_success is False
