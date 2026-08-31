"""Read-only receptor inspection with residue-level M2 decisions."""

import re
from collections import defaultdict
from datetime import UTC, datetime

import gemmi

from ankora_backend import __version__
from ankora_backend.domain.errors import AnkoraDomainError
from ankora_backend.persistence.artifact_store import StructureArtifactStore
from ankora_backend.schemas.provenance import ProvenanceEvent, ToolIdentity
from ankora_backend.schemas.receptors import (
    ReceptorComponent,
    ReceptorDecisionAction,
    ReceptorInspectionReport,
    ReceptorIssue,
    ReceptorIssueKind,
    ReceptorIssueSeverity,
    ResidueLocator,
)
from ankora_backend.schemas.structures import HeterogenKind, StructureFormat
from ankora_backend.schemas.warnings import StructuredWarning, WarningCode

NEAR_REFERENCE_CUTOFF_ANGSTROM = 8.0

_PDB_MISSING_RESIDUE = re.compile(
    r"^REMARK 465\s+(?:\d+\s+)?(?P<name>[A-Z0-9]{3})\s+(?P<chain>\S)\s+"
    r"(?P<number>-?\d+)(?P<icode>[A-Z]?)\s*$"
)
_PDB_MISSING_ATOMS = re.compile(
    r"^REMARK 470\s+(?:\d+\s+)?(?P<name>[A-Z0-9]{3})\s+(?P<chain>\S)\s+"
    r"(?P<number>-?\d+)(?P<icode>[A-Z]?)\s+(?P<atoms>.+)$"
)


def component_id(
    *,
    kind: HeterogenKind,
    chain_id: str,
    name: str,
    sequence_number: int | None,
    insertion_code: str,
) -> str:
    number = "?" if sequence_number is None else str(sequence_number)
    return "|".join((kind.value, chain_id, name, number, insertion_code))


def inspect_receptor(
    *,
    artifact_id: str,
    store: StructureArtifactStore,
    reference_component_id: str | None = None,
) -> ReceptorInspectionReport:
    record = store.load_record(artifact_id)
    content = store.content_path(artifact_id).read_bytes()
    structure, cif_block, text = _read_structure(content, record.artifact.format)
    model = structure[0]

    components = [
        ReceptorComponent(
            component_id=component_id(
                kind=item.kind,
                chain_id=item.chain_id,
                name=item.name,
                sequence_number=item.sequence_number,
                insertion_code=item.insertion_code,
            ),
            name=item.name,
            chain_id=item.chain_id,
            sequence_number=item.sequence_number,
            insertion_code=item.insertion_code,
            atom_count=item.atom_count,
            kind=item.kind,
        )
        for item in record.metadata.heterogens
        if item.kind is not HeterogenKind.WATER
    ]
    water_count = sum(
        item.kind is HeterogenKind.WATER for item in record.metadata.heterogens
    )
    reference_positions = _reference_positions(model, components, reference_component_id)
    raw_issues = _reported_coordinate_issues(text, cif_block)
    raw_issues.extend(_alternate_location_issues(model))
    raw_issues.extend(_nonstandard_residue_issues(model))
    issues = [
        _build_issue(model=model, raw=raw, reference_positions=reference_positions)
        for raw in sorted(raw_issues, key=_issue_sort_key)
    ]
    warnings = [_issue_warning(issue) for issue in issues]
    generated_at = datetime.now(UTC)
    provenance = ProvenanceEvent(
        event_id=f"receptor-inspection-{artifact_id}-{generated_at.timestamp()}",
        event_type="receptor_inspected",
        timestamp=generated_at,
        input_artifacts=[artifact_id],
        tool=ToolIdentity(name="ankora-receptor-inspector", version=__version__),
        parameters={
            "reference_component_id": reference_component_id,
            "near_reference_cutoff_angstrom": NEAR_REFERENCE_CUTOFF_ANGSTROM,
            "coordinate_model": 1,
        },
        warnings=warnings,
    )
    return ReceptorInspectionReport(
        source_artifact_id=artifact_id,
        generated_at=generated_at,
        candidate_chains=[
            chain.chain_id
            for chain in record.metadata.chains
            if chain.polymer_residue_count > 0
        ],
        components=components,
        water_count=water_count,
        issues=issues,
        reference_component_id=reference_component_id,
        near_reference_cutoff_angstrom=NEAR_REFERENCE_CUTOFF_ANGSTROM,
        warnings=warnings,
        provenance=provenance,
    )


