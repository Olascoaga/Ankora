"""Isolated PDB2PQR/PROPKA worker with structured pKa output.

The compatibility hook changes only the pKa value presented to PDB2PQR for
an explicitly overridden residue. PDB2PQR still applies its own topology
patch, hydrogen optimization, charge assignment, and output generation.
"""

import argparse
import json
from pathlib import Path
from typing import Any

from ankora_backend.schemas.receptors import ProtonationOverride


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--pqr-output", type=Path, required=True)
    parser.add_argument("--pdb-output", type=Path, required=True)
    parser.add_argument("--ph", type=float, required=True)
    parser.add_argument("--force-field", required=True)
    parser.add_argument("--override", action="append", default=[])
    return parser


def main() -> None:
    args = _parser().parse_args()
    from pdb2pqr import biomolecule, io
    from pdb2pqr.main import run_pdb2pqr

    overrides = _parse_overrides(args.override)
    applied: list[dict[str, object]] = []
    original_apply = biomolecule.Biomolecule.apply_pka_values

    def apply_with_overrides(
        instance: Any, force_field: str, ph: float, pkadic: dict[str, float]
    ) -> None:
        available = dict(pkadic)
        for identity, state in overrides.items():
            chain_id, residue_name, sequence_number, insertion_code = identity
            if insertion_code:
                raise ValueError(
                    "PDB2PQR does not expose insertion codes in its pKa assignment key; "
                    f"cannot safely override {chain_id}:{sequence_number}{insertion_code}."
                )
            key = f"{residue_name} {sequence_number} {chain_id}".strip()
            if key not in pkadic:
                raise ValueError(f"The requested protonation override did not match {key}.")
            predicted_pka = float(pkadic[key])
            forced_pka = _forced_pka(residue_name, state, ph)
            pkadic[key] = forced_pka
            applied.append(
                {
                    "chain_id": chain_id,
                    "residue_name": residue_name,
                    "sequence_number": sequence_number,
                    "insertion_code": insertion_code,
                    "state": state,
                    "predicted_pka": predicted_pka,
                    "forced_pka": forced_pka,
                }
            )
        original_apply(instance, force_field, ph, pkadic)
        if len(applied) != len(overrides):
            missing = [
                "|".join((chain, name, str(number), insertion))
                for chain, name, number, insertion in overrides
                if f"{name} {number} {chain}".strip() not in available
            ]
            raise ValueError(f"Unapplied protonation overrides: {missing}")

    biomolecule.Biomolecule.apply_pka_values = apply_with_overrides
    io.setup_logger(str(args.pqr_output), "INFO")
    _, pka_rows, _ = run_pdb2pqr(
        [
            f"--ff={args.force_field}",
            "--keep-chain",
            "--titration-state-method=propka",
            f"--with-ph={args.ph:g}",
            f"--pdb-output={args.pdb_output}",
            str(args.input),
            str(args.pqr_output),
        ]
    )
    print(
        json.dumps(
            {
                "predictions": [_json_row(row) for row in (pka_rows or [])],
                "applied_overrides": applied,
            },
            sort_keys=True,
        )
    )


def _parse_overrides(
    values: list[str],
) -> dict[tuple[str, str, int, str], str]:
    overrides: dict[tuple[str, str, int, str], str] = {}
    for value in values:
        override = ProtonationOverride.model_validate_json(value)
        residue = override.residue
        identity = (
            residue.chain_id,
            residue.residue_name,
            residue.sequence_number,
            residue.insertion_code,
        )
        if identity in overrides:
            raise ValueError(f"Duplicate protonation override: {value}")
        overrides[identity] = override.state
    return overrides


def _forced_pka(residue_name: str, state: str, ph: float) -> float:
    high = ph + 100.0
    low = ph - 100.0
    states = {
        "ASP": {"ASP": low, "ASH": high},
        "GLU": {"GLU": low, "GLH": high},
        "CYS": {"CYS": high, "CYM": low},
        "HIS": {"HIS_NEUTRAL_AUTO": low, "HIP": high},
        "LYS": {"LYS": high, "LYN": low},
    }
    try:
        return states[residue_name][state]
    except KeyError as error:
        raise ValueError(
            f"State {state} is not a supported PDB2PQR override for {residue_name}."
        ) from error


def _json_row(row: dict[str, object]) -> dict[str, object]:
    return {
        "res_num": int(str(row["res_num"])),
        "ins_code": str(row.get("ins_code") or "").strip(),
        "res_name": str(row["res_name"]).strip(),
        "chain_id": str(row.get("chain_id") or "").strip(),
        "group_label": str(row["group_label"]),
        "group_type": None if row.get("group_type") is None else str(row["group_type"]),
        "pKa": float(str(row["pKa"])),
        "model_pKa": (
            None if row.get("model_pKa") is None else float(str(row["model_pKa"]))
        ),
        "buried": None if row.get("buried") is None else float(str(row["buried"])),
        "coupled_group": (
            None if row.get("coupled_group") is None else str(row["coupled_group"])
        ),
    }


if __name__ == "__main__":
    main()
