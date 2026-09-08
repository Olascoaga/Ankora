"""Discover configured executables without running them."""

import os
import re
import shutil
import sys
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from hashlib import sha256
from importlib import metadata, util
from pathlib import Path, PureWindowsPath


@dataclass(frozen=True, slots=True)
class DiscoveredTool:
    available: bool
    path: str | None
    version: str | None = None
    architecture: str | None = None
    sha256: str | None = None


_P2RANK_RELEASE_PATTERN = re.compile(r"release-(\d+(?:\.\d+)+)-", re.IGNORECASE)
_P2RANK_DIRECTORY_PATTERN = re.compile(r"^p2rank(?:[_-])?(\d+(?:\.\d+)*)$", re.IGNORECASE)
_VINA_DIRECTORY_PATTERN = re.compile(
    r"^(?:autodock[-_])?vina(?:[-_])?(\d+(?:\.\d+)*)$", re.IGNORECASE
)
_VINA_EXECUTABLE_PATTERN = re.compile(
    r"^vina(?:[_-])(\d+(?:\.\d+)+)(?:[_-]win)?\.exe$", re.IGNORECASE
)
_AUTODOCK4_DIRECTORY_PATTERN = re.compile(
    r"^autodock(?:suite|4)?[-_]?(\d+(?:\.\d+)*)$", re.IGNORECASE
)
_AUTODOCK_GPU_DIRECTORY_PATTERN = re.compile(
    r"^(?:autodock[-_]?gpu|adgpu)[-_]?(?:v)?(\d+(?:\.\d+)*)$", re.IGNORECASE
)
_AUTODOCK_GPU_EXECUTABLE_PATTERN = re.compile(
    r"^(?:autodock[-_]?gpu|autodock_gpu_\d+wi|adgpu(?:-v\d+(?:\.\d+)*)?[^/]*)\.exe$",
    re.IGNORECASE,
)
_JAVA_DIRECTORY_PATTERN = re.compile(r"^(?:jdk|jre)[-_]?(\d+(?:\.\d+)*)", re.IGNORECASE)
_JAVA_RELEASE_PATTERN = re.compile(r'^JAVA_VERSION="([^"]+)"$', re.MULTILINE)
_P2RANK_JAVA_MAJOR_RANGE = range(17, 24)
_PACKAGED_PYTHON_TOOLS = {
    "mk_prepare_ligand": ("meeko", "meeko"),
    "mk_prepare_receptor": ("meeko", "meeko"),
    "pdb2pqr": ("pdb2pqr", "pdb2pqr"),
    "propka3": ("propka", "propka"),
}


def build_windows_candidate(
    directory: PureWindowsPath, tool_name: str, extension: str = "exe"
) -> PureWindowsPath:
    """Build an explicit Windows executable path without shell concatenation."""
    return directory / f"{tool_name}.{extension}"


def _configured_candidate(configured_path: str | Path, tool_name: str, extension: str) -> Path:
    path = Path(configured_path).expanduser()
    if path.is_dir():
        return path / f"{tool_name}.{extension}"
    return path


def discover_tool(
    tool_name: str,
    configured_path: str | Path | None = None,
    *,
    extension: str = "exe",
    path_lookup: Callable[[str], str | None] = shutil.which,
    candidate_directories: Iterable[Path] | None = None,
) -> DiscoveredTool:
    """Find a tool by explicit path, PATH, or this Python runtime; never execute it.

    `extension` covers launchers that are not `.exe` (e.g. P2Rank ships as
    `prank.bat`, which Windows cannot launch directly without `cmd /c`).
    """
    candidate: Path | None = None
    if configured_path:
        candidate = _configured_candidate(configured_path, tool_name, extension)
    else:
        located = path_lookup(f"{tool_name}.{extension}") or path_lookup(tool_name)
        if located:
            candidate = Path(located)
        else:
            directories = (
                _runtime_candidate_directories()
                if candidate_directories is None
                else candidate_directories
            )
            for directory in directories:
                for filename in (f"{tool_name}.{extension}", tool_name):
                    runtime_candidate = directory / filename
                    if runtime_candidate.is_file():
                        candidate = runtime_candidate
                        break
                if candidate is not None:
                    break

    if candidate is None:
        packaged_distribution = _PACKAGED_PYTHON_TOOLS.get(tool_name)
        if packaged_distribution is not None and getattr(sys, "frozen", False):
            distribution, module = packaged_distribution
            if discover_python_package(distribution, module).available:
                candidate = Path(sys.executable)

    if candidate is None or not candidate.is_file():
        return DiscoveredTool(available=False, path=None)

    return DiscoveredTool(available=True, path=str(candidate.resolve()))


