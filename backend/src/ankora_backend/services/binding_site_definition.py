"""Explicit binding-site definition ahead of docking (M4).

The resulting box is always computed in the same coordinate frame as the
immutable original structure. Receptor preparation (PDBFixer repair,
relaxation, PDB2PQR/PROPKA protonation) never translates or rotates
coordinates, so a box computed from the original aligns with the prepared
receptor at every stage.
"""

import math
import re
from datetime import UTC, datetime
from hashlib import sha256

import gemmi

from ankora_backend import __version__
from ankora_backend.domain.errors import AnkoraDomainError
from ankora_backend.domain.gemmi_utils import clean_insertion_code
from ankora_backend.persistence.artifact_store import StructureArtifactStore
from ankora_backend.persistence.binding_site_store import BindingSiteArtifactStore
from ankora_backend.persistence.pocket_detection_store import PocketDetectionArtifactStore
from ankora_backend.persistence.receptor_store import ReceptorArtifactStore
from ankora_backend.schemas.binding_sites import (
    BindingBox,
    BindingSitePreview,
    BindingSiteRecord,
    BindingSiteRequest,
    BindingSiteSource,
    PoseFocusedEvidence,
)
from ankora_backend.schemas.provenance import ProvenanceEvent, ToolIdentity
from ankora_backend.schemas.receptors import (
    ReceptorFlexMode,
    ReceptorOutputArtifact,
    ReceptorPreparationRecord,
    ReceptorPreparationStatus,
    ResidueLocator,
)
from ankora_backend.schemas.warnings import StructuredWarning, WarningCode
from ankora_backend.services.pose_interactions import PoseInteractionService
from ankora_backend.services.project_dependencies import ProjectDependencyService

_VINA_LARGE_SEARCH_SPACE_VOLUME = 27_000.0
# Meeko macrocycle ring-closure dummy glue pseudoatoms (G0..G9, G, DU, LP).
# Real macrocycle carbons (CG0..CG9) and PDB atom names (CG1/CG2) are real heavy atoms.
_PSEUDOATOM_TYPE_RE = re.compile(r"^(?:G\d+|G|DU|LP)$", re.IGNORECASE)
_HYDROGEN_AD_TYPES = frozenset({"H", "HD", "HS"})


def define_binding_site(
    *,
    receptor_id: str,
    request: BindingSiteRequest,
    structure_store: StructureArtifactStore,
    receptor_store: ReceptorArtifactStore,
    binding_site_store: BindingSiteArtifactStore,
    pocket_detection_store: PocketDetectionArtifactStore,
    pose_interaction_service: PoseInteractionService | None = None,
    dependency_service: ProjectDependencyService | None = None,
) -> BindingSiteRecord:
    receptor_record = _load_docking_ready_receptor(receptor_id, receptor_store)
    if (
        request.source is BindingSiteSource.FULL_PROTEIN_BLIND
        and not request.acknowledge_exploratory_full_protein
    ):
        raise AnkoraDomainError(
            code="BINDING_SITE_FULL_PROTEIN_ACKNOWLEDGEMENT_REQUIRED",
            stage="binding_site_definition",
            message=(
                "A full-protein search space is exploratory and must be "
                "acknowledged explicitly before it is finalized."
            ),
            status_code=422,
            details={"source": request.source.value},
        )
    source_artifact_id = receptor_record.source_artifact_id
    input_artifacts = [source_artifact_id, receptor_id]
    if request.parent_binding_site_id is not None:
        try:
            parent = binding_site_store.load_record(request.parent_binding_site_id)
        except AnkoraDomainError as error:
            raise AnkoraDomainError(
                code="BINDING_SITE_PARENT_NOT_FOUND",
                stage="binding_site_definition",
                message="The binding site being adjusted is not available.",
                status_code=422,
                details={"parent_binding_site_id": request.parent_binding_site_id},
            ) from error
        if parent.receptor_id != receptor_id:
            raise AnkoraDomainError(
                code="BINDING_SITE_PARENT_RECEPTOR_MISMATCH",
                stage="binding_site_definition",
                message="The binding site being adjusted belongs to a different receptor.",
                status_code=422,
                details={
                    "parent_binding_site_id": request.parent_binding_site_id,
                    "receptor_id": receptor_id,
                    "parent_receptor_id": parent.receptor_id,
                },
            )
        input_artifacts.append(parent.binding_site_id)
    box, pose_focused_evidence, extra_inputs, warnings = _resolve_box_and_evidence(
        request=request,
        structure_store=structure_store,
        receptor_store=receptor_store,
        receptor_record=receptor_record,
        pocket_detection_store=pocket_detection_store,
        source_artifact_id=source_artifact_id,
        pose_interaction_service=pose_interaction_service,
        dependency_service=dependency_service,
    )
    for item in extra_inputs:
        if item not in input_artifacts:
            input_artifacts.append(item)

    binding_site_id = binding_site_store.new_binding_site_id()
    created_at = datetime.now(UTC)
    provenance_params: dict[str, object] = {"decisions": request.model_dump(mode="json")}
    if pose_focused_evidence is not None:
        provenance_params["pose_focused_evidence"] = pose_focused_evidence.model_dump(mode="json")
    provenance = ProvenanceEvent(
        event_id=f"binding-site-{binding_site_id}",
        event_type="binding_site_defined",
        timestamp=created_at,
        input_artifacts=input_artifacts,
        output_artifacts=[binding_site_id],
        tool=ToolIdentity(name="ankora-binding-site", version=__version__),
        parameters=provenance_params,
        warnings=list(warnings),
    )
    record = BindingSiteRecord(
        binding_site_id=binding_site_id,
        receptor_id=receptor_id,
        source_artifact_id=source_artifact_id,
        created_at=created_at,
        decisions=request,
        box=box,
        stale=False,
        warnings=warnings,
        provenance=[provenance],
        pose_focused_evidence=pose_focused_evidence,
    )
    binding_site_store.save_record(record)
    return record


