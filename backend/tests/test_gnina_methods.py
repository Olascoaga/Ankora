"""The Methods section a GNINA single job's own records support.

Every fixture here is explicitly synthetic. The numbers are chosen to be
distinguishable rather than to resemble any real system, and the two poses
deliberately put the highest CNN score beside the *weakest* minimized energy:
a renderer that confused GNINA's dimensionless ranking with its kcal/mol
estimate would rank these poses the other way round, so the fixture catches
that rather than merely exercising the code.

The properties pinned are the ones a paper depends on: the three score axes
stay three quantities, the engine and its exact recorded search box are
reported precisely, a preparation is described only while its recorded hash
still matches, and anything the record cannot support is a visible gap instead
of a sentence.
"""

from datetime import UTC, datetime
from hashlib import sha256
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient

from ankora_backend.api.app import create_app
from ankora_backend.domain.errors import AnkoraDomainError
from ankora_backend.persistence.gnina_store import GninaJobStore
from ankora_backend.schemas.binding_sites import BindingBox
from ankora_backend.schemas.docking import DockingFailure, DockingJobPhase, DockingJobStatus
from ankora_backend.schemas.gnina import (
    GninaDockingParameters,
    GninaDockingRequest,
    GninaExecutionEvidence,
    GninaJobRecord,
    GninaPoseArtifact,
    GninaPoseResult,
    GninaToolIdentity,
)
from ankora_backend.services.methods_report import MethodsReportService
from ankora_backend.services.result_catalog import ResultCatalogService

RECEPTOR_BYTES = b"synthetic receptor pdbqt"
LIGAND_BYTES = b"synthetic ligand pdbqt"
CONFORMER_BYTES = b"synthetic conformer sdf"
RECEPTOR_SHA = sha256(RECEPTOR_BYTES).hexdigest()
LIGAND_SHA = sha256(LIGAND_BYTES).hexdigest()
CONFORMER_SHA = sha256(CONFORMER_BYTES).hexdigest()
EXECUTABLE_SHA = "a" * 64
RECEPTOR_ARTIFACT = "synthetic-receptor-pdbqt"

# Synthetic: descending CNN score, ascending favourability in kcal/mol.
POSES = ((1, 0.9, 8.0, -4.0), (2, 0.7, 7.0, -9.0))


class _Missing:
    """A store whose records have all been removed."""

    def __getattr__(self, name: str) -> Any:
        def _raise(*_: Any, **__: Any) -> Any:
            raise AnkoraDomainError(
                code="NOT_FOUND",
                stage="test",
                message="gone",
                status_code=404,
            )

        return _raise


def _job(store: GninaJobStore, **overrides: Any) -> GninaJobRecord:
    parameters = overrides.pop("parameters", GninaDockingParameters(compute="cpu"))
    poses = [
        GninaPoseResult(
            mode=mode,
            cnn_score=score,
            cnn_affinity=affinity,
            minimized_affinity_kcal_mol=energy,
            artifact=GninaPoseArtifact(
                artifact_id=f"pose-{mode}",
                mode=mode,
                filename=f"pose_{mode}.pdbqt",
                sha256=sha256(f"synthetic pose {mode}".encode()).hexdigest(),
                size_bytes=len(f"synthetic pose {mode}"),
            ),
        )
        for mode, score, affinity, energy in POSES
    ]
    fields: dict[str, Any] = {
        "job_id": store.new_job_id(),
        "status": DockingJobStatus.COMPLETED,
        "phase": DockingJobPhase.COMPLETE,
        "created_at": datetime.now(UTC),
        "completed_at": datetime.now(UTC),
        "request": GninaDockingRequest(
            receptor_id="synthetic-receptor",
            binding_site_id="synthetic-site",
            ligand_id="synthetic-ligand",
            ligand_preparation_id="synthetic-preparation",
            parameters=parameters,
            acknowledge_inputs_and_scoring=True,
        ),
        "tool": GninaToolIdentity(version="1.3.3", sha256=EXECUTABLE_SHA, architecture="x86_64"),
        "box": BindingBox(center_x=1, center_y=2, center_z=3, size_x=10, size_y=12, size_z=14),
        "receptor_output_artifact_id": RECEPTOR_ARTIFACT,
        "receptor_sha256": RECEPTOR_SHA,
        "ligand_sha256": LIGAND_SHA,
        "conformer_sha256": CONFORMER_SHA,
        "execution": GninaExecutionEvidence(
            command=["synthetic-gnina"], exit_code=0, stdout="", stderr=""
        ),
        "poses": poses,
    }
    fields.update(overrides)
    return GninaJobRecord(**fields)


def _receptor(sha: str = RECEPTOR_SHA, artifact_id: str = RECEPTOR_ARTIFACT) -> Any:
    return SimpleNamespace(
        source_artifact_id="synthetic-source",
        decisions=SimpleNamespace(
            selected_chains=["A"],
            water_action="remove",
            component_decisions=[],
            relaxation=SimpleNamespace(enabled=False),
        ),
        outputs=[SimpleNamespace(artifact_id=artifact_id, sha256=sha)],
        provenance=[
            SimpleNamespace(
                event_type="receptor_protonated",
                tool=SimpleNamespace(name="PDB2PQR/PROPKA", version="pdb2pqr 3.7.1"),
                parameters={"ph": 7.4, "force_field": "AMBER"},
            ),
            SimpleNamespace(
                event_type="receptor_pdbqt_generated",
                tool=SimpleNamespace(name="Meeko", version="0.7.1"),
                parameters={},
            ),
        ],
    )


