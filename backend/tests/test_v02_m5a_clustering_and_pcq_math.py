"""Adversarial & mathematical verification for M5a pose clustering and ADR-030 PC-Q/PC-ECR/PC-L2.

Every molecule, pose coordinate, and docking score in this module is explicitly
labelled synthetic. Tests verify complete-linkage diameter invariants (E3),
joint (ligand, flex) separation (E8), explicit K_max capping (E2), parent-weighted
midrank quantiles (E1), block non-double-voting, D_ic disagreement, separate-scale
PC-ECR (E5), two-tier denominator invariance (E6), and strictly convex PC-L2
promotion gating (ADR-030 §3).
"""

from __future__ import annotations

from hashlib import sha256
from importlib import import_module
from math import exp
from pathlib import Path
from typing import Any

import pytest

from ankora_backend.adapters.chemistry.pose_clustering import (
    ClusterCandidatePose,
    cluster_parent_pose_complexes,
    in_place_flex_sidechains_rmsd,
)
from ankora_backend.adapters.consensus.pcq_math import (
    build_reference_panel,
    compute_pc_ecr_from_block_quantiles,
    compute_pcq_and_ecr_consensus,
    fit_and_gate_pc_l2,
    parent_weighted_midrank_quantile,
    resolve_variant_weights,
)
from ankora_backend.domain.errors import AnkoraDomainError
from ankora_backend.persistence.calibration_store import CalibrationArtifactStore
from ankora_backend.schemas.calibration import (
    INSUFFICIENT_EVIDENCE_TEXT,
    CalibrationCompoundInput,
    CalibrationSplitPolicy,
)
from ankora_backend.schemas.consensus import (
    FROZEN_ECR_TAU,
    ConsensusParentInput,
    ConsensusPoseScoreInput,
    ConsensusVariantId,
)
from ankora_backend.schemas.receptors import ReceptorFlexMode, ReceptorFlexSpec
from ankora_backend.schemas.v02_contracts import (
    PoseComplexIdentity,
    RankingMethod,
    ScoringFamily,
    ScoringFunctionId,
)
from ankora_backend.schemas.warnings import WarningCode
from ankora_backend.services.protocol_calibration import ProtocolCalibrationService

Chem: Any = import_module("rdkit.Chem")
AllChem: Any = import_module("rdkit.Chem.AllChem")
meeko: Any = import_module("meeko")

_REC_SHA = "a" * 64
_FLEX_SHA = "b" * 64
_BOX_SHA = "c" * 64
_MAP_SHA = "d" * 64


def _sha(text: str) -> str:
    return sha256(text.encode("utf-8")).hexdigest()


def _make_synthetic_ethanol_template_and_pose(
    dx: float, dy: float = 0.0, dz: float = 0.0, *, flip_x: bool = False
) -> tuple[Any, str]:
    """Generate a deterministic synthetic ethanol template + translated/flipped Meeko PDBQT."""
    mol = Chem.AddHs(Chem.MolFromSmiles("CCO"))
    params = AllChem.ETKDGv3()
    params.randomSeed = 20261119
    params.numThreads = 1
    assert AllChem.EmbedMolecule(mol, params) == 0
    assert AllChem.MMFFOptimizeMolecule(mol, mmffVariant="MMFF94s") == 0
    template = Chem.RemoveHs(Chem.Mol(mol))

    conf = mol.GetConformer()
    for idx in range(mol.GetNumAtoms()):
        pt = conf.GetAtomPosition(idx)
        nx = (-pt.x if flip_x else pt.x) + dx
        conf.SetAtomPosition(idx, (nx, pt.y + dy, pt.z + dz))

    prep = meeko.MoleculePreparation()
    setups = prep.prepare(mol)
    pdbqt_str, is_ok, err = meeko.PDBQTWriterLegacy.write_string(setups[0])
    assert is_ok, err
    return template, pdbqt_str


_FLEX_MET_A = (
    "BEGIN_RES MET A 5\n"
    "ROOT\n"
    "ATOM      1  CA  MET A   5       0.000   0.000   0.000  1.00  0.00     0.000 C \n"
    "ENDROOT\n"
    "BRANCH   1   2\n"
    "ATOM      2  CB  MET A   5       1.530   0.000   0.000  1.00  0.00     0.000 C \n"
    "BRANCH   2   3\n"
    "ATOM      3  CG  MET A   5       2.040   1.440   0.000  1.00  0.00     0.000 C \n"
    "BRANCH   3   4\n"
    "ATOM      4  SD  MET A   5       3.850   1.440   0.000  1.00  0.00     0.000 SA\n"
    "ATOM      5  CE  MET A   5       4.200   3.190   0.250  1.00  0.00     0.000 C \n"
    "ENDBRANCH   3   4\n"
    "ENDBRANCH   2   3\n"
    "ENDBRANCH   1   2\n"
    "END_RES MET A 5\n"
)

_FLEX_MET_B_FLIPPED = (
    "BEGIN_RES MET A 5\n"
    "ROOT\n"
    "ATOM      1  CA  MET A   5       0.000   0.000   0.000  1.00  0.00     0.000 C \n"
    "ENDROOT\n"
    "BRANCH   1   2\n"
    "ATOM      2  CB  MET A   5       1.530   0.000   0.000  1.00  0.00     0.000 C \n"
    "BRANCH   2   3\n"
    "ATOM      3  CG  MET A   5       2.040  -1.440   0.000  1.00  0.00     0.000 C \n"
    "BRANCH   3   4\n"
    "ATOM      4  SD  MET A   5       3.850  -1.440   0.000  1.00  0.00     0.000 SA\n"
    "ATOM      5  CE  MET A   5       4.200  -3.190  -0.250  1.00  0.00     0.000 C \n"
    "ENDBRANCH   3   4\n"
    "ENDBRANCH   2   3\n"
    "ENDBRANCH   1   2\n"
    "END_RES MET A 5\n"
)


