"""Apply explicit M2 receptor decisions into immutable, traceable derivatives."""

import hashlib
import json
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path
from uuid import uuid4

import gemmi

from ankora_backend import __version__
from ankora_backend.adapters.tools.receptor_preparation import (
    run_meeko_receptor,
    run_pdb2pqr_propka,
    run_pdbfixer,
)
from ankora_backend.domain.errors import AnkoraDomainError
from ankora_backend.execution.subprocess_runner import ToolExecution
from ankora_backend.persistence.artifact_store import StructureArtifactStore
from ankora_backend.persistence.receptor_store import ReceptorArtifactStore
from ankora_backend.schemas.provenance import ProvenanceEvent, ToolIdentity
from ankora_backend.schemas.receptors import (
    ComponentAction,
    IssueDecision,
    ReceptorDecisionAction,
    ReceptorInspectionReport,
    ReceptorIssue,
    ReceptorIssueKind,
    ReceptorOutputArtifact,
    ReceptorOutputStage,
    ReceptorPreparationRecord,
    ReceptorPreparationRequest,
    ReceptorPreparationStatus,
    TerminalHeavyAtomAddition,
)
from ankora_backend.schemas.structures import HeterogenKind, StructureFormat
from ankora_backend.services.receptor_inspection import (
    _clean_char,
    _read_structure,
    component_id,
    inspect_receptor,
)