def packaged_console_arguments(
    *, executable: str, worker: str, arguments: list[str]
) -> list[str]:
    """Route a bundled console tool through Ankora's frozen executable."""
    if getattr(sys, "frozen", False) and Path(executable).resolve() == Path(
        sys.executable
    ).resolve():
        return ["--worker", worker, *arguments]
    return arguments


def python_worker_arguments(
    *, worker: str, module: str, arguments: list[str]
) -> list[str]:
    """Build a worker command for source and frozen Python runtimes."""
    if getattr(sys, "frozen", False):
        return ["--worker", worker, *arguments]
    return ["-m", module, *arguments]


def discover_p2rank(
    configured_path: str | Path | None = None,
    *,
    path_lookup: Callable[[str], str | None] = shutil.which,
    candidate_directories: Iterable[Path] | None = None,
) -> DiscoveredTool:
    """Discover a portable P2Rank distribution without executing it.

    P2Rank has no Windows installer and does not add ``prank.bat`` to PATH.
    In addition to normal discovery, Ankora therefore checks versioned
    distributions directly below the user's conventional ``tools`` folder.
    An explicit configured path remains authoritative when supplied.
    """
    directories = candidate_directories
    if configured_path is None and directories is None:
        directories = (
            *_runtime_candidate_directories(),
            *_portable_p2rank_candidate_directories(Path.home()),
        )
    discovered = discover_tool(
        "prank",
        configured_path,
        extension="bat",
        path_lookup=path_lookup,
        candidate_directories=directories,
    )
    if not discovered.available or discovered.path is None:
        return discovered
    executable = Path(discovered.path)
    return DiscoveredTool(
        available=True,
        path=discovered.path,
        version=_read_p2rank_version(executable),
    )


def discover_vina(
    configured_path: str | Path | None = None,
    *,
    path_lookup: Callable[[str], str | None] = shutil.which,
    candidate_directories: Iterable[Path] | None = None,
) -> DiscoveredTool:
    """Discover AutoDock Vina, including its versioned portable Windows build.

    The official Windows release is named ``vina_<version>_win.exe`` rather
    than ``vina.exe`` and is commonly unpacked below ``~/tools``. Explicit
    configuration remains authoritative; portable discovery is deliberately
    constrained to Vina-named directories and executable names.
    """
    if configured_path:
        configured = Path(configured_path).expanduser()
        if configured.is_dir():
            candidates = _vina_executables_in(configured)
            executable = candidates[0] if candidates else configured / "vina.exe"
        else:
            executable = configured
        return _vina_discovery_result(executable)

    located = path_lookup("vina.exe") or path_lookup("vina")
    if located:
        return _vina_discovery_result(Path(located))

    directories = candidate_directories
    if directories is None:
        directories = (
            *_runtime_candidate_directories(),
            *_portable_vina_candidate_directories(Path.home()),
        )
    for directory in directories:
        candidates = _vina_executables_in(directory)
        if candidates:
            return _vina_discovery_result(candidates[0])
    return DiscoveredTool(available=False, path=None, version=None)


def discover_autodock4(
    configured_path: str | Path | None = None,
    *,
    path_lookup: Callable[[str], str | None] = shutil.which,
    candidate_directories: Iterable[Path] | None = None,
) -> DiscoveredTool:
    """Discover the legacy AutoDock4 CPU executable without launching it."""
    directories = candidate_directories
    if configured_path is None and directories is None:
        directories = (
            *_runtime_candidate_directories(),
            *_portable_autodock4_candidate_directories(Path.home()),
        )
    return _discover_autodock_binary(
        configured_path,
        executable_names=("autodock4.exe",),
        path_lookup=path_lookup,
        candidate_directories=directories or (),
        directory_pattern=_AUTODOCK4_DIRECTORY_PATTERN,
    )


