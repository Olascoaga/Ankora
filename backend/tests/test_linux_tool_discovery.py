"""Native (non-Windows) executable discovery contracts.

Every executable here is a SYNTHETIC fixture that is never launched: a minimal
ELF header, a PE header, or a ``#!`` script stub. Discovery reads headers,
permissions and metadata only; no scientific tool runs and no result is mocked.
POSIX permission bits and symlinks are required, so the module skips on Windows,
whose accepted rules are pinned in test_tool_discovery.py.
"""

from __future__ import annotations

import hashlib
import os
import shutil
from pathlib import Path

import pytest

from ankora_backend.adapters.tools import discovery
from ankora_backend.adapters.tools.discovery import (
    _portable_autodock4_candidate_directories,
    _portable_p2rank_candidate_directories,
    _portable_vina_candidate_directories,
    discover_autodock4,
    discover_autodock_gpu,
    discover_autogrid4,
    discover_java_home,
    discover_p2rank,
    discover_tool,
    discover_vina,
)

pytestmark = pytest.mark.skipif(os.name == "nt", reason="native POSIX discovery rules")

X86_64, ARM64 = 0x3E, 0xB7


def _executable(path: Path, content: bytes, mode: int = 0o755) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    path.chmod(mode)
    return path


def _elf(path: Path, machine: int = X86_64, mode: int = 0o755) -> Path:
    """Synthetic 64-bit little-endian ELF header; never executed."""
    header = bytearray(64)
    header[0:4] = b"\x7fELF"
    header[4], header[5], header[6] = 2, 1, 1
    header[18:20] = machine.to_bytes(2, byteorder="little")
    return _executable(path, bytes(header) + b"synthetic ELF fixture; never executed", mode)


def _pe(path: Path) -> Path:
    """Synthetic PE header, executable bit set as on a WSL drive mount; never executed."""
    content = bytearray(512)
    content[0:2] = b"MZ"
    content[0x3C:0x40] = (128).to_bytes(4, byteorder="little")
    content[128:132] = b"PE\x00\x00"
    content[132:134] = (0x8664).to_bytes(2, byteorder="little")
    return _executable(path, bytes(content))


def _script(path: Path, interpreter: str = "/bin/sh") -> Path:
    return _executable(path, f"#!{interpreter}\n# synthetic launcher; never executed\n".encode())


def _no_path(_: str) -> None:
    return None


# --- Executable identity -------------------------------------------------------------


def test_native_executables_are_recognised_by_content_not_name(tmp_path: Path) -> None:
    assert discovery._is_native_executable(_elf(tmp_path / "elf"))
    assert discovery._is_native_executable(_script(tmp_path / "script"))
    assert not discovery._is_native_executable(_pe(tmp_path / "masquerading-pe"))
    assert not discovery._is_native_executable(_elf(tmp_path / "renamed.exe"))
    assert not discovery._is_native_executable(_script(tmp_path / "launcher.bat"))
    assert not discovery._is_native_executable(_elf(tmp_path / "not-executable", mode=0o644))
    assert not discovery._is_native_executable(_executable(tmp_path / "data", b"plain text"))
    assert not discovery._is_native_executable(tmp_path / "missing")


def test_scripts_for_windows_interpreters_are_rejected(tmp_path: Path) -> None:
    assert not discovery._is_native_executable(
        _script(tmp_path / "a", "/mnt/c/Python312/python.exe")
    )
    assert not discovery._is_native_executable(_script(tmp_path / "b", "/mnt/d/tools/sh"))
    assert not discovery._is_native_executable(_script(tmp_path / "c", "relative/sh"))
    assert discovery._is_native_executable(_script(tmp_path / "d", "/usr/bin/env bash"))


@pytest.mark.parametrize(
    ("path", "windows"),
    [
        ("/mnt/c/Program Files/tool", True),
        ("/mnt/D/tools/vina", True),
        ("/mnt/c", True),
        ("/mnt/data/tools/vina", False),
        ("/opt/mnt/c/vina", False),
        ("/usr/bin/vina", False),
    ],
)
def test_wsl_drive_mounts_are_windows_locations(path: str, windows: bool) -> None:
    assert discovery._is_wsl_drive_path(Path(path)) is windows


def test_elf_architecture_is_read_from_the_header(tmp_path: Path) -> None:
    assert discovery._read_elf_architecture(_elf(tmp_path / "x", X86_64)) == "x86_64"
    assert discovery._read_elf_architecture(_elf(tmp_path / "a", ARM64)) == "arm64"
    assert discovery._read_elf_architecture(_elf(tmp_path / "u", 0x1234)) == "unknown"
    assert discovery._read_elf_architecture(_script(tmp_path / "s")) is None
    assert discovery._read_elf_architecture(_pe(tmp_path / "p")) is None


