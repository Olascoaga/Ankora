"""One read-only catalog over every durable docking result (M6).

The spec is explicit that this is a read model: it "must not copy pose files,
rewrite a DLG, mutate a campaign, or create a second scientific truth." So every
entry is projected from the authoritative record on demand and references it by
id; nothing is cached into a parallel database that could disagree.

The frontend asks this service rather than knowing six store layouts, which is
what keeps the interface from growing its own opinion about where results live.
"""

from typing import Any

from ankora_backend.domain.errors import AnkoraDomainError
from ankora_backend.persistence.autodock4_store import AutoDock4JobStore
from ankora_backend.persistence.autodock_gpu_store import AutoDockGpuJobStore
from ankora_backend.persistence.binding_site_store import BindingSiteArtifactStore
from ankora_backend.persistence.docking_store import DockingArtifactStore
from ankora_backend.persistence.ligand_store import LigandArtifactStore
from ankora_backend.schemas.results_catalog import (
    CatalogEntry,
    CatalogPage,
    CompoundPage,
    CompoundRow,
    ResultMode,
    ScoringFamily,
)

_STAGE = "results_catalog"

VINA_BATCH = "vina_batch"
AUTODOCK4_BATCH = "autodock4_batch"
AUTODOCK_GPU_BATCH = "autodock_gpu_batch"
VINA_JOB = "vina_job"
AUTODOCK4_JOB = "autodock4_job"
AUTODOCK_GPU_JOB = "autodock_gpu_job"

VALUE_LABEL = {
    ScoringFamily.VINA: "Vina score (kcal/mol)",
    ScoringFamily.AUTODOCK4: "Binding energy (kcal/mol)",
}


