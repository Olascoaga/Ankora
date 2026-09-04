"""Interpret PROPKA evidence without confusing a prediction with a decision."""

import hashlib
from datetime import UTC, datetime
from pathlib import Path

import gemmi

from ankora_backend.domain.errors import AnkoraDomainError
from ankora_backend.persistence.artifact_store import StructureArtifactStore
from ankora_backend.schemas.receptors import (
    ProtonationDecisionSource,
    ProtonationMetalContact,
    ProtonationOverride,
    ReceptorComponent,
    ReceptorInspectionReport,
    ReceptorProtonationAnalysis,
    ReceptorProtonationProposal,
    ResidueLocator,
)
from ankora_backend.schemas.structures import HeterogenKind
from ankora_backend.services.receptor_inspection import (
    _clean_char,
    _minimum_distance,
    _read_structure,
    _reference_positions,
    _residue_positions,
)

METAL_WARNING_CUTOFF_ANGSTROM = 4.0
_SIDECHAIN_GROUPS = {"ARG", "ASP", "CYS", "GLU", "HIS", "LYS", "TYR"}


def build_protonation_analysis(
    *,
    source_artifact_id: str,
    input_path: Path,
    inspection: ReceptorInspectionReport,
    structure_store: StructureArtifactStore,
    worker_report: dict[str, object],
    ph: float,
    force_field: str,
    tool_version: str,
    overrides: list[ProtonationOverride],
) -> ReceptorProtonationAnalysis:
    predictions = worker_report.get("predictions")
    if not isinstance(predictions, list):
        raise _analysis_error("The structured PDB2PQR report has no prediction rows.")

    source_record = structure_store.load_record(source_artifact_id)
    source_content = structure_store.content_path(source_artifact_id).read_bytes()
    structure, _, _ = _read_structure(source_content, source_record.artifact.format)
    model = structure[0]
    reference_positions = _reference_positions(
        model, inspection.components, inspection.reference_component_id
    )
    metal_positions = _metal_positions(model, inspection)
    terminal_identities = _terminal_identities(input_path)
    override_map = {_identity(item.residue): item.state for item in overrides}
    matched_overrides: set[tuple[str, str, int, str]] = set()

    proposals: list[ReceptorProtonationProposal] = []
    for raw in predictions:
        if not isinstance(raw, dict):
            raise _analysis_error("A PDB2PQR prediction row is not an object.")
        proposal = _proposal_from_row(
            raw=raw,
            model=model,
            reference_positions=reference_positions,
            metal_positions=metal_positions,
            terminal_identities=terminal_identities,
            ph=ph,
            force_field=force_field,
            override_map=override_map,
            near_reference_cutoff_angstrom=inspection.near_reference_cutoff_angstrom,
        )
        if proposal is None:
            continue
        if proposal.decision_source is ProtonationDecisionSource.SCIENTIST_OVERRIDE:
            matched_overrides.add(_identity(proposal.residue))
        proposals.append(proposal)

    unmatched = set(override_map) - matched_overrides
    if unmatched:
        raise _analysis_error(
            "One or more protonation overrides did not match a titratable residue.",
            {"unmatched_overrides": [list(item) for item in sorted(unmatched)]},
        )
    return ReceptorProtonationAnalysis(
        generated_at=datetime.now(UTC),
        input_sha256=hashlib.sha256(input_path.read_bytes()).hexdigest(),
        target_ph=ph,
        force_field=force_field,
        tool_version=tool_version,
        proposals=sorted(
            proposals,
            key=lambda item: (
                item.residue.chain_id,
                item.residue.sequence_number,
                item.residue.insertion_code,
                item.group_label,
            ),
        ),
        reference_component_id=inspection.reference_component_id,
        near_reference_cutoff_angstrom=inspection.near_reference_cutoff_angstrom,
        metal_warning_cutoff_angstrom=METAL_WARNING_CUTOFF_ANGSTROM,
    )


