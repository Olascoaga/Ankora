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
from ankora_backend.validation.screening_benchmark_ligand_preparation import (
    verify_ligand_preparation_manifest,
)
from ankora_backend.validation.screening_benchmark_protonation_previews import (
    verify_protonation_preview_manifest,
)
from ankora_backend.validation.screening_benchmark_templates import (
    verify_template_manifest,
)
from ankora_backend.validation.screening_benchmark_vina_plan import (
    verify_vina_campaign_plan,
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
RECEPTOR_PLAN_MANIFEST_PATH = SPEC_PATH.with_name(
    "LIT_PCBA_ANKORA_VS_V1.receptor-plans.json"
)
PROTONATION_PREVIEW_MANIFEST_PATH = SPEC_PATH.with_name(
    "LIT_PCBA_ANKORA_VS_V1.protonation-previews.json"
)
LIGAND_PREPARATION_PLAN_PATH = SPEC_PATH.with_name(
    "LIT_PCBA_ANKORA_VS_V1.ligand-preparation-plan.json"
)
LIGAND_PREPARATION_RESULT_PATH = SPEC_PATH.with_name(
    "LIT_PCBA_ANKORA_VS_V1.ligand-preparation.json"
)
VINA_CAMPAIGN_PLAN_PATH = SPEC_PATH.with_name(
    "LIT_PCBA_ANKORA_VS_V1.vina-primary-plan.json"
)


def test_frozen_protocol_matches_the_metric_implementation() -> None:
    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))

    assert spec["status"] == "primary_vina_campaign_plan_frozen_before_docking"
    assert spec["protonation_previews_executed_on"] == "2026-09-17"
    assert spec["ligand_preparation_completed_on"] == "2026-09-21"
    assert spec["ligand_preparation_verified_on"] == "2026-09-23"
    assert spec["vina_campaign_plan_frozen_on"] == "2026-09-23"
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
        "explicit_receptor_plans": {
            "path": RECEPTOR_PLAN_MANIFEST_PATH.name,
            "manifest_sha256": (
                "117bc6a50589b0f02c952584291598b5f3aeeaa29d54d127e63dc0bfb21fae55"
            ),
        },
        "protonation_previews": {
            "path": PROTONATION_PREVIEW_MANIFEST_PATH.name,
            "manifest_sha256": (
                "81d53765255308d761619f781fd37ef49e11fc343d9429a367ec620cd91927aa"
            ),
        },
        "final_receptors": {
            "path": "LIT_PCBA_ANKORA_VS_V1.final-receptors.json",
            "manifest_sha256": (
                "b617361c059c9c07b27010c34a3429a86eec355ecd6e27fe69172a7642a1636e"
            ),
        },
        "ligand_preparation_plan": {
            "path": LIGAND_PREPARATION_PLAN_PATH.name,
            "manifest_sha256": (
                "b6370eb32566e84ba569460f35efe5e89bdff12172609d92f203f51edd0d48e1"
            ),
        },
        "ligand_preparation_results": {
            "path": LIGAND_PREPARATION_RESULT_PATH.name,
            "manifest_sha256": (
                "d7704f66118820974a6c55a0a5fcc366ac33c5738db3af9672a77eadb74a3ab0"
            ),
        },
        "primary_vina_campaign_plan": {
            "path": VINA_CAMPAIGN_PLAN_PATH.name,
            "manifest_sha256": (
                "31862a168e737d2d6d81ab9ce5eba3b316eb31225318300237b140a99c020feb"
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


def test_explicit_receptor_plans_are_frozen_without_execution() -> None:
    manifest = json.loads(RECEPTOR_PLAN_MANIFEST_PATH.read_text(encoding="utf-8"))

    assert manifest["manifest_sha256"] == (
        "117bc6a50589b0f02c952584291598b5f3aeeaa29d54d127e63dc0bfb21fae55"
    )
    assert manifest["plan_census"] == {
        "target_count": 3,
        "template_plan_count": 6,
    }
    assert manifest["execution_boundary"]["status"] == (
        "plans_frozen_propka_reviews_not_yet_executed"
    )
    assert manifest["result_status"] == (
        "receptor_plans_frozen_no_protonation_preview_receptor_derivative_or_"
        "docking_result_executed"
    )
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
    assert all(
        template["preparation_request"]["selected_chains"] == ["A"]
        for template in templates
    )
    assert all(
        template["preparation_request"]["water_action"] == "remove"
        for template in templates
    )
    assert all(
        template["execution_gate"]
        == "structured_propka_preview_and_review_required"
        for template in templates
    )
    assert {
        decision["selected_altloc"]
        for template in templates
        for decision in template["preparation_request"]["issue_decisions"]
        if decision["selected_altloc"] is not None
    } == {"A"}
    assert {
        decision["component_id"]
        for template in templates
        for decision in template["preparation_request"]["component_decisions"]
        if decision["action"] == "keep"
    } == {"metal|A|ZN|313|", "metal|A|ZN|401|"}


def test_protonation_previews_are_frozen_without_final_receptors() -> None:
    manifest = verify_protonation_preview_manifest(PROTONATION_PREVIEW_MANIFEST_PATH)

    assert manifest["manifest_sha256"] == (
        "81d53765255308d761619f781fd37ef49e11fc343d9429a367ec620cd91927aa"
    )
    assert manifest["preview_census"] == {
        "requested": 6,
        "completed": 6,
        "failed": 0,
        "proposal_count": 449,
        "review_attention_count": 102,
    }
    assert manifest["scientist_review"]["status"] == "pending"
    assert manifest["scientist_review"]["accepted_default_proposals"] == []
    assert manifest["scientist_review"]["approved_overrides"] == []
    assert all(
        preview["final_receptor_created"] is False
        and preview["final_pdbqt_created"] is False
        for preview in manifest["previews"]
    )
    assert [preview["pdb_id"] for preview in manifest["previews"]] == [
        "5ufx",
        "2iog",
        "3b1m",
        "5y2t",
        "3zme",
        "5o1i",
    ]


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


def test_ligand_preparation_closes_every_parent_before_docking() -> None:
    manifest = verify_ligand_preparation_manifest(
        LIGAND_PREPARATION_RESULT_PATH,
        plan_manifest_path=LIGAND_PREPARATION_PLAN_PATH,
    )

    assert manifest["manifest_sha256"] == (
        "d7704f66118820974a6c55a0a5fcc366ac33c5738db3af9672a77eadb74a3ab0"
    )
    assert manifest["scores_seen"] is False
    assert manifest["execution_policy"]["docking_executed"] is False
    assert manifest["execution_policy"]["scores_or_metrics_computed"] is False
    assert manifest["preparation_census"] == {
        "requested": 11412,
        "terminal": 11412,
        "prepared": 11302,
        "unscored_worst_tie": 110,
        "by_status": {
            "preparation_failed": 3,
            "prepared": 11302,
            "unresolved_chemical_state": 107,
        },
    }
    active_entries = [
        entry for entry in manifest["entries"] if entry["class_label"] == "active"
    ]
    assert len(active_entries) == 176
    assert all(entry["status"] == "prepared" for entry in active_entries)


def test_primary_vina_campaign_is_frozen_before_any_score_is_seen() -> None:
    manifest = verify_vina_campaign_plan(VINA_CAMPAIGN_PLAN_PATH)

    assert manifest["manifest_sha256"] == (
        "31862a168e737d2d6d81ab9ce5eba3b316eb31225318300237b140a99c020feb"
    )
    assert manifest["scores_seen"] is False
    assert manifest["parameters"] == {
        "sampling_protocol": "screening",
        "total_cpu_threads": 15,
        "parallel_ligands": 15,
        "seed": 20260911,
        "exhaustiveness": 8,
        "num_modes": 9,
        "min_rmsd_angstrom": 1.0,
        "energy_range_kcal_mol": 3.0,
        "timeout_minutes_per_ligand": 360,
        "threads_per_ligand": 1,
    }
    assert manifest["totals"]["source_parents"] == 11412
    assert manifest["totals"]["prepared_for_docking"] == 11302
    assert manifest["totals"]["retained_unscored_worst_tie"] == 110
    assert manifest["execution_policy"]["docking_executed"] is False
    assert manifest["execution_policy"]["scores_or_metrics_computed"] is False