class _Ligands:
    """The one preparation this job names, with controllable recorded hashes."""

    def __init__(self, pdbqt_sha: str = LIGAND_SHA, conformer_sha: str = CONFORMER_SHA) -> None:
        self._pdbqt_sha = pdbqt_sha
        self._conformer_sha = conformer_sha

    def load_pdbqt_record(self, ligand_id: str, preparation_id: str) -> Any:
        assert (ligand_id, preparation_id) == ("synthetic-ligand", "synthetic-preparation")
        return SimpleNamespace(
            artifact=SimpleNamespace(
                ligand_id=ligand_id,
                conformer_id="synthetic-conformer",
                sha256=self._pdbqt_sha,
            ),
            charge_model="gasteiger",
            tool=SimpleNamespace(name="Meeko", version="0.7.1"),
        )

    def load_conformer_record(self, ligand_id: str, conformer_id: str) -> Any:
        assert (ligand_id, conformer_id) == ("synthetic-ligand", "synthetic-conformer")
        return SimpleNamespace(
            artifact=SimpleNamespace(sha256=self._conformer_sha),
            minimization=SimpleNamespace(
                embedding_method="ETKDGv3",
                force_field="MMFF94s",
                max_iterations=500,
                random_seed=20260819,
                conformer_pool_size=20,
                independent_from_source_coordinates=True,
            ),
            provenance=SimpleNamespace(
                input_artifacts=["synthetic-state"],
                tool=SimpleNamespace(name="RDKit ETKDG/MMFF", version="2025.09.6"),
            ),
        )

    def load_record(self, ligand_id: str) -> Any:
        return SimpleNamespace(state=SimpleNamespace(state_id="synthetic-state"))


def _structures() -> Any:
    """A local synthetic source file, so no real PDB entry is implied."""
    return SimpleNamespace(
        load_record=lambda _: SimpleNamespace(
            metadata=SimpleNamespace(entry_id=None, resolution_angstrom=None),
            artifact=SimpleNamespace(source="file", original_filename="synthetic_receptor.pdb"),
        )
    )


def _site(box: BindingBox | None = None) -> Any:
    return SimpleNamespace(
        binding_site_id="synthetic-site",
        receptor_id="synthetic-receptor",
        box=box or BindingBox(center_x=1, center_y=2, center_z=3, size_x=10, size_y=12, size_z=14),
        decisions=SimpleNamespace(
            source="co_crystallized_ligand",
            pocket_selection=None,
            parent_binding_site_id=None,
            residue_selection=None,
            ligand_origin=SimpleNamespace(
                heterogen=SimpleNamespace(residue_name="SYN", chain_id="A", sequence_number=401),
                padding_angstrom=4.0,
            ),
        ),
    )


def _render(
    tmp_path: Any,
    monkeypatch: Any,
    *,
    job_overrides: dict[str, Any] | None = None,
    receptors: Any = None,
    ligands: Any = None,
    binding_sites: Any = None,
    structures: Any = None,
    tampered_bytes: str | None = None,
) -> Any:
    """Render through the real catalog, store and job record."""
    monkeypatch.setenv("ANKORA_DATA_DIR", str(tmp_path))
    store = GninaJobStore.from_environment()
    job = _job(store, **(job_overrides or {}))
    store.create_job(job)
    paths = {}
    for name, contents in (
        ("receptor", RECEPTOR_BYTES),
        ("ligand", LIGAND_BYTES),
        ("conformer", CONFORMER_BYTES),
    ):
        path = tmp_path / f"synthetic-{name}"
        path.write_bytes(b"altered synthetic content" if tampered_bytes == name else contents)
        paths[name] = path
    receptor_store = (
        receptors if receptors is not None else SimpleNamespace(load_record=lambda _: _receptor())
    )
    if isinstance(receptor_store, SimpleNamespace):
        receptor_store.content_path = lambda *_: paths["receptor"]
    ligand_store = ligands if ligands is not None else _Ligands()
    if isinstance(ligand_store, _Ligands):
        ligand_store.pdbqt_content_path = lambda *_: paths["ligand"]
        ligand_store.conformer_content_path = lambda *_: paths["conformer"]
    service = MethodsReportService(
        catalog=ResultCatalogService.from_environment(),
        structures=structures if structures is not None else _structures(),  # type: ignore[arg-type]
        receptors=receptor_store,  # type: ignore[arg-type]
        binding_sites=binding_sites
        if binding_sites is not None
        else SimpleNamespace(  # type: ignore[arg-type]
            load_record=lambda _: _site()
        ),
        pockets=_Missing(),  # type: ignore[arg-type]
        ligands=ligand_store,  # type: ignore[arg-type]
        maps=_Missing(),  # type: ignore[arg-type]
        docking=_Missing(),  # type: ignore[arg-type]
        autodock4=_Missing(),  # type: ignore[arg-type]
        autodock_gpu=_Missing(),  # type: ignore[arg-type]
        gnina=store,
    )
    return service.render(f"gnina_job:{job.job_id}"), job


def test_gnina_methods_keeps_the_three_score_axes_apart(tmp_path, monkeypatch) -> None:
    report, _ = _render(tmp_path, monkeypatch)

    assert "descending CNN pose score" in report.markdown
    assert "dimensionless and bounded between 0 and 1" in report.markdown
    assert "not an energy and has no kcal/mol interpretation" in report.markdown
    # Each axis named with its own unit, and the top pose's three values given.
    assert "CNN affinity prediction, in pK units" in report.markdown
    assert "minimized affinity from GNINA's empirical scoring function, in kcal mol⁻¹" in (
        report.markdown
    )
    assert "CNN pose score of 0.9" in report.markdown
    assert "predicted CNN affinity of 8 pK" in report.markdown
    assert "minimized affinity of -4 kcal mol⁻¹" in report.markdown
    # The fixture's best-ranked pose is the worst energy, so this must be said.
    assert "not necessarily the one with the lowest recorded energy" in report.markdown


def test_gnina_methods_claims_no_measurement_and_no_cross_engine_scale(
    tmp_path, monkeypatch
) -> None:
    report, _ = _render(tmp_path, monkeypatch)

    assert "None is a measured binding affinity" in report.markdown
    assert "none is evidence of biological activity" in report.markdown
    assert "do not share a scale with the score of any other docking engine" in report.markdown
    assert "does not pool or jointly rank results across engines" in report.markdown
    lowered = report.markdown.lower()
    assert "measured affinity of" not in lowered
    assert "experimentally" not in lowered
    assert "validated" not in lowered


