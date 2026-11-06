"""Run the predeclared isolated Linux Vina service engineering smoke."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend" / "src"))
import validate_linux_vina_smoke as adapter_smoke  # noqa: E402
from ankora_backend.adapters.engines.vina import probe_vina  # noqa: E402
from ankora_backend.persistence.binding_site_store import BindingSiteArtifactStore  # noqa: E402
from ankora_backend.persistence.docking_store import DockingArtifactStore  # noqa: E402
from ankora_backend.persistence.ligand_store import LigandArtifactStore  # noqa: E402
from ankora_backend.persistence.receptor_store import ReceptorArtifactStore  # noqa: E402
from ankora_backend.persistence.work_lease_store import WorkLeaseStore  # noqa: E402
from ankora_backend.schemas.binding_sites import (  # noqa: E402
    BindingSiteRecord,
    BindingSiteRequest,
    BindingSiteSource,
)
from ankora_backend.schemas.docking import DockingJobStatus, VinaDockingRequest  # noqa: E402
from ankora_backend.schemas.ligands import (  # noqa: E402
    LigandChargeModel,
    LigandPdbqtArtifact,
    LigandPdbqtRecord,
)
from ankora_backend.schemas.provenance import ProvenanceEvent, ToolIdentity  # noqa: E402
from ankora_backend.schemas.receptors import (  # noqa: E402
    ComponentAction,
    ProtonationSettings,
    ReceptorOutputArtifact,
    ReceptorOutputStage,
    ReceptorPreparationRecord,
    ReceptorPreparationRequest,
    ReceptorPreparationStatus,
)
from ankora_backend.schemas.work_recovery import WorkKind, WorkLeaseState  # noqa: E402
from ankora_backend.services.resource_arbiter import ResourceArbiter  # noqa: E402
from ankora_backend.services.vina_docking import VinaDockingService  # noqa: E402
from ankora_backend.services.work_leases import WorkLeaseManager  # noqa: E402


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def seed_fixture_stores(root: Path, receptor: bytes, ligand: bytes):  # type: ignore[no-untyped-def]
    """Seed explicitly labeled fixture records, not a preparation/import run."""
    receptors = ReceptorArtifactStore(root)
    ligands = LigandArtifactStore(root)
    sites = BindingSiteArtifactStore(root)
    jobs = DockingArtifactStore(root)
    now = datetime.now(UTC)
    fixture_tool = ToolIdentity(name="development fixture seeded for service smoke", version="1")

    def provenance(name: str) -> ProvenanceEvent:
        return ProvenanceEvent(
            event_id=name, event_type="development_fixture_seed", timestamp=now, tool=fixture_tool
        )

    receptor_id = receptors.new_receptor_id()
    receptors.create_receptor(receptor_id)
    receptors.write_bytes(receptor_id, "receptor.pdbqt", receptor)
    receptor_output = ReceptorOutputArtifact(
        artifact_id=f"{receptor_id}-pdbqt",
        stage=ReceptorOutputStage.PDBQT,
        filename="receptor.pdbqt",
        format="pdbqt",
        sha256=hashlib.sha256(receptor).hexdigest(),
        size_bytes=len(receptor),
        created_at=now,
        content_url="/development-fixture/receptor",
    )
    receptors.save_record(
        ReceptorPreparationRecord(
            receptor_id=receptor_id,
            source_artifact_id="development-fixture-no-import-record",
            created_at=now,
            status=ReceptorPreparationStatus.DOCKING_READY,
            decisions=ReceptorPreparationRequest(
                selected_chains=["A"],
                water_action=ComponentAction.REMOVE,
                component_decisions=[],
                issue_decisions=[],
                protonation=ProtonationSettings(enabled=True),
                generate_pdbqt=True,
            ),
            outputs=[receptor_output],
            warnings=[],
            provenance=[provenance("seed-receptor")],
            display_output_artifact_id=receptor_output.artifact_id,
        )
    )
    ligand_id = ligands.new_ligand_id()
    (root / "projects" / "default" / "original" / "ligands" / ligand_id).mkdir(parents=True)
    preparation_id = ligands.new_preparation_id()
    artifact = LigandPdbqtArtifact(
        preparation_id=preparation_id,
        ligand_id=ligand_id,
        conformer_id="development-fixture-conformer",
        filename="ligand.pdbqt",
        format="pdbqt",
        sha256=hashlib.sha256(ligand).hexdigest(),
        size_bytes=len(ligand),
        created_at=now,
    )
    ligands.create_pdbqt(
        ligand_id,
        preparation_id,
        ligand,
        LigandPdbqtRecord(
            artifact=artifact,
            charge_model=LigandChargeModel.GASTEIGER,
            tool=fixture_tool,
            command=["development-fixture-seed"],
            stdout="",
            stderr="",
            provenance=provenance("seed-ligand"),
            content_url="/development-fixture/ligand",
        ),
    )
    site_id = sites.new_binding_site_id()
    sites.save_record(
        BindingSiteRecord(
            binding_site_id=site_id,
            receptor_id=receptor_id,
            source_artifact_id=receptor_output.artifact_id,
            created_at=now,
            decisions=BindingSiteRequest(
                source=BindingSiteSource.MANUAL, manual_box=adapter_smoke.BOX
            ),
            box=adapter_smoke.BOX,
            warnings=[],
            provenance=[provenance("seed-binding-site")],
        )
    )
    request = VinaDockingRequest(
        receptor_id=receptor_id,
        binding_site_id=site_id,
        ligand_id=ligand_id,
        ligand_preparation_id=preparation_id,
        parameters=adapter_smoke.PARAMETERS,
        acknowledge_inputs_and_scoring=True,
    )
    return receptors, ligands, sites, jobs, request


def run(receptor: Path, ligand: Path, predictions: Path, output: Path) -> dict[str, Any]:
    """Run once; refuse an existing directory and preserve evidence on failure."""
    output.mkdir(parents=True, exist_ok=False)
    data = output / "data"
    evidence: dict[str, Any] = {
        "status": "failed",
        "purpose": "isolated seeded-fixture service engineering smoke",
        "scope": "Not redocking, biological validation, preparation-service or GUI acceptance.",
    }
    service = None
    leases = None
    try:
        if sys.platform != "linux":
            raise ValueError("This execution requires Linux.")
        inputs = output / "inputs"
        inputs.mkdir()
        copies = []
        for source, name, expected in (
            (receptor, "receptor.pdbqt", adapter_smoke.PINNED.receptor_sha256),
            (ligand, "ligand.pdbqt", adapter_smoke.PINNED.ligand_sha256),
            (predictions, "predictions.csv", adapter_smoke.PINNED.pocket_predictions_sha256),
        ):
            target = inputs / name
            adapter_smoke._verified_copy(source, target, name, expected)
            copies.append(target)
        adapter_smoke._check_pocket_center(copies[2])
        installation = probe_vina()
        executable = Path(installation.executable)
        if (
            installation.version != adapter_smoke.VINA_VERSION
            or digest(executable) != adapter_smoke.PINNED.vina_sha256
        ):
            raise ValueError("Vina executable differs from the declared identity.")
        evidence["engine"] = {"version": installation.version, "sha256": digest(executable)}
        os.environ["ANKORA_DATA_DIR"] = str(data)
        receptors, ligands, sites, jobs, request = seed_fixture_stores(
            data, copies[0].read_bytes(), copies[1].read_bytes()
        )
        lease_store = WorkLeaseStore(data)
        leases = WorkLeaseManager(lease_store)
        arbiter = ResourceArbiter.from_environment()
        service = VinaDockingService(
            docking_store=jobs,
            receptor_store=receptors,
            binding_site_store=sites,
            ligand_store=ligands,
            lease_manager=leases,
            resource_arbiter=arbiter,
        )
        initial = service.start(request)
        deadline = time.monotonic() + 80
        terminal = {DockingJobStatus.COMPLETED, DockingJobStatus.FAILED, DockingJobStatus.CANCELED}
        while True:
            record = service.get(initial.job_id)
            if record.status in terminal:
                break
            if time.monotonic() >= deadline:
                service.cancel(initial.job_id)
                raise TimeoutError("Service job did not reach a terminal state within 80 seconds.")
            time.sleep(0.1)
        service.shutdown()
        service = None
        leases.shutdown()
        leases = None
        evidence["job"] = record.model_dump(mode="json")
        evidence["job_id"] = initial.job_id
        evidence["input_hashes_after"] = [digest(path) for path in copies]
        raw = jobs.output_path(initial.job_id, "vina_poses.pdbqt")
        evidence["raw_output_sha256"] = digest(raw) if raw.is_file() else None
        lease = lease_store.load(WorkKind.VINA_JOB, initial.job_id)
        evidence["lease_state"] = lease.state.value if lease is not None else None
        evidence["active_resource_allocations"] = len(arbiter.snapshot().active_allocations)
        if record.status is not DockingJobStatus.COMPLETED or record.execution is None:
            raise RuntimeError("Service did not complete; see the retained job record.")
        if (
            record.execution.exit_code != 0
            or record.execution.timed_out
            or record.execution.canceled
        ):
            raise RuntimeError("Service execution was unsuccessful.")
        if (
            not raw.is_file()
            or [pose.mode for pose in record.poses] != list(range(1, len(record.poses) + 1))
            or not 1 <= len(record.poses) <= 3
        ):
            raise RuntimeError("Raw output or sequential pose count is invalid.")
        for pose in record.poses:
            path = jobs.pose_content_path(initial.job_id, pose.artifact.artifact_id)
            if (
                digest(path) != pose.artifact.sha256
                or path.stat().st_size != pose.artifact.size_bytes
            ):
                raise RuntimeError("A pose artifact differs from its recorded identity.")
        if evidence["input_hashes_after"] != [
            adapter_smoke.PINNED.receptor_sha256,
            adapter_smoke.PINNED.ligand_sha256,
            adapter_smoke.PINNED.pocket_predictions_sha256,
        ]:
            raise RuntimeError("A copied input changed.")
        if (
            evidence["lease_state"] != WorkLeaseState.RELEASED.value
            or evidence["active_resource_allocations"]
        ):
            raise RuntimeError("A work or resource lease was not released.")
        evidence["status"] = "completed"
    except Exception as error:
        evidence["failure"] = {"type": type(error).__name__, "message": str(error)}
    finally:
        if service is not None:
            service.shutdown()
        if leases is not None:
            leases.shutdown()
    with (output / "evidence.json").open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(evidence, handle, indent=2, sort_keys=True)
        handle.write("\n")
    return evidence


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--receptor", type=Path, required=True)
    parser.add_argument("--ligand", type=Path, required=True)
    parser.add_argument("--pocket-predictions", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = run(args.receptor, args.ligand, args.pocket_predictions, args.output.resolve())
    except FileExistsError:
        print("Refusing to overwrite an existing evidence directory.", file=sys.stderr)
        return 2
    print(f"Service smoke: {result['status']}")
    print(f"Evidence SHA-256: {digest(args.output / 'evidence.json')}")
    return 0 if result["status"] == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
