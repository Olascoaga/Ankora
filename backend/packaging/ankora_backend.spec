"""Build Ankora's Windows backend as one relocatable onedir runtime."""

from pathlib import Path

from PyInstaller.utils.hooks import collect_all, copy_metadata


repository_root = Path(SPECPATH).parents[1]
backend_source = repository_root / "backend" / "src"
entry_point = repository_root / "backend" / "packaging" / "ankora_backend_entry.py"

datas = []
for name in ("synthetic_m1.pdb", "synthetic_ethanol.smi"):
    datas.append((str(repository_root / "backend/tests/fixtures" / name),
                  "smoke-fixtures/backend/tests/fixtures"))
binaries = []
hiddenimports = [
    "uvicorn.lifespan.on",
    "uvicorn.logging",
    "uvicorn.loops.auto",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets.auto",
]

# These packages either load compiled extensions/data dynamically or are entered
# through Ankora's packaged worker dispatcher. Their complete payload is needed
# even when static import analysis cannot see a particular execution path.
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

analysis = Analysis(
    [str(entry_point)],
    pathex=[str(backend_source)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["pytest", "mypy", "ruff"],
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
    rel = str(entry[0]).replace("\\", "/").lower()
    if rel in {"tcl86t.dll", "tk86t.dll", "_tkinter.pyd"}:
        return False
    return True


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

