"""Build Ankora's Windows backend as one relocatable onedir runtime."""

from pathlib import Path

from PyInstaller.utils.hooks import collect_all, copy_metadata


repository_root = Path(SPECPATH).parents[1]
backend_source = repository_root / "backend" / "src"
entry_point = repository_root / "backend" / "packaging" / "ankora_backend_entry.py"

datas = []
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

bundle = COLLECT(
    executable,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="ankora-backend",
)