def _read_structure(
    content: bytes, structure_format: StructureFormat
) -> tuple[gemmi.Structure, gemmi.cif.Block | None, str]:
    text = content.decode("utf-8-sig")
    if structure_format is StructureFormat.PDB:
        structure = gemmi.read_pdb_string(content)
        cif_block = None
    else:
        document = gemmi.cif.read_string(text)
        cif_block = document.sole_block()
        structure = gemmi.make_structure_from_block(cif_block)
    structure.setup_entities()
    return structure, cif_block, text


class _RawIssue:
    def __init__(
        self,
        *,
        kind: ReceptorIssueKind,
        locator: ResidueLocator,
        missing_atoms: list[str] | None = None,
        alternate_locations: list[str] | None = None,
    ) -> None:
        self.kind = kind
        self.locator = locator
        self.missing_atoms = missing_atoms or []
        self.alternate_locations = alternate_locations or []


def _reported_coordinate_issues(
    text: str, cif_block: gemmi.cif.Block | None
) -> list[_RawIssue]:
    if cif_block is None:
        return _pdb_reported_issues(text)
    issues: list[_RawIssue] = []
    issues.extend(
        _cif_grouped_issues(
            cif_block,
            prefix="_pdbx_unobs_or_zero_occ_atoms.",
            kind=ReceptorIssueKind.MISSING_ATOMS,
            atom_column="auth_atom_id",
        )
    )
    issues.extend(
        _cif_grouped_issues(
            cif_block,
            prefix="_pdbx_unobs_or_zero_occ_residues.",
            kind=ReceptorIssueKind.MISSING_RESIDUE,
            atom_column=None,
        )
    )
    return issues


def _pdb_reported_issues(text: str) -> list[_RawIssue]:
    issues: list[_RawIssue] = []
    for line in text.splitlines():
        missing_residue = _PDB_MISSING_RESIDUE.match(line)
        if missing_residue:
            issues.append(
                _RawIssue(
                    kind=ReceptorIssueKind.MISSING_RESIDUE,
                    locator=_locator_from_match(missing_residue),
                )
            )
            continue
        missing_atoms = _PDB_MISSING_ATOMS.match(line)
        if missing_atoms:
            issues.append(
                _RawIssue(
                    kind=ReceptorIssueKind.MISSING_ATOMS,
                    locator=_locator_from_match(missing_atoms),
                    missing_atoms=missing_atoms.group("atoms").split(),
                )
            )
    return issues


def _locator_from_match(match: re.Match[str]) -> ResidueLocator:
    return ResidueLocator(
        chain_id=match.group("chain"),
        residue_name=match.group("name"),
        sequence_number=int(match.group("number")),
        insertion_code=match.group("icode") or "",
    )


def _cif_grouped_issues(
    block: gemmi.cif.Block,
    *,
    prefix: str,
    kind: ReceptorIssueKind,
    atom_column: str | None,
) -> list[_RawIssue]:
    category = block.get_mmcif_category(prefix)
    if not category:
        return []
    row_count = len(next(iter(category.values()), []))
    grouped: dict[tuple[str, str, int, str], list[str]] = defaultdict(list)
    for index in range(row_count):
        chain = _cif_cell(category, "auth_asym_id", index)
        name = _cif_cell(category, "auth_comp_id", index)
        number_text = _cif_cell(category, "auth_seq_id", index)
        if not chain or not name or not number_text:
            continue
        insertion_code = _cif_cell(category, "PDB_ins_code", index)
        key = (chain, name, int(number_text), insertion_code)
        if atom_column:
            atom_name = _cif_cell(category, atom_column, index)
            if atom_name:
                grouped[key].append(atom_name)
        else:
            grouped.setdefault(key, [])
    return [
        _RawIssue(
            kind=kind,
            locator=ResidueLocator(
                chain_id=chain,
                residue_name=name,
                sequence_number=number,
                insertion_code=insertion_code,
            ),
            missing_atoms=sorted(set(atoms)),
        )
        for (chain, name, number, insertion_code), atoms in grouped.items()
    ]


