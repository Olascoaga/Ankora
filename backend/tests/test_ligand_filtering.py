"""Synthetic contracts for explicit local library filtering."""

import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from ankora_backend.api.app import create_app
from ankora_backend.domain.errors import AnkoraDomainError
from ankora_backend.persistence.ligand_store import LigandArtifactStore
from ankora_backend.schemas.ligands import (
    ApplyLigandLibraryFilterRequest,
    LigandAlertPolicy,
    LigandCustomFilterRule,
    LigandCustomRuleDescriptor,
    LigandCustomRuleOperator,
    LigandLibraryFilterPlan,
    LigandLibraryFilterRequest,
    LigandLibraryRecord,
)
from ankora_backend.services.ligand_filtering import (
    apply_library_filters,
    preview_library_filters,
)
from ankora_backend.services.ligand_import import import_local_ligand_library

SYNTHETIC_LIBRARY = b"""CCO ethanol
CCCCCCCCCCCCCCCCCCCC eicosane
CCO ethanol_duplicate
O=C1NC(=S)SC1=Cc1ccccc1 synthetic_rhodanine
CCO.[Na+] unresolved_salt
"""


def _library(store: LigandArtifactStore) -> LigandLibraryRecord:
    return import_local_ligand_library(
        content=SYNTHETIC_LIBRARY,
        filename="synthetic_filter_library.smi",
        store=store,
    )