# --- PATH and the active Python environment ------------------------------------------


def test_path_search_skips_a_masquerading_windows_entry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    windows_directory = tmp_path / "windows-path-entry"
    native_directory = tmp_path / "native-path-entry"
    _pe(windows_directory / "pdb2pqr")
    native = _script(native_directory / "pdb2pqr")
    monkeypatch.setenv("PATH", f"{windows_directory}{os.pathsep}{native_directory}")

    assert shutil.which("pdb2pqr") == str(windows_directory / "pdb2pqr")
    discovered = discover_tool("pdb2pqr", candidate_directories=())

    assert discovered.available is True
    assert discovered.path == str(native.resolve())


def test_meeko_py_entry_points_and_plain_console_names_are_found(tmp_path: Path) -> None:
    environment_bin = tmp_path / "env" / "bin"
    ligand = _script(environment_bin / "mk_prepare_ligand.py", "/opt/env/bin/python")
    receptor = _script(environment_bin / "mk_prepare_receptor", "/opt/env/bin/python")
    _pe(environment_bin / "propka3.exe")
    propka = _script(environment_bin / "propka3", "/opt/env/bin/python")

    def found(name: str) -> str | None:
        return discover_tool(
            name, path_lookup=_no_path, candidate_directories=(environment_bin,)
        ).path

    assert found("mk_prepare_ligand") == str(ligand.resolve())
    assert found("mk_prepare_receptor") == str(receptor.resolve())
    assert found("propka3") == str(propka.resolve())
    assert found("pdb2pqr") is None


def test_runtime_directories_are_the_unresolved_active_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    environment = tmp_path / "venv"
    interpreter = environment / "bin" / "python"
    interpreter.parent.mkdir(parents=True)
    interpreter.symlink_to(shutil.which("python3") or "/usr/bin/python3")
    monkeypatch.setattr("sys.executable", str(interpreter))
    monkeypatch.setattr("sys.prefix", str(environment))

    assert discovery._runtime_candidate_directories() == (environment / "bin",)


# --- Explicit configuration ------------------------------------------------------------


def test_invalid_explicit_configuration_never_falls_back(tmp_path: Path) -> None:
    native_on_path = str(_elf(tmp_path / "path" / "vina"))

    def lookup(_: str) -> str:
        return native_on_path

    for configured in (
        _elf(tmp_path / "configured" / "vina", mode=0o644),
        _pe(tmp_path / "configured" / "vina-pe"),
        _elf(tmp_path / "configured" / "vina.exe"),
        tmp_path / "configured" / "missing",
    ):
        assert discover_vina(configured, path_lookup=lookup).available is False
        assert discover_tool("pdb2pqr", configured, path_lookup=lookup).available is False
        assert discover_autodock4(configured, path_lookup=lookup).available is False
    empty_directory = tmp_path / "empty"
    empty_directory.mkdir()
    assert discover_vina(empty_directory, path_lookup=lookup).available is False
    assert discover_p2rank(empty_directory, path_lookup=lookup).available is False


def test_configured_directory_resolves_native_names(tmp_path: Path) -> None:
    directory = tmp_path / "configured"
    _pe(directory / "pdb2pqr.exe")
    native = _script(directory / "pdb2pqr")

    discovered = discover_tool("pdb2pqr", directory, path_lookup=_no_path)

    assert discovered.path == str(native.resolve())


# --- Engines: identity evidence, never invented versions -------------------------------


def test_official_vina_linux_release_records_version_architecture_and_hash(
    tmp_path: Path,
) -> None:
    older = _elf(tmp_path / "tools" / "autodock-vina-1.2.5" / "vina_1.2.5_linux_x86_64")
    current_directory = tmp_path / "tools" / "autodock-vina-1.2.7"
    _pe(current_directory / "vina_1.2.7_win.exe")
    executable = _elf(current_directory / "vina_1.2.7_linux_x86_64")
    candidates = _portable_vina_candidate_directories(tmp_path)

    discovered = discover_vina(path_lookup=_no_path, candidate_directories=candidates)

    assert candidates == (current_directory, older.parent)
    assert discovered.available is True
    assert discovered.path == str(executable.resolve())
    assert discovered.version == "1.2.7"
    assert discovered.architecture == "x86_64"
    assert discovered.sha256 == hashlib.sha256(executable.read_bytes()).hexdigest()


def test_unversioned_vina_on_path_reports_no_version(tmp_path: Path) -> None:
    executable = _elf(tmp_path / "bin" / "vina", ARM64)

    discovered = discover_vina(path_lookup=lambda _: str(executable), candidate_directories=())

    assert discovered.path == str(executable.resolve())
    assert discovered.version is None
    assert discovered.architecture == "arm64"
    assert discovered.sha256 == hashlib.sha256(executable.read_bytes()).hexdigest()


