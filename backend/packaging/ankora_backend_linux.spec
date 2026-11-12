"""Build Ankora's Linux x86_64 backend as a relocatable slim onedir ELF runtime."""

from __future__ import annotations

import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules, copy_metadata

repository_root = Path(SPECPATH).parents[1]
backend_source = repository_root / "backend" / "src"
entry_point = repository_root / "backend" / "packaging" / "ankora_backend_entry.py"
openmm_runtime_hook = repository_root / "backend" / "packaging" / "pyi_rth_linux_openmm.py"
conda_lib_dir = Path(sys.base_prefix).resolve() / "lib"

datas: list[tuple[str, str]] = []
for name in ("synthetic_m1.pdb", "synthetic_ethanol.smi"):
    datas.append(
        (
            str(repository_root / "backend/tests/fixtures" / name),
            "smoke-fixtures/backend/tests/fixtures",
        )
    )

binaries: list[tuple[str, str]] = []
_RETAINED_OPENMM_PLUGINS = (
    "libOpenMMCPU.so",
    "libOpenMMPME.so",
    "libOpenMMAmoebaReference.so",
    "libOpenMMDrudeReference.so",
    "libOpenMMRPMDReference.so",
)
openmm_plugins_dir = conda_lib_dir / "plugins"
for plugin_name in _RETAINED_OPENMM_PLUGINS:
    plugin_path = openmm_plugins_dir / plugin_name
    if not plugin_path.is_file():
        raise FileNotFoundError(f"Required OpenMM CPU/Reference plugin missing: {plugin_path}")
    binaries.append((str(plugin_path), "openmm_plugins"))

for core_openmm_so in sorted(conda_lib_dir.glob("libOpenMM*.so*")):
    if core_openmm_so.is_file() and not any(
        tag in core_openmm_so.name for tag in ("CUDA", "HIP", "OpenCL")
    ):
        binaries.append((str(core_openmm_so.resolve()), "."))

hiddenimports = [
    "uvicorn.lifespan.on",
    "uvicorn.logging",
    "uvicorn.loops.auto",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets.auto",
    *collect_submodules("ankora_backend"),
]

for package in (
    "dimorphite_dl",
    "gemmi",
    "meeko",
    "MDAnalysis",
    "openmm",
    "pdb2pqr",
    "pdbfixer",
    "prolif",
    "propka",
    "rdkit",
):
    package_datas, package_binaries, package_hiddenimports = collect_all(package)
    datas += package_datas
    binaries += package_binaries
    hiddenimports += package_hiddenimports

for distribution in (
    "ankora-backend",
    "dimorphite-dl",
    "meeko",
    "openmm",
    "pdb2pqr",
    "pdbfixer",
    "prolif",
    "propka",
    "rdkit",
):
    datas += copy_metadata(distribution)

_RETAINED_OPENMM_DATA = {
    "amber14",
    "implicit",
    "amber14-all.xml",
    "amber99sb.xml",
    "amber99sbildn.xml",
    "amber99sbnmr.xml",
    "amber99obc.xml",
    "bondDefinitions.xml",
    "hydrogens.xml",
    "pdbNames.xml",
    "residues.xml",
    "tip3p.xml",
    "tip3pfb.xml",
    "tip4pew.xml",
    "tip4pfb.xml",
    "tip5p.xml",
    "spce.xml",
    "opc.xml",
    "opc3.xml",
}
_OMITTED_PROLIF_DATA = {
    "top.pdb",
    "traj.xtc",
    "water_m2.pdb",
    "water_m2.xtc",
    "implicitHbond",
    "vina",
}
_FORBIDDEN_DRIVER_PREFIXES = (
    "libcuda.so",
    "libnvidia-ml.so",
    "libnvidia-ptxjitcompiler.so",
)


def _retain_data(entry: tuple) -> bool:
    rel = str(entry[0]).replace("\\", "/")
    if rel.startswith(("_tcl_data/", "_tk_data/", "rdkit/Contrib/")):
        return False
    if rel.startswith("prolif/data/"):
        sub = rel.removeprefix("prolif/data/").split("/", 1)[0]
        if sub in _OMITTED_PROLIF_DATA:
            return False
    if rel.startswith("openmm/app/data/"):
        sub = rel.removeprefix("openmm/app/data/").split("/", 1)[0]
        if sub not in _RETAINED_OPENMM_DATA:
            return False
    if rel.startswith("MDAnalysis/") and rel.endswith((".c", ".cpp", ".h", ".pxd", ".pyx")):
        return False
    return True


def _retain_binary(entry: tuple) -> bool:
    rel = str(entry[0]).replace("\\", "/")
    base = Path(rel).name.lower()
    if any(base.startswith(prefix) for prefix in _FORBIDDEN_DRIVER_PREFIXES):
        return False
    if (
        base.startswith(("libtcl", "libtk", "_tkinter"))
        or base in {"tcl86t.dll", "tk86t.dll", "_tkinter.pyd"}
    ):
        return False
    if base.startswith("libopenmm") and any(
        gpu_tag in base for gpu_tag in ("cuda", "hip", "opencl")
    ):
        return False
    return True


analysis = Analysis(
    [str(entry_point)],
    pathex=[str(backend_source)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[str(openmm_runtime_hook)],
    excludes=["pytest", "mypy", "ruff", "tkinter", "_tkinter"],
    noarchive=False,
    optimize=1,
)
pyz = PYZ(analysis.pure)

executable = EXE(
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="ankora-backend",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

filtered_binaries = [item for item in analysis.binaries if _retain_binary(item)]
filtered_datas = [item for item in analysis.datas if _retain_data(item)]

bundle = COLLECT(
    executable,
    filtered_binaries,
    filtered_datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="ankora-backend",
)
