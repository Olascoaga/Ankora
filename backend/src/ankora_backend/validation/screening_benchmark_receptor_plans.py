"""Freeze explicit receptor plans for the LIT-PCBA benchmark templates.

The source protein MOL2 files are used only to identify the deposited alternate
location that the benchmark source retained.  Coordinates are always read from
the independently acquired official structure, and no source MOL2 is converted
into a receptor derivative.
"""

from __future__ import annotations

import hashlib
import json
import math
import tarfile
import tempfile
from pathlib import Path
from typing import Any

import gemmi

from ankora_backend.persistence.artifact_store import StructureArtifactStore
from ankora_backend.schemas.receptors import (
    ComponentAction,
    ComponentDecision,
    IssueDecision,
    ProtonationSettings,
    ReceptorDecisionAction,
    ReceptorIssue,
    ReceptorIssueKind,
    ReceptorPreparationRequest,
    RelaxationSettings,
    TerminalHeavyAtomAddition,
)
from ankora_backend.schemas.structures import HeterogenKind, StructureSource
from ankora_backend.services.receptor_inspection import inspect_receptor
from ankora_backend.services.structure_inspection import import_structure_bytes
from ankora_backend.validation.screening_benchmark_structures import (
    COORDINATE_MATCH_TOLERANCE_ANGSTROM,
    _parse_mol2_heavy_atoms,
    _safe_regular_members,
    _SourceAtom,
    _verified_member_bytes,
)

TARGET_PH = 7.4
FORCE_FIELD = "AMBER"
RESTRAINT_FORCE_CONSTANT_KCAL_MOL_A2 = 50.0
RELAXATION_MAX_ITERATIONS = 200


class ScreeningBenchmarkReceptorPlanError(ValueError):
    """The explicit receptor-plan freeze cannot be reproduced safely."""


def build_receptor_plan_manifest(
    *,
    archive: Path,
    structure_manifest_path: Path,
    structures_dir: Path,
    frozen_on: str,
) -> dict[str, Any]:
    """Inspect official bytes and build deterministic, path-free plans."""

    structures = _load_object(structure_manifest_path, "structure manifest")
    _verify_manifest_identity(structures, "structure manifest")
    protocol_id = _required_string(structures, "protocol_id")
    targets = _required_list(structures, "targets")

    try:
        with tarfile.open(archive, mode="r:*") as source_archive:
            members = _safe_regular_members(source_archive)
            with tempfile.TemporaryDirectory(prefix="ankora-receptor-plan-") as temp:
                store = StructureArtifactStore(Path(temp))
                planned_targets = [
                    _build_target_plan(
                        source_archive,
                        members,
                        structures_dir=structures_dir,
                        store=store,
                        target=_required_object(raw, "structure target"),
                    )
                    for raw in targets
                ]
    except (OSError, tarfile.TarError) as error:
        raise ScreeningBenchmarkReceptorPlanError(
            "The benchmark source is not a readable tar archive."
        ) from error

    plan_count = sum(
        1
        for target in planned_targets
        for role in ("primary_template", "alternate_template")
        if role in target
    )
    manifest: dict[str, Any] = {
        "schema_version": 1,
        "protocol_id": protocol_id,
        "frozen_on": frozen_on,
        "dependencies": {
            "official_structure_manifest_sha256": _required_sha256(
                structures, "manifest_sha256"
            )
        },
        "plan_policy": {
            "coordinate_source": "official RCSB PDBx/mmCIF only",
            "source_protein_mol2_use": (
                "alternate-location identity evidence only; never converted"
            ),
            "chain_selection": (
                "the one author chain containing every exact source-receptor match"
            ),
            "waters": "remove all",
            "components": (
                "retain structural metals; remove co-crystal ligands and other "
                "non-polymer components"
            ),
            "missing_residues": "leave unmodelled; never build loops",
            "missing_atoms": "repair every explicitly reported observed residue",
            "alternate_locations": (
                "select the unique conformer whose heavy-atom coordinates match "
                "the frozen source receptor; removed waters/components are removed"
            ),
            "nonstandard_polymer_residues": "remove explicitly",
            "repair_relaxation": {
                "enabled_when_missing_atoms_are_repaired": True,
                "restraint_force_constant_kcal_mol_a2": (
                    RESTRAINT_FORCE_CONSTANT_KCAL_MOL_A2
                ),
                "max_iterations": RELAXATION_MAX_ITERATIONS,
            },
            "protonation": {
                "target_ph": TARGET_PH,
                "force_field": FORCE_FIELD,
                "terminal_oxt_policy": (
                    "authorize only the exact final observed polymer residue when "
                    "OXT is absent; this is a coordinate-model terminus, not a claim "
                    "about the biological sequence terminus"
                ),
                "final_execution_gate": (
                    "run and review the structured PROPKA preview for every template "
                    "before creating a final receptor"
                ),
            },
        },
        "targets": planned_targets,
        "plan_census": {
            "target_count": len(planned_targets),
            "template_plan_count": plan_count,
        },
        "execution_boundary": {
            "status": "plans_frozen_propka_reviews_not_yet_executed",
            "required_next": (
                "execute all six create-only PROPKA previews, review every structured "
                "proposal, freeze any exact overrides before final receptor creation, "
                "then create receptor PDBQT derivatives without changing these "
                "structural decisions"
            ),
        },
        "result_status": (
            "receptor_plans_frozen_no_protonation_preview_receptor_derivative_or_"
            "docking_result_executed"
        ),
    }
    manifest["manifest_sha256"] = hashlib.sha256(_canonical_json(manifest)).hexdigest()
    return manifest