def test_gnina_methods_records_engine_identity_and_the_exact_recorded_box(
    tmp_path, monkeypatch
) -> None:
    report, job = _render(tmp_path, monkeypatch)

    assert f"GNINA {job.tool.version}" in report.markdown
    assert "native x86_64 Linux build" in report.markdown
    assert f"executable SHA-256 {EXECUTABLE_SHA}" in report.markdown
    assert "fixed random seed of 20261029" in report.markdown
    assert "exhaustiveness of 8" in report.markdown
    assert "at most 9 binding modes" in report.markdown
    assert "minimum inter-mode RMSD filter of 1 Å" in report.markdown
    assert "scoring mode `rescore`" in report.markdown
    assert "built-in `dense_1_3` model" in report.markdown
    # The box comes from the run's own record, not from the site artifact.
    assert "centred at (1.0, 2.0, 3.0) Å" in report.markdown
    assert "dimensions 10.0 × 12.0 × 14.0 Å" in report.markdown
    assert "taken from the run's own record" in report.markdown
    assert any(tool.name == "GNINA" and tool.version == "1.3.3" for tool in report.software)


def test_gnina_methods_states_the_prepared_pdbqt_hydrogen_policy(tmp_path, monkeypatch) -> None:
    report, _ = _render(tmp_path, monkeypatch)

    assert "independently prepared PDBQT files" in report.markdown
    assert "hydrogen addition and hydrogen stripping disabled" in report.markdown
    assert "neither added nor removed hydrogens" in report.markdown
    assert "protonation those inputs carry is the one recorded" in report.markdown


def test_gnina_methods_reports_cpu_policy_without_implying_a_fallback(
    tmp_path, monkeypatch
) -> None:
    report, _ = _render(tmp_path, monkeypatch)

    assert "executed on the CPU with 2 threads" in report.markdown
    assert "GPU execution explicitly disabled" in report.markdown
    assert "never falls back between compute devices" in report.markdown
    assert "GPU" in report.markdown and "neural-network operation" not in report.markdown


def test_gnina_methods_bounds_what_a_gpu_observation_proves(tmp_path, monkeypatch) -> None:
    report, _ = _render(
        tmp_path,
        monkeypatch,
        job_overrides={
            "parameters": GninaDockingParameters(compute="cuda", device_index=0),
            "execution": GninaExecutionEvidence(
                command=["synthetic-gnina"],
                exit_code=0,
                stdout="",
                stderr="",
                gpu_process_observed=True,
                gpu_observation="synthetic observation",
                requested_gpu_uuid="GPU-synthetic-0",
                observed_gpu_uuid="GPU-synthetic-0",
            ),
        },
    )

    assert "requested on CUDA logical device 0" in report.markdown
    assert "never falls back from a requested GPU to the CPU" in report.markdown
    assert "observed the GNINA process occupying GPU GPU-synthetic-0" in report.markdown
    assert "the device requested for this run" in report.markdown
    # The honest bound on what nvidia-smi observation establishes.
    assert "not independent proof that every neural-network operation" in report.markdown


def test_gnina_methods_marks_an_unobserved_cuda_run_as_a_gap(tmp_path, monkeypatch) -> None:
    # A completed CUDA record cannot exist without observation, but a canceled
    # one can, and the section must not imply the GPU was confirmed.
    report, _ = _render(
        tmp_path,
        monkeypatch,
        job_overrides={
            "parameters": GninaDockingParameters(compute="cuda"),
            "status": DockingJobStatus.CANCELED,
            "poses": [],
            "execution": GninaExecutionEvidence(
                command=["synthetic-gnina"], exit_code=0, stdout="", stderr="", canceled=True
            ),
        },
    )

    assert "recorded GNINA GPU process observation" in report.gaps
    assert "observed the GNINA process occupying" not in report.markdown


def test_gnina_methods_describes_preparations_only_while_hashes_match(
    tmp_path, monkeypatch
) -> None:
    report, _ = _render(tmp_path, monkeypatch)

    assert f"prepared PDBQT identified by SHA-256 {RECEPTOR_SHA}" in report.markdown
    assert "still matches the stored artifact" in report.markdown
    assert "Protonation states were assigned at pH 7.4" in report.markdown
    assert f"still match the hashes GNINA recorded ({LIGAND_SHA} and {CONFORMER_SHA})" in (
        report.markdown
    )
    assert "The selected ligand was converted" in report.markdown
    assert "ETKDGv3" in report.markdown and "MMFF94s" in report.markdown
    assert "Gasteiger partial charges" in report.markdown
    # The policy's explicit negatives still apply to a single GNINA ligand.
    assert "No pH-based ligand protonation enumeration was recorded" in report.markdown
    assert "No ligand tautomer enumeration was recorded" in report.markdown
    assert report.gaps == []


@pytest.mark.parametrize(
    ("tampered", "expected_gap", "absent"),
    [
        (
            "receptor",
            "a prepared receptor whose stored bytes still match the hash GNINA recorded",
            "Protonation states were assigned",
        ),
        (
            "ligand",
            "a prepared ligand whose stored bytes still match the hash GNINA recorded",
            "The selected ligand was converted",
        ),
        (
            "conformer",
            "a conformer whose stored bytes still match the hash GNINA recorded",
            "The selected ligand was converted",
        ),
    ],
)
def test_gnina_methods_refuses_a_preparation_whose_artifact_changed(
    tmp_path, monkeypatch, tampered: str, expected_gap: str, absent: str
) -> None:
    """A receptor prepared again since the run is a different receptor.

    Describing it would put a protocol in the Methods section that did not
    produce these numbers, which is the one failure this renderer exists to
    prevent.
    """
    report, _ = _render(
        tmp_path,
        monkeypatch,
        receptors=SimpleNamespace(load_record=lambda _: _receptor(sha="f" * 64))
        if tampered == "receptor"
        else None,
        ligands=_Ligands(pdbqt_sha="f" * 64)
        if tampered == "ligand"
        else (_Ligands(conformer_sha="f" * 64) if tampered == "conformer" else None),
    )

    assert expected_gap in report.gaps
    assert f"[not recorded: {expected_gap}]" in report.markdown
    assert absent not in report.markdown
    # The run itself is still described; only the preparation is withheld.
    assert "GNINA 1.3.3" in report.markdown
    assert "CNN pose score of 0.9" in report.markdown