def validate_protonation_overrides(
    *, input_path: Path, force_field: str, overrides: list[ProtonationOverride]
) -> None:
    if not overrides:
        return
    if force_field.upper() != "AMBER":
        raise _analysis_error(
            "Explicit protonation overrides are currently validated only for AMBER."
        )
    terminal_identities = _terminal_identities(input_path)
    supported = {
        "ASP": {"ASP", "ASH"},
        "GLU": {"GLU", "GLH"},
        "CYS": {"CYS", "CYM"},
        "HIS": {"HIS_NEUTRAL_AUTO", "HIP"},
        "LYS": {"LYS", "LYN"},
    }
    for override in overrides:
        residue = override.residue
        identity = _identity(residue)
        if residue.insertion_code:
            raise _analysis_error(
                "PDB2PQR cannot safely address an override with an insertion code.",
                {"residue": residue.model_dump(mode="json")},
            )
        allowed = supported.get(residue.residue_name, set())
        if override.state not in allowed:
            raise _analysis_error(
                "The requested protonation state is not supported for this AMBER residue.",
                {
                    "residue": residue.model_dump(mode="json"),
                    "requested_state": override.state,
                    "allowed_states": sorted(allowed),
                },
            )
        if identity in terminal_identities and override.state in {"ASH", "GLH", "LYN"}:
            raise _analysis_error(
                "AMBER/PDB2PQR cannot safely apply this state at a chain terminus.",
                {
                    "residue": residue.model_dump(mode="json"),
                    "requested_state": override.state,
                },
            )


def _proposal_from_row(
    *,
    raw: dict[object, object],
    model: gemmi.Model,
    reference_positions: list[gemmi.Position],
    metal_positions: list[tuple[ReceptorComponent, list[gemmi.Position]]],
    terminal_identities: set[tuple[str, str, int, str]],
    ph: float,
    force_field: str,
    override_map: dict[tuple[str, str, int, str], str],
    near_reference_cutoff_angstrom: float,
) -> ReceptorProtonationProposal | None:
    try:
        residue = ResidueLocator(
            chain_id=str(raw.get("chain_id") or ""),
            residue_name=str(raw["res_name"]),
            sequence_number=int(str(raw["res_num"])),
            insertion_code=str(raw.get("ins_code") or ""),
        )
        group_label = str(raw["group_label"])
        pka = float(str(raw["pKa"]))
    except (KeyError, TypeError, ValueError) as error:
        raise _analysis_error(
            "A PDB2PQR prediction row is missing a typed residue or pKa value.",
            {"row": {str(key): value for key, value in raw.items()}},
        ) from error

    is_terminal = group_label.startswith(("N+", "C-"))
    if not is_terminal and not group_label.startswith(residue.residue_name):
        return None
    if not is_terminal and residue.residue_name not in _SIDECHAIN_GROUPS:
        return None

    identity = _identity(residue)
    predicted_state, default_state, allowed_states, warnings = _states_for(
        residue=residue,
        group_label=group_label,
        pka=pka,
        ph=ph,
        force_field=force_field,
        is_terminal_residue=identity in terminal_identities,
    )
    override = override_map.get(identity) if not is_terminal else None
    if override is not None and override not in allowed_states:
        raise _analysis_error(
            "A protonation override is incompatible with its PROPKA proposal.",
            {
                "residue": residue.model_dump(mode="json"),
                "requested_state": override,
                "allowed_states": allowed_states,
            },
        )
    selected_state = override or default_state
    positions = _residue_positions(model, residue)
    reference_distance = _minimum_distance(positions, reference_positions)
    nearby_metals: list[ProtonationMetalContact] = []
    for component, coordinates in metal_positions:
        distance = _minimum_distance(positions, coordinates)
        if distance is None or distance > METAL_WARNING_CUTOFF_ANGSTROM:
            continue
        nearby_metals.append(
            ProtonationMetalContact(
                component_id=component.component_id,
                name=component.name,
                chain_id=component.chain_id,
                sequence_number=component.sequence_number,
                insertion_code=component.insertion_code,
                distance_angstrom=distance,
            )
        )
    near_reference = (
        reference_distance is not None
        and reference_distance <= near_reference_cutoff_angstrom
    )
    if near_reference:
        warnings.append("ACTIVE_SITE_REVIEW")
    if nearby_metals:
        warnings.append("METAL_COORDINATION_REVIEW")
    if abs(pka - ph) <= 1.0:
        warnings.append("PKA_NEAR_TARGET_PH")
    if raw.get("coupled_group") is not None:
        warnings.append("COUPLED_TITRATION_GROUP")
    return ReceptorProtonationProposal(
        proposal_id="|".join(
            (
                residue.chain_id,
                residue.residue_name,
                str(residue.sequence_number),
                residue.insertion_code,
                group_label,
            )
        ),
        residue=residue,
        group_label=group_label,
        group_type=None if raw.get("group_type") is None else str(raw["group_type"]),
        predicted_pka=pka,
        model_pka=_optional_float(raw.get("model_pKa")),
        buried_fraction=_optional_float(raw.get("buried")),
        coupled_group=(
            None if raw.get("coupled_group") is None else str(raw["coupled_group"])
        ),
        predicted_state=predicted_state,
        default_state=default_state,
        selected_state=selected_state,
        allowed_states=allowed_states,
        decision_source=(
            ProtonationDecisionSource.SCIENTIST_OVERRIDE
            if override is not None
            else ProtonationDecisionSource.PROPKA_PREDICTION
        ),
        distance_to_reference_angstrom=reference_distance,
        near_reference=near_reference,
        nearby_metals=sorted(nearby_metals, key=lambda item: item.distance_angstrom),
        warnings=sorted(set(warnings)),
    )


