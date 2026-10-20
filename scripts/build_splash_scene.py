"""Build the startup scene from Ankora's own recorded 7AQF / RV2 evidence.

The startup screen does not draw an illustration of a binding pocket. It draws
*the* pocket: the SERPINE1 cavity around RV2 A:401 from the exact 7AQF mmCIF the
SERPINE1_7AQF_RV2 reference case froze, with RV2 in its crystallographic pose
from the recorded reference ligand. Both inputs are checked against the hashes
that case recorded, so the scene cannot silently drift to another structure.

The output is a committed asset; regenerating it needs the local recorded
artifacts under `.ankora-data`, but using it needs nothing.

    python scripts/build_splash_scene.py
"""

import hashlib
import json
import math
import pathlib
import sys
from importlib import import_module
from typing import Any

import numpy as np

gemmi: Any = import_module("gemmi")
Chem: Any = import_module("rdkit.Chem")

ROOT = pathlib.Path(__file__).resolve().parent.parent
DATA = ROOT / ".ankora-data" / "projects" / "default" / "original"
STRUCTURE = DATA / "structures" / "76f5afae-1f5d-4baa-8359-a7335407abb8" / "7AQF.cif"
LIGAND = DATA / "ligands" / "12ebd97c-4302-4e0f-ad49-9b606edab666" / "RV2_A_401.sdf"
OUTPUT = ROOT / "apps" / "desktop" / "src" / "assets" / "splash-scene.json"

# The bytes the frozen reference case recorded (docs/validation/reference_cases/SERPINE1_7AQF_RV2.md).
EXPECTED = {
    STRUCTURE: "79fd3b96adca6bdbe17ded6e9c693534007ae2cb0538739044788754b7c6faac",
    LIGAND: "6fa65e2d76adb3ba91d60a5747e4986d359766c965f29fdf3559203f26195fe4",
}
# The co-crystal search space every frozen 7AQF engine record used.
BOX_CENTER = np.array([35.4305, -2.967, -0.7905])
BOX_SIZE = np.array([21.597, 19.87, 19.317])

VDW = {"C": 1.70, "N": 1.55, "O": 1.52, "S": 1.80, "Cl": 1.75, "P": 1.80}
PROBE = 0.55           # small probe: the surface hugs the cavity
POCKET_RADIUS = 8.5    # Å from any ligand atom
SURFACE_WINDOW = 12.0  # Å from the ligand centroid
LINING = 6.2           # Å: keep only the surface that lines the cavity around RV2
DOTS_PER_ATOM = 150
MAX_DOTS = 3400
MESH_STEP = 1.05       # Å: neighbouring surface points joined into a faint mesh
CONTACT = 3.5          # Å: polar heavy-atom pairs drawn once RV2 is anchored
SAMPLE_SEED = 20260823  # the frozen Vina seed, reused only so the dot sample is stable


