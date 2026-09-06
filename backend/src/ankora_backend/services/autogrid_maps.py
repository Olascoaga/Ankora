"""Immutable AutoGrid4 map-set generation with reuse by exact scientific identity."""

import json
import shutil
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

from ankora_backend.adapters.engines.autodock4 import (
    collect_autodock_atom_types,
    plan_autodock_grid,
    preflight_autodock4_cpu_atom_types,
    preflight_autodock4_receptor_atom_types,
    render_autogrid_gpf,
)
from ankora_backend.adapters.engines.autogrid import (
    GRID_LOG_FILENAME,
    GRID_PARAMETER_FILENAME,
    MAP_PREFIX,
    RECEPTOR_FILENAME,
    AutoGridInstallation,
    execute_autogrid_cancellable,
    grid_log_reports_success,
    probe_autogrid4,
    validate_against_autogrid_limits,
)
from ankora_backend.domain.errors import AnkoraDomainError
from ankora_backend.persistence.autogrid_store import AutoGridMapStore
from ankora_backend.persistence.binding_site_store import BindingSiteArtifactStore
from ankora_backend.persistence.ligand_store import LigandArtifactStore
from ankora_backend.persistence.receptor_store import ReceptorArtifactStore
from ankora_backend.schemas.autogrid import (
    AutoGridExecutionEvidence,
    AutoGridFailure,
    AutoGridGeometry,
    AutoGridJobCancelResponse,
    AutoGridJobPhase,
    AutoGridJobStatus,
    AutoGridLigandPreflightRow,
    AutoGridLigandSource,
    AutoGridMapArtifact,
    AutoGridMapJobRecord,
    AutoGridMapKind,
    AutoGridMapSetRecord,
    AutoGridMapSetRequest,
    AutoGridMapSetSummary,
    AutoGridPreflight,
)
from ankora_backend.schemas.binding_sites import BindingSiteRecord
from ankora_backend.schemas.ligand_library_preparation import LigandPreparationStatus
from ankora_backend.schemas.provenance import ProvenanceEvent
from ankora_backend.schemas.receptors import (
    ReceptorOutputArtifact,
    ReceptorOutputStage,
    ReceptorPreparationStatus,
)
from ankora_backend.schemas.work_recovery import WorkKind
from ankora_backend.services.resource_arbiter import (
    ResourceArbiter,
    ResourceLease,
    ResourceRequestCanceled,
    autogrid_claim,
)
from ankora_backend.services.work_leases import WorkLeaseManager

_STAGE = "autogrid_map_generation"


@dataclass(frozen=True, slots=True)
class _PreparedMapSet:
    """Everything validated before AutoGrid is launched, including the cache answer."""

    request: AutoGridMapSetRequest
    installation: AutoGridInstallation
    identity_key: str
    receptor_output: ReceptorOutputArtifact
    receptor_path: Path
    receptor_atom_types: tuple[str, ...]
    binding_site: BindingSiteRecord
    geometry: AutoGridGeometry
    preflight: AutoGridPreflight
    existing: AutoGridMapSetRecord | None


class _JobCanceled(Exception):
    """Internal signal: the scientist stopped this run; it is not a failure."""

    def __init__(self, *, execution: AutoGridExecutionEvidence, evidence_directory: str) -> None:
        super().__init__("AutoGrid generation was canceled")
        self.execution = execution
        self.evidence_directory = evidence_directory


def _as_optional_str(value: object) -> str | None:
    return value if isinstance(value, str) else None