def test_vina_version_comes_from_the_resolved_release_name(tmp_path: Path) -> None:
    release = _elf(tmp_path / "tools" / "autodock-vina-1.2.7" / "vina_1.2.7_linux_x86_64")
    link = tmp_path / "bin" / "vina"
    link.parent.mkdir()
    link.symlink_to(release)

    discovered = discover_vina(link)

    assert discovered.path == str(release.resolve())
    assert discovered.version == "1.2.7"


def test_configured_vina_directory_prefers_the_newest_release(tmp_path: Path) -> None:
    directory = tmp_path / "vina"
    _elf(directory / "vina")
    _elf(directory / "vina_1.2.5_linux_x86_64")
    newest = _elf(directory / "vina_1.2.7_linux_x86_64")
    _pe(directory / "vina_1.2.9_win.exe")

    assert discover_vina(directory, path_lookup=_no_path).path == str(newest.resolve())


def test_autodock_suite_linux_layout_is_discovered_with_binary_evidence(tmp_path: Path) -> None:
    binary_directory = tmp_path / "tools" / "autodocksuite-4.2.6" / "x86_64Linux2"
    autodock = _elf(binary_directory / "autodock4")
    autogrid = _elf(binary_directory / "autogrid4", ARM64)
    _pe(binary_directory / "autodock4.exe")
    candidates = _portable_autodock4_candidate_directories(tmp_path)

    discovered_autodock = discover_autodock4(path_lookup=_no_path, candidate_directories=candidates)
    discovered_autogrid = discover_autogrid4(path_lookup=_no_path, candidate_directories=candidates)

    assert binary_directory in candidates
    assert discovered_autodock.path == str(autodock.resolve())
    assert discovered_autodock.version == "4.2.6"
    assert discovered_autodock.architecture == "x86_64"
    assert discovered_autodock.sha256 == hashlib.sha256(autodock.read_bytes()).hexdigest()
    assert discovered_autogrid.path == str(autogrid.resolve())
    assert discovered_autogrid.architecture == "arm64"


def test_autodock_on_path_in_unversioned_location_has_no_version(tmp_path: Path) -> None:
    autogrid = _elf(tmp_path / "usr" / "bin" / "autogrid4")

    discovered = discover_autogrid4(path_lookup=lambda _: str(autogrid), candidate_directories=())

    assert discovered.available is True
    assert discovered.version is None
    assert discovered.sha256 is not None


def test_autodock_gpu_discovers_linux_elf_without_claiming_a_verified_version(
    tmp_path: Path,
) -> None:
    binary = _elf(tmp_path / "autodock-gpu-1.6" / "autodock_gpu_128wi")
    configured = discover_autodock_gpu(binary)
    from_path = discover_autodock_gpu(path_lookup=lambda _: str(binary), candidate_directories=())
    assert configured.available and from_path.available
    assert configured.path == str(binary.resolve())
    assert configured.architecture == "x86_64"
    assert configured.version is None
    assert configured.sha256 == hashlib.sha256(binary.read_bytes()).hexdigest()


def test_autodock_gpu_rejects_windows_scripts_and_wrong_architecture(tmp_path: Path) -> None:
    assert not discover_autodock_gpu(_pe(tmp_path / "renamed_gpu")).available
    assert not discover_autodock_gpu(_script(tmp_path / "script")).available
    assert not discover_autodock_gpu(_elf(tmp_path / "arm", ARM64)).available
    assert not discover_autodock_gpu(_elf(tmp_path / "not_executable", mode=0o644)).available


def test_autodock_gpu_configured_path_remains_authoritative(tmp_path: Path) -> None:
    fallback = _elf(tmp_path / "fallback")
    assert not discover_autodock_gpu(
        tmp_path / "missing", path_lookup=lambda _: str(fallback), candidate_directories=()
    ).available


def test_autodock_gpu_discovers_versioned_tools_directory(tmp_path: Path) -> None:
    binary = _elf(tmp_path / "tools" / "autodock-gpu-1.6" / "bin" / "autodock_gpu_128wi")
    directories = discovery._portable_autodock_gpu_candidate_directories(tmp_path)
    found = discover_autodock_gpu(path_lookup=_no_path, candidate_directories=directories)
    assert found.path == str(binary.resolve())


# --- P2Rank and Java ------------------------------------------------------------------


