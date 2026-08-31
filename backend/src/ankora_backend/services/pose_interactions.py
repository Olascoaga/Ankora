"""Resolve and analyze one exact pose from the durable M6 result catalog."""

from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any
from uuid import uuid4

from ankora_backend.adapters.chemistry.redocking_rmsd import pdbqt_to_pdb_block
from ankora_backend.adapters.interactions.prolif_adapter import ProlifInteractionAdapter
from ankora_backend.domain.errors import AnkoraDomainError
from ankora_backend.persistence.autodock4_store import AutoDock4JobStore
from ankora_backend.persistence.autodock_gpu_store import AutoDockGpuJobStore
from ankora_backend.persistence.autogrid_store import AutoGridMapStore
from ankora_backend.persistence.docking_store import DockingArtifactStore
from ankora_backend.persistence.ligand_store import LigandArtifactStore
from ankora_backend.persistence.pose_interaction_store import PoseInteractionStore
from ankora_backend.persistence.receptor_store import ReceptorArtifactStore
from ankora_backend.schemas.pose_interactions import (
    InteractionAnalysisRecord,
    InteractionAnalysisRequest,
    PoseInventory,
    PoseKind,
    PoseReference,
)
from ankora_backend.schemas.provenance import ProvenanceEvent, ToolIdentity
from ankora_backend.schemas.receptors import ReceptorOutputStage
from ankora_backend.services.result_catalog import (
    AUTODOCK4_BATCH,
    AUTODOCK4_JOB,
    AUTODOCK_GPU_BATCH,
    AUTODOCK_GPU_JOB,
    VINA_BATCH,
    VINA_JOB,
)

_STAGE = "pose_interaction_analysis"


@dataclass(frozen=True)
class _ResolvedPose:
    catalog_id: str
    engine_key: str
    record_id: str
    engine_label: str
    ligand_id: str
    ligand_preparation_id: str
    receptor_id: str
    docking_receptor_artifact_id: str
    docking_receptor_sha256: str
    pose: PoseReference
    pose_path: Path


