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
        "bitwise_reproducible": False,
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
            ),
        )


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
    assert "ligand conformer and PDBQT records" not in report.gaps
    assert preparation.lookups == [
        ("ligand-exact", "preparation-exact"),
        ("ligand-exact", "conformer-exact"),
    ]


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


def test_an_irreproducible_backend_says_so_instead_of_listing_seeds() -> None:
    """Seeds would imply a determinism this backend does not have."""
    report = _service(_entry(bitwise_reproducible=False)).render(
        "autodock_gpu_batch:batch-1"
    )

    assert "does not reproduce a run from its seeds" in report.markdown
    assert "reproduces the reported values" not in report.markdown


def test_a_reproducible_backend_says_that_instead() -> None:
    report = _service(_entry(bitwise_reproducible=True)).render(
        "autodock_gpu_batch:batch-1"
    )

    assert "reproduces the reported values" in report.markdown
    assert "does not reproduce a run from its seeds" not in report.markdown


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
