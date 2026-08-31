"""Read-only 2D library filtering and immutable selection manifests."""

import json
import os
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from importlib import import_module
from pathlib import Path
from threading import Lock, local
from typing import Any

from ankora_backend.domain.errors import AnkoraDomainError
from ankora_backend.persistence.ligand_store import LigandArtifactStore
from ankora_backend.schemas.ligands import (
    ApplyLigandLibraryFilterRequest,
    LigandAlertPolicy,
    LigandCustomFilterRule,
    LigandCustomRuleOperator,
    LigandCustomRuleResult,
    LigandDuplicatePolicy,
    LigandFilterDescriptors,
    LigandFilterDisposition,
    LigandFilterEvaluation,
    LigandFilterRunArtifact,
    LigandFilterSummary,
    LigandLibraryEntry,
    LigandLibraryFilterPreview,
    LigandLibraryFilterRequest,
    LigandLibraryFilterRun,
    LigandRuleEvaluation,
    LigandStructuralAlert,
)
from ankora_backend.schemas.provenance import ProvenanceEvent, ToolIdentity

Chem: Any = import_module("rdkit.Chem")
rdBase: Any = import_module("rdkit.rdBase")
QED: Any = import_module("rdkit.Chem.QED")
Crippen: Any = import_module("rdkit.Chem.Crippen")
Descriptors: Any = import_module("rdkit.Chem.Descriptors")
Lipinski: Any = import_module("rdkit.Chem.Lipinski")
FilterCatalogModule: Any = import_module("rdkit.Chem.FilterCatalog")
FilterCatalog: Any = FilterCatalogModule.FilterCatalog
FilterCatalogParams: Any = FilterCatalogModule.FilterCatalogParams
_catalog_state = local()


@dataclass(frozen=True, slots=True)
class _CachedDescriptors:
    canonical_isomeric_smiles: str
    descriptors: LigandFilterDescriptors
    alerts: list[LigandStructuralAlert]


# A chemical state's SDF content is immutable once its state_id is minted, so its
# descriptors, canonical SMILES, and structural alerts are a pure function of
# (store root, ligand_id, state_id) and never need to change. Interactively
# adjusting filter thresholds re-evaluates the whole library on every
# "Recalculate filter preview" click; without this cache, that re-parses every
# molecule's SDF and reruns RDKit descriptor/QED/PAINS/BRENK computation from
# scratch each time, even though only the rule thresholds changed, not the
# molecules. Bounded LRU (not a plain dict) so a long-running process working
# through many large libraries doesn't retain every molecule it has ever seen;
# keyed by the store's resolved root, not just (ligand_id, state_id), so two
# different `ANKORA_DATA_DIR` roots served by the same process (tests, or any
# future multi-project support) can't collide on the same UUID.
_DESCRIPTOR_CACHE_MAX_ENTRIES = 4096
_descriptor_cache: "OrderedDict[tuple[Path, str, str], _CachedDescriptors]" = OrderedDict()
_descriptor_cache_lock = Lock()


def _cached_descriptors(
    store: LigandArtifactStore, ligand_id: str, state_id: str
) -> _CachedDescriptors:
    key = (store.root, ligand_id, state_id)
    with _descriptor_cache_lock:
        cached = _descriptor_cache.get(key)
        if cached is not None:
            _descriptor_cache.move_to_end(key)
            return cached
    molecule = _load_state_molecule(store, ligand_id, state_id)
    computed = _CachedDescriptors(
        canonical_isomeric_smiles=Chem.MolToSmiles(molecule, isomericSmiles=True),
        descriptors=_descriptors(molecule),
        alerts=[*_catalog_alerts(molecule, "PAINS"), *_catalog_alerts(molecule, "BRENK")],
    )
    with _descriptor_cache_lock:
        _descriptor_cache[key] = computed
        _descriptor_cache.move_to_end(key)
        while len(_descriptor_cache) > _DESCRIPTOR_CACHE_MAX_ENTRIES:
            _descriptor_cache.popitem(last=False)
    return computed


