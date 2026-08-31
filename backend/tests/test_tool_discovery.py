from pathlib import Path, PureWindowsPath

from ankora_backend.adapters.tools.discovery import (
    _portable_autodock4_candidate_directories,
    _portable_autodock_gpu_candidate_directories,
    _portable_p2rank_candidate_directories,
    _portable_vina_candidate_directories,
    build_windows_candidate,
    discover_autodock4,
    discover_autodock_gpu,
    discover_autogrid4,
    discover_java_home,
    discover_p2rank,
    discover_tool,
    discover_vina,
)


def _write_synthetic_pe(executable: Path, machine: int = 0x8664) -> None:
    """Write only the PE headers needed for side-effect-free architecture tests."""
    content = bytearray(512)
    content[0:2] = b"MZ"
    content[0x3C:0x40] = (128).to_bytes(4, byteorder="little")
    content[128:132] = b"PE\x00\x00"
    content[132:134] = machine.to_bytes(2, byteorder="little")
    executable.write_bytes(content)


def test_missing_tool_is_reported_without_execution() -> None:
    discovered = discover_tool(
        "vina", path_lookup=lambda _: None, candidate_directories=()
    )

    assert discovered.available is False
    assert discovered.path is None


def test_configured_executable_is_discovered(tmp_path) -> None:  # type: ignore[no-untyped-def]
    executable = tmp_path / "vina.exe"
    executable.write_bytes(b"synthetic fixture; never executed")

    discovered = discover_tool("vina", executable)

    assert discovered.available is True
    assert discovered.path == str(executable.resolve())


def test_configured_directory_resolves_windows_executable(tmp_path) -> None:  # type: ignore[no-untyped-def]
    executable = tmp_path / "gnina.exe"
    executable.write_bytes(b"synthetic fixture; never executed")

    discovered = discover_tool("gnina", tmp_path)

    assert discovered.available is True
    assert discovered.path == str(executable.resolve())


def test_windows_path_candidate_uses_exe_suffix() -> None:
    candidate = build_windows_candidate(PureWindowsPath(r"Scientific Tools\Vina"), "vina")

    assert candidate == PureWindowsPath(r"Scientific Tools\Vina\vina.exe")


def test_active_python_environment_scripts_are_discovered(tmp_path) -> None:  # type: ignore[no-untyped-def]
    scripts = tmp_path / "Scripts"
    scripts.mkdir()
    executable = scripts / "mk_prepare_ligand.exe"
    executable.write_bytes(b"synthetic fixture; never executed")

    discovered = discover_tool(
        "mk_prepare_ligand",
        path_lookup=lambda _: None,
        candidate_directories=(scripts,),
    )

    assert discovered.available is True
    assert discovered.path == str(executable.resolve())


def test_portable_p2rank_distribution_is_discovered_and_versioned(tmp_path: Path) -> None:
    older = tmp_path / "tools" / "p2rank_2.9.0"
    current = tmp_path / "tools" / "p2rank_2.10.1"
    older.mkdir(parents=True)
    current.mkdir()
    (older / "prank.bat").write_text("synthetic fixture; never executed", encoding="utf-8")
    executable = current / "prank.bat"
    executable.write_text("synthetic fixture; never executed", encoding="utf-8")
    (current / "README.md").write_text(
        "synthetic P2Rank fixture release-2.10.1-green.svg",
        encoding="utf-8",
    )

    candidates = _portable_p2rank_candidate_directories(tmp_path)
    discovered = discover_p2rank(
        path_lookup=lambda _: None,
        candidate_directories=candidates,
    )

    assert candidates == (current, older)
    assert discovered.available is True
    assert discovered.path == str(executable.resolve())
    assert discovered.version == "2.10.1"


def test_portable_vina_release_is_discovered_and_versioned(tmp_path: Path) -> None:
    older = tmp_path / "tools" / "autodock-vina-1.2.5"
    current = tmp_path / "tools" / "autodock-vina-1.2.7"
    older.mkdir(parents=True)
    current.mkdir()
    (older / "vina_1.2.5_win.exe").write_bytes(b"synthetic fixture; never executed")
    executable = current / "vina_1.2.7_win.exe"
    executable.write_bytes(b"synthetic fixture; never executed")

    candidates = _portable_vina_candidate_directories(tmp_path)
    discovered = discover_vina(
        path_lookup=lambda _: None,
        candidate_directories=candidates,
    )

    assert candidates == (current, older)
    assert discovered.available is True
    assert discovered.path == str(executable.resolve())
    assert discovered.version == "1.2.7"


def test_portable_autodock4_toolchain_is_discovered_with_binary_evidence(
    tmp_path: Path,
) -> None:
    binary_directory = tmp_path / "tools" / "autodock4-4.2.6" / "bin"
    binary_directory.mkdir(parents=True)
    autodock = binary_directory / "autodock4.exe"
    autogrid = binary_directory / "autogrid4.exe"
    _write_synthetic_pe(autodock, 0x014C)
    _write_synthetic_pe(autogrid, 0x014C)
    candidates = _portable_autodock4_candidate_directories(tmp_path)

    discovered_autodock = discover_autodock4(
        path_lookup=lambda _: None, candidate_directories=candidates
    )
    discovered_autogrid = discover_autogrid4(
        path_lookup=lambda _: None, candidate_directories=candidates
    )

    assert discovered_autodock.path == str(autodock.resolve())
    assert discovered_autodock.version == "4.2.6"
    assert discovered_autodock.architecture == "x86"
    assert discovered_autodock.sha256 is not None
    assert discovered_autogrid.path == str(autogrid.resolve())
    assert discovered_autogrid.architecture == "x86"


def test_portable_autodock_gpu_is_discovered_without_launching_it(tmp_path: Path) -> None:
    binary_directory = tmp_path / "tools" / "autodock-gpu-1.6" / "bin"
    binary_directory.mkdir(parents=True)
    executable = binary_directory / "adgpu-v1.6_windows_ocl_128wi.exe"
    _write_synthetic_pe(executable)
    candidates = _portable_autodock_gpu_candidate_directories(tmp_path)

    discovered = discover_autodock_gpu(
        path_lookup=lambda _: None, candidate_directories=candidates
    )

    assert discovered.path == str(executable.resolve())
    assert discovered.version == "1.6"
    assert discovered.architecture == "x86_64"
    assert discovered.sha256 is not None


def test_java_home_is_derived_from_java_on_path(tmp_path: Path) -> None:
    java_home = tmp_path / "jdk-21"
    executable = java_home / "bin" / "java.exe"
    executable.parent.mkdir(parents=True)
    executable.write_bytes(b"synthetic fixture; never executed")

    discovered = discover_java_home(path_lookup=lambda _: str(executable))

    assert discovered == java_home.resolve()


def test_java_home_falls_back_to_a_compatible_windows_installation(
    tmp_path: Path,
) -> None:
    incompatible = tmp_path / "jre-8"
    compatible = tmp_path / "jre-21.0.12"
    for home, version in ((incompatible, "1.8.0_472"), (compatible, "21.0.12")):
        executable = home / "bin" / "java.exe"
        executable.parent.mkdir(parents=True)
        executable.write_bytes(b"synthetic fixture; never executed")
        (home / "release").write_text(
            f'JAVA_VERSION="{version}"\n',
            encoding="utf-8",
        )

    discovered = discover_java_home(
        tmp_path / "stale-java-home",
        path_lookup=lambda _: None,
        candidate_homes=(incompatible, compatible),
    )

    assert discovered == compatible.resolve()