def _cif_cell(category: dict[str, list[str]], column: str, index: int) -> str:
    values = category.get(column, [])
    if index >= len(values):
        return ""
    value = values[index]
    return "" if value in {None, "", ".", "?"} else str(value).strip()


def _alternate_location_issues(model: gemmi.Model) -> list[_RawIssue]:
    issues: list[_RawIssue] = []
    seen: set[tuple[str, int, str]] = set()
    for chain in model:
        for residue in chain:
            sequence_number = residue.seqid.num
            if sequence_number is None:
                continue
            labels = sorted(
                {_clean_char(atom.altloc) for atom in residue if _clean_char(atom.altloc)}
            )
            key = (chain.name, sequence_number, _clean_char(residue.seqid.icode))
            if labels and key not in seen:
                seen.add(key)
                issues.append(
                    _RawIssue(
                        kind=ReceptorIssueKind.ALTERNATE_LOCATION,
                        locator=ResidueLocator(
                            chain_id=chain.name,
                            residue_name=residue.name.strip() or "UNK",
                            sequence_number=sequence_number,
                            insertion_code=_clean_char(residue.seqid.icode),
                        ),
                        alternate_locations=labels,
                    )
                )
    return issues


def _nonstandard_residue_issues(model: gemmi.Model) -> list[_RawIssue]:
    issues: list[_RawIssue] = []
    for chain in model:
        for residue in chain:
            if residue.entity_type is not gemmi.EntityType.Polymer:
                continue
            sequence_number = residue.seqid.num
            if sequence_number is None:
                continue
            residue_info = gemmi.find_tabulated_residue(residue.name)
            if residue_info.is_standard():
                continue
            issues.append(
                _RawIssue(
                    kind=ReceptorIssueKind.NONSTANDARD_RESIDUE,
                    locator=ResidueLocator(
                        chain_id=chain.name,
                        residue_name=residue.name.strip() or "UNK",
                        sequence_number=sequence_number,
                        insertion_code=_clean_char(residue.seqid.icode),
                    ),
                )
            )
    return issues


def _reference_positions(
    model: gemmi.Model,
    components: list[ReceptorComponent],
    reference_component_id: str | None,
) -> list[gemmi.Position]:
    if reference_component_id is None:
        return []
    component = next(
        (item for item in components if item.component_id == reference_component_id), None
    )
    if component is None:
        raise AnkoraDomainError(
            code="RECEPTOR_REFERENCE_COMPONENT_NOT_FOUND",
            stage="receptor_inspection",
            message="The selected pocket reference is not present in this structure.",
            status_code=422,
            details={"reference_component_id": reference_component_id},
        )
    positions: list[gemmi.Position] = []
    for chain in model:
        if chain.name != component.chain_id:
            continue
        for residue in chain:
            if (
                residue.name.strip() == component.name
                and residue.seqid.num == component.sequence_number
                and _clean_char(residue.seqid.icode) == component.insertion_code
            ):
                positions.extend(atom.pos for atom in residue)
    return positions