def verify_receptor_plan_manifest(
    *,
    archive: Path,
    structure_manifest_path: Path,
    structures_dir: Path,
    receptor_plan_manifest_path: Path,
) -> dict[str, Any]:
    """Rebuild and compare the plan freeze without running scientific tools."""

    recorded = _load_object(receptor_plan_manifest_path, "receptor-plan manifest")
    _verify_manifest_identity(recorded, "receptor-plan manifest")
    rebuilt = build_receptor_plan_manifest(
        archive=archive,
        structure_manifest_path=structure_manifest_path,
        structures_dir=structures_dir,
        frozen_on=_required_string(recorded, "frozen_on"),
    )
    if rebuilt != recorded:
        raise ScreeningBenchmarkReceptorPlanError(
            "The receptor-plan manifest does not reproduce from recorded bytes."
        )
    return recorded


def serialize_receptor_plan_manifest(manifest: dict[str, Any]) -> str:
    return json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"


def _build_target_plan(
    source_archive: tarfile.TarFile,
    members: dict[str, tarfile.TarInfo],
    *,
    structures_dir: Path,
    store: StructureArtifactStore,
    target: dict[str, Any],
) -> dict[str, Any]:
    return {
        "target_id": _required_string(target, "target_id"),
        "primary_template": _build_template_plan(
            source_archive,
            members,
            structures_dir=structures_dir,
            store=store,
            template=_required_object(target.get("primary_template"), "primary template"),
        ),
        "alternate_template": _build_template_plan(
            source_archive,
            members,
            structures_dir=structures_dir,
            store=store,
            template=_required_object(
                target.get("alternate_template"), "alternate template"
            ),
        ),
    }