def prepare_receptor(
    *,
    source_artifact_id: str,
    request: ReceptorPreparationRequest,
    structure_store: StructureArtifactStore,
    receptor_store: ReceptorArtifactStore,
) -> ReceptorPreparationRecord:
    report = inspect_receptor(
        artifact_id=source_artifact_id,
        store=structure_store,
        reference_component_id=request.reference_component_id,
    )
    selected_issues, issue_decisions = _validate_decisions(report, request)
    source_record = structure_store.load_record(source_artifact_id)
    source_content = structure_store.content_path(source_artifact_id).read_bytes()
    receptor_id = receptor_store.new_receptor_id()
    receptor_store.create_receptor(receptor_id)
    created_at = datetime.now(UTC)
    outputs: list[ReceptorOutputArtifact] = []
    provenance: list[ProvenanceEvent] = []

    try:
        selected_content = _build_selected_receptor(
            content=source_content,
            structure_format=source_record.artifact.format,
            request=request,
            issue_decisions=issue_decisions,
            issues=selected_issues,
        )
        selected_path = receptor_store.write_bytes(
            receptor_id, "selected_receptor.pdb", selected_content
        )
        selected_output = _record_output(
            receptor_id=receptor_id,
            path=selected_path,
            stage=ReceptorOutputStage.SELECTED,
            format_name=StructureFormat.PDB,
            created_at=created_at,
        )
        outputs.append(selected_output)
        selection_event = ProvenanceEvent(
            event_id=f"receptor-selection-{receptor_id}",
            event_type="receptor_selection_applied",
            timestamp=created_at,
            input_artifacts=[source_artifact_id],
            output_artifacts=[selected_output.artifact_id],
            tool=ToolIdentity(name="ankora-gemmi-selector", version=version("gemmi")),
            parameters={
                "selected_chains": request.selected_chains,
                "water_action": request.water_action.value,
                "component_decisions": [
                    decision.model_dump(mode="json")
                    for decision in request.component_decisions
                ],
                "issue_decisions": [
                    decision.model_dump(mode="json") for decision in request.issue_decisions
                ],
                "coordinate_model": 1,
            },
            warnings=report.warnings,
        )
        provenance.append(selection_event)
        current_pdb = selected_path

        repair_residues = [
            issue.residue
            for issue in selected_issues
            if issue.kind is ReceptorIssueKind.MISSING_ATOMS
            and issue_decisions[issue.issue_id].action is ReceptorDecisionAction.REPAIR
        ]
        if repair_residues:
            repaired_path = receptor_store.output_path(receptor_id, "repaired_receptor.pdb")
            relaxed_path = (
                receptor_store.output_path(receptor_id, "relaxed_receptor.pdb")
                if request.relaxation.enabled
                else None
            )
            execution, tool_version = run_pdbfixer(
                input_path=current_pdb,
                output_path=repaired_path,
                residues=repair_residues,
                relaxed_output_path=relaxed_path,
                restraint_force_constant_kcal_mol_a2=(
                    request.relaxation.restraint_force_constant_kcal_mol_a2
                    if relaxed_path is not None
                    else None
                ),
                relax_max_iterations=(
                    request.relaxation.max_iterations if relaxed_path is not None else None
                ),
            )
            log_files = _save_execution_logs(
                receptor_store,
                receptor_id,
                "pdbfixer",
                execution,
                additional_files=[relaxed_path] if relaxed_path is not None else None,
            )
            repaired_output = _record_output(
                receptor_id=receptor_id,
                path=repaired_path,
                stage=ReceptorOutputStage.REPAIRED,
                format_name=StructureFormat.PDB,
                created_at=datetime.now(UTC),
            )
            outputs.append(repaired_output)
            provenance.append(
                _tool_event(
                    receptor_id=receptor_id,
                    event_type="receptor_residues_repaired",
                    input_artifact=selected_output.artifact_id,
                    output_artifact=repaired_output.artifact_id,
                    tool_name="PDBFixer",
                    tool_version=tool_version,
                    execution=execution,
                    parameters={
                        "residues": [item.model_dump() for item in repair_residues],
                        "missing_loops_added": False,
                        "nonstandard_residues_replaced": False,
                        "raw_logs": log_files,
                    },
                )
            )
            current_pdb = repaired_path

            if relaxed_path is not None:
                # Compare against the pre-repair structure, not the repaired one:
                # newly reconstructed atoms already exist in repaired_path (just
                # not yet relaxed), and are *supposed* to move a lot when the
                # declash step repositions them. Only atoms present before
                # PDBFixer ever ran are the ones this tolerance protects.
                max_displacement_angstrom = _assert_restrained_atoms_stable(
                    original_path=selected_path, relaxed_path=relaxed_path
                )
                relaxed_output = _record_output(
                    receptor_id=receptor_id,
                    path=relaxed_path,
                    stage=ReceptorOutputStage.RELAXED,
                    format_name=StructureFormat.PDB,
                    created_at=datetime.now(UTC),
                )
                outputs.append(relaxed_output)
                provenance.append(
                    _tool_event(
                        receptor_id=receptor_id,
                        event_type="receptor_clashes_relaxed",
                        input_artifact=repaired_output.artifact_id,
                        output_artifact=relaxed_output.artifact_id,
                        tool_name="OpenMM declash (PDBFixer worker)",
                        tool_version=tool_version,
                        execution=execution,
                        parameters={
                            "restraint_force_constant_kcal_mol_a2": (
                                request.relaxation.restraint_force_constant_kcal_mol_a2
                            ),
                            "max_iterations": request.relaxation.max_iterations,
                            "max_restrained_atom_displacement_angstrom": (
                                max_displacement_angstrom
                            ),
                            "tolerance_angstrom": _RESTRAINED_ATOM_TOLERANCE_ANGSTROM,
                            "raw_logs": log_files,
                        },
                    )
                )
                current_pdb = relaxed_path

        status = ReceptorPreparationStatus.SELECTED
        display_output = outputs[-1]
        pqr_path: Path | None = None
        pqr_output: ReceptorOutputArtifact | None = None
        if request.protonation.enabled:
            pqr_path = receptor_store.output_path(receptor_id, "protonated_receptor.pqr")
            protonated_pdb_path = receptor_store.output_path(
                receptor_id, "protonated_receptor.pdb"
            )
            execution, tool_version = run_pdb2pqr_propka(
                input_path=current_pdb,
                pqr_output_path=pqr_path,
                pdb_output_path=protonated_pdb_path,
                ph=request.protonation.ph,
                force_field=request.protonation.force_field,
            )
            log_files = _save_execution_logs(
                receptor_store,
                receptor_id,
                "pdb2pqr-propka",
                execution,
                additional_files=[pqr_path.with_suffix(".log")],
            )
            applied_terminal_additions = _assert_heavy_atoms_unchanged(
                input_path=current_pdb,
                output_path=protonated_pdb_path,
                execution=execution,
                authorized_terminal_additions=(
                    request.protonation.authorized_terminal_heavy_atom_additions
                ),
            )
            pqr_output = _record_output(
                receptor_id=receptor_id,
                path=pqr_path,
                stage=ReceptorOutputStage.PROTONATED_PQR,
                format_name="pqr",
                created_at=datetime.now(UTC),
            )
            pdb_output = _record_output(
                receptor_id=receptor_id,
                path=protonated_pdb_path,
                stage=ReceptorOutputStage.PROTONATED_PDB,
                format_name=StructureFormat.PDB,
                created_at=datetime.now(UTC),
            )
            outputs.extend((pqr_output, pdb_output))
            provenance.append(
                _tool_event(
                    receptor_id=receptor_id,
                    event_type="receptor_protonated",
                    input_artifact=display_output.artifact_id,
                    output_artifact=pqr_output.artifact_id,
                    tool_name="PDB2PQR/PROPKA",
                    tool_version=tool_version,
                    execution=execution,
                    parameters={
                        "ph": request.protonation.ph,
                        "force_field": request.protonation.force_field,
                        "authorized_terminal_heavy_atom_additions": [
                            item.model_dump(mode="json")
                            for item in (
                                request.protonation
                                .authorized_terminal_heavy_atom_additions
                            )
                        ],
                        "applied_terminal_heavy_atom_additions": (
                            applied_terminal_additions
                        ),
                        "raw_logs": log_files,
                    },
                )
            )
            status = ReceptorPreparationStatus.PROTONATED
            display_output = pdb_output

        if request.generate_pdbqt:
            if pqr_path is None or pqr_output is None:
                raise AnkoraDomainError(
                    code="RECEPTOR_PDBQT_REQUIRES_PROTONATION",
                    stage="receptor_preparation",
                    message=(
                        "Generating a receptor PDBQT requires PDB2PQR/PROPKA "
                        "protonation to have run first."
                    ),
                    status_code=422,
                    details={"receptor_id": receptor_id},
                )
            meeko_input_content, normalized_line_count = _normalize_pqr_for_meeko(
                pqr_path.read_bytes()
            )
            meeko_input_path = receptor_store.write_bytes(
                receptor_id,
                "meeko_input_receptor.pqr",
                meeko_input_content,
            )
            meeko_input_output = _record_output(
                receptor_id=receptor_id,
                path=meeko_input_path,
                stage=ReceptorOutputStage.MEEKO_INPUT_PQR,
                format_name="pqr",
                created_at=datetime.now(UTC),
            )
            outputs.append(meeko_input_output)
            provenance.append(
                ProvenanceEvent(
                    event_id=f"receptor-meeko-pqr-format-{receptor_id}",
                    event_type="receptor_pqr_formatted_for_meeko",
                    timestamp=datetime.now(UTC),
                    input_artifacts=[pqr_output.artifact_id],
                    output_artifacts=[meeko_input_output.artifact_id],
                    tool=ToolIdentity(
                        name="ankora-pqr-compatibility-formatter",
                        version=__version__,
                    ),
                    parameters={
                        "format_only": True,
                        "rule": (
                            "separate a nonblank chain identifier from a compact "
                            "four-digit residue sequence field"
                        ),
                        "normalized_compact_residue_lines": normalized_line_count,
                        "source_pqr_sha256": pqr_output.sha256,
                        "meeko_input_pqr_sha256": meeko_input_output.sha256,
                    },
                )
            )
            pdbqt_path = receptor_store.output_path(receptor_id, "prepared_receptor.pdbqt")
            try:
                execution, tool_version = run_meeko_receptor(
                    input_pqr_path=meeko_input_path,
                    output_pdbqt_path=pdbqt_path,
                )
            except AnkoraDomainError as error:
                error.details.update(
                    {
                        "source_pqr_artifact_id": pqr_output.artifact_id,
                        "source_pqr_sha256": pqr_output.sha256,
                        "meeko_input_pqr_artifact_id": meeko_input_output.artifact_id,
                        "meeko_input_pqr_sha256": meeko_input_output.sha256,
                        "normalized_compact_residue_lines": normalized_line_count,
                    }
                )
                raise
            log_files = _save_execution_logs(
                receptor_store, receptor_id, "meeko", execution
            )
            pdbqt_output = _record_output(
                receptor_id=receptor_id,
                path=pdbqt_path,
                stage=ReceptorOutputStage.PDBQT,
                format_name="pdbqt",
                created_at=datetime.now(UTC),
            )
            outputs.append(pdbqt_output)
            provenance.append(
                _tool_event(
                    receptor_id=receptor_id,
                    event_type="receptor_pdbqt_generated",
                    input_artifact=meeko_input_output.artifact_id,
                    output_artifact=pdbqt_output.artifact_id,
                    tool_name="Meeko",
                    tool_version=tool_version,
                    execution=execution,
                    parameters={"raw_logs": log_files},
                )
            )
            status = ReceptorPreparationStatus.DOCKING_READY

        record = ReceptorPreparationRecord(
            receptor_id=receptor_id,
            source_artifact_id=source_artifact_id,
            created_at=created_at,
            status=status,
            decisions=request,
            outputs=outputs,
            warnings=report.warnings,
            provenance=provenance,
            display_output_artifact_id=display_output.artifact_id,
        )
        receptor_store.save_record(record)
        return record
    except AnkoraDomainError as error:
        error.details["receptor_id"] = receptor_id
        _save_failure(receptor_store, receptor_id, error)
        raise