def preview_binding_site(
    *,
    receptor_id: str,
    request: BindingSiteRequest,
    structure_store: StructureArtifactStore,
    receptor_store: ReceptorArtifactStore,
    pocket_detection_store: PocketDetectionArtifactStore,
    pose_interaction_service: PoseInteractionService | None = None,
    dependency_service: ProjectDependencyService | None = None,
) -> BindingSitePreview:
    """Resolve an editable box without creating a scientific artifact."""
    receptor_record = _load_docking_ready_receptor(receptor_id, receptor_store)
    box, pose_focused_evidence, _, warnings = _resolve_box_and_evidence(
        request=request,
        structure_store=structure_store,
        receptor_store=receptor_store,
        receptor_record=receptor_record,
        pocket_detection_store=pocket_detection_store,
        source_artifact_id=receptor_record.source_artifact_id,
        pose_interaction_service=pose_interaction_service,
        dependency_service=dependency_service,
    )
    return BindingSitePreview(
        receptor_id=receptor_id,
        source=request.source,
        box=box,
        warnings=warnings,
        pose_focused_evidence=pose_focused_evidence,
    )


def _load_docking_ready_receptor(
    receptor_id: str,
    receptor_store: ReceptorArtifactStore,
) -> ReceptorPreparationRecord:
    receptor_record = receptor_store.load_record(receptor_id)
    if receptor_record.status is not ReceptorPreparationStatus.DOCKING_READY:
        raise AnkoraDomainError(
            code="BINDING_SITE_RECEPTOR_NOT_READY",
            stage="binding_site_definition",
            message=(
                "Define a binding site only for a receptor that has reached docking-ready status."
            ),
            status_code=422,
            details={"receptor_id": receptor_id, "status": receptor_record.status.value},
        )
    return receptor_record


def _resolve_box_and_evidence(
    *,
    request: BindingSiteRequest,
    structure_store: StructureArtifactStore,
    receptor_store: ReceptorArtifactStore,
    receptor_record: ReceptorPreparationRecord,
    pocket_detection_store: PocketDetectionArtifactStore,
    source_artifact_id: str,
    pose_interaction_service: PoseInteractionService | None,
    dependency_service: ProjectDependencyService | None,
) -> tuple[BindingBox, PoseFocusedEvidence | None, list[str], list[StructuredWarning]]:
    if request.source is BindingSiteSource.POSE_FOCUSED:
        return _resolve_pose_focused_box(
            request=request,
            receptor_store=receptor_store,
            receptor_record=receptor_record,
            pose_interaction_service=pose_interaction_service,
            dependency_service=dependency_service,
        )
    box = _resolve_box(
        request=request,
        structure_store=structure_store,
        receptor_store=receptor_store,
        receptor_record=receptor_record,
        pocket_detection_store=pocket_detection_store,
        source_artifact_id=source_artifact_id,
    )
    return box, None, [], []