def _build_template_plan(
    source_archive: tarfile.TarFile,
    members: dict[str, tarfile.TarInfo],
    *,
    structures_dir: Path,
    store: StructureArtifactStore,
    template: dict[str, Any],
) -> dict[str, Any]:
    pdb_id = _required_string(template, "pdb_id")
    official_identity = _required_object(
        template.get("official_structure"), "official structure"
    )
    structure_path = structures_dir / _required_string(official_identity, "filename")
    _verify_file_identity(structure_path, official_identity, pdb_id)
    source_receptor_identity = _required_object(
        template.get("source_receptor"), "source receptor"
    )
    source_atoms = _parse_mol2_heavy_atoms(
        _verified_member_bytes(source_archive, members, source_receptor_identity),
        label=f"{pdb_id} source receptor",
    )
    matched_chains = _required_list(
        _required_object(
            template.get("source_receptor_frame_evidence"),
            "source receptor frame evidence",
        ),
        "matched_author_chain_ids",
    )
    if len(matched_chains) != 1 or not isinstance(matched_chains[0], str):
        raise ScreeningBenchmarkReceptorPlanError(
            f"Template {pdb_id} does not identify exactly one source-matched chain."
        )
    selected_chain = matched_chains[0]

    content = structure_path.read_bytes()
    record = import_structure_bytes(
        content=content,
        filename=structure_path.name,
        source=StructureSource.RCSB,
        source_uri=_required_string(official_identity, "source_uri"),
        store=store,
    )
    initial_report = inspect_receptor(
        artifact_id=record.artifact.artifact_id,
        store=store,
    )
    ligand_locator = _required_object(
        _required_object(
            template.get("source_ligand_frame_evidence"),
            "source ligand frame evidence",
        ).get("matched_official_residue"),
        "matched official ligand residue",
    )
    references = [
        component
        for component in initial_report.components
        if component.chain_id == _required_string(ligand_locator, "author_chain_id")
        and component.name == _required_string(ligand_locator, "residue_name")
        and component.sequence_number
        == _required_int(ligand_locator, "author_sequence_number")
        and component.insertion_code == _optional_string(ligand_locator, "insertion_code")
    ]
    if len(references) != 1:
        raise ScreeningBenchmarkReceptorPlanError(
            f"Template {pdb_id} does not expose exactly one frozen reference component."
        )
    reference_component_id = references[0].component_id
    report = inspect_receptor(
        artifact_id=record.artifact.artifact_id,
        store=store,
        reference_component_id=reference_component_id,
    )
    if selected_chain not in report.candidate_chains:
        raise ScreeningBenchmarkReceptorPlanError(
            f"Template {pdb_id} source-matched chain is not a polymer candidate."
        )

    structure = gemmi.read_structure(str(structure_path))
    structure.setup_entities()
    model = structure[0]
    chain = next((item for item in model if item.name == selected_chain), None)
    if chain is None:
        raise ScreeningBenchmarkReceptorPlanError(
            f"Template {pdb_id} selected chain is absent from the official structure."
        )
    components = [
        item for item in report.components if item.chain_id == selected_chain
    ]
    component_decisions = [
        ComponentDecision(
            component_id=item.component_id,
            action=(
                ComponentAction.KEEP
                if item.kind is HeterogenKind.METAL
                else ComponentAction.REMOVE
            ),
        )
        for item in components
    ]
    component_actions = {
        decision.component_id: decision.action for decision in component_decisions
    }
    selected_issues = [
        issue for issue in report.issues if issue.residue.chain_id == selected_chain
    ]
    selected_chain_water_count = sum(
        item.kind is HeterogenKind.WATER and item.chain_id == selected_chain
        for item in record.metadata.heterogens
    )
    issue_decisions: list[IssueDecision] = []
    decision_evidence: list[dict[str, Any]] = []
    for issue in selected_issues:
        decision, evidence = _issue_decision(
            issue,
            chain=chain,
            source_atoms=source_atoms,
            components=components,
            component_actions=component_actions,
        )
        issue_decisions.append(decision)
        decision_evidence.append(evidence)

    terminal = _coordinate_terminus(chain)
    authorized_terminal_additions = []
    if not terminal["oxt_present"]:
        authorized_terminal_additions.append(
            TerminalHeavyAtomAddition(
                chain_id=selected_chain,
                residue_name=str(terminal["residue_name"]),
                sequence_number=int(terminal["sequence_number"]),
                insertion_code=str(terminal["insertion_code"]),
            )
        )
    repair_missing_atoms = any(
        issue.kind is ReceptorIssueKind.MISSING_ATOMS
        and decision.action is ReceptorDecisionAction.REPAIR
        for issue, decision in zip(selected_issues, issue_decisions, strict=True)
    )
    request = ReceptorPreparationRequest(
        selected_chains=[selected_chain],
        water_action=ComponentAction.REMOVE,
        component_decisions=component_decisions,
        issue_decisions=issue_decisions,
        reference_component_id=reference_component_id,
        relaxation=RelaxationSettings(
            enabled=repair_missing_atoms,
            restraint_force_constant_kcal_mol_a2=(
                RESTRAINT_FORCE_CONSTANT_KCAL_MOL_A2
            ),
            max_iterations=RELAXATION_MAX_ITERATIONS,
        ),
        protonation=ProtonationSettings(
            enabled=True,
            ph=TARGET_PH,
            force_field=FORCE_FIELD,
            authorized_terminal_heavy_atom_additions=authorized_terminal_additions,
            overrides=[],
        ),
        generate_pdbqt=True,
    )
    return {
        "role": _required_string(template, "role"),
        "pdb_id": pdb_id,
        "official_structure": {
            "filename": structure_path.name,
            "size_bytes": structure_path.stat().st_size,
            "sha256": _file_sha256(structure_path),
        },
        "source_receptor": {
            "path": _required_string(source_receptor_identity, "path"),
            "size_bytes": _required_int(source_receptor_identity, "size_bytes"),
            "sha256": _required_sha256(source_receptor_identity, "sha256"),
        },
        "reference_component_id": reference_component_id,
        "inspection_census": {
            "candidate_chains": report.candidate_chains,
            "selected_chain": selected_chain,
            "water_count_all_chains": report.water_count,
            "selected_chain_water_count": selected_chain_water_count,
            "selected_chain_component_count": len(components),
            "selected_chain_issue_count": len(selected_issues),
            "issue_counts": {
                kind.value: sum(issue.kind is kind for issue in selected_issues)
                for kind in ReceptorIssueKind
            },
        },
        "component_evidence": [item.model_dump(mode="json") for item in components],
        "issue_evidence": [item.model_dump(mode="json") for item in selected_issues],
        "decision_evidence": decision_evidence,
        "coordinate_model_c_terminus": terminal,
        "preparation_request": request.model_dump(mode="json"),
        "execution_gate": "structured_propka_preview_and_review_required",
    }