class ResultCatalogService:
    def __init__(
        self,
        *,
        docking_store: DockingArtifactStore,
        autodock4_store: AutoDock4JobStore,
        autodock_gpu_store: AutoDockGpuJobStore,
        binding_site_store: BindingSiteArtifactStore,
        ligand_store: LigandArtifactStore,
    ) -> None:
        self._docking_store = docking_store
        self._autodock4_store = autodock4_store
        self._autodock_gpu_store = autodock_gpu_store
        self._binding_site_store = binding_site_store
        self._ligand_store = ligand_store

    @classmethod
    def from_environment(cls) -> "ResultCatalogService":
        return cls(
            docking_store=DockingArtifactStore.from_environment(),
            autodock4_store=AutoDock4JobStore.from_environment(),
            autodock_gpu_store=AutoDockGpuJobStore.from_environment(),
            binding_site_store=BindingSiteArtifactStore.from_environment(),
            ligand_store=LigandArtifactStore.from_environment(),
        )

    # --- listing ----------------------------------------------------------

    def list_campaigns(
        self,
        *,
        offset: int = 0,
        limit: int = 25,
        mode: ResultMode | None = None,
        scoring_family: ScoringFamily | None = None,
        receptor_id: str | None = None,
        binding_site_id: str | None = None,
        status: str | None = None,
    ) -> CatalogPage:
        """Every result this project holds, newest first.

        Newest first is the only defensible default. Ordering a mixed list by
        "best" would put a Vina score next to an AutoDock4 binding energy and
        call one better, which is exactly the comparison the policy forbids.
        """
        entries = self._all()
        if mode is not None:
            entries = [e for e in entries if e.mode is mode]
        if scoring_family is not None:
            entries = [e for e in entries if e.scoring_family is scoring_family]
        if receptor_id is not None:
            entries = [e for e in entries if e.receptor_id == receptor_id]
        if binding_site_id is not None:
            entries = [e for e in entries if e.binding_site_id == binding_site_id]
        if status is not None:
            entries = [e for e in entries if e.status == status]

        # The record id breaks ties, so two results created in one clock tick
        # keep a stable order between requests.
        entries.sort(key=lambda item: (item.created_at, item.record_id), reverse=True)
        window = entries[offset : offset + limit]
        return CatalogPage(
            entries=[self._with_box(entry) for entry in window],
            total=len(entries),
            offset=offset,
            limit=limit,
        )

    def get_campaign(self, catalog_id: str) -> CatalogEntry:
        engine_key, record_id = self._split(catalog_id)
        return self._with_box(self._project(engine_key, record_id))

    def _all(self) -> list[CatalogEntry]:
        """Projected from whatever is on disk; a store that fails is skipped.

        A single unreadable store must not make the whole catalog unavailable,
        because the catalog is how a scientist finds the rest of their work.
        """
        entries: list[CatalogEntry] = []
        for load, project in (
            (self._docking_store.list_batch_records, self._from_vina_batch),
            (self._autodock4_store.list_batches, self._from_autodock4_batch),
            (self._autodock_gpu_store.list_batches, self._from_gpu_batch),
            (self._docking_store.list_jobs, self._from_vina_job),
            (self._autodock4_store.list_jobs, self._from_autodock4_job),
            (self._autodock_gpu_store.list_jobs, self._from_gpu_job),
        ):
            try:
                records: list[Any] = list(load())
            except (AnkoraDomainError, OSError):
                continue
            entries.extend(project(record) for record in records)
        return entries

    # --- compounds --------------------------------------------------------

    def list_compounds(
        self,
        catalog_id: str,
        *,
        offset: int = 0,
        limit: int = 100,
        status: str | None = None,
        search: str | None = None,
    ) -> CompoundPage:
        """One page of molecules, in this engine's own ranking order.

        Molecules the engine could not dock sort last rather than disappearing:
        a selection is described by what happened to all of it.
        """
        engine_key, record_id = self._split(catalog_id)
        entry = self._project(engine_key, record_id)
        rows = self._rows(engine_key, record_id)

        if status is not None:
            rows = [row for row in rows if row.status == status]
        if search:
            needle = search.casefold()
            rows = [
                row
                for row in rows
                if needle in row.name.casefold()
                or needle in (row.canonical_smiles or "").casefold()
            ]
        rows.sort(
            key=lambda row: (
                row.best_result_kcal_mol is None,
                row.best_result_kcal_mol if row.best_result_kcal_mol is not None else 0.0,
                row.source_index,
            )
        )
        return CompoundPage(
            catalog_id=catalog_id,
            engine_label=entry.engine_label,
            value_label=VALUE_LABEL[entry.scoring_family],
            rows=rows[offset : offset + limit],
            total=len(rows),
            offset=offset,
            limit=limit,
        )

    # --- projection -------------------------------------------------------

    def _project(self, engine_key: str, record_id: str) -> CatalogEntry:
        if engine_key == VINA_BATCH:
            return self._from_vina_batch(
                self._docking_store.load_batch_record(record_id)
            )
        if engine_key == AUTODOCK4_BATCH:
            return self._from_autodock4_batch(
                self._autodock4_store.load_batch(record_id)
            )
        if engine_key == AUTODOCK_GPU_BATCH:
            return self._from_gpu_batch(self._autodock_gpu_store.load_batch(record_id))
        if engine_key == VINA_JOB:
            return self._from_vina_job(self._docking_store.load_record(record_id))
        if engine_key == AUTODOCK4_JOB:
            return self._from_autodock4_job(self._autodock4_store.load_job(record_id))
        if engine_key == AUTODOCK_GPU_JOB:
            return self._from_gpu_job(self._autodock_gpu_store.load_job(record_id))
        raise self._unknown(engine_key)

    def _rows(self, engine_key: str, record_id: str) -> list[CompoundRow]:
        if engine_key == VINA_BATCH:
            record = self._docking_store.load_batch_record(record_id)
            return [self._vina_row(entry) for entry in record.entries]
        if engine_key == AUTODOCK4_BATCH:
            return [
                self._autodock_row(entry)
                for entry in self._autodock4_store.load_batch(record_id).entries
            ]
        if engine_key == AUTODOCK_GPU_BATCH:
            return [
                self._autodock_row(entry)
                for entry in self._autodock_gpu_store.load_batch(record_id).entries
            ]
        # A single-ligand job is a one-row table. Presenting it through the same
        # shape means the interface has one results table, not two.
        if engine_key == VINA_JOB:
            vina = self._docking_store.load_record(record_id)
            return [
                self._single_row(
                    vina.request.ligand_id,
                    vina.status.value,
                    vina.failure.code if vina.failure else None,
                    best=_pose_best(vina),
                    pose_count=len(vina.poses),
                )
            ]
        if engine_key in (AUTODOCK4_JOB, AUTODOCK_GPU_JOB):
            store: Any = (
                self._autodock4_store
                if engine_key == AUTODOCK4_JOB
                else self._autodock_gpu_store
            )
            job = store.load_job(record_id)
            top = next((c for c in job.clusters if c.cluster_rank == 1), None)
            return [
                self._single_row(
                    job.request.ligand_id,
                    job.status.value,
                    job.failure.code if job.failure else None,
                    best=_cluster_best(job),
                    cluster_count=len(job.clusters),
                    top_cluster_runs=top.run_count if top else None,
                )
            ]
        raise self._unknown(engine_key)

    @staticmethod
    def _vina_row(entry: Any) -> CompoundRow:
        return CompoundRow(
            ligand_id=entry.ligand_id,
            source_index=entry.source_index,
            name=entry.name,
            canonical_smiles=entry.canonical_smiles,
            molecular_weight_g_mol=entry.molecular_weight_g_mol,
            status=entry.status.value,
            failure_code=entry.failure.code if entry.failure else None,
            best_result_kcal_mol=_pose_best(entry),
            # Vina is pose-native; it has no clusters to report and the spec
            # forbids inventing them.
            pose_count=len(entry.poses),
        )

    @staticmethod
    def _autodock_row(entry: Any) -> CompoundRow:
        top = next((c for c in entry.clusters if c.cluster_rank == 1), None)
        return CompoundRow(
            ligand_id=entry.ligand_id,
            source_index=entry.source_index,
            name=entry.name,
            canonical_smiles=entry.canonical_smiles,
            molecular_weight_g_mol=entry.molecular_weight_g_mol,
            status=entry.status.value,
            failure_code=entry.failure.code if entry.failure else None,
            best_result_kcal_mol=_cluster_best(entry),
            # Cluster-native, kept cluster-native.
            cluster_count=len(entry.clusters),
            top_cluster_runs=top.run_count if top else None,
        )

    def _single_row(
        self,
        ligand_id: str,
        status: str,
        failure_code: str | None,
        *,
        best: float | None,
        pose_count: int | None = None,
        cluster_count: int | None = None,
        top_cluster_runs: int | None = None,
    ) -> CompoundRow:
        name, smiles, weight = self._inspect(ligand_id)
        return CompoundRow(
            ligand_id=ligand_id,
            source_index=0,
            name=name,
            canonical_smiles=smiles,
            molecular_weight_g_mol=weight,
            status=status,
            failure_code=failure_code,
            best_result_kcal_mol=best,
            pose_count=pose_count,
            cluster_count=cluster_count,
            top_cluster_runs=top_cluster_runs,
        )

    def _inspect(self, ligand_id: str) -> tuple[str, str | None, float | None]:
        """The molecule's own identity, or its id if the ligand is gone.

        A result outlives whatever produced it, so a deleted ligand must not
        make a finished job unreadable.
        """
        try:
            record = self._ligand_store.load_record(ligand_id)
        except (AnkoraDomainError, OSError, ValueError):
            return ligand_id, None, None
        return (
            record.inspection.name,
            record.inspection.canonical_smiles,
            record.inspection.molecular_weight_g_mol,
        )

    # --- one projection per kind of record --------------------------------

    def _from_vina_batch(self, record: Any) -> CatalogEntry:
        best, molecule = _best(record.entries, _pose_best)
        return CatalogEntry(
            catalog_id=f"{VINA_BATCH}:{record.batch_id}",
            engine_key=VINA_BATCH,
            record_id=record.batch_id,
            mode=ResultMode.SCREENING,
            scoring_family=ScoringFamily.VINA,
            engine_label=f"{record.tool.name} {record.tool.version}",
            engine_version=record.tool.version,
            bitwise_reproducible=True,
            status=record.status.value,
            created_at=record.created_at,
            completed_at=record.completed_at,
            receptor_id=record.request.receptor_id,
            binding_site_id=record.request.binding_site_id,
            library_id=record.request.library_id,
            filter_run_id=record.request.filter_run_id,
            selection_manifest_sha256=record.selection_manifest_sha256,
            selected_count=record.selected_count,
            succeeded_count=record.succeeded_count,
            failed_count=record.failed_count,
            canceled_count=record.canceled_count,
            best_result_kcal_mol=best,
            best_molecule=molecule,
        )

    def _from_autodock4_batch(self, record: Any) -> CatalogEntry:
        best, molecule = _best(record.entries, _cluster_best)
        return CatalogEntry(
            catalog_id=f"{AUTODOCK4_BATCH}:{record.batch_id}",
            engine_key=AUTODOCK4_BATCH,
            record_id=record.batch_id,
            mode=ResultMode.SCREENING,
            scoring_family=ScoringFamily.AUTODOCK4,
            backend="autodock4_cpu",
            engine_label=_cpu_label(record.autodock4),
            engine_version=record.autodock4.tool.version,
            executable_sha256=record.autodock4.sha256,
            bitwise_reproducible=True,
            status=record.status.value,
            created_at=record.created_at,
            completed_at=record.completed_at,
            receptor_id=record.receptor_id,
            binding_site_id=record.binding_site_id,
            map_set_id=record.map_set_id,
            map_set_identity_key=record.map_set_identity_key,
            library_id=record.request.library_id,
            filter_run_id=record.request.filter_run_id,
            selection_manifest_sha256=record.selection_manifest_sha256,
            selected_count=record.selected_count,
            succeeded_count=record.succeeded_count,
            failed_count=record.failed_count,
            canceled_count=record.canceled_count,
            best_result_kcal_mol=best,
            best_molecule=molecule,
        )

    def _from_gpu_batch(self, record: Any) -> CatalogEntry:
        best, molecule = _best(record.entries, _cluster_best)
        return CatalogEntry(
            catalog_id=f"{AUTODOCK_GPU_BATCH}:{record.batch_id}",
            engine_key=AUTODOCK_GPU_BATCH,
            record_id=record.batch_id,
            mode=ResultMode.SCREENING,
            # The same scoring family as the CPU engine, on a different backend.
            scoring_family=ScoringFamily.AUTODOCK4,
            backend=record.backend.value,
            engine_label=_gpu_label(record.autodock_gpu),
            engine_version=record.autodock_gpu.tool.version,
            executable_sha256=record.autodock_gpu.sha256,
            device_name=record.autodock_gpu.device_name,
            bitwise_reproducible=record.bitwise_reproducible,
            status=record.status.value,
            created_at=record.created_at,
            completed_at=record.completed_at,
            receptor_id=record.receptor_id,
            binding_site_id=record.binding_site_id,
            map_set_id=record.map_set_id,
            map_set_identity_key=record.map_set_identity_key,
            library_id=record.request.library_id,
            filter_run_id=record.request.filter_run_id,
            selection_manifest_sha256=record.selection_manifest_sha256,
            selected_count=record.selected_count,
            succeeded_count=record.succeeded_count,
            failed_count=record.failed_count,
            canceled_count=record.canceled_count,
            best_result_kcal_mol=best,
            best_molecule=molecule,
        )

    def _from_vina_job(self, record: Any) -> CatalogEntry:
        return CatalogEntry(
            catalog_id=f"{VINA_JOB}:{record.job_id}",
            engine_key=VINA_JOB,
            record_id=record.job_id,
            mode=ResultMode.SINGLE_LIGAND,
            scoring_family=ScoringFamily.VINA,
            engine_label=f"{record.tool.name} {record.tool.version}",
            engine_version=record.tool.version,
            bitwise_reproducible=True,
            status=record.status.value,
            created_at=record.created_at,
            completed_at=record.completed_at,
            receptor_id=record.request.receptor_id,
            binding_site_id=record.request.binding_site_id,
            ligand_id=record.request.ligand_id,
            best_molecule=self._inspect(record.request.ligand_id)[0],
            **_single_counts(record, _pose_best(record)),
        )

    def _from_autodock4_job(self, record: Any) -> CatalogEntry:
        return CatalogEntry(
            catalog_id=f"{AUTODOCK4_JOB}:{record.job_id}",
            engine_key=AUTODOCK4_JOB,
            record_id=record.job_id,
            mode=ResultMode.SINGLE_LIGAND,
            scoring_family=ScoringFamily.AUTODOCK4,
            backend="autodock4_cpu",
            engine_label=_cpu_label(record.autodock4),
            engine_version=record.autodock4.tool.version,
            executable_sha256=record.autodock4.sha256,
            bitwise_reproducible=True,
            status=record.status.value,
            created_at=record.created_at,
            completed_at=record.completed_at,
            receptor_id=record.receptor_id,
            binding_site_id=record.binding_site_id,
            map_set_id=record.map_set_id,
            map_set_identity_key=record.map_set_identity_key,
            ligand_id=record.request.ligand_id,
            best_molecule=self._inspect(record.request.ligand_id)[0],
            **_single_counts(record, _cluster_best(record)),
        )

    def _from_gpu_job(self, record: Any) -> CatalogEntry:
        return CatalogEntry(
            catalog_id=f"{AUTODOCK_GPU_JOB}:{record.job_id}",
            engine_key=AUTODOCK_GPU_JOB,
            record_id=record.job_id,
            mode=ResultMode.SINGLE_LIGAND,
            scoring_family=ScoringFamily.AUTODOCK4,
            backend=record.backend.value,
            engine_label=_gpu_label(record.autodock_gpu),
            engine_version=record.autodock_gpu.tool.version,
            executable_sha256=record.autodock_gpu.sha256,
            device_name=record.autodock_gpu.device_name,
            bitwise_reproducible=record.bitwise_reproducible,
            status=record.status.value,
            created_at=record.created_at,
            completed_at=record.completed_at,
            receptor_id=record.receptor_id,
            binding_site_id=record.binding_site_id,
            map_set_id=record.map_set_id,
            map_set_identity_key=record.map_set_identity_key,
            ligand_id=record.request.ligand_id,
            best_molecule=self._inspect(record.request.ligand_id)[0],
            **_single_counts(record, _cluster_best(record)),
        )

    def _with_box(self, entry: CatalogEntry) -> CatalogEntry:
        """The exact search space, which is half of what identifies a result."""
        try:
            site = self._binding_site_store.load_record(entry.binding_site_id)
        except (AnkoraDomainError, OSError, ValueError):
            return entry
        return entry.model_copy(update={"box": site.box.model_dump(mode="json")})

    @staticmethod
    def _split(catalog_id: str) -> tuple[str, str]:
        engine_key, _, record_id = catalog_id.partition(":")
        if not engine_key or not record_id:
            raise AnkoraDomainError(
                code="RESULT_CATALOG_ID_INVALID",
                stage=_STAGE,
                message="A catalog identifier names its engine and its record.",
                status_code=422,
                details={"catalog_id": catalog_id},
            )
        return engine_key, record_id

    @staticmethod
    def _unknown(engine_key: str) -> AnkoraDomainError:
        return AnkoraDomainError(
            code="RESULT_CATALOG_ENGINE_UNKNOWN",
            stage=_STAGE,
            message="Ankora has no result catalog for this kind of record.",
            status_code=422,
            details={"engine_key": engine_key},
        )