def _resolve_pose_focused_box(
    *,
    request: BindingSiteRequest,
    receptor_store: ReceptorArtifactStore,
    receptor_record: ReceptorPreparationRecord,
    pose_interaction_service: PoseInteractionService | None,
    dependency_service: ProjectDependencyService | None,
) -> tuple[BindingBox, PoseFocusedEvidence, list[str], list[StructuredWarning]]:
    if request.pose_focused is None:
        raise _inconsistent_request_error(request.source.value, "pose_focused")
    origin = request.pose_focused
    interactions = pose_interaction_service or PoseInteractionService.from_environment()
    verified = interactions.resolve_verified_pose_inputs(
        origin.source_catalog_id,
        origin.ligand_id,
        origin.pose_artifact_id,
    )
    if verified.resolved.receptor_id != receptor_record.receptor_id:
        raise AnkoraDomainError(
            code="BINDING_SITE_POSE_RECEPTOR_MISMATCH",
            stage="binding_site_definition",
            message="The selected lead pose belongs to a different receptor.",
            status_code=422,
            details={
                "receptor_id": receptor_record.receptor_id,
                "pose_receptor_id": verified.resolved.receptor_id,
                "source_catalog_id": origin.source_catalog_id,
                "pose_artifact_id": origin.pose_artifact_id,
            },
        )
    if dependency_service is not None:
        fresh_ids = [
            receptor_record.receptor_id,
            verified.resolved.record_id,
            verified.resolved.pose.artifact_id,
        ]
        if origin.source_consensus_id is not None:
            fresh_ids.append(origin.source_consensus_id)
        if request.parent_binding_site_id is not None:
            fresh_ids.append(request.parent_binding_site_id)
        dependency_service.require_current(fresh_ids)

    pose_bytes = verified.resolved.pose_path.read_bytes()
    pose_sha = sha256(pose_bytes).hexdigest()
    flex_sha: str | None = None
    if (
        verified.resolved.pose_flex_path is not None
        and verified.resolved.pose_flex_path.is_file()
    ):
        flex_sha = sha256(verified.resolved.pose_flex_path.read_bytes()).hexdigest()

    positions, excluded_h, excluded_pseudo = _extract_pose_heavy_atom_positions(
        pose_bytes.decode("utf-8", errors="replace"),
        pose_artifact_id=origin.pose_artifact_id,
    )
    computed_base_box = _bounding_box(
        positions,
        padding_angstrom=origin.padding_angstrom,
        degenerate_details={
            "source_catalog_id": origin.source_catalog_id,
            "ligand_id": origin.ligand_id,
            "pose_artifact_id": origin.pose_artifact_id,
        },
    )
    final_box = origin.box_override if origin.box_override is not None else computed_base_box

    flex_checked = _validate_flex_residues_containment(
        box=final_box,
        receptor_record=receptor_record,
        receptor_store=receptor_store,
        margin_angstrom=origin.flex_containment_margin_angstrom,
    )

    warnings: list[StructuredWarning] = []
    volume = final_box.size_x * final_box.size_y * final_box.size_z
    if volume > _VINA_LARGE_SEARCH_SPACE_VOLUME:
        warnings.append(
            StructuredWarning(
                code=WarningCode.DOCKING_SEARCH_SPACE_LARGE,
                stage="binding_site_definition",
                message=(
                    f"Pose-focused search space volume ({volume:,.1f} A^3) exceeds the "
                    f"{_VINA_LARGE_SEARCH_SPACE_VOLUME:,.0f} A^3 Vina guidance threshold "
                    "(ADR-018). Ankora changed no sampling parameters."
                ),
                details={
                    "volume_angstrom3": round(volume, 3),
                    "threshold_angstrom3": _VINA_LARGE_SEARCH_SPACE_VOLUME,
                    "ratio": round(volume / _VINA_LARGE_SEARCH_SPACE_VOLUME, 4),
                    "source": BindingSiteSource.POSE_FOCUSED.value,
                },
            )
        )

    evidence = PoseFocusedEvidence(
        source_catalog_id=origin.source_catalog_id,
        engine_key=verified.resolved.engine_key,
        record_id=verified.resolved.record_id,
        ligand_id=verified.resolved.ligand_id,
        ligand_preparation_id=verified.resolved.ligand_preparation_id,
        pose_artifact_id=verified.resolved.pose.artifact_id,
        pose_sha256=pose_sha,
        pose_flex_sidechains_sha256=flex_sha,
        source_consensus_id=origin.source_consensus_id,
        source_cluster_id=origin.source_cluster_id,
        heavy_atom_count=len(positions),
        excluded_hydrogen_count=excluded_h,
        excluded_pseudoatom_count=excluded_pseudo,
        computed_base_box=computed_base_box,
        box_overridden=origin.box_override is not None,
        flex_containment_checked=flex_checked,
        flex_containment_margin_angstrom=origin.flex_containment_margin_angstrom,
    )
    extra_inputs = [
        verified.resolved.record_id,
        verified.resolved.pose.artifact_id,
    ]
    if origin.source_consensus_id is not None:
        extra_inputs.append(origin.source_consensus_id)
    return final_box, evidence, extra_inputs, warnings