class PoseInteractionService:
    def __init__(
        self,
        *,
        docking_store: DockingArtifactStore,
        autodock4_store: AutoDock4JobStore,
        autodock_gpu_store: AutoDockGpuJobStore,
        autogrid_store: AutoGridMapStore,
        receptor_store: ReceptorArtifactStore,
        ligand_store: LigandArtifactStore,
        interaction_store: PoseInteractionStore,
        adapter: ProlifInteractionAdapter | None = None,
    ) -> None:
        self._docking = docking_store
        self._autodock4 = autodock4_store
        self._gpu = autodock_gpu_store
        self._autogrid = autogrid_store
        self._receptors = receptor_store
        self._ligands = ligand_store
        self._interactions = interaction_store
        self._adapter = adapter or ProlifInteractionAdapter()

    @classmethod
    def from_environment(cls) -> "PoseInteractionService":
        return cls(
            docking_store=DockingArtifactStore.from_environment(),
            autodock4_store=AutoDock4JobStore.from_environment(),
            autodock_gpu_store=AutoDockGpuJobStore.from_environment(),
            autogrid_store=AutoGridMapStore.from_environment(),
            receptor_store=ReceptorArtifactStore.from_environment(),
            ligand_store=LigandArtifactStore.from_environment(),
            interaction_store=PoseInteractionStore.from_environment(),
        )

    def list_poses(self, catalog_id: str, ligand_id: str) -> PoseInventory:
        engine_key, record_id = _split(catalog_id)
        poses, context = self._native_poses(engine_key, record_id, ligand_id)
        receptor_record = self._receptors.load_record(context["receptor_id"])
        analysis_output = next(
            (
                item
                for item in receptor_record.outputs
                if item.stage is ReceptorOutputStage.PROTONATED_PDB
            ),
            None,
        )
        return PoseInventory(
            catalog_id=catalog_id,
            ligand_id=ligand_id,
            engine_label=context["engine_label"],
            receptor_artifact_id=(
                analysis_output.artifact_id if analysis_output is not None else None
            ),
            receptor_content_url=(
                analysis_output.content_url if analysis_output is not None else None
            ),
            poses=poses,
        )

    def list_analyses(
        self, catalog_id: str, ligand_id: str, pose_artifact_id: str
    ) -> list[InteractionAnalysisRecord]:
        self._resolve(catalog_id, ligand_id, pose_artifact_id)
        return self._interactions.list_for_pose(
            catalog_id, ligand_id, pose_artifact_id
        )

    def analyze(
        self,
        catalog_id: str,
        ligand_id: str,
        pose_artifact_id: str,
        request: InteractionAnalysisRequest,
    ) -> InteractionAnalysisRecord:
        resolved = self._resolve(catalog_id, ligand_id, pose_artifact_id)
        receptor_record = self._receptors.load_record(resolved.receptor_id)
        docking_output = next(
            (
                item
                for item in receptor_record.outputs
                if item.artifact_id == resolved.docking_receptor_artifact_id
            ),
            None,
        )
        if docking_output is None or docking_output.sha256 != resolved.docking_receptor_sha256:
            raise _failure(
                "POSE_INTERACTION_RECEPTOR_IDENTITY_MISMATCH",
                "The receptor artifact recorded by docking no longer matches its receptor record.",
            )
        docking_receptor_path = self._receptors.content_path(
            resolved.receptor_id, docking_output.artifact_id
        )
        _verify_hash(docking_receptor_path, docking_output.sha256, "docking receptor")

        analysis_output = next(
            (
                item
                for item in receptor_record.outputs
                if item.stage is ReceptorOutputStage.PROTONATED_PDB
            ),
            None,
        )
        if analysis_output is None:
            raise _failure(
                "POSE_INTERACTION_RECEPTOR_FORMAT_UNAVAILABLE",
                "This prepared receptor has no protonated PDB representation "
                "for interaction analysis.",
            )
        receptor_path = self._receptors.content_path(
            resolved.receptor_id, analysis_output.artifact_id
        )
        _verify_hash(receptor_path, analysis_output.sha256, "analysis receptor")

        preparation = self._ligands.load_pdbqt_record(
            ligand_id, resolved.ligand_preparation_id
        )
        if preparation.artifact.ligand_id != ligand_id:
            raise _failure(
                "POSE_INTERACTION_LIGAND_IDENTITY_MISMATCH",
                "The recorded ligand preparation belongs to a different ligand.",
            )
        conformer = self._ligands.load_conformer_record(
            ligand_id, preparation.artifact.conformer_id
        )
        conformer_path = self._ligands.conformer_content_path(
            ligand_id, conformer.artifact.conformer_id
        )
        _verify_hash(conformer_path, conformer.artifact.sha256, "ligand conformer")
        _verify_hash(resolved.pose_path, resolved.pose.sha256, "docking pose")

        contacts, diagram = self._adapter.analyze(
            pose_path=resolved.pose_path,
            conformer_path=conformer_path,
            receptor_path=receptor_path,
            profile=request.profile,
        )
        created_at = datetime.now(UTC)
        analysis_id = self._interactions.new_analysis_id()
        detector = ToolIdentity(name="ProLIF", version=self._adapter.version())
        provenance = ProvenanceEvent(
            event_id=str(uuid4()),
            event_type="pose_interactions_analyzed",
            timestamp=created_at,
            input_artifacts=[
                resolved.docking_receptor_artifact_id,
                analysis_output.artifact_id,
                preparation.artifact.preparation_id,
                conformer.artifact.conformer_id,
                resolved.pose.artifact_id,
            ],
            output_artifacts=[analysis_id],
            tool=detector,
            parameters={
                "catalog_id": catalog_id,
                "profile": request.profile.model_dump(mode="json"),
                "topology_validation": "Meeko PDBQT reconstruction matched to exact conformer SDF",
            },
        )
        record = InteractionAnalysisRecord(
            analysis_id=analysis_id,
            created_at=created_at,
            catalog_id=catalog_id,
            engine_key=resolved.engine_key,
            record_id=resolved.record_id,
            engine_label=resolved.engine_label,
            ligand_id=ligand_id,
            ligand_preparation_id=resolved.ligand_preparation_id,
            conformer_id=conformer.artifact.conformer_id,
            conformer_sha256=conformer.artifact.sha256,
            pose=resolved.pose,
            receptor_id=resolved.receptor_id,
            docking_receptor_artifact_id=resolved.docking_receptor_artifact_id,
            docking_receptor_sha256=resolved.docking_receptor_sha256,
            analysis_receptor_artifact_id=analysis_output.artifact_id,
            analysis_receptor_sha256=analysis_output.sha256,
            analysis_receptor_content_url=analysis_output.content_url,
            detector=detector,
            profile=request.profile,
            contacts=contacts,
            ligand_diagram=diagram,
            provenance=provenance,
        )
        self._interactions.create(record)
        return record

    def complex_pdb(
        self, catalog_id: str, ligand_id: str, pose_artifact_id: str
    ) -> tuple[str, str]:
        """The receptor and this exact pose in one PDB, for any other viewer.

        Both halves are copied from the preserved artifacts after their hashes
        are checked, so what opens in PyMOL or Chimera is the same geometry
        Ankora analyzed - not a re-docked, re-minimized or re-oriented copy of
        it. The only thing Ankora writes is the chain identifier the ligand
        needed in order not to collide with the receptor's own.
        """
        resolved = self._resolve(catalog_id, ligand_id, pose_artifact_id)
        receptor_record = self._receptors.load_record(resolved.receptor_id)
        analysis_output = next(
            (
                item
                for item in receptor_record.outputs
                if item.stage is ReceptorOutputStage.PROTONATED_PDB
            ),
            None,
        )
        if analysis_output is None:
            raise _failure(
                "POSE_COMPLEX_RECEPTOR_FORMAT_UNAVAILABLE",
                "This prepared receptor has no PDB representation to combine "
                "with the pose.",
            )
        receptor_path = self._receptors.content_path(
            resolved.receptor_id, analysis_output.artifact_id
        )
        _verify_hash(receptor_path, analysis_output.sha256, "analysis receptor")
        _verify_hash(resolved.pose_path, resolved.pose.sha256, "docking pose")

        receptor_lines = [
            line
            for line in receptor_path.read_text(encoding="utf-8").splitlines()
            if line.startswith(("ATOM", "HETATM"))
        ]
        if not receptor_lines:
            raise _failure(
                "POSE_COMPLEX_RECEPTOR_EMPTY",
                "The preserved receptor holds no atoms to combine with the pose.",
            )
        ligand_chain = _free_chain_id(receptor_lines)
        ligand_lines = _named_ligand_atoms(
            pdbqt_to_pdb_block(
                resolved.pose_path.read_text(encoding="utf-8"), keep_hydrogens=True
            ).splitlines(),
            ligand_chain,
            first_serial=_next_serial(receptor_lines),
        )

        header = [
            "REMARK   1 Ankora ligand-receptor complex",
            f"REMARK   1 RESULT          {catalog_id}",
            f"REMARK   1 ENGINE          {_ascii(resolved.engine_label)}",
            f"REMARK   1 LIGAND          {ligand_id}",
            f"REMARK   1 POSE            {_ascii(resolved.pose.label)}",
            f"REMARK   1 POSE VALUE      {resolved.pose.result_kcal_mol:.3f} kcal/mol"
            f" ({_ascii(resolved.pose.value_label)})",
            f"REMARK   1 POSE SHA256     {resolved.pose.sha256}",
            f"REMARK   1 RECEPTOR        {analysis_output.artifact_id}",
            f"REMARK   1 RECEPTOR SHA256 {analysis_output.sha256}",
            f"REMARK   1 LIGAND CHAIN    {ligand_chain} (assigned by Ankora; free here)",
            "REMARK   1 Ligand atom names are assigned C1, C2, O1 ... because a",
            "REMARK   1 PDBQT names every atom for its element alone, and a PDB",
            "REMARK   1 reader splits a residue whose atom names repeat. Serials",
            "REMARK   1 continue the receptor's rather than restarting at 1.",
            "REMARK   1 Coordinates are copied unchanged. Nothing was re-docked,",
            "REMARK   1 re-minimized, superimposed or re-oriented.",
            "REMARK   1 The value above is a computational estimate, not a",
            "REMARK   1 measured binding affinity.",
        ]
        document = "\n".join(
            [*header, *receptor_lines, "TER", *ligand_lines, "END", ""]
        )
        filename = f"complex_{_ascii(resolved.pose.label).replace(chr(32), chr(95))}.pdb"
        return document, filename

    def _resolve(
        self, catalog_id: str, ligand_id: str, pose_artifact_id: str
    ) -> _ResolvedPose:
        engine_key, record_id = _split(catalog_id)
        poses, context = self._native_poses(engine_key, record_id, ligand_id)
        pose = next((item for item in poses if item.artifact_id == pose_artifact_id), None)
        if pose is None:
            raise _failure(
                "RESULT_POSE_NOT_FOUND",
                "This pose does not belong to the selected molecule and result.",
                status_code=404,
                details={"pose_artifact_id": pose_artifact_id},
            )
        return _ResolvedPose(
            catalog_id=catalog_id,
            engine_key=engine_key,
            record_id=record_id,
            engine_label=context["engine_label"],
            ligand_id=ligand_id,
            ligand_preparation_id=str(context["ligand_preparation_id"]),
            receptor_id=str(context["receptor_id"]),
            docking_receptor_artifact_id=str(context["receptor_artifact_id"]),
            docking_receptor_sha256=str(context["receptor_sha256"]),
            pose=pose,
            pose_path=self._pose_path(
                engine_key, record_id, ligand_id, pose_artifact_id
            ),
        )

    def _native_poses(
        self, engine_key: str, record_id: str, ligand_id: str
    ) -> tuple[list[PoseReference], dict[str, str]]:
        if engine_key == VINA_BATCH:
            vina_batch = self._docking.load_batch_record(record_id)
            entry = _entry(vina_batch.entries, ligand_id)
            context = {
                "engine_label": f"{vina_batch.tool.name} {vina_batch.tool.version}",
                "ligand_preparation_id": _required(entry.ligand_preparation_id),
                "receptor_id": vina_batch.request.receptor_id,
                "receptor_artifact_id": vina_batch.receptor_output_artifact_id,
                "receptor_sha256": vina_batch.receptor_sha256,
            }
            return [_vina_pose(item) for item in entry.poses], context
        if engine_key == VINA_JOB:
            vina_job = self._docking.load_record(record_id)
            _same_ligand(vina_job.request.ligand_id, ligand_id)
            return [_vina_pose(item) for item in vina_job.poses], {
                "engine_label": f"{vina_job.tool.name} {vina_job.tool.version}",
                "ligand_preparation_id": vina_job.request.ligand_preparation_id,
                "receptor_id": vina_job.request.receptor_id,
                "receptor_artifact_id": vina_job.receptor_output_artifact_id,
                "receptor_sha256": vina_job.receptor_sha256,
            }
        if engine_key in (AUTODOCK4_BATCH, AUTODOCK_GPU_BATCH):
            store: Any = self._autodock4 if engine_key == AUTODOCK4_BATCH else self._gpu
            record = store.load_batch(record_id)
            entry = _entry(record.entries, ligand_id)
            maps = self._autogrid.load_record(record.map_set_id)
            return [_autodock_pose(item) for item in entry.runs], {
                "engine_label": _autodock_label(record, engine_key),
                "ligand_preparation_id": _required(entry.ligand_preparation_id),
                "receptor_id": record.receptor_id,
                "receptor_artifact_id": maps.receptor_output_artifact_id,
                "receptor_sha256": maps.receptor_sha256,
            }
        if engine_key in (AUTODOCK4_JOB, AUTODOCK_GPU_JOB):
            store = self._autodock4 if engine_key == AUTODOCK4_JOB else self._gpu
            record = store.load_job(record_id)
            _same_ligand(record.request.ligand_id, ligand_id)
            maps = self._autogrid.load_record(record.map_set_id)
            return [_autodock_pose(item) for item in record.runs], {
                "engine_label": _autodock_label(record, engine_key),
                "ligand_preparation_id": record.request.ligand_preparation_id,
                "receptor_id": record.receptor_id,
                "receptor_artifact_id": maps.receptor_output_artifact_id,
                "receptor_sha256": maps.receptor_sha256,
            }
        raise _failure(
            "RESULT_CATALOG_ENGINE_UNKNOWN",
            "Ankora has no pose resolver for this kind of result.",
            details={"engine_key": engine_key},
        )

    def _pose_path(
        self, engine_key: str, record_id: str, ligand_id: str, artifact_id: str
    ) -> Path:
        if engine_key == VINA_BATCH:
            return self._docking.batch_pose_content_path(record_id, ligand_id, artifact_id)
        if engine_key == VINA_JOB:
            return self._docking.pose_content_path(record_id, artifact_id)
        if engine_key == AUTODOCK4_BATCH:
            return self._autodock4.batch_pose_content_path(
                record_id, ligand_id, artifact_id
            )
        if engine_key == AUTODOCK4_JOB:
            return self._autodock4.pose_content_path(record_id, artifact_id)
        if engine_key == AUTODOCK_GPU_BATCH:
            return self._gpu.batch_pose_content_path(record_id, ligand_id, artifact_id)
        if engine_key == AUTODOCK_GPU_JOB:
            return self._gpu.pose_content_path(record_id, artifact_id)
        raise _failure("RESULT_CATALOG_ENGINE_UNKNOWN", "Unknown result engine.")