def _issue_decision(
    issue: ReceptorIssue,
    *,
    chain: gemmi.Chain,
    source_atoms: list[_SourceAtom],
    components: list[Any],
    component_actions: dict[str, ComponentAction],
) -> tuple[IssueDecision, dict[str, Any]]:
    evidence: dict[str, Any] = {
        "issue_id": issue.issue_id,
        "kind": issue.kind.value,
    }
    if issue.kind is ReceptorIssueKind.MISSING_RESIDUE:
        decision = IssueDecision(
            issue_id=issue.issue_id, action=ReceptorDecisionAction.LEAVE
        )
        evidence["basis"] = "unobserved loop remains unmodelled"
        return decision, evidence
    if issue.kind is ReceptorIssueKind.MISSING_ATOMS:
        decision = IssueDecision(
            issue_id=issue.issue_id, action=ReceptorDecisionAction.REPAIR
        )
        evidence["basis"] = "reported observed residue is completed explicitly"
        evidence["missing_atoms"] = issue.missing_atoms
        return decision, evidence
    if issue.kind is ReceptorIssueKind.NONSTANDARD_RESIDUE:
        decision = IssueDecision(
            issue_id=issue.issue_id, action=ReceptorDecisionAction.REMOVE
        )
        evidence["basis"] = "nonstandard polymer is outside the frozen AMBER plan"
        return decision, evidence
    if issue.kind is not ReceptorIssueKind.ALTERNATE_LOCATION:
        raise ScreeningBenchmarkReceptorPlanError(
            f"Unsupported receptor issue kind {issue.kind.value}."
        )

    residue = _find_residue(chain, issue)
    if residue.is_water():
        decision = IssueDecision(
            issue_id=issue.issue_id, action=ReceptorDecisionAction.REMOVE
        )
        evidence["basis"] = "water is removed by the frozen component policy"
        return decision, evidence
    if residue.entity_type is not gemmi.EntityType.Polymer:
        component = next(
            (
                item
                for item in components
                if item.chain_id == issue.residue.chain_id
                and item.name == issue.residue.residue_name
                and item.sequence_number == issue.residue.sequence_number
                and item.insertion_code == issue.residue.insertion_code
            ),
            None,
        )
        if (
            component is None
            or component_actions.get(component.component_id)
            is not ComponentAction.REMOVE
        ):
            raise ScreeningBenchmarkReceptorPlanError(
                f"Alternate component {issue.issue_id} is not explicitly removable."
            )
        decision = IssueDecision(
            issue_id=issue.issue_id, action=ReceptorDecisionAction.REMOVE
        )
        evidence["basis"] = "non-polymer component is removed by the frozen policy"
        return decision, evidence

    selected, matches = _source_aligned_altloc(residue, source_atoms)
    decision = IssueDecision(
        issue_id=issue.issue_id,
        action=ReceptorDecisionAction.REPAIR,
        selected_altloc=selected,
    )
    evidence.update(
        {
            "basis": "unique exact source-receptor coordinate match",
            "selected_altloc": selected,
            "exact_source_matches_by_altloc": matches,
            "tolerance_angstrom": COORDINATE_MATCH_TOLERANCE_ANGSTROM,
        }
    )
    return decision, evidence