def _validate_decisions(
    report: ReceptorInspectionReport, request: ReceptorPreparationRequest
) -> tuple[list[ReceptorIssue], dict[str, IssueDecision]]:
    selected_chains = set(request.selected_chains)
    if len(selected_chains) != len(request.selected_chains):
        raise _decision_error("Selected chains must not contain duplicates.")
    unknown_chains = selected_chains - set(report.candidate_chains)
    if unknown_chains:
        raise _decision_error(
            "The preparation plan contains chains that are not polymer candidates.",
            {"unknown_chains": sorted(unknown_chains)},
        )

    expected_components = {
        item.component_id
        for item in report.components
        if item.chain_id in selected_chains
    }
    component_map = {item.component_id: item for item in request.component_decisions}
    if len(component_map) != len(request.component_decisions):
        raise _decision_error("Component decisions must not contain duplicates.")
    if set(component_map) != expected_components:
        raise _decision_error(
            (
                "Every non-water component in the selected chains requires an explicit "
                "keep/remove decision."
            ),
            {
                "missing_component_decisions": sorted(expected_components - set(component_map)),
                "unexpected_component_decisions": sorted(set(component_map) - expected_components),
            },
        )

    selected_issues = [
        issue for issue in report.issues if issue.residue.chain_id in selected_chains
    ]
    expected_issues = {issue.issue_id for issue in selected_issues}
    issue_map = {item.issue_id: item for item in request.issue_decisions}
    if len(issue_map) != len(request.issue_decisions):
        raise _decision_error("Residue decisions must not contain duplicates.")
    if set(issue_map) != expected_issues:
        raise _decision_error(
            "Every reported issue in the selected chains requires an explicit decision.",
            {
                "missing_issue_decisions": sorted(expected_issues - set(issue_map)),
                "unexpected_issue_decisions": sorted(set(issue_map) - expected_issues),
            },
        )
    by_id = {issue.issue_id: issue for issue in selected_issues}
    for issue_id, decision in issue_map.items():
        issue = by_id[issue_id]
        if decision.action not in issue.allowed_actions:
            raise _decision_error(
                "A residue decision requests an unsupported action.",
                {"issue_id": issue_id, "action": decision.action.value},
            )
        if decision.action is ReceptorDecisionAction.MANUAL_REVIEW:
            raise _decision_error(
                "Resolve all residues marked for manual review before applying the plan.",
                {"issue_id": issue_id},
                status_code=409,
            )
        if (
            issue.kind is ReceptorIssueKind.ALTERNATE_LOCATION
            and decision.action is ReceptorDecisionAction.REPAIR
            and decision.selected_altloc not in issue.alternate_locations
        ):
            raise _decision_error(
                "Choose one of the reported alternate-location labels.",
                {
                    "issue_id": issue_id,
                    "allowed_altlocs": issue.alternate_locations,
                },
            )
    if request.protonation.enabled:
        protonation_blockers = [
            issue
            for issue in selected_issues
            if issue.kind
            in {
                ReceptorIssueKind.MISSING_ATOMS,
                ReceptorIssueKind.ALTERNATE_LOCATION,
                ReceptorIssueKind.NONSTANDARD_RESIDUE,
            }
            and issue_map[issue.issue_id].action is ReceptorDecisionAction.LEAVE
        ]
        if protonation_blockers:
            raise AnkoraDomainError(
                code="RECEPTOR_PROTONATION_REQUIRES_RESOLUTION",
                stage="receptor_decisions",
                message=(
                    "Protonation cannot run while incomplete or ambiguous observed "
                    "residues are explicitly left unchanged."
                ),
                status_code=409,
                details={
                    "blocking_issues": [
                        {
                            "issue_id": issue.issue_id,
                            "kind": issue.kind.value,
                            "residue": issue.residue.model_dump(),
                            "selected_action": issue_map[issue.issue_id].action.value,
                            "available_actions": [
                                action.value
                                for action in issue.allowed_actions
                                if action
                                not in {
                                    ReceptorDecisionAction.LEAVE,
                                    ReceptorDecisionAction.MANUAL_REVIEW,
                                }
                            ],
                        }
                        for issue in protonation_blockers
                    ],
                    "possible_actions": [
                        "Repair or remove each listed residue explicitly.",
                        "Disable protonation and create only the structural selection derivative.",
                    ],
                },
            )
    return selected_issues, issue_map


