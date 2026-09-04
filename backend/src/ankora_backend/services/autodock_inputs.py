"""Input validation shared by both AutoDock backends.

The CPU and GPU engines consume exactly the same inputs: a docking-ready
receptor, a binding site that belongs to it, and a map set whose maps actually
apply. Duplicating these checks would let the two drift apart, and the one that
drifted would be the one that quietly accepted something it should not.

Only the error codes and the stage differ, so those are parameters. The
judgements themselves are stated once.
"""

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

from ankora_backend.adapters.engines.autodock4 import collect_autodock_atom_types
from ankora_backend.domain.errors import AnkoraDomainError
from ankora_backend.persistence.binding_site_store import BindingSiteArtifactStore
from ankora_backend.persistence.ligand_store import LigandArtifactStore
from ankora_backend.persistence.receptor_store import ReceptorArtifactStore
from ankora_backend.schemas.autogrid import AutoGridMapKind, AutoGridMapSetRecord
from ankora_backend.schemas.binding_sites import BindingSiteRecord
from ankora_backend.schemas.ligand_library_preparation import LigandPreparationStatus
from ankora_backend.schemas.ligands import (
    LigandInspection,
    LigandLibraryFilterRun,
    LigandRecord,
)
from ankora_backend.schemas.receptors import (
    ReceptorOutputArtifact,
    ReceptorOutputStage,
    ReceptorPreparationStatus,
)
from ankora_backend.schemas.warnings import StructuredWarning, WarningCode


def resolve_receptor_and_site(
    *,
    receptor_id: str,
    binding_site_id: str,
    receptor_store: ReceptorArtifactStore,
    binding_site_store: BindingSiteArtifactStore,
    stage: str,
    code_prefix: str,
) -> tuple[ReceptorOutputArtifact, BindingSiteRecord]:
    receptor = receptor_store.load_record(receptor_id)
    if receptor.status is not ReceptorPreparationStatus.DOCKING_READY:
        raise _rejected(
            f"{code_prefix}_RECEPTOR_NOT_READY",
            "Docking requires a receptor in docking-ready status.",
            {"receptor_id": receptor_id, "status": receptor.status.value},
            stage,
        )
    receptor_output = next(
        (item for item in receptor.outputs if item.stage is ReceptorOutputStage.PDBQT),
        None,
    )
    if receptor_output is None:
        raise _rejected(
            f"{code_prefix}_RECEPTOR_PDBQT_MISSING",
            "The selected receptor has no preserved PDBQT output.",
            {"receptor_id": receptor_id},
            stage,
        )
    binding_site = binding_site_store.load_record(binding_site_id)
    if binding_site.receptor_id != receptor_id or binding_site.stale:
        raise _rejected(
            f"{code_prefix}_BINDING_SITE_INVALID",
            "The binding site is stale or belongs to a different receptor.",
            {
                "binding_site_id": binding_site_id,
                "binding_site_receptor_id": binding_site.receptor_id,
                "requested_receptor_id": receptor_id,
                "stale": binding_site.stale,
            },
            stage,
        )
    return receptor_output, binding_site


def validate_map_set_applies(
    map_set: AutoGridMapSetRecord,
    *,
    receptor_output: ReceptorOutputArtifact,
    binding_site: BindingSiteRecord,
    stage: str,
    code_prefix: str,
) -> list[StructuredWarning]:
    """Check what actually makes the maps valid, not which record made them.

    AutoGrid computes a map set from a receptor's coordinates and a box. Map
    identity is keyed on exactly that, so two binding-site records with the same
    geometry legitimately share one map set. Comparing record IDs here would
    reject a scientifically correct reuse - and did, because a receptor can
    accumulate many binding-site records with an identical box.
    """
    if map_set.receptor_sha256 != receptor_output.sha256:
        raise _rejected(
            f"{code_prefix}_MAP_SET_RECEPTOR_MISMATCH",
            "The selected map set was generated from different receptor coordinates.",
            {
                "map_set_receptor_sha256": map_set.receptor_sha256,
                "requested_receptor_sha256": receptor_output.sha256,
            },
            stage,
        )
    if map_set.box != binding_site.box:
        raise _rejected(
            f"{code_prefix}_MAP_SET_BOX_MISMATCH",
            "The selected map set covers a different search space than this binding site.",
            {
                "map_set_box": map_set.box.model_dump(mode="json"),
                "binding_site_box": binding_site.box.model_dump(mode="json"),
            },
            stage,
        )
    if map_set.binding_site_id == binding_site.binding_site_id:
        return []
    # Same science, different provenance: worth stating rather than hiding.
    return [
        StructuredWarning(
            code=WarningCode.DOCKING_MAPS_FROM_EQUIVALENT_SITE,
            message=(
                "These maps were generated for a different binding-site record "
                "with an identical receptor and search space, so they apply "
                "unchanged to this one."
            ),
            stage=stage,
            details={
                "map_set_binding_site_id": map_set.binding_site_id,
                "requested_binding_site_id": binding_site.binding_site_id,
            },
            recoverable=True,
        )
    ]


