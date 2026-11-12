"""Build the offline Linux .deb installer, portable .tar.zst, and release manifest (ADR-029 D3)."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tarfile
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.complete_linux_legal import verify_complete_linux_legal

DESKTOP_DIR = REPO_ROOT / "apps" / "desktop"
TAURI_DIR = DESKTOP_DIR / "src-tauri"
RELEASE_TAURI_CONFIG = TAURI_DIR / "tauri.linux.release.conf.json"
ICONS_DIR = TAURI_DIR / "icons"
DEFAULT_BUILD_ROOT = REPO_ROOT / "build" / "linux-runtime"

FORBIDDEN_PAYLOAD_PREFIXES = (
    "gnina",
    "libcuda.so",
    "libnvidia-ml.so",
    "libnvidia-ptxjitcompiler.so",
    "libcudnn",
    "libcublas",
)

DEB_LAUNCHER_SCRIPT = """#!/bin/sh
set -eu
exec /usr/lib/ankora/ankora-desktop "$@"
"""

PORTABLE_LAUNCHER_SCRIPT = """#!/bin/sh
set -eu
HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
exec "$HERE/ankora-desktop" "$@"
"""

PORTABLE_README_TEXT = """Ankora 0.1.0 — Portable Offline Linux Edition (x86_64)
======================================================

Zero-sudo launch (Ubuntu 24.04 LTS / Linux Mint 22 / Pop!_OS / Debian):
  ./ankora

Included offline Core scientific engines & runtimes:
  - Bundled Python 3.12.13 scientific backend (RDKit, OpenMM CPU, PDBFixer,
    PDB2PQR, PROPKA, Meeko, Dimorphite-DL, MDAnalysis, ProLIF)
  - AutoDock Vina 1.2.7
  - AutoGrid4 & AutoDock4 4.2.6
  - AutoDock-GPU 1.6 (multi-arch CUDA fatbin sm_75..sm_120 + PTX)
  - Eclipse Temurin OpenJDK 21.0.12.1+1 & P2Rank 2.5.1

Optional GNINA 1.3.3 + CUDA 12.8 / cuDNN 9.25 Offline Pack:
  Open Ankora -> Docking (GNINA) or Tools -> Scientific tools -> click
  "Import offline GNINA pack..." and select Ankora_0.1.0_gnina-cuda12-pack.tar.zst.

Third-party licenses and GPL/LGPL source code availability:
  See ./legal/INSTALLATION_TERMS.txt and ./legal/SOURCE_AVAILABILITY.txt.