def preview_library_filters(
    *,
    library_id: str,
    request: LigandLibraryFilterRequest,
    store: LigandArtifactStore,
) -> LigandLibraryFilterPreview:
    library = store.load_library_record(library_id)
    ligand_ids = {
        entry.ligand.artifact.ligand_id
        for entry in library.entries
        if entry.ligand is not None
    }
    unknown_overrides = sorted(set(request.state_overrides) - ligand_ids)
    if unknown_overrides:
        raise _filter_error(
            "LIGAND_FILTER_STATE_OVERRIDE_INVALID",
            "A chemical-state override does not belong to this ligand library.",
            details={"ligand_ids": unknown_overrides},
        )

    entries = [
        entry
        for entry in library.entries
        if entry.ligand is not None and entry.ligand.state is not None
    ]
    worker_count = _parallel_worker_count(len(entries))
    if worker_count == 1:
        evaluations = [
            _evaluate_entry(entry=entry, request=request, store=store) for entry in entries
        ]
    else:
        with ThreadPoolExecutor(
            max_workers=worker_count,
            thread_name_prefix="ankora-filter",
        ) as executor:
            evaluations = list(
                executor.map(
                    lambda entry: _evaluate_entry(
                        entry=entry,
                        request=request,
                        store=store,
                    ),
                    entries,
                )
            )
    evaluations = _apply_duplicate_policy(evaluations, request.plan.duplicate_policy)

    return LigandLibraryFilterPreview(
        library_id=library_id,
        plan=request.plan,
        evaluations=evaluations,
        summary=_summary(evaluations),
        rdkit_version=rdBase.rdkitVersion,
        worker_count=worker_count,
    )


def _evaluate_entry(
    *,
    entry: LigandLibraryEntry,
    request: LigandLibraryFilterRequest,
    store: LigandArtifactStore,
) -> LigandFilterEvaluation:
    ligand = entry.ligand
    if ligand is None or ligand.state is None:
        raise RuntimeError("Only successfully imported ligand states can be filtered.")
    ligand_id = ligand.artifact.ligand_id
    state_id = request.state_overrides.get(ligand_id, ligand.state.state_id)
    if state_id == ligand.state.state_id:
        inspection = ligand.inspection
    else:
        state_artifact = store.load_state_artifact(ligand_id, state_id)
        if state_artifact.ligand_id != ligand_id:
            raise _filter_error(
                "LIGAND_FILTER_STATE_OVERRIDE_INVALID",
                "The selected chemical state does not belong to this compound.",
                details={"ligand_id": ligand_id, "state_id": state_id},
            )
        inspection = store.load_state_inspection(ligand_id, state_id)

    if inspection.fragment_count > 1 or inspection.undefined_stereocenter_count > 0:
        unresolved_reasons: list[str] = []
        if inspection.fragment_count > 1:
            unresolved_reasons.append("MULTICOMPONENT_STATE_REQUIRES_DECISION")
        if inspection.undefined_stereocenter_count > 0:
            unresolved_reasons.append("STEREOCHEMISTRY_REQUIRES_DECISION")
        return LigandFilterEvaluation(
            ligand_id=ligand_id,
            record_index=entry.record_index,
            state_id=state_id,
            canonical_isomeric_smiles=inspection.canonical_smiles,
            disposition=LigandFilterDisposition.NEEDS_DECISION,
            reasons=unresolved_reasons,
        )

    cached = _cached_descriptors(store, ligand_id, state_id)
    descriptors = cached.descriptors
    smiles = cached.canonical_isomeric_smiles
    alerts = cached.alerts
    lipinski = _lipinski(descriptors)
    veber = _veber(descriptors)
    ghose = _ghose(descriptors)
    muegge = _muegge(descriptors)
    reasons: list[str] = []
    excluded = False
    plan = request.plan
    if plan.require_lipinski and len(lipinski.violations) > plan.max_lipinski_violations:
        reasons.append("LIPINSKI_REQUIRED")
        excluded = True
    if plan.require_veber and not veber.passed:
        reasons.append("VEBER_REQUIRED")
        excluded = True
    if plan.require_ghose and not ghose.passed:
        reasons.append("GHOSE_REQUIRED")
        excluded = True
    if plan.require_muegge and not muegge.passed:
        reasons.append("MUEGGE_REQUIRED")
        excluded = True
    if plan.minimum_qed is not None and descriptors.qed < plan.minimum_qed:
        reasons.append("QED_BELOW_MINIMUM")
        excluded = True

    custom_rule_results = _evaluate_custom_rules(descriptors, plan.custom_rules)
    for result in custom_rule_results:
        if result.required and not result.passed:
            reasons.append(f"CUSTOM_RULE_REQUIRED:{result.rule_id}")
            excluded = True

    excluded = _apply_alert_policy(
        has_match=any(alert.catalog == "PAINS" for alert in alerts),
        policy=plan.pains_policy,
        label="PAINS",
        reasons=reasons,
        excluded=excluded,
    )
    excluded = _apply_alert_policy(
        has_match=any(alert.catalog == "BRENK" for alert in alerts),
        policy=plan.brenk_policy,
        label="BRENK",
        reasons=reasons,
        excluded=excluded,
    )
    return LigandFilterEvaluation(
        ligand_id=ligand_id,
        record_index=entry.record_index,
        state_id=state_id,
        canonical_isomeric_smiles=smiles,
        descriptors=descriptors,
        lipinski=lipinski,
        veber=veber,
        ghose=ghose,
        muegge=muegge,
        custom_rule_results=custom_rule_results,
        alerts=alerts,
        disposition=(
            LigandFilterDisposition.EXCLUDED
            if excluded
            else LigandFilterDisposition.ELIGIBLE
        ),
        reasons=reasons,
    )