def _rejected(
    code: str, message: str, details: dict[str, object], stage: str
) -> AnkoraDomainError:
    return AnkoraDomainError(
        code=code, stage=stage, message=message, status_code=422, details=details
    )


def ordered_atom_types(document: str) -> tuple[str, ...]:
    """Preserve first-appearance order.

    AutoDock matches the DPF's `map` lines to `ligand_types` positionally, so
    this order is load-bearing rather than cosmetic. AutoDock-GPU reads the
    types from the `.fld` instead, but both engines need the same union.
    """
    collect_autodock_atom_types((document,))
    ordered: list[str] = []
    for line in document.splitlines():
        if not line.startswith(("ATOM  ", "HETATM")):
            continue
        atom_type = line.split()[-1]
        if atom_type not in ordered:
            ordered.append(atom_type)
    return tuple(ordered)


def torsional_degrees_of_freedom(document: str) -> int:
    for line in document.splitlines():
        if line.startswith("TORSDOF"):
            return int(line.split()[1])
    return 0


@dataclass(frozen=True, slots=True)
class SelectedMolecule:
    """One molecule of an applied selection, resolved for either backend.

    `unavailable_code` is None when the molecule is ready to dock. When it is
    set the molecule stays in the campaign as a recorded refusal rather than
    disappearing from it: a scientist has to be able to see that a molecule was
    selected and why it was not docked.
    """

    ligand_id: str
    source_index: int
    name: str
    parent_compound_id: str | None = None
    chemical_state_id: str | None = None
    chemical_state_formal_charge: int | None = None
    canonical_smiles: str | None = None
    molecular_weight_g_mol: float | None = None
    preparation_id: str | None = None
    sha256: str | None = None
    atom_types: tuple[str, ...] = ()
    path: Path | None = None
    unavailable_code: str | None = None
    unavailable_reason: str | None = None

    @property
    def runnable(self) -> bool:
        return self.unavailable_code is None


