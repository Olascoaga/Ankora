"""Recompress a generated full NSIS installer without changing its payload.

Run Tauri's --no-bundle build first. This creates a separate output directory,
never invokes the default bundler, and preserves explicitly named old installers.
No installed runtime, model, source archive or offline prerequisite is removed.
Optional deduplication materializes identical models from the shipped source ZIP.
Larger LZMA dictionaries trade build/install memory for download size.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import zipfile
from pathlib import Path

from scripts.windows_scientific_payload import sha256


def deduplicate_models(source: str, resources: Path) -> str:
    from ankora_backend.installer_resources import (
        MODEL_NAMES,
        SOURCE_FILE,
        SOURCE_SHA256,
    )

    from scripts.complete_windows_legal import verify_complete

    verify_complete(resources / "complete-legal", resources / "backend/tools")
    archive_path = resources / "complete-legal" / SOURCE_FILE
    if sha256(archive_path) != SOURCE_SHA256:
        raise ValueError("Wrong P2Rank source archive")
    with zipfile.ZipFile(archive_path) as archive:
        for name in MODEL_NAMES:
            relative = f"tools/p2rank-2.5.1/models/{name}/model.zst"
            content = archive.read(f"p2rank-2.5.1/distro/models/{name}/model.zst")
            if hashlib.sha256(content).hexdigest() != sha256(
                resources / "backend" / relative
            ):
                raise ValueError(
                    f"Model is not identical in source and runtime: {name}"
                )
    # Prove the just-frozen backend has this installer-only entry point.
    subprocess.run(
        [
            str(resources / "backend/ankora-backend.exe"),
            "--worker",
            "installer-resources",
            "--help",
        ],
        check=True,
        timeout=60,
        capture_output=True,
    )
    # Rebind the generated resource File inputs to a separately staged complete
    # tree, not the original bundle. The main desktop executable stays current.
    marker = (
        '    File /a "/oname=backend\\tools\\p2rank-2.5.1\\models\\default\\model.zst" '
    )
    entries = [line for line in source.splitlines() if line.startswith(marker)]
    if len(entries) != 1:
        raise ValueError("Cannot resolve generated resource root")
    original_file = Path(entries[0][len(marker) :].strip('"'))
    original_root = original_file.parents[5]
    source = source.replace(
        '"' + str(original_root) + "\\", '"' + str(resources) + "\\"
    )
    listed = {
        Path(value).resolve()
        for value in re.findall(r'^    File /a "/oname=[^"]+" "([^"]+)"$', source, re.MULTILINE)
        if Path(value).is_relative_to(resources)
    }
    actual = {path.resolve() for path in resources.rglob("*") if path.is_file()}
    if listed != actual:
        raise ValueError(
            "Generated NSIS resource list does not cover the exact staged tree"
        )
    return model_script(source, MODEL_NAMES)


def model_script(source: str, names: tuple[str, ...]) -> str:
    for name in names:
        prefix = f'    File /a "/oname=backend\\tools\\p2rank-2.5.1\\models\\{name}\\model.zst" '
        matches = [
            line for line in source.splitlines(keepends=True) if line.startswith(prefix)
        ]
        if len(matches) != 1:
            raise ValueError(f"Generated model entry changed: {name}")
        source = source.replace(matches[0], "")
    marker = '  WriteUninstaller "$INSTDIR\\uninstall.exe"'
    if source.count(marker) != 1:
        raise ValueError("Generated uninstaller boundary changed")
    return source.replace(
        marker,
        marker
        + """
  DetailPrint "Restoring and verifying bundled P2Rank models..."
  nsExec::ExecToStack '"$INSTDIR\\backend\\ankora-backend.exe" --worker installer-resources --root "$INSTDIR"'
  Pop $0
  Pop $1
  ${If} $0 != 0
    DetailPrint "$1"
    MessageBox MB_ICONSTOP|MB_OK "Offline scientific model installation failed. $1" /SD IDOK
    SetErrorLevel 1
    Abort
  ${EndIf}