def test_complete_linkage_rejects_7a_flipped_pose_and_is_order_invariant() -> None:
    template, p0 = _make_synthetic_ethanol_template_and_pose(0.0)
    _, p_near = _make_synthetic_ethanol_template_and_pose(0.8)
    _, p_mid = _make_synthetic_ethanol_template_and_pose(1.7)
    _, p_chain = _make_synthetic_ethanol_template_and_pose(3.2)
    _, p_flipped_7a = _make_synthetic_ethanol_template_and_pose(7.0, flip_x=True)

    raw_poses = [
        ("pose-0", "vina", 1, p0),
        ("pose-near", "autodock4", 1, p_near),
        ("pose-mid", "vina", 2, p_mid),
        ("pose-chain", "autodock4", 2, p_chain),
        ("pose-flip-7a", "autodock4", 3, p_flipped_7a),
    ]
    candidates = [
        ClusterCandidatePose(
            pose_id=pid,
            source_engine=eng,  # type: ignore[arg-type]
            primary_rank_order=rank,
            pose_complex=PoseComplexIdentity(
                mode=ReceptorFlexMode.RIGID,
                receptor_rigid_sha256=_REC_SHA,
                ligand_pose_sha256=_sha(pdbqt),
            ),
            ligand_pdbqt_text=pdbqt,
        )
        for pid, eng, rank, pdbqt in raw_poses
    ]

    res_fwd = cluster_parent_pose_complexes(
        candidates=candidates,
        reference_conformer_mol=template,
        k_max=10,
        rmsd_threshold_angstrom=2.0,
    )
    res_rev = cluster_parent_pose_complexes(
        candidates=list(reversed(candidates)),
        reference_conformer_mol=template,
        k_max=10,
        rmsd_threshold_angstrom=2.0,
    )

    # Bitwise input-order invariance (E3)
    assert [c.cluster_id for c in res_fwd.retained_clusters] == [
        c.cluster_id for c in res_rev.retained_clusters
    ]
    assert [c.medoid_pose_id for c in res_fwd.retained_clusters] == [
        c.medoid_pose_id for c in res_rev.retained_clusters
    ]

    # Complete-linkage hard diameter bound: every cluster diameter <= 2.0 A, and the 7 A
    # flipped pose is strictly isolated in its own singleton cluster!
    for cluster in res_fwd.retained_clusters:
        assert cluster.max_intra_cluster_rmsd_angstrom <= 2.0 + 1e-9
    flip_cluster = next(
        c for c in res_fwd.retained_clusters if any(m.pose_id == "pose-flip-7a" for m in c.members)
    )
    assert flip_cluster.member_count == 1

    # Complete linkage prevents chaining: pose-0 (0 A) and pose-chain (3.2 A) cannot co-cluster
    for cluster in res_fwd.retained_clusters:
        ids = {m.pose_id for m in cluster.members}
        assert not ({"pose-0", "pose-chain"}.issubset(ids))

    # K_max pre-evaluation truncation (E2)
    res_capped = cluster_parent_pose_complexes(
        candidates=candidates,
        reference_conformer_mol=template,
        k_max=2,
        rmsd_threshold_angstrom=2.0,
    )
    assert res_capped.total_clusters_found == res_fwd.total_clusters_found
    assert len(res_capped.retained_clusters) == 2
    assert res_capped.truncated_by_k_max is True


def test_joint_flexres_clustering_separates_divergent_rotamers_and_respects_symmetry() -> None:
    template, lig_pdbqt = _make_synthetic_ethanol_template_and_pose(2.0)

    # Identical ligand (RMSD_lig = 0 A) + divergent MET A:5 rotamers (RMSD_flex > 3 A) -> split
    c_a = ClusterCandidatePose(
        pose_id="flex-pose-a",
        source_engine="vina",
        primary_rank_order=1,
        pose_complex=PoseComplexIdentity(
            mode=ReceptorFlexMode.SIDECHAIN_FLEX,
            receptor_rigid_sha256=_REC_SHA,
            pose_flex_sidechains_sha256=_sha(_FLEX_MET_A),
            ligand_pose_sha256=_sha(lig_pdbqt),
        ),
        ligand_pdbqt_text=lig_pdbqt,
        pose_flex_sidechains_pdbqt_text=_FLEX_MET_A,
    )
    c_b = ClusterCandidatePose(
        pose_id="flex-pose-b",
        source_engine="autodock4",
        primary_rank_order=1,
        pose_complex=PoseComplexIdentity(
            mode=ReceptorFlexMode.SIDECHAIN_FLEX,
            receptor_rigid_sha256=_REC_SHA,
            pose_flex_sidechains_sha256=_sha(_FLEX_MET_B_FLIPPED),
            ligand_pose_sha256=_sha(lig_pdbqt),
        ),
        ligand_pdbqt_text=lig_pdbqt,
        pose_flex_sidechains_pdbqt_text=_FLEX_MET_B_FLIPPED,
    )
    res = cluster_parent_pose_complexes(
        candidates=[c_a, c_b],
        reference_conformer_mol=template,
        k_max=5,
        rmsd_threshold_angstrom=2.0,
    )
    assert res.total_clusters_found == 2
    assert res.pairwise_joint_rmsd[("flex-pose-a", "flex-pose-b")] > 2.0

    # Symmetric terminal swap on ASP OD1/OD2 gives 0.0 A RMSD (never falsely split!)
    asp_1 = {
        ("A", 10, "", "ASP", "CA"): (0.0, 0.0, 0.0),
        ("A", 10, "", "ASP", "CG"): (2.0, 0.0, 0.0),
        ("A", 10, "", "ASP", "OD1"): (3.0, 1.0, 0.0),
        ("A", 10, "", "ASP", "OD2"): (3.0, -1.0, 0.0),
    }
    asp_swapped = {
        ("A", 10, "", "ASP", "CA"): (0.0, 0.0, 0.0),
        ("A", 10, "", "ASP", "CG"): (2.0, 0.0, 0.0),
        ("A", 10, "", "ASP", "OD1"): (3.0, -1.0, 0.0),
        ("A", 10, "", "ASP", "OD2"): (3.0, 1.0, 0.0),
    }
    assert in_place_flex_sidechains_rmsd(asp_1, asp_swapped) == pytest.approx(0.0, abs=1e-12)


def _pose_complex(tag: str) -> PoseComplexIdentity:
    return PoseComplexIdentity(
        mode=ReceptorFlexMode.RIGID,
        receptor_rigid_sha256=_REC_SHA,
        ligand_pose_sha256=_sha(tag),
    )


