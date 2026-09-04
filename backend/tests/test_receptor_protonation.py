from pathlib import Path

import pytest

from ankora_backend.adapters.tools.pdb2pqr_worker import _forced_pka
from ankora_backend.domain.errors import AnkoraDomainError
from ankora_backend.persistence.artifact_store import StructureArtifactStore
from ankora_backend.schemas.receptors import (
    ProtonationDecisionSource,
    ProtonationOverride,
    ResidueLocator,
)
from ankora_backend.schemas.structures import StructureSource
from ankora_backend.services.receptor_inspection import inspect_receptor
from ankora_backend.services.receptor_protonation import (
    build_protonation_analysis,
    validate_protonation_overrides,
)
from ankora_backend.services.structure_inspection import import_structure_bytes

FIXTURES = Path(__file__).parent / "fixtures"


def _synthetic_active_site(residue_name: str = "CYS") -> bytes:
    return (
        (FIXTURES / "synthetic_m1.pdb")
        .read_text()
        .replace("ALA A   1", f"{residue_name} A   1")
        .replace(
            "HETATM    9 ZN    ZN A 301       9.000   9.000   9.000",
            "HETATM    9 ZN    ZN A 301      11.104  13.207   8.100",
        )
        .encode()
    )


def _raw_prediction() -> dict[str, object]:
    return {
        "predictions": [
            {
                "res_num": 1,
                "ins_code": "",
                "res_name": "CYS",
                "chain_id": "A",
                "group_label": "CYS   1 A",
                "group_type": "CYS",
                "pKa": 8.0,
                "model_pKa": 3.8,
                "buried": 0.75,
                "coupled_group": "HIS   2 A",
            }
        ],
        "applied_overrides": [],
    }


def test_analysis_separates_propka_prediction_from_scientist_override(
    tmp_path: Path,
) -> None:
    store = StructureArtifactStore(tmp_path)
    content = _synthetic_active_site()
    source = import_structure_bytes(
        content=content,
        filename="synthetic_protonation_site.pdb",
        source=StructureSource.LOCAL,
        source_uri=None,
        store=store,
    )
    inspection = inspect_receptor(
        artifact_id=source.artifact.artifact_id,
        store=store,
        reference_component_id="ligand|A|LIG|101|",
    )
    input_path = tmp_path / "selected.pdb"
    input_path.write_bytes(content)
    override = ProtonationOverride(
        residue=ResidueLocator(
            chain_id="A", residue_name="CYS", sequence_number=1
        ),
        state="CYM",
    )

    analysis = build_protonation_analysis(
        source_artifact_id=source.artifact.artifact_id,
        input_path=input_path,
        inspection=inspection,
        structure_store=store,
        worker_report=_raw_prediction(),
        ph=7.4,
        force_field="AMBER",
        tool_version="pdb2pqr synthetic; propka synthetic",
        overrides=[override],
    )

    proposal = analysis.proposals[0]
    assert proposal.predicted_state == "CYS"
    assert proposal.default_state == "CYS"
    assert proposal.selected_state == "CYM"
    assert proposal.decision_source is ProtonationDecisionSource.SCIENTIST_OVERRIDE
    assert proposal.near_reference is True
    assert proposal.nearby_metals[0].name == "ZN"
    assert proposal.nearby_metals[0].distance_angstrom == pytest.approx(0.0)
    assert set(proposal.warnings) >= {
        "ACTIVE_SITE_REVIEW",
        "METAL_COORDINATION_REVIEW",
        "PKA_NEAR_TARGET_PH",
        "COUPLED_TITRATION_GROUP",
    }


def test_amber_rejects_a_terminal_acid_override_the_tool_cannot_apply(
    tmp_path: Path,
) -> None:
    input_path = tmp_path / "terminal_asp.pdb"
    input_path.write_bytes(_synthetic_active_site("ASP"))

    with pytest.raises(AnkoraDomainError) as captured:
        validate_protonation_overrides(
            input_path=input_path,
            force_field="AMBER",
            overrides=[
                ProtonationOverride(
                    residue=ResidueLocator(
                        chain_id="A", residue_name="ASP", sequence_number=1
                    ),
                    state="ASH",
                )
            ],
        )

    assert captured.value.code == "RECEPTOR_PROTONATION_DECISION_INVALID"


@pytest.mark.parametrize(
    ("residue_name", "state", "expected_relation"),
    [
        ("ASP", "ASH", "high"),
        ("ASP", "ASP", "low"),
        ("CYS", "CYM", "low"),
        ("HIS", "HIP", "high"),
        ("LYS", "LYN", "low"),
    ],
)
def test_worker_override_forces_the_pdb2pqr_titration_branch(
    residue_name: str, state: str, expected_relation: str
) -> None:
    ph = 7.4
    forced = _forced_pka(residue_name, state, ph)
    assert (forced > ph) is (expected_relation == "high")