def _vina_pose(item: Any) -> PoseReference:
    return PoseReference(
        artifact_id=item.artifact.artifact_id,
        kind=PoseKind.VINA_MODE,
        ordinal=item.mode,
        label=f"Mode {item.mode}",
        result_kcal_mol=item.affinity_kcal_mol,
        value_label="Vina score",
        rmsd_lower_bound_angstrom=item.rmsd_lower_bound_angstrom,
        rmsd_upper_bound_angstrom=item.rmsd_upper_bound_angstrom,
        sha256=item.artifact.sha256,
        content_url=item.artifact.content_url,
    )


def _autodock_pose(item: Any) -> PoseReference:
    return PoseReference(
        artifact_id=item.artifact.artifact_id,
        kind=PoseKind.AUTODOCK_RUN,
        ordinal=item.run,
        label=f"Cluster {item.cluster_rank} · run {item.run}",
        result_kcal_mol=item.binding_energy_kcal_mol,
        value_label="Binding energy",
        cluster_rank=item.cluster_rank,
        sub_rank=item.sub_rank,
        cluster_rmsd_angstrom=item.cluster_rmsd_angstrom,
        reference_rmsd_angstrom=item.reference_rmsd_angstrom,
        sha256=item.artifact.sha256,
        content_url=item.artifact.content_url,
    )