def test_parent_weighted_quantiles_non_double_voting_dic_ecr_and_two_tier_invariants() -> None:
    rec_spec = ReceptorFlexSpec(mode=ReceptorFlexMode.RIGID, receptor_rigid_sha256=_REC_SHA)
    enabled = (
        ScoringFunctionId.VINA,
        ScoringFunctionId.VINARDO,
        ScoringFunctionId.AUTODOCK4,
    )

    # Verify block weights prevent vina+vinardo from double-voting against autodock4
    block_w, within_w = resolve_variant_weights(
        variant_id=ConsensusVariantId.PCQ_CORE_V1,
        enabled_functions=enabled,
    )
    assert block_w == {ScoringFamily.VINA_VINARDO: 0.5, ScoringFamily.AUTODOCK4: 0.5}
    assert within_w[ScoringFunctionId.VINA] == pytest.approx(0.5)
    assert within_w[ScoringFunctionId.VINARDO] == pytest.approx(0.5)
    assert within_w[ScoringFunctionId.AUTODOCK4] == pytest.approx(1.0)

    # Parent P1 has 4 identical-score medoids; P2, P3, P4 have 1 medoid each.
    # Parent weighting guarantees P1 contributes total weight 1/4, NEVER 4/7!
    def _medoid(
        cid: str, vina: float, vinardo: float, ad4: float | None, engines: tuple[str, ...]
    ) -> ConsensusPoseScoreInput:
        scores: dict[ScoringFunctionId, float] = {
            ScoringFunctionId.VINA: vina,
            ScoringFunctionId.VINARDO: vinardo,
        }
        if ad4 is not None:
            scores[ScoringFunctionId.AUTODOCK4] = ad4
        return ConsensusPoseScoreInput(
            cluster_id=cid,
            medoid_pose_id=f"pose-{cid}",
            pose_complex=_pose_complex(cid),
            canonical_coordinate_sha256=_sha(f"coord-{cid}"),
            search_engines_present=engines,  # type: ignore[arg-type]
            scores_by_function=scores,
        )

    parents = (
        ConsensusParentInput(
            parent_compound_id="P1_concordant_best",
            parent_state_id="P1-s1",
            rotatable_bond_count=8,
            medoids=(
                _medoid("p1-c1", -10.0, -10.0, -10.0, ("vina", "autodock4")),
                _medoid("p1-c2", -10.0, -10.0, -10.0, ("vina",)),
                _medoid("p1-c3", -10.0, -10.0, -10.0, ("vina",)),
                _medoid("p1-c4", -10.0, -10.0, -10.0, ("vina",)),
            ),
        ),
        ConsensusParentInput(
            parent_compound_id="P2_polarized_disagreement",
            parent_state_id="P2-s1",
            rotatable_bond_count=3,
            # Top in Vina/Vinardo (-11.0), worst in AD4 (-4.0)!
            medoids=(_medoid("p2-c1", -11.0, -11.0, -4.0, ("vina",)),),
        ),
        ConsensusParentInput(
            parent_compound_id="P3_mid",
            parent_state_id="P3-s1",
            rotatable_bond_count=2,
            medoids=(_medoid("p3-c1", -8.0, -8.0, -8.0, ("vina", "autodock4")),),
        ),
        ConsensusParentInput(
            parent_compound_id="P4_worst",
            parent_state_id="P4-s1",
            rotatable_bond_count=1,
            medoids=(_medoid("p4-c1", -6.0, -6.0, -6.0, ("autodock4",)),),
        ),
        ConsensusParentInput(
            parent_compound_id="P5_macrocycle_missing_ad4",
            parent_state_id="P5-s1",
            rotatable_bond_count=5,
            medoids=(_medoid("p5-c1", -9.5, -9.5, None, ("vina",)),),
            failure_or_exclusion_codes=("AUTODOCK4_UNSUPPORTED_CG0_PSEUDOATOM",),
        ),
    )

    panel = build_reference_panel(
        receptor_id="rec-1",
        binding_site_id="site-1",
        receptor_flex_spec=rec_spec,
        binding_box_sha256=_BOX_SHA,
        autogrid_map_set_sha256=_MAP_SHA,
        enabled_functions=enabled,
        k_max=4,
        parents=parents,
    )
    assert panel.total_panel_parents == 4  # P5 excluded from panel because partial

    # Verify parent-weighted midrank for P3 (-8.0 in Vina):
    # Strictly worse than P3: P4 (-6.0) -> 1 parent (weight 1/4)
    # Tied with P3: P3 (-8.0) -> 0.5 * 1/4 = 1/8
    # Strictly better than P3: P1 (-10.0 across 4 medoids -> STILL weight 1/4!) and P2 (-11.0)
    # Exact q_vina(-8.0) = (1 + 0.5) / 4 = 0.375!
    q_p3_vina = parent_weighted_midrank_quantile(
        panel=panel, scoring_function=ScoringFunctionId.VINA, raw_score=-8.0
    )
    assert q_p3_vina == pytest.approx(0.375, abs=1e-12)

    out = compute_pcq_and_ecr_consensus(
        variant_id=ConsensusVariantId.PCQ_CORE_V1,
        enabled_functions=enabled,
        reference_panel=panel,
        parents=parents,
        search_engine_count=2,
    )

    # E6 two-tier denominator invariant
    assert out.ranking.method is RankingMethod.PC_Q_CORE_V1
    assert out.ranking.total_parents == 5
    assert out.ranking.full_profile_count == 4
    assert out.ranking.partial_or_unscored_count == 1
    assert out.core_ranking is None
    assert out.ecr_ranking.method is RankingMethod.PC_ECR_V1

    # P1 concordant best beats P2 polarized disagreement!
    by_id = {d.parent_compound_id: d for d in out.parent_details}
    p1 = by_id["P1_concordant_best"]
    p2 = by_id["P2_polarized_disagreement"]
    p5 = by_id["P5_macrocycle_missing_ad4"]
    assert p1.pcq_score is not None and p2.pcq_score is not None
    assert p1.pcq_score > p2.pcq_score
    assert p1.inter_family_disagreement is not None and p2.inter_family_disagreement is not None
    # P2: q_vina_block = (3 + 0.5)/4 = 0.875, q_ad4 = (0 + 0.5)/4 = 0.125 -> PC-Q=50.0, D_ic=37.5
    # P1: q_vina_block = (2 + 0.5)/4 = 0.625, q_ad4 = (3 + 0.5)/4 = 0.875 -> PC-Q=75.0, D_ic=12.5
    assert p2.pcq_score == pytest.approx(50.0, abs=1e-9)
    assert p2.inter_family_disagreement == pytest.approx(37.5, abs=1e-9)
    assert p1.pcq_score == pytest.approx(75.0, abs=1e-9)
    assert p1.inter_family_disagreement == pytest.approx(12.5, abs=1e-9)

    # E5: PC-ECR matches exact Palacio-Rodriguez kernel on 1/sigma scale
    expected_p1_ecr = compute_pc_ecr_from_block_quantiles(
        block_quantiles=p1.medoids[0].block_quantiles,
        block_weights=block_w,
        n_panel_parents=4,
        tau=FROZEN_ECR_TAU,
    )
    sigma = FROZEN_ECR_TAU * 4.0
    q_vv = p1.medoids[0].block_quantiles[ScoringFamily.VINA_VINARDO]
    q_ad = p1.medoids[0].block_quantiles[ScoringFamily.AUTODOCK4]
    manual_ecr = (
        0.5 * exp(-(1.0 + (1.0 - q_vv) * 3.0) / sigma)
        + 0.5 * exp(-(1.0 + (1.0 - q_ad) * 3.0) / sigma)
    ) / sigma
    assert p1.pc_ecr_score == pytest.approx(expected_p1_ecr, abs=1e-12)
    assert expected_p1_ecr == pytest.approx(manual_ecr, abs=1e-12)

    # Partial parent retained with zero imputation
    assert p5.tier == "partial_or_unscored"
    assert p5.pcq_score is None
    assert p5.pc_ecr_score is None
    assert "AUTODOCK4_UNSUPPORTED_CG0_PSEUDOATOM" in p5.failure_or_exclusion_codes
    warn_codes = {w.code for w in out.warnings}
    assert WarningCode.CONSENSUS_PARTIAL_PROFILE_RETAINED in warn_codes
    assert WarningCode.CONSENSUS_HIGH_INTER_FAMILY_DISAGREEMENT in warn_codes


