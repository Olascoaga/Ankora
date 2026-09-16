"""Keep the public point-26 preregistration aligned with executable metrics."""

import hashlib
import json
from pathlib import Path

from ankora_backend.schemas.screening_benchmark import ScoreDirection
from ankora_backend.services.screening_benchmark import (
    BOOTSTRAP_METHOD,
    DEFAULT_BEDROC_ALPHA,
    DEFAULT_BOOTSTRAP_REPLICATES,
    DEFAULT_BOOTSTRAP_SEED,
    DEFAULT_CONFIDENCE_LEVEL,
    DEFAULT_TOP_FRACTION,
    FAILURE_POLICY,
    PERCENTILE_METHOD,
    PR_AUC_DEFINITION,
    TIE_POLICY,
)
from ankora_backend.validation.screening_benchmark_geometry import (
    SENTINELS_PER_CLASS_PER_TARGET,
)
from ankora_backend.validation.screening_benchmark_templates import (
    verify_template_manifest,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SPEC_PATH = (
    REPOSITORY_ROOT
    / "docs"
    / "validation"
    / "reference_cases"
    / "LIT_PCBA_ANKORA_VS_V1.spec.json"
)
INPUT_MANIFEST_PATH = SPEC_PATH.with_name("LIT_PCBA_ANKORA_VS_V1.inputs.json")
TEMPLATE_MANIFEST_PATH = SPEC_PATH.with_name("LIT_PCBA_ANKORA_VS_V1.templates.json")
GEOMETRY_MANIFEST_PATH = SPEC_PATH.with_name(
    "LIT_PCBA_ANKORA_VS_V1.geometry-sentinels.json"
)
STRUCTURE_MANIFEST_PATH = SPEC_PATH.with_name("LIT_PCBA_ANKORA_VS_V1.structures.json")


def test_frozen_protocol_matches_the_metric_implementation() -> None:
    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))

    assert spec["status"] == (
        "exact_source_templates_boxes_sentinels_and_official_structure_frames_"
        "frozen_before_results"
    )
    assert spec["result_status"] == "not_executed"
    assert spec["ranking"] == {
        "unit": "one canonical parent compound",
        "duplicate_key": (
            "RDKit canonical isomeric SMILES of the sanitized source graph without "
            "uncharging, tautomerization, or fragment removal"
        ),
        "primary_state_policy": "exact_imported_state",
        "score_direction": ScoreDirection.LOWER_IS_BETTER,
        "tie_policy": TIE_POLICY,
        "failure_policy": FAILURE_POLICY,
        "cross_engine_pooling": False,
    }
    assert spec["metrics"]["top_fraction"] == DEFAULT_TOP_FRACTION
    assert spec["metrics"]["bedroc_alpha"] == DEFAULT_BEDROC_ALPHA
    assert spec["metrics"]["pr_auc_definition"] == PR_AUC_DEFINITION
    assert spec["metrics"]["bootstrap"] == {
        "method": BOOTSTRAP_METHOD,
        "replicates": DEFAULT_BOOTSTRAP_REPLICATES,
        "confidence_level": DEFAULT_CONFIDENCE_LEVEL,
        "seed": DEFAULT_BOOTSTRAP_SEED,
        "percentile_method": PERCENTILE_METHOD,
    }


def test_frozen_source_and_pre_result_amendment_are_exactly_identified() -> None:
    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    evidence = spec["primary_evidence"]

    assert evidence["source_archive"] == {
        "filename": "LIT-PCBA_AVE_unbiased.tar.gz",
        "size_bytes": 57399933,
        "sha256": (
            "1f50ef6bf66b8e987f056a2d2528f1d5a9031ad542ddc97f8ee2fbfd651c8de3"
        ),
    }
    assert evidence["source_layout"] == {
        "active_files": ["active_T.smi", "active_V.smi"],
        "inactive_files": ["inactive_T.smi", "inactive_V.smi"],
    }

    [reference] = spec["amendments"]
    amendment_path = SPEC_PATH.parent / reference["path"]
    amendment_bytes = amendment_path.read_bytes()
    amendment = json.loads(amendment_bytes)
    assert hashlib.sha256(amendment_bytes).hexdigest() == reference["sha256"]
    assert amendment["amendment_id"] == reference["amendment_id"] == "001"
    assert amendment["protocol_id"] == spec["protocol_id"]
    assert amendment["invariants"]["scores_seen"] is False
    assert amendment["result_status"] == "pre_result_source_identity_correction"


