"""Isolated PDB2PQR/PROPKA worker with structured state evidence.

Ordinary overrides change only the pKa value presented to PDB2PQR.  An exact
neutral histidine override additionally fixes the PDB2PQR residue to HID or
HIE after native hydrogen construction and before native hydrogen optimization
and AMBER charge/radius assignment.  The written PDB and PQR are then checked
independently; no output file is edited after PDB2PQR returns.
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
    original_hold = biomolecule.Biomolecule.hold_residues
    explicit_histidines = {
        identity: state
        for identity, state in overrides.items()
        if identity[1] == "HIS" and state in {"HID", "HIE"}
    }
    fixed_histidines: set[tuple[str, str, int, str]] = set()

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

    def hold_with_tautomer_overrides(instance: Any, hlist: object) -> None:
        if explicit_histidines and not fixed_histidines:
            fixed_keys: list[tuple[int, str, str]] = []
            for residue in instance.residues:
                identity = (
                    str(residue.chain_id),
                    str(residue.name),
                    int(residue.res_seq),
                    str(residue.ins_code or "").strip(),
                )
                state = explicit_histidines.get(identity)
                if state is None:
                    continue
                _fix_histidine_tautomer(residue, state)
                fixed_histidines.add(identity)
                fixed_keys.append(
                    (int(residue.res_seq), str(residue.chain_id), str(residue.ins_code))
                )
            missing = set(explicit_histidines) - fixed_histidines
            if missing:
                raise ValueError(
                    "Explicit histidine tautomer overrides did not match PDB2PQR "
                    f"residues: {sorted(missing)}"
                )
            original_hold(instance, fixed_keys)
        original_hold(instance, hlist)

    biomolecule.Biomolecule.apply_pka_values = apply_with_overrides
    biomolecule.Biomolecule.hold_residues = hold_with_tautomer_overrides
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
    predictions = [_json_row(row) for row in (pka_rows or [])]
    output_states = _histidine_output_states(
        pdb_path=args.pdb_output,
        pqr_path=args.pqr_output,
        predictions=predictions,
    )
    output_state_map = {
        _output_identity(item): str(item["state"]) for item in output_states
    }
    for item in applied:
        identity = (
            str(item["chain_id"]),
            str(item["residue_name"]),
            int(str(item["sequence_number"])),
            str(item["insertion_code"]),
        )
        if identity[1] != "HIS":
            continue
        observed = output_state_map.get(identity)
        if observed is None:
            raise ValueError(f"No written histidine state was found for {identity}.")
        item["output_state"] = observed
        requested = str(item["state"])
        if requested in {"HID", "HIE", "HIP"} and observed != requested:
            raise ValueError(
                f"PDB2PQR wrote {observed} for {identity}, not requested {requested}."
            )
    print(
        json.dumps(
            {
                "predictions": predictions,
                "applied_overrides": applied,
                "output_states": output_states,
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
        "HIS": {"HIS_NEUTRAL_AUTO": low, "HID": low, "HIE": low, "HIP": high},
        "LYS": {"LYS": high, "LYN": low},
    }
    try:
        return states[residue_name][state]
    except KeyError as error:
        raise ValueError(
            f"State {state} is not a supported PDB2PQR override for {residue_name}."
        ) from error


def _fix_histidine_tautomer(residue: Any, state: str) -> None:
    """Fix one native PDB2PQR histidine before optimization and force-field use."""

    if state not in {"HID", "HIE"}:
        raise ValueError(f"Exact neutral histidine state must be HID or HIE, not {state}.")
    required = "HD1" if state == "HID" else "HE2"
    removed = "HE2" if state == "HID" else "HD1"
    if not residue.has_atom(required) or not residue.has_atom(removed):
        raise ValueError(
            f"PDB2PQR did not construct both neutral histidine candidates before {state}."
        )
    residue.remove_atom(removed)


def _histidine_output_states(
    *, pdb_path: Path, pqr_path: Path, predictions: list[dict[str, object]]
) -> list[dict[str, object]]:
    identities = {
        (
            str(row.get("chain_id") or ""),
            "HIS",
            int(str(row["res_num"])),
            str(row.get("ins_code") or ""),
        )
        for row in predictions
        if str(row.get("res_name") or "") == "HIS"
        and str(row.get("group_label") or "").startswith("HIS")
    }
    pdb_atoms = _residue_atom_names(pdb_path, identities)
    pqr_atoms = _residue_atom_names(pqr_path, identities)
    output: list[dict[str, object]] = []
    for identity in sorted(identities):
        pdb_state = _histidine_state(pdb_atoms.get(identity, set()), identity, "PDB")
        pqr_state = _histidine_state(pqr_atoms.get(identity, set()), identity, "PQR")
        if pdb_state != pqr_state:
            raise ValueError(
                f"Written PDB/PQR histidine states disagree for {identity}: "
                f"{pdb_state} versus {pqr_state}."
            )
        output.append(
            {
                "chain_id": identity[0],
                "residue_name": identity[1],
                "sequence_number": identity[2],
                "insertion_code": identity[3],
                "state": pdb_state,
                "ring_hydrogens": sorted(
                    pdb_atoms[identity].intersection({"HD1", "HE2"})
                ),
                "verified_in": ["pdb", "pqr"],
            }
        )
    return output


def _residue_atom_names(
    path: Path, identities: set[tuple[str, str, int, str]]
) -> dict[tuple[str, str, int, str], set[str]]:
    atoms: dict[tuple[str, str, int, str], set[str]] = {
        identity: set() for identity in identities
    }
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.startswith(("ATOM  ", "HETATM")) or len(line) < 27:
            continue
        try:
            identity = (
                line[21].strip(),
                "HIS" if line[17:20].strip() in {"HIS", "HID", "HIE", "HIP"} else "",
                int(line[22:26]),
                line[26].strip(),
            )
        except ValueError:
            continue
        if identity in atoms:
            atoms[identity].add(line[12:16].strip())
    return atoms


def _histidine_state(
    atom_names: set[str], identity: tuple[str, str, int, str], label: str
) -> str:
    if not atom_names:
        raise ValueError(f"Written {label} has no histidine residue for {identity}.")
    hd1 = "HD1" in atom_names
    he2 = "HE2" in atom_names
    if hd1 and he2:
        return "HIP"
    if hd1:
        return "HID"
    if he2:
        return "HIE"
    raise ValueError(
        f"Written {label} histidine {identity} has neither HD1 nor HE2."
    )


def _output_identity(item: dict[str, object]) -> tuple[str, str, int, str]:
    return (
        str(item["chain_id"]),
        str(item["residue_name"]),
        int(str(item["sequence_number"])),
        str(item["insertion_code"]),
    )


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
