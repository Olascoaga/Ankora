"""Run the separately predeclared, post-failure 1HSG exploratory follow-up."""

from __future__ import annotations

import argparse
import copy
from pathlib import Path

import validate_linux_crystal_redocking as smoke
from validate_linux_api_preparation import digest_bytes

AUTHORIZED = [
    {
        "chain_id": chain,
        "residue_name": "PHE",
        "sequence_number": 99,
        "insertion_code": "",
        "atom_name": "OXT",
    }
    for chain in ("A", "B")
]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--structure", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.name != "exploratory-followup-01":
        parser.error("The follow-up uses the single predeclared create-only output directory.")
    plan = copy.deepcopy(smoke.PLAN)
    protonation = plan["protonation"]
    if not isinstance(protonation, dict):
        raise ValueError("The declared protonation plan is not a mapping.")
    protonation["authorized_terminal_heavy_atom_additions"] = AUTHORIZED
    smoke.PLAN = plan
    try:
        result = smoke.run(args.structure, args.output)
    except (ValueError, FileExistsError) as error:
        print(str(error))
        return 2
    print(f"Exploratory follow-up: {result['status']}")
    if "failure" in result:
        print(result["failure"])
    print(f"Evidence SHA-256: {digest_bytes((args.output / 'evidence.json').read_bytes())}")
    return 0 if result["status"] == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