def test_holo_template_selection_reproduces_offline_from_recorded_metadata() -> None:
    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    manifest = verify_template_manifest(
        input_manifest_path=INPUT_MANIFEST_PATH,
        template_manifest_path=TEMPLATE_MANIFEST_PATH,
    )

    assert spec["acquisition_manifests"] == {
        "source_population": {
            "path": INPUT_MANIFEST_PATH.name,
            "manifest_sha256": (
                "ebc5170e741939ef0e0b3e6c53129f15747cfdf0d54727746fc53c481372645b"
            ),
        },
        "holo_templates": {
            "path": TEMPLATE_MANIFEST_PATH.name,
            "manifest_sha256": manifest["manifest_sha256"],
        },
        "geometry_and_sentinels": {
            "path": GEOMETRY_MANIFEST_PATH.name,
            "manifest_sha256": (
                "fea2d678f492317d874492b7c21c5732a70cb0e056aead4c11b5f702aa7d57fb"
            ),
        },
        "official_structures_and_frames": {
            "path": STRUCTURE_MANIFEST_PATH.name,
            "manifest_sha256": (
                "d7bcac2269f70432ff4cd35f7288e07ca8d0f766ab23372558e3ac32b82e459f"
            ),
        },
    }
    assert [
        (
            target["target_id"],
            target["primary_template"]["pdb_id"],
            target["alternate_template"]["pdb_id"],
        )
        for target in manifest["targets"]
    ] == [
        ("ESR_antago", "5ufx", "2iog"),
        ("PPARG", "3b1m", "5y2t"),
        ("TP53", "3zme", "5o1i"),
    ]
    assert manifest["result_status"] == "templates_selected_no_docking_executed"


def test_box_and_sentinel_manifest_closes_without_results() -> None:
    manifest = json.loads(GEOMETRY_MANIFEST_PATH.read_text(encoding="utf-8"))

    assert manifest["manifest_sha256"] == (
        "fea2d678f492317d874492b7c21c5732a70cb0e056aead4c11b5f702aa7d57fb"
    )
    assert manifest["result_status"] == (
        "boxes_and_sentinels_frozen_no_docking_executed"
    )
    assert manifest["receptor_preparation_boundary"]["status"] == "not_yet_frozen"
    assert [target["primary_template_id"] for target in manifest["targets"]] == [
        "5ufx",
        "3b1m",
        "3zme",
    ]
    assert all(
        len(target["chemical_state_sentinels"][label])
        == SENTINELS_PER_CLASS_PER_TARGET
        for target in manifest["targets"]
        for label in ("active", "inactive")
    )


def test_official_structures_close_the_coordinate_frames_without_results() -> None:
    manifest = json.loads(STRUCTURE_MANIFEST_PATH.read_text(encoding="utf-8"))

    assert manifest["manifest_sha256"] == (
        "d7bcac2269f70432ff4cd35f7288e07ca8d0f766ab23372558e3ac32b82e459f"
    )
    assert manifest["result_status"] == (
        "official_structures_and_coordinate_frames_frozen_no_receptor_"
        "preparation_or_docking_executed"
    )
    assert manifest["receptor_preparation_boundary"]["status"] == "not_yet_executed"
    templates = [
        target[role]
        for target in manifest["targets"]
        for role in ("primary_template", "alternate_template")
    ]
    assert [template["pdb_id"] for template in templates] == [
        "5ufx",
        "2iog",
        "3b1m",
        "5y2t",
        "3zme",
        "5o1i",
    ]
    assert all(template["coordinate_frame_congruent"] is True for template in templates)
    assert all(
        template["source_ligand_frame_evidence"]["exact_match_fraction"] == 1.0
        for template in templates
    )
    assert all(
        template["source_receptor_frame_evidence"]["matched_author_chain_ids"]
        == ["A"]
        for template in templates
    )


def test_frozen_cohort_is_multi_target_and_its_source_census_closes() -> None:
    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))

    targets = spec["primary_evidence"]["targets"]
    assert [target["target_id"] for target in targets] == [
        "ESR_antago",
        "PPARG",
        "TP53",
    ]
    assert [target["source_directory"] for target in targets] == [
        "ESR1_ant",
        "PPARG",
        "TP53",
    ]
    assert len({target["pubchem_aid"] for target in targets}) == 3
    assert sum(target["reported_actives"] for target in targets) == 176
    assert sum(target["reported_inactives"] for target in targets) == 11236
    assert all(
        target["reported_actives"] + target["reported_inactives"] <= 5000
        for target in targets
    )
