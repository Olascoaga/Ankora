"""P2Rank-based pocket detection ahead of binding-site definition (M4).

Each candidate's box is centered on P2Rank's own predicted centroid (a
ligandability-weighted point, not just a geometric bounding-box midpoint),
sized from the bounding extent of the pocket's lining residues in the
receptor's own docking-ready structure, padded by a fixed margin — the same
"real atoms, padded" approach used for the co-crystallized-ligand box.
"""

import csv
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory

import gemmi

from ankora_backend.adapters.tools.pocket_detection import execute_p2rank
from ankora_backend.domain.errors import AnkoraDomainError
from ankora_backend.domain.gemmi_utils import clean_insertion_code
from ankora_backend.persistence.pocket_detection_store import PocketDetectionArtifactStore
from ankora_backend.persistence.receptor_store import ReceptorArtifactStore
from ankora_backend.schemas.binding_sites import (
    BindingBox,
    PocketCandidate,
    PocketDetectionExecutionEvidence,
    PocketDetectionReport,
)
from ankora_backend.schemas.provenance import ProvenanceEvent, ToolIdentity
from ankora_backend.schemas.receptors import ReceptorPreparationStatus, ResidueLocator

POCKET_BOX_PADDING_ANGSTROM = 5.0


@dataclass(frozen=True, slots=True)
class _PredictionRow:
    name: str
    rank: int
    probability: float
    center_x: float
    center_y: float
    center_z: float
    residue_keys: list[tuple[str, int]]


def detect_pockets(
    *,
    receptor_id: str,
    receptor_store: ReceptorArtifactStore,
    pocket_detection_store: PocketDetectionArtifactStore,
) -> PocketDetectionReport:
    receptor_record = receptor_store.load_record(receptor_id)
    if receptor_record.status is not ReceptorPreparationStatus.DOCKING_READY:
        raise AnkoraDomainError(
            code="POCKET_DETECTION_RECEPTOR_NOT_READY",
            stage="pocket_detection",
            message=(
                "Detect pockets only for a receptor that has reached "
                "docking-ready status."
            ),
            status_code=422,
            details={"receptor_id": receptor_id, "status": receptor_record.status.value},
        )
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
            code="POCKET_DETECTION_RECEPTOR_OUTPUT_MISSING",
            stage="pocket_detection",
            message="The docking-ready receptor has no displayable prepared output.",
            status_code=422,
            details={"receptor_id": receptor_id},
        )
    receptor_path = receptor_store.content_path(receptor_id, output.artifact_id)
    structure = gemmi.read_structure(str(receptor_path))

    with TemporaryDirectory(prefix="ankora-p2rank-") as work_dir:
        output_dir = Path(work_dir)
        execution, tool_version = execute_p2rank(
            receptor_pdb_path=receptor_path, output_dir=output_dir
        )
        predictions_path = output_dir / f"{receptor_path.name}_predictions.csv"
        if execution.exit_code != 0 or not predictions_path.is_file():
            raise AnkoraDomainError(
                code="POCKET_DETECTION_FAILED",
                stage="pocket_detection",
                message="P2Rank did not produce a pocket prediction for this receptor.",
                status_code=422,
                details={
                    "receptor_id": receptor_id,
                    "tool_version": tool_version,
                    "command": execution.command,
                    "exit_code": execution.exit_code,
                    "stdout": execution.stdout,
                    "stderr": execution.stderr,
                },
            )
        rows = _parse_predictions_csv(predictions_path)
        predictions_csv = predictions_path.read_text(encoding="utf-8", errors="replace")

    candidates = [_build_candidate(row, structure[0]) for row in rows]

    report_id = pocket_detection_store.new_report_id()
    generated_at = datetime.now(UTC)
    tool = ToolIdentity(name="P2Rank", version=tool_version)
    provenance = ProvenanceEvent(
        event_id=f"pocket-detection-{report_id}",
        event_type="pockets_detected",
        timestamp=generated_at,
        input_artifacts=[receptor_id],
        output_artifacts=[report_id],
        tool=tool,
        parameters={},
        command=execution.command,
    )
    report = PocketDetectionReport(
        report_id=report_id,
        receptor_id=receptor_id,
        source_output_artifact_id=output.artifact_id,
        generated_at=generated_at,
        tool=tool,
        candidates=candidates,
        warnings=[],
        provenance=provenance,
        execution=PocketDetectionExecutionEvidence(
            command=execution.command,
            exit_code=execution.exit_code,
            stdout=execution.stdout,
            stderr=execution.stderr,
            predictions_csv=predictions_csv,
        ),
    )
    pocket_detection_store.save_record(report)
    return report