def test_default_filter_preview_is_explicit_and_row_scoped(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("ankora_backend.services.ligand_filtering.os.cpu_count", lambda: 4)
    store = LigandArtifactStore(tmp_path)
    library = _library(store)

    preview = preview_library_filters(
        library_id=library.artifact.library_id,
        request=LigandLibraryFilterRequest(),
        store=store,
    )

    assert preview.summary.imported_count == 5
    assert preview.summary.eligible_count == 2
    assert preview.summary.excluded_count == 2
    assert preview.summary.needs_decision_count == 1
    assert preview.summary.duplicate_count == 1
    assert preview.summary.pains_match_count == 1
    assert preview.worker_count == 3
    ethanol, eicosane, duplicate, rhodanine, salt = preview.evaluations
    assert ethanol.disposition == "eligible"
    assert ethanol.descriptors is not None
    assert ethanol.descriptors.molecular_weight_g_mol == pytest.approx(46.069, abs=0.001)
    assert 0 <= ethanol.descriptors.qed <= 1
    assert ethanol.lipinski is not None and ethanol.lipinski.passed
    assert ethanol.veber is not None and ethanol.veber.passed
    assert ethanol.ghose is not None and not ethanol.ghose.passed
    assert ethanol.muegge is not None and not ethanol.muegge.passed
    assert eicosane.disposition == "excluded"
    assert "VEBER_REQUIRED" in eicosane.reasons
    assert duplicate.duplicate_of_ligand_id == ethanol.ligand_id
    assert "DUPLICATE_EXCLUDED" in duplicate.reasons
    assert rhodanine.disposition == "eligible"
    assert "PAINS_REVIEW" in rhodanine.reasons
    assert any(alert.catalog == "PAINS" and alert.atom_indices for alert in rhodanine.alerts)
    assert salt.disposition == "needs_decision"
    assert salt.descriptors is None


def test_informative_rules_and_qed_become_gates_only_when_requested(
    tmp_path: Path,
) -> None:
    store = LigandArtifactStore(tmp_path)
    library = _library(store)

    preview = preview_library_filters(
        library_id=library.artifact.library_id,
        request=LigandLibraryFilterRequest(
            plan=LigandLibraryFilterPlan(
                require_ghose=True,
                require_muegge=True,
                minimum_qed=0.8,
            )
        ),
        store=store,
    )

    ethanol = preview.evaluations[0]
    assert ethanol.disposition == "excluded"
    assert {"GHOSE_REQUIRED", "MUEGGE_REQUIRED", "QED_BELOW_MINIMUM"}.issubset(
        ethanol.reasons
    )


def test_custom_rule_required_excludes_and_informative_records_without_excluding(
    tmp_path: Path,
) -> None:
    store = LigandArtifactStore(tmp_path)
    library = _library(store)

    baseline = preview_library_filters(
        library_id=library.artifact.library_id,
        request=LigandLibraryFilterRequest(),
        store=store,
    )
    ethanol = baseline.evaluations[0]
    assert ethanol.descriptors is not None
    mw = ethanol.descriptors.molecular_weight_g_mol

    preview = preview_library_filters(
        library_id=library.artifact.library_id,
        request=LigandLibraryFilterRequest(
            plan=LigandLibraryFilterPlan(
                require_veber=False,
                custom_rules=[
                    LigandCustomFilterRule(
                        rule_id="mw-too-heavy",
                        label="MW must exceed synthetic threshold",
                        descriptor=LigandCustomRuleDescriptor.MOLECULAR_WEIGHT,
                        operator=LigandCustomRuleOperator.GREATER_THAN,
                        value=mw + 1,
                        required=True,
                    ),
                    LigandCustomFilterRule(
                        rule_id="mw-informative",
                        label="Informative-only MW note",
                        descriptor=LigandCustomRuleDescriptor.MOLECULAR_WEIGHT,
                        operator=LigandCustomRuleOperator.GREATER_THAN,
                        value=mw + 1,
                        required=False,
                    ),
                ],
            )
        ),
        store=store,
    )

    ethanol_result = preview.evaluations[0]
    assert ethanol_result.disposition == "excluded"
    assert "CUSTOM_RULE_REQUIRED:mw-too-heavy" in ethanol_result.reasons
    assert not any(
        reason.startswith("CUSTOM_RULE_REQUIRED:mw-informative")
        for reason in ethanol_result.reasons
    )
    results_by_id = {result.rule_id: result for result in ethanol_result.custom_rule_results}
    assert results_by_id["mw-too-heavy"].passed is False
    assert results_by_id["mw-informative"].passed is False
    assert results_by_id["mw-informative"].required is False


def test_custom_rule_between_operator_passes_when_value_in_range(tmp_path: Path) -> None:
    store = LigandArtifactStore(tmp_path)
    library = _library(store)

    baseline = preview_library_filters(
        library_id=library.artifact.library_id,
        request=LigandLibraryFilterRequest(),
        store=store,
    )
    ethanol = baseline.evaluations[0]
    assert ethanol.descriptors is not None
    mw = ethanol.descriptors.molecular_weight_g_mol

    preview = preview_library_filters(
        library_id=library.artifact.library_id,
        request=LigandLibraryFilterRequest(
            plan=LigandLibraryFilterPlan(
                custom_rules=[
                    LigandCustomFilterRule(
                        rule_id="mw-range",
                        label="MW within synthetic range",
                        descriptor=LigandCustomRuleDescriptor.MOLECULAR_WEIGHT,
                        operator=LigandCustomRuleOperator.BETWEEN,
                        value=mw - 1,
                        value_upper=mw + 1,
                        required=True,
                    )
                ],
            )
        ),
        store=store,
    )

    ethanol_result = preview.evaluations[0]
    assert ethanol_result.disposition == "eligible"
    assert ethanol_result.custom_rule_results[0].passed is True


def test_custom_filter_rule_requires_value_upper_for_between_operator() -> None:
    with pytest.raises(ValidationError):
        LigandCustomFilterRule(
            rule_id="bad",
            label="bad",
            descriptor=LigandCustomRuleDescriptor.CLOGP,
            operator=LigandCustomRuleOperator.BETWEEN,
            value=1.0,
        )


def test_custom_filter_rule_rejects_value_upper_outside_between_operator() -> None:
    with pytest.raises(ValidationError):
        LigandCustomFilterRule(
            rule_id="bad",
            label="bad",
            descriptor=LigandCustomRuleDescriptor.CLOGP,
            operator=LigandCustomRuleOperator.LESS_THAN,
            value=1.0,
            value_upper=2.0,
        )


def test_recalculating_preview_with_a_new_plan_does_not_reparse_unchanged_states(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import ankora_backend.services.ligand_filtering as filtering_module

    monkeypatch.setattr(
        "ankora_backend.services.ligand_filtering.os.cpu_count", lambda: 1
    )
    store = LigandArtifactStore(tmp_path)
    library = _library(store)
    calls: list[tuple[str, str]] = []
    real_load = filtering_module._load_state_molecule

    def counting_load(store_arg: LigandArtifactStore, ligand_id: str, state_id: str) -> Any:
        calls.append((ligand_id, state_id))
        return real_load(store_arg, ligand_id, state_id)

    monkeypatch.setattr(filtering_module, "_load_state_molecule", counting_load)

    preview_library_filters(
        library_id=library.artifact.library_id,
        request=LigandLibraryFilterRequest(),
        store=store,
    )
    first_call_count = len(calls)
    assert first_call_count > 0

    preview_library_filters(
        library_id=library.artifact.library_id,
        request=LigandLibraryFilterRequest(
            plan=LigandLibraryFilterPlan(require_ghose=True, minimum_qed=0.5)
        ),
        store=store,
    )

    assert len(calls) == first_call_count


def test_descriptor_cache_does_not_collide_across_different_data_roots(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The descriptor cache used to be keyed only by (ligand_id, state_id).
    Those are per-store UUIDs, not globally unique across two different
    `ANKORA_DATA_DIR` roots served by the same process (e.g. two tests, or
    any future multi-project support) — force an identical id in two
    separate stores holding two different molecules, and confirm each
    store's own real content wins rather than whichever was cached first."""
    import ankora_backend.persistence.ligand_store as ligand_store_module
    import ankora_backend.services.ligand_filtering as filtering_module

    root_a = tmp_path / "root_a"
    root_b = tmp_path / "root_b"
    root_a.mkdir()
    root_b.mkdir()
    store_a = LigandArtifactStore(root_a)
    store_b = LigandArtifactStore(root_b)

    fixed_id = "11111111-1111-1111-1111-111111111111"
    monkeypatch.setattr(ligand_store_module, "uuid4", lambda: fixed_id)

    ligand_a = import_local_ligand_library(
        content=b"CCO ethanol\n", filename="a.smi", store=store_a
    )
    ligand_b = import_local_ligand_library(
        content=b"c1ccccc1 benzene\n", filename="b.smi", store=store_b
    )
    entry_a = ligand_a.entries[0].ligand
    entry_b = ligand_b.entries[0].ligand
    assert entry_a is not None and entry_b is not None
    assert entry_a.artifact.ligand_id == entry_b.artifact.ligand_id == fixed_id

    descriptors_a = filtering_module._cached_descriptors(
        store_a, entry_a.artifact.ligand_id, entry_a.state.state_id  # type: ignore[union-attr]
    )
    descriptors_b = filtering_module._cached_descriptors(
        store_b, entry_b.artifact.ligand_id, entry_b.state.state_id  # type: ignore[union-attr]
    )

    assert descriptors_a.canonical_isomeric_smiles != descriptors_b.canonical_isomeric_smiles
    assert descriptors_a.descriptors.molecular_weight_g_mol != pytest.approx(
        descriptors_b.descriptors.molecular_weight_g_mol
    )


def test_alert_policy_can_exclude_without_changing_source(tmp_path: Path) -> None:
    store = LigandArtifactStore(tmp_path)
    library = _library(store)
    source_before = store.library_content_path(library.artifact.library_id).read_bytes()

    preview = preview_library_filters(
        library_id=library.artifact.library_id,
        request=LigandLibraryFilterRequest(
            plan=LigandLibraryFilterPlan(pains_policy=LigandAlertPolicy.EXCLUDE)
        ),
        store=store,
    )

    rhodanine = preview.evaluations[3]
    assert rhodanine.disposition == "excluded"
    assert "PAINS_EXCLUDED" in rhodanine.reasons
    assert store.library_content_path(library.artifact.library_id).read_bytes() == source_before


def test_filter_application_requires_confirmation_and_persists_manifest(
    tmp_path: Path,
) -> None:
    store = LigandArtifactStore(tmp_path)
    library = _library(store)

    with pytest.raises(AnkoraDomainError) as captured:
        apply_library_filters(
            library_id=library.artifact.library_id,
            request=ApplyLigandLibraryFilterRequest(),
            store=store,
        )
    assert captured.value.code == "LIGAND_FILTER_CONFIRMATION_REQUIRED"

    record = apply_library_filters(
        library_id=library.artifact.library_id,
        request=ApplyLigandLibraryFilterRequest(acknowledge_selection=True),
        store=store,
    )
    loaded = store.load_filter_run(
        library.artifact.library_id, record.artifact.filter_run_id
    )
    manifest = json.loads(
        store.filter_run_content_path(
            library.artifact.library_id, record.artifact.filter_run_id
        ).read_text(encoding="utf-8")
    )
    assert loaded == record
    assert manifest["selected_ligand_ids"] == record.selected_ligand_ids
    assert manifest["worker_count"] == record.worker_count
    assert len(record.selected_ligand_ids) == 2
    assert record.provenance.input_artifacts[0] == library.artifact.library_id


def test_filter_preview_and_apply_api_round_trip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ANKORA_DATA_DIR", str(tmp_path))
    client = TestClient(create_app())
    client.headers["Origin"] = "tauri://localhost"
    imported = client.post(
        "/api/v1/ligand-libraries/import",
        files={
            "file": (
                "synthetic_filter_library.smi",
                SYNTHETIC_LIBRARY,
                "chemical/x-daylight-smiles",
            )
        },
    ).json()
    library_id = imported["artifact"]["library_id"]

    preview = client.post(
        f"/api/v1/ligand-libraries/{library_id}/filter-preview",
        json={"plan": {}, "state_overrides": {}},
    )
    assert preview.status_code == 200
    assert preview.json()["summary"]["eligible_count"] == 2

    applied = client.post(
        f"/api/v1/ligand-libraries/{library_id}/filter-runs",
        json={"plan": {}, "state_overrides": {}, "acknowledge_selection": True},
    )
    assert applied.status_code == 201
    record = applied.json()
    loaded = client.get(
        f"/api/v1/ligand-libraries/{library_id}/filter-runs/"
        f"{record['artifact']['filter_run_id']}"
    )
    latest = client.get(
        f"/api/v1/ligand-libraries/{library_id}/filter-runs/latest"
    )
    manifest = client.get(f"/api/v1{record['manifest_content_url']}")
    assert loaded.status_code == 200
    assert latest.status_code == 200
    assert latest.json()["artifact"]["filter_run_id"] == record["artifact"]["filter_run_id"]
    assert manifest.status_code == 200
    assert manifest.json()["selected_ligand_ids"] == record["selected_ligand_ids"]