def _source_aligned_altloc(
    residue: gemmi.Residue, source_atoms: list[_SourceAtom]
) -> tuple[str, dict[str, int]]:
    labels = sorted(
        {
            _clean_char(atom.altloc)
            for atom in residue
            if _clean_char(atom.altloc)
        }
    )
    if not labels:
        raise ScreeningBenchmarkReceptorPlanError(
            "An alternate-location issue has no labelled coordinates."
        )
    if residue.seqid.num is None:
        raise ScreeningBenchmarkReceptorPlanError(
            "An alternate-location residue has no author sequence number."
        )
    source_residue_label = (
        f"{residue.name.strip()}{residue.seqid.num}{_clean_char(residue.seqid.icode)}"
    )
    residue_source_atoms = [
        atom for atom in source_atoms if atom.residue_label == source_residue_label
    ]
    if not residue_source_atoms:
        raise ScreeningBenchmarkReceptorPlanError(
            "A polymer alternate location has no matching source-residue identity."
        )
    tolerance = COORDINATE_MATCH_TOLERANCE_ANGSTROM + 1e-12
    counts: dict[str, int] = {}
    for label in labels:
        atoms = [atom for atom in residue if _clean_char(atom.altloc) == label]
        counts[label] = sum(
            any(
                source.element == atom.element.name
                and math.dist(
                    (source.x, source.y, source.z),
                    (atom.pos.x, atom.pos.y, atom.pos.z),
                )
                <= tolerance
                for source in residue_source_atoms
            )
            for atom in atoms
        )
    best = max(counts.values())
    winners = [label for label, count in counts.items() if count == best]
    if best == 0 or len(winners) != 1:
        raise ScreeningBenchmarkReceptorPlanError(
            "A polymer alternate location has no unique source-coordinate match."
        )
    return winners[0], counts


def _find_residue(chain: gemmi.Chain, issue: ReceptorIssue) -> gemmi.Residue:
    matches = [
        residue
        for residue in chain
        if residue.seqid.num == issue.residue.sequence_number
        and _clean_char(residue.seqid.icode) == issue.residue.insertion_code
        and residue.name.strip() == issue.residue.residue_name
    ]
    if len(matches) != 1:
        raise ScreeningBenchmarkReceptorPlanError(
            f"Issue {issue.issue_id} does not map to one observed residue."
        )
    return matches[0]


