"""Keep Unicode filesystem access in Python, not RDKit's narrow Windows API.

The original molecular bytes and RDKit parsing/sanitization settings are
unchanged. Only opening the file moves to Python's Unicode-aware filesystem.
"""

from importlib import import_module
from pathlib import Path
from typing import Any


def sdf_supplier(path: Path, *, remove_hs: bool = False) -> Any:
    chemistry = import_module("rdkit.Chem")
    supplier = chemistry.SDMolSupplier()
    supplier.SetData(path.read_bytes(), removeHs=remove_hs, sanitize=True)
    return supplier
