"""Verify one preserved GNINA job before projecting it into a screening result."""

from hashlib import sha256

from ankora_backend.domain.errors import AnkoraDomainError
from ankora_backend.persistence.gnina_store import GninaJobStore
from ankora_backend.schemas.docking import DockingJobStatus
from ankora_backend.schemas.gnina import GninaDockingRequest, GninaJobRecord, GninaPoseResult
from ankora_backend.schemas.gnina_screening import (
    GninaScreeningCampaignRecord,
    GninaScreeningEntry,
)


def verified_screening_pose(
    *,
    store: GninaJobStore,
    job_id: str,
    expected_request: GninaDockingRequest,
    expected_receptor_sha256: str,
    expected_ligand_sha256: str,
    expected_conformer_sha256: str,
    expected_tool_sha256: str,
) -> GninaPoseResult:
    """Return mode 1 only when job identity and preserved input bytes still match.

    This is a projection of the existing single-job record, not a new docking
    computation or an assertion of experimental affinity. The caller must
    separately verify the applied library selection and preparation identities.
    """
    record = store.load_job(job_id)
    if (
        record.status is not DockingJobStatus.COMPLETED
        or record.job_id != job_id
        or record.request != expected_request
        or record.receptor_sha256 != expected_receptor_sha256
        or record.ligand_sha256 != expected_ligand_sha256
        or record.conformer_sha256 != expected_conformer_sha256
        or record.tool.sha256 != expected_tool_sha256
        or not record.poses
    ):
        raise _mismatch(job_id)

    for filename, digest in (
        ("receptor.pdbqt", record.receptor_sha256),
        ("ligand.pdbqt", record.ligand_sha256),
        ("conformer.sdf", record.conformer_sha256),
    ):
        try:
            content = store.output_path(job_id, filename).read_bytes()
        except OSError as error:
            raise _mismatch(job_id) from error
        if sha256(content).hexdigest() != digest:
            raise _mismatch(job_id)

    pose = record.poses[0]
    # The store validates the published pose's recorded hash before returning it.
    path = store.pose_content_path(job_id, pose.artifact.artifact_id)
    try:
        if path.stat().st_size != pose.artifact.size_bytes:
            raise _mismatch(job_id)
    except OSError as error:
        raise _mismatch(job_id) from error
    return pose


def verified_campaign_entry_job(
    *,
    store: GninaJobStore,
    campaign: GninaScreeningCampaignRecord,
    entry: GninaScreeningEntry,
) -> GninaJobRecord:
    """Verify a completed screening entry's child job and all published poses."""
    job_id = entry.gnina_job_id
    if (
        entry.status is not DockingJobStatus.COMPLETED
        or job_id is None
        or entry.ligand_preparation_id is None
        or entry.ligand_sha256 is None
        or entry.conformer_sha256 is None
    ):
        raise _mismatch(job_id or entry.ligand_id)

    expected_request = GninaDockingRequest(
        receptor_id=campaign.request.receptor_id,
        binding_site_id=campaign.request.binding_site_id,
        ligand_id=entry.ligand_id,
        ligand_preparation_id=entry.ligand_preparation_id,
        parameters=campaign.request.parameters,
        acknowledge_inputs_and_scoring=True,
    )
    verified_screening_pose(
        store=store,
        job_id=job_id,
        expected_request=expected_request,
        expected_receptor_sha256=campaign.receptor_sha256,
        expected_ligand_sha256=entry.ligand_sha256,
        expected_conformer_sha256=entry.conformer_sha256,
        expected_tool_sha256=campaign.tool.sha256,
    )
    record = store.load_job(job_id)
    if (
        record.screening_campaign_id != campaign.campaign_id
        or record.box != campaign.box
        or record.receptor_output_artifact_id != campaign.receptor_output_artifact_id
        or record.tool != campaign.tool
    ):
        raise _mismatch(job_id)

    for pose in record.poses[1:]:
        path = store.pose_content_path(job_id, pose.artifact.artifact_id)
        try:
            if path.stat().st_size != pose.artifact.size_bytes:
                raise _mismatch(job_id)
        except OSError as error:
            raise _mismatch(job_id) from error
    return record


def _mismatch(job_id: str) -> AnkoraDomainError:
    return AnkoraDomainError(
        code="GNINA_SCREENING_JOB_MISMATCH",
        stage="gnina_screening",
        message="The recorded GNINA job or its preserved inputs do not match this campaign entry.",
        status_code=409,
        details={"job_id": job_id},
    )
