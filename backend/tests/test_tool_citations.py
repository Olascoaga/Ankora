"""The reference each tool's authors ask to be cited.

These entries go into somebody's bibliography. A wrong one is worse than a
missing one, because a citation looks correct until a reader follows it, so the
properties pinned here are about refusing to guess rather than about coverage.
"""

from ankora_backend.services import tool_citations
from ankora_backend.services.tool_citations import Reference, references_for


def _all_references() -> list[Reference]:
    return [
        reference
        for group in tool_citations._BY_TOOL.values()
        for reference in group
    ]


def test_a_tool_ankora_has_no_reference_for_returns_nothing() -> None:
    """Never a neighbour's citation, never an invented one."""
    assert references_for("Some Engine That Does Not Exist") == ()
    assert references_for("") == ()


def test_every_reference_is_resolvable_by_a_reader() -> None:
    for reference in _all_references():
        assert reference.doi or reference.url, reference.key
        assert reference.authors, reference.key
        assert reference.title, reference.key
        assert reference.container, reference.key


def test_one_key_never_names_two_different_works() -> None:
    """Numbering in the rendered list dedupes by key, so a collision would
    silently point two tools at one wrong paper."""
    by_key: dict[str, Reference] = {}
    for reference in _all_references():
        existing = by_key.setdefault(reference.key, reference)
        assert existing == reference, reference.key


def test_a_journal_article_states_where_to_find_it() -> None:
    for reference in _all_references():
        if reference.container == "Software":
            continue
        assert reference.year > 0, reference.key
        assert reference.volume, reference.key
        assert reference.pages, reference.key
        assert reference.doi.startswith("10."), reference.key


def test_a_software_citation_states_no_year_it_cannot_support() -> None:
    """The version that ran identifies it, and that lives in the Software table.

    Printing a release year that does not match the recorded version would be a
    small, quiet falsehood in a bibliography.
    """
    rdkit = references_for("RDKit")[0]

    assert rdkit.year == 0
    assert "2026" not in rdkit.rendered()
    assert rdkit.rendered().startswith("Landrum G, et al. RDKit: Open-source cheminformatics.")


def test_a_tool_whose_authors_ask_for_two_papers_carries_both() -> None:
    vina = references_for("AutoDock Vina")

    assert [reference.doi for reference in vina] == [
        "10.1021/acs.jcim.1c00203",
        "10.1002/jcc.21334",
    ]


def test_protonation_cites_pdb2pqr_and_both_propka_papers() -> None:
    dois = [reference.doi for reference in references_for("PDB2PQR/PROPKA")]

    assert dois == ["10.1002/pro.3280", "10.1021/ct100578z", "10.1021/ct200133y"]


def test_the_conformer_tool_cites_the_methods_its_prose_names() -> None:
    """The section says ETKDGv3 and MMFF94s by name, so a reader needs those."""
    keys = [reference.key for reference in references_for("RDKit ETKDG/MMFF")]

    assert keys == ["rdkit", "etkdg", "etkdg-v3", "mmff94", "mmff94s"]


def test_a_rendered_reference_reads_as_one_pasteable_line() -> None:
    rendered = references_for("AutoDock4")[0].rendered()

    assert rendered == (
        "Morris GM, Huey R, Lindstrom W, Sanner MF, Belew RK, Goodsell DS, Olson AJ. "
        "AutoDock4 and AutoDockTools4: Automated docking with selective receptor "
        "flexibility. Journal of Computational Chemistry. 2009;30(16):2785-2791. "
        "doi:10.1002/jcc.21256"
    )
    assert "\n" not in rendered
