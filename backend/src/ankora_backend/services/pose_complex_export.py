"""Write one exact ligand-receptor complex into an explicit folder.

The coordinate document is produced by :class:`PoseInteractionService`, which
verifies both preserved inputs before combining them. This service only gives
those bytes a durable, create-only home and records where they went.
"""

import json
import os
import re
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

from ankora_backend.domain.errors import AnkoraDomainError
from ankora_backend.schemas.pose_complexes import (
    PoseComplexExport,
    PoseComplexExportRequest,
    PoseComplexFile,
    PoseComplexManifest,
)
from ankora_backend.services.pose_interactions import PoseInteractionService

_STAGE = "pose_complex_export"


class PoseComplexExportService:
    def __init__(self, *, root: Path, pose_service: PoseInteractionService) -> None:
        self._root = root.resolve()
        self._poses = pose_service

    @classmethod
    def from_environment(cls) -> "PoseComplexExportService":
        configured = os.getenv("ANKORA_DATA_DIR")
        root = Path(configured) if configured else Path.cwd() / ".ankora-data"
        return cls(root=root, pose_service=PoseInteractionService.from_environment())

    def export(
        self,
        catalog_id: str,
        ligand_id: str,
        pose_artifact_id: str,
        request: PoseComplexExportRequest,
    ) -> PoseComplexExport:
        inventory = self._poses.list_poses(catalog_id, ligand_id)
        exact_pose = next(
            (item for item in inventory.poses if item.artifact_id == pose_artifact_id),
            None,
        )
        if exact_pose is None:
            raise _failure(
                "RESULT_POSE_NOT_FOUND",
                "This pose does not belong to the selected molecule and result.",
                details={"pose_artifact_id": pose_artifact_id},
            )
        document, generated_name = self._poses.complex_pdb(catalog_id, ligand_id, pose_artifact_id)
        payload = document.encode("utf-8")
        chosen = _validated_destination(request.destination)

        export_id = str(uuid4())
        record_directory = (
            self._root / "projects" / "default" / "exports" / "pose_complexes" / export_id
        ).resolve()
        if self._root not in record_directory.parents:
            raise _failure(
                "POSE_COMPLEX_DESTINATION_INVALID",
                "The project export folder could not be resolved safely.",
            )
        record_directory.mkdir(parents=True, exist_ok=False)

        directory = chosen or record_directory
        basename = (
            _slug(f"{request.molecule_name}_{Path(generated_name).stem}")
            if chosen
            else "ligand_receptor_complex"
        )
        filename = _free_name(directory, basename or "ligand_receptor_complex", "pdb")
        path = directory / filename
        try:
            with path.open("xb") as stream:
                stream.write(payload)
        except OSError as error:
            raise _failure(
                "POSE_COMPLEX_WRITE_FAILED",
                "The ligand-receptor PDB could not be written into that folder.",
                details={"destination": str(directory), "reason": str(error)},
            ) from error

        exported_at = datetime.now(UTC)
        exported = PoseComplexExport(
            export_id=export_id,
            exported_at=exported_at,
            catalog_id=catalog_id,
            ligand_id=ligand_id,
            molecule_name=request.molecule_name,
            pose_artifact_id=pose_artifact_id,
            pose_label=exact_pose.label,
            directory=str(directory),
            outside_project=chosen is not None,
            record_directory=str(record_directory),
            file=PoseComplexFile(
                filename=filename,
                sha256=sha256(payload).hexdigest(),
                size_bytes=len(payload),
            ),
        )
        manifest = PoseComplexManifest(
            export_id=exported.export_id,
            exported_at=exported.exported_at,
            catalog_id=exported.catalog_id,
            ligand_id=exported.ligand_id,
            molecule_name=exported.molecule_name,
            pose_artifact_id=exported.pose_artifact_id,
            pose_label=exported.pose_label,
            written_to=exported.directory,
            recorded_in=exported.record_directory,
            file=exported.file,
            notes=[
                "The receptor coordinates and this exact docking pose were copied "
                "without re-docking, minimization, superposition or reorientation.",
                "Ligand atom names, serials and one free chain identifier were assigned "
                "only to make the combined PDB unambiguous to external viewers.",
            ],
        )
        manifest_text = (
            json.dumps(manifest.model_dump(mode="json"), indent=2, ensure_ascii=False) + "\n"
        )
        with (record_directory / "complex.json").open(
            "x", encoding="utf-8", newline="\n"
        ) as stream:
            stream.write(manifest_text)
        if chosen is not None:
            manifest_name = _free_name(chosen, basename or "ligand_receptor_complex", "json")
            with (chosen / manifest_name).open("x", encoding="utf-8", newline="\n") as stream:
                stream.write(manifest_text)
        return exported


def _validated_destination(destination: str | None) -> Path | None:
    if destination is None:
        return None
    path = Path(destination).expanduser()
    if not path.is_absolute():
        raise _failure(
            "POSE_COMPLEX_DESTINATION_INVALID",
            "A destination folder has to be a full path.",
            details={"destination": destination},
        )
    resolved = path.resolve()
    if not resolved.is_dir():
        raise _failure(
            "POSE_COMPLEX_DESTINATION_NOT_FOUND",
            "That destination folder does not exist. Ankora will not guess or "
            "create a working folder on your behalf.",
            details={"destination": str(resolved)},
        )
    if not os.access(resolved, os.W_OK):
        raise _failure(
            "POSE_COMPLEX_DESTINATION_NOT_WRITABLE",
            "Ankora cannot write into that folder.",
            details={"destination": str(resolved)},
        )
    return resolved


def _slug(value: str) -> str:
    kept = [
        character
        if character.isascii() and (character.isalnum() or character in "-_")
        else ("-" if character in " ." else "")
        for character in value.strip()
    ]
    return re.sub(r"-{2,}", "-", "".join(kept)).strip("-_")


def _free_name(directory: Path, basename: str, extension: str) -> str:
    candidate = f"{basename}.{extension}"
    index = 2
    while (directory / candidate).exists():
        candidate = f"{basename} ({index}).{extension}"
        index += 1
    return candidate


def _failure(
    code: str, message: str, *, details: dict[str, object] | None = None
) -> AnkoraDomainError:
    return AnkoraDomainError(
        code=code,
        stage=_STAGE,
        message=message,
        status_code=422,
        details=details,
    )
