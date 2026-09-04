"""Explicit binding-site definition ahead of docking (M4).

The resulting box is always computed in the same coordinate frame as the
immutable original structure. Receptor preparation (PDBFixer repair,
relaxation, PDB2PQR/PROPKA protonation) never translates or rotates
coordinates, so a box computed from the original aligns with the prepared
receptor at every stage.
"""

from datetime import UTC, datetime

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
)
from ankora_backend.schemas.provenance import ProvenanceEvent, ToolIdentity
from ankora_backend.schemas.receptors import (
    ReceptorOutputArtifact,
    ReceptorPreparationRecord,
    ReceptorPreparationStatus,
    ResidueLocator,
)


def define_binding_site(
    *,
    receptor_id: str,
    request: BindingSiteRequest,
    structure_store: StructureArtifactStore,
    receptor_store: ReceptorArtifactStore,
    binding_site_store: BindingSiteArtifactStore,
    pocket_detection_store: PocketDetectionArtifactStore,
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
    box = _resolve_box(
        request=request,
        structure_store=structure_store,
        receptor_store=receptor_store,
        receptor_record=receptor_record,
        pocket_detection_store=pocket_detection_store,
        source_artifact_id=source_artifact_id,
    )

    binding_site_id = binding_site_store.new_binding_site_id()
    created_at = datetime.now(UTC)
    provenance = ProvenanceEvent(
        event_id=f"binding-site-{binding_site_id}",
        event_type="binding_site_defined",
        timestamp=created_at,
        input_artifacts=input_artifacts,
        output_artifacts=[binding_site_id],
        tool=ToolIdentity(name="ankora-binding-site", version=__version__),
        parameters={"decisions": request.model_dump(mode="json")},
    )
    record = BindingSiteRecord(
        binding_site_id=binding_site_id,
        receptor_id=receptor_id,
        source_artifact_id=source_artifact_id,
        created_at=created_at,
        decisions=request,
        box=box,
        stale=False,
        warnings=[],
        provenance=[provenance],
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
) -> BindingSitePreview:
    """Resolve an editable box without creating a scientific artifact."""
    receptor_record = _load_docking_ready_receptor(receptor_id, receptor_store)
    box = _resolve_box(
        request=request,
        structure_store=structure_store,
        receptor_store=receptor_store,
        receptor_record=receptor_record,
        pocket_detection_store=pocket_detection_store,
        source_artifact_id=receptor_record.source_artifact_id,
    )
    return BindingSitePreview(
        receptor_id=receptor_id,
        source=request.source,
        box=box,
        warnings=[],
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