def _states_for(
    *,
    residue: ResidueLocator,
    group_label: str,
    pka: float,
    ph: float,
    force_field: str,
    is_terminal_residue: bool,
) -> tuple[str, str, list[str], list[str]]:
    amber = force_field.upper() == "AMBER"
    warnings: list[str] = []
    if group_label.startswith("N+"):
        predicted = "NTERM_NEUTRAL" if ph >= pka else "NTERM_CHARGED"
        default = "NTERM_CHARGED" if amber else predicted
        if default != predicted:
            warnings.append("STATE_UNSUPPORTED_BY_FORCE_FIELD")
        return predicted, default, [default], warnings
    if group_label.startswith("C-"):
        predicted = "CTERM_NEUTRAL" if ph < pka else "CTERM_CHARGED"
        default = "CTERM_CHARGED" if amber else predicted
        if default != predicted:
            warnings.append("STATE_UNSUPPORTED_BY_FORCE_FIELD")
        return predicted, default, [default], warnings

    name = residue.residue_name
    if name == "ASP":
        predicted = "ASH" if ph < pka else "ASP"
        allowed = ["ASP"] if amber and is_terminal_residue else ["ASP", "ASH"]
    elif name == "GLU":
        predicted = "GLH" if ph < pka else "GLU"
        allowed = ["GLU"] if amber and is_terminal_residue else ["GLU", "GLH"]
    elif name == "CYS":
        predicted = "CYM" if ph >= pka else "CYS"
        allowed = ["CYS", "CYM"]
    elif name == "HIS":
        predicted = "HIP" if ph < pka else "HIS_NEUTRAL_AUTO"
        allowed = ["HIS_NEUTRAL_AUTO", "HIP"]
        if predicted == "HIS_NEUTRAL_AUTO":
            warnings.append("HISTIDINE_TAUTOMER_OPTIMIZED_BY_PDB2PQR")
    elif name == "LYS":
        predicted = "LYN" if ph >= pka else "LYS"
        allowed = ["LYS"] if amber and is_terminal_residue else ["LYS", "LYN"]
    elif name == "ARG":
        predicted = "AR0" if ph >= pka else "ARG"
        allowed = ["ARG"] if amber else ["ARG", "AR0"]
    elif name == "TYR":
        predicted = "TYM" if ph >= pka else "TYR"
        allowed = ["TYR"] if amber else ["TYR", "TYM"]
    else:
        return name, name, [name], warnings
    default = predicted if predicted in allowed else allowed[0]
    if default != predicted:
        warnings.append("STATE_UNSUPPORTED_BY_FORCE_FIELD")
    return predicted, default, allowed, warnings


def _metal_positions(
    model: gemmi.Model, inspection: ReceptorInspectionReport
) -> list[tuple[ReceptorComponent, list[gemmi.Position]]]:
    values: list[tuple[ReceptorComponent, list[gemmi.Position]]] = []
    for component in inspection.components:
        if component.kind is not HeterogenKind.METAL:
            continue
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
        if positions:
            values.append((component, positions))
    return values


def _terminal_identities(path: Path) -> set[tuple[str, str, int, str]]:
    structure = gemmi.read_pdb(str(path))
    identities: set[tuple[str, str, int, str]] = set()
    for chain in structure[0]:
        residues = [
            residue
            for residue in chain
            if residue.entity_type is gemmi.EntityType.Polymer
            or gemmi.find_tabulated_residue(residue.name).is_amino_acid()
        ]
        for residue in residues[:1] + residues[-1:]:
            if residue.seqid.num is None:
                continue
            identities.add(
                (
                    chain.name,
                    residue.name.strip(),
                    residue.seqid.num,
                    _clean_char(residue.seqid.icode),
                )
            )
    return identities


def _identity(residue: ResidueLocator) -> tuple[str, str, int, str]:
    return (
        residue.chain_id,
        residue.residue_name,
        residue.sequence_number,
        residue.insertion_code,
    )


def _optional_float(value: object) -> float | None:
    return None if value is None else float(str(value))


def _analysis_error(
    message: str, details: dict[str, object] | None = None
) -> AnkoraDomainError:
    return AnkoraDomainError(
        code="RECEPTOR_PROTONATION_DECISION_INVALID",
        stage="receptor_protonation",
        message=message,
        status_code=422,
        details=details or {},
    )