""",
    )


def compact_script(source: str, dictionary_mb: int) -> str:
    if dictionary_mb not in (32, 64, 128):
        raise ValueError("Use a reviewed 32, 64 or 128 MiB dictionary")
    compressor = '  SetCompressor /SOLID "lzma"'
    if source.count(compressor) != 1 or "SetCompressorDictSize" in source:
        raise ValueError("Generated NSIS compression shape changed; review required")
    outfile = '!define OUTFILE "nsis-output.exe"'
    if source.count(outfile) != 1:
        raise ValueError("Generated NSIS output shape changed; review required")
    if '!define INSTALLWEBVIEW2MODE "offlineInstaller"' not in source:
        raise ValueError("The complete installer requires offline WebView2")
    return source.replace(
        compressor, compressor + f"\n  SetCompressorDictSize {dictionary_mb}"
    ).replace(outfile, '!define OUTFILE "Ankora_0.1.0_x64-compact-setup.exe"')


def build(
    source: Path,
    output: Path,
    compiler: Path,
    dictionary_mb: int,
    preserve: list[Path],
    resources: Path | None = None,
) -> None:
    source, output, compiler = source.resolve(), output.resolve(), compiler.resolve()
    originals = {str(p.resolve()): sha256(p) for p in preserve}
    if not originals:
        raise ValueError("Name the existing installer(s) to preserve")
    text = source.read_text(encoding="utf-8")
    rewritten = compact_script(text, dictionary_mb)
    if resources is not None:
        rewritten = deduplicate_models(rewritten, resources.resolve())
    # Capture all actual file inputs, including offline WebView, native
    # executable and resources. Deduplicated models remain in the source ZIP.
    inputs = {}
    for value in re.findall(r'"([^"\n]+)"', rewritten):
        if re.match(r"^[A-Za-z]:[\\/]", value):
            path = Path(value)
            if path.is_file():
                inputs[str(path)] = sha256(path)
    if not inputs:
        raise ValueError("No generated Windows payload inputs found")
    output.mkdir(parents=True, exist_ok=False)
    try:
        for path in source.parent.iterdir():
            if path.is_file() and (
                path.suffix == ".nsh" or path.name == "license_file"
            ):
                shutil.copyfile(path, output / path.name)
        generated = output / "installer.nsi"
        generated.write_text(rewritten, encoding="utf-8")
        with (output / "build.log").open("w", encoding="utf-8") as log:
            subprocess.run(
                [str(compiler), "/V3", str(generated)],
                cwd=output,
                stdout=log,
                stderr=subprocess.STDOUT,
                check=True,
            )
        for name, digest in inputs.items():
            if sha256(Path(name)) != digest:
                raise ValueError(f"Build input changed during compilation: {name}")
        installer = output / "Ankora_0.1.0_x64-compact-setup.exe"
        evidence = {
            "schema_version": 1,
            "dictionary_mib": dictionary_mb,
            "payload_policy": "identical installed resources; source ZIP model deduplication"
            if resources
            else "unchanged complete offline payload",
            "source_script_sha256": sha256(source),
            "generated_script_sha256": sha256(generated),
            "compiler_sha256": sha256(compiler),
            "inputs": inputs,
            "preserved_installers": originals,
            "installer": {
                "name": installer.name,
                "sha256": sha256(installer),
                "size_bytes": installer.stat().st_size,
            },
        }
        (output / "compression-evidence.json").write_text(
            json.dumps(evidence, indent=2) + "\n", encoding="utf-8"
        )
        print(json.dumps(evidence["installer"]))
    finally:
        for name, digest in originals.items():
            if sha256(Path(name)) != digest:
                raise ValueError(f"Protected original changed: {name}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--compiler", type=Path, required=True)
    parser.add_argument("--dictionary-mb", type=int, choices=(32, 64, 128), default=64)
    parser.add_argument("--preserve", type=Path, action="append", required=True)
    parser.add_argument("--deduplicate-resources", type=Path)
    args = parser.parse_args()
    build(
        args.source,
        args.output,
        args.compiler,
        args.dictionary_mb,
        args.preserve,
        args.deduplicate_resources,
    )