def discover_autogrid4(
    configured_path: str | Path | None = None,
    *,
    path_lookup: Callable[[str], str | None] = shutil.which,
    candidate_directories: Iterable[Path] | None = None,
) -> DiscoveredTool:
    """Discover the AutoGrid4 executable shared by CPU and GPU docking."""
    directories = candidate_directories
    if configured_path is None and directories is None:
        directories = (
            *_runtime_candidate_directories(),
            *_portable_autodock4_candidate_directories(Path.home()),
        )
    return _discover_autodock_binary(
        configured_path,
        executable_names=("autogrid4.exe",),
        path_lookup=path_lookup,
        candidate_directories=directories or (),
        directory_pattern=_AUTODOCK4_DIRECTORY_PATTERN,
    )


def discover_autodock_gpu(
    configured_path: str | Path | None = None,
    *,
    path_lookup: Callable[[str], str | None] = shutil.which,
    candidate_directories: Iterable[Path] | None = None,
) -> DiscoveredTool:
    """Discover official-style AutoDock-GPU Windows executables side-effect-free."""
    directories = candidate_directories
    if configured_path is None and directories is None:
        directories = (
            *_runtime_candidate_directories(),
            *_portable_autodock_gpu_candidate_directories(Path.home()),
        )
    return _discover_autodock_binary(
        configured_path,
        executable_names=(
            "AutoDock-GPU.exe",
            "autodock_gpu_128wi.exe",
            "autodock_gpu_64wi.exe",
        ),
        path_lookup=path_lookup,
        candidate_directories=directories or (),
        directory_pattern=_AUTODOCK_GPU_DIRECTORY_PATTERN,
        executable_pattern=_AUTODOCK_GPU_EXECUTABLE_PATTERN,
    )


def discover_java_home(
    configured_home: str | Path | None = None,
    *,
    path_lookup: Callable[[str], str | None] = shutil.which,
    candidate_homes: Iterable[Path] | None = None,
) -> Path | None:
    """Resolve a Java home suitable for P2Rank without launching Java."""
    if configured_home:
        home = Path(configured_home).expanduser()
        if _is_p2rank_compatible_java_home(home):
            return home.resolve()
    located = path_lookup("java.exe") or path_lookup("java")
    if located:
        executable = Path(located).resolve()
        home = executable.parent.parent
        if _is_p2rank_compatible_java_home(home):
            return home
    homes = _windows_java_candidate_homes() if candidate_homes is None else candidate_homes
    for home in homes:
        if _is_p2rank_compatible_java_home(home):
            return home.resolve()
    return None


def _portable_p2rank_candidate_directories(home: Path) -> tuple[Path, ...]:
    tools_root = home / "tools"
    if not tools_root.is_dir():
        return ()
    candidates = [
        path
        for path in tools_root.iterdir()
        if path.is_dir() and path.name.lower().startswith("p2rank")
    ]
    candidates.sort(key=_p2rank_directory_version, reverse=True)
    return tuple(candidates)


def _portable_vina_candidate_directories(home: Path) -> tuple[Path, ...]:
    tools_root = home / "tools"
    if not tools_root.is_dir():
        return ()
    candidates = [
        path
        for path in tools_root.iterdir()
        if path.is_dir() and _VINA_DIRECTORY_PATTERN.match(path.name)
    ]
    candidates.sort(key=_vina_directory_version, reverse=True)
    return tuple(candidates)


def _portable_autodock4_candidate_directories(home: Path) -> tuple[Path, ...]:
    return _portable_autodock_candidate_directories(home, _AUTODOCK4_DIRECTORY_PATTERN)


def _portable_autodock_gpu_candidate_directories(home: Path) -> tuple[Path, ...]:
    return _portable_autodock_candidate_directories(home, _AUTODOCK_GPU_DIRECTORY_PATTERN)


def _portable_autodock_candidate_directories(
    home: Path, directory_pattern: re.Pattern[str]
) -> tuple[Path, ...]:
    tools_root = home / "tools"
    if not tools_root.is_dir():
        return ()
    roots = [
        path
        for path in tools_root.iterdir()
        if path.is_dir() and directory_pattern.match(path.name)
    ]
    roots.sort(
        key=lambda path: _version_from_match(directory_pattern.match(path.name)),
        reverse=True,
    )
    candidates: list[Path] = []
    for root in roots:
        candidates.extend((root, root / "bin", root / "windows", root / "x86", root / "x64"))
    return tuple(path for path in candidates if path.is_dir())


