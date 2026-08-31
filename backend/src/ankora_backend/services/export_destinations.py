"""Writing into a folder the scientist chose, for every kind of export.

Figures, ligand-receptor complexes and campaign bundles all end up in the same
place — the folder holding a manuscript — and all three need the same three
guarantees, which is why they are stated once here rather than three times:

* **The folder must already exist.** Creating it would turn a typo into a
  figure saved somewhere the scientist will never look.
* **A name in use is never taken.** That folder holds work; every write is
  create-only and a taken name counts up the way Windows does.
* **Names carry what the file is.** `interaction_diagram.svg` identifies
  nothing among its own peers.
"""

import os
import re
from pathlib import Path

from ankora_backend.domain.errors import AnkoraDomainError


def validated_destination(
    destination: str | None, *, stage: str, prefix: str
) -> Path | None:
    """The folder the scientist named, or nothing if they named none.

    `prefix` names the error codes so each export kind keeps reporting in its
    own vocabulary — `FIGURE_DESTINATION_NOT_FOUND` is what its tests and its
    interface already know.
    """
    if destination is None:
        return None
    path = Path(destination).expanduser()
    if not path.is_absolute():
        raise AnkoraDomainError(
            code=f"{prefix}_DESTINATION_INVALID",
            stage=stage,
            message="A destination folder has to be a full path.",
            status_code=422,
            details={"destination": destination},
        )
    resolved = path.resolve()
    if not resolved.is_dir():
        raise AnkoraDomainError(
            code=f"{prefix}_DESTINATION_NOT_FOUND",
            stage=stage,
            message=(
                "That destination folder does not exist. Ankora never writes "
                "into a folder it had to create."
            ),
            status_code=422,
            details={"destination": str(resolved)},
        )
    if not os.access(resolved, os.W_OK):
        raise AnkoraDomainError(
            code=f"{prefix}_DESTINATION_NOT_WRITABLE",
            stage=stage,
            message="Ankora cannot write into that folder.",
            status_code=422,
            details={"destination": str(resolved)},
        )
    return resolved


def slug(value: str) -> str:
    """A filename fragment: ASCII, no separators a shell or a path would eat."""
    kept = [
        character if (character.isascii() and (character.isalnum() or character in "-_"))
        else ("-" if character in " ." else "")
        for character in value.strip()
    ]
    # `Cluster 1 · run 3` drops the middle dot and would otherwise keep the two
    # spaces around it as a double hyphen.
    return re.sub(r"-{2,}", "-", "".join(kept)).strip("-_")


def free_name(directory: Path, basename: str, extension: str) -> str:
    """A filename nothing in this folder already uses."""
    candidate = f"{basename}.{extension}"
    index = 2
    while (directory / candidate).exists():
        candidate = f"{basename} ({index}).{extension}"
        index += 1
    return candidate


def free_directory(parent: Path, basename: str) -> Path:
    """A folder name nothing in this folder already uses."""
    candidate = parent / basename
    index = 2
    while candidate.exists():
        candidate = parent / f"{basename} ({index})"
        index += 1
    return candidate
