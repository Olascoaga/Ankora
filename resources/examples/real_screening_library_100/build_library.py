"""Build a reproducible library from a pinned, public RDKit NCI sample.

The output directory must not exist. No molecular structures are invented.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import tempfile
from collections import Counter
from pathlib import Path

from ankora_backend.persistence.ligand_store import LigandArtifactStore
from ankora_backend.schemas.ligands import (
    LigandLibraryFilterPlan,
    LigandLibraryFilterRequest,
)
from ankora_backend.services.ligand_filtering import preview_library_filters
from ankora_backend.services.ligand_import import import_local_ligand_library
from rdkit import Chem, RDConfig, rdBase
from rdkit.Chem import AllChem

SOURCE_SHA = "91e71c015f14939837f2943dcc904f7c87e5a3a0124d82b05c28ad2f23004def"
SUBSET_SHA = "7230041129c4433e2264199eba52ccb29a8c7b225c6b404e9ec21b18671ebd4d"
SOURCE_URL = (
    "https://github.com/rdkit/rdkit/blob/Release_2025_09_6/Data/NCI/first_5K.smi"
)


def digest(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output", required=True, type=Path, help="new directory, never overwritten"
    )
    args = parser.parse_args()
    source = Path(RDConfig.RDDataDir) / "NCI" / "first_5K.smi"
    source_bytes = source.read_bytes()
    if digest(source_bytes) != SOURCE_SHA:
        raise ValueError("Installed source differs from the declared RDKit NCI source")
    subset = b"".join(source_bytes.splitlines(keepends=True)[:100])
    if digest(subset) != SUBSET_SHA:
        raise ValueError("The first 100 source rows differ from the declared sample")
    args.output.mkdir(parents=True, exist_ok=False)
    smi_path = args.output / "nci_real_100.smi"
    sdf_path = args.output / "nci_real_100.sdf"
    smi_path.write_bytes(subset)
    lines = subset.decode("utf-8").splitlines()
    original = []
    with Chem.SDWriter(str(sdf_path)) as writer:
        for row, line in enumerate(lines, 1):
            smiles, source_label = line.split()
            molecule = Chem.MolFromSmiles(smiles)
            if molecule is None:
                raise ValueError(f"Cannot parse source row {row}")
            original.append(Chem.MolToSmiles(molecule, isomericSmiles=True))
            molecule.SetProp("_Name", f"NCI-{source_label}")
            molecule.SetProp("SOURCE_ROW", str(row))
            molecule.SetProp("SOURCE_LABEL", source_label)
            molecule.SetProp("SOURCE_SMILES", smiles)
            AllChem.Compute2DCoords(molecule)
            writer.write(molecule)
    reloaded = list(Chem.SDMolSupplier(str(sdf_path), removeHs=False))
    if len(reloaded) != 100 or any(molecule is None for molecule in reloaded):
        raise ValueError("SDF did not retain all 100 readable molecular records")
    observed = [
        Chem.MolToSmiles(molecule, isomericSmiles=True) for molecule in reloaded
    ]
    if observed != original:
        raise ValueError("SDF round trip changed one or more structures")

    plans = {
        "predeterminado": LigandLibraryFilterPlan(),
        "demostracion": LigandLibraryFilterPlan(
            preset="custom",
            require_ghose=True,
            require_muegge=True,
            minimum_qed=0.3,
            pains_policy="exclude",
            brenk_policy="exclude",
        ),
    }
    with tempfile.TemporaryDirectory(prefix="ankora-real-library-") as scratch:
        store = LigandArtifactStore(Path(scratch))
        library = import_local_ligand_library(
            content=sdf_path.read_bytes(), filename=sdf_path.name, store=store
        )
        if (library.imported_count, library.failed_count) != (100, 0):
            raise ValueError("Ankora did not import all SDF records")
        previews = {
            label: preview_library_filters(
                library_id=library.artifact.library_id,
                request=LigandLibraryFilterRequest(plan=plan),
                store=store,
                worker_limit=1,
            )
            for label, plan in plans.items()
        }
        baseline, strict = previews["predeterminado"], previews["demostracion"]
        if len(baseline.evaluations) != 100 or len(strict.evaluations) != 100:
            raise ValueError("Filter preview did not account for all records")
        columns = [
            "source_row",
            "source_label",
            "source_smiles",
            "canonical_isomeric_smiles",
            "molecular_weight_g_mol",
            "clogp",
            "qed",
            "lipinski_pass",
            "lipinski_violations",
            "veber_pass",
            "ghose_pass",
            "muegge_pass",
            "pains_alerts",
            "brenk_alerts",
            "default_disposition",
            "default_reasons",
            "demo_disposition",
            "demo_reasons",
        ]
        with (args.output / "resultados_filtros.csv").open(
            "w", encoding="utf-8", newline=""
        ) as handle:
            writer = csv.DictWriter(handle, fieldnames=columns)
            writer.writeheader()
            for row, (default, demonstration, line) in enumerate(
                zip(baseline.evaluations, strict.evaluations, lines, strict=True), 1
            ):
                if (
                    default.record_index != row - 1
                    or demonstration.record_index != row - 1
                ):
                    raise ValueError("Filter order differs from original source")
                smiles, source_label = line.split()
                desc = default.descriptors
                writer.writerow(
                    {
                        "source_row": row,
                        "source_label": source_label,
                        "source_smiles": smiles,
                        "canonical_isomeric_smiles": default.canonical_isomeric_smiles
                        or "",
                        "molecular_weight_g_mol": desc.molecular_weight_g_mol
                        if desc
                        else "",
                        "clogp": desc.clogp if desc else "",
                        "qed": desc.qed if desc else "",
                        "lipinski_pass": default.lipinski.passed
                        if default.lipinski
                        else "",
                        "lipinski_violations": " | ".join(default.lipinski.violations)
                        if default.lipinski
                        else "",
                        "veber_pass": default.veber.passed if default.veber else "",
                        "ghose_pass": default.ghose.passed if default.ghose else "",
                        "muegge_pass": default.muegge.passed if default.muegge else "",
                        "pains_alerts": " | ".join(
                            alert.description
                            for alert in default.alerts
                            if alert.catalog == "PAINS"
                        ),
                        "brenk_alerts": " | ".join(
                            alert.description
                            for alert in default.alerts
                            if alert.catalog == "BRENK"
                        ),
                        "default_disposition": default.disposition.value,
                        "default_reasons": " | ".join(default.reasons),
                        "demo_disposition": demonstration.disposition.value,
                        "demo_reasons": " | ".join(demonstration.reasons),
                    }
                )
        summary = {
            "source_url": SOURCE_URL,
            "source_rdkit_version": rdBase.rdkitVersion,
            "source_sha256": SOURCE_SHA,
            "selection": "first 100 source rows, original order",
            "source_subset_sha256": SUBSET_SHA,
            "sdf_sha256": digest(sdf_path.read_bytes()),
            "records": 100,
            "sdf_canonical_isomeric_roundtrip_mismatches": 0,
            "profiles": {
                name: {
                    "plan": plans[name].model_dump(mode="json"),
                    "summary": result.summary.model_dump(mode="json"),
                    "evaluated": sum(
                        item.descriptors is not None for item in result.evaluations
                    ),
                    "reason_counts_overlap": dict(
                        Counter(
                            reason
                            for item in result.evaluations
                            for reason in item.reasons
                        )
                    ),
                }
                for name, result in previews.items()
            },
        }
        (args.output / "manifest.json").write_text(
            json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