def _coordinate_terminus(chain: gemmi.Chain) -> dict[str, Any]:
    residues = [
        residue
        for residue in chain
        if residue.entity_type is gemmi.EntityType.Polymer and len(residue) > 0
    ]
    if not residues:
        raise ScreeningBenchmarkReceptorPlanError(
            "The selected chain has no observed polymer terminus."
        )
    residue = residues[-1]
    if residue.seqid.num is None:
        raise ScreeningBenchmarkReceptorPlanError(
            "The selected-chain terminus has no author sequence number."
        )
    return {
        "chain_id": chain.name,
        "residue_name": residue.name.strip(),
        "sequence_number": residue.seqid.num,
        "insertion_code": _clean_char(residue.seqid.icode),
        "oxt_present": any(atom.name.strip() == "OXT" for atom in residue),
        "interpretation": (
            "final observed polymer residue in the selected coordinate model; "
            "not necessarily the biological sequence terminus"
        ),
    }


def _verify_file_identity(path: Path, identity: dict[str, Any], pdb_id: str) -> None:
    if not path.is_file():
        raise ScreeningBenchmarkReceptorPlanError(
            f"Official structure {pdb_id} is unavailable."
        )
    if path.stat().st_size != _required_int(identity, "size_bytes"):
        raise ScreeningBenchmarkReceptorPlanError(
            f"Official structure {pdb_id} size changed."
        )
    if _file_sha256(path) != _required_sha256(identity, "sha256"):
        raise ScreeningBenchmarkReceptorPlanError(
            f"Official structure {pdb_id} SHA-256 changed."
        )


def _load_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value: Any = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ScreeningBenchmarkReceptorPlanError(
            f"The {label} is unavailable or invalid."
        ) from error
    return _required_object(value, label)


def _verify_manifest_identity(manifest: dict[str, Any], label: str) -> None:
    recorded = _required_sha256(manifest, "manifest_sha256")
    payload = dict(manifest)
    payload.pop("manifest_sha256")
    if hashlib.sha256(_canonical_json(payload)).hexdigest() != recorded:
        raise ScreeningBenchmarkReceptorPlanError(
            f"The {label} content differs from its manifest SHA-256."
        )


def _required_object(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ScreeningBenchmarkReceptorPlanError(f"{label} must be an object.")
    return value


def _required_list(value: dict[str, Any], key: str) -> list[Any]:
    raw = value.get(key)
    if not isinstance(raw, list):
        raise ScreeningBenchmarkReceptorPlanError(f"{key} must be a list.")
    return raw


def _required_string(value: dict[str, Any], key: str) -> str:
    raw = value.get(key)
    if not isinstance(raw, str) or not raw:
        raise ScreeningBenchmarkReceptorPlanError(
            f"{key} must be a non-empty string."
        )
    return raw


def _optional_string(value: dict[str, Any], key: str) -> str:
    raw = value.get(key, "")
    if not isinstance(raw, str):
        raise ScreeningBenchmarkReceptorPlanError(f"{key} must be a string.")
    return raw


def _required_int(value: dict[str, Any], key: str) -> int:
    raw = value.get(key)
    if not isinstance(raw, int) or isinstance(raw, bool) or raw < 0:
        raise ScreeningBenchmarkReceptorPlanError(
            f"{key} must be a non-negative integer."
        )
    return raw


def _required_sha256(value: dict[str, Any], key: str) -> str:
    raw = _required_string(value, key).lower()
    if len(raw) != 64 or any(character not in "0123456789abcdef" for character in raw):
        raise ScreeningBenchmarkReceptorPlanError(f"{key} must be a SHA-256 digest.")
    return raw


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_json(value: dict[str, Any]) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _clean_char(value: str) -> str:
    return "" if value in {"\x00", " ", ".", "?"} else value
