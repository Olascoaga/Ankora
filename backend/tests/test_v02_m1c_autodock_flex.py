"""Tests for AutoDock4 CPU + AutoDock-GPU FlexRes, E7 enforcement, and E8 PoseComplex.

All non-live fixtures in this module are synthetic and explicitly labelled synthetic.
Live binary smoke tests execute the real installed Meeko, AutoGrid4, AutoDock4, and
AutoDock-GPU binaries when configured on the host.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime
from hashlib import sha256
from importlib import import_module
from pathlib import Path

import pytest
from test_autogrid_maps import _install_synthetic_autogrid

from ankora_backend.adapters.chemistry.flex_pose_complex import materialize_coupled_receptor_pdb
from ankora_backend.adapters.engines.autodock4_job import (
    parse_autodock4_log,
    render_autodock4_dpf,
)
from ankora_backend.adapters.engines.autodock4_runner import (
    DOCKING_LOG_FILENAME,
    DOCKING_PARAMETER_FILENAME,
    FLEXRES_FILENAME,
    AutoDock4Installation,
    probe_autodock4,
    validate_ligand_against_autodock4_limits,
)
from ankora_backend.adapters.engines.autodock_gpu import (
    DOCKING_LOG_FILENAME as GPU_LOG_FILENAME,
)
from ankora_backend.adapters.engines.autodock_gpu import (
    FLEXRES_FILENAME as GPU_FLEXRES_FILENAME,
)
from ankora_backend.adapters.engines.autodock_gpu import (
    AutoDockGpuInstallation,
    build_arguments,
    probe_autodock_gpu,
)
from ankora_backend.adapters.engines.autogrid import probe_autogrid4
from ankora_backend.domain.errors import AnkoraDomainError
from ankora_backend.execution.cancellable_subprocess import CancellableToolExecution
from ankora_backend.execution.subprocess_runner import ToolExecution
from ankora_backend.persistence.artifact_store import StructureArtifactStore
from ankora_backend.persistence.autodock4_store import AutoDock4JobStore
from ankora_backend.persistence.autodock_gpu_store import AutoDockGpuJobStore
from ankora_backend.persistence.autogrid_store import AutoGridMapStore
from ankora_backend.persistence.binding_site_store import BindingSiteArtifactStore
from ankora_backend.persistence.docking_store import DockingArtifactStore
from ankora_backend.persistence.ligand_store import LigandArtifactStore
from ankora_backend.persistence.pose_interaction_store import PoseInteractionStore
from ankora_backend.persistence.receptor_store import ReceptorArtifactStore
from ankora_backend.schemas.autodock4 import (
    AutoDock4BatchParameters,
    AutoDock4BatchRecord,
    AutoDock4BatchRequest,
    AutoDock4DockingJobRecord,
    AutoDock4DockingParameters,
    AutoDock4DockingRequest,
    AutoDock4JobStatus,
)
from ankora_backend.schemas.autodock_gpu import (
    AutoDockGpuBatchParameters,
    AutoDockGpuBatchRecord,
    AutoDockGpuBatchRequest,
    AutoDockGpuDockingJobRecord,
    AutoDockGpuDockingParameters,
    AutoDockGpuDockingRequest,
    AutoDockJobStatus,
)
from ankora_backend.schemas.autogrid import (
    AutoGridLigandSource,
    AutoGridMapKind,
    AutoGridMapSetRecord,
    AutoGridMapSetRequest,
)
from ankora_backend.schemas.binding_sites import (
    BindingBox,
    BindingSiteRecord,
    BindingSiteRequest,
    BindingSiteSource,
)
from ankora_backend.schemas.ligands import (
    ApplyLigandLibraryFilterRequest,
    GenerateLigandConformerRequest,
    PrepareLigandPdbqtRequest,
)
from ankora_backend.schemas.pose_interactions import (
    InteractionAnalysisRequest,
    LigandDiagram,
    LigandDiagramAtom,
)
from ankora_backend.schemas.provenance import ProvenanceEvent, ToolIdentity
from ankora_backend.schemas.receptors import (
    ComponentAction,
    ProtonationSettings,
    ReceptorFlexMode,
    ReceptorFlexRequest,
    ReceptorFlexSpec,
    ReceptorOutputArtifact,
    ReceptorOutputStage,
    ReceptorPreparationRecord,
    ReceptorPreparationRequest,
    ReceptorPreparationStatus,
    ResidueLocator,
)
from ankora_backend.schemas.structures import StructureSource
from ankora_backend.schemas.v02_contracts import PoseComplexIdentity
from ankora_backend.schemas.warnings import StructuredWarning, WarningCode
from ankora_backend.services import autodock4_docking as ad4_module
from ankora_backend.services import autodock_gpu_docking as gpu_module
from ankora_backend.services import receptor_preparation
from ankora_backend.services.autodock4_docking import AutoDock4DockingService
from ankora_backend.services.autodock_gpu_docking import (
    AutoDockGpuDockingService,
    _as_filelist_arguments,
)
from ankora_backend.services.autogrid_maps import AutoGridMapService
from ankora_backend.services.ligand_filtering import apply_library_filters
from ankora_backend.services.ligand_import import (
    import_local_ligand,
    import_local_ligand_library,
)
from ankora_backend.services.ligand_minimization import generate_ligand_conformer
from ankora_backend.services.ligand_preparation import prepare_ligand_pdbqt
from ankora_backend.services.pose_interactions import PoseInteractionService
from ankora_backend.services.structure_inspection import import_structure_bytes

_BOX = BindingBox(
    center_x=0.0,
    center_y=0.0,
    center_z=0.0,
    size_x=14.0,
    size_y=14.0,
    size_z=14.0,
)

# Synthetic full-atom crystal PDB with MET A:5 backbone + side chain + non-polar Hs.
_SYNTHETIC_CRYSTAL_PDB = (
    "ATOM      1  N   MET A   5      -0.500  -1.350   0.250  1.00  0.00           N  \n"
    "ATOM      2  CA  MET A   5       0.000   0.000   0.000  1.00  0.00           C  \n"
    "ATOM      3  C   MET A   5      -0.550   0.500  -1.320  1.00  0.00           C  \n"
    "ATOM      4  O   MET A   5      -0.100   1.550  -1.780  1.00  0.00           O  \n"
    "ATOM      5  HA  MET A   5      -0.350   0.650   0.780  1.00  0.00           H  \n"
    "ATOM      6  CB  MET A   5       1.530   0.000   0.000  1.00  0.00           C  \n"
    "ATOM      7  CG  MET A   5       2.040   1.440   0.000  1.00  0.00           C  \n"
    "ATOM      8  SD  MET A   5       3.850   1.440   0.000  1.00  0.00           S  \n"
    "ATOM      9  CE  MET A   5       4.200   3.190   0.250  1.00  0.00           C  \n"
    "ATOM     10  HB2 MET A   5       1.894  -0.514   0.890  1.00  0.00           H  \n"
    "ATOM     11  HB3 MET A   5       1.894  -0.514  -0.890  1.00  0.00           H  \n"
    "ATOM     12  HG2 MET A   5       1.676   1.954   0.890  1.00  0.00           H  \n"
    "ATOM     13  HG3 MET A   5       1.676   1.954  -0.890  1.00  0.00           H  \n"
    "ATOM     14  HE1 MET A   5       5.280   3.310   0.250  1.00  0.00           H  \n"
    "ATOM     15  HE2 MET A   5       3.780   3.620   1.158  1.00  0.00           H  \n"
    "ATOM     16  HE3 MET A   5       3.780   3.620  -0.658  1.00  0.00           H  \n"
    "END\n"
)

_SYNTHETIC_RIGID_PDBQT = (
    "ATOM      1  N   MET A   5      -0.500  -1.350   0.250  1.00  0.00     0.000 N \n"
    "ATOM      2  C   MET A   5      -0.550   0.500  -1.320  1.00  0.00     0.000 C \n"
    "ATOM      3  O   MET A   5      -0.100   1.550  -1.780  1.00  0.00     0.000 OA\n"
)

_SYNTHETIC_FULL_RIGID_PDBQT = (
    _SYNTHETIC_RIGID_PDBQT
    + "ATOM      4  CA  MET A   5       0.000   0.000   0.000  1.00  0.00     0.000 C \n"
    + "ATOM      5  CB  MET A   5       1.530   0.000   0.000  1.00  0.00     0.000 C \n"
    + "ATOM      6  CG  MET A   5       2.040   1.440   0.000  1.00  0.00     0.000 C \n"
    + "ATOM      7  SD  MET A   5       3.850   1.440   0.000  1.00  0.00     0.000 SA\n"
    + "ATOM      8  CE  MET A   5       4.200   3.190   0.250  1.00  0.00     0.000 C \n"
)

_SYNTHETIC_FLEX_INITIAL_PDBQT = (
    "BEGIN_RES MET A 5\n"
    "ROOT\n"
    "ATOM      1  CA  MET A   5       0.000   0.000   0.000  1.00  0.00     0.000 C \n"
    "ENDROOT\n"
    "BRANCH   1   2\n"
    "ATOM      2  CB  MET A   5       1.530   0.000   0.000  1.00  0.00     0.000 C \n"
    "BRANCH   2   3\n"
    "ATOM      3  CG  MET A   5       2.040   1.440   0.000  1.00  0.00     0.000 C \n"
    "BRANCH   3   4\n"
    "ATOM      4  SD  MET A   5       3.850   1.440   0.000  1.00  0.00     0.000 SA\n"
    "ATOM      5  CE  MET A   5       4.200   3.190   0.250  1.00  0.00     0.000 C \n"
    "ENDBRANCH   3   4\n"
    "ENDBRANCH   2   3\n"
    "ENDBRANCH   1   2\n"
    "END_RES MET A 5\n"
)

# Sulfur-free synthetic ligand (only C and OA; SA comes exclusively from MET A:5 flex!).
_SYNTHETIC_LIGAND_PDBQT = (
    "ROOT\n"
    "ATOM      1  C   UNL     1       1.000  -2.500   0.500  1.00  0.00     0.000 C \n"
    "ATOM      2  O   UNL     1       2.200  -2.500   0.500  1.00  0.00     0.000 OA\n"
    "ENDROOT\n"
    "TORSDOF 0\n"
)


def _synthetic_flex_dlg(*, serial_offset: int, include_success_marker: bool) -> str:
    """Build a synthetic 2-run AutoDock DLG mirroring real Gate 0 CPU/GPU flex formatting.

    AutoDock4 CPU continues atom serials inside BEGIN_RES (`serial_offset=2` -> 3..7),
    while AutoDock-GPU restarts flex atom serials at 1 (`serial_offset=0` -> 1..5).
    """

    def _model(run: int, energy: float) -> list[str]:
        s = serial_offset
        return [
            f"DOCKED: MODEL        {run}",
            f"DOCKED: USER    Run = {run}",
            f"DOCKED: USER    Estimated Free Energy of Binding    =  {energy:6.2f} kcal/mol",
            "DOCKED: ROOT",
            (
                "DOCKED: ATOM      1  C   UNL     1       1.000  -2.500   0.500"
                " -0.10 +0.00    +0.000 C "
            ),
            (
                "DOCKED: ATOM      2  O   UNL     1       2.200  -2.500   0.500"
                " -0.20 +0.00    +0.000 OA"
            ),
            "DOCKED: ENDROOT",
            "DOCKED: TORSDOF 0",
            "DOCKED: BEGIN_RES MET A 5",
            "DOCKED: ROOT",
            (
                f"DOCKED: ATOM  {1 + s:5d}  CA  MET A   5       0.000   0.000   0.000"
                " +0.00 +0.00    +0.000 C "
            ),
            "DOCKED: ENDROOT",
            "DOCKED: BRANCH   1   2",
            (
                f"DOCKED: ATOM  {2 + s:5d}  CB  MET A   5       1.530   0.000   0.000"
                " +0.00 +0.00    +0.000 C "
            ),
            "DOCKED: BRANCH   2   3",
            (
                f"DOCKED: ATOM  {3 + s:5d}  CG  MET A   5       2.040  -1.440   0.000"
                " -0.05 +0.00    +0.000 C "
            ),
            "DOCKED: BRANCH   3   4",
            (
                f"DOCKED: ATOM  {4 + s:5d}  SD  MET A   5       3.850  -1.440   0.000"
                " -0.05 +0.00    +0.000 SA"
            ),
            (
                f"DOCKED: ATOM  {5 + s:5d}  CE  MET A   5       4.200  -3.190  -0.250"
                " -0.05 +0.00    +0.000 C "
            ),
            "DOCKED: ENDBRANCH   3   4",
            "DOCKED: ENDBRANCH   2   3",
            "DOCKED: ENDBRANCH   1   2",
            "DOCKED: END_RES MET A 5",
            "DOCKED: TER",
            "DOCKED: ENDMDL",
        ]

    lines = [
        *_model(1, -4.50),
        *_model(2, -4.10),
        "CLUSTERING HISTOGRAM",
        "   1 | -4.50 |   1 | -4.30 |   2 | ##",
        "RMSD TABLE",
        "   1    1    1   -4.50   0.00   0.00 RANKING",
        "   1    2    2   -4.10   0.45   0.45 RANKING",
    ]
    if include_success_marker:
        lines.append("Successful Completion")
    return "\n".join(lines) + "\n"


def _synthetic_rigid_dlg() -> str:
    lines = [
        "DOCKED: MODEL        1",
        "DOCKED: USER    Run = 1",
        "DOCKED: USER    Estimated Free Energy of Binding    =  -3.20 kcal/mol",
        "DOCKED: ROOT",
        "DOCKED: ATOM      1  C   UNL     1       1.000  -2.500   0.500 -0.10 +0.00    +0.000 C ",
        "DOCKED: ATOM      2  O   UNL     1       2.200  -2.500   0.500 -0.20 +0.00    +0.000 OA",
        "DOCKED: ENDROOT",
        "DOCKED: TORSDOF 0",
        "DOCKED: TER",
        "DOCKED: ENDMDL",
        "DOCKED: MODEL        2",
        "DOCKED: USER    Run = 2",
        "DOCKED: USER    Estimated Free Energy of Binding    =  -3.00 kcal/mol",
        "DOCKED: ROOT",
        "DOCKED: ATOM      1  C   UNL     1       1.100  -2.500   0.500 -0.10 +0.00    +0.000 C ",
        "DOCKED: ATOM      2  O   UNL     1       2.300  -2.500   0.500 -0.20 +0.00    +0.000 OA",
        "DOCKED: ENDROOT",
        "DOCKED: TORSDOF 0",
        "DOCKED: TER",
        "DOCKED: ENDMDL",
        "CLUSTERING HISTOGRAM",
        "   1 | -3.20 |   1 | -3.10 |   2 | ##",
        "RMSD TABLE",
        "   1    1    1   -3.20   0.00   0.00 RANKING",
        "   1    2    2   -3.00   0.10   0.10 RANKING",
        "Successful Completion",
    ]
    return "\n".join(lines) + "\n"


class _StubProlifAdapter:
    """Deterministic stub capturing the exact materialized coupled receptor PDB."""

    def __init__(self) -> None:
        self.seen_receptor_pdb_text: str | None = None

    def version(self) -> str:
        return "2.2.1"

    def analyze(
        self,
        *,
        pose_path: Path,
        conformer_path: Path,
        receptor_path: Path,
        profile: object,
    ) -> tuple[list[object], LigandDiagram]:
        _ = (pose_path, conformer_path, profile)
        self.seen_receptor_pdb_text = receptor_path.read_text(encoding="utf-8")
        return (
            [],
            LigandDiagram(
                atoms=[LigandDiagramAtom(atom_index=0, element="C", label="C1", x=0.0, y=0.0)],
                bonds=[],
            ),
        )


def _ad4_installation(*, max_atoms: int = 2048, max_torsions: int = 32) -> AutoDock4Installation:
    return AutoDock4Installation(
        executable="synthetic-autodock4",
        version="4.2.6",
        sha256="c" * 64,
        architecture="x86_64",
        max_torsions=max_torsions,
        max_atoms=max_atoms,
        max_maps=16,
    )


def _gpu_installation(**_: object) -> AutoDockGpuInstallation:
    return AutoDockGpuInstallation(
        executable="synthetic-autodock-gpu",
        version="1.6",
        sha256="d" * 64,
        architecture="x86_64",
        build="Release",
        device_name="Synthetic GPU Device",
    )


def _seed_synthetic_project(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    flexible: bool = True,
    with_high_dof_warning: bool = False,
) -> dict[str, object]:
    """Seed durable synthetic receptor, binding site, ligand, library, and AutoGrid map set."""
    now = datetime.now(UTC)
    receptor_store = ReceptorArtifactStore(tmp_path)
    site_store = BindingSiteArtifactStore(tmp_path)
    ligand_store = LigandArtifactStore(tmp_path)
    map_store = AutoGridMapStore(tmp_path)

    receptor_id = receptor_store.new_receptor_id()
    receptor_store.create_receptor(receptor_id)
    prot_bytes = _SYNTHETIC_CRYSTAL_PDB.encode("utf-8")
    prot_art_id = "rec-prot-pdb"
    receptor_store.write_bytes(receptor_id, "protonated.pdb", prot_bytes)

    warnings: list[StructuredWarning] = []
    if with_high_dof_warning:
        warnings.append(
            StructuredWarning(
                code=WarningCode.DOCKING_FLEXRES_DOF_HIGH,
                stage="receptor_preparation",
                message="Synthetic high flexible-DOF advisory for testing propagation.",
                details={"flex_residue_count": 5, "added_chi_torsion_count": 14},
            )
        )

    outputs = [
        ReceptorOutputArtifact(
            artifact_id=prot_art_id,
            stage=ReceptorOutputStage.PROTONATED_PDB,
            filename="protonated.pdb",
            format="pdb",
            sha256=sha256(prot_bytes).hexdigest(),
            size_bytes=len(prot_bytes),
            created_at=now,
            content_url=f"/receptors/{receptor_id}/outputs/{prot_art_id}/content",
        )
    ]

    flex_res = ResidueLocator(chain_id="A", residue_name="MET", sequence_number=5)
    flex_spec: ReceptorFlexSpec | None = None
    flex_atom_types: list[str] = []
    if flexible:
        rigid_bytes = _SYNTHETIC_RIGID_PDBQT.encode("utf-8")
        flex_bytes = _SYNTHETIC_FLEX_INITIAL_PDBQT.encode("utf-8")
        rigid_art_id = "rec-rigid-pdbqt"
        flex_art_id = "rec-flex-pdbqt"
        receptor_store.write_bytes(receptor_id, "receptor_rigid.pdbqt", rigid_bytes)
        receptor_store.write_bytes(receptor_id, "receptor_flex.pdbqt", flex_bytes)
        flex_spec = ReceptorFlexSpec(
            mode=ReceptorFlexMode.SIDECHAIN_FLEX,
            flex_residues=(flex_res,),
            receptor_rigid_sha256=sha256(rigid_bytes).hexdigest(),
            receptor_flex_sha256=sha256(flex_bytes).hexdigest(),
            added_chi_torsion_count=3,
        )
        flex_atom_types = ["C", "SA"]
        outputs.extend(
            [
                ReceptorOutputArtifact(
                    artifact_id=rigid_art_id,
                    stage=ReceptorOutputStage.PDBQT_RIGID,
                    filename="receptor_rigid.pdbqt",
                    format="pdbqt",
                    sha256=sha256(rigid_bytes).hexdigest(),
                    size_bytes=len(rigid_bytes),
                    created_at=now,
                    content_url=f"/receptors/{receptor_id}/outputs/{rigid_art_id}/content",
                ),
                ReceptorOutputArtifact(
                    artifact_id=flex_art_id,
                    stage=ReceptorOutputStage.PDBQT_FLEX,
                    filename="receptor_flex.pdbqt",
                    format="pdbqt",
                    sha256=sha256(flex_bytes).hexdigest(),
                    size_bytes=len(flex_bytes),
                    created_at=now,
                    content_url=f"/receptors/{receptor_id}/outputs/{flex_art_id}/content",
                ),
            ]
        )
    else:
        full_bytes = _SYNTHETIC_FULL_RIGID_PDBQT.encode("utf-8")
        full_art_id = "rec-full-pdbqt"
        receptor_store.write_bytes(receptor_id, "receptor.pdbqt", full_bytes)
        outputs.append(
            ReceptorOutputArtifact(
                artifact_id=full_art_id,
                stage=ReceptorOutputStage.PDBQT,
                filename="receptor.pdbqt",
                format="pdbqt",
                sha256=sha256(full_bytes).hexdigest(),
                size_bytes=len(full_bytes),
                created_at=now,
                content_url=f"/receptors/{receptor_id}/outputs/{full_art_id}/content",
            )
        )

    receptor_record = ReceptorPreparationRecord(
        receptor_id=receptor_id,
        source_artifact_id="src-synthetic-met",
        created_at=now,
        status=ReceptorPreparationStatus.DOCKING_READY,
        decisions=ReceptorPreparationRequest(
            selected_chains=["A"],
            water_action=ComponentAction.REMOVE,
            component_decisions=[],
            issue_decisions=[],
            protonation=ProtonationSettings(enabled=True),
            generate_pdbqt=True,
            flexibility=(
                ReceptorFlexRequest(
                    mode=ReceptorFlexMode.SIDECHAIN_FLEX,
                    flex_residues=[flex_res],
                )
                if flexible
                else None
            ),
        ),
        outputs=outputs,
        warnings=warnings,
        provenance=[],
        display_output_artifact_id=prot_art_id,
        flex_spec=flex_spec,
        flex_atom_types=flex_atom_types,
    )
    receptor_store.save_record(receptor_record)

    site_id = site_store.new_binding_site_id()
    site_store.save_record(
        BindingSiteRecord(
            binding_site_id=site_id,
            receptor_id=receptor_id,
            source_artifact_id="src-synthetic-met",
            created_at=now,
            box=_BOX,
            decisions=BindingSiteRequest(source=BindingSiteSource.MANUAL, manual_box=_BOX),
            warnings=[],
            provenance=[
                ProvenanceEvent(
                    event_id="evt-site",
                    event_type="binding_site_confirmed",
                    timestamp=now,
                    input_artifacts=[receptor_id],
                    output_artifacts=[site_id],
                    tool=ToolIdentity(name="Ankora", version="0.2.0-dev"),
                )
            ],
        )
    )

    library = import_local_ligand_library(
        content=b"CO SYNTHETIC_SULFUR_FREE_LIG\n",
        filename="synthetic.smi",
        store=ligand_store,
    )
    filter_run = apply_library_filters(
        library_id=library.artifact.library_id,
        request=ApplyLigandLibraryFilterRequest(acknowledge_selection=True),
        store=ligand_store,
    )
    ligand_id = filter_run.selected_ligand_ids[0]
    ligand = ligand_store.load_record(ligand_id)
    assert ligand.state is not None
    conformer = generate_ligand_conformer(
        ligand_id=ligand_id,
        request=GenerateLigandConformerRequest(
            acknowledge_current_chemical_state=True,
            state_id=ligand.state.state_id,
        ),
        store=ligand_store,
    )

    def _synthetic_meeko(**kwargs: object) -> tuple[ToolExecution, str]:
        output_path = kwargs["output_pdbqt_path"]
        assert isinstance(output_path, Path)
        output_path.write_text(_SYNTHETIC_LIGAND_PDBQT, encoding="utf-8", newline="\n")
        return (
            ToolExecution(command=["synthetic-meeko"], exit_code=0, stdout="", stderr=""),
            "0.7.1",
        )

    monkeypatch.setattr(
        "ankora_backend.services.ligand_preparation.execute_meeko_ligand",
        _synthetic_meeko,
    )
    pdbqt_record = prepare_ligand_pdbqt(
        ligand_id=ligand_id,
        conformer_id=conformer.artifact.conformer_id,
        request=PrepareLigandPdbqtRequest(),
        store=ligand_store,
    )
    prep_id = pdbqt_record.artifact.preparation_id
    library_id = library.artifact.library_id
    filter_run_id = filter_run.artifact.filter_run_id

    _install_synthetic_autogrid(monkeypatch)
    map_service = AutoGridMapService(
        map_store=map_store,
        receptor_store=receptor_store,
        binding_site_store=site_store,
        ligand_store=ligand_store,
    )
    map_set = map_service.ensure_map_set(
        AutoGridMapSetRequest(
            receptor_id=receptor_id,
            binding_site_id=site_id,
            source=AutoGridLigandSource.LIGAND_PREPARATION,
            ligand_id=ligand_id,
            ligand_preparation_id=prep_id,
        )
    ).record
    return {
        "receptor_id": receptor_id,
        "receptor": receptor_record,
        "site_id": site_id,
        "ligand_id": ligand_id,
        "prep_id": prep_id,
        "library_id": library_id,
        "filter_run_id": filter_run_id,
        "map_set": map_set,
    }


def _wait_for_ad4_job(service: AutoDock4DockingService, job_id: str) -> AutoDock4DockingJobRecord:
    deadline = time.monotonic() + 10.0
    while time.monotonic() < deadline:
        record = service.get(job_id)
        if record.status in {
            AutoDock4JobStatus.COMPLETED,
            AutoDock4JobStatus.FAILED,
            AutoDock4JobStatus.CANCELED,
        }:
            return record
        time.sleep(0.01)
    raise AssertionError("AutoDock4 job did not finish")


def _wait_for_ad4_batch(service: AutoDock4DockingService, batch_id: str) -> AutoDock4BatchRecord:
    deadline = time.monotonic() + 10.0
    while time.monotonic() < deadline:
        record = service.get_batch(batch_id)
        if record.status in {
            AutoDock4JobStatus.COMPLETED,
            AutoDock4JobStatus.FAILED,
            AutoDock4JobStatus.CANCELED,
        }:
            return record
        time.sleep(0.01)
    raise AssertionError("AutoDock4 batch did not finish")


def _wait_for_gpu_job(
    service: AutoDockGpuDockingService, job_id: str
) -> AutoDockGpuDockingJobRecord:
    deadline = time.monotonic() + 10.0
    while time.monotonic() < deadline:
        record = service.get(job_id)
        if record.status in {
            AutoDockJobStatus.COMPLETED,
            AutoDockJobStatus.FAILED,
            AutoDockJobStatus.CANCELED,
        }:
            return record
        time.sleep(0.01)
    raise AssertionError("AutoDock-GPU job did not finish")


def _wait_for_gpu_batch(
    service: AutoDockGpuDockingService, batch_id: str
) -> AutoDockGpuBatchRecord:
    deadline = time.monotonic() + 10.0
    while time.monotonic() < deadline:
        record = service.get_batch(batch_id)
        if record.status in {
            AutoDockJobStatus.COMPLETED,
            AutoDockJobStatus.FAILED,
            AutoDockJobStatus.CANCELED,
        }:
            return record
        time.sleep(0.01)
    raise AssertionError("AutoDock-GPU batch did not finish")


# --- Pure adapter & ADR-032 A1/A6 tests ---


def test_autodock4_dpf_renders_flexres_and_union_types_while_preserving_rigid_dpf() -> None:
    rigid_dpf = render_autodock4_dpf(
        ligand_filename="ligand.pdbqt",
        map_prefix="receptor",
        ligand_atom_types=("C", "OA"),
        about=(1.0, 2.0, 3.0),
        torsional_degrees_of_freedom=2,
        seed=(42, 43),
        ga_runs=2,
        ga_population_size=50,
        ga_energy_evaluations=10_000,
        ga_generations=27_000,
        cluster_rmsd_tolerance_angstrom=2.0,
    )
    assert "flexres " not in rigid_dpf
    assert "ligand_types C OA\n" in rigid_dpf

    flex_dpf = render_autodock4_dpf(
        ligand_filename="ligand.pdbqt",
        map_prefix="receptor",
        ligand_atom_types=("C", "OA", "SA"),
        about=(1.0, 2.0, 3.0),
        torsional_degrees_of_freedom=2,
        seed=(42, 43),
        ga_runs=2,
        ga_population_size=50,
        ga_energy_evaluations=10_000,
        ga_generations=27_000,
        cluster_rmsd_tolerance_angstrom=2.0,
        flexres_filename=FLEXRES_FILENAME,
    )
    lines = flex_dpf.splitlines()
    assert "ligand_types C OA SA" in lines
    assert "map receptor.SA.map" in lines
    move_idx = lines.index("move ligand.pdbqt")
    assert lines[move_idx + 1] == f"flexres {FLEXRES_FILENAME}"

    for bad_name in ("", "../flex.pdbqt", "flex bad.pdbqt", "fléx.pdbqt"):
        with pytest.raises(AnkoraDomainError) as exc_info:
            render_autodock4_dpf(
                ligand_filename="ligand.pdbqt",
                map_prefix="receptor",
                ligand_atom_types=("C",),
                about=(0.0, 0.0, 0.0),
                torsional_degrees_of_freedom=0,
                seed=(42, 43),
                ga_runs=2,
                ga_population_size=50,
                ga_energy_evaluations=10_000,
                ga_generations=27_000,
                cluster_rmsd_tolerance_angstrom=2.0,
                flexres_filename=bad_name,
            )
        assert exc_info.value.code == "AUTODOCK4_REQUEST_INVALID"


def test_autodock4_limits_account_for_flex_atoms_and_torsions() -> None:
    inst = _ad4_installation(max_atoms=10, max_torsions=6)
    validate_ligand_against_autodock4_limits(
        inst, atom_count=5, torsional_degrees_of_freedom=3, map_count=8,
        flex_atom_count=5, flex_torsions=3,
    )
    with pytest.raises(AnkoraDomainError) as atom_err:
        validate_ligand_against_autodock4_limits(
            inst, atom_count=6, torsional_degrees_of_freedom=2, map_count=8,
            flex_atom_count=5, flex_torsions=2,
        )
    assert atom_err.value.code == "AUTODOCK4_LIGAND_TOO_LARGE"
    assert atom_err.value.details["atom_count"] == 11
    assert atom_err.value.details["flex_atom_count"] == 5

    with pytest.raises(AnkoraDomainError) as tors_err:
        validate_ligand_against_autodock4_limits(
            inst, atom_count=4, torsional_degrees_of_freedom=4, map_count=8,
            flex_atom_count=4, flex_torsions=3,
        )
    assert tors_err.value.code == "AUTODOCK4_LIGAND_TOO_FLEXIBLE"
    assert tors_err.value.details["torsional_degrees_of_freedom"] == 7
    assert tors_err.value.details["flex_torsions"] == 3


def test_autodock_gpu_build_arguments_supports_flexres_and_preserves_filelist() -> None:
    rigid_args = build_arguments(
        device_number=1,
        runs=2,
        seed=(1, 2, 3),
        heuristics=False,
        autostop=False,
        energy_evaluations=10_000,
        population_size=50,
        local_search_method="ad",
        cluster_rmsd_tolerance_angstrom=2.0,
    )
    assert "--flexres" not in rigid_args

    flex_args = build_arguments(
        device_number=1,
        runs=2,
        seed=(1, 2, 3),
        heuristics=False,
        autostop=False,
        energy_evaluations=10_000,
        population_size=50,
        local_search_method="ad",
        cluster_rmsd_tolerance_angstrom=2.0,
        flexres_filename=GPU_FLEXRES_FILENAME,
    )
    assert "--flexres" in flex_args
    assert flex_args[flex_args.index("--flexres") + 1] == GPU_FLEXRES_FILENAME

    filelist_args = _as_filelist_arguments(flex_args)
    assert "--lfile" not in filelist_args
    assert "--resnam" not in filelist_args
    assert "--filelist" in filelist_args
    assert "--flexres" in filelist_args
    assert filelist_args[filelist_args.index("--flexres") + 1] == GPU_FLEXRES_FILENAME

    with pytest.raises(AnkoraDomainError) as bad_err:
        build_arguments(
            device_number=1,
            runs=2,
            seed=(1, 2, 3),
            heuristics=False,
            autostop=False,
            energy_evaluations=10_000,
            population_size=50,
            local_search_method="ad",
            cluster_rmsd_tolerance_angstrom=2.0,
            flexres_filename="../bad.pdbqt",
        )
    assert bad_err.value.code == "AUTODOCK_GPU_FLEXRES_INVALID"


def test_parse_autodock4_log_splits_cpu_and_gpu_flex_and_produces_identical_e8_pdb() -> None:
    # CPU continues atom serials inside BEGIN_RES (3..7); GPU restarts at 1 (1..5).
    cpu_parsed = parse_autodock4_log(
        _synthetic_flex_dlg(serial_offset=2, include_success_marker=True),
        expect_flex_sidechains=True,
    )
    gpu_parsed = parse_autodock4_log(
        _synthetic_flex_dlg(serial_offset=0, include_success_marker=False),
        expect_flex_sidechains=True,
    )
    assert len(cpu_parsed.poses) == 2
    assert len(gpu_parsed.poses) == 2

    cpu_pose = cpu_parsed.poses[0]
    gpu_pose = gpu_parsed.poses[0]
    assert b"BEGIN_RES" not in cpu_pose.content
    assert b"BEGIN_RES" not in gpu_pose.content
    assert cpu_pose.flex_sidechains_content is not None
    assert gpu_pose.flex_sidechains_content is not None
    assert cpu_pose.flex_residue_markers == ("MET A 5",)
    assert gpu_pose.flex_residue_markers == ("MET A 5",)
    # Raw serial numbers differ between CPU and GPU (ADR-032 A6)...
    assert cpu_pose.flex_sidechains_content != gpu_pose.flex_sidechains_content
    # ...yet deterministic E8 materialization yields bit-identical coupled receptor PDBs!
    cpu_mat = materialize_coupled_receptor_pdb(
        protonated_pdb_text=_SYNTHETIC_CRYSTAL_PDB,
        pose_flex_sidechains_pdbqt=cpu_pose.flex_sidechains_content.decode("utf-8"),
    )
    gpu_mat = materialize_coupled_receptor_pdb(
        protonated_pdb_text=_SYNTHETIC_CRYSTAL_PDB,
        pose_flex_sidechains_pdbqt=gpu_pose.flex_sidechains_content.decode("utf-8"),
    )
    assert cpu_mat.sha256 == gpu_mat.sha256
    assert cpu_mat.pdb_text == gpu_mat.pdb_text
    assert cpu_mat.repositioned_nonpolar_hydrogen_count == 7

    # Missing BEGIN_RES when flex is expected must fail closed.
    with pytest.raises(AnkoraDomainError) as missing_flex:
        parse_autodock4_log(_synthetic_rigid_dlg(), expect_flex_sidechains=True)
    assert missing_flex.value.code == "AUTODOCK4_OUTPUT_INVALID"


# --- E7 fail-closed enforcement tests ---


def test_autodock4_and_gpu_fail_closed_with_e7_on_mismatched_map_sets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    flex_project = _seed_synthetic_project(tmp_path / "flex", monkeypatch, flexible=True)
    rigid_project = _seed_synthetic_project(tmp_path / "rigid", monkeypatch, flexible=False)

    # Copy rigid map set into flex project store to simulate reusing a full rigid map set
    # with a sidechain_flex receptor (forbidden by ADR-032 E7).
    flex_root = tmp_path / "flex"
    rigid_map_set: AutoGridMapSetRecord = rigid_project["map_set"]  # type: ignore[assignment]
    flex_map_store = AutoGridMapStore(flex_root)
    rigid_map_store = AutoGridMapStore(tmp_path / "rigid")
    reused_id = flex_map_store.new_map_set_id()
    copied_record = rigid_map_set.model_copy(
        update={
            "map_set_id": reused_id,
            "receptor_id": str(flex_project["receptor_id"]),
            "binding_site_id": str(flex_project["site_id"]),
        }
    )
    copied_dir = flex_map_store.create_map_set_directory(reused_id)
    src_dir = rigid_map_store.map_set_directory(rigid_map_set.map_set_id)
    for artifact in copied_record.artifacts:
        (copied_dir / artifact.filename).write_bytes((src_dir / artifact.filename).read_bytes())
    flex_map_store.write_record(copied_record)

    monkeypatch.setattr(ad4_module, "probe_autodock4", _ad4_installation)
    monkeypatch.setattr(gpu_module, "probe_autodock_gpu", _gpu_installation)

    ad4_service = AutoDock4DockingService(
        job_store=AutoDock4JobStore(flex_root),
        map_store=flex_map_store,
        ligand_store=LigandArtifactStore(flex_root),
        receptor_store=ReceptorArtifactStore(flex_root),
        binding_site_store=BindingSiteArtifactStore(flex_root),
    )
    gpu_service = AutoDockGpuDockingService(
        job_store=AutoDockGpuJobStore(flex_root),
        map_store=flex_map_store,
        ligand_store=LigandArtifactStore(flex_root),
        receptor_store=ReceptorArtifactStore(flex_root),
        binding_site_store=BindingSiteArtifactStore(flex_root),
    )

    with pytest.raises(AnkoraDomainError) as ad4_err:
        ad4_service.start(
            AutoDock4DockingRequest(
                receptor_id=str(flex_project["receptor_id"]),
                binding_site_id=str(flex_project["site_id"]),
                map_set_id=reused_id,
                ligand_id=str(flex_project["ligand_id"]),
                ligand_preparation_id=str(flex_project["prep_id"]),
                parameters=AutoDock4DockingParameters(ga_runs=2),
                acknowledge_inputs_and_scoring=True,
            )
        )
    assert (ad4_err.value.code, ad4_err.value.status_code) == ("AUTOGRID_FLEXRES_MAP_MISMATCH", 422)

    with pytest.raises(AnkoraDomainError) as ad4_batch_err:
        ad4_service.start_batch(
            AutoDock4BatchRequest(
                receptor_id=str(flex_project["receptor_id"]),
                binding_site_id=str(flex_project["site_id"]),
                map_set_id=reused_id,
                library_id=str(flex_project["library_id"]),
                filter_run_id=str(flex_project["filter_run_id"]),
                parameters=AutoDock4BatchParameters(ga_runs=2),
                acknowledge_inputs_and_scoring=True,
            )
        )
    assert ad4_batch_err.value.code == "AUTOGRID_FLEXRES_MAP_MISMATCH"

    with pytest.raises(AnkoraDomainError) as gpu_err:
        gpu_service.start(
            AutoDockGpuDockingRequest(
                receptor_id=str(flex_project["receptor_id"]),
                binding_site_id=str(flex_project["site_id"]),
                map_set_id=reused_id,
                ligand_id=str(flex_project["ligand_id"]),
                ligand_preparation_id=str(flex_project["prep_id"]),
                parameters=AutoDockGpuDockingParameters(runs=2),
                acknowledge_inputs_and_scoring=True,
            )
        )
    assert (gpu_err.value.code, gpu_err.value.status_code) == ("AUTOGRID_FLEXRES_MAP_MISMATCH", 422)

    with pytest.raises(AnkoraDomainError) as gpu_batch_err:
        gpu_service.start_batch(
            AutoDockGpuBatchRequest(
                receptor_id=str(flex_project["receptor_id"]),
                binding_site_id=str(flex_project["site_id"]),
                map_set_id=reused_id,
                library_id=str(flex_project["library_id"]),
                filter_run_id=str(flex_project["filter_run_id"]),
                parameters=AutoDockGpuBatchParameters(runs=2),
                acknowledge_inputs_and_scoring=True,
            )
        )
    assert gpu_batch_err.value.code == "AUTOGRID_FLEXRES_MAP_MISMATCH"

    # Also test a flex map set tampered to omit the SA affinity map file.
    valid_flex_map: AutoGridMapSetRecord = flex_project["map_set"]  # type: ignore[assignment]
    no_sa_id = flex_map_store.new_map_set_id()
    no_sa_record = valid_flex_map.model_copy(
        update={
            "map_set_id": no_sa_id,
            "artifacts": [
                item
                for item in valid_flex_map.artifacts
                if not (item.kind is AutoGridMapKind.AFFINITY and item.atom_type == "SA")
            ],
        }
    )
    flex_map_store.create_map_set_directory(no_sa_id)
    flex_map_store.write_record(no_sa_record)
    with pytest.raises(AnkoraDomainError) as missing_sa_err:
        ad4_service.start(
            AutoDock4DockingRequest(
                receptor_id=str(flex_project["receptor_id"]),
                binding_site_id=str(flex_project["site_id"]),
                map_set_id=no_sa_id,
                ligand_id=str(flex_project["ligand_id"]),
                ligand_preparation_id=str(flex_project["prep_id"]),
                parameters=AutoDock4DockingParameters(ga_runs=2),
                acknowledge_inputs_and_scoring=True,
            )
        )
    assert missing_sa_err.value.code == "AUTOGRID_FLEXRES_MAP_MISMATCH"


# --- Full service E8 coupled persistence & PoseInteractions tests ---


def test_autodock4_and_gpu_single_and_batch_flex_persist_e8_and_match_in_pose_interactions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seeded = _seed_synthetic_project(
        tmp_path, monkeypatch, flexible=True, with_high_dof_warning=True
    )
    map_set: AutoGridMapSetRecord = seeded["map_set"]  # type: ignore[assignment]
    receptor: ReceptorPreparationRecord = seeded["receptor"]  # type: ignore[assignment]
    assert receptor.flex_spec is not None

    monkeypatch.setattr(ad4_module, "probe_autodock4", _ad4_installation)
    monkeypatch.setattr(gpu_module, "probe_autodock_gpu", _gpu_installation)

    captured_dpfs: list[str] = []
    captured_gpu_args: list[list[str]] = []

    def _fake_ad4_run(**kwargs: object) -> CancellableToolExecution:
        job_dir = kwargs["job_directory"]
        assert isinstance(job_dir, Path)
        assert (job_dir / FLEXRES_FILENAME).is_file()
        assert (job_dir / "receptor.SA.map").is_file()
        dpf_text = (job_dir / DOCKING_PARAMETER_FILENAME).read_text(encoding="ascii")
        captured_dpfs.append(dpf_text)
        (job_dir / DOCKING_LOG_FILENAME).write_text(
            _synthetic_flex_dlg(serial_offset=2, include_success_marker=True),
            encoding="utf-8",
        )
        return CancellableToolExecution(
            command=["synthetic-autodock4", "-p", DOCKING_PARAMETER_FILENAME],
            exit_code=0,
            stdout="",
            stderr="",
            canceled=False,
            timed_out=False,
        )

    def _fake_gpu_run(**kwargs: object) -> CancellableToolExecution:
        job_dir = kwargs["job_directory"]
        arguments = kwargs["arguments"]
        assert isinstance(job_dir, Path)
        assert isinstance(arguments, list)
        captured_gpu_args.append(list(arguments))
        assert (job_dir / GPU_FLEXRES_FILENAME).is_file()
        assert (job_dir / "receptor.SA.map").is_file()
        dlg_text = _synthetic_flex_dlg(serial_offset=0, include_success_marker=False)
        if "--filelist" in arguments:
            (job_dir / "m1.dlg").write_text(dlg_text, encoding="utf-8")
        else:
            (job_dir / GPU_LOG_FILENAME).write_text(dlg_text, encoding="utf-8")
        return CancellableToolExecution(
            command=["synthetic-autodock-gpu", *arguments],
            exit_code=0,
            stdout="OpenCL device: Synthetic GPU Device\nAll jobs ran without errors.\n",
            stderr="",
            canceled=False,
            timed_out=False,
        )

    monkeypatch.setattr(ad4_module, "execute_autodock4_cancellable", _fake_ad4_run)
    monkeypatch.setattr(gpu_module, "execute_autodock_gpu_cancellable", _fake_gpu_run)

    ad4_store = AutoDock4JobStore(tmp_path)
    gpu_store = AutoDockGpuJobStore(tmp_path)
    map_store = AutoGridMapStore(tmp_path)
    ligand_store = LigandArtifactStore(tmp_path)
    receptor_store = ReceptorArtifactStore(tmp_path)
    site_store = BindingSiteArtifactStore(tmp_path)

    ad4_service = AutoDock4DockingService(
        job_store=ad4_store,
        map_store=map_store,
        ligand_store=ligand_store,
        receptor_store=receptor_store,
        binding_site_store=site_store,
    )
    gpu_service = AutoDockGpuDockingService(
        job_store=gpu_store,
        map_store=map_store,
        ligand_store=ligand_store,
        receptor_store=receptor_store,
        binding_site_store=site_store,
    )

    try:
        # 1. AutoDock4 CPU single job
        ad4_job = _wait_for_ad4_job(
            ad4_service,
            ad4_service.start(
                AutoDock4DockingRequest(
                    receptor_id=str(seeded["receptor_id"]),
                    binding_site_id=str(seeded["site_id"]),
                    map_set_id=map_set.map_set_id,
                    ligand_id=str(seeded["ligand_id"]),
                    ligand_preparation_id=str(seeded["prep_id"]),
                    parameters=AutoDock4DockingParameters(ga_runs=2),
                    acknowledge_inputs_and_scoring=True,
                )
            ).job_id,
        )
        assert ad4_job.status is AutoDock4JobStatus.COMPLETED
        assert ad4_job.receptor_flex_mode is ReceptorFlexMode.SIDECHAIN_FLEX
        assert ad4_job.receptor_flex_sha256 == receptor.flex_spec.receptor_flex_sha256
        assert ad4_job.flex_atom_types == ["C", "SA"]
        assert any(w.code is WarningCode.DOCKING_FLEXRES_DOF_HIGH for w in ad4_job.warnings)
        assert len(ad4_job.runs) == 2
        ad4_art = ad4_job.runs[0].artifact
        assert ad4_art.flex_filename == "run_1_flex.pdbqt"
        assert ad4_art.pose_flex_sidechains_sha256 is not None
        assert ad4_art.pose_complex_identity_sha256 == PoseComplexIdentity(
            mode=ReceptorFlexMode.SIDECHAIN_FLEX,
            receptor_rigid_sha256=receptor.flex_spec.receptor_rigid_sha256,
            pose_flex_sidechains_sha256=ad4_art.pose_flex_sidechains_sha256,
            ligand_pose_sha256=ad4_art.sha256,
        ).complex_identity_sha256
        flex_path = ad4_service.pose_flex_content_path(ad4_job.job_id, ad4_art.artifact_id)
        assert flex_path is not None and flex_path.is_file()

        # Verify DPF included union ligand_types (C OA SA), map receptor.SA.map, and flexres.
        assert "ligand_types C OA SA\n" in captured_dpfs[0]
        assert "map receptor.SA.map\n" in captured_dpfs[0]
        assert f"flexres {FLEXRES_FILENAME}\n" in captured_dpfs[0]

        # 2. AutoDock4 CPU batch campaign
        ad4_batch = _wait_for_ad4_batch(
            ad4_service,
            ad4_service.start_batch(
                AutoDock4BatchRequest(
                    receptor_id=str(seeded["receptor_id"]),
                    binding_site_id=str(seeded["site_id"]),
                    map_set_id=map_set.map_set_id,
                    library_id=str(seeded["library_id"]),
                    filter_run_id=str(seeded["filter_run_id"]),
                    parameters=AutoDock4BatchParameters(ga_runs=2),
                    acknowledge_inputs_and_scoring=True,
                )
            ).batch_id,
        )
        assert ad4_batch.status is AutoDock4JobStatus.COMPLETED
        assert ad4_batch.receptor_flex_mode is ReceptorFlexMode.SIDECHAIN_FLEX
        assert ad4_batch.succeeded_count == 1
        ad4_batch_art = ad4_batch.entries[0].runs[0].artifact
        assert ad4_batch_art.pose_flex_sidechains_sha256 is not None
        assert (
            ad4_service.batch_pose_flex_content_path(
                ad4_batch.batch_id, str(seeded["ligand_id"]), ad4_batch_art.artifact_id
            )
            is not None
        )
        assert f"flexres {FLEXRES_FILENAME}\n" in captured_dpfs[1]

        # 3. AutoDock-GPU single job
        gpu_job = _wait_for_gpu_job(
            gpu_service,
            gpu_service.start(
                AutoDockGpuDockingRequest(
                    receptor_id=str(seeded["receptor_id"]),
                    binding_site_id=str(seeded["site_id"]),
                    map_set_id=map_set.map_set_id,
                    ligand_id=str(seeded["ligand_id"]),
                    ligand_preparation_id=str(seeded["prep_id"]),
                    parameters=AutoDockGpuDockingParameters(runs=2),
                    acknowledge_inputs_and_scoring=True,
                )
            ).job_id,
        )
        assert gpu_job.status is AutoDockJobStatus.COMPLETED
        assert gpu_job.receptor_flex_mode is ReceptorFlexMode.SIDECHAIN_FLEX
        assert any(w.code is WarningCode.DOCKING_FLEXRES_DOF_HIGH for w in gpu_job.warnings)
        assert "--flexres" in captured_gpu_args[0]
        gpu_art = gpu_job.runs[0].artifact
        assert gpu_art.flex_filename == "run_1_flex.pdbqt"
        assert gpu_art.pose_flex_sidechains_sha256 is not None
        assert gpu_service.pose_flex_content_path(gpu_job.job_id, gpu_art.artifact_id) is not None

        # 4. AutoDock-GPU batch (--filelist + --flexres)
        gpu_batch = _wait_for_gpu_batch(
            gpu_service,
            gpu_service.start_batch(
                AutoDockGpuBatchRequest(
                    receptor_id=str(seeded["receptor_id"]),
                    binding_site_id=str(seeded["site_id"]),
                    map_set_id=map_set.map_set_id,
                    library_id=str(seeded["library_id"]),
                    filter_run_id=str(seeded["filter_run_id"]),
                    parameters=AutoDockGpuBatchParameters(runs=2),
                    acknowledge_inputs_and_scoring=True,
                )
            ).batch_id,
        )
        assert gpu_batch.status is AutoDockJobStatus.COMPLETED
        assert gpu_batch.receptor_flex_mode is ReceptorFlexMode.SIDECHAIN_FLEX
        assert gpu_batch.succeeded_count == 1
        assert "--filelist" in captured_gpu_args[1]
        assert "--flexres" in captured_gpu_args[1]
        gpu_batch_art = gpu_batch.entries[0].runs[0].artifact
        assert gpu_batch_art.pose_flex_sidechains_sha256 is not None
        assert (
            gpu_service.batch_pose_flex_content_path(
                gpu_batch.batch_id, str(seeded["ligand_id"]), gpu_batch_art.artifact_id
            )
            is not None
        )

        # 5. Coupled E8 PoseInteractionService (ProLIF + complex_pdb) across CPU & GPU
        stub_prolif = _StubProlifAdapter()
        interactions = PoseInteractionService(
            docking_store=DockingArtifactStore(tmp_path),
            autodock4_store=ad4_store,
            autodock_gpu_store=gpu_store,
            autogrid_store=map_store,
            receptor_store=receptor_store,
            ligand_store=ligand_store,
            interaction_store=PoseInteractionStore(tmp_path),
            adapter=stub_prolif,  # type: ignore[arg-type]
        )
        ad4_analysis = interactions.analyze(
            f"autodock4_job:{ad4_job.job_id}",
            str(seeded["ligand_id"]),
            ad4_art.artifact_id,
            InteractionAnalysisRequest(),
        )
        ad4_coupled_pdb_for_prolif = stub_prolif.seen_receptor_pdb_text
        assert ad4_coupled_pdb_for_prolif is not None
        assert ad4_analysis.materialized_coupled_receptor_sha256 is not None
        assert ad4_analysis.pose_flex_sidechains_sha256 == ad4_art.pose_flex_sidechains_sha256
        assert ad4_analysis.pose_complex_identity_sha256 == ad4_art.pose_complex_identity_sha256
        # Moved MET A:5 CG is at y = -1.440 (not crystal +1.440)!
        assert "  2.040  -1.440   0.000" in ad4_coupled_pdb_for_prolif

        gpu_analysis = interactions.analyze(
            f"autodock_gpu_job:{gpu_job.job_id}",
            str(seeded["ligand_id"]),
            gpu_art.artifact_id,
            InteractionAnalysisRequest(),
        )
        gpu_coupled_pdb_for_prolif = stub_prolif.seen_receptor_pdb_text
        assert gpu_coupled_pdb_for_prolif == ad4_coupled_pdb_for_prolif
        assert (
            gpu_analysis.materialized_coupled_receptor_sha256
            == ad4_analysis.materialized_coupled_receptor_sha256
        )

        # Verify batch interaction analysis + complex_pdb also resolve coupled side chains.
        ad4_batch_analysis = interactions.analyze(
            f"autodock4_batch:{ad4_batch.batch_id}",
            str(seeded["ligand_id"]),
            ad4_batch_art.artifact_id,
            InteractionAnalysisRequest(),
        )
        gpu_batch_analysis = interactions.analyze(
            f"autodock_gpu_batch:{gpu_batch.batch_id}",
            str(seeded["ligand_id"]),
            gpu_batch_art.artifact_id,
            InteractionAnalysisRequest(),
        )
        assert (
            ad4_batch_analysis.materialized_coupled_receptor_sha256
            == ad4_analysis.materialized_coupled_receptor_sha256
        )
        assert (
            gpu_batch_analysis.materialized_coupled_receptor_sha256
            == ad4_analysis.materialized_coupled_receptor_sha256
        )

        ad4_complex_text, _ = interactions.complex_pdb(
            f"autodock4_job:{ad4_job.job_id}",
            str(seeded["ligand_id"]),
            ad4_art.artifact_id,
        )
        gpu_complex_text, _ = interactions.complex_pdb(
            f"autodock_gpu_job:{gpu_job.job_id}",
            str(seeded["ligand_id"]),
            gpu_art.artifact_id,
        )
        assert "  2.040  -1.440   0.000" in ad4_complex_text
        assert "  2.040  -1.440   0.000" in gpu_complex_text
    finally:
        ad4_service.shutdown()
        gpu_service.shutdown()


def test_legacy_rigid_autodock4_and_gpu_records_still_deserialize() -> None:
    now = datetime.now(UTC).isoformat()
    legacy_ad4 = {
        "job_id": "job-1",
        "status": "completed",
        "phase": "complete",
        "created_at": now,
        "request": {
            "receptor_id": "rec-1",
            "binding_site_id": "site-1",
            "map_set_id": "map-1",
            "ligand_id": "lig-1",
            "ligand_preparation_id": "prep-1",
            "acknowledge_inputs_and_scoring": True,
        },
        "autodock4": {
            "tool": {"name": "AutoDock", "version": "4.2.6"},
            "executable_path": "autodock4",
            "sha256": "a" * 64,
            "max_torsions": 32,
            "max_atoms": 2048,
            "max_maps": 16,
        },
        "receptor_id": "rec-1",
        "binding_site_id": "site-1",
        "map_set_id": "map-1",
        "map_set_identity_key": "b" * 64,
        "ligand_sha256": "c" * 64,
        "ligand_atom_types": ["C", "OA"],
        "ligand_atom_count": 2,
        "torsional_degrees_of_freedom": 0,
    }
    parsed_ad4 = AutoDock4DockingJobRecord.model_validate(legacy_ad4)
    assert parsed_ad4.receptor_flex_mode is ReceptorFlexMode.RIGID
    assert parsed_ad4.flex_residues == []

    legacy_gpu = {
        "job_id": "gpu-1",
        "status": "completed",
        "phase": "complete",
        "created_at": now,
        "request": legacy_ad4["request"],
        "autodock_gpu": {
            "tool": {"name": "AutoDock-GPU", "version": "1.6"},
            "executable_path": "autodock-gpu",
            "sha256": "d" * 64,
            "build": "Release",
            "device_number": 1,
            "device_name": "Synthetic GPU",
        },
        "receptor_id": "rec-1",
        "binding_site_id": "site-1",
        "map_set_id": "map-1",
        "map_set_identity_key": "b" * 64,
        "ligand_sha256": "c" * 64,
        "ligand_atom_types": ["C", "OA"],
        "ligand_atom_count": 2,
        "torsional_degrees_of_freedom": 0,
    }
    parsed_gpu = AutoDockGpuDockingJobRecord.model_validate(legacy_gpu)
    assert parsed_gpu.receptor_flex_mode is ReceptorFlexMode.RIGID
    assert parsed_gpu.flex_residues == []


# --- Live real-binary end-to-end tests (Windows + Linux) ---


def _prepare_live_garymp_project(tmp_path: Path) -> dict[str, object]:
    """Build real Meeko 0.7.1 FlexRes split (TYR A:4, MET A:5) + sulfur-free ligand."""
    Chem = import_module("rdkit.Chem")
    AllChem = import_module("rdkit.Chem.AllChem")

    peptide = Chem.MolFromSequence("GARYMP")
    assert peptide is not None
    peptide_h = Chem.AddHs(peptide)
    params = AllChem.ETKDGv3()
    params.randomSeed = 42
    assert AllChem.EmbedMolecule(peptide_h, params) == 0
    pdb_text = Chem.MolToPDBBlock(peptide_h)

    structures = StructureArtifactStore(tmp_path)
    receptors = ReceptorArtifactStore(tmp_path)
    sites = BindingSiteArtifactStore(tmp_path)
    ligands = LigandArtifactStore(tmp_path)

    structure = import_structure_bytes(
        content=pdb_text.encode("utf-8"),
        filename="live_synthetic_garymp.pdb",
        source=StructureSource.LOCAL,
        source_uri=None,
        store=structures,
    )
    flex_residues = [
        ResidueLocator(chain_id="A", residue_name="TYR", sequence_number=4),
        ResidueLocator(chain_id="A", residue_name="MET", sequence_number=5),
    ]
    receptor = receptor_preparation.prepare_receptor(
        source_artifact_id=structure.artifact.artifact_id,
        request=ReceptorPreparationRequest(
            selected_chains=["A"],
            water_action=ComponentAction.REMOVE,
            component_decisions=[],
            issue_decisions=[],
            protonation=ProtonationSettings(enabled=True, force_field="PARSE"),
            generate_pdbqt=True,
            flexibility=ReceptorFlexRequest(
                mode=ReceptorFlexMode.SIDECHAIN_FLEX,
                flex_residues=flex_residues,
            ),
        ),
        structure_store=structures,
        receptor_store=receptors,
    )
    assert receptor.flex_spec is not None
    assert "SA" in receptor.flex_atom_types

    # Center box on receptor centroid so all flex atoms stay inside the grid.
    prot = next(
        item for item in receptor.outputs if item.stage is ReceptorOutputStage.PROTONATED_PDB
    )
    prot_text = receptors.content_path(receptor.receptor_id, prot.artifact_id).read_text(
        encoding="utf-8"
    )
    coords = [
        (float(line[30:38]), float(line[38:46]), float(line[46:54]))
        for line in prot_text.splitlines()
        if line.startswith(("ATOM  ", "HETATM"))
    ]
    cx = sum(p[0] for p in coords) / len(coords)
    cy = sum(p[1] for p in coords) / len(coords)
    cz = sum(p[2] for p in coords) / len(coords)
    box = BindingBox(center_x=cx, center_y=cy, center_z=cz, size_x=22.0, size_y=22.0, size_z=22.0)

    site_id = sites.new_binding_site_id()
    now = datetime.now(UTC)
    sites.save_record(
        BindingSiteRecord(
            binding_site_id=site_id,
            receptor_id=receptor.receptor_id,
            source_artifact_id=structure.artifact.artifact_id,
            created_at=now,
            box=box,
            decisions=BindingSiteRequest(source=BindingSiteSource.MANUAL, manual_box=box),
            warnings=[],
            provenance=[
                ProvenanceEvent(
                    event_id="evt-live-site",
                    event_type="binding_site_confirmed",
                    timestamp=now,
                    input_artifacts=[receptor.receptor_id],
                    output_artifacts=[site_id],
                    tool=ToolIdentity(name="Ankora", version="0.2.0-dev"),
                )
            ],
        )
    )

    # Sulfur-free ligand (N-ethylacetamide) prepared through real RDKit + Meeko.
    lig_record = import_local_ligand(
        content=b"CCNC(C)=O LIVE_SYNTHETIC_AMIDE\n",
        filename="live_synthetic_amide.smi",
        store=ligands,
    )
    assert lig_record.state is not None
    conformer = generate_ligand_conformer(
        ligand_id=lig_record.artifact.ligand_id,
        request=GenerateLigandConformerRequest(
            acknowledge_current_chemical_state=True,
            state_id=lig_record.state.state_id,
        ),
        store=ligands,
    )
    pdbqt_record = prepare_ligand_pdbqt(
        ligand_id=lig_record.artifact.ligand_id,
        conformer_id=conformer.artifact.conformer_id,
        request=PrepareLigandPdbqtRequest(),
        store=ligands,
    )
    assert "SA" not in pdbqt_record.atom_types

    map_service = AutoGridMapService(
        map_store=AutoGridMapStore(tmp_path),
        receptor_store=receptors,
        binding_site_store=sites,
        ligand_store=ligands,
    )
    map_set = map_service.ensure_map_set(
        AutoGridMapSetRequest(
            receptor_id=receptor.receptor_id,
            binding_site_id=site_id,
            source=AutoGridLigandSource.LIGAND_PREPARATION,
            ligand_id=lig_record.artifact.ligand_id,
            ligand_preparation_id=pdbqt_record.artifact.preparation_id,
        )
    ).record
    assert "SA" in map_set.preflight.ligand_atom_types

    return {
        "receptor": receptor,
        "prot_text": prot_text,
        "site_id": site_id,
        "ligand_id": lig_record.artifact.ligand_id,
        "prep_id": pdbqt_record.artifact.preparation_id,
        "map_set": map_set,
    }


@pytest.mark.live_engine
def test_live_real_autogrid4_and_autodock4_cpu_flex_end_to_end(tmp_path: Path) -> None:
    try:
        probe_autogrid4()
        probe_autodock4()
    except AnkoraDomainError:
        pytest.skip("Real AutoGrid4 / AutoDock4 binaries are not configured on this host.")

    live = _prepare_live_garymp_project(tmp_path)
    receptor: ReceptorPreparationRecord = live["receptor"]  # type: ignore[assignment]
    map_set: AutoGridMapSetRecord = live["map_set"]  # type: ignore[assignment]
    prot_text: str = live["prot_text"]  # type: ignore[assignment]

    ad4_store = AutoDock4JobStore(tmp_path)
    service = AutoDock4DockingService(
        job_store=ad4_store,
        map_store=AutoGridMapStore(tmp_path),
        ligand_store=LigandArtifactStore(tmp_path),
        receptor_store=ReceptorArtifactStore(tmp_path),
        binding_site_store=BindingSiteArtifactStore(tmp_path),
    )
    try:
        job = service.start(
            AutoDock4DockingRequest(
                receptor_id=receptor.receptor_id,
                binding_site_id=str(live["site_id"]),
                map_set_id=map_set.map_set_id,
                ligand_id=str(live["ligand_id"]),
                ligand_preparation_id=str(live["prep_id"]),
                parameters=AutoDock4DockingParameters(
                    ga_runs=2,
                    ga_population_size=50,
                    ga_energy_evaluations=10_000,
                    ga_generations=5_000,
                    seed_1=42,
                    seed_2=43,
                ),
                acknowledge_inputs_and_scoring=True,
            )
        )
        completed = _wait_for_ad4_job(service, job.job_id)
        assert completed.status is AutoDock4JobStatus.COMPLETED, completed.failure
        assert completed.receptor_flex_mode is ReceptorFlexMode.SIDECHAIN_FLEX
        assert len(completed.runs) == 2

        pose_art = completed.runs[0].artifact
        assert pose_art.pose_flex_sidechains_sha256 is not None
        flex_path = ad4_store.pose_flex_content_path(completed.job_id, pose_art.artifact_id)
        assert flex_path is not None
        materialized = materialize_coupled_receptor_pdb(
            protonated_pdb_text=prot_text,
            pose_flex_sidechains_pdbqt=flex_path.read_text(encoding="utf-8"),
        )
        assert materialized.moved_atom_count >= 14
        Chem = import_module("rdkit.Chem")
        mol = Chem.MolFromPDBBlock(
            materialized.pdb_text, removeHs=False, sanitize=True, proximityBonding=True
        )
        assert mol is not None
    finally:
        service.shutdown()


@pytest.mark.live_engine
def test_live_real_autodock_gpu_flex_end_to_end(tmp_path: Path) -> None:
    try:
        probe_autogrid4()
        gpu_install = probe_autodock_gpu()
    except AnkoraDomainError:
        pytest.skip("Real AutoGrid4 / AutoDock-GPU binaries are not configured on this host.")
    if not gpu_install.device_available:
        pytest.skip("No OpenCL/CUDA device available for live AutoDock-GPU test.")

    live = _prepare_live_garymp_project(tmp_path)
    receptor: ReceptorPreparationRecord = live["receptor"]  # type: ignore[assignment]
    map_set: AutoGridMapSetRecord = live["map_set"]  # type: ignore[assignment]
    prot_text: str = live["prot_text"]  # type: ignore[assignment]

    gpu_store = AutoDockGpuJobStore(tmp_path)
    service = AutoDockGpuDockingService(
        job_store=gpu_store,
        map_store=AutoGridMapStore(tmp_path),
        ligand_store=LigandArtifactStore(tmp_path),
        receptor_store=ReceptorArtifactStore(tmp_path),
        binding_site_store=BindingSiteArtifactStore(tmp_path),
    )
    try:
        job = service.start(
            AutoDockGpuDockingRequest(
                receptor_id=receptor.receptor_id,
                binding_site_id=str(live["site_id"]),
                map_set_id=map_set.map_set_id,
                ligand_id=str(live["ligand_id"]),
                ligand_preparation_id=str(live["prep_id"]),
                parameters=AutoDockGpuDockingParameters(
                    runs=2,
                    population_size=50,
                    energy_evaluations=10_000,
                    heuristics=False,
                    autostop=False,
                    seed_1=42,
                    seed_2=43,
                    seed_3=44,
                ),
                acknowledge_inputs_and_scoring=True,
            )
        )
        completed = _wait_for_gpu_job(service, job.job_id)
        assert completed.status is AutoDockJobStatus.COMPLETED, completed.failure
        assert completed.receptor_flex_mode is ReceptorFlexMode.SIDECHAIN_FLEX
        assert len(completed.runs) == 2

        pose_art = completed.runs[0].artifact
        assert pose_art.pose_flex_sidechains_sha256 is not None
        flex_path = gpu_store.pose_flex_content_path(completed.job_id, pose_art.artifact_id)
        assert flex_path is not None
        materialized = materialize_coupled_receptor_pdb(
            protonated_pdb_text=prot_text,
            pose_flex_sidechains_pdbqt=flex_path.read_text(encoding="utf-8"),
        )
        assert materialized.moved_atom_count >= 14
        Chem = import_module("rdkit.Chem")
        mol = Chem.MolFromPDBBlock(
            materialized.pdb_text, removeHs=False, sanitize=True, proximityBonding=True
        )
        assert mol is not None
    finally:
        service.shutdown()
