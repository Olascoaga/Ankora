"""Deterministic complete-linkage joint (ligand, flex) pose clustering (ADR-030 E2/E3 & ADR-032 E8).

Zero new dependencies: reuses `redocking_rmsd.py`'s in-place symmetry-aware
heavy-atom `CalcRMS` (never superposed!) and pairs it with exact symmetry-aware
in-place heavy-atom RMSD over moved `FlexRes` side chains under `sidechain_flex`.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from hashlib import sha256
from importlib import import_module
from math import sqrt
from typing import Any

from ankora_backend.adapters.chemistry.redocking_rmsd import (
    autodock_type_to_element,
    in_place_rmsd,
    load_pose,
)
from ankora_backend.domain.errors import AnkoraDomainError
from ankora_backend.schemas.consensus import (
    DEFAULT_CLUSTER_RMSD_THRESHOLD_ANGSTROM,
    PoseClusterMemberSummary,
    PoseClusterSummary,
    SourceEngine,
)
from ankora_backend.schemas.receptors import ReceptorFlexMode
from ankora_backend.schemas.v02_contracts import PoseComplexIdentity

_STAGE = "consensus_pose_clustering"

#: Symmetric terminal heavy-atom swap pairs inside standard flexible amino-acid side chains.
_SYMMETRIC_SIDECHAIN_SWAPS: dict[str, tuple[tuple[tuple[str, str], ...], ...]] = {
    "PHE": ((("CD1", "CD2"), ("CE1", "CE2")),),
    "TYR": ((("CD1", "CD2"), ("CE1", "CE2")),),
    "ASP": ((("OD1", "OD2"),),),
    "GLU": ((("OE1", "OE2"),),),
    "ARG": ((("NH1", "NH2"),),),
    "VAL": ((("CG1", "CG2"),),),
    "LEU": ((("CD1", "CD2"),),),
}

type _FlexAtomKey = tuple[str, int, str, str, str]


@dataclass(frozen=True)
class ClusterCandidatePose:
    """One verified pose complex candidate entering per-parent complete-linkage clustering."""

    pose_id: str
    source_engine: SourceEngine
    primary_rank_order: int
    pose_complex: PoseComplexIdentity
    ligand_pdbqt_text: str
    pose_flex_sidechains_pdbqt_text: str | None = None


@dataclass(frozen=True)
class ParentClusteringResult:
    """Complete-linkage clusters, deterministic medoids, and explicit K_max retention."""

    total_input_poses: int
    total_clusters_found: int
    retained_clusters: tuple[PoseClusterSummary, ...]
    truncated_by_k_max: bool
    pairwise_joint_rmsd: dict[tuple[str, str], float]


def _strip_nul_lines(text: str) -> str:
    return "\n".join(line for line in text.splitlines() if line.strip("\x00\r\n"))


def _load_cluster_ligand_mol(pdbqt_text: str, reference_conformer_mol: Any) -> Any:
    """Reconstruct exact ligand topology for in-place RMSD without proximity-bond artifacts.

    Prefers Meeko's recorded molecular graph (`meeko.PDBQTMolecule`) when available so
    sterically self-clashing poses cannot acquire spurious proximity covalent bonds and
    Meeko macrocycle glue pseudoatoms (`CG0`/`G0`) are resolved cleanly. Falls back to
    `redocking_rmsd.load_pose` for non-Meeko PDBQT fixtures while enforcing exact heavy
    atom and bond count equality against `reference_conformer_mol`.
    """
    chem: Any = import_module("rdkit.Chem")
    ref_no_h = chem.RemoveHs(reference_conformer_mol)
    expected_atoms = int(ref_no_h.GetNumAtoms())
    expected_bonds = int(ref_no_h.GetNumBonds())
    try:
        meeko: Any = import_module("meeko")
        pmol = meeko.PDBQTMolecule(pdbqt_text, skip_typing=True)
        reconstructed = meeko.RDKitMolCreate.from_pdbqt_mol(pmol)
        candidate = next((mol for mol in reconstructed if mol is not None), None)
        if candidate is not None:
            heavy = chem.RemoveHs(candidate)
            if (
                int(heavy.GetNumAtoms()) == expected_atoms
                and int(heavy.GetNumBonds()) == expected_bonds
                and heavy.HasSubstructMatch(ref_no_h)
            ):
                return heavy
    except Exception:
        pass
    loaded = load_pose(pdbqt_text, reference_conformer_mol)
    if (
        int(loaded.GetNumAtoms()) != expected_atoms
        or int(loaded.GetNumBonds()) != expected_bonds
    ):
        raise _clustering_error(
            "CONSENSUS_POSE_TOPOLOGY_MISMATCH",
            "Reconstructed pose bond graph does not match the reference conformer topology.",
            expected_heavy_atoms=expected_atoms,
            observed_heavy_atoms=int(loaded.GetNumAtoms()),
            expected_bonds=expected_bonds,
            observed_bonds=int(loaded.GetNumBonds()),
        )
    return loaded


def extract_heavy_atom_coords_from_pdbqt(
    pdbqt_text: str,
) -> list[tuple[_FlexAtomKey, tuple[float, float, float]]]:
    """Parse heavy atoms `(chain, resseq, icode, resname, atom_name) -> (x, y, z)` from PDBQT."""
    cleaned = _strip_nul_lines(pdbqt_text)
    atoms: list[tuple[_FlexAtomKey, tuple[float, float, float]]] = []
    for line in cleaned.splitlines():
        if not line.startswith(("ATOM  ", "HETATM")):
            continue
        if len(line) < 54:
            continue
        atom_type = line[77:79].strip() if len(line) >= 78 else ""
        element = autodock_type_to_element(atom_type) if atom_type else None
        atom_name = line[12:16].strip()
        if element == "H" or (element is None and atom_name.upper().startswith("H")):
            continue
        resname = line[17:20].strip().upper()
        chain_id = line[21:22].strip()
        try:
            resseq = int(line[22:26].strip())
            x = float(line[30:38])
            y = float(line[38:46])
            z = float(line[46:54])
        except ValueError as error:
            raise _clustering_error(
                "CONSENSUS_COORDINATES_UNREADABLE",
                "Pose PDBQT contains unreadable coordinate records.",
                reason=str(error),
            ) from error
        icode = line[26:27].strip()
        atoms.append(((chain_id, resseq, icode, resname, atom_name), (x, y, z)))
    return atoms


def canonical_pose_coordinate_sha256(
    *,
    ligand_pdbqt_text: str,
    pose_flex_sidechains_pdbqt_text: str | None = None,
) -> str:
    """Compute a deterministic canonical coordinate SHA-256 for E3 medoid tie-breaking."""
    lig_coords = extract_heavy_atom_coords_from_pdbqt(ligand_pdbqt_text)
    if not lig_coords:
        raise _clustering_error(
            "CONSENSUS_POSE_EMPTY",
            "Ligand pose PDBQT contains no heavy atoms.",
        )
    parts: list[str] = ["LIG"]
    for _, (x, y, z) in lig_coords:
        parts.append(f"{x:.4f},{y:.4f},{z:.4f}")
    if pose_flex_sidechains_pdbqt_text is not None:
        flex_coords = sorted(
            extract_heavy_atom_coords_from_pdbqt(pose_flex_sidechains_pdbqt_text),
            key=lambda item: item[0],
        )
        parts.append("FLEX")
        for key, (x, y, z) in flex_coords:
            parts.append(f"{key[0]}:{key[1]}{key[2]}:{key[3]}:{key[4]}={x:.4f},{y:.4f},{z:.4f}")
    return sha256("|".join(parts).encode("utf-8")).hexdigest()


def in_place_flex_sidechains_rmsd(
    flex_coords_a: dict[_FlexAtomKey, tuple[float, float, float]],
    flex_coords_b: dict[_FlexAtomKey, tuple[float, float, float]],
) -> float:
    """Compute symmetry-aware in-place heavy-atom RMSD across moved FlexRes side chains."""
    if not flex_coords_a or set(flex_coords_a) != set(flex_coords_b):
        raise _clustering_error(
            "CONSENSUS_FLEXRES_ATOM_SET_MISMATCH",
            "Flexible side-chain heavy-atom sets differ across poses of the same complex.",
            atoms_a=len(flex_coords_a),
            atoms_b=len(flex_coords_b),
        )

    # Group heavy atoms by residue so symmetric terminal flips (PHE/TYR/ASP/GLU/ARG/VAL/LEU)
    # are evaluated independently per residue without superimposing anything.
    by_residue: dict[tuple[str, int, str, str], list[_FlexAtomKey]] = {}
    for key in sorted(flex_coords_a):
        res_key = (key[0], key[1], key[2], key[3])
        by_residue.setdefault(res_key, []).append(key)

    total_sq_dist = 0.0
    total_atoms = 0
    for (chain, resseq, icode, resname), atom_keys in by_residue.items():
        # Baseline (unswapped) squared distance sum
        base_sq = sum(
            (flex_coords_a[k][0] - flex_coords_b[k][0]) ** 2
            + (flex_coords_a[k][1] - flex_coords_b[k][1]) ** 2
            + (flex_coords_a[k][2] - flex_coords_b[k][2]) ** 2
            for k in atom_keys
        )
        best_sq = base_sq
        swap_groups = _SYMMETRIC_SIDECHAIN_SWAPS.get(resname, ())
        for swap_pairs in swap_groups:
            remap: dict[_FlexAtomKey, _FlexAtomKey] = {k: k for k in atom_keys}
            valid_swap = True
            for atom1, atom2 in swap_pairs:
                k1 = (chain, resseq, icode, resname, atom1)
                k2 = (chain, resseq, icode, resname, atom2)
                if k1 not in flex_coords_b or k2 not in flex_coords_b:
                    valid_swap = False
                    break
                remap[k1] = k2
                remap[k2] = k1
            if not valid_swap:
                continue
            swapped_sq = sum(
                (flex_coords_a[k][0] - flex_coords_b[remap[k]][0]) ** 2
                + (flex_coords_a[k][1] - flex_coords_b[remap[k]][1]) ** 2
                + (flex_coords_a[k][2] - flex_coords_b[remap[k]][2]) ** 2
                for k in atom_keys
            )
            if swapped_sq < best_sq:
                best_sq = swapped_sq

        total_sq_dist += best_sq
        total_atoms += len(atom_keys)

    return sqrt(total_sq_dist / float(total_atoms))


def cluster_parent_pose_complexes(
    *,
    candidates: Sequence[ClusterCandidatePose],
    reference_conformer_mol: Any,
    k_max: int,
    rmsd_threshold_angstrom: float = DEFAULT_CLUSTER_RMSD_THRESHOLD_ANGSTROM,
) -> ParentClusteringResult:
    """Cluster one parent's poses using deterministic complete linkage (<= 2.0 A).

    Enforces:
    - ADR-030 E2: explicit required `k_max` (>= 1) pre-evaluation cluster cap.
    - ADR-030 E3: complete linkage guarantees every intra-cluster pair satisfies
      `d_joint <= rmsd_threshold_angstrom`, with deterministic lowest-coordinate-hash
      medoid tie-breaking invariant to input pose order.
    - ADR-032 E8: under `sidechain_flex`, `d_joint = max(RMSD_lig, RMSD_flex)` so
      divergent moved side chains never collapse into one representative.
    """
    if k_max < 1:
        raise _clustering_error(
            "CONSENSUS_KMAX_INVALID",
            "Pre-evaluation cluster cap k_max must be at least 1.",
            k_max=k_max,
        )
    if rmsd_threshold_angstrom <= 0.0:
        raise _clustering_error(
            "CONSENSUS_RMSD_THRESHOLD_INVALID",
            "Clustering RMSD threshold must be positive.",
            rmsd_threshold_angstrom=rmsd_threshold_angstrom,
        )
    if not candidates:
        return ParentClusteringResult(
            total_input_poses=0,
            total_clusters_found=0,
            retained_clusters=(),
            truncated_by_k_max=False,
            pairwise_joint_rmsd={},
        )

    modes = {c.pose_complex.mode for c in candidates}
    if len(modes) != 1:
        raise _clustering_error(
            "CONSENSUS_SHARED_CONTEXT_MISMATCH",
            "Cannot cluster rigid and sidechain_flex poses of the same parent together.",
            modes=sorted(m.value for m in modes),
        )
    mode = next(iter(modes))
    rigid_hashes = {c.pose_complex.receptor_rigid_sha256 for c in candidates}
    if len(rigid_hashes) != 1:
        raise _clustering_error(
            "CONSENSUS_SHARED_CONTEXT_MISMATCH",
            "Cannot cluster poses docked against different rigid receptor hashes.",
            receptor_rigid_sha256s=sorted(rigid_hashes),
        )

    # Canonicalize input ordering by coordinate hash (+ pose_id) so clustering is
    # strictly bitwise invariant to the order candidates were supplied.
    prepared: list[
        tuple[
            ClusterCandidatePose,
            str,
            Any,
            dict[_FlexAtomKey, tuple[float, float, float]] | None,
        ]
    ] = []
    seen_pose_ids: set[str] = set()
    for item in candidates:
        if item.pose_id in seen_pose_ids:
            raise _clustering_error(
                "CONSENSUS_DUPLICATE_POSE_ID",
                f"Duplicate pose_id '{item.pose_id}' supplied for clustering.",
                pose_id=item.pose_id,
            )
        seen_pose_ids.add(item.pose_id)
        cleaned_lig = _strip_nul_lines(item.ligand_pdbqt_text)
        lig_mol = _load_cluster_ligand_mol(cleaned_lig, reference_conformer_mol)
        flex_map: dict[_FlexAtomKey, tuple[float, float, float]] | None = None
        if mode is ReceptorFlexMode.SIDECHAIN_FLEX:
            if item.pose_flex_sidechains_pdbqt_text is None:
                raise _clustering_error(
                    "CONSENSUS_FLEXRES_MISSING",
                    "sidechain_flex pose clustering requires moved flex side-chain PDBQT text.",
                    pose_id=item.pose_id,
                )
            flex_list = extract_heavy_atom_coords_from_pdbqt(item.pose_flex_sidechains_pdbqt_text)
            flex_map = dict(flex_list)
        coord_hash = canonical_pose_coordinate_sha256(
            ligand_pdbqt_text=cleaned_lig,
            pose_flex_sidechains_pdbqt_text=item.pose_flex_sidechains_pdbqt_text,
        )
        prepared.append((item, coord_hash, lig_mol, flex_map))

    prepared.sort(key=lambda row: (row[1], row[0].pose_id))
    n = len(prepared)

    # Pairwise joint in-place distance matrix d_joint(i, j) = max(RMSD_lig, RMSD_flex).
    dist: list[list[float]] = [[0.0] * n for _ in range(n)]
    pairwise_map: dict[tuple[str, str], float] = {}
    for i in range(n):
        for j in range(i + 1, n):
            rmsd_lig = in_place_rmsd(prepared[i][2], prepared[j][2])
            if mode is ReceptorFlexMode.SIDECHAIN_FLEX:
                flex_i = prepared[i][3]
                flex_j = prepared[j][3]
                assert flex_i is not None and flex_j is not None
                rmsd_flex = in_place_flex_sidechains_rmsd(flex_i, flex_j)
                d_joint = max(rmsd_lig, rmsd_flex)
            else:
                d_joint = rmsd_lig
            dist[i][j] = d_joint
            dist[j][i] = d_joint
            id_i = prepared[i][0].pose_id
            id_j = prepared[j][0].pose_id
            key = (id_i, id_j) if id_i < id_j else (id_j, id_i)
            pairwise_map[key] = d_joint

    # Exact deterministic agglomerative complete-linkage clustering with hard diameter <= threshold.
    clusters: list[list[int]] = [[idx] for idx in range(n)]
    while len(clusters) > 1:
        best_pair: tuple[int, int] | None = None
        best_key: tuple[float, str, str] | None = None
        for a in range(len(clusters)):
            for b in range(a + 1, len(clusters)):
                complete_dist = max(dist[i][j] for i in clusters[a] for j in clusters[b])
                if complete_dist > rmsd_threshold_angstrom + 1e-12:
                    continue
                # Round distance to 1e-9 for tie-breaking stability across libm/platform ULP drift
                tie_key = (
                    round(complete_dist, 9),
                    prepared[clusters[a][0]][1],
                    prepared[clusters[b][0]][1],
                )
                if best_key is None or tie_key < best_key:
                    best_key = tie_key
                    best_pair = (a, b)
        if best_pair is None:
            break
        a, b = best_pair
        merged = sorted(clusters[a] + clusters[b])
        clusters[a] = merged
        clusters.pop(b)

    # Build deterministic cluster summaries with E3 medoid selection.
    summaries: list[PoseClusterSummary] = []
    for member_indices in clusters:
        # Medoid minimizes total intra-cluster joint distance; ties break by lowest coord hash
        best_medoid_idx = min(
            member_indices,
            key=lambda u: (
                round(sum(dist[u][v] for v in member_indices), 9),
                prepared[u][1],
                prepared[u][0].pose_id,
            ),
        )
        max_diameter = (
            max(dist[i][j] for i in member_indices for j in member_indices)
            if len(member_indices) > 1
            else 0.0
        )
        medoid_cand, medoid_hash, _, _ = prepared[best_medoid_idx]
        best_primary = min(prepared[idx][0].primary_rank_order for idx in member_indices)
        engines_present: tuple[SourceEngine, ...] = tuple(
            sorted({prepared[idx][0].source_engine for idx in member_indices})
        )
        member_summaries = tuple(
            PoseClusterMemberSummary(
                pose_id=prepared[idx][0].pose_id,
                source_engine=prepared[idx][0].source_engine,
                primary_rank_order=prepared[idx][0].primary_rank_order,
                pose_complex=prepared[idx][0].pose_complex,
                canonical_coordinate_sha256=prepared[idx][1],
            )
            for idx in member_indices
        )
        summaries.append(
            PoseClusterSummary(
                cluster_id=f"cluster-{medoid_hash[:12]}",
                medoid_pose_id=medoid_cand.pose_id,
                medoid_pose_complex=medoid_cand.pose_complex,
                medoid_canonical_coordinate_sha256=medoid_hash,
                member_count=len(member_indices),
                max_intra_cluster_rmsd_angstrom=max_diameter,
                best_primary_rank_order=best_primary,
                search_engines_present=engines_present,
                members=member_summaries,
            )
        )

    # Order clusters deterministically before E2 K_max truncation:
    # best primary rank first, then larger search convergence, then coordinate hash.
    summaries.sort(
        key=lambda item: (
            item.best_primary_rank_order,
            -len(item.search_engines_present),
            item.medoid_canonical_coordinate_sha256,
        )
    )
    retained = tuple(summaries[:k_max])
    return ParentClusteringResult(
        total_input_poses=n,
        total_clusters_found=len(summaries),
        retained_clusters=retained,
        truncated_by_k_max=len(summaries) > k_max,
        pairwise_joint_rmsd=pairwise_map,
    )


def _clustering_error(code: str, message: str, **details: object) -> AnkoraDomainError:
    return AnkoraDomainError(
        code=code,
        stage=_STAGE,
        message=message,
        status_code=422,
        details=details,
    )