"""

DESKTOP_ENTRY_TEXT = """[Desktop Entry]
Version=1.0
Type=Application
Name=Ankora
GenericName=Molecular Docking Workbench
Comment=Scientist-controlled offline molecular docking workbench
Exec=/usr/bin/ankora
Icon=ankora
Terminal=false
Categories=Science;Chemistry;Biology;Education;
StartupNotify=true
StartupWMClass=ankora-desktop
"""


def _sha256_and_size(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    total = 0
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
            total += len(chunk)
    return digest.hexdigest(), total


def _verify_elf_x86_64_no_home_rpath(executable: Path) -> list[str]:
    if not executable.is_file() or not os.access(executable, os.X_OK):
        raise ValueError(f"Missing or non-executable Linux binary: {executable}")
    with executable.open("rb") as handle:
        header = handle.read(20)
    if len(header) < 20 or header[:4] != b"\x7fELF" or header[4] != 2 or header[5] != 1:
        raise ValueError(f"Not a 64-bit little-endian ELF binary: {executable}")
    machine = int.from_bytes(header[18:20], byteorder="little")
    if machine != 0x3E:
        raise ValueError(f"Expected x86_64 ELF (0x3e), got {hex(machine)}: {executable}")

    readelf = shutil.which("readelf") or "/usr/bin/readelf"
    proc = subprocess.run(
        [readelf, "-d", str(executable)],
        capture_output=True,
        text=True,
        check=True,
    )
    needed: list[str] = []
    for line in proc.stdout.splitlines():
        if ("(RPATH)" in line or "(RUNPATH)" in line) and (
            "/home/" in line or "/tmp/" in line or "/mnt/" in line
        ):
            raise ValueError(
                f"Release binary embeds non-portable host RPATH/RUNPATH ({executable}): {line}"
            )
        m = re.search(r"\(NEEDED\)\s+Shared library:\s+\[([^\]]+)\]", line)
        if m:
            needed.append(m.group(1))
    return needed


def _resolve_zstd_executable() -> str:
    sibling = Path(sys.executable).resolve().parent / "zstd"
    if sibling.is_file():
        return str(sibling)
    found = shutil.which("zstd")
    if found:
        return found
    raise FileNotFoundError("zstd CLI executable not found on PATH or beside sys.executable.")


def _link_or_copy(src: Path, dst: Path) -> None:
    if dst.exists() or dst.is_symlink():
        dst.unlink()
    try:
        os.link(src, dst)
    except OSError:
        shutil.copy2(src, dst)


def _copy_tree_preserving_intra_symlinks(src: Path, dst: Path) -> None:
    """Copy a directory tree preserving intra-tree relative symlinks while rejecting escapes."""
    src_root = src.resolve(strict=True)
    if dst.exists() or dst.is_symlink():
        shutil.rmtree(dst)
    shutil.copytree(src_root, dst, symlinks=True)

    dst_root = dst.resolve(strict=True)
    for root, dirs, files in os.walk(dst_root, followlinks=False):
        root_path = Path(root)
        os.chmod(root_path, 0o755)
        for name in [*dirs, *files]:
            item = root_path / name
            if item.is_symlink():
                raw_target = os.readlink(item)
                if os.path.isabs(raw_target):
                    raise ValueError(f"Absolute symlink forbidden inside packaged tree: {item}")
                resolved_target = (item.parent / raw_target).resolve(strict=True)
                if not resolved_target.is_relative_to(dst_root):
                    raise ValueError(f"Escaping symlink forbidden inside packaged tree: {item}")
            elif item.is_file():
                lower = item.name.lower()
                if any(lower.startswith(prefix) for prefix in FORBIDDEN_PAYLOAD_PREFIXES):
                    raise ValueError(f"Forbidden driver or GNINA file in Core bundle: {item}")
                mode = 0o755 if os.access(item, os.X_OK) else 0o644
                os.chmod(item, mode)


def build_tauri_release_binary(*, skip_tauri_build: bool = False) -> tuple[Path, list[str]]:
    release_bin = TAURI_DIR / "target" / "release" / "ankora-desktop"
    if not skip_tauri_build:
        env = os.environ.copy()
        path_parts = [p for p in env.get("PATH", "").split(os.pathsep) if p and not p.startswith("/mnt/")]
        cargo_bin = Path.home() / ".cargo" / "bin"
        if cargo_bin.is_dir() and str(cargo_bin) not in path_parts:
            path_parts.insert(0, str(cargo_bin))
        nvm_versions = Path.home() / ".nvm" / "versions" / "node"
        if nvm_versions.is_dir() and not shutil.which("npm", path=os.pathsep.join(path_parts)):
            candidates = sorted(nvm_versions.glob("*/bin"))
            if candidates:
                path_parts.insert(0, str(candidates[-1]))
        for node_bin in (
            REPO_ROOT / "node_modules" / ".bin",
            DESKTOP_DIR / "node_modules" / ".bin",
        ):
            if node_bin.is_dir() and str(node_bin) not in path_parts:
                path_parts.insert(0, str(node_bin))
        env["PATH"] = os.pathsep.join(path_parts)

        subprocess.run(
            [
                "/bin/sh",
                str(REPO_ROOT / "scripts" / "tauri_linux.sh"),
                "build",
                "--no-bundle",
                "--config",
                str(RELEASE_TAURI_CONFIG),
            ],
            cwd=DESKTOP_DIR,
            env=env,
            check=True,
        )
    needed = _verify_elf_x86_64_no_home_rpath(release_bin)
    return release_bin, needed


def compute_deb_depends(needed_libs: list[str]) -> str:
    deps = [
        "libc6 (>= 2.38)",
        "libwebkit2gtk-4.1-0",
        "libgtk-3-0t64 | libgtk-3-0",
        "libsoup-3.0-0",
    ]
    if any("ayatana-appindicator" in lib for lib in needed_libs):
        deps.append("libayatana-appindicator3-1 | libappindicator3-1")
    elif any("appindicator" in lib for lib in needed_libs):
        deps.append("libappindicator3-1 | libayatana-appindicator3-1")
    return ", ".join(deps)


def stage_application_bundle(
    *,
    target_app_dir: Path,
    desktop_binary: Path,
    frozen_backend_dir: Path,
    scientific_tools_dir: Path,
    legal_dir: Path,
) -> None:
    if target_app_dir.exists():
        shutil.rmtree(target_app_dir)
    target_app_dir.mkdir(parents=True, mode=0o755)

    staged_desktop = target_app_dir / "ankora-desktop"
    shutil.copy2(desktop_binary, staged_desktop)
    staged_desktop.chmod(0o755)
    # Strip unneeded debug symbols on the staged copy to keep installer compact.
    strip_exe = shutil.which("strip") or "/usr/bin/strip"
    if Path(strip_exe).is_file():
        subprocess.run([strip_exe, "--strip-unneeded", str(staged_desktop)], check=True)

    staged_backend = target_app_dir / "backend"
    _copy_tree_preserving_intra_symlinks(frozen_backend_dir, staged_backend)
    (staged_backend / "ankora-backend").chmod(0o755)

    staged_tools = staged_backend / "tools"
    _copy_tree_preserving_intra_symlinks(scientific_tools_dir, staged_tools)

    staged_legal = target_app_dir / "legal"
    _copy_tree_preserving_intra_symlinks(legal_dir, staged_legal)


def _installed_size_kib(root: Path) -> int:
    total_bytes = 0
    for dirpath, _, filenames in os.walk(root, followlinks=False):
        if Path(dirpath).name == "DEBIAN":
            continue
        for fname in filenames:
            item = Path(dirpath) / fname
            st = item.lstat()
            if stat.S_ISREG(st.st_mode):
                total_bytes += st.st_size
    return max(1, (total_bytes + 1023) // 1024)


def build_deb_package(
    *,
    staged_app_dir: Path,
    version: str,
    depends: str,
    work_dir: Path,
    output_deb: Path,
) -> None:
    deb_root = work_dir / "deb-root"
    if deb_root.exists():
        shutil.rmtree(deb_root)

    usr_lib_ankora = deb_root / "usr" / "lib" / "ankora"
    usr_lib_ankora.parent.mkdir(parents=True, mode=0o755)
    _copy_tree_preserving_intra_symlinks(staged_app_dir, usr_lib_ankora)

    usr_bin = deb_root / "usr" / "bin"
    usr_bin.mkdir(parents=True, mode=0o755)
    launcher = usr_bin / "ankora"
    launcher.write_text(DEB_LAUNCHER_SCRIPT, encoding="utf-8")
    launcher.chmod(0o755)

    apps_dir = deb_root / "usr" / "share" / "applications"
    apps_dir.mkdir(parents=True, mode=0o755)
    desktop_file = apps_dir / "ankora.desktop"
    desktop_file.write_text(DESKTOP_ENTRY_TEXT, encoding="utf-8")
    desktop_file.chmod(0o644)

    icon_map = {
        "32x32": ICONS_DIR / "32x32.png",
        "64x64": ICONS_DIR / "64x64.png",
        "128x128": ICONS_DIR / "128x128.png",
        "256x256": ICONS_DIR / "128x128@2x.png",
        "512x512": ICONS_DIR / "icon.png",
    }
    for size_label, src_icon in icon_map.items():
        if not src_icon.is_file():
            raise FileNotFoundError(f"Missing application icon {src_icon}")
        dst_icon_dir = deb_root / "usr" / "share" / "icons" / "hicolor" / size_label / "apps"
        dst_icon_dir.mkdir(parents=True, mode=0o755)
        dst_icon = dst_icon_dir / "ankora.png"
        shutil.copy2(src_icon, dst_icon)
        dst_icon.chmod(0o644)

    doc_dir = deb_root / "usr" / "share" / "doc" / "ankora"
    doc_dir.mkdir(parents=True, mode=0o755)
    copyright_file = doc_dir / "copyright"
    shutil.copy2(staged_app_dir / "legal" / "THIRD_PARTY_NOTICES.txt", copyright_file)
    copyright_file.chmod(0o644)

    # Ensure every directory under deb_root is 0755 for lintian/dpkg cleanliness.
    for dirpath, _, _ in os.walk(deb_root, followlinks=False):
        os.chmod(dirpath, 0o755)

    debian_dir = deb_root / "DEBIAN"
    debian_dir.mkdir(parents=True, mode=0o755)
    installed_kib = _installed_size_kib(deb_root)
    control_text = (
        f"Package: ankora\n"
        f"Version: {version}\n"
        f"Section: science\n"
        f"Priority: optional\n"
        f"Architecture: amd64\n"
        f"Maintainer: Ankora Contributors <opensource@ankora.science>\n"
        f"Installed-Size: {installed_kib}\n"
        f"Depends: {depends}\n"
        f"Homepage: https://github.com/ankora-science/ankora\n"
        f"Description: Scientist-controlled offline molecular docking workbench\n"
        f" Ankora is a local-first desktop workbench for explicit, inspectable,\n"
        f" and reproducible receptor preparation, ligand microstate curation,\n"
        f" pocket detection (P2Rank 2.5.1), and molecular docking (AutoDock Vina\n"
        f" 1.2.7, AutoGrid4/AutoDock4 4.2.6, AutoDock-GPU 1.6, and optional\n"
        f" offline GNINA 1.3.3 + CUDA 12 / cuDNN 9 pack).\n"
    )
    control_file = debian_dir / "control"
    control_file.write_text(control_text, encoding="utf-8")
    control_file.chmod(0o644)

    dpkg_deb = shutil.which("dpkg-deb") or "/usr/bin/dpkg-deb"
    output_deb.parent.mkdir(parents=True, exist_ok=True)
    if output_deb.exists():
        output_deb.unlink()
    env = {**os.environ, "SOURCE_DATE_EPOCH": "0"}
    subprocess.run(
        [
            dpkg_deb,
            "--root-owner-group",
            "-Zxz",
            "-z3",
            "--build",
            str(deb_root),
            str(output_deb),
        ],
        env=env,
        check=True,
    )


def build_portable_tar_zst(
    *,
    staged_app_dir: Path,
    version: str,
    work_dir: Path,
    output_tar_zst: Path,
    zstd_level: int = 3,
) -> None:
    portable_folder_name = f"Ankora-{version}-linux-x86_64"
    portable_root = work_dir / portable_folder_name
    if portable_root.exists():
        shutil.rmtree(portable_root)
    _copy_tree_preserving_intra_symlinks(staged_app_dir, portable_root)

    launcher = portable_root / "ankora"
    launcher.write_text(PORTABLE_LAUNCHER_SCRIPT, encoding="utf-8")
    launcher.chmod(0o755)

    readme = portable_root / "README-PORTABLE.txt"
    readme.write_text(PORTABLE_README_TEXT, encoding="utf-8")
    readme.chmod(0o644)

    output_tar_zst.parent.mkdir(parents=True, exist_ok=True)
    tmp_out = output_tar_zst.parent / f".{output_tar_zst.name}.tmp"
    if tmp_out.exists():
        tmp_out.unlink()

    zstd_exe = _resolve_zstd_executable()
    proc = subprocess.Popen(
        [zstd_exe, f"-{zstd_level}", "-T0", "-f", "-q", "-o", str(tmp_out)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        assert proc.stdin is not None
        with tarfile.open(fileobj=proc.stdin, mode="w|", format=tarfile.PAX_FORMAT) as tar:
            for item in sorted(portable_root.rglob("*"), key=lambda p: p.as_posix()):
                arcname = f"{portable_folder_name}/{item.relative_to(portable_root).as_posix()}"
                st = item.lstat()
                info = tarfile.TarInfo(name=arcname)
                info.mtime = 0
                info.uid = 0
                info.gid = 0
                info.uname = ""
                info.gname = ""
                if stat.S_ISDIR(st.st_mode):
                    info.type = tarfile.DIRTYPE
                    info.mode = 0o755
                    tar.addfile(info)
                elif stat.S_ISLNK(st.st_mode):
                    info.type = tarfile.SYMTYPE
                    info.linkname = os.readlink(item)
                    info.mode = 0o777
                    tar.addfile(info)
                elif stat.S_ISREG(st.st_mode):
                    info.type = tarfile.REGTYPE
                    info.size = st.st_size
                    info.mode = 0o755 if os.access(item, os.X_OK) else 0o644
                    with item.open("rb") as stream:
                        tar.addfile(info, stream)
        proc.stdin.close()
        proc.stdin = None
        _, stderr_bytes = proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(
                f"zstd portable archive compression failed: "
                f"{stderr_bytes.decode('utf-8', errors='replace')}"
            )
    except BaseException:
        proc.kill()
        proc.wait()
        if tmp_out.exists():
            tmp_out.unlink()
        raise

    tmp_out.replace(output_tar_zst)


def build_linux_release(
    *,
    build_root: Path = DEFAULT_BUILD_ROOT,
    skip_tauri_build: bool = False,
    require_gnina_pack: bool = True,
) -> dict[str, Any]:
    tauri_cfg = json.loads(RELEASE_TAURI_CONFIG.read_text(encoding="utf-8"))
    version = str(tauri_cfg["version"])

    frozen_backend_dir = build_root / "dist-slim" / "ankora-backend"
    scientific_tools_dir = build_root / "scientific-tools-slim"
    legal_dir = build_root / "complete-legal"
    sources_zip = build_root / f"Ankora_{version}_linux-sources-companion.zip"
    gnina_pack = build_root / f"Ankora_{version}_gnina-cuda12-pack.tar.zst"

    for required_path, label in (
        (frozen_backend_dir / "ankora-backend", "frozen Linux backend"),
        (scientific_tools_dir / "payload.json", "staged Core scientific tools"),
        (legal_dir / "COMPLETE_LEGAL_MANIFEST.json", "Linux complete-legal notices"),
        (sources_zip, "GPL/LGPL corresponding sources companion zip"),
    ):
        if not required_path.exists():
            raise FileNotFoundError(f"Missing required {label}: {required_path}")

    if require_gnina_pack and not gnina_pack.is_file():
        raise FileNotFoundError(f"Missing required offline GNINA pack: {gnina_pack}")

    verify_complete_linux_legal(
        output_legal=legal_dir,
        tools=scientific_tools_dir,
        companion_zip_path=sources_zip,
    )

    desktop_bin, needed_libs = build_tauri_release_binary(skip_tauri_build=skip_tauri_build)
    depends = compute_deb_depends(needed_libs)

    work_dir = build_root / "installer-staging"
    if work_dir.exists():
        shutil.rmtree(work_dir)
    work_dir.mkdir(parents=True, mode=0o755)

    staged_app_dir = work_dir / "app-bundle"
    stage_application_bundle(
        target_app_dir=staged_app_dir,
        desktop_binary=desktop_bin,
        frozen_backend_dir=frozen_backend_dir,
        scientific_tools_dir=scientific_tools_dir,
        legal_dir=legal_dir,
    )

    release_dir = build_root / f"release-{version}"
    if release_dir.exists():
        shutil.rmtree(release_dir)
    release_dir.mkdir(parents=True, mode=0o755)

    deb_path = release_dir / f"Ankora_{version}_amd64.deb"
    portable_path = release_dir / f"Ankora_{version}_linux_x86_64.tar.zst"
    release_sources_zip = release_dir / sources_zip.name

    build_deb_package(
        staged_app_dir=staged_app_dir,
        version=version,
        depends=depends,
        work_dir=work_dir,
        output_deb=deb_path,
    )
    build_portable_tar_zst(
        staged_app_dir=staged_app_dir,
        version=version,
        work_dir=work_dir,
        output_tar_zst=portable_path,
    )
    _link_or_copy(sources_zip, release_sources_zip)

    artifact_paths = [deb_path, portable_path, release_sources_zip]
    if gnina_pack.is_file():
        release_gnina_pack = release_dir / gnina_pack.name
        _link_or_copy(gnina_pack, release_gnina_pack)
        artifact_paths.append(release_gnina_pack)

    artifacts_meta: list[dict[str, Any]] = []
    sha256_lines: list[str] = []
    for artifact in artifact_paths:
        sha, size = _sha256_and_size(artifact)
        artifacts_meta.append(
            {
                "filename": artifact.name,
                "size_bytes": size,
                "size_mib": round(size / (1024 * 1024), 2),
                "sha256": sha,
            }
        )
        sha256_lines.append(f"{sha}  {artifact.name}")

    (release_dir / "SHA256SUMS.txt").write_text(
        "\n".join(sha256_lines) + "\n",
        encoding="utf-8",
    )
    manifest = {
        "schema_version": 1,
        "version": version,
        "platform": "linux-x86_64",
        "deb_depends": depends,
        "desktop_needed_shared_libraries": needed_libs,
        "artifacts": artifacts_meta,
    }
    (release_dir / "linux-release-manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    shutil.rmtree(work_dir, ignore_errors=True)
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build-root", type=Path, default=DEFAULT_BUILD_ROOT)
    parser.add_argument("--skip-tauri-build", action="store_true")
    parser.add_argument("--no-require-gnina-pack", action="store_true")
    args = parser.parse_args(argv)

    manifest = build_linux_release(
        build_root=args.build_root.resolve(),
        skip_tauri_build=args.skip_tauri_build,
        require_gnina_pack=not args.no_require_gnina_pack,
    )
    print(json.dumps(manifest, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