@pytest.mark.parametrize("artifact", ["receptor", "ligand", "conformer"])
def test_gnina_methods_checks_actual_input_bytes(tmp_path, monkeypatch, artifact):
    report, _ = _render(tmp_path, monkeypatch, tampered_bytes=artifact)
    assert any("stored bytes still match" in gap for gap in report.gaps)
    if artifact == "receptor":
        assert "Protonation states were assigned" not in report.markdown
    else:
        assert "The selected ligand was converted" not in report.markdown


@pytest.mark.parametrize("status", [DockingJobStatus.QUEUED, DockingJobStatus.FAILED])
def test_unfinished_gnina_is_described_as_configuration(tmp_path, monkeypatch, status):
    report, _ = _render(
        tmp_path,
        monkeypatch,
        job_overrides={
            "status": status,
            "poses": [],
            "execution": None,
            "completed_at": None,
        },
    )
    assert "configured" in report.markdown
    assert "Docking was performed" not in report.markdown
    assert "A single ligand was docked" not in report.markdown
    assert "The search used" not in report.markdown


def test_gnina_methods_reports_a_missing_receptor_artifact_as_its_own_gap(
    tmp_path, monkeypatch
) -> None:
    report, _ = _render(
        tmp_path,
        monkeypatch,
        receptors=SimpleNamespace(load_record=lambda _: _receptor(artifact_id="other")),
    )

    assert "the prepared receptor artifact GNINA was given, in the receptor record" in report.gaps
    assert "Protonation states were assigned" not in report.markdown


def test_gnina_methods_reports_removed_records_as_holes_not_prose(tmp_path, monkeypatch) -> None:
    report, _ = _render(
        tmp_path,
        monkeypatch,
        receptors=_Missing(),
        ligands=_Missing(),
        binding_sites=_Missing(),
    )

    assert "the receptor preparation record for this GNINA job" in report.gaps
    assert "the prepared ligand record for this GNINA job" in report.gaps
    assert "the binding site record for this GNINA job" in report.gaps
    # Nothing was invented to fill them.
    assert "pH" not in report.markdown
    assert "ETKDGv3" not in report.markdown
    assert "co-crystallized ligand" not in report.markdown
    # The box is on the job record, so it survives the loss of the site record.
    assert "centred at (1.0, 2.0, 3.0) Å" in report.markdown


def test_gnina_methods_ignores_a_binding_site_that_no_longer_matches(tmp_path, monkeypatch) -> None:
    """Two records can name the same pocket; the box says whether they agree."""
    moved = BindingBox(center_x=9, center_y=9, center_z=9, size_x=10, size_y=12, size_z=14)
    report, _ = _render(
        tmp_path,
        monkeypatch,
        binding_sites=SimpleNamespace(load_record=lambda _: _site(box=moved)),
    )

    assert "a binding site record consistent with the recorded GNINA box" in report.gaps
    assert "SYN A:401" not in report.markdown
    assert "centred at (1.0, 2.0, 3.0) Å" in report.markdown
    assert "9.00" not in report.markdown


def test_gnina_methods_publishes_no_score_for_a_failed_job(tmp_path, monkeypatch) -> None:
    report, _ = _render(
        tmp_path,
        monkeypatch,
        job_overrides={
            "status": DockingJobStatus.FAILED,
            "poses": [],
            "execution": GninaExecutionEvidence(
                command=["synthetic-gnina"], exit_code=1, stdout="", stderr="synthetic failure"
            ),
            "failure": DockingFailure(
                code="GNINA_EXECUTION_FAILED",
                message="GNINA did not complete successfully.",
                details={"exit_code": 1},
            ),
        },
    )

    assert "did not complete; its recorded status is `failed`" in report.markdown
    assert "no poses were published for it" in report.markdown
    assert "GNINA_EXECUTION_FAILED" in report.markdown
    assert "No CNN score, affinity prediction or pose is reported" in report.markdown
    # Not one number from the score axes may appear for a job that produced none.
    assert "CNN pose score of" not in report.markdown
    assert "predicted CNN affinity of" not in report.markdown
    assert "kcal mol⁻¹" not in report.markdown


def test_gnina_methods_never_borrows_another_engine_procedure(tmp_path, monkeypatch) -> None:
    """Regression: GNINA prose must not be written by the Vina or AutoDock4 path.

    Those branches describe a Lamarckian genetic algorithm, AutoGrid map
    precomputation, Vina energy ranges and AutoDock clustering. None of them
    happened here, and a Methods section that claimed one would describe a
    procedure the campaign never ran.
    """
    report, _ = _render(tmp_path, monkeypatch)

    for claim in (
        "Lamarckian",
        "genetic algorithm",
        "AutoGrid",
        "affinity grid maps",
        "energy evaluations",
        "clustered by AutoDock",
        "energy range",
        "Vina sampling purpose",
        "local search",
        "Compounds are ranked by their best",
    ):
        assert claim not in report.markdown, claim
    assert not any(
        tool.name in {"AutoDock Vina", "AutoDock4", "AutoGrid", "AutoDock-GPU"}
        for tool in report.software
    )


def test_gnina_repeat_behavior_is_not_inferred_from_a_recorded_seed(tmp_path, monkeypatch) -> None:
    report, _ = _render(tmp_path, monkeypatch)

    assert "Repeat reproducibility was not assessed" in report.markdown
    assert "do not establish that its outputs will match" in report.markdown
    assert "were identical" not in report.markdown


def test_every_gnina_gap_is_marked_in_the_text(tmp_path, monkeypatch) -> None:
    """A hole counted but not shown, or shown but not counted, is a trap."""
    report, _ = _render(
        tmp_path, monkeypatch, receptors=_Missing(), ligands=_Missing(), binding_sites=_Missing()
    )

    for gap in report.gaps:
        assert f"[not recorded: {gap}]" in report.markdown
    assert report.markdown.count("[not recorded:") == len(report.gaps)