def _build_selected_receptor(
    *,
    content: bytes,
    structure_format: StructureFormat,
    request: ReceptorPreparationRequest,
    issue_decisions: dict[str, IssueDecision],
    issues: list[ReceptorIssue],
) -> bytes:
    structure, _cif_block, _text = _read_structure(content, structure_format)
    while len(structure) > 1:
        del structure[-1]
    model = structure[0]
    selected_chains = set(request.selected_chains)
    component_actions = {
        decision.component_id: decision.action for decision in request.component_decisions
    }
    issues_by_locator: dict[tuple[str, int, str], list[ReceptorIssue]] = {}
    for issue in issues:
        locator = issue.residue
        issues_by_locator.setdefault(
            (locator.chain_id, locator.sequence_number, locator.insertion_code), []
        ).append(issue)

    for chain_index in range(len(model) - 1, -1, -1):
        chain = model[chain_index]
        if chain.name not in selected_chains:
            del model[chain_index]
            continue
        for residue_index in range(len(chain) - 1, -1, -1):
            residue = chain[residue_index]
            locator_key = (
                chain.name,
                _sequence_number(residue),
                _clean_char(residue.seqid.icode),
            )
            residue_issues = issues_by_locator.get(locator_key, [])
            if any(
                issue_decisions[issue.issue_id].action is ReceptorDecisionAction.REMOVE
                for issue in residue_issues
            ):
                del chain[residue_index]
                continue
            if residue.entity_type is not gemmi.EntityType.Polymer:
                if residue.is_water():
                    if request.water_action is ComponentAction.REMOVE:
                        del chain[residue_index]
                    continue
                kind = _heterogen_kind(residue)
                item_id = component_id(
                    kind=kind,
                    chain_id=chain.name,
                    name=residue.name.strip() or "UNK",
                    sequence_number=residue.seqid.num,
                    insertion_code=_clean_char(residue.seqid.icode),
                )
                if component_actions[item_id] is ComponentAction.REMOVE:
                    del chain[residue_index]
                    continue
            repair_atom_names = {
                atom_name
                for issue in residue_issues
                if issue.kind is ReceptorIssueKind.MISSING_ATOMS
                and issue_decisions[issue.issue_id].action
                is ReceptorDecisionAction.REPAIR
                for atom_name in issue.missing_atoms
            }
            # mmCIF's `_pdbx_unobs_or_zero_occ_atoms` can describe atoms that
            # still occur in `_atom_site` with occupancy zero and modelled
            # coordinates. They are not observed coordinates. Leaving those
            # atom names in the PDB makes PDBFixer treat the requested residue
            # as complete and silently repair nothing. Remove only the exact
            # reported atoms for an explicit Repair decision; Leave preserves
            # the source bytes and Remove was handled at residue scope above.
            if repair_atom_names:
                for atom_index in range(len(residue) - 1, -1, -1):
                    if residue[atom_index].name.strip() in repair_atom_names:
                        del residue[atom_index]
            for issue in residue_issues:
                decision = issue_decisions[issue.issue_id]
                if (
                    issue.kind is ReceptorIssueKind.ALTERNATE_LOCATION
                    and decision.action is ReceptorDecisionAction.REPAIR
                ):
                    _select_altloc(residue, decision.selected_altloc)

    pdb_text = structure.make_pdb_string()
    if not pdb_text.strip():
        raise AnkoraDomainError(
            code="EMPTY_RECEPTOR_DERIVATIVE",
            stage="receptor_selection",
            message="The explicit decisions removed every coordinate from the receptor.",
            status_code=422,
        )
    return pdb_text.encode("utf-8")