def _extract_pose_heavy_atom_positions(
    pdbqt_text: str,
    *,
    pose_artifact_id: str,
) -> tuple[list[gemmi.Position], int, int]:
    """Extract finite real heavy-atom coordinates from a ligand PDBQT pose."""
    positions: list[gemmi.Position] = []
    excluded_h = 0
    excluded_pseudo = 0
    for line_no, line in enumerate(pdbqt_text.splitlines(), start=1):
        if line.startswith("ENDMDL"):
            break
        if not line.startswith(("ATOM  ", "HETATM")):
            continue
        if len(line) < 54:
            raise AnkoraDomainError(
                code="BINDING_SITE_POSE_INVALID_COORDINATES",
                stage="binding_site_definition",
                message="The selected lead pose contains a truncated PDBQT atom record.",
                status_code=422,
                details={"pose_artifact_id": pose_artifact_id, "line": line_no},
            )
        try:
            x = float(line[30:38])
            y = float(line[38:46])
            z = float(line[46:54])
        except ValueError as error:
            raise AnkoraDomainError(
                code="BINDING_SITE_POSE_INVALID_COORDINATES",
                stage="binding_site_definition",
                message="The selected lead pose contains non-numeric coordinates.",
                status_code=422,
                details={"pose_artifact_id": pose_artifact_id, "line": line_no},
            ) from error
        if not (math.isfinite(x) and math.isfinite(y) and math.isfinite(z)):
            raise AnkoraDomainError(
                code="BINDING_SITE_POSE_INVALID_COORDINATES",
                stage="binding_site_definition",
                message="The selected lead pose contains non-finite coordinates.",
                status_code=422,
                details={"pose_artifact_id": pose_artifact_id, "line": line_no},
            )
        atom_name = line[12:16].strip()
        ad_type = line[77:].strip() if len(line) > 77 else ""
        if not ad_type:
            parts = line.split()
            ad_type = parts[-1] if parts else ""
        upper_type = ad_type.upper()
        upper_name = atom_name.upper()
        if upper_type in _HYDROGEN_AD_TYPES or (not upper_type and upper_name.startswith("H")):
            excluded_h += 1
            continue
        if _PSEUDOATOM_TYPE_RE.match(upper_type):
            excluded_pseudo += 1
            continue
        positions.append(gemmi.Position(x, y, z))

    if not positions:
        raise AnkoraDomainError(
            code="BINDING_SITE_POSE_NO_HEAVY_ATOMS",
            stage="binding_site_definition",
            message="The selected lead pose contains no real heavy atoms for box derivation.",
            status_code=422,
            details={
                "pose_artifact_id": pose_artifact_id,
                "excluded_hydrogen_count": excluded_h,
                "excluded_pseudoatom_count": excluded_pseudo,
            },
        )
    return positions, excluded_h, excluded_pseudo