def _autodock_label(record: Any, engine_key: str) -> str:
    if engine_key in (AUTODOCK4_BATCH, AUTODOCK4_JOB):
        return f"{record.autodock4.tool.name} {record.autodock4.tool.version} · CPU"
    return f"AutoDock4 · {record.autodock_gpu.tool.name} {record.autodock_gpu.tool.version}"


def _entry(entries: list[Any], ligand_id: str) -> Any:
    entry = next((item for item in entries if item.ligand_id == ligand_id), None)
    if entry is None:
        raise _failure(
            "RESULT_LIGAND_NOT_FOUND",
            "This molecule does not belong to the selected result.",
            status_code=404,
            details={"ligand_id": ligand_id},
        )
    return entry


def _same_ligand(expected: str, actual: str) -> None:
    if expected != actual:
        raise _failure(
            "RESULT_LIGAND_NOT_FOUND",
            "This molecule does not belong to the selected result.",
            status_code=404,
            details={"ligand_id": actual},
        )


def _next_serial(receptor_lines: list[str]) -> int:
    """One past the receptor's last atom serial."""
    serials = [
        int(line[6:11]) for line in receptor_lines if line[6:11].strip().isdigit()
    ]
    return (max(serials) + 1) if serials else 1


def _named_ligand_atoms(
    lines: list[str], chain: str, *, first_serial: int
) -> list[str]:
    """One residue, uniquely named and numbered, which a PDB reader needs.

    A PDBQT names every atom for its element and starts its serials at 1, so
    the pose arrives with duplicate names *and* thirty serials the receptor
    already used. Read back through gemmi that is not one ligand at all - it is
    twenty-five separate residues, measured. Names, serials and the chain are
    the only things assigned here, and the PDBQT-only columns are cleared;
    every coordinate is the one the engine wrote.
    """
    counts: dict[str, int] = {}
    named: list[str] = []
    # Columns 67-76 are unused in a PDB, but a PDBQT leaves the atom's partial
    # charge there and columns 73-76 are the segment identifier. Read back, a
    # different charge per atom is a different segment per atom, which is what
    # actually split this ligand into twenty-five residues.
    blank = " " * 10
    for offset, line in enumerate(lines):
        element = line[76:78].strip()
        counts[element] = counts.get(element, 0) + 1
        name = f"{element}{counts[element]}"[:4]
        column = name.ljust(4) if len(element) > 1 else f" {name}".ljust(4)
        serial = str(first_serial + offset).rjust(5)[:5]
        named.append(
            f"HETATM{serial} {column}{line[16:21]}{chain}{line[22:66]}"
            f"{blank}{line[76:78]}"
        )
    return named