def _heterogen_kind(residue: gemmi.Residue) -> HeterogenKind:
    atoms = list(residue)
    if len(atoms) == 1 and atoms[0].element.is_metal:
        return HeterogenKind.METAL
    if residue.entity_type is gemmi.EntityType.NonPolymer:
        return HeterogenKind.LIGAND
    return HeterogenKind.OTHER


def _sequence_number(residue: gemmi.Residue) -> int:
    return 0 if residue.seqid.num is None else residue.seqid.num


def _select_altloc(residue: gemmi.Residue, selected_altloc: str | None) -> None:
    if selected_altloc is None:
        raise AnkoraDomainError(
            code="RECEPTOR_ALTLOC_DECISION_MISSING",
            stage="receptor_selection",
            message="An alternate-location residue requires an explicit conformation choice.",
            status_code=422,
            details={"residue": residue.name.strip(), "sequence_number": residue.seqid.num},
        )
    for atom_index in range(len(residue) - 1, -1, -1):
        atom = residue[atom_index]
        altloc = _clean_char(atom.altloc)
        if altloc and altloc != selected_altloc:
            del residue[atom_index]
        elif altloc == selected_altloc:
            atom.altloc = "\x00"


def _assert_heavy_atoms_unchanged(
    *,
    input_path: Path,
    output_path: Path,
    execution: ToolExecution,
    authorized_terminal_additions: list[TerminalHeavyAtomAddition] | None = None,
) -> list[str]:
    before = _heavy_atom_keys(input_path)
    after = _heavy_atom_keys(output_path)
    added = sorted(after - before)
    removed = sorted(before - after)
    authorized = _authorized_terminal_addition_keys(
        input_path, authorized_terminal_additions or []
    )
    applied_authorizations = sorted(set(added) & authorized)
    unapproved_added = sorted(set(added) - authorized)
    if not unapproved_added and not removed:
        return applied_authorizations
    raise AnkoraDomainError(
        code="PDB2PQR_UNAPPROVED_HEAVY_ATOM_CHANGE",
        stage="receptor_protonation",
        message=(
            "PDB2PQR changed heavy atoms beyond the explicit receptor plan; "
            "the protonated derivative was rejected."
        ),
        status_code=422,
        details={
            "command": execution.command,
            "exit_code": execution.exit_code,
            "added_heavy_atoms": added,
            "authorized_terminal_heavy_atom_additions": sorted(authorized),
            "applied_terminal_heavy_atom_additions": applied_authorizations,
            "unapproved_added_heavy_atoms": unapproved_added,
            "removed_heavy_atoms": removed,
            "stdout": execution.stdout,
            "stderr": execution.stderr,
            "possible_actions": [
                "Return to the receptor report and resolve the affected residues.",
                "Inspect the preserved PDB2PQR logs and rejected derivative files.",
            ],
        },
    )