def _validate_flex_residues_containment(
    *,
    box: BindingBox,
    receptor_record: ReceptorPreparationRecord,
    receptor_store: ReceptorArtifactStore,
    margin_angstrom: float,
) -> bool:
    """Verify anchors and all mobile atoms of every FlexRes lie inside box minus margin."""
    flex_spec = receptor_record.flex_spec
    if flex_spec is None or flex_spec.mode is not ReceptorFlexMode.SIDECHAIN_FLEX:
        return False

    output = _display_output(receptor_record)
    receptor_path = receptor_store.content_path(receptor_record.receptor_id, output.artifact_id)
    model = gemmi.read_structure(str(receptor_path))[0]

    min_x = box.center_x - box.size_x / 2.0 + margin_angstrom
    max_x = box.center_x + box.size_x / 2.0 - margin_angstrom
    min_y = box.center_y - box.size_y / 2.0 + margin_angstrom
    max_y = box.center_y + box.size_y / 2.0 - margin_angstrom
    min_z = box.center_z - box.size_z / 2.0 + margin_angstrom
    max_z = box.center_z + box.size_z / 2.0 - margin_angstrom

    offending: list[dict[str, object]] = []
    missing_residues: list[dict[str, object]] = []
    all_flex_positions: list[gemmi.Position] = []

    for locator in flex_spec.flex_residues:
        matched_residue = None
        for chain in model:
            if chain.name != locator.chain_id:
                continue
            for residue in chain:
                if (
                    residue.name.strip() == locator.residue_name
                    and residue.seqid.num == locator.sequence_number
                    and clean_insertion_code(residue.seqid.icode) == locator.insertion_code
                ):
                    matched_residue = residue
                    break
            if matched_residue is not None:
                break
        if matched_residue is None:
            missing_residues.append(locator.model_dump(mode="json"))
            continue
        for atom in matched_residue:
            pos = atom.pos
            all_flex_positions.append(pos)
            if (
                min_x > max_x
                or min_y > max_y
                or min_z > max_z
                or pos.x < min_x
                or pos.x > max_x
                or pos.y < min_y
                or pos.y > max_y
                or pos.z < min_z
                or pos.z > max_z
            ):
                offending.append(
                    {
                        "residue": locator.model_dump(mode="json"),
                        "atom_name": atom.name.strip(),
                        "x": round(pos.x, 3),
                        "y": round(pos.y, 3),
                        "z": round(pos.z, 3),
                    }
                )

    if missing_residues or offending:
        req_size_x = (
            max(
                box.size_x,
                max(abs(p.x - box.center_x) for p in all_flex_positions) * 2.0
                + 2.0 * margin_angstrom,
            )
            if all_flex_positions
            else box.size_x
        )
        req_size_y = (
            max(
                box.size_y,
                max(abs(p.y - box.center_y) for p in all_flex_positions) * 2.0
                + 2.0 * margin_angstrom,
            )
            if all_flex_positions
            else box.size_y
        )
        req_size_z = (
            max(
                box.size_z,
                max(abs(p.z - box.center_z) for p in all_flex_positions) * 2.0
                + 2.0 * margin_angstrom,
            )
            if all_flex_positions
            else box.size_z
        )
        raise AnkoraDomainError(
            code="BINDING_SITE_FLEXRES_OUTSIDE_BOX",
            stage="binding_site_definition",
            message=(
                "One or more flexible side-chain atoms lie outside the pose-focused box "
                f"(margin {margin_angstrom:g} A). Expand the box or change FlexRes explicitly; "
                "Ankora will not silently trim flexible residues."
            ),
            status_code=422,
            details={
                "margin_angstrom": margin_angstrom,
                "missing_residues": missing_residues,
                "offending_atom_count": len(offending),
                "offending_atoms": offending[:25],
                "recommended_min_size": {
                    "size_x": round(req_size_x, 3),
                    "size_y": round(req_size_y, 3),
                    "size_z": round(req_size_z, 3),
                },
            },
        )
    return True