def resolve_selection(
    *,
    library_id: str,
    filter_run_id: str,
    map_set: AutoGridMapSetRecord,
    ligand_store: LigandArtifactStore,
    stage: str,
    code_prefix: str,
) -> list[SelectedMolecule]:
    """Turn an applied selection into molecules a campaign can act on.

    Engine-agnostic on purpose. Both backends dock the same selection from the
    same library against the same maps, and every refusal here - missing from
    the library, never prepared, hash drifted, atom type not in the map set -
    is a fact about the inputs rather than about the executable.
    """
    filter_run = ligand_store.load_filter_run(library_id, filter_run_id)
    if not filter_run.selected_ligand_ids:
        raise _rejected(
            f"{code_prefix}_SELECTION_EMPTY",
            "The applied ligand selection contains no molecules to dock.",
            {"filter_run_id": filter_run_id},
            stage,
        )
    library = ligand_store.load_library_record(library_id)
    preparation = ligand_store.load_preparation_status(library_id)
    indexed = {
        entry.ligand.artifact.ligand_id: (entry.record_index, entry.ligand)
        for entry in library.entries
        if entry.ligand is not None
    }
    covered = {
        artifact.atom_type
        for artifact in map_set.artifacts
        if artifact.kind is AutoGridMapKind.AFFINITY
    }

    resolved: list[SelectedMolecule] = []
    for ligand_id in filter_run.selected_ligand_ids:
        source = indexed.get(ligand_id)
        if source is None:
            resolved.append(
                SelectedMolecule(
                    ligand_id=ligand_id,
                    source_index=len(resolved),
                    name="Unavailable library molecule",
                    unavailable_code=f"{code_prefix}_LIBRARY_LIGAND_MISSING",
                    unavailable_reason=(
                        "The selected molecule is absent from its library record."
                    ),
                )
            )
            continue
        source_index, ligand = source
        try:
            state = resolve_selected_chemical_state(
                ligand_id=ligand_id,
                ligand=ligand,
                filter_run=filter_run,
                ligand_store=ligand_store,
                stage=stage,
                code_prefix=code_prefix,
            )
        except AnkoraDomainError as error:
            resolved.append(
                SelectedMolecule(
                    ligand_id=ligand_id,
                    parent_compound_id=ligand_id,
                    source_index=source_index,
                    name=ligand.inspection.name,
                    unavailable_code=error.code,
                    unavailable_reason=error.message,
                )
            )
            continue
        common: dict[str, object] = {
            "ligand_id": ligand_id,
            "parent_compound_id": ligand_id,
            "chemical_state_id": state.state_id,
            "chemical_state_formal_charge": state.inspection.formal_charge,
            "source_index": source_index,
            "name": state.inspection.name,
            "canonical_smiles": state.inspection.canonical_smiles,
            "molecular_weight_g_mol": state.inspection.molecular_weight_g_mol,
        }
        status = preparation.entries.get(ligand_id)
        if (
            status is None
            or status.status is not LigandPreparationStatus.PREPARED
            or status.pdbqt_preparation_id is None
        ):
            resolved.append(
                SelectedMolecule(
                    **common,  # type: ignore[arg-type]
                    unavailable_code=f"{code_prefix}_LIGAND_NOT_PREPARED",
                    unavailable_reason=(
                        "This molecule has no completed Meeko PDBQT preparation."
                    ),
                )
            )
            continue
        if status.chemical_state_id != state.state_id:
            resolved.append(
                SelectedMolecule(
                    **common,  # type: ignore[arg-type]
                    unavailable_code=f"{code_prefix}_PREPARATION_STATE_MISMATCH",
                    unavailable_reason=(
                        "The prepared PDBQT belongs to a different or unrecorded "
                        "chemical state than the applied selection manifest."
                    ),
                )
            )
            continue
        try:
            pdbqt = ligand_store.load_pdbqt_record(
                ligand_id, status.pdbqt_preparation_id
            )
            path = ligand_store.pdbqt_content_path(
                ligand_id, status.pdbqt_preparation_id
            )
            verify_hash(
                path, pdbqt.artifact.sha256, stage=stage, code_prefix=code_prefix
            )
            document = path.read_text(encoding="utf-8", errors="replace")
            atom_types = ordered_atom_types(document)
        except (AnkoraDomainError, ValueError) as error:
            resolved.append(
                SelectedMolecule(
                    **common,  # type: ignore[arg-type]
                    unavailable_code=f"{code_prefix}_LIGAND_UNAVAILABLE",
                    unavailable_reason=str(getattr(error, "message", error)),
                )
            )
            continue
        missing = sorted(set(atom_types) - covered)
        if missing:
            resolved.append(
                SelectedMolecule(
                    **common,  # type: ignore[arg-type]
                    preparation_id=status.pdbqt_preparation_id,
                    sha256=pdbqt.artifact.sha256,
                    atom_types=atom_types,
                    unavailable_code=f"{code_prefix}_LIGAND_TYPES_NOT_IN_MAP_SET",
                    unavailable_reason=(
                        "This molecule uses atom types the selected map set does "
                        f"not cover: {', '.join(missing)}."
                    ),
                )
            )
            continue
        resolved.append(
            SelectedMolecule(
                **common,  # type: ignore[arg-type]
                preparation_id=status.pdbqt_preparation_id,
                sha256=pdbqt.artifact.sha256,
                atom_types=atom_types,
                path=path,
            )
        )
    return resolved


@dataclass(frozen=True, slots=True)
class SelectedChemicalState:
    """Exact parent/state identity carried by an applied screening manifest."""

    parent_compound_id: str
    state_id: str
    inspection: LigandInspection


def resolve_selected_chemical_state(
    *,
    ligand_id: str,
    ligand: LigandRecord,
    filter_run: LigandLibraryFilterRun,
    ligand_store: LigandArtifactStore,
    stage: str,
    code_prefix: str,
) -> SelectedChemicalState:
    evaluation = next(
        (item for item in filter_run.evaluations if item.ligand_id == ligand_id),
        None,
    )
    if evaluation is None:
        raise _rejected(
            f"{code_prefix}_SELECTION_STATE_MISSING",
            "The applied selection does not record this parent compound's chemical state.",
            {"ligand_id": ligand_id, "filter_run_id": filter_run.artifact.filter_run_id},
            stage,
        )
    state_id = evaluation.state_id
    try:
        inspection = (
            ligand.inspection
            if ligand.state is not None and ligand.state.state_id == state_id
            else ligand_store.load_state_inspection(ligand_id, state_id)
        )
    except (AnkoraDomainError, OSError, ValueError) as error:
        raise _rejected(
            f"{code_prefix}_SELECTION_STATE_UNAVAILABLE",
            "The exact chemical state recorded by the applied selection is unavailable.",
            {"ligand_id": ligand_id, "chemical_state_id": state_id},
            stage,
        ) from error
    return SelectedChemicalState(
        parent_compound_id=ligand_id,
        state_id=state_id,
        inspection=inspection,
    )


def verify_hash(path: Path, expected: str, *, stage: str, code_prefix: str) -> None:
    """A prepared ligand that drifted from its recorded hash is not that ligand."""
    digest = sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    if digest.hexdigest() != expected:
        raise _rejected(
            f"{code_prefix}_INPUT_HASH_MISMATCH",
            "The prepared ligand no longer matches its stored hash.",
            {"path": path.name, "expected_sha256": expected},
            stage,
        )