def _authorized_terminal_addition_keys(
    input_path: Path, additions: list[TerminalHeavyAtomAddition]
) -> set[str]:
    if not additions:
        return set()
    structure = gemmi.read_structure(str(input_path))
    if not structure:
        raise _terminal_addition_error("The receptor contains no coordinate model.")
    model = structure[0]
    keys: set[str] = set()
    for addition in additions:
        chain = model.find_chain(addition.chain_id)
        if chain is None:
            raise _terminal_addition_error(
                "The authorized terminal atom names a chain absent from the receptor.",
                addition,
            )
        polymer_residues = [residue for residue in chain if residue.het_flag == "A"]
        if not polymer_residues:
            raise _terminal_addition_error(
                "The authorized chain contains no polymer residue.", addition
            )
        terminal = polymer_residues[-1]
        terminal_identity = (
            _canonical_residue_name(terminal.name.strip()),
            _sequence_number(terminal),
            _clean_char(terminal.seqid.icode),
        )
        requested_identity = (
            _canonical_residue_name(addition.residue_name),
            addition.sequence_number,
            addition.insertion_code,
        )
        if requested_identity != terminal_identity:
            raise _terminal_addition_error(
                (
                    "The authorized OXT addition does not name the final polymer "
                    "residue of its selected chain."
                ),
                addition,
                terminal={
                    "chain_id": addition.chain_id,
                    "residue_name": terminal_identity[0],
                    "sequence_number": terminal_identity[1],
                    "insertion_code": terminal_identity[2],
                },
            )
        atom_names = {atom.name.strip() for atom in terminal}
        if addition.atom_name in atom_names:
            raise _terminal_addition_error(
                "The authorized terminal atom already exists in the receptor.", addition
            )
        keys.add(
            "|".join(
                (
                    addition.chain_id,
                    terminal_identity[0],
                    str(terminal_identity[1]),
                    terminal_identity[2],
                    addition.atom_name,
                )
            )
        )
    return keys


def _terminal_addition_error(
    message: str,
    addition: TerminalHeavyAtomAddition | None = None,
    **details: object,
) -> AnkoraDomainError:
    if addition is not None:
        details["authorization"] = addition.model_dump(mode="json")
    return AnkoraDomainError(
        code="RECEPTOR_TERMINAL_ADDITION_INVALID",
        stage="receptor_protonation",
        message=message,
        status_code=422,
        details=details,
    )