def _resolve_box(
    *,
    request: BindingSiteRequest,
    structure_store: StructureArtifactStore,
    receptor_store: ReceptorArtifactStore,
    receptor_record: ReceptorPreparationRecord,
    pocket_detection_store: PocketDetectionArtifactStore,
    source_artifact_id: str,
) -> BindingBox:
    if request.source is BindingSiteSource.CO_CRYSTALLIZED_LIGAND:
        if request.ligand_origin is None:
            raise _inconsistent_request_error(request.source.value, "ligand_origin")
        source_path = structure_store.content_path(source_artifact_id)
        positions = _heterogen_positions(
            gemmi.read_structure(str(source_path))[0], request.ligand_origin.heterogen
        )
        heterogen_details: dict[str, object] = {
            "heterogen": request.ligand_origin.heterogen.model_dump(mode="json")
        }
        if not positions:
            raise AnkoraDomainError(
                code="BINDING_SITE_HETEROGEN_NOT_FOUND",
                stage="binding_site_definition",
                message=(
                    "The selected co-crystallized ligand is not present in the original structure."
                ),
                status_code=422,
                details=heterogen_details,
            )
        return _bounding_box(
            positions,
            padding_angstrom=request.ligand_origin.padding_angstrom,
            degenerate_details=heterogen_details,
        )
    if request.source is BindingSiteSource.SELECTED_RESIDUES:
        if request.residue_selection is None:
            raise _inconsistent_request_error(request.source.value, "residue_selection")
        output = _display_output(receptor_record)
        receptor_path = receptor_store.content_path(receptor_record.receptor_id, output.artifact_id)
        model = gemmi.read_structure(str(receptor_path))[0]
        positions, missing = _selected_residue_positions(
            model,
            request.residue_selection.residues,
        )
        selection_details: dict[str, object] = {
            "residues": [
                residue.model_dump(mode="json") for residue in request.residue_selection.residues
            ]
        }
        if missing:
            raise AnkoraDomainError(
                code="BINDING_SITE_SELECTED_RESIDUE_NOT_FOUND",
                stage="binding_site_definition",
                message=(
                    "One or more selected residues are not present in the docking-ready receptor."
                ),
                status_code=422,
                details={
                    **selection_details,
                    "missing_residues": [item.model_dump(mode="json") for item in missing],
                },
            )
        return _bounding_box(
            positions,
            padding_angstrom=request.residue_selection.padding_angstrom,
            degenerate_details=selection_details,
        )
    if request.source is BindingSiteSource.MANUAL:
        if request.manual_box is None:
            raise _inconsistent_request_error(request.source.value, "manual_box")
        return request.manual_box
    if request.source is BindingSiteSource.FULL_PROTEIN_BLIND:
        output = _display_output(receptor_record)
        receptor_path = receptor_store.content_path(receptor_record.receptor_id, output.artifact_id)
        structure = gemmi.read_structure(str(receptor_path))
        positions = [atom.pos for chain in structure[0] for residue in chain for atom in residue]
        return _bounding_box(
            positions,
            padding_angstrom=request.blind_margin_angstrom,
            degenerate_details={"receptor_id": receptor_record.receptor_id},
        )
    if request.source is BindingSiteSource.POCKET_DETECTED:
        if request.pocket_selection is None:
            raise _inconsistent_request_error(request.source.value, "pocket_selection")
        selection = request.pocket_selection
        try:
            report = pocket_detection_store.load_record(selection.report_id)
        except AnkoraDomainError as error:
            raise AnkoraDomainError(
                code="BINDING_SITE_POCKET_REPORT_NOT_FOUND",
                stage="binding_site_definition",
                message="The selected pocket-detection report is not available.",
                status_code=422,
                details={"report_id": selection.report_id},
            ) from error
        if report.receptor_id != receptor_record.receptor_id:
            raise AnkoraDomainError(
                code="BINDING_SITE_POCKET_REPORT_MISMATCH",
                stage="binding_site_definition",
                message="The selected pocket-detection report belongs to a different receptor.",
                status_code=422,
                details={
                    "report_id": selection.report_id,
                    "receptor_id": receptor_record.receptor_id,
                },
            )
        candidate = next(
            (item for item in report.candidates if item.pocket_id == selection.pocket_id), None
        )
        if candidate is None:
            raise AnkoraDomainError(
                code="BINDING_SITE_POCKET_NOT_FOUND",
                stage="binding_site_definition",
                message="The selected pocket is not present in that detection report.",
                status_code=422,
                details={"report_id": selection.report_id, "pocket_id": selection.pocket_id},
            )
        return candidate.box
    raise AnkoraDomainError(
        code="BINDING_SITE_SOURCE_NOT_IMPLEMENTED",
        stage="binding_site_definition",
        message=f"The '{request.source.value}' binding-site source is not implemented yet.",
        status_code=501,
        details={"source": request.source.value},
    )


