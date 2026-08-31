"""Shared helpers for reasoning about gemmi structures across services."""


def clean_insertion_code(value: str) -> str:
    """Normalize gemmi's "no insertion code" sentinel to an empty string.

    gemmi represents an absent insertion code as the null byte `"\\x00"`,
    not as an empty string or plain whitespace. A bare `.strip()` leaves
    `"\\x00"` untouched (it isn't whitespace), so comparing it directly
    against a locator's `insertion_code=""` spuriously fails to match a
    residue that has no insertion code at all.
    """
    return "" if value in {"\x00", " ", ".", "?"} else value