def _ascii(value: str) -> str:
    """A PDB is read by parsers written decades before UTF-8.

    Ankora's own labels carry a middle dot; a header line and a filename both
    have to survive tools that assume every byte is ASCII, so it becomes a
    hyphen here rather than a replacement character somewhere downstream.
    """
    folded = value.replace("·", "-").replace("–", "-").replace("—", "-")
    return folded.encode("ascii", "ignore").decode("ascii").strip()


def _free_chain_id(receptor_lines: list[str]) -> str:
    """A chain the receptor does not already use, so nothing is overwritten."""
    taken = {line[21] for line in receptor_lines if len(line) > 21}
    for candidate in "ZYXWVUTSRQPONMLKJIHGFEDCBA0123456789":
        if candidate not in taken:
            return candidate
    raise _failure(
        "POSE_COMPLEX_NO_FREE_CHAIN",
        "This receptor already uses every chain identifier, so the pose cannot "
        "be added without overwriting one.",
    )


def _required(value: str | None) -> str:
    if value is None:
        raise _failure(
            "POSE_INTERACTION_PREPARATION_MISSING",
            "The selected result has no completed ligand preparation to analyze.",
        )
    return value


def _split(catalog_id: str) -> tuple[str, str]:
    engine_key, separator, record_id = catalog_id.partition(":")
    if not separator or not engine_key or not record_id:
        raise _failure(
            "RESULT_CATALOG_ID_INVALID",
            "A catalog identifier names its engine and its record.",
        )
    return engine_key, record_id


def _verify_hash(path: Path, expected: str, label: str) -> None:
    digest = sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    actual = digest.hexdigest()
    if actual != expected:
        raise _failure(
            "POSE_INTERACTION_INPUT_HASH_MISMATCH",
            f"The preserved {label} no longer matches its recorded SHA-256.",
            details={"path": path.name, "expected_sha256": expected, "actual_sha256": actual},
        )


def _failure(
    code: str,
    message: str,
    *,
    status_code: int = 422,
    details: dict[str, object] | None = None,
) -> AnkoraDomainError:
    return AnkoraDomainError(
        code=code,
        stage=_STAGE,
        message=message,
        status_code=status_code,
        details=details,
    )