def _inconsistent_request_error(source: str, missing_field: str) -> AnkoraDomainError:
    # Reachable only if pydantic's own cross-field validation on
    # BindingSiteRequest is ever bypassed or loosened — a bare `assert`
    # here would silently disappear under `python -O`, letting a `None`
    # payload flow into the source-specific branch below and fail later
    # with a much less clear AttributeError instead of this 422.
    return AnkoraDomainError(
        code="BINDING_SITE_REQUEST_INCONSISTENT",
        stage="binding_site_definition",
        message=f"A '{source}' binding site request requires '{missing_field}'.",
        status_code=422,
        details={"source": source, "missing_field": missing_field},
    )


def _display_output(receptor_record: ReceptorPreparationRecord) -> ReceptorOutputArtifact:
    output = next(
        (
            item
            for item in receptor_record.outputs
            if item.artifact_id == receptor_record.display_output_artifact_id
        ),
        None,
    )
    if output is None:
        raise AnkoraDomainError(
            code="BINDING_SITE_RECEPTOR_OUTPUT_MISSING",
            stage="binding_site_definition",
            message="The docking-ready receptor has no displayable prepared output.",
            status_code=422,
            details={"receptor_id": receptor_record.receptor_id},
        )
    return output


def _bounding_box(
    positions: list[gemmi.Position],
    *,
    padding_angstrom: float,
    degenerate_details: dict[str, object],
) -> BindingBox:
    min_x = min(pos.x for pos in positions)
    max_x = max(pos.x for pos in positions)
    min_y = min(pos.y for pos in positions)
    max_y = max(pos.y for pos in positions)
    min_z = min(pos.z for pos in positions)
    max_z = max(pos.z for pos in positions)
    size_x = (max_x - min_x) + 2 * padding_angstrom
    size_y = (max_y - min_y) + 2 * padding_angstrom
    size_z = (max_z - min_z) + 2 * padding_angstrom
    if size_x <= 0 or size_y <= 0 or size_z <= 0:
        raise AnkoraDomainError(
            code="BINDING_SITE_BOX_DEGENERATE",
            stage="binding_site_definition",
            message="The computed box has no volume. Increase the padding and try again.",
            status_code=422,
            details={**degenerate_details, "padding_angstrom": padding_angstrom},
        )
    return BindingBox(
        center_x=(min_x + max_x) / 2,
        center_y=(min_y + max_y) / 2,
        center_z=(min_z + max_z) / 2,
        size_x=size_x,
        size_y=size_y,
        size_z=size_z,
    )


def _heterogen_positions(model: gemmi.Model, heterogen: ResidueLocator) -> list[gemmi.Position]:
    positions: list[gemmi.Position] = []
    for chain in model:
        if chain.name != heterogen.chain_id:
            continue
        for residue in chain:
            if (
                residue.name.strip() == heterogen.residue_name
                and residue.seqid.num == heterogen.sequence_number
                and clean_insertion_code(residue.seqid.icode) == heterogen.insertion_code
            ):
                positions.extend(atom.pos for atom in residue)
    return positions


def _selected_residue_positions(
    model: gemmi.Model,
    selected: list[ResidueLocator],
) -> tuple[list[gemmi.Position], list[ResidueLocator]]:
    positions: list[gemmi.Position] = []
    missing: list[ResidueLocator] = []
    for locator in selected:
        found = False
        for chain in model:
            if chain.name != locator.chain_id:
                continue
            for residue in chain:
                if (
                    residue.name.strip() == locator.residue_name
                    and residue.seqid.num == locator.sequence_number
                    and clean_insertion_code(residue.seqid.icode) == locator.insertion_code
                ):
                    positions.extend(atom.pos for atom in residue)
                    found = True
        if not found:
            missing.append(locator)
    return positions, missing