def _discover_autodock_binary(
    configured_path: str | Path | None,
    *,
    executable_names: tuple[str, ...],
    path_lookup: Callable[[str], str | None],
    candidate_directories: Iterable[Path],
    directory_pattern: re.Pattern[str],
    executable_pattern: re.Pattern[str] | None = None,
) -> DiscoveredTool:
    candidates: list[Path] = []
    if configured_path:
        configured = Path(configured_path).expanduser()
        candidates = (
            _autodock_executables_in(configured, executable_names, executable_pattern)
            if configured.is_dir()
            else [configured]
        )
    else:
        for name in executable_names:
            located = path_lookup(name) or path_lookup(Path(name).stem)
            if located:
                candidates.append(Path(located))
                break
        if not candidates:
            for directory in candidate_directories:
                candidates.extend(
                    _autodock_executables_in(directory, executable_names, executable_pattern)
                )
                if candidates:
                    break
    if not candidates:
        return DiscoveredTool(available=False, path=None)
    executable = candidates[0]
    if not executable.is_file():
        return DiscoveredTool(available=False, path=None)
    resolved = executable.resolve()
    return DiscoveredTool(
        available=True,
        path=str(resolved),
        version=_autodock_version_from_path(resolved, directory_pattern),
        architecture=_read_pe_architecture(resolved),
        sha256=_file_sha256(resolved),
    )


def _autodock_executables_in(
    path: Path,
    executable_names: tuple[str, ...],
    executable_pattern: re.Pattern[str] | None,
) -> list[Path]:
    if not path.is_dir():
        return []
    candidates = [path / name for name in executable_names]
    if executable_pattern is not None:
        try:
            candidates.extend(
                child
                for child in path.iterdir()
                if child.is_file() and executable_pattern.match(child.name)
            )
        except OSError:
            return []
    return list(dict.fromkeys(candidate for candidate in candidates if candidate.is_file()))


def _autodock_version_from_path(path: Path, pattern: re.Pattern[str]) -> str | None:
    for parent in (path.parent, path.parent.parent):
        match = pattern.match(parent.name)
        if match is not None:
            return match.group(1)
    match = re.search(r"(?:^|[-_])v?(\d+(?:\.\d+)+)(?:[-_]|\.)", path.name)
    return match.group(1) if match is not None else None


def _version_from_match(match: re.Match[str] | None) -> tuple[int, ...]:
    if match is None:
        return ()
    return tuple(int(part) for part in match.group(1).split("."))


def _read_pe_architecture(executable: Path) -> str | None:
    machine_names = {0x014C: "x86", 0x8664: "x86_64", 0xAA64: "arm64"}
    try:
        with executable.open("rb") as stream:
            if stream.read(2) != b"MZ":
                return None
            stream.seek(0x3C)
            pe_offset_bytes = stream.read(4)
            if len(pe_offset_bytes) != 4:
                return None
            pe_offset = int.from_bytes(pe_offset_bytes, byteorder="little")
            stream.seek(pe_offset)
            if stream.read(4) != b"PE\x00\x00":
                return None
            machine_bytes = stream.read(2)
    except OSError:
        return None
    if len(machine_bytes) != 2:
        return None
    return machine_names.get(int.from_bytes(machine_bytes, byteorder="little"), "unknown")


def _file_sha256(path: Path) -> str | None:
    digest = sha256()
    try:
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError:
        return None
    return digest.hexdigest()


def _vina_directory_version(path: Path) -> tuple[int, ...]:
    match = _VINA_DIRECTORY_PATTERN.match(path.name)
    if match is None:
        return ()
    return tuple(int(part) for part in match.group(1).split("."))


def _vina_executables_in(directory: Path) -> list[Path]:
    if not directory.is_dir():
        return []
    candidates = [directory / "vina.exe"]
    try:
        candidates.extend(
            path
            for path in directory.iterdir()
            if path.is_file() and _VINA_EXECUTABLE_PATTERN.match(path.name)
        )
    except OSError:
        return []
    available = [path for path in candidates if path.is_file()]
    available.sort(key=_vina_executable_version, reverse=True)
    return available


def _vina_executable_version(path: Path) -> tuple[int, ...]:
    match = _VINA_EXECUTABLE_PATTERN.match(path.name)
    if match is None:
        return ()
    return tuple(int(part) for part in match.group(1).split("."))