def _apply_duplicate_policy(
    evaluations: list[LigandFilterEvaluation],
    policy: LigandDuplicatePolicy,
) -> list[LigandFilterEvaluation]:
    first_by_smiles: dict[str, str] = {}
    resolved: list[LigandFilterEvaluation] = []
    for evaluation in evaluations:
        smiles = evaluation.canonical_isomeric_smiles
        if evaluation.descriptors is None or smiles is None:
            resolved.append(evaluation)
            continue
        duplicate_of = first_by_smiles.get(smiles)
        if duplicate_of is None:
            first_by_smiles[smiles] = evaluation.ligand_id
            resolved.append(evaluation)
            continue
        reasons = [*evaluation.reasons]
        disposition = evaluation.disposition
        if policy is LigandDuplicatePolicy.EXCLUDE:
            reasons.append("DUPLICATE_EXCLUDED")
            disposition = LigandFilterDisposition.EXCLUDED
        elif policy is LigandDuplicatePolicy.REVIEW:
            reasons.append("DUPLICATE_REVIEW")
        resolved.append(
            evaluation.model_copy(
                update={
                    "duplicate_of_ligand_id": duplicate_of,
                    "disposition": disposition,
                    "reasons": reasons,
                }
            )
        )
    return resolved


def _parallel_worker_count(task_count: int) -> int:
    logical_cores = os.cpu_count() or 2
    usable_cores = logical_cores - 1 if logical_cores > 1 else 1
    return max(1, min(task_count, usable_cores))