def test_gnina_methods_describes_nothing_without_the_job_record(tmp_path, monkeypatch) -> None:
    """The catalog can still hold an entry whose job record has gone.

    Every section depends on that record, so each must report its own hole
    rather than fall back on the entry's summary fields.
    """
    monkeypatch.setenv("ANKORA_DATA_DIR", str(tmp_path))
    store = GninaJobStore.from_environment()
    job = _job(store)
    store.create_job(job)
    service = MethodsReportService(
        catalog=ResultCatalogService.from_environment(),
        structures=_structures(),  # type: ignore[arg-type]
        receptors=SimpleNamespace(load_record=lambda _: _receptor()),  # type: ignore[arg-type]
        binding_sites=SimpleNamespace(load_record=lambda _: _site()),  # type: ignore[arg-type]
        pockets=_Missing(),  # type: ignore[arg-type]
        ligands=_Ligands(),  # type: ignore[arg-type]
        maps=_Missing(),  # type: ignore[arg-type]
        docking=_Missing(),  # type: ignore[arg-type]
        autodock4=_Missing(),  # type: ignore[arg-type]
        autodock_gpu=_Missing(),  # type: ignore[arg-type]
        gnina=None,
    )

    report = service.render(f"gnina_job:{job.job_id}")

    assert "the GNINA job record" in report.gaps
    assert "the recorded GNINA search box" in report.gaps
    assert "the GNINA request parameters" in report.gaps
    assert "the recorded GNINA outcome" in report.gaps
    # Not one number survives the loss of the record that held them.
    assert "CNN pose score of" not in report.markdown
    assert "SHA-256" not in report.markdown
    assert "centred at" not in report.markdown
    assert "Protonation states were assigned" not in report.markdown
    for gap in report.gaps:
        assert f"[not recorded: {gap}]" in report.markdown
    assert report.markdown.count("[not recorded:") == len(report.gaps)


def test_gnina_methods_route_renders_the_recorded_job(tmp_path, monkeypatch) -> None:
    """The route now answers for GNINA, from the project-scoped store."""
    monkeypatch.setenv("ANKORA_DATA_DIR", str(tmp_path))
    store = GninaJobStore.from_environment()
    job = _job(store)
    store.create_job(job)

    with TestClient(create_app()) as client:
        response = client.get(f"/api/v1/results/campaigns/gnina_job/{job.job_id}/methods")

        assert response.status_code == 200
        payload = response.json()
        assert payload["engine_label"] == "GNINA 1.3.3"
        assert f"executable SHA-256 {EXECUTABLE_SHA}" in payload["markdown"]
        assert "descending CNN pose score" in payload["markdown"]
        assert "centred at (1.0, 2.0, 3.0) Å" in payload["markdown"]
        # This project holds no receptor or ligand records, so the preparations
        # are gaps rather than invented prose.
        assert payload["gaps"]
        for gap in payload["gaps"]:
            assert f"[not recorded: {gap}]" in payload["markdown"]


def test_gnina_methods_does_not_cross_project_boundaries(tmp_path, monkeypatch) -> None:
    """A job recorded in one project is not readable from another.

    The Methods service resolves its GNINA store per request, so a project
    switch must change which records exist rather than widen the view.
    """
    monkeypatch.setenv("ANKORA_DATA_DIR", str(tmp_path))
    store = GninaJobStore.from_environment()
    job = _job(store)
    store.create_job(job)

    with TestClient(create_app()) as client:
        assert (
            client.get(f"/api/v1/results/campaigns/gnina_job/{job.job_id}/methods").status_code
            == 200
        )

        created = client.post("/api/v1/projects", json={"name": "Synthetic other project"})
        assert created.status_code == 201
        other = created.json()["project_id"]
        assert client.post(f"/api/v1/projects/{other}/activate").status_code == 200

        # Same identifier, different project: the record is simply not there.
        assert (
            client.get(f"/api/v1/results/campaigns/gnina_job/{job.job_id}/methods").status_code
            == 404
        )
        assert client.get("/api/v1/results/campaigns?scoring_family=gnina").json()["total"] == 0


