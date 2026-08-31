"""Contract for the shared insertion-code normalization helper.

Empirically, gemmi represents an absent insertion code as a plain space
(`" "`) for every real file this project has actually read this session
(synthetic PDB, synthetic mmCIF, and a real PDBFixer/PDB2PQR/Meeko-prepared
7AQF receptor) — confirmed by reading `seqid.icode` directly, not assumed.
`.strip()` already handles that case correctly. `clean_insertion_code` is
kept defensive against `"\\x00"`/`"."`/`"?"` too, since `seqid.icode` is a
plain string field on `gemmi.Residue` that isn't guaranteed to only ever
hold a space for every gemmi version or every way a Residue can be built
(e.g. constructed in code rather than read from a file) — but the space
case is the one with real, verified evidence behind it.
"""

from ankora_backend.domain.gemmi_utils import clean_insertion_code


def test_space_is_normalized_to_empty() -> None:
    # The real, verified representation: `repr(icode) == "' '"` for every
    # real structure file read during this session.
    assert clean_insertion_code(" ") == ""


def test_null_byte_is_normalized_to_empty() -> None:
    assert clean_insertion_code("\x00") == ""


def test_other_placeholder_characters_are_normalized_to_empty() -> None:
    assert clean_insertion_code(".") == ""
    assert clean_insertion_code("?") == ""


def test_a_real_insertion_code_letter_is_preserved() -> None:
    assert clean_insertion_code("A") == "A"
