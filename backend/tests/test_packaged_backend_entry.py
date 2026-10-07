from __future__ import annotations

import sys

import pytest

from ankora_backend import __main__ as backend_entry


def test_packaged_worker_receives_only_tool_arguments(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    calls: list[list[str]] = []

    def worker() -> None:
        calls.append(sys.argv.copy())

    monkeypatch.setattr(backend_entry, "_worker", lambda _name: worker)
    monkeypatch.setattr(sys, "argv", ["ankora-backend.exe"])

    backend_entry.main(
        ["--worker", "meeko-ligand", "-i", "ligand.sdf", "-o", "ligand.pdbqt"]
    )

    assert calls == [
        ["ankora-backend.exe", "-i", "ligand.sdf", "-o", "ligand.pdbqt"]
    ]


@pytest.mark.parametrize("code", [0, 1, 7])
def test_packaged_worker_propagates_integer_exit_status(monkeypatch, code) -> None:
    monkeypatch.setattr(backend_entry, "_worker", lambda _name: lambda: code)
    monkeypatch.setattr(sys, "argv", ["ankora-backend.exe"])
    with pytest.raises(SystemExit) as exit_info:
        backend_entry.main(["--worker", "native-smoke", "--package-probe"])
    assert exit_info.value.code == code