def test_pcq_neural_v1_always_computes_windows_comparable_core_alongside() -> None:
    rec_spec = ReceptorFlexSpec(mode=ReceptorFlexMode.RIGID, receptor_rigid_sha256=_REC_SHA)
    enabled = (
        ScoringFunctionId.VINA,
        ScoringFunctionId.AUTODOCK4,
        ScoringFunctionId.GNINA_CNN_VS,
    )
    parents = (
        ConsensusParentInput(
            parent_compound_id="N1",
            parent_state_id="N1-s1",
            medoids=(
                ConsensusPoseScoreInput(
                    cluster_id="n1-c1",
                    medoid_pose_id="p-n1",
                    pose_complex=_pose_complex("n1"),
                    canonical_coordinate_sha256=_sha("n1-coord"),
                    search_engines_present=("vina", "autodock4", "gnina"),
                    scores_by_function={
                        ScoringFunctionId.VINA: -9.5,
                        ScoringFunctionId.AUTODOCK4: -9.0,
                        ScoringFunctionId.GNINA_CNN_VS: 7.2,
                    },
                ),
            ),
        ),
        ConsensusParentInput(
            parent_compound_id="N2",
            parent_state_id="N2-s1",
            medoids=(
                ConsensusPoseScoreInput(
                    cluster_id="n2-c1",
                    medoid_pose_id="p-n2",
                    pose_complex=_pose_complex("n2"),
                    canonical_coordinate_sha256=_sha("n2-coord"),
                    search_engines_present=("vina",),
                    scores_by_function={
                        ScoringFunctionId.VINA: -6.0,
                        ScoringFunctionId.AUTODOCK4: -6.0,
                        ScoringFunctionId.GNINA_CNN_VS: 2.1,
                    },
                ),
            ),
        ),
    )
    panel = build_reference_panel(
        receptor_id="rec-1",
        binding_site_id="site-1",
        receptor_flex_spec=rec_spec,
        binding_box_sha256=_BOX_SHA,
        autogrid_map_set_sha256=_MAP_SHA,
        enabled_functions=enabled,
        k_max=3,
        parents=parents,
    )
    out = compute_pcq_and_ecr_consensus(
        variant_id=ConsensusVariantId.PCQ_NEURAL_V1,
        enabled_functions=enabled,
        reference_panel=panel,
        parents=parents,
        search_engine_count=3,
    )
    assert out.ranking.method is RankingMethod.PC_Q_NEURAL_V1
    assert out.core_ranking is not None
    assert out.core_ranking.method is RankingMethod.PC_Q_CORE_V1
    assert out.block_weights[ScoringFamily.GNINA_NEURAL] == pytest.approx(1.0 / 3.0)