def _vina_discovery_result(executable: Path) -> DiscoveredTool:
    if not executable.is_file():
        return DiscoveredTool(available=False, path=None, version=None)
    match = _VINA_EXECUTABLE_PATTERN.match(executable.name)
    version = match.group(1) if match is not None else None
    return DiscoveredTool(available=True, path=str(executable.resolve()), version=version)


def _p2rank_directory_version(path: Path) -> tuple[int, ...]:
    match = _P2RANK_DIRECTORY_PATTERN.match(path.name)
    if match is None:
        return ()
    return tuple(int(part) for part in match.group(1).split("."))


def _read_p2rank_version(executable: Path) -> str | None:
    readme = executable.parent / "README.md"
    if readme.is_file():
        content = readme.read_text(encoding="utf-8", errors="replace")
        match = _P2RANK_RELEASE_PATTERN.search(content)
        if match is not None:
            return match.group(1)
    match = _P2RANK_DIRECTORY_PATTERN.match(executable.parent.name)
    return match.group(1) if match is not None else None


def _windows_java_candidate_homes() -> tuple[Path, ...]:
    install_roots: list[Path] = []
    for variable in ("ProgramW6432", "ProgramFiles", "ProgramFiles(x86)"):
        value = os.getenv(variable)
        if value:
            install_roots.append(Path(value))
    local_app_data = os.getenv("LOCALAPPDATA")
    if local_app_data:
        install_roots.append(Path(local_app_data) / "Programs")
    if not install_roots and os.name == "nt":
        system_drive = os.getenv("SYSTEMDRIVE")
        if system_drive:
            install_roots.append(Path(system_drive) / "Program Files")

    vendor_roots = tuple(
        root / vendor
        for root in dict.fromkeys(install_roots)
        for vendor in (
            "Eclipse Adoptium",
            "Java",
            "Microsoft",
            "Amazon Corretto",
            "BellSoft",
            "Zulu",
        )
    )
    candidates: list[Path] = []
    for vendor_root in vendor_roots:
        if not vendor_root.is_dir():
            continue
        if (vendor_root / "bin" / "java.exe").is_file():
            candidates.append(vendor_root)
        try:
            candidates.extend(
                child
                for child in vendor_root.iterdir()
                if child.is_dir() and (child / "bin" / "java.exe").is_file()
            )
        except OSError:
            continue
    candidates.sort(key=_java_home_version, reverse=True)
    return tuple(dict.fromkeys(candidates))


def _java_home_version(home: Path) -> tuple[int, ...]:
    release_version = _read_java_release_version(home)
    version = release_version
    if version is None:
        match = _JAVA_DIRECTORY_PATTERN.match(home.name)
        version = match.group(1) if match is not None else None
    if version is None:
        return ()
    return tuple(int(part) for part in re.findall(r"\d+", version))


def _read_java_release_version(home: Path) -> str | None:
    release = home / "release"
    if not release.is_file():
        return None
    try:
        content = release.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    match = _JAVA_RELEASE_PATTERN.search(content)
    return match.group(1) if match is not None else None


def _is_p2rank_compatible_java_home(home: Path) -> bool:
    if not (home / "bin" / "java.exe").is_file():
        return False
    version = _read_java_release_version(home)
    if version is None:
        return True
    numbers = re.findall(r"\d+", version)
    if not numbers:
        return True
    major = int(numbers[1] if numbers[0] == "1" and len(numbers) > 1 else numbers[0])
    return major in _P2RANK_JAVA_MAJOR_RANGE


def _runtime_candidate_directories() -> tuple[Path, ...]:
    """Return executable directories belonging to the active Python environment."""
    executable_directory = Path(sys.executable).resolve().parent
    prefix = Path(sys.prefix).resolve()
    candidates = (
        executable_directory,
        prefix,
        prefix / "Scripts",
        prefix / "Library" / "bin",
        prefix / "bin",
    )
    return tuple(dict.fromkeys(candidates))


def discover_python_package(distribution: str, module: str) -> DiscoveredTool:
    """Discover an importable scientific package without importing or executing it."""
    specification = util.find_spec(module)
    if specification is None or specification.origin is None:
        return DiscoveredTool(available=False, path=None, version=None)
    try:
        package_version = metadata.version(distribution)
    except metadata.PackageNotFoundError:
        package_version = None
    return DiscoveredTool(
        available=True,
        path=str(Path(specification.origin).resolve()),
        version=package_version,
    )