# PDB2PQR renames residues to forcefield-specific protonation-state variants
# (e.g. AMBER/CHARMM histidine tautomers, protonated acidic residues) without
# changing the underlying heavy-atom set. The identity check must compare
# canonical residue names, not these labels, or it rejects every protonated
# histidine/aspartate/glutamate/cysteine/lysine as an unapproved change.
_PROTONATION_VARIANT_RESIDUE_NAMES: dict[str, str] = {
    "HID": "HIS", "HIE": "HIS", "HIP": "HIS",
    "HSD": "HIS", "HSE": "HIS", "HSP": "HIS",
    "ASH": "ASP",
    "GLH": "GLU",
    "CYX": "CYS", "CYM": "CYS",
    "LYN": "LYS",
}


def _canonical_residue_name(name: str) -> str:
    return _PROTONATION_VARIANT_RESIDUE_NAMES.get(name, name)


def _heavy_atom_keys(path: Path) -> set[str]:
    structure = gemmi.read_structure(str(path))
    keys: set[str] = set()
    for model in structure:
        for chain in model:
            for residue in chain:
                sequence_number = _sequence_number(residue)
                insertion_code = _clean_char(residue.seqid.icode)
                residue_name = _canonical_residue_name(residue.name.strip())
                for atom in residue:
                    if atom.element.is_hydrogen:
                        continue
                    keys.add(
                        "|".join(
                            (
                                chain.name,
                                residue_name,
                                str(sequence_number),
                                insertion_code,
                                atom.name.strip(),
                            )
                        )
                    )
    return keys


# How far a previously observed heavy atom may move while OpenMM relaxes the
# atoms PDBFixer just placed. Exceeding it means the restraint failed to hold
# against a clash too severe to resolve safely - the derivative is rejected
# rather than silently accepted with a displaced original atom.
_RESTRAINED_ATOM_TOLERANCE_ANGSTROM = 0.5


def _heavy_atom_positions(path: Path) -> dict[str, tuple[float, float, float]]:
    structure = gemmi.read_structure(str(path))
    positions: dict[str, tuple[float, float, float]] = {}
    for model in structure:
        for chain in model:
            for residue in chain:
                sequence_number = _sequence_number(residue)
                insertion_code = _clean_char(residue.seqid.icode)
                residue_name = _canonical_residue_name(residue.name.strip())
                for atom in residue:
                    if atom.element.is_hydrogen:
                        continue
                    key = "|".join(
                        (
                            chain.name,
                            residue_name,
                            str(sequence_number),
                            insertion_code,
                            atom.name.strip(),
                        )
                    )
                    positions[key] = (atom.pos.x, atom.pos.y, atom.pos.z)
        break  # only the first model; relaxation never touches alternate models
    return positions


def _assert_restrained_atoms_stable(*, original_path: Path, relaxed_path: Path) -> float:
    original = _heavy_atom_positions(original_path)
    relaxed = _heavy_atom_positions(relaxed_path)
    max_displacement = 0.0
    for key, original_position in original.items():
        relaxed_position = relaxed.get(key)
        if relaxed_position is None:
            continue
        displacement = sum(
            (a - b) ** 2 for a, b in zip(original_position, relaxed_position, strict=True)
        ) ** 0.5
        max_displacement = max(max_displacement, displacement)
    if max_displacement > _RESTRAINED_ATOM_TOLERANCE_ANGSTROM:
        raise AnkoraDomainError(
            code="RECEPTOR_RELAXATION_TOLERANCE_EXCEEDED",
            stage="receptor_relaxation",
            message=(
                "Relaxation moved a previously observed atom beyond the allowed "
                f"{_RESTRAINED_ATOM_TOLERANCE_ANGSTROM} Å tolerance; the clash "
                "was too severe to resolve safely. Review or remove the affected "
                "residue instead."
            ),
            status_code=422,
            details={
                "max_displacement_angstrom": max_displacement,
                "tolerance_angstrom": _RESTRAINED_ATOM_TOLERANCE_ANGSTROM,
            },
        )
    return max_displacement


def _record_output(
    *,
    receptor_id: str,
    path: Path,
    stage: ReceptorOutputStage,
    format_name: StructureFormat | str,
    created_at: datetime,
) -> ReceptorOutputArtifact:
    content = path.read_bytes()
    artifact_id = str(uuid4())
    return ReceptorOutputArtifact(
        artifact_id=artifact_id,
        stage=stage,
        filename=path.name,
        format=format_name,
        sha256=hashlib.sha256(content).hexdigest(),
        size_bytes=len(content),
        created_at=created_at,
        content_url=f"/receptors/{receptor_id}/outputs/{artifact_id}/content",
    )