def _build_issue(
    *, model: gemmi.Model, raw: _RawIssue, reference_positions: list[gemmi.Position]
) -> ReceptorIssue:
    observed_positions = _residue_positions(model, raw.locator)
    distance = _minimum_distance(observed_positions, reference_positions)
    severity = (
        ReceptorIssueSeverity.UNASSESSED
        if not reference_positions or distance is None
        else ReceptorIssueSeverity.NEAR_REFERENCE
        if distance <= NEAR_REFERENCE_CUTOFF_ANGSTROM
        else ReceptorIssueSeverity.REMOTE
    )
    allowed_actions = [
        ReceptorDecisionAction.LEAVE,
        ReceptorDecisionAction.REMOVE,
        ReceptorDecisionAction.MANUAL_REVIEW,
    ]
    if raw.kind in {ReceptorIssueKind.MISSING_ATOMS, ReceptorIssueKind.ALTERNATE_LOCATION}:
        allowed_actions.insert(1, ReceptorDecisionAction.REPAIR)
    locator = raw.locator
    issue_id = "|".join(
        (
            raw.kind.value,
            locator.chain_id,
            locator.residue_name,
            str(locator.sequence_number),
            locator.insertion_code,
        )
    )
    return ReceptorIssue(
        issue_id=issue_id,
        kind=raw.kind,
        residue=locator,
        missing_atoms=raw.missing_atoms,
        alternate_locations=raw.alternate_locations,
        distance_to_reference_angstrom=distance,
        severity=severity,
        allowed_actions=allowed_actions,
        message=_issue_message(raw),
    )


def _issue_message(raw: _RawIssue) -> str:
    if raw.kind is ReceptorIssueKind.MISSING_RESIDUE:
        return "The source reports this residue without observed coordinates."
    if raw.kind is ReceptorIssueKind.MISSING_ATOMS:
        atoms = ", ".join(raw.missing_atoms)
        return f"The source reports missing atoms: {atoms}."
    if raw.kind is ReceptorIssueKind.ALTERNATE_LOCATION:
        labels = ", ".join(raw.alternate_locations)
        return f"Observed atoms use alternate locations: {labels}."
    return "This polymer residue is not a standard tabulated residue."


def _residue_positions(model: gemmi.Model, locator: ResidueLocator) -> list[gemmi.Position]:
    positions: list[gemmi.Position] = []
    for chain in model:
        if chain.name != locator.chain_id:
            continue
        for residue in chain:
            if (
                residue.seqid.num == locator.sequence_number
                and _clean_char(residue.seqid.icode) == locator.insertion_code
            ):
                positions.extend(atom.pos for atom in residue)
    return positions


def _minimum_distance(
    first: list[gemmi.Position], second: list[gemmi.Position]
) -> float | None:
    if not first or not second:
        return None
    return min(position.dist(reference) for position in first for reference in second)


def _issue_warning(issue: ReceptorIssue) -> StructuredWarning:
    if issue.kind is ReceptorIssueKind.MISSING_RESIDUE:
        code = WarningCode.REC_MISSING_RESIDUE
    elif issue.kind is ReceptorIssueKind.ALTERNATE_LOCATION:
        code = WarningCode.REC_ALTERNATE_LOCATION
    elif issue.kind is ReceptorIssueKind.NONSTANDARD_RESIDUE:
        code = WarningCode.REC_NONSTANDARD_RESIDUE
    elif issue.severity is ReceptorIssueSeverity.NEAR_REFERENCE:
        code = WarningCode.REC_NEAR_POCKET_GAP
    elif issue.severity is ReceptorIssueSeverity.REMOTE:
        code = WarningCode.REC_REMOTE_INCOMPLETE_RESIDUE
    else:
        code = WarningCode.REC_MISSING_SIDECHAIN
    return StructuredWarning(
        code=code,
        message=issue.message,
        stage="receptor_inspection",
        details={
            "issue_id": issue.issue_id,
            "residue": issue.residue.model_dump(),
            "distance_to_reference_angstrom": issue.distance_to_reference_angstrom,
            "severity": issue.severity.value,
        },
    )


def _issue_sort_key(issue: _RawIssue) -> tuple[str, int, str, str]:
    locator = issue.locator
    return (locator.chain_id, locator.sequence_number, locator.insertion_code, issue.kind.value)


def _clean_char(value: str) -> str:
    return "" if value in {"\x00", " ", ".", "?"} else value