def test_pc_l2_strictly_convex_non_negative_fit_and_confirmation_promotion_gate(
    tmp_path: Path,
) -> None:
    """Verifies both PC-L2 outcomes under ADR-030 §3:
    1. Orthogonal complementarity (Vina rescues half of actives, AD4 rescues the other half)
       -> PC-L2 beats BOTH single engines on locked Confirmation (`promoted = True`).
    2. Identical/collinear single-engine signal -> PC-L2 cannot beat the single engine
       -> `promoted = False` + verbatim `"Insufficient evidence to prefer over baseline"`.
    """
    cores = (
        "c1ccccc1",
        "c1ccc2ccccc2c1",
        "c1ccncc1",
        "C1CCCCC1",
        "c1ccsc1",
        "C1CCNCC1",
        "c1ccc(-c2ccccc2)cc1",
        "c1cnc2ccccc2c1",
        "c1ccoc1",
        "C1CCOC1",
    )
    compounds: list[CalibrationCompoundInput] = []
    for fam_idx, core in enumerate(cores):
        for member in range(10):
            compounds.append(
                CalibrationCompoundInput(
                    parent_id=f"pcl2_f{fam_idx}_m{member}",
                    canonical_smiles=f"{core}{'C' * (member + 1)}",
                    is_active=(member < 4),
                )
            )

    cal_service = ProtocolCalibrationService(store=CalibrationArtifactStore(root=tmp_path))
    cal_run = cal_service.create_split(
        project_id="default",
        receptor_id="rec-pcl2",
        binding_site_id="site-pcl2",
        compounds=compounds,
        policy=CalibrationSplitPolicy(bootstrap_replicates=250, min_confirmation_actives=8),
    )
    rec_spec = ReceptorFlexSpec(mode=ReceptorFlexMode.RIGID, receptor_rigid_sha256=_REC_SHA)
    enabled = (
        ScoringFunctionId.VINA,
        ScoringFunctionId.AUTODOCK4,
        ScoringFunctionId.GNINA_CNN_VS,
    )

    def _run_scenario(
        *,
        mode: str,
        underpowered: bool = False,
    ) -> tuple[bool, str, dict[ScoringFunctionId, float]]:
        split_run = (
            cal_service.create_split(
                project_id="default",
                receptor_id="rec-pcl2-up",
                binding_site_id="site-pcl2",
                compounds=compounds,
                policy=CalibrationSplitPolicy(
                    bootstrap_replicates=250, min_confirmation_actives=999
                ),
            )
            if underpowered
            else cal_run
        )
        parents: list[ConsensusParentInput] = []
        active_counter = 0
        for idx, comp in enumerate(split_run.split.compounds):
            if comp.is_active:
                active_counter += 1
                if mode == "asymmetric_complementary":
                    # Vina & AD4 rescue orthogonal halves of actives while GNINA is anti-correlated
                    # noise: unfitted 1/3-1/3-1/3 PC-Q is dragged down by GNINA, whereas PC-L2
                    # zeros GNINA and strictly beats BOTH every single engine AND unfitted PC-Q!
                    if active_counter % 2 == 0:
                        vina_s, ad4_s, gnina_s = -10.8, -7.8, 1.5
                    else:
                        vina_s, ad4_s, gnina_s = -7.8, -10.8, 1.5
                elif mode == "handicapped_vina":
                    vina_s, ad4_s, gnina_s = -6.0, -9.5, 6.0
                else:
                    vina_s, ad4_s, gnina_s = -9.5, -9.5, 8.0
            else:
                if mode == "asymmetric_complementary":
                    vina_s = -8.4 if (idx % 2 == 0) else -6.0
                    ad4_s = -6.0 if (idx % 2 == 0) else -8.4
                    gnina_s = 7.5
                elif mode == "handicapped_vina":
                    vina_s, ad4_s, gnina_s = -7.5, -6.5, 2.0
                else:
                    vina_s = -8.4 if (idx % 2 == 0) else -6.0
                    ad4_s = -6.0 if (idx % 2 == 0) else -8.4
                    gnina_s = 3.0

            medoids_list = [
                ConsensusPoseScoreInput(
                    cluster_id=f"c1-{comp.parent_id}",
                    medoid_pose_id=f"p1-{comp.parent_id}",
                    pose_complex=_pose_complex(f"{comp.parent_id}-c1"),
                    canonical_coordinate_sha256=_sha(f"{comp.parent_id}-c1"),
                    search_engines_present=("vina", "autodock4", "gnina"),
                    scores_by_function={
                        ScoringFunctionId.VINA: vina_s,
                        ScoringFunctionId.AUTODOCK4: ad4_s,
                        ScoringFunctionId.GNINA_CNN_VS: gnina_s,
                    },
                )
            ]
            if mode == "handicapped_vina":
                # Second medoid where Vina alone achieves perfect active separation (BEDROC=1.0),
                # while PC-Q picks c1 -> PC-L2 must NOT falsely beat Vina!
                medoids_list.append(
                    ConsensusPoseScoreInput(
                        cluster_id=f"c2-{comp.parent_id}",
                        medoid_pose_id=f"p2-{comp.parent_id}",
                        pose_complex=_pose_complex(f"{comp.parent_id}-c2"),
                        canonical_coordinate_sha256=_sha(f"{comp.parent_id}-c2"),
                        search_engines_present=("vina", "autodock4", "gnina"),
                        scores_by_function={
                            ScoringFunctionId.VINA: -12.0 if comp.is_active else -5.0,
                            ScoringFunctionId.AUTODOCK4: -4.0,
                            ScoringFunctionId.GNINA_CNN_VS: 0.5,
                        },
                    )
                )
            parents.append(
                ConsensusParentInput(
                    parent_compound_id=comp.parent_id,
                    parent_state_id=f"{comp.parent_id}-s1",
                    medoids=tuple(medoids_list),
                )
            )
        panel = build_reference_panel(
            receptor_id="rec-pcl2",
            binding_site_id="site-pcl2",
            receptor_flex_spec=rec_spec,
            binding_box_sha256=_BOX_SHA,
            autogrid_map_set_sha256=_MAP_SHA,
            enabled_functions=enabled,
            k_max=2,
            parents=parents,
        )
        out = compute_pcq_and_ecr_consensus(
            variant_id=ConsensusVariantId.PCQ_NEURAL_V1,
            enabled_functions=enabled,
            reference_panel=panel,
            parents=parents,
            search_engine_count=3,
        )
        model, pcl2_ranking, warnings = fit_and_gate_pc_l2(
            calibration=split_run,
            reference_panel=panel,
            feature_functions=enabled,
            parent_details_by_id={d.parent_compound_id: d for d in out.parent_details},
            l2_regularization=0.1,
        )
        assert pcl2_ranking.method is RankingMethod.PC_L2_V1
        assert model.converged is True
        assert model.confirmation_delta_vs_pcq is not None
        assert all(w >= 0.0 for w in model.weights.values())
        if not model.promoted:
            assert any(w.code is WarningCode.CONSENSUS_PCL2_UNPROMOTED for w in warnings)
        return model.promoted, model.promotion_verdict_text, model.weights

    promoted_asym, verdict_asym, weights_asym = _run_scenario(mode="asymmetric_complementary")
    assert promoted_asym is True
    assert weights_asym[ScoringFunctionId.VINA] > 0.0
    assert weights_asym[ScoringFunctionId.AUTODOCK4] > 0.0
    assert "Promoted" in verdict_asym

    # Underpowered confirmation split must NEVER promote (D2-006)
    promoted_up, verdict_up, _ = _run_scenario(mode="asymmetric_complementary", underpowered=True)
    assert promoted_up is False
    assert verdict_up == INSUFFICIENT_EVIDENCE_TEXT

    # Multi-medoid unbiased Vina baseline (BEDROC=1.0 on c2) blocks false promotion (D2-006)
    promoted_hc, verdict_hc, _ = _run_scenario(mode="handicapped_vina")
    assert promoted_hc is False
    assert verdict_hc == INSUFFICIENT_EVIDENCE_TEXT

    promoted_collinear, verdict_collinear, _ = _run_scenario(mode="collinear")
    assert promoted_collinear is False
    assert verdict_collinear == INSUFFICIENT_EVIDENCE_TEXT


def test_consensus_rejects_invalid_family_membership_and_non_positive_kmax() -> None:
    with pytest.raises(AnkoraDomainError) as exc_info:
        resolve_variant_weights(
            variant_id=ConsensusVariantId.PCQ_CORE_V1,
            enabled_functions=(ScoringFunctionId.VINA, ScoringFunctionId.VINARDO),
        )
    assert exc_info.value.code == "CONSENSUS_VARIANT_FAMILY_MISMATCH"

    template, _ = _make_synthetic_ethanol_template_and_pose(0.0)
    with pytest.raises(AnkoraDomainError) as exc_k:
        cluster_parent_pose_complexes(
            candidates=[],
            reference_conformer_mol=template,
            k_max=0,
        )
    assert exc_k.value.code == "CONSENSUS_KMAX_INVALID"


def test_pose_clustering_handles_meeko_self_clash_without_spurious_proximity_bonds() -> None:
    """Synthetic self-clashing pose clusters cleanly via Meeko topology; non-Meeko fails closed."""
    import meeko
    from rdkit import Chem
    from rdkit.Chem import AllChem

    # Synthetic 1-butane chain where terminal carbons C1 and C4 fold within 1.1 A (steric clash)
    mol = Chem.AddHs(Chem.MolFromSmiles("CCCC"))
    assert AllChem.EmbedMolecule(mol, randomSeed=42) == 0
    ref_no_h = Chem.RemoveHs(Chem.Mol(mol))

    prep = meeko.MoleculePreparation()
    setups = prep.prepare(mol)
    pdbqt_ok, is_ok, _ = meeko.PDBQTWriterLegacy.write_string(setups[0])
    assert is_ok

    # Fold atom 4 (terminal carbon) right next to atom 1 (within 1.1 A) in the Meeko PDBQT copy
    clashed_lines: list[str] = []
    heavy_idx = 0
    c1_xyz: tuple[float, float, float] | None = None
    for line in pdbqt_ok.splitlines():
        if line.startswith(("ATOM  ", "HETATM")):
            atype = line[77:79].strip()
            if atype not in {"H", "HD", "HS"}:
                heavy_idx += 1
                if heavy_idx == 1:
                    c1_xyz = (float(line[30:38]), float(line[38:46]), float(line[46:54]))
                elif heavy_idx == 4 and c1_xyz is not None:
                    line = (
                        f"{line[:30]}"
                        f"{c1_xyz[0] + 1.10:8.3f}{c1_xyz[1]:8.3f}{c1_xyz[2]:8.3f}"
                        f"{line[54:]}"
                    )
        clashed_lines.append(line)
    pdbqt_clashed_meeko = "\n".join(clashed_lines) + "\n"

    # With Meeko REMARK SMILES intact, clustering preserves exact 4-atom / 3-bond topology
    result = cluster_parent_pose_complexes(
        candidates=[
            ClusterCandidatePose(
                pose_id="p-ok",
                source_engine="vina",
                primary_rank_order=1,
                pose_complex=_pose_complex("p-ok"),
                ligand_pdbqt_text=pdbqt_ok,
            ),
            ClusterCandidatePose(
                pose_id="p-clashed",
                source_engine="gnina",
                primary_rank_order=2,
                pose_complex=_pose_complex("p-clashed"),
                ligand_pdbqt_text=pdbqt_clashed_meeko,
            ),
        ],
        reference_conformer_mol=ref_no_h,
        k_max=3,
    )
    assert result.total_input_poses == 2
    assert result.total_clusters_found >= 1

    # Without Meeko topology remarks, proximity bonding creates a spurious 4th bond -> fail closed
    stripped_non_meeko = "\n".join(
        line for line in clashed_lines if not line.startswith("REMARK")
    ) + "\n"
    with pytest.raises(AnkoraDomainError) as exc_topo:
        cluster_parent_pose_complexes(
            candidates=[
                ClusterCandidatePose(
                    pose_id="p-clashed-raw",
                    source_engine="gnina",
                    primary_rank_order=1,
                    pose_complex=_pose_complex("p-clashed-raw"),
                    ligand_pdbqt_text=stripped_non_meeko,
                )
            ],
            reference_conformer_mol=ref_no_h,
            k_max=3,
        )
    assert exc_topo.value.code == "CONSENSUS_POSE_TOPOLOGY_MISMATCH"


