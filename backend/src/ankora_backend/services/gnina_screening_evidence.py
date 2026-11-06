"""Verify one preserved GNINA job before projecting it into a screening result."""

from hashlib import sha256

from ankora_backend.domain.errors import AnkoraDomainError
from ankora_backend.persistence.gnina_store import GninaJobStore
from ankora_backend.schemas.docking import DockingJobStatus
from ankora_backend.schemas.gnina import GninaDockingRequest, GninaPoseResult


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


def _mismatch(job_id: str) -> AnkoraDomainError:
    return AnkoraDomainError(
        code="GNINA_SCREENING_JOB_MISMATCH",
        stage="gnina_screening",
        message="The recorded GNINA job or its preserved inputs do not match this campaign entry.",
        status_code=409,
        details={"job_id": job_id},
    )