def _parse_predictions_csv(path: Path) -> list[_PredictionRow]:
    with path.open("r", encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream, skipinitialspace=True)
        if reader.fieldnames:
            reader.fieldnames = [name.strip() for name in reader.fieldnames]
        rows: list[_PredictionRow] = []
        for raw in reader:
            residue_keys: list[tuple[str, int]] = []
            for token in raw["residue_ids"].split():
                chain_id, separator, sequence_text = token.partition("_")
                if not separator:
                    continue
                try:
                    residue_keys.append((chain_id, int(sequence_text)))
                except ValueError:
                    continue
            rows.append(
                _PredictionRow(
                    name=raw["name"].strip(),
                    rank=int(raw["rank"]),
                    probability=float(raw["probability"]),
                    center_x=float(raw["center_x"]),
                    center_y=float(raw["center_y"]),
                    center_z=float(raw["center_z"]),
                    residue_keys=residue_keys,
                )
            )
        return rows


def _build_candidate(row: _PredictionRow, model: gemmi.Model) -> PocketCandidate:
    if not row.residue_keys:
        raise AnkoraDomainError(
            code="POCKET_DETECTION_EMPTY_POCKET",
            stage="pocket_detection",
            message="P2Rank reported a pocket with no lining residues.",
            status_code=422,
            details={"pocket": row.name},
        )
    lining_residues: list[ResidueLocator] = []
    positions: list[gemmi.Position] = []
    for chain_id, sequence_number in row.residue_keys:
        matches = _find_residues(model, chain_id, sequence_number)
        if not matches:
            raise AnkoraDomainError(
                code="POCKET_DETECTION_RESIDUE_NOT_FOUND",
                stage="pocket_detection",
                message="A residue reported by P2Rank is not present in the prepared receptor.",
                status_code=422,
                details={
                    "pocket": row.name,
                    "chain_id": chain_id,
                    "sequence_number": sequence_number,
                },
            )
        if len(matches) > 1:
            # P2Rank's own residue_ids column is just "ChainID_SeqNum" — it
            # never reports an insertion code, so there's no way to tell
            # which of several same-numbered residues (e.g. 103 vs 103A) it
            # actually meant. Silently picking one would be exactly the kind
            # of guess this project's residue-identity checks exist to avoid.
            raise AnkoraDomainError(
                code="POCKET_DETECTION_RESIDUE_AMBIGUOUS",
                stage="pocket_detection",
                message=(
                    "P2Rank reported a residue number that matches more than one "
                    "residue in the prepared receptor (they differ only by "
                    "insertion code, which P2Rank does not report)."
                ),
                status_code=422,
                details={
                    "pocket": row.name,
                    "chain_id": chain_id,
                    "sequence_number": sequence_number,
                    "insertion_codes": [
                        clean_insertion_code(residue.seqid.icode) for residue in matches
                    ],
                },
            )
        residue = matches[0]
        lining_residues.append(
            ResidueLocator(
                chain_id=chain_id,
                residue_name=residue.name.strip() or "UNK",
                sequence_number=sequence_number,
                insertion_code=clean_insertion_code(residue.seqid.icode),
            )
        )
        positions.extend(atom.pos for atom in residue)

    return PocketCandidate(
        pocket_id=row.name,
        rank=row.rank,
        druggability_score=row.probability,
        volume_angstrom3=None,
        box=_pocket_box(row, positions),
        lining_residues=lining_residues,
    )


def _pocket_box(row: _PredictionRow, positions: list[gemmi.Position]) -> BindingBox:
    size_x = _padded_extent(pos.x for pos in positions)
    size_y = _padded_extent(pos.y for pos in positions)
    size_z = _padded_extent(pos.z for pos in positions)
    if size_x <= 0 or size_y <= 0 or size_z <= 0:
        raise AnkoraDomainError(
            code="BINDING_SITE_BOX_DEGENERATE",
            stage="pocket_detection",
            message="The computed pocket box has no volume.",
            status_code=422,
            details={"pocket": row.name},
        )
    return BindingBox(
        center_x=row.center_x,
        center_y=row.center_y,
        center_z=row.center_z,
        size_x=size_x,
        size_y=size_y,
        size_z=size_z,
    )


def _padded_extent(values: Iterable[float]) -> float:
    ordered = list(values)
    return (max(ordered) - min(ordered)) + 2 * POCKET_BOX_PADDING_ANGSTROM


def _find_residues(model: gemmi.Model, chain_id: str, sequence_number: int) -> list[gemmi.Residue]:
    matches: list[gemmi.Residue] = []
    for chain in model:
        if chain.name != chain_id:
            continue
        for residue in chain:
            if residue.seqid.num == sequence_number:
                matches.append(residue)
    return matches