def test_gnina_methods_route_refuses_an_unknown_job(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ANKORA_DATA_DIR", str(tmp_path))

    with TestClient(create_app()) as client:
        response = client.get(
            "/api/v1/results/campaigns/gnina_job/00000000-0000-4000-8000-000000000000/methods"
        )

        assert response.status_code == 404


def test_gnina_methods_cites_crossref_verified_gnina_publication(tmp_path, monkeypatch) -> None:
    """GNINA 1.0 DOI metadata verified against Crossref renders in Software and References."""
    report, _ = _render(tmp_path, monkeypatch)

    assert "## Software" in report.markdown
    assert "## References" in report.markdown
    assert "| GNINA | 1.3.3 | molecular docking |" in report.markdown
    assert "| GNINA | 1.3.3 | molecular docking | none recorded |" not in report.markdown
    assert "Ankora holds no verified published reference for GNINA" not in report.markdown
    assert (
        "McNutt AT, Francoeur P, Aggarwal R, Masuda T, Meli R, Ragoza M, Sunseri J, Koes DR. "
        "GNINA 1.0: molecular docking with deep learning. Journal of Cheminformatics. "
        "2021;13(1):43. doi:10.1186/s13321-021-00522-2"
    ) in report.markdown


def _screening_campaign_fixture(
    tmp_path,
    monkeypatch,
    *,
    tampered: str | None = None,
):
    import json

    from ankora_backend.persistence.gnina_screening_store import GninaScreeningStore
    from ankora_backend.schemas.gnina_screening import (
        GninaScreeningCampaignRecord,
        GninaScreeningEntry,
        GninaScreeningPreflightCode,
        GninaScreeningRequest,
        GninaScreeningSelection,
    )
    from ankora_backend.schemas.ligands import (
        LigandFilterDisposition,
        LigandLibraryFilterPlan,
        LigandMicrostatePlan,
    )

    monkeypatch.setenv("ANKORA_DATA_DIR", str(tmp_path))
    job_store = GninaJobStore.from_environment()
    screening_store = GninaScreeningStore.from_environment()
    now = datetime(2026, 8, 26, 21, 0, tzinfo=UTC)

    receptor_file = tmp_path / "receptor.pdbqt"
    ligand_a_file = tmp_path / "ligand_a.pdbqt"
    ligand_b_file = tmp_path / "ligand_b.pdbqt"
    conformer_a_file = tmp_path / "conformer_a.sdf"
    conformer_b_file = tmp_path / "conformer_b.sdf"
    receptor_file.write_bytes(RECEPTOR_BYTES)
    ligand_a_file.write_bytes(b"synthetic ligand A pdbqt")
    ligand_b_file.write_bytes(b"synthetic ligand B pdbqt")
    conformer_a_file.write_bytes(b"synthetic conformer A sdf")
    conformer_b_file.write_bytes(b"synthetic conformer B sdf")

    sha_lig_a = sha256(ligand_a_file.read_bytes()).hexdigest()
    sha_lig_b = sha256(ligand_b_file.read_bytes()).hexdigest()
    sha_conf_a = sha256(conformer_a_file.read_bytes()).hexdigest()
    sha_conf_b = sha256(conformer_b_file.read_bytes()).hexdigest()

    campaign_id = screening_store.new_campaign_id()
    parameters = GninaDockingParameters(compute="cuda", device_index=0)
    request = GninaScreeningRequest(
        receptor_id="synthetic-receptor",
        binding_site_id="synthetic-site",
        library_id="synthetic-library",
        filter_run_id="synthetic-filter",
        parameters=parameters,
        acknowledge_inputs_and_scoring=True,
    )

    def _make_child(
        ligand_id: str,
        prep_id: str,
        lig_bytes: bytes,
        lig_sha: str,
        conf_bytes: bytes,
        conf_sha: str,
        *,
        cnn_score: float,
        cnn_affinity: float,
        energy: float,
    ) -> GninaJobRecord:
        pose_bytes = f"synthetic pose for {ligand_id}".encode()
        job = _job(
            job_store,
            screening_campaign_id=campaign_id,
            parameters=parameters,
            request=GninaDockingRequest(
                receptor_id="synthetic-receptor",
                binding_site_id="synthetic-site",
                ligand_id=ligand_id,
                ligand_preparation_id=prep_id,
                parameters=parameters,
                acknowledge_inputs_and_scoring=True,
            ),
            ligand_sha256=lig_sha,
            conformer_sha256=conf_sha,
            execution=GninaExecutionEvidence(
                command=["synthetic-gnina"],
                exit_code=0,
                stdout="",
                stderr="",
                gpu_process_observed=True,
                gpu_observation="synthetic nvidia-smi",
                requested_gpu_uuid="GPU-synthetic-0",
                observed_gpu_uuid="GPU-synthetic-0",
            ),
            poses=[
                GninaPoseResult(
                    mode=1,
                    cnn_score=cnn_score,
                    cnn_affinity=cnn_affinity,
                    minimized_affinity_kcal_mol=energy,
                    artifact=GninaPoseArtifact(
                        artifact_id="pose-1",
                        mode=1,
                        filename="pose_1.pdbqt",
                        sha256=sha256(pose_bytes).hexdigest(),
                        size_bytes=len(pose_bytes),
                    ),
                )
            ],
        )
        job_store.create_job(job)
        job_store.write_artifact(job.job_id, "receptor.pdbqt", RECEPTOR_BYTES)
        job_store.write_artifact(job.job_id, "ligand.pdbqt", lig_bytes)
        job_store.write_artifact(job.job_id, "conformer.sdf", conf_bytes)
        job_store.write_artifact(job.job_id, "pose_1.pdbqt", pose_bytes)
        return job

    # Deliberately opposite order between CNNscore and kcal/mol energy:
    # Synthetic Alpha has weaker CNNscore (0.71) and stronger energy (-9.4);
    # Synthetic Beta has stronger CNNscore (0.94) and weaker energy (-4.2).
    job_a = _make_child(
        "synthetic-lig-a",
        "prep-a",
        ligand_a_file.read_bytes(),
        sha_lig_a,
        conformer_a_file.read_bytes(),
        sha_conf_a,
        cnn_score=0.71,
        cnn_affinity=6.8,
        energy=-9.4,
    )
    job_b = _make_child(
        "synthetic-lig-b",
        "prep-b",
        ligand_b_file.read_bytes(),
        sha_lig_b,
        conformer_b_file.read_bytes(),
        sha_conf_b,
        cnn_score=0.94,
        cnn_affinity=8.3,
        energy=-4.2,
    )

    entries = [
        GninaScreeningEntry(
            ligand_id="synthetic-lig-a",
            chemical_state_id="state-a",
            source_index=0,
            name="Synthetic Alpha",
            ligand_preparation_id="prep-a",
            conformer_id="conf-a",
            ligand_sha256=sha_lig_a,
            conformer_sha256=sha_conf_a,
            status=DockingJobStatus.QUEUED,
            phase=DockingJobPhase.QUEUED,
        ),
        GninaScreeningEntry(
            ligand_id="synthetic-lig-b",
            chemical_state_id="state-b",
            source_index=1,
            name="Synthetic Beta",
            ligand_preparation_id="prep-b",
            conformer_id="conf-b",
            ligand_sha256=sha_lig_b,
            conformer_sha256=sha_conf_b,
            status=DockingJobStatus.QUEUED,
            phase=DockingJobPhase.QUEUED,
        ),
        GninaScreeningEntry(
            ligand_id="synthetic-lig-c",
            chemical_state_id="state-c",
            source_index=2,
            name="Synthetic Unprepared",
            status=DockingJobStatus.FAILED,
            phase=DockingJobPhase.COMPLETE,
            completed_at=now,
            failure=DockingFailure(
                code=GninaScreeningPreflightCode.LIGAND_NOT_PREPARED,
                message="Synthetic preflight refusal.",
            ),
        ),
    ]

    plan = LigandLibraryFilterPlan()
    microstate_plan = LigandMicrostatePlan()
    summary_dict = {
        "imported_count": 4,
        "eligible_count": 3,
        "excluded_count": 1,
        "needs_decision_count": 0,
        "pains_match_count": 0,
        "brenk_match_count": 0,
        "duplicate_count": 0,
    }
    eval_dicts = [
        {
            "ligand_id": item.ligand_id,
            "state_id": item.chemical_state_id,
            "record_index": item.source_index,
            "disposition": LigandFilterDisposition.ELIGIBLE.value,
        }
        for item in entries
    ]
    manifest_payload = {
        "filter_run_id": "synthetic-filter",
        "library_id": "synthetic-library",
        "created_at": now.isoformat(),
        "rdkit_version": "2025.09.6",
        "worker_count": 1,
        "plan": plan.model_dump(mode="json"),
        "microstate_plan": microstate_plan.model_dump(mode="json"),
        "summary": summary_dict,
        "selected_ligand_ids": [item.ligand_id for item in entries],
        "evaluations": eval_dicts,
    }
    manifest_file = tmp_path / "filter_manifest.json"
    manifest_bytes = json.dumps(manifest_payload).encode("utf-8")
    manifest_file.write_bytes(manifest_bytes)
    manifest_sha = sha256(manifest_bytes).hexdigest()

    filter_run_record = SimpleNamespace(
        artifact=SimpleNamespace(
            library_id="synthetic-library",
            filter_run_id="synthetic-filter",
            created_at=now,
            size_bytes=len(manifest_bytes),
            sha256=manifest_sha,
        ),
        rdkit_version="2025.09.6",
        worker_count=1,
        plan=plan,
        microstate_plan=microstate_plan,
        summary=SimpleNamespace(
            **summary_dict,
            model_dump=lambda mode="json": dict(summary_dict),
        ),
        selected_ligand_ids=[item.ligand_id for item in entries],
        evaluations=[
            SimpleNamespace(
                ligand_id=item["ligand_id"],
                state_id=item["state_id"],
                record_index=item["record_index"],
                disposition=LigandFilterDisposition.ELIGIBLE,
                model_dump=lambda mode="json", row=item: dict(row),
            )
            for item in eval_dicts
        ],
    )

    campaign = GninaScreeningCampaignRecord(
        campaign_id=campaign_id,
        status=DockingJobStatus.QUEUED,
        phase=DockingJobPhase.QUEUED,
        created_at=now,
        request=request,
        tool=job_a.tool,
        selection=GninaScreeningSelection(
            library_id="synthetic-library",
            filter_run_id="synthetic-filter",
            manifest_artifact_id="synthetic-filter",
            manifest_sha256=manifest_sha,
        ),
        receptor_output_artifact_id=RECEPTOR_ARTIFACT,
        receptor_sha256=RECEPTOR_SHA,
        box=job_a.box,
        selected_count=3,
        completed_count=1,
        failed_count=1,
        entries=entries,
    )

    monkeypatch.setattr(
        "ankora_backend.persistence.gnina_screening_store.verified_screening_selection",
        lambda **_kwargs: filter_run_record,
    )
    monkeypatch.setattr(
        GninaScreeningStore,
        "_verify_entry_preparation",
        lambda *_args, **_kwargs: None,
    )
    screening_store.create_campaign(campaign)
    for lig_id, child_job in (("synthetic-lig-a", job_a), ("synthetic-lig-b", job_b)):
        stored = screening_store.load_entry(campaign_id, lig_id)
        assert stored is not None
        running = screening_store.update_entry(
            campaign_id,
            stored.model_copy(
                update={
                    "status": DockingJobStatus.RUNNING,
                    "phase": DockingJobPhase.DOCKING,
                    "gnina_job_id": child_job.job_id,
                    "started_at": now,
                }
            ),
        )
        screening_store.update_entry(
            campaign_id,
            running.model_copy(
                update={
                    "status": DockingJobStatus.COMPLETED,
                    "phase": DockingJobPhase.COMPLETE,
                    "completed_at": now,
                }
            ),
        )
    screening_store.finalize_campaign(campaign_id)

    if tampered == "receptor":
        receptor_file.write_bytes(b"tampered upstream receptor")
    elif tampered == "selection":
        manifest_file.write_bytes(b'{"tampered": true}')
    elif tampered == "ligand":
        ligand_b_file.write_bytes(b"tampered upstream ligand")
    elif tampered == "conformer":
        conformer_b_file.write_bytes(b"tampered upstream conformer")

    pdbqt_paths = {"prep-a": ligand_a_file, "prep-b": ligand_b_file}
    conf_paths = {"conf-a": conformer_a_file, "conf-b": conformer_b_file}
    pdbqt_shas = {"prep-a": sha_lig_a, "prep-b": sha_lig_b}
    conf_shas = {"conf-a": sha_conf_a, "conf-b": sha_conf_b}
    conf_ids = {"prep-a": "conf-a", "prep-b": "conf-b"}

    ligand_stub = SimpleNamespace(
        load_library_record=lambda _lib_id: SimpleNamespace(
            artifact=SimpleNamespace(
                record_count=4,
                filename="synthetic_lib.sdf",
                format="sdf",
            ),
            imported_count=4,
            failed_count=0,
        ),
        load_filter_run=lambda _lib_id, _run_id: filter_run_record,
        filter_run_content_path=lambda _lib_id, _run_id: manifest_file,
        load_pdbqt_record=lambda lig_id, prep_id: SimpleNamespace(
            artifact=SimpleNamespace(
                ligand_id=lig_id,
                conformer_id=conf_ids[prep_id],
                sha256=pdbqt_shas[prep_id],
            ),
            charge_model="gasteiger",
            tool=SimpleNamespace(name="Meeko", version="0.7.1"),
        ),
        pdbqt_content_path=lambda _lig_id, prep_id: pdbqt_paths[prep_id],
        load_conformer_record=lambda _lig_id, conf_id: SimpleNamespace(
            artifact=SimpleNamespace(sha256=conf_shas[conf_id]),
            minimization=SimpleNamespace(
                embedding_method="ETKDGv3",
                force_field="MMFF94s",
                max_iterations=500,
                random_seed=20260819,
                conformer_pool_size=20,
                independent_from_source_coordinates=True,
            ),
            provenance=SimpleNamespace(
                input_artifacts=[f"state-{conf_id[-1]}"],
                tool=SimpleNamespace(name="RDKit ETKDG/MMFF", version="2025.09.6"),
            ),
        ),
        conformer_content_path=lambda _lig_id, conf_id: conf_paths[conf_id],
        load_record=lambda lig_id: SimpleNamespace(
            inspection=SimpleNamespace(
                name=lig_id,
                canonical_smiles="CCO",
                molecular_weight_g_mol=46.07,
                formal_charge=0,
            ),
            state=SimpleNamespace(state_id=f"state-{lig_id[-1]}"),
        ),
    )

    catalog = ResultCatalogService(
        docking_store=_Missing(),  # type: ignore[arg-type]
        autodock4_store=_Missing(),  # type: ignore[arg-type]
        autodock_gpu_store=_Missing(),  # type: ignore[arg-type]
        binding_site_store=_Missing(),  # type: ignore[arg-type]
        ligand_store=ligand_stub,  # type: ignore[arg-type]
        gnina_store=job_store,
        gnina_screening_store=screening_store,
    )
    service = MethodsReportService(
        catalog=catalog,
        structures=_structures(),  # type: ignore[arg-type]
        receptors=SimpleNamespace(
            load_record=lambda _: _receptor(),
            content_path=lambda _rec, _art: receptor_file,
        ),  # type: ignore[arg-type]
        binding_sites=SimpleNamespace(load_record=lambda _: _site()),  # type: ignore[arg-type]
        pockets=_Missing(),  # type: ignore[arg-type]
        ligands=ligand_stub,  # type: ignore[arg-type]
        maps=_Missing(),  # type: ignore[arg-type]
        docking=_Missing(),  # type: ignore[arg-type]
        autodock4=_Missing(),  # type: ignore[arg-type]
        autodock_gpu=_Missing(),  # type: ignore[arg-type]
        gnina=job_store,
        gnina_screening=screening_store,
    )
    return service.render(f"gnina_screening:{campaign_id}"), campaign_id


def test_gnina_screening_methods_renders_verified_campaign_without_gaps(
    tmp_path, monkeypatch
) -> None:
    report, _ = _screening_campaign_fixture(tmp_path, monkeypatch)

    assert report.gaps == []
    assert "worker_count = 1" in report.markdown
    assert "1 refused at preflight before launching GNINA and 0 failed during docking" in (
        report.markdown
    )
    # Ranked by descending CNNscore (Synthetic Beta = 0.94), NOT energy (-9.4).
    assert "The top-ranked compound (Synthetic Beta) had a top-pose CNN pose score of 0.94" in (
        report.markdown
    )
    assert "predicted CNN affinity of 8.3 pK" in report.markdown
    assert "minimized affinity of -4.2 kcal mol⁻¹" in report.markdown
    assert "not necessarily the one with the lowest recorded energy" in report.markdown
    assert "10.1186/s13321-021-00522-2" in report.markdown
    assert "observed the GNINA process in all 2 completed child executions" in report.markdown
    for claim in ("Lamarckian", "AutoGrid", "clustered by AutoDock", "Vina sampling purpose"):
        assert claim not in report.markdown


@pytest.mark.parametrize(
    ("tampered", "expected_gap"),
    [
        (
            "receptor",
            "a prepared receptor whose stored bytes still match the hash GNINA recorded",
        ),
        (
            "selection",
            "a verified library filter selection manifest matching the recorded GNINA campaign",
        ),
        (
            "ligand",
            "verified ligand conformer and PDBQT artifacts for every recorded "
            "GNINA screening entry",
        ),
        (
            "conformer",
            "verified ligand conformer and PDBQT artifacts for every recorded "
            "GNINA screening entry",
        ),
    ],
)
def test_gnina_screening_methods_marks_upstream_drift_as_explicit_gaps(
    tmp_path, monkeypatch, tampered: str, expected_gap: str
) -> None:
    report, _ = _screening_campaign_fixture(tmp_path, monkeypatch, tampered=tampered)

    assert expected_gap in report.gaps
    for gap in report.gaps:
        assert f"[not recorded: {gap}]" in report.markdown
    assert report.markdown.count("[not recorded:") == len(report.gaps)


def test_gnina_screening_methods_renders_preserved_cuda_campaign_copy(
    tmp_path, monkeypatch
) -> None:
    import shutil
    from pathlib import Path

    source_data = (
        Path(__file__).resolve().parents[2]
        / "logs/linux-gnina-investigation/v1.3.3/screening-api-cuda-01/data"
    )
    if not source_data.is_dir():
        pytest.skip("Local recorded GNINA CUDA screening evidence is not present in this checkout.")
    isolated_data = tmp_path / "isolated-data"
    shutil.copytree(source_data, isolated_data)
    monkeypatch.setenv("ANKORA_DATA_DIR", str(isolated_data))

    with TestClient(create_app()) as client:
        campaigns = client.get(
            "/api/v1/results/campaigns?scoring_family=gnina&mode=screening"
        ).json()
        campaign_id = campaigns["entries"][0]["record_id"]
        response = client.get(
            f"/api/v1/results/campaigns/gnina_screening/{campaign_id}/methods"
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["gaps"] == []
        markdown = payload["markdown"]
        assert "[not recorded:" not in markdown
        assert "The top-ranked compound (NCI-68)" in markdown
        assert "all 11 completed child executions occupying GPU GPU-" in markdown
        assert "not independent proof that every neural-network operation" in markdown
        assert "doi:10.1186/s13321-021-00522-2" in markdown
        assert "Sunseri J" in markdown