def apply_library_filters(
    *,
    library_id: str,
    request: ApplyLigandLibraryFilterRequest,
    store: LigandArtifactStore,
) -> LigandLibraryFilterRun:
    if not request.acknowledge_selection:
        raise _filter_error(
            "LIGAND_FILTER_CONFIRMATION_REQUIRED",
            "Confirm the complete library-filter plan before creating a selection manifest.",
        )
    preview = preview_library_filters(
        library_id=library_id,
        request=LigandLibraryFilterRequest(
            plan=request.plan,
            state_overrides=request.state_overrides,
        ),
        store=store,
    )
    filter_run_id = store.new_filter_run_id()
    created_at = datetime.now(UTC)
    selected = [
        item.ligand_id
        for item in preview.evaluations
        if item.disposition is LigandFilterDisposition.ELIGIBLE
    ]
    manifest_payload = {
        "filter_run_id": filter_run_id,
        "library_id": library_id,
        "created_at": created_at.isoformat(),
        "rdkit_version": preview.rdkit_version,
        "worker_count": preview.worker_count,
        "plan": preview.plan.model_dump(mode="json"),
        "summary": preview.summary.model_dump(mode="json"),
        "selected_ligand_ids": selected,
        "evaluations": [item.model_dump(mode="json") for item in preview.evaluations],
    }
    manifest = (
        json.dumps(manifest_payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        + "\n"
    ).encode()
    artifact = LigandFilterRunArtifact(
        filter_run_id=filter_run_id,
        library_id=library_id,
        filename="selection_manifest.json",
        sha256=sha256(manifest).hexdigest(),
        size_bytes=len(manifest),
        created_at=created_at,
    )
    provenance = ProvenanceEvent(
        event_id=f"ligand_library_filtered-{filter_run_id}",
        event_type="ligand_library_filter_selection_created",
        timestamp=created_at,
        input_artifacts=[library_id, *request.state_overrides.values()],
        output_artifacts=[filter_run_id],
        tool=ToolIdentity(name="RDKit library filters", version=preview.rdkit_version),
        parameters={
            "plan": preview.plan.model_dump(mode="json"),
            "summary": preview.summary.model_dump(mode="json"),
            "state_overrides": request.state_overrides,
            "worker_count": preview.worker_count,
        },
        warnings=[],
        command=None,
    )
    record = LigandLibraryFilterRun(
        artifact=artifact,
        plan=preview.plan,
        evaluations=preview.evaluations,
        summary=preview.summary,
        selected_ligand_ids=selected,
        rdkit_version=preview.rdkit_version,
        worker_count=preview.worker_count,
        provenance=provenance,
        manifest_content_url=(
            f"/ligand-libraries/{library_id}/filter-runs/{filter_run_id}/content"
        ),
    )
    store.create_filter_run(library_id, filter_run_id, manifest, record)
    return record


def _load_state_molecule(
    store: LigandArtifactStore, ligand_id: str, state_id: str
) -> Any:
    supplier = Chem.SDMolSupplier(
        str(store.state_content_path(ligand_id, state_id)),
        removeHs=False,
        sanitize=True,
    )
    molecule = next((item for item in supplier if item is not None), None)
    if molecule is None:
        raise _filter_error(
            "LIGAND_FILTER_STATE_PARSE_FAILED",
            "RDKit could not inspect the selected chemical state for filtering.",
            details={"ligand_id": ligand_id, "state_id": state_id},
        )
    return molecule


def _descriptors(molecule: Any) -> LigandFilterDescriptors:
    hydrogenated = Chem.AddHs(Chem.Mol(molecule))
    carbon_count = sum(atom.GetAtomicNum() == 6 for atom in molecule.GetAtoms())
    hetero_count = sum(atom.GetAtomicNum() not in {1, 6} for atom in molecule.GetAtoms())
    return LigandFilterDescriptors(
        molecular_weight_g_mol=Descriptors.MolWt(molecule),
        clogp=Crippen.MolLogP(molecule),
        hydrogen_bond_donors=Lipinski.NumHDonors(molecule),
        hydrogen_bond_acceptors=Lipinski.NumHAcceptors(molecule),
        tpsa_angstrom2=Descriptors.TPSA(molecule),
        rotatable_bonds=Lipinski.NumRotatableBonds(molecule),
        molar_refractivity=Crippen.MolMR(molecule),
        total_atom_count_with_hydrogens=hydrogenated.GetNumAtoms(),
        carbon_atom_count=carbon_count,
        hetero_atom_count=hetero_count,
        ring_count=Descriptors.RingCount(molecule),
        qed=QED.qed(molecule),
    )


def _lipinski(value: LigandFilterDescriptors) -> LigandRuleEvaluation:
    violations = []
    if value.molecular_weight_g_mol > 500:
        violations.append("MW > 500 g/mol")
    if value.clogp > 5:
        violations.append("cLogP > 5")
    if value.hydrogen_bond_donors > 5:
        violations.append("HBD > 5")
    if value.hydrogen_bond_acceptors > 10:
        violations.append("HBA > 10")
    return LigandRuleEvaluation(passed=not violations, violations=violations)


def _veber(value: LigandFilterDescriptors) -> LigandRuleEvaluation:
    violations = []
    if value.rotatable_bonds > 10:
        violations.append("rotatable bonds > 10")
    if value.tpsa_angstrom2 > 140:
        violations.append("TPSA > 140 Å²")
    return LigandRuleEvaluation(passed=not violations, violations=violations)


def _ghose(value: LigandFilterDescriptors) -> LigandRuleEvaluation:
    violations = []
    if not 160 <= value.molecular_weight_g_mol <= 480:
        violations.append("MW outside 160–480 g/mol")
    if not -0.4 <= value.clogp <= 5.6:
        violations.append("cLogP outside -0.4–5.6")
    if not 40 <= value.molar_refractivity <= 130:
        violations.append("molar refractivity outside 40–130")
    if not 20 <= value.total_atom_count_with_hydrogens <= 70:
        violations.append("total atoms outside 20–70")
    return LigandRuleEvaluation(passed=not violations, violations=violations)


def _muegge(value: LigandFilterDescriptors) -> LigandRuleEvaluation:
    violations = []
    if not 200 <= value.molecular_weight_g_mol <= 600:
        violations.append("MW outside 200–600 g/mol")
    if not -2 <= value.clogp <= 5:
        violations.append("cLogP outside -2–5")
    if value.tpsa_angstrom2 > 150:
        violations.append("TPSA > 150 Å²")
    if value.ring_count > 7:
        violations.append("rings > 7")
    if value.carbon_atom_count <= 4:
        violations.append("carbon atoms ≤ 4")
    if value.hetero_atom_count <= 1:
        violations.append("hetero atoms ≤ 1")
    if value.rotatable_bonds > 15:
        violations.append("rotatable bonds > 15")
    if value.hydrogen_bond_acceptors > 10:
        violations.append("HBA > 10")
    if value.hydrogen_bond_donors > 5:
        violations.append("HBD > 5")
    return LigandRuleEvaluation(passed=not violations, violations=violations)


def _evaluate_custom_rules(
    descriptors: LigandFilterDescriptors,
    rules: list[LigandCustomFilterRule],
) -> list[LigandCustomRuleResult]:
    results = []
    for rule in rules:
        value = float(getattr(descriptors, rule.descriptor.value))
        results.append(
            LigandCustomRuleResult(
                rule_id=rule.rule_id,
                label=rule.label,
                required=rule.required,
                passed=_custom_rule_passes(rule, value),
                value=value,
            )
        )
    return results


def _custom_rule_passes(rule: LigandCustomFilterRule, value: float) -> bool:
    if rule.operator is LigandCustomRuleOperator.LESS_THAN:
        return value < rule.value
    if rule.operator is LigandCustomRuleOperator.LESS_THAN_OR_EQUAL:
        return value <= rule.value
    if rule.operator is LigandCustomRuleOperator.GREATER_THAN:
        return value > rule.value
    if rule.operator is LigandCustomRuleOperator.GREATER_THAN_OR_EQUAL:
        return value >= rule.value
    if rule.operator is LigandCustomRuleOperator.EQUAL:
        return value == rule.value
    if rule.operator is not LigandCustomRuleOperator.BETWEEN or rule.value_upper is None:
        # Reachable only if the schema's own between-requires-value_upper
        # validator is ever bypassed — every other LigandCustomRuleOperator
        # is handled by the branches above, so this really would be an
        # unreachable-in-practice bug, but a bare `assert` disappears under
        # `python -O` and lets execution fall through to `value_upper=None`,
        # raising a much less clear TypeError instead of this 422.
        raise AnkoraDomainError(
            code="LIGAND_CUSTOM_RULE_INVALID",
            stage="ligand_filtering",
            message="A 'between' custom filter rule requires an upper bound.",
            status_code=422,
            details={"operator": rule.operator.value},
        )
    return rule.value <= value <= rule.value_upper


def _catalog_alerts(molecule: Any, catalog_name: str) -> list[LigandStructuralAlert]:
    catalog = _filter_catalog(catalog_name)
    return [
        LigandStructuralAlert(
            catalog=catalog_name,
            description=match.filterMatch.GetName(),
            atom_indices=sorted({pair.target for pair in match.atomPairs}),
        )
        for match in catalog.GetFilterMatches(molecule)
    ]


def _filter_catalog(catalog_name: str) -> Any:
    catalogs: dict[str, Any] | None = getattr(_catalog_state, "catalogs", None)
    if catalogs is None:
        catalogs = {}
        _catalog_state.catalogs = catalogs
    cached = catalogs.get(catalog_name)
    if cached is not None:
        return cached
    catalog_type = (
        FilterCatalogParams.FilterCatalogs.PAINS
        if catalog_name == "PAINS"
        else FilterCatalogParams.FilterCatalogs.BRENK
    )
    parameters = FilterCatalogParams()
    parameters.AddCatalog(catalog_type)
    catalog = FilterCatalog(parameters)
    catalogs[catalog_name] = catalog
    return catalog


def _apply_alert_policy(
    *,
    has_match: bool,
    policy: LigandAlertPolicy,
    label: str,
    reasons: list[str],
    excluded: bool,
) -> bool:
    if not has_match or policy is LigandAlertPolicy.IGNORE:
        return excluded
    reasons.append(f"{label}_{'EXCLUDED' if policy is LigandAlertPolicy.EXCLUDE else 'REVIEW'}")
    return excluded or policy is LigandAlertPolicy.EXCLUDE


def _summary(evaluations: list[LigandFilterEvaluation]) -> LigandFilterSummary:
    return LigandFilterSummary(
        imported_count=len(evaluations),
        eligible_count=sum(
            item.disposition is LigandFilterDisposition.ELIGIBLE for item in evaluations
        ),
        excluded_count=sum(
            item.disposition is LigandFilterDisposition.EXCLUDED for item in evaluations
        ),
        needs_decision_count=sum(
            item.disposition is LigandFilterDisposition.NEEDS_DECISION
            for item in evaluations
        ),
        duplicate_count=sum(item.duplicate_of_ligand_id is not None for item in evaluations),
        pains_match_count=sum(
            any(alert.catalog == "PAINS" for alert in item.alerts) for item in evaluations
        ),
        brenk_match_count=sum(
            any(alert.catalog == "BRENK" for alert in item.alerts) for item in evaluations
        ),
    )


def _filter_error(
    code: str,
    message: str,
    *,
    details: dict[str, object] | None = None,
) -> AnkoraDomainError:
    return AnkoraDomainError(
        code=code,
        stage="ligand_filtering",
        message=message,
        status_code=422,
        details=details,
    )