def test_p2rank_selects_the_shell_launcher_and_reads_its_release(tmp_path: Path) -> None:
    distribution = tmp_path / "tools" / "p2rank_2.5.1"
    launcher = _script(distribution / "prank", "/usr/bin/env bash")
    _script(distribution / "prank.bat", "/usr/bin/env bash")
    (distribution / "README.md").write_text(
        "synthetic P2Rank fixture release-2.5.1-green.svg", encoding="utf-8"
    )
    candidates = _portable_p2rank_candidate_directories(tmp_path)

    discovered = discover_p2rank(path_lookup=_no_path, candidate_directories=candidates)

    assert discovered.path == str(launcher.resolve())
    assert discovered.version == "2.5.1"


def test_p2rank_launcher_without_execute_permission_is_unavailable(tmp_path: Path) -> None:
    distribution = tmp_path / "tools" / "p2rank_2.5.1"
    _executable(distribution / "prank", b"#!/usr/bin/env bash\n", mode=0o644)

    discovered = discover_p2rank(
        path_lookup=_no_path,
        candidate_directories=_portable_p2rank_candidate_directories(tmp_path),
    )

    assert discovered.available is False


def _java_home(home: Path, version: str | None, machine: int = X86_64) -> Path:
    _elf(home / "bin" / "java", machine)
    if version is not None:
        (home / "release").write_text(f'JAVA_VERSION="{version}"\n', encoding="utf-8")
    return home


def test_java_on_path_resolves_through_symlinks_to_a_compatible_home(tmp_path: Path) -> None:
    home = _java_home(tmp_path / "jvm" / "java-21-openjdk-amd64", "21.0.5")
    alternative = tmp_path / "alternatives" / "java"
    alternative.parent.mkdir()
    alternative.symlink_to(home / "bin" / "java")
    on_path = tmp_path / "usr" / "bin" / "java"
    on_path.parent.mkdir(parents=True)
    on_path.symlink_to(alternative)

    assert discover_java_home(path_lookup=lambda _: str(on_path)) == home.resolve()


@pytest.mark.parametrize(
    ("version", "compatible"),
    [
        ("1.8.0_472", False),
        ("11.0.25", False),
        ("17.0.13", True),
        ("23.0.1", True),
        ("24", False),
        (None, False),
    ],
)
def test_java_compatibility_requires_release_metadata_17_to_23(
    tmp_path: Path, version: str | None, compatible: bool
) -> None:
    home = _java_home(tmp_path / "jdk", version)

    discovered = discover_java_home(path_lookup=_no_path, candidate_homes=(home,))

    assert discovered == (home.resolve() if compatible else None)


def test_incompatible_java_on_path_falls_to_named_tools_homes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    old = _java_home(tmp_path / "jvm" / "java-11", "11.0.25")
    _java_home(tmp_path / "home" / "tools" / "jdk-17.0.13+11", "17.0.13")
    newest = _java_home(tmp_path / "home" / "tools" / "jdk-21.0.5+11", "21.0.5")
    _java_home(tmp_path / "home" / "tools" / "openjdk-22", "22.0.2")
    monkeypatch.setattr("sys.prefix", str(tmp_path / "empty-prefix"))
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")

    discovered = discover_java_home(path_lookup=lambda _: str(old / "bin" / "java"))

    assert discovered == newest.resolve()


def test_explicit_java_home_is_authoritative(tmp_path: Path) -> None:
    configured = _java_home(tmp_path / "java-11", "11.0.25")
    compatible = _java_home(tmp_path / "jdk-21", "21.0.5")

    assert (
        discover_java_home(
            configured,
            path_lookup=lambda _: str(compatible / "bin" / "java"),
            candidate_homes=(compatible,),
        )
        is None
    )
    assert discover_java_home(compatible, path_lookup=_no_path) == compatible.resolve()


def test_windows_java_is_never_a_linux_java_home(tmp_path: Path) -> None:
    home = tmp_path / "jdk-21"
    _pe(home / "bin" / "java")
    (home / "release").write_text('JAVA_VERSION="21.0.5"\n', encoding="utf-8")
    _executable(home / "bin" / "java.exe", b"MZ")

    assert discover_java_home(path_lookup=_no_path, candidate_homes=(home,)) is None


# --- Frozen payload ---------------------------------------------------------------------


def test_frozen_windows_payload_is_not_reported_as_linux_supported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload_binary = _pe(tmp_path / "tools" / "vina.exe")
    java = _pe(tmp_path / "tools" / "java" / "bin" / "java.exe")
    monkeypatch.setattr("sys.frozen", True, raising=False)
    monkeypatch.setattr(
        discovery,
        "bundled_tool",
        lambda name: (java, "21.0.5") if name == "java" else (payload_binary, "1.2.7"),
    )

    assert discover_vina().available is False
    assert discover_autogrid4().available is False
    assert discover_autodock4().available is False
    assert discover_autodock_gpu().available is False
    assert discover_p2rank().available is False
    assert discover_java_home() is None
