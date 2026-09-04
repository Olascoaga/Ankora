"""The Methods section a campaign's own records support.

This is the output that ends up in a paper, so the rule it has to hold is
narrow and absolute: every sentence comes from a stored artifact, and a
missing artifact becomes a visible hole rather than a plausible sentence.
"""

from types import SimpleNamespace
from typing import Any

import pytest

from ankora_backend.domain.errors import AnkoraDomainError
from ankora_backend.schemas.methods import MethodsReport
from ankora_backend.schemas.results_catalog import (
    ReproducibilityAssessment,
    ReproducibilityExecution,
    ReproducibilityStatus,
    ScoringFamily,
)
from ankora_backend.services.methods_report import MethodsReportService


class _Missing:
    """A store whose records have all been removed."""

    def __getattr__(self, name: str) -> Any:
        def _raise(*_: Any, **__: Any) -> Any:
            raise AnkoraDomainError(
                code="NOT_FOUND", stage="test", message="gone", status_code=404,
            )
        return _raise


def _entry(**overrides: Any) -> Any:
    defaults: dict[str, Any] = {
        "catalog_id": "autodock_gpu_batch:batch-1",
        "engine_key": "autodock_gpu_batch",
        "record_id": "batch-1",
        "engine_label": "AutoDock4 · AutoDock-GPU 1.6",
        "engine_version": "1.6",
        "scoring_family": SimpleNamespace(name="AUTODOCK4"),
        "backend": "autodock_gpu",
        "receptor_id": "receptor-1",
        "binding_site_id": "site-1",
        "map_set_id": None,
        "library_id": None,
        "filter_run_id": None,
        "executable_sha256": None,
        "device_name": None,
        "selected_count": 3,
        "succeeded_count": 2,
        "failed_count": 1,
        "reproducibility": ReproducibilityAssessment(),
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


class _Catalog:
    def __init__(self, entry: Any) -> None:
        self._entry = entry

    def get_campaign(self, catalog_id: str) -> Any:
        return self._entry


def _service(entry: Any, **stores: Any) -> MethodsReportService:
    defaults = {
        "structures": _Missing(), "receptors": _Missing(),
        "binding_sites": _Missing(), "ligands": _Missing(), "maps": _Missing(),
        "docking": _Missing(), "autodock4": _Missing(), "autodock_gpu": _Missing(),
    }
    defaults.update(stores)
    return MethodsReportService(catalog=_Catalog(entry), **defaults)  # type: ignore[arg-type]


class _ExactPreparation:
    """Only the preparation named by the docking request may be described."""

    def __init__(self) -> None:
        self.lookups: list[tuple[str, str]] = []

    def load_pdbqt_record(self, ligand_id: str, preparation_id: str) -> Any:
        self.lookups.append((ligand_id, preparation_id))
        assert (ligand_id, preparation_id) == ("ligand-exact", "preparation-exact")
        return SimpleNamespace(
            artifact=SimpleNamespace(conformer_id="conformer-exact"),
            charge_model="gasteiger",
            tool=SimpleNamespace(name="Meeko", version="0.7.1"),
        )

    def load_conformer_record(self, ligand_id: str, conformer_id: str) -> Any:
        self.lookups.append((ligand_id, conformer_id))
        assert (ligand_id, conformer_id) == ("ligand-exact", "conformer-exact")
        return SimpleNamespace(
            minimization=SimpleNamespace(
                embedding_method="ETKDGv3",
                force_field="MMFF94s",
                max_iterations=500,
                random_seed=20260819,
                conformer_pool_size=20,
                independent_from_source_coordinates=True,
            ),
            provenance=SimpleNamespace(
                input_artifacts=["state-exact"],
                tool=SimpleNamespace(name="RDKit ETKDG/MMFF", version="2025.09.6"),
            ),
        )

    def load_record(self, ligand_id: str) -> Any:
        assert ligand_id == "ligand-exact"
        return SimpleNamespace(state=SimpleNamespace(state_id="state-exact"))


@pytest.mark.parametrize(
    ("engine_key", "store_name", "loader_name", "engine_label", "scoring_name"),
    [
        ("vina_job", "docking", "load_record", "AutoDock Vina 1.2.7", "VINA"),
        ("autodock4_job", "autodock4", "load_job", "AutoDock 4.2.6", "AUTODOCK4"),
        (
            "autodock_gpu_job", "autodock_gpu", "load_job",
            "AutoDock4 · AutoDock-GPU 1.6", "AUTODOCK4",
        ),
    ],
)
def test_single_jobs_describe_the_exact_ligand_preparation(
    engine_key: str,
    store_name: str,
    loader_name: str,
    engine_label: str,
    scoring_name: str,
) -> None:
    preparation = _ExactPreparation()
    record = SimpleNamespace(
        request=SimpleNamespace(
            ligand_id="ligand-exact",
            ligand_preparation_id="preparation-exact",
            parameters=SimpleNamespace(model_dump=lambda mode: {}),
        ),
    )
    engine_store = SimpleNamespace(**{loader_name: lambda _: record})
    report = _service(
        _entry(
            engine_key=engine_key,
            engine_label=engine_label,
            scoring_family=SimpleNamespace(name=scoring_name),
            library_id=None,
            selected_count=1,
            succeeded_count=1,
            failed_count=0,
        ),
        ligands=preparation,
        **{store_name: engine_store},
    ).render(f"{engine_key}:job-1")

    assert "A single ligand was docked" in report.markdown
    assert "The selected ligand was converted" in report.markdown
    assert "ETKDGv3" in report.markdown
    assert "MMFF94s" in report.markdown
    assert "up to 500 iterations" in report.markdown
    assert "Meeko 0.7.1" in report.markdown
    assert "Gasteiger partial charges" in report.markdown
    assert "seed 20260819" in report.markdown
    assert "20-conformer pool" in report.markdown
    assert "initial imported or extracted chemical state" in report.markdown
    assert "No pH-based ligand protonation enumeration was recorded" in report.markdown
    assert "No ligand tautomer enumeration was recorded" in report.markdown
    assert "ligand conformer and PDBQT records" not in report.gaps
    assert "complete ligand chemical-state lineage" not in report.gaps
    assert preparation.lookups == [
        ("ligand-exact", "preparation-exact"),
        ("ligand-exact", "conformer-exact"),
    ]


class _BatchLigands:
    def __init__(
        self,
        protocols: dict[str, dict[str, Any]],
        state_records: dict[tuple[str, str], Any] | None = None,
        filter_plan: dict[str, Any] | None = None,
        filter_summary: dict[str, int] | None = None,
    ) -> None:
        self.protocols = protocols
        self.state_records = state_records or {}
        self.filter_plan = filter_plan or {}
        self.filter_summary = filter_summary or {}
        self.preparation_lookups: list[tuple[str, str]] = []

    def load_library_record(self, library_id: str) -> Any:
        assert library_id == "library-1"
        count = len(self.protocols)
        return SimpleNamespace(
            artifact=SimpleNamespace(
                record_count=count,
                filename="synthetic_library.sdf",
                format="sdf",
            ),
            imported_count=count,
            failed_count=0,
        )

    def load_filter_run(self, library_id: str, filter_run_id: str) -> Any:
        assert (library_id, filter_run_id) == ("library-1", "filter-1")
        count = len(self.protocols)
        plan = {
            "require_lipinski": False,
            "max_lipinski_violations": 1,
            "require_veber": False,
            "require_ghose": False,
            "require_muegge": False,
            "minimum_qed": None,
            "custom_rules": [],
            "pains_policy": "ignore",
            "brenk_policy": "ignore",
            "duplicate_policy": "keep",
        }
        plan.update(self.filter_plan)
        summary = {
            "pains_match_count": 0,
            "brenk_match_count": 0,
            "duplicate_count": 0,
            "needs_decision_count": 0,
            "imported_count": count,
            "eligible_count": count,
            "excluded_count": 0,
        }
        summary.update(self.filter_summary)
        return SimpleNamespace(
            rdkit_version="2025.09.6",
            plan=SimpleNamespace(**plan),
            summary=SimpleNamespace(**summary),
        )

    def load_pdbqt_record(self, ligand_id: str, preparation_id: str) -> Any:
        self.preparation_lookups.append((ligand_id, preparation_id))
        protocol = self.protocols.get(ligand_id)
        if protocol is None or protocol.get("unavailable"):
            raise AnkoraDomainError(
                code="NOT_FOUND", stage="test", message="gone", status_code=404,
            )
        assert preparation_id == protocol["preparation_id"]
        return SimpleNamespace(
            artifact=SimpleNamespace(conformer_id=protocol["conformer_id"]),
            charge_model=protocol.get("charge_model", "gasteiger"),
            tool=SimpleNamespace(
                name=protocol.get("meeko_name", "Meeko"),
                version=protocol.get("meeko_version", "0.7.1"),
            ),
        )

    def load_conformer_record(self, ligand_id: str, conformer_id: str) -> Any:
        protocol = self.protocols[ligand_id]
        assert conformer_id == protocol["conformer_id"]
        return SimpleNamespace(
            minimization=SimpleNamespace(
                embedding_method=protocol.get("embedding_method", "ETKDGv3"),
                force_field=protocol.get("force_field", "MMFF94s"),
                max_iterations=protocol.get("max_iterations", 500),
                random_seed=protocol.get("random_seed", 20260819),
                conformer_pool_size=protocol.get("conformer_pool_size", 20),
                independent_from_source_coordinates=True,
            ),
            provenance=SimpleNamespace(
                input_artifacts=[protocol.get("state_id", f"state-{ligand_id}")],
                tool=SimpleNamespace(name="RDKit ETKDG/MMFF", version="2025.09.6"),
            ),
        )

    def load_record(self, ligand_id: str) -> Any:
        return SimpleNamespace(state=SimpleNamespace(state_id=f"state-{ligand_id}"))

    def load_state_record(self, ligand_id: str, state_id: str) -> Any:
        try:
            return self.state_records[(ligand_id, state_id)]
        except KeyError as error:
            raise AnkoraDomainError(
                code="NOT_FOUND", stage="test", message="gone", status_code=404,
            ) from error


def _batch_report(
    ligands: _BatchLigands, entries: list[Any], selected_count: int,
) -> MethodsReport:
    record = SimpleNamespace(
        request=SimpleNamespace(
            parameters=SimpleNamespace(model_dump=lambda mode: {}),
        ),
        entries=entries,
    )
    return _service(
        _entry(
            library_id="library-1",
            filter_run_id="filter-1",
            selected_count=selected_count,
            succeeded_count=len(entries),
            failed_count=0,
        ),
        ligands=ligands,
        autodock_gpu=SimpleNamespace(load_batch=lambda _: record),
    ).render("autodock_gpu_batch:batch-1")


def _protocol(ligand_id: str, **overrides: Any) -> dict[str, Any]:
    values = {
        "preparation_id": f"preparation-{ligand_id}",
        "conformer_id": f"conformer-{ligand_id}",
    }
    values.update(overrides)
    return values


def _batch_entry(ligand_id: str, preparation_id: str | None) -> Any:
    return SimpleNamespace(
        ligand_id=ligand_id,
        ligand_preparation_id=preparation_id,
    )


def test_uniform_batch_protocol_is_claimed_only_after_every_entry_is_read() -> None:
    protocols = {
        "ligand-1": _protocol("ligand-1"),
        "ligand-2": _protocol("ligand-2"),
    }
    ligands = _BatchLigands(protocols)
    report = _batch_report(
        ligands,
        [
            _batch_entry("ligand-1", "preparation-ligand-1"),
            _batch_entry("ligand-2", "preparation-ligand-2"),
        ],
        selected_count=2,
    )

    assert "All 2 docked ligands were prepared" in report.markdown
    assert "2 distinct recorded protocols" not in report.markdown
    assert "All 2 verified ligands used the initial imported" in report.markdown
    assert ligands.preparation_lookups == [
        ("ligand-1", "preparation-ligand-1"),
        ("ligand-2", "preparation-ligand-2"),
    ]


def test_filter_census_names_every_mutually_exclusive_outcome() -> None:
    protocols = {f"ligand-{index}": _protocol(f"ligand-{index}") for index in range(5)}
    ligands = _BatchLigands(
        protocols,
        filter_plan={"pains_policy": "exclude", "brenk_policy": "review"},
        filter_summary={
            "eligible_count": 2,
            "excluded_count": 2,
            "needs_decision_count": 1,
            "pains_match_count": 1,
            "brenk_match_count": 2,
        },
    )
    report = _batch_report(
        ligands,
        [_batch_entry("ligand-1", "preparation-ligand-1")],
        selected_count=1,
    )

    assert (
        "PAINS alerts matched 1 compound; compounds with those matches were excluded"
        in report.markdown
    )
    assert (
        "Brenk alerts matched 2 compounds; those matches were flagged for review"
        in report.markdown
    )
    assert "2 were eligible for selection, 2 were excluded, and 1 required" in report.markdown
    assert "mutually exclusive outcomes account for all 5 compounds" in report.markdown
    assert "internally consistent library filter census" not in report.gaps
    assert "excluded and excluded respectively" not in report.markdown


def test_inconsistent_filter_census_stays_a_visible_methods_gap() -> None:
    protocols = {f"ligand-{index}": _protocol(f"ligand-{index}") for index in range(5)}
    report = _batch_report(
        _BatchLigands(
            protocols,
            filter_summary={
                "eligible_count": 2,
                "excluded_count": 2,
                "needs_decision_count": 0,
            },
        ),
        [_batch_entry("ligand-1", "preparation-ligand-1")],
        selected_count=1,
    )

    assert "The categories account for 4 compounds" in report.markdown
    assert "[not recorded: internally consistent library filter census]" in report.markdown
    assert "internally consistent library filter census" in report.gaps


def test_batch_reports_heterogeneous_protocols_and_state_lineages() -> None:
    initial_state = "state-ligand-2"
    manual_state = "manual-ligand-2"
    protonated_state = "protonated-ligand-2"
    manual = SimpleNamespace(
        parent_state_id=initial_state,
        provenance=SimpleNamespace(
            event_type="ligand_chemical_state_resolved",
            tool=SimpleNamespace(name="RDKit state resolver", version="2025.09.6"),
        ),
    )
    protonated = SimpleNamespace(
        parent_state_id=manual_state,
        selection=SimpleNamespace(
            ph_min=7.4, ph_max=7.4, candidate_count=3,
        ),
        provenance=SimpleNamespace(
            event_type="ligand_protonation_resolved",
            tool=SimpleNamespace(name="Dimorphite-DL", version="2.0.2"),
        ),
    )
    protocols = {
        "ligand-1": _protocol("ligand-1", random_seed=11),
        "ligand-2": _protocol(
            "ligand-2", random_seed=22, state_id=protonated_state,
        ),
    }
    ligands = _BatchLigands(
        protocols,
        {
            ("ligand-2", manual_state): manual,
            ("ligand-2", protonated_state): protonated,
        },
    )
    report = _batch_report(
        ligands,
        [
            _batch_entry("ligand-1", "preparation-ligand-1"),
            _batch_entry("ligand-2", "preparation-ligand-2"),
        ],
        selected_count=2,
    )

    assert "2 distinct recorded protocols" in report.markdown
    assert "seed 11" in report.markdown
    assert "seed 22" in report.markdown
    assert "2 chemical-state lineages" in report.markdown
    assert "explicit component/stereochemistry resolution" in report.markdown
    assert "3 enumerated by Dimorphite-DL 2.0.2 at pH 7.4" in report.markdown
    assert "No pH-based ligand protonation enumeration" not in report.markdown
    assert "No ligand tautomer enumeration was recorded" in report.markdown


def test_selected_microstate_is_described_as_bounded_and_unranked() -> None:
    initial_state = "state-ligand-1"
    microstate_id = "microstate-ligand-1"
    microstate = SimpleNamespace(
        parent_state_id=initial_state,
        selection=SimpleNamespace(
            plan=SimpleNamespace(
                ph_min=7.4,
                ph_max=7.4,
                max_tautomers_per_protomer=8,
                max_microstates_per_parent=16,
            ),
            candidate_count=5,
            candidate_index=2,
            enumeration_truncated=True,
        ),
        provenance=SimpleNamespace(
            event_type="ligand_microstate_selected",
            tool=SimpleNamespace(
                name="Dimorphite-DL + RDKit TautomerEnumerator",
                version="Dimorphite-DL 2.0.2; RDKit 2025.09.6",
            ),
        ),
    )
    ligands = _BatchLigands(
        {"ligand-1": _protocol("ligand-1", state_id=microstate_id)},
        {("ligand-1", microstate_id): microstate},
    )

    report = _batch_report(
        ligands,
        [_batch_entry("ligand-1", "preparation-ligand-1")],
        selected_count=1,
    )

    assert "protonation/tautomer candidate 3 of 5" in report.markdown
    assert "candidate order was unranked" in report.markdown
    assert "configured bound reached" in report.markdown
    assert "No ligand tautomer enumeration was recorded" not in report.markdown


def test_incomplete_batch_preparation_stays_a_visible_methods_gap() -> None:
    protocols = {
        "ligand-1": _protocol("ligand-1"),
        "ligand-2": _protocol("ligand-2", unavailable=True),
    }
    report = _batch_report(
        _BatchLigands(protocols),
        [
            _batch_entry("ligand-1", "preparation-ligand-1"),
            _batch_entry("ligand-2", "preparation-ligand-2"),
            _batch_entry("ligand-3", None),
        ],
        selected_count=3,
    )

    assert "available for 1 of 3 campaign entries" in report.markdown
    assert "2 did not name an available conformer and PDBQT lineage" in report.markdown
    assert "complete batch ligand preparation records" in report.gaps


def test_incomplete_chemical_state_lineage_stays_a_visible_methods_gap() -> None:
    protocols = {
        "ligand-1": _protocol("ligand-1", state_id="missing-derived-state"),
    }
    report = _batch_report(
        _BatchLigands(protocols),
        [_batch_entry("ligand-1", "preparation-ligand-1")],
        selected_count=1,
    )

    assert "Chemical-state lineage was available for 0 of 1" in report.markdown
    assert "complete ligand chemical-state lineage" in report.gaps
    assert "No pH-based ligand protonation enumeration" not in report.markdown
    assert "No ligand tautomer enumeration" not in report.markdown


def test_a_campaign_whose_records_are_gone_reports_holes_not_prose() -> None:
    """The failure Ankora exists to prevent is text that reads as verified.

    With every referenced artifact removed, the section must be a list of
    what it could not establish — not a fluent paragraph with no source.
    """
    report = _service(_entry()).render("autodock_gpu_batch:batch-1")

    assert isinstance(report, MethodsReport)
    assert "[not recorded: receptor preparation record]" in report.markdown
    assert "[not recorded: binding site record]" in report.markdown
    assert "[not recorded: docking request parameters]" in report.markdown
    assert set(report.gaps) >= {
        "receptor preparation record",
        "binding site record",
        "docking request parameters",
    }
    # And nothing was invented to fill them.
    assert "pH" not in report.markdown
    assert "centred at" not in report.markdown


def test_the_gap_list_matches_the_markers_in_the_text() -> None:
    """A hole counted but not shown, or shown but not counted, is a trap."""
    report = _service(_entry()).render("autodock_gpu_batch:batch-1")

    for gap in report.gaps:
        assert f"[not recorded: {gap}]" in report.markdown
    assert report.markdown.count("[not recorded:") == len(report.gaps)


def test_a_single_ligand_campaign_says_no_library_was_screened() -> None:
    report = _service(_entry(library_id=None)).render("autodock_gpu_batch:batch-1")

    assert "no compound library was screened" in report.markdown
    assert "compounds were imported" not in report.markdown


def _assessment(status: ReproducibilityStatus, *outputs: str) -> ReproducibilityAssessment:
    return ReproducibilityAssessment(
        status=status,
        input_fingerprint_sha256="a" * 64,
        executions=[
            ReproducibilityExecution(
                catalog_id=f"autodock_gpu_batch:batch-{index}",
                output_fingerprint_sha256=output,
            )
            for index, output in enumerate(outputs, start=1)
        ],
    )


def test_unassessed_repeat_behavior_is_not_promoted_from_an_engine_or_seed() -> None:
    report = _service(_entry()).render("autodock_gpu_batch:batch-1")

    assert "Repeat reproducibility was not assessed" in report.markdown
    assert "do not establish that its outputs will match" in report.markdown
    assert "were identical" not in report.markdown


def test_measured_variability_names_the_exact_compared_executions_and_hashes() -> None:
    report = _service(
        _entry(
            reproducibility=_assessment(
                ReproducibilityStatus.MEASURED_VARIABLE,
                "b" * 64,
                "c" * 64,
            )
        )
    ).render("autodock_gpu_batch:batch-1")

    assert "Repeat behavior was measured across 2 exactly comparable" in report.markdown
    assert "batch-1 (output fingerprint SHA-256" in report.markdown
    assert "batch-2 (output fingerprint SHA-256" in report.markdown
    assert "input fingerprint SHA-256 " + "a" * 64 in report.markdown


def test_measured_reproducibility_requires_equal_output_fingerprints() -> None:
    report = _service(
        _entry(
            reproducibility=_assessment(
                ReproducibilityStatus.MEASURED_REPRODUCIBLE,
                "b" * 64,
                "b" * 64,
            )
        )
    ).render("autodock_gpu_batch:batch-1")

    assert "retained pose-artifact bytes were identical" in report.markdown
    assert report.markdown.count("output fingerprint SHA-256 " + "b" * 64) == 2


def test_the_score_is_never_called_an_affinity() -> None:
    """The one claim a docking Methods section must not make."""
    report = _service(_entry()).render("autodock_gpu_batch:batch-1")

    assert "are not measured binding affinities" in report.markdown
    lowered = report.markdown.lower()
    assert "binding affinity of" not in lowered
    assert "affinity was" not in lowered


def test_the_software_table_is_a_hole_when_no_tool_version_is_known() -> None:
    report = _service(_entry()).render("autodock_gpu_batch:batch-1")

    assert "[not recorded: tool versions]" in report.markdown
    assert report.software == []


def test_citations_are_declared_the_authors_responsibility() -> None:
    """Ankora records versions; it does not know which paper to cite."""
    report = _service(
        _entry(),
        autodock_gpu=SimpleNamespace(
            load_batch=lambda _: SimpleNamespace(
                request=SimpleNamespace(parameters=SimpleNamespace(
                    model_dump=lambda mode: {
                        "runs": 10, "population_size": 150,
                        "energy_evaluations": 2_500_000,
                        "local_search_method": "ad",
                        "cluster_rmsd_tolerance_angstrom": 2.0,
                    },
                )),
                entries=[],
            ),
        ),
    ).render("autodock_gpu_batch:batch-1")

    assert "must be added by the author" in report.markdown
    assert "ADADELTA" in report.markdown
    assert "2.5 × 10⁶" in report.markdown


@pytest.mark.parametrize(
    ("sampling_protocol", "expected"),
    [
        ("screening", "recorded Vina sampling purpose was Screening"),
        ("pose_refinement", "recorded Vina sampling purpose was Pose refinement"),
        ("custom", "recorded Vina sampling purpose was Custom"),
    ],
)
def test_vina_methods_report_sampling_purpose_without_claiming_convergence(
    sampling_protocol: str,
    expected: str,
) -> None:
    parameters = {
        "sampling_protocol": sampling_protocol,
        "exhaustiveness": 8,
        "num_modes": 9,
        "min_rmsd_angstrom": 1.0,
        "energy_range_kcal_mol": 3.0,
        "seed": 42,
    }
    report = _service(
        _entry(
            engine_key="vina_job",
            engine_label="AutoDock Vina 1.2.7",
            engine_version="1.2.7",
            scoring_family=ScoringFamily.VINA,
            backend="vina",
            selected_count=1,
            succeeded_count=1,
            failed_count=0,
        ),
        docking=SimpleNamespace(
            load_record=lambda _: SimpleNamespace(
                request=SimpleNamespace(
                    parameters=SimpleNamespace(model_dump=lambda mode: parameters),
                ),
            ),
        ),
    ).render("vina_job:job-1")

    assert expected in report.markdown
    assert "not evidence of sampling convergence or publication suitability" in report.markdown


def test_historical_vina_methods_report_does_not_infer_sampling_purpose() -> None:
    parameters = {
        "exhaustiveness": 8,
        "num_modes": 9,
        "min_rmsd_angstrom": 1.0,
        "energy_range_kcal_mol": 3.0,
        "seed": 42,
    }
    report = _service(
        _entry(
            engine_key="vina_job",
            engine_label="AutoDock Vina 1.2.7",
            engine_version="1.2.7",
            scoring_family=ScoringFamily.VINA,
            backend="vina",
            selected_count=1,
            succeeded_count=1,
            failed_count=0,
        ),
        docking=SimpleNamespace(
            load_record=lambda _: SimpleNamespace(
                request=SimpleNamespace(
                    parameters=SimpleNamespace(model_dump=lambda mode: parameters),
                ),
            ),
        ),
    ).render("vina_job:job-1")

    assert "did not record a named Vina sampling purpose" in report.markdown
    assert "no screening or refinement intent was inferred" in report.markdown


def test_an_unknown_campaign_is_refused_rather_than_described() -> None:
    class _Absent:
        def get_campaign(self, catalog_id: str) -> Any:
            raise AnkoraDomainError(
                code="RESULT_CATALOG_ENGINE_UNKNOWN", stage="test",
                message="no", status_code=422,
            )

    service = MethodsReportService(
        catalog=_Absent(),  # type: ignore[arg-type]
        structures=_Missing(), receptors=_Missing(), binding_sites=_Missing(),  # type: ignore[arg-type]
        ligands=_Missing(), maps=_Missing(), docking=_Missing(),  # type: ignore[arg-type]
        autodock4=_Missing(), autodock_gpu=_Missing(),  # type: ignore[arg-type]
    )

    with pytest.raises(AnkoraDomainError):
        service.render("gnina_batch:whatever")