def sha256(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sphere(n: int) -> np.ndarray:
    """Golden-spiral points on a unit sphere."""
    i = np.arange(n) + 0.5
    phi = np.arccos(1 - 2 * i / n)
    theta = math.pi * (1 + 5 ** 0.5) * i
    return np.stack([np.cos(theta) * np.sin(phi), np.sin(theta) * np.sin(phi), np.cos(phi)], 1)


def rotation_to(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Rotation matrix taking direction a onto direction b."""
    a, b = a / np.linalg.norm(a), b / np.linalg.norm(b)
    v, c = np.cross(a, b), float(np.dot(a, b))
    if np.linalg.norm(v) < 1e-8:
        return np.eye(3) if c > 0 else -np.eye(3)
    k = np.array([[0, -v[2], v[1]], [v[2], 0, -v[0]], [-v[1], v[0], 0]])
    return np.eye(3) + k + k @ k * (1 / (1 + c))


def element(atom: Any) -> str:
    name = atom.element.name
    return name.capitalize() if len(name) > 1 else name


def build_scene() -> dict[str, Any]:
    for path, digest in EXPECTED.items():
        if not path.exists():
            raise SystemExit(f"missing recorded artifact: {path}")
        if sha256(path) != digest:
            raise SystemExit(f"{path.name} does not match the frozen reference-case bytes")

    # RV2 in its crystallographic pose, bond orders from the recorded SDF.
    mol = Chem.MolFromMolFile(str(LIGAND), removeHs=True)
    conf = mol.GetConformer()
    lig_xyz = np.array([list(conf.GetAtomPosition(i)) for i in range(mol.GetNumAtoms())])
    lig_el = [a.GetSymbol() for a in mol.GetAtoms()]
    bonds = [
        [b.GetBeginAtomIdx(), b.GetEndAtomIdx(), 1.5 if b.GetIsAromatic() else b.GetBondTypeAsDouble()]
        for b in mol.GetBonds()
    ]
    centroid = lig_xyz.mean(0)

    # Chain A protein heavy atoms of model 1.
    st = gemmi.read_structure(str(STRUCTURE))
    st.remove_hydrogens()
    atoms = []
    for chain in st[0]:
        if chain.name != "A":
            continue
        for res in chain:
            info = gemmi.find_tabulated_residue(res.name)
            if info is None or not info.is_amino_acid():
                continue
            for at in res:
                atoms.append((np.array(at.pos.tolist()), element(at), f"{res.name} {res.seqid.num}"))
    xyz = np.array([a[0] for a in atoms])
    els = [a[1] for a in atoms]

    d_lig = np.min(np.linalg.norm(xyz[:, None, :] - lig_xyz[None, :, :], axis=2), axis=1)
    pocket = np.where(d_lig < POCKET_RADIUS)[0]
    near = np.where(np.linalg.norm(xyz - centroid, axis=1) < SURFACE_WINDOW + 6)[0]

    # Solvent-accessible dot surface lining the cavity.
    unit = sphere(DOTS_PER_ATOM)
    radii = np.array([VDW.get(e, 1.7) + PROBE for e in els])
    dots = []
    for i in pocket:
        pts = xyz[i] + unit * radii[i]
        neigh = near[np.linalg.norm(xyz[near] - xyz[i], axis=1) < radii[i] + 3.6]
        neigh = neigh[neigh != i]
        if len(neigh):
            dd = np.linalg.norm(pts[:, None, :] - xyz[neigh][None, :, :], axis=2)
            pts = pts[np.all(dd >= radii[neigh][None, :] - 1e-6, axis=1)]
        pts = pts[np.linalg.norm(pts - centroid, axis=1) < SURFACE_WINDOW]
        if len(pts):
            lining = np.min(np.linalg.norm(pts[:, None, :] - lig_xyz[None, :, :], axis=2), axis=1)
            pts = pts[lining <= LINING]
        polar = 1 if els[i] in ("N", "O") else 0
        dots.extend((p, polar) for p in pts)
    rng = np.random.default_rng(SAMPLE_SEED)
    if len(dots) > MAX_DOTS:
        keep = rng.choice(len(dots), MAX_DOTS, replace=False)
        dots = [dots[k] for k in sorted(keep)]

    # Join each surface point to its nearest neighbours: a surface, not a cloud.
    pos = np.array([d[0] for d in dots])
    edges: set[tuple[int, int]] = set()
    for a in range(len(pos)):
        dd = np.linalg.norm(pos - pos[a], axis=1)
        dd[a] = np.inf
        for b in np.argsort(dd)[:3]:
            if dd[b] <= MESH_STEP:
                edges.add((min(a, int(b)), max(a, int(b))))

    # Polar contacts the deposited pose makes — geometry only, no interaction claim.
    contacts = []
    for li, (lp, le) in enumerate(zip(lig_xyz, lig_el)):
        if le not in ("N", "O", "Cl"):
            continue
        for ri in pocket:
            if els[ri] in ("N", "O") and np.linalg.norm(xyz[ri] - lp) <= CONTACT:
                contacts.append((li, xyz[ri], atoms[ri][2], round(float(np.linalg.norm(xyz[ri] - lp)), 2)))

    # Orient so the pocket mouth faces the viewer.
    mouth = centroid - xyz[pocket].mean(0)
    rot = rotation_to(mouth, np.array([0.18, -0.28, 1.0]))

    def tf(p: Any) -> list[float]:
        return [round(float(v), 2) for v in rot @ (np.asarray(p) - centroid)]

    corners = [
        BOX_CENTER + np.array([1 if i & 1 else -1, 1 if i & 2 else -1, 1 if i & 4 else -1]) * BOX_SIZE / 2
        for i in range(8)
    ]
    return {
        "provenance": {
            "reference_case": "SERPINE1_7AQF_RV2",
            "structure": "7AQF.cif",
            "structure_sha256": EXPECTED[STRUCTURE],
            "ligand": "RV2 A:401, crystallographic",
            "ligand_sha256": EXPECTED[LIGAND],
            "generator": "scripts/build_splash_scene.py",
        },
        "ligand": {"atoms": [[*tf(p), e] for p, e in zip(lig_xyz, lig_el)], "bonds": bonds},
        "dots": [[*tf(p), polar] for p, polar in dots],
        "edges": [list(e) for e in sorted(edges)],
        "contacts": [[li, *tf(p), label, dist] for li, p, label, dist in contacts],
        "box": {"corners": [tf(c) for c in corners], "size": [round(float(v), 2) for v in BOX_SIZE]},
    }


def main() -> int:
    scene = build_scene()
    OUTPUT.write_text(json.dumps(scene, separators=(",", ":")) + "\n", encoding="utf-8")
    print(
        f"ligand atoms {len(scene['ligand']['atoms'])} · bonds {len(scene['ligand']['bonds'])} · "
        f"surface dots {len(scene['dots'])} · mesh edges {len(scene['edges'])} · "
        f"contacts {len(scene['contacts'])}"
    )
    print(f"contact residues: {sorted({c[4] for c in scene['contacts']})}")
    print(f"wrote {OUTPUT.relative_to(ROOT)} ({OUTPUT.stat().st_size // 1024} KiB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