def test_pcq_math_ranking_order_scale_invariance_metadata_and_nan_guards() -> None:
    """D2-007/D2-008/D2-009/D2-016 + D4-011 + pcq_math mutation oracles."""
    from pydantic import ValidationError

    from ankora_backend.adapters.consensus.pcq_math import (
        _build_two_tier_ranking,
        _RankingRow,
        compute_pc_ecr_from_block_quantiles,
        parent_weighted_midrank_quantile,
    )
    from ankora_backend.schemas.v02_contracts import ScoringFamily

    rec_spec = ReceptorFlexSpec(mode=ReceptorFlexMode.RIGID, receptor_rigid_sha256=_REC_SHA)
    enabled = (
        ScoringFunctionId.VINA,
        ScoringFunctionId.AUTODOCK4,
        ScoringFunctionId.GNINA_CNN_VS,
    )

    # 1. D2-007: NaN/inf rejected by ConsensusPoseScoreInput AND parent_weighted_midrank_quantile
    with pytest.raises(ValidationError):
        ConsensusPoseScoreInput(
            cluster_id="c-nan",
            medoid_pose_id="p-nan",
            pose_complex=_pose_complex("p-nan"),
            canonical_coordinate_sha256=_sha("p-nan"),
            search_engines_present=("vina",),
            scores_by_function={ScoringFunctionId.VINA: float("nan")},
        )

    # 2. Build 10-parent neural panel + parent with divergent PC-Q vs PC-ECR medoids (D2-008)
    #    + parent with Vina+AD4 complete but GNINA missing (must still rank in core_ranking!)
    parents: list[ConsensusParentInput] = []
    for idx in range(10):
        pid = f"bg_{idx:02d}"
        score = -10.0 + idx * 0.5
        parents.append(
            ConsensusParentInput(
                parent_compound_id=pid,
                parent_state_id=f"{pid}-s1",
                medoids=(
                    ConsensusPoseScoreInput(
                        cluster_id=f"c-{pid}",
                        medoid_pose_id=f"m-{pid}",
                        pose_complex=_pose_complex(pid),
                        canonical_coordinate_sha256=_sha(pid),
                        search_engines_present=("vina", "autodock4", "gnina"),
                        scores_by_function={
                            ScoringFunctionId.VINA: score,
                            ScoringFunctionId.AUTODOCK4: score,
                            ScoringFunctionId.GNINA_CNN_VS: 10.0 - idx * 0.5,
                        },
                    ),
                ),
            )
        )
    # Parent p_div: c_balanced wins PC-Q (high mean, low D_ic, conv=2),
    # while c_spiky wins PC-ECR (one family at Q=1.0, huge D_ic, conv=1)
    parents.append(
        ConsensusParentInput(
            parent_compound_id="p_div",
            parent_state_id="p_div-s1",
            medoids=(
                ConsensusPoseScoreInput(
                    cluster_id="c_balanced",
                    medoid_pose_id="m_bal",
                    pose_complex=_pose_complex("p_div-bal"),
                    canonical_coordinate_sha256=_sha("p_div-bal"),
                    search_engines_present=("vina", "autodock4"),
                    scores_by_function={
                        ScoringFunctionId.VINA: -9.2,
                        ScoringFunctionId.AUTODOCK4: -9.2,
                        ScoringFunctionId.GNINA_CNN_VS: 9.2,
                    },
                ),
                ConsensusPoseScoreInput(
                    cluster_id="c_spiky",
                    medoid_pose_id="m_spiky",
                    pose_complex=_pose_complex("p_div-spiky"),
                    canonical_coordinate_sha256=_sha("p_div-spiky"),
                    search_engines_present=("gnina",),
                    scores_by_function={
                        ScoringFunctionId.VINA: -5.0,
                        ScoringFunctionId.AUTODOCK4: -5.0,
                        ScoringFunctionId.GNINA_CNN_VS: 12.0,
                    },
                ),
            ),
        )
    )
    # Parent p_core_only: Vina+AD4 succeeded, GNINA failed -> partial in neural, full in core!
    parents.append(
        ConsensusParentInput(
            parent_compound_id="p_core_only",
            parent_state_id="p_core_only-s1",
            medoids=(
                ConsensusPoseScoreInput(
                    cluster_id="c_core",
                    medoid_pose_id="m_core",
                    pose_complex=_pose_complex("p_core_only"),
                    canonical_coordinate_sha256=_sha("p_core_only"),
                    search_engines_present=("vina", "autodock4"),
                    scores_by_function={
                        ScoringFunctionId.VINA: -9.8,
                        ScoringFunctionId.AUTODOCK4: -9.8,
                    },
                ),
            ),
        )
    )
    # Parent p_empty_fail: zero medoids & empty failure codes -> fallback code (kills M15)
    parents.append(
        ConsensusParentInput(
            parent_compound_id="p_empty_fail",
            parent_state_id="p_empty_fail-s1",
            medoids=(),
            failure_or_exclusion_codes=(),
        )
    )

    panel = build_reference_panel(
        receptor_id="rec-u4",
        binding_site_id="site-u4",
        receptor_flex_spec=rec_spec,
        binding_box_sha256=_BOX_SHA,
        autogrid_map_set_sha256=_MAP_SHA,
        enabled_functions=enabled,
        k_max=2,
        parents=parents,
    )
    with pytest.raises(AnkoraDomainError) as nan_exc:
        parent_weighted_midrank_quantile(
            panel=panel, scoring_function=ScoringFunctionId.VINA, raw_score=float("nan")
        )
    assert nan_exc.value.code == "CONSENSUS_NON_FINITE_SCORE"

    out = compute_pcq_and_ecr_consensus(
        variant_id=ConsensusVariantId.PCQ_NEURAL_V1,
        enabled_functions=enabled,
        reference_panel=panel,
        parents=parents,
        search_engine_count=3,
    )

    # Assert strict descending rank order in primary ranking (kills D2-016 / M13 & M14!)
    full_entries = [e for e in out.ranking.entries if e.tier == "full_profile"]
    assert full_entries[0].parent_compound_id == "bg_00"
    assert full_entries[0].rank == 1
    assert full_entries[-1].parent_compound_id == "bg_09"
    assert full_entries[0].score_value is not None and full_entries[-1].score_value is not None
    assert full_entries[0].score_value > full_entries[-1].score_value

    # Assert p_div medoid choices & independent D_ic / convergence metadata (D2-008/D4-011)
    p_div_detail = next(d for d in out.parent_details if d.parent_compound_id == "p_div")
    assert p_div_detail.selected_medoid_cluster_id == "c_balanced"
    assert p_div_detail.pc_ecr_selected_cluster_id == "c_spiky"
    ecr_div = next(e for e in out.ecr_ranking.entries if e.parent_compound_id == "p_div")
    assert ecr_div.search_convergence_count == 1
    assert (
        ecr_div.inter_family_disagreement is not None and ecr_div.inter_family_disagreement > 30.0
    )
    pcq_div = next(e for e in out.ranking.entries if e.parent_compound_id == "p_div")
    assert pcq_div.search_convergence_count == 2
    assert pcq_div.inter_family_disagreement is not None and pcq_div.inter_family_disagreement < 5.0

    # Assert core_ranking rescues p_core_only even when GNINA is missing (D2-008)
    assert out.core_ranking is not None
    core_only_neural = next(
        e for e in out.ranking.entries if e.parent_compound_id == "p_core_only"
    )
    core_only_core = next(
        e for e in out.core_ranking.entries if e.parent_compound_id == "p_core_only"
    )
    assert core_only_neural.tier == "partial_or_unscored"
    assert core_only_core.tier == "full_profile"
    assert core_only_core.score_value is not None and core_only_core.score_value > 80.0

    # Assert partial parent with empty codes gets fallback code (kills M15)
    empty_entry = next(e for e in out.ranking.entries if e.parent_compound_id == "p_empty_fail")
    assert empty_entry.failure_or_exclusion_codes == ("CONSENSUS_NO_FULL_PROFILE_MEDOID",)

    # 3. D2-009: PC-ECR scale invariance at N_panel = 100,000 (must NOT collapse ranks!)
    bw = {ScoringFamily.VINA_VINARDO: 0.5, ScoringFamily.AUTODOCK4: 0.5}
    ecr_hi = compute_pc_ecr_from_block_quantiles(
        block_quantiles={ScoringFamily.VINA_VINARDO: 0.05, ScoringFamily.AUTODOCK4: 0.05},
        block_weights=bw,
        n_panel_parents=100_000,
    )
    ecr_lo = compute_pc_ecr_from_block_quantiles(
        block_quantiles={ScoringFamily.VINA_VINARDO: 0.0, ScoringFamily.AUTODOCK4: 0.0},
        block_weights=bw,
        n_panel_parents=100_000,
    )
    assert ecr_hi > ecr_lo
    d_a = out.parent_details[0]
    d_b = out.parent_details[1]
    assert d_a.selected_pose_complex is not None and d_b.selected_pose_complex is not None
    rk_100k = _build_two_tier_ranking(
        method=RankingMethod.PC_ECR_V1,
        reference_panel_sha256=panel.reference_panel_sha256,
        full_rows=[
            _RankingRow(d_b, ecr_hi, d_b.selected_pose_complex, None, 0.0, 1, 1),
            _RankingRow(d_a, ecr_lo, d_a.selected_pose_complex, None, 0.0, 1, 1),
        ],
        partial_rows=[],
        tie_policy="test",
        failure_policy="test",
    )
    assert [e.parent_compound_id for e in rk_100k.entries] == [
        d_b.parent_compound_id,
        d_a.parent_compound_id,
    ]
    assert [e.rank for e in rk_100k.entries] == [1, 2]