def _cpu_label(identity: Any) -> str:
    """`AutoDock 4.2.6 · CPU` - the backend is part of the engine's name.

    Two backends of one scoring family produce numbers on the same scale from
    different executions, and only one of them is reproducible.
    """
    return f"{identity.tool.name} {identity.tool.version} · CPU"


def _gpu_label(identity: Any) -> str:
    return f"AutoDock4 · {identity.tool.name} {identity.tool.version}"


def _pose_best(entry: Any) -> float | None:
    if not entry.poses:
        return None
    return float(entry.poses[0].affinity_kcal_mol)


def _cluster_best(entry: Any) -> float | None:
    if not entry.clusters:
        return None
    return float(
        min(cluster.lowest_binding_energy_kcal_mol for cluster in entry.clusters)
    )


def _single_counts(record: Any, best: float | None) -> dict[str, Any]:
    """A single job is a selection of one, counted the way a campaign is."""
    status = record.status.value
    return {
        "selected_count": 1,
        "succeeded_count": 1 if best is not None else 0,
        "failed_count": 1 if status == "failed" else 0,
        "canceled_count": 1 if status == "canceled" else 0,
        "best_result_kcal_mol": best,
    }


def _best(entries: Any, value: Any) -> tuple[float | None, str | None]:
    best: float | None = None
    molecule: str | None = None
    for entry in entries:
        current = value(entry)
        if current is None:
            continue
        if best is None or current < best:
            best, molecule = current, entry.name
    return best, molecule