class AutoGridMapService:
    def __init__(
        self,
        *,
        map_store: AutoGridMapStore,
        receptor_store: ReceptorArtifactStore,
        binding_site_store: BindingSiteArtifactStore,
        ligand_store: LigandArtifactStore,
        lease_manager: WorkLeaseManager | None = None,
        resource_arbiter: ResourceArbiter | None = None,
    ) -> None:
        self._map_store = map_store
        self._receptor_store = receptor_store
        self._binding_site_store = binding_site_store
        self._ligand_store = ligand_store
        self._leases = lease_manager
        self._resources = resource_arbiter
        # AutoGrid is memory and CPU heavy and a campaign only ever needs one
        # map set at a time, so runs serialize rather than competing.
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ankora-autogrid")
        self._cancel_events: dict[str, threading.Event] = {}
        self._lock = threading.RLock()

    @classmethod
    def from_environment(
        cls,
        *,
        lease_manager: WorkLeaseManager | None = None,
        resource_arbiter: ResourceArbiter | None = None,
    ) -> "AutoGridMapService":
        return cls(
            map_store=AutoGridMapStore.from_environment(),
            receptor_store=ReceptorArtifactStore.from_environment(),
            binding_site_store=BindingSiteArtifactStore.from_environment(),
            ligand_store=LigandArtifactStore.from_environment(),
            lease_manager=lease_manager,
            resource_arbiter=resource_arbiter,
        )

    def get(self, map_set_id: str) -> AutoGridMapSetRecord:
        return self._map_store.load_record(map_set_id)

    def content_path(self, map_set_id: str, artifact_id: str) -> Path:
        return self._map_store.content_path(map_set_id, artifact_id)

    def ensure_map_set(self, request: AutoGridMapSetRequest) -> AutoGridMapSetSummary:
        """Generate or reuse the map set for this identity, blocking until done.

        Suitable for a small pocket box. A full-protein grid takes minutes, so
        a caller that must stay responsive should use `start_map_set` instead.
        """
        prepared = self._prepare(request)
        if prepared.existing is not None:
            return AutoGridMapSetSummary(reused_existing_map_set=True, record=prepared.existing)
        if self._resources is None:
            record = self._generate(prepared, cancel_event=threading.Event())
        else:
            claim = autogrid_claim(
                prepared.identity_key,
                npts=prepared.geometry.npts,
                map_count=len(prepared.preflight.ligand_atom_types) + 2,
            )
            with self._resources.acquire(claim):
                record = self._generate(prepared, cancel_event=threading.Event())
        return AutoGridMapSetSummary(reused_existing_map_set=False, record=record)

    def start_map_set(self, request: AutoGridMapSetRequest) -> AutoGridMapJobRecord:
        """Validate now, generate in the background, and report progress by polling.

        Validation stays synchronous so an unusable request fails immediately
        with a structured error instead of becoming a queued job that cannot
        succeed. It is also what makes an identical prior map set return as an
        already-completed job rather than re-running AutoGrid.
        """
        prepared = self._prepare(request)
        now = datetime.now(UTC)
        job_id = self._map_store.new_job_id()
        record = AutoGridMapJobRecord(
            job_id=job_id,
            status=AutoGridJobStatus.QUEUED,
            phase=AutoGridJobPhase.QUEUED,
            created_at=now,
            request=request,
            identity_key=prepared.identity_key,
            geometry=prepared.geometry,
            preflight=prepared.preflight,
            autogrid=prepared.installation.identity(),
        )
        if prepared.existing is not None:
            record = record.model_copy(
                update={
                    "status": AutoGridJobStatus.COMPLETED,
                    "phase": AutoGridJobPhase.COMPLETE,
                    "started_at": now,
                    "completed_at": now,
                    "map_set_id": prepared.existing.map_set_id,
                    "reused_existing_map_set": True,
                }
            )
            self._map_store.create_job(record)
            return record

        self._map_store.create_job(record)
        cancel_event = threading.Event()
        with self._lock:
            self._cancel_events[job_id] = cancel_event
        self._executor.submit(self._run_job, job_id, prepared, cancel_event)
        return record

    def get_job(self, job_id: str) -> AutoGridMapJobRecord:
        return self._map_store.load_job(job_id)

    def cancel_job(self, job_id: str) -> AutoGridJobCancelResponse:
        with self._lock:
            record = self._map_store.load_job(job_id)
            if record.status in {
                AutoGridJobStatus.CANCELED,
                AutoGridJobStatus.COMPLETED,
                AutoGridJobStatus.FAILED,
            }:
                return AutoGridJobCancelResponse(job_id=job_id, status=record.status)
            cancel_event = self._cancel_events.get(job_id)
            if cancel_event is None:
                raise AnkoraDomainError(
                    code="AUTOGRID_JOB_NOT_ACTIVE",
                    stage=_STAGE,
                    message="This AutoGrid job is not active in the current Ankora session.",
                    status_code=409,
                    details={"job_id": job_id, "status": record.status.value},
                )
            cancel_event.set()
            self._map_store.update_job(
                record.model_copy(update={"status": AutoGridJobStatus.CANCEL_REQUESTED})
            )
        return AutoGridJobCancelResponse(job_id=job_id, status=AutoGridJobStatus.CANCEL_REQUESTED)

    def shutdown(self) -> None:
        with self._lock:
            for event in self._cancel_events.values():
                event.set()
        self._executor.shutdown(wait=True, cancel_futures=True)

    def has_active_work(self) -> bool:
        with self._lock:
            return bool(self._cancel_events)

    def _run_job(
        self,
        job_id: str,
        prepared: "_PreparedMapSet",
        cancel_event: threading.Event,
    ) -> None:
        resource_lease: ResourceLease | None = None
        if self._leases is not None:
            self._leases.acquire(WorkKind.AUTOGRID_JOB, job_id)
        record = self._map_store.load_job(job_id)
        if self._resources is not None:
            try:
                resource_lease = self._resources.acquire(
                    autogrid_claim(
                        job_id,
                        npts=prepared.geometry.npts,
                        map_count=len(prepared.preflight.ligand_atom_types) + 2,
                    ),
                    cancel_event=cancel_event,
                )
            except ResourceRequestCanceled:
                self._finish_job(record, status=AutoGridJobStatus.CANCELED)
                if self._leases is not None:
                    self._leases.release(WorkKind.AUTOGRID_JOB, job_id)
                self._forget(job_id)
                return
            except AnkoraDomainError as error:
                self._finish_job(
                    record,
                    status=AutoGridJobStatus.FAILED,
                    failure=AutoGridFailure(
                        code=error.code,
                        message=error.message,
                        details=dict(error.details),
                    ),
                )
                if self._leases is not None:
                    self._leases.release(WorkKind.AUTOGRID_JOB, job_id)
                self._forget(job_id)
                return
        if cancel_event.is_set():
            self._finish_job(record, status=AutoGridJobStatus.CANCELED)
            if resource_lease is not None:
                resource_lease.release()
            if self._leases is not None:
                self._leases.release(WorkKind.AUTOGRID_JOB, job_id)
            self._forget(job_id)
            return
        running = record.model_copy(
            update={
                "status": AutoGridJobStatus.RUNNING,
                "phase": AutoGridJobPhase.GENERATING_MAPS,
                "started_at": datetime.now(UTC),
            }
        )
        self._map_store.update_job(running)
        try:
            map_set = self._generate(prepared, cancel_event=cancel_event, job=running)
        except _JobCanceled as canceled:
            self._finish_job(
                running,
                status=AutoGridJobStatus.CANCELED,
                execution=canceled.execution,
                evidence_directory=canceled.evidence_directory,
            )
        except AnkoraDomainError as error:
            self._finish_job(
                running,
                status=AutoGridJobStatus.FAILED,
                failure=AutoGridFailure(
                    code=error.code, message=error.message, details=dict(error.details)
                ),
                evidence_directory=_as_optional_str(error.details.get("evidence_directory")),
            )
        else:
            self._finish_job(
                running,
                status=AutoGridJobStatus.COMPLETED,
                map_set_id=map_set.map_set_id,
                execution=map_set.execution,
            )
        finally:
            if resource_lease is not None:
                resource_lease.release()
            if self._leases is not None:
                self._leases.release(WorkKind.AUTOGRID_JOB, job_id)
            self._forget(job_id)

    def _finish_job(
        self,
        record: AutoGridMapJobRecord,
        *,
        status: AutoGridJobStatus,
        map_set_id: str | None = None,
        execution: AutoGridExecutionEvidence | None = None,
        failure: AutoGridFailure | None = None,
        evidence_directory: str | None = None,
    ) -> None:
        self._map_store.update_job(
            record.model_copy(
                update={
                    "status": status,
                    "phase": AutoGridJobPhase.COMPLETE,
                    "completed_at": datetime.now(UTC),
                    "map_set_id": map_set_id,
                    "execution": execution,
                    "failure": failure,
                    "evidence_directory": evidence_directory,
                }
            )
        )

    def _forget(self, job_id: str) -> None:
        with self._lock:
            self._cancel_events.pop(job_id, None)

    def _prepare(self, request: AutoGridMapSetRequest) -> "_PreparedMapSet":
        installation = probe_autogrid4()
        receptor_output, receptor_path, binding_site = self._validate_receptor_and_site(
            request.receptor_id, request.binding_site_id
        )
        receptor_document = receptor_path.read_text(encoding="utf-8", errors="replace")
        receptor_atom_types = preflight_autodock4_receptor_atom_types(
            collect_autodock_atom_types((receptor_document,))
        )
        preflight = self._preflight_ligands(request, receptor_atom_types)
        ligand_atom_types = tuple(preflight.ligand_atom_types)

        plan = plan_autodock_grid(
            binding_site.box, spacing_angstrom=request.parameters.spacing_angstrom
        )
        validate_against_autogrid_limits(
            installation,
            plan=plan,
            receptor_atom_types=receptor_atom_types,
            ligand_atom_types=ligand_atom_types,
        )
        geometry = AutoGridGeometry(
            spacing_angstrom=plan.spacing_angstrom,
            npts=plan.npts,
            requested_size_angstrom=plan.requested_size_angstrom,
            realized_size_angstrom=plan.realized_size_angstrom,
        )
        identity_key = self._identity_key(
            receptor_sha256=receptor_output.sha256,
            binding_site=binding_site,
            geometry=geometry,
            receptor_atom_types=receptor_atom_types,
            ligand_atom_types=ligand_atom_types,
            request=request,
            installation=installation,
        )
        return _PreparedMapSet(
            request=request,
            installation=installation,
            identity_key=identity_key,
            receptor_output=receptor_output,
            receptor_path=receptor_path,
            receptor_atom_types=receptor_atom_types,
            binding_site=binding_site,
            geometry=geometry,
            preflight=preflight,
            existing=self._map_store.find_by_identity(identity_key),
        )

    def _generate(
        self,
        prepared: "_PreparedMapSet",
        *,
        cancel_event: threading.Event,
        job: AutoGridMapJobRecord | None = None,
    ) -> AutoGridMapSetRecord:
        request = prepared.request
        installation = prepared.installation
        identity_key = prepared.identity_key
        receptor_output = prepared.receptor_output
        receptor_path = prepared.receptor_path
        receptor_atom_types = prepared.receptor_atom_types
        binding_site = prepared.binding_site
        geometry = prepared.geometry
        preflight = prepared.preflight
        ligand_atom_types = tuple(preflight.ligand_atom_types)
        gpf, _ = render_autogrid_gpf(
            binding_site.box,
            receptor_filename=RECEPTOR_FILENAME,
            receptor_atom_types=receptor_atom_types,
            ligand_atom_types=ligand_atom_types,
            map_prefix=MAP_PREFIX,
            spacing_angstrom=request.parameters.spacing_angstrom,
            smoothing_angstrom=request.parameters.smoothing_angstrom,
            dielectric=request.parameters.dielectric,
        )
        map_set_id = self._map_store.new_map_set_id()
        job_directory = self._map_store.create_map_set_directory(map_set_id)
        self._require_ascii_job_directory(job_directory)

        shutil.copyfile(receptor_path, job_directory / RECEPTOR_FILENAME)
        (job_directory / GRID_PARAMETER_FILENAME).write_text(gpf, encoding="ascii", newline="\n")

        started = time.monotonic()
        execution = execute_autogrid_cancellable(
            installation=installation,
            job_directory=job_directory,
            timeout_seconds=request.parameters.timeout_minutes * 60,
            cancel_event=cancel_event,
        )
        duration_seconds = time.monotonic() - started
        successful_log = grid_log_reports_success(job_directory)
        evidence = AutoGridExecutionEvidence(
            command=execution.command,
            exit_code=execution.exit_code,
            stdout=execution.stdout,
            stderr=execution.stderr,
            duration_seconds=duration_seconds,
            successful_completion_logged=successful_log,
        )
        if execution.canceled:
            # The partial directory stays on disk as evidence. It can never be
            # mistaken for a usable map set: no record.json was written, so
            # identity lookup ignores it.
            raise _JobCanceled(execution=evidence, evidence_directory=str(job_directory))
        if execution.timed_out:
            raise AnkoraDomainError(
                code="AUTOGRID_EXECUTION_TIMED_OUT",
                stage=_STAGE,
                message=(
                    "AutoGrid exceeded the configured timeout. Its raw output is "
                    "preserved for inspection."
                ),
                status_code=422,
                details={
                    "map_set_id": map_set_id,
                    "evidence_directory": str(job_directory),
                    "timeout_minutes": request.parameters.timeout_minutes,
                    **evidence.model_dump(mode="json"),
                },
            )
        if job is not None:
            self._map_store.update_job(
                job.model_copy(update={"phase": AutoGridJobPhase.COLLECTING_ARTIFACTS})
            )
        if execution.exit_code != 0 or not successful_log:
            raise AnkoraDomainError(
                code="AUTOGRID_EXECUTION_FAILED",
                stage=_STAGE,
                message=(
                    "AutoGrid did not complete successfully. Its raw output is "
                    "preserved for inspection."
                ),
                status_code=422,
                details={
                    "map_set_id": map_set_id,
                    "evidence_directory": str(job_directory),
                    **evidence.model_dump(mode="json"),
                },
            )

        artifacts = self._collect_artifacts(map_set_id, job_directory, ligand_atom_types)
        field_artifact = next(item for item in artifacts if item.kind is AutoGridMapKind.FIELD)
        created_at = datetime.now(UTC)
        record = AutoGridMapSetRecord(
            map_set_id=map_set_id,
            identity_key=identity_key,
            created_at=created_at,
            request=request,
            receptor_id=request.receptor_id,
            receptor_output_artifact_id=receptor_output.artifact_id,
            receptor_sha256=receptor_output.sha256,
            binding_site_id=binding_site.binding_site_id,
            box=binding_site.box,
            geometry=geometry,
            preflight=preflight,
            autogrid=installation.identity(),
            gpf_sha256=sha256(gpf.encode("ascii")).hexdigest(),
            field_artifact_id=field_artifact.artifact_id,
            execution=evidence,
            artifacts=artifacts,
            provenance=ProvenanceEvent(
                event_id=f"autogrid-map-set-{map_set_id}",
                event_type="autogrid_map_set_created",
                timestamp=created_at,
                input_artifacts=[
                    receptor_output.artifact_id,
                    binding_site.binding_site_id,
                    *self._ligand_input_artifacts(request),
                ],
                output_artifacts=[item.artifact_id for item in artifacts],
                tool=installation.identity().tool,
                parameters={
                    **request.parameters.model_dump(mode="json"),
                    "identity_key": identity_key,
                    "npts": list(geometry.npts),
                    "requested_size_angstrom": list(geometry.requested_size_angstrom),
                    "realized_size_angstrom": list(geometry.realized_size_angstrom),
                    "receptor_atom_types": list(receptor_atom_types),
                    "ligand_atom_types": list(ligand_atom_types),
                    "autogrid_sha256": installation.sha256,
                    # The user-visible location is recorded even though AutoGrid
                    # itself only ever saw short relative filenames.
                    "job_directory": str(job_directory),
                },
                command=execution.command,
            ),
        )
        self._map_store.write_record(record)
        return record

    def _collect_artifacts(
        self,
        map_set_id: str,
        job_directory: Path,
        ligand_atom_types: tuple[str, ...],
    ) -> list[AutoGridMapArtifact]:
        affinity_filenames = {
            f"{MAP_PREFIX}.{atom_type}.map": atom_type for atom_type in ligand_atom_types
        }
        expected = {
            f"{MAP_PREFIX}.maps.fld": AutoGridMapKind.FIELD,
            f"{MAP_PREFIX}.maps.xyz": AutoGridMapKind.GRID_POINTS,
            f"{MAP_PREFIX}.e.map": AutoGridMapKind.ELECTROSTATIC,
            f"{MAP_PREFIX}.d.map": AutoGridMapKind.DESOLVATION,
            RECEPTOR_FILENAME: AutoGridMapKind.RECEPTOR,
            GRID_PARAMETER_FILENAME: AutoGridMapKind.GRID_PARAMETER_FILE,
            GRID_LOG_FILENAME: AutoGridMapKind.GRID_LOG,
            **dict.fromkeys(affinity_filenames, AutoGridMapKind.AFFINITY),
        }
        missing = sorted(
            filename for filename in expected if not (job_directory / filename).is_file()
        )
        if missing:
            raise AnkoraDomainError(
                code="AUTOGRID_MAP_SET_INCOMPLETE",
                stage=_STAGE,
                message=(
                    "AutoGrid reported success but did not write every expected "
                    "map. The raw evidence is preserved for inspection."
                ),
                status_code=500,
                details={
                    "map_set_id": map_set_id,
                    "missing": missing,
                    "evidence_directory": str(job_directory),
                },
                recoverable=False,
            )
        artifacts: list[AutoGridMapArtifact] = []
        for filename in sorted(expected):
            path = job_directory / filename
            content = path.read_bytes()
            artifact_id = str(uuid4())
            artifacts.append(
                AutoGridMapArtifact(
                    artifact_id=artifact_id,
                    kind=expected[filename],
                    atom_type=affinity_filenames.get(filename),
                    filename=filename,
                    sha256=sha256(content).hexdigest(),
                    size_bytes=len(content),
                    content_url=(
                        f"/autogrid/map-sets/{map_set_id}/artifacts/{artifact_id}/content"
                    ),
                )
            )
        return artifacts

    def _preflight_ligands(
        self, request: AutoGridMapSetRequest, receptor_atom_types: tuple[str, ...]
    ) -> AutoGridPreflight:
        if request.source is AutoGridLigandSource.LIGAND_PREPARATION:
            rows = [self._single_ligand_row(request)]
        else:
            rows = self._filter_run_rows(request)
        compatible = [row for row in rows if row.compatible]
        if not compatible:
            raise AnkoraDomainError(
                code="AUTOGRID_NO_COMPATIBLE_LIGANDS",
                stage=_STAGE,
                message=(
                    "No selected molecule is compatible with stock AutoDock4, so "
                    "there are no ligand affinity maps to compute."
                ),
                status_code=422,
                details={
                    "incompatible": [
                        {"ligand_id": row.ligand_id, "reason": row.reason}
                        for row in rows
                        if not row.compatible
                    ]
                },
            )
        union = preflight_autodock4_cpu_atom_types(
            {atom_type for row in compatible for atom_type in row.atom_types}
        )
        return AutoGridPreflight(
            receptor_atom_types=list(receptor_atom_types),
            ligand_atom_types=list(union),
            selected_count=len(rows),
            prepared_count=sum(1 for row in rows if row.atom_types),
            compatible_count=len(compatible),
            incompatible_count=len(rows) - len(compatible),
            ligands=rows,
        )

    def _single_ligand_row(self, request: AutoGridMapSetRequest) -> AutoGridLigandPreflightRow:
        if request.ligand_id is None or request.ligand_preparation_id is None:
            raise self._inconsistent_request(
                request.source.value, "ligand_id and ligand_preparation_id"
            )
        ligand = self._ligand_store.load_record(request.ligand_id)
        pdbqt = self._ligand_store.load_pdbqt_record(
            request.ligand_id, request.ligand_preparation_id
        )
        path = self._ligand_store.pdbqt_content_path(
            request.ligand_id, request.ligand_preparation_id
        )
        self._verify_hash(path, pdbqt.artifact.sha256, "ligand")
        return self._row_from_document(
            ligand_id=request.ligand_id,
            source_index=0,
            name=ligand.inspection.name,
            document=path.read_text(encoding="utf-8", errors="replace"),
        )

    def _filter_run_rows(self, request: AutoGridMapSetRequest) -> list[AutoGridLigandPreflightRow]:
        if request.library_id is None or request.filter_run_id is None:
            raise self._inconsistent_request(request.source.value, "library_id and filter_run_id")
        filter_run = self._ligand_store.load_filter_run(request.library_id, request.filter_run_id)
        if not filter_run.selected_ligand_ids:
            raise AnkoraDomainError(
                code="AUTOGRID_SELECTION_EMPTY",
                stage=_STAGE,
                message="The applied ligand selection contains no molecules.",
                status_code=422,
                details={"filter_run_id": request.filter_run_id},
            )
        library = self._ligand_store.load_library_record(request.library_id)
        preparation = self._ligand_store.load_preparation_status(request.library_id)
        indexed = {
            entry.ligand.artifact.ligand_id: (entry.record_index, entry.ligand)
            for entry in library.entries
            if entry.ligand is not None
        }
        rows: list[AutoGridLigandPreflightRow] = []
        for ligand_id in filter_run.selected_ligand_ids:
            source = indexed.get(ligand_id)
            if source is None:
                rows.append(
                    AutoGridLigandPreflightRow(
                        ligand_id=ligand_id,
                        source_index=len(rows),
                        name="Unavailable library molecule",
                        compatible=False,
                        reason="The selected molecule is absent from its library record.",
                    )
                )
                continue
            source_index, ligand = source
            status = preparation.entries.get(ligand_id)
            if (
                status is None
                or status.status is not LigandPreparationStatus.PREPARED
                or status.pdbqt_preparation_id is None
            ):
                rows.append(
                    AutoGridLigandPreflightRow(
                        ligand_id=ligand_id,
                        source_index=source_index,
                        name=ligand.inspection.name,
                        compatible=False,
                        reason="This molecule has no completed Meeko PDBQT preparation.",
                    )
                )
                continue
            try:
                pdbqt = self._ligand_store.load_pdbqt_record(ligand_id, status.pdbqt_preparation_id)
                path = self._ligand_store.pdbqt_content_path(ligand_id, status.pdbqt_preparation_id)
                self._verify_hash(path, pdbqt.artifact.sha256, "ligand")
                document = path.read_text(encoding="utf-8", errors="replace")
            except AnkoraDomainError as error:
                rows.append(
                    AutoGridLigandPreflightRow(
                        ligand_id=ligand_id,
                        source_index=source_index,
                        name=ligand.inspection.name,
                        compatible=False,
                        reason=error.message,
                    )
                )
                continue
            rows.append(
                self._row_from_document(
                    ligand_id=ligand_id,
                    source_index=source_index,
                    name=ligand.inspection.name,
                    document=document,
                )
            )
        return rows

    @staticmethod
    def _row_from_document(
        *, ligand_id: str, source_index: int, name: str, document: str
    ) -> AutoGridLigandPreflightRow:
        try:
            atom_types = collect_autodock_atom_types((document,))
        except ValueError as error:
            return AutoGridLigandPreflightRow(
                ligand_id=ligand_id,
                source_index=source_index,
                name=name,
                compatible=False,
                reason=str(error),
            )
        try:
            preflight_autodock4_cpu_atom_types(atom_types)
        except ValueError as error:
            return AutoGridLigandPreflightRow(
                ligand_id=ligand_id,
                source_index=source_index,
                name=name,
                compatible=False,
                atom_types=list(atom_types),
                reason=str(error),
            )
        return AutoGridLigandPreflightRow(
            ligand_id=ligand_id,
            source_index=source_index,
            name=name,
            compatible=True,
            atom_types=list(atom_types),
        )

    def _validate_receptor_and_site(
        self, receptor_id: str, binding_site_id: str
    ) -> tuple[ReceptorOutputArtifact, Path, BindingSiteRecord]:
        receptor = self._receptor_store.load_record(receptor_id)
        if receptor.status is not ReceptorPreparationStatus.DOCKING_READY:
            raise self._input_error(
                "AUTOGRID_RECEPTOR_NOT_READY",
                "Grid generation requires a receptor in docking-ready status.",
                {"receptor_id": receptor_id, "status": receptor.status.value},
            )
        receptor_output = next(
            (item for item in receptor.outputs if item.stage is ReceptorOutputStage.PDBQT),
            None,
        )
        if receptor_output is None:
            raise self._input_error(
                "AUTOGRID_RECEPTOR_PDBQT_MISSING",
                "The selected receptor has no preserved PDBQT output.",
                {"receptor_id": receptor_id},
            )
        receptor_path = self._receptor_store.content_path(receptor_id, receptor_output.artifact_id)
        self._verify_hash(receptor_path, receptor_output.sha256, "receptor")
        binding_site = self._binding_site_store.load_record(binding_site_id)
        if binding_site.receptor_id != receptor_id or binding_site.stale:
            raise self._input_error(
                "AUTOGRID_BINDING_SITE_INVALID",
                "The binding site is stale or belongs to a different receptor.",
                {
                    "binding_site_id": binding_site_id,
                    "binding_site_receptor_id": binding_site.receptor_id,
                    "requested_receptor_id": receptor_id,
                    "stale": binding_site.stale,
                },
            )
        return receptor_output, receptor_path, binding_site

    @staticmethod
    def _identity_key(
        *,
        receptor_sha256: str,
        binding_site: BindingSiteRecord,
        geometry: AutoGridGeometry,
        receptor_atom_types: tuple[str, ...],
        ligand_atom_types: tuple[str, ...],
        request: AutoGridMapSetRequest,
        installation: AutoGridInstallation,
    ) -> str:
        """Hash everything that changes the maps, and nothing that does not.

        `timeout_minutes` is deliberately excluded: it bounds how long Ankora
        waits, never what AutoGrid computes, so it must not fragment the cache.
        """
        identity = {
            "receptor_sha256": receptor_sha256,
            "box": binding_site.box.model_dump(mode="json"),
            "spacing_angstrom": geometry.spacing_angstrom,
            "npts": list(geometry.npts),
            "realized_size_angstrom": list(geometry.realized_size_angstrom),
            "receptor_atom_types": list(receptor_atom_types),
            "ligand_atom_types": list(ligand_atom_types),
            "smoothing_angstrom": request.parameters.smoothing_angstrom,
            "dielectric": request.parameters.dielectric,
            "autogrid_version": installation.version,
            "autogrid_sha256": installation.sha256,
        }
        canonical = json.dumps(identity, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return sha256(canonical.encode("utf-8")).hexdigest()

    @staticmethod
    def _ligand_input_artifacts(request: AutoGridMapSetRequest) -> list[str]:
        if request.source is AutoGridLigandSource.LIGAND_PREPARATION:
            return [value for value in (request.ligand_preparation_id,) if value]
        return [value for value in (request.filter_run_id,) if value]

    @staticmethod
    def _require_ascii_job_directory(job_directory: Path) -> None:
        """AutoGrid 4.2.6 does not reliably tolerate non-ASCII job paths.

        Failing here with a clear instruction is preferable to letting AutoGrid
        misread its own inputs and produce maps nobody can trust.
        """
        if not str(job_directory).isascii():
            raise AnkoraDomainError(
                code="AUTOGRID_DATA_DIRECTORY_NOT_ASCII",
                stage=_STAGE,
                message=(
                    "AutoGrid 4.2.6 requires an ASCII-only working path. Set "
                    "ANKORA_DATA_DIR to a directory without accented or "
                    "non-Latin characters."
                ),
                status_code=422,
                details={"job_directory": str(job_directory)},
            )

    @staticmethod
    def _verify_hash(path: Path, expected: str, label: str) -> None:
        digest = sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        if digest.hexdigest() != expected:
            raise AnkoraDomainError(
                code="AUTOGRID_INPUT_HASH_MISMATCH",
                stage=_STAGE,
                message=f"A recorded {label} artifact no longer matches its stored hash.",
                status_code=422,
                details={"path": path.name, "expected_sha256": expected},
            )

    @staticmethod
    def _inconsistent_request(source: str, missing_field: str) -> AnkoraDomainError:
        return AnkoraDomainError(
            code="AUTOGRID_REQUEST_INCONSISTENT",
            stage=_STAGE,
            message=f"An '{source}' grid request requires '{missing_field}'.",
            status_code=422,
            details={"source": source, "missing_field": missing_field},
        )

    @staticmethod
    def _input_error(code: str, message: str, details: dict[str, object]) -> AnkoraDomainError:
        return AnkoraDomainError(
            code=code,
            stage=_STAGE,
            message=message,
            status_code=422,
            details=details,
        )