def _normalize_pqr_for_meeko(content: bytes) -> tuple[bytes, int]:
    """Separate compact four-digit PQR residue fields without changing chemistry.

    PDB2PQR preserves PDB-style fixed columns, so chain A followed by residue 1000
    is written as ``A1000``. Meeko 0.7.1 tokenizes PQR records on whitespace and
    therefore cannot distinguish the chain from the residue number. The exact
    tool input is preserved as a separate artifact; this formatter only inserts
    one ASCII space at that boundary.
    """
    normalized_lines: list[bytes] = []
    normalized_count = 0
    for line in content.splitlines(keepends=True):
        body = line.rstrip(b"\r\n")
        newline = line[len(body) :]
        record_name = body[:6].strip()
        chain_id = body[21:22]
        residue_sequence = body[22:26]
        if (
            record_name in {b"ATOM", b"HETATM"}
            and len(body) >= 26
            and chain_id.strip()
            and len(residue_sequence) == 4
            and residue_sequence.isdigit()
        ):
            rewritten = body[:22] + b" " + body[22:]
            before_tokens = body.split()
            after_tokens = rewritten.split()
            expected_tokens = (
                before_tokens[:4]
                + [chain_id, residue_sequence]
                + before_tokens[5:]
            )
            if len(before_tokens) < 6 or after_tokens != expected_tokens:
                raise AnkoraDomainError(
                    code="MEEKO_PQR_FORMAT_NORMALIZATION_FAILED",
                    stage="receptor_pdbqt",
                    message=(
                        "Ankora could not prove that Meeko PQR normalization was "
                        "format-only, so the receptor was not passed to Meeko."
                    ),
                    status_code=422,
                    details={
                        "line_number": len(normalized_lines) + 1,
                        "record_name": record_name.decode("ascii", errors="replace"),
                    },
                )
            body = rewritten
            normalized_count += 1
        normalized_lines.append(body + newline)
    return b"".join(normalized_lines), normalized_count


def _save_execution_logs(
    store: ReceptorArtifactStore,
    receptor_id: str,
    prefix: str,
    execution: ToolExecution,
    additional_files: list[Path] | None = None,
) -> list[str]:
    stdout_name = f"{prefix}.stdout.log"
    stderr_name = f"{prefix}.stderr.log"
    store.write_text(receptor_id, stdout_name, execution.stdout)
    store.write_text(receptor_id, stderr_name, execution.stderr)
    recorded = [stdout_name, stderr_name]
    for path in additional_files or []:
        if path.is_file():
            recorded.append(path.name)
    return recorded


def _tool_event(
    *,
    receptor_id: str,
    event_type: str,
    input_artifact: str,
    output_artifact: str,
    tool_name: str,
    tool_version: str,
    execution: ToolExecution,
    parameters: dict[str, object],
) -> ProvenanceEvent:
    return ProvenanceEvent(
        event_id=f"{event_type}-{receptor_id}",
        event_type=event_type,
        timestamp=datetime.now(UTC),
        input_artifacts=[input_artifact],
        output_artifacts=[output_artifact],
        tool=ToolIdentity(name=tool_name, version=tool_version),
        parameters=parameters,
        command=execution.command,
    )


def _save_failure(
    store: ReceptorArtifactStore, receptor_id: str, error: AnkoraDomainError
) -> None:
    details = {
        "code": error.code,
        "stage": error.stage,
        "message": error.message,
        "details": error.details,
        "recoverable": error.recoverable,
        "recorded_at": datetime.now(UTC).isoformat(),
        "ankora_version": __version__,
    }
    stdout = error.details.get("stdout")
    stderr = error.details.get("stderr")
    if isinstance(stdout, str):
        store.write_text(receptor_id, "failed-tool.stdout.log", stdout)
    if isinstance(stderr, str):
        store.write_text(receptor_id, "failed-tool.stderr.log", stderr)
    store.write_text(
        receptor_id,
        "failure.json",
        json.dumps(details, indent=2, ensure_ascii=False) + "\n",
    )


def _decision_error(
    message: str,
    details: dict[str, object] | None = None,
    *,
    status_code: int = 422,
) -> AnkoraDomainError:
    return AnkoraDomainError(
        code="RECEPTOR_DECISIONS_INCOMPLETE",
        stage="receptor_decisions",
        message=message,
        status_code=status_code,
        details=details,
    )