def test_pose_clustering_stereo_charge_meeko_error_macrocycle_and_3d_flex_oracles(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """D1-009, D4-006, D4-012, D4-003 + pose_clustering mutation oracles."""
    import meeko
    from rdkit import Chem
    from rdkit.Chem import AllChem

    from ankora_backend.adapters.chemistry.pose_clustering import (
        extract_heavy_atom_coords_from_pdbqt,
        in_place_flex_sidechains_rmsd,
    )
    from ankora_backend.services.pose_interactions import _ordered_autodock_runs

    # 1. D4-006: opposite enantiomers & distinct protonation states MUST fail closed
    mol_r = Chem.AddHs(Chem.MolFromSmiles("C[C@H](O)F"))
    mol_s = Chem.AddHs(Chem.MolFromSmiles("C[C@@H](O)F"))
    assert AllChem.EmbedMolecule(mol_r, randomSeed=42) == 0
    assert AllChem.EmbedMolecule(mol_s, randomSeed=42) == 0
    prep = meeko.MoleculePreparation()
    pdbqt_s, ok_s, _ = meeko.PDBQTWriterLegacy.write_string(prep.prepare(mol_s)[0])
    assert ok_s
    with pytest.raises(AnkoraDomainError) as enantiomer_exc:
        cluster_parent_pose_complexes(
            candidates=[
                ClusterCandidatePose(
                    pose_id="p-s",
                    source_engine="vina",
                    primary_rank_order=1,
                    pose_complex=_pose_complex("p-s"),
                    ligand_pdbqt_text=pdbqt_s,
                )
            ],
            reference_conformer_mol=mol_r,
            k_max=2,
        )
    assert enantiomer_exc.value.code == "CONSENSUS_POSE_TOPOLOGY_MISMATCH"

    # Distinct protonation states (CCN vs CC[NH3+]) must also fail closed
    amine = Chem.AddHs(Chem.MolFromSmiles("CCN"))
    ammonium = Chem.AddHs(Chem.MolFromSmiles("CC[NH3+]"))
    assert AllChem.EmbedMolecule(amine, randomSeed=7) == 0
    assert AllChem.EmbedMolecule(ammonium, randomSeed=7) == 0
    pdbqt_nh3, ok_nh3, _ = meeko.PDBQTWriterLegacy.write_string(prep.prepare(ammonium)[0])
    assert ok_nh3
    with pytest.raises(AnkoraDomainError) as charge_exc:
        cluster_parent_pose_complexes(
            candidates=[
                ClusterCandidatePose(
                    pose_id="p-nh3",
                    source_engine="vina",
                    primary_rank_order=1,
                    pose_complex=_pose_complex("p-nh3"),
                    ligand_pdbqt_text=pdbqt_nh3,
                )
            ],
            reference_conformer_mol=amine,
            k_max=2,
        )
    assert charge_exc.value.code == "CONSENSUS_POSE_TOPOLOGY_MISMATCH"

    # 2. D1-009: Meeko failure cause must be preserved in fallback AnkoraDomainError.details
    def _boom(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("synthetic_meeko_boom")

    monkeypatch.setattr(meeko, "PDBQTMolecule", _boom)
    bad_type_pdbqt = (
        "MODEL 1\n"
        "ATOM      1  C1  UNL     1       0.000   0.000   0.000  1.00  0.00    +0.000 ZZ\n"
        "ENDMDL\n"
    )
    with pytest.raises(AnkoraDomainError) as meeko_exc:
        cluster_parent_pose_complexes(
            candidates=[
                ClusterCandidatePose(
                    pose_id="p-boom",
                    source_engine="vina",
                    primary_rank_order=1,
                    pose_complex=_pose_complex("p-boom"),
                    ligand_pdbqt_text=bad_type_pdbqt,
                )
            ],
            reference_conformer_mol=amine,
            k_max=1,
        )
    assert "synthetic_meeko_boom" in str(meeko_exc.value.details)
    monkeypatch.undo()

    # 3. D4-012: Flexible 12-carbon cyclododecane yields 12 heavy atoms (drops 2 G0, keeps 2 CG0)
    cyc12 = Chem.AddHs(Chem.MolFromSmiles("C1CCCCCCCCCCC1"))
    assert AllChem.EmbedMolecule(cyc12, randomSeed=42) == 0
    prep_flex = meeko.MoleculePreparation(rigid_macrocycles=False)
    pdbqt_cyc12, ok_c12, _ = meeko.PDBQTWriterLegacy.write_string(prep_flex.prepare(cyc12)[0])
    assert ok_c12 and "G0" in pdbqt_cyc12 and "CG0" in pdbqt_cyc12
    extracted = extract_heavy_atom_coords_from_pdbqt(pdbqt_cyc12)
    assert len(extracted) == 12

    # Truncated <54-char & NaN lines fail closed (kills M05)
    with pytest.raises(AnkoraDomainError) as trunc_exc:
        extract_heavy_atom_coords_from_pdbqt("ATOM      1  C1  UNL     1\n")
    assert trunc_exc.value.code == "CONSENSUS_COORDINATES_UNREADABLE"
    with pytest.raises(AnkoraDomainError) as nan_coord_exc:
        extract_heavy_atom_coords_from_pdbqt(
            "ATOM      1  C1  UNL     1         nan   0.000   0.000  1.00  0.00    +0.000 C \n"
        )
    assert nan_coord_exc.value.code == "CONSENSUS_COORDINATES_UNREADABLE"

    # 4. 3D non-planar off-origin FlexRes RMSD & symmetric ASP OD1/OD2 swap in Z (kills M08..M13)
    with pytest.raises(AnkoraDomainError):
        in_place_flex_sidechains_rmsd({}, {})
    k_cg = ("A", 10, "", "ASP", "CG")
    k_od1 = ("A", 10, "", "ASP", "OD1")
    k_od2 = ("A", 10, "", "ASP", "OD2")
    flex_a = {
        k_cg: (5.0, -3.0, 2.0),
        k_od1: (5.0, -3.0, 4.0),
        k_od2: (5.0, -3.0, 0.0),
    }
    # Swapping OD1/OD2 purely along Z -> exact 0.0 A (kills M13 Z-sign in swap loop!)
    flex_swapped = {
        k_cg: (5.0, -3.0, 2.0),
        k_od1: (5.0, -3.0, 0.0),
        k_od2: (5.0, -3.0, 4.0),
    }
    assert in_place_flex_sidechains_rmsd(flex_a, flex_swapped) == pytest.approx(0.0, abs=1e-9)
    # Pure Z shift +2.5 A (kills M09 & M11!)
    flex_z = {k: (x, y, z + 2.5) for k, (x, y, z) in flex_a.items()}
    assert in_place_flex_sidechains_rmsd(flex_a, flex_z) == pytest.approx(2.5, abs=1e-9)

    # 5. k_max=1 & rmsd_threshold<=0 & multi-engine convergence ranking (kills M15, M16, M18, M20)
    template, pose_origin = _make_synthetic_ethanol_template_and_pose(0.0)
    _, pose_far = _make_synthetic_ethanol_template_and_pose(10.0)
    with pytest.raises(AnkoraDomainError):
        cluster_parent_pose_complexes(
            candidates=[],
            reference_conformer_mol=template,
            k_max=1,
            rmsd_threshold_angstrom=0.0,
        )
    # Cluster B (at x=10, found by 2 engines: vina + autodock4) must beat Cluster A (1 engine)
    # under k_max=1 truncation even though Cluster A has primary_rank_order=1! (kills M20)
    res_k1 = cluster_parent_pose_complexes(
        candidates=[
            ClusterCandidatePose(
                pose_id="solo",
                source_engine="gnina",
                primary_rank_order=1,
                pose_complex=_pose_complex("solo"),
                ligand_pdbqt_text=pose_origin,
            ),
            ClusterCandidatePose(
                pose_id="conv-1",
                source_engine="vina",
                primary_rank_order=1,
                pose_complex=_pose_complex("conv-1"),
                ligand_pdbqt_text=pose_far,
            ),
            ClusterCandidatePose(
                pose_id="conv-2",
                source_engine="autodock4",
                primary_rank_order=3,
                pose_complex=_pose_complex("conv-2"),
                ligand_pdbqt_text=pose_far,
            ),
        ],
        reference_conformer_mol=template,
        k_max=1,
    )
    assert len(res_k1.retained_clusters) == 1
    assert len(res_k1.retained_clusters[0].search_engines_present) == 2

    # 6. D4-003: _ordered_autodock_runs orders by (cluster_rank, sub_rank), never GA run index!
    from types import SimpleNamespace

    runs = [
        SimpleNamespace(run=1, cluster_rank=3, sub_rank=1, binding_energy_kcal_mol=-6.2),
        SimpleNamespace(run=2, cluster_rank=1, sub_rank=1, binding_energy_kcal_mol=-9.4),
        SimpleNamespace(run=3, cluster_rank=2, sub_rank=1, binding_energy_kcal_mol=-8.1),
    ]
    ordered = _ordered_autodock_runs(runs)
    assert [r.run for r in ordered] == [2, 3, 1]
