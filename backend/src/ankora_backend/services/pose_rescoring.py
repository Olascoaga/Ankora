"""Fail-closed cross-engine `--score_only` pose rescoring service (M2a / M5).

Evaluates a hash-verified `PoseComplexIdentity` in place across AutoDock Vina
(`vina`, `vinardo`), AutoDock4 (`autodock4 4.2.6 epdb` or `vina --scoring ad4
--maps`), and Linux `GNINA 1.3.3` without re-docking or mutating parent bytes.
Enforces ADR-030 invariant `E4` (`CONSENSUS_SHARED_CONTEXT_MISMATCH`), ADR-032
invariant `E7` (`AUTOGRID_FLEXRES_MAP_MISMATCH`), and Gate 0 Finding `F4`
(`unbound_reference_shifted` provenance on flexible Vina `--score_only`).
"""

from __future__ import annotations

import shutil
import tempfile
import threading
from collections.abc import Mapping
from hashlib import sha256
from pathlib import Path
from typing import Literal

from ankora_backend.adapters.engines.autodock4 import collect_autodock_atom_types
from ankora_backend.adapters.engines.autodock4_job import (
    parse_autodock4_epdb_dlg,
    render_autodock4_epdb_dpf,
)
from ankora_backend.adapters.engines.autodock4_runner import (
    DOCKING_LOG_FILENAME,
    DOCKING_PARAMETER_FILENAME,
    execute_autodock4_cancellable,
    probe_autodock4,
)
from ankora_backend.adapters.engines.gnina import (
    execute_gnina_score_only,
    parse_gnina_score_only_stdout,
    probe_gnina,
)
from ankora_backend.adapters.engines.vina_v02 import (
    VinaScoreOnlyFunction,
    execute_vina_score_only,
    parse_vina_score_only_output,
    probe_vina,
)
from ankora_backend.domain.errors import AnkoraDomainError
from ankora_backend.schemas.receptors import ReceptorFlexMode, flex_residue_locator_key
from ankora_backend.schemas.rescoring import (
    AutoDock4RescoreBackend,
    PoseRescoreContext,
    PoseRescoreFunctionEvidence,
    PoseRescoreRequest,
    PoseRescoreResult,
)
from ankora_backend.schemas.screening_benchmark import ScoreDirection
from ankora_backend.schemas.v02_contracts import (
    ObservationStatus,
    ProtocolSpec,
    ScoreObservation,
    ScoringFamily,
    ScoringFunctionId,
    canonical_contract_sha256,
)

_STAGE = "pose_rescoring"
_STALE_SCORE_REMARKS = frozenset(
    {
        b"VINA",
        b"minimizedAffinity",
        b"minimizedRMSD",
        b"CNNscore",
        b"CNNaffinity",
        b"CNN_VS",
        b"CNNaffinity_variance",
    }
)
_GNINA_FUNCTIONS = frozenset(
    {
        ScoringFunctionId.GNINA_CNN_SCORE,
        ScoringFunctionId.GNINA_CNN_AFFINITY,
        ScoringFunctionId.GNINA_CNN_VS,
        ScoringFunctionId.GNINA_MINIMIZED_AFFINITY,
    }
)
_FAMILY_FOR_FUNCTION: dict[ScoringFunctionId, ScoringFamily] = {
    ScoringFunctionId.VINA: ScoringFamily.VINA_VINARDO,
    ScoringFunctionId.VINARDO: ScoringFamily.VINA_VINARDO,
    ScoringFunctionId.AUTODOCK4: ScoringFamily.AUTODOCK4,
    ScoringFunctionId.GNINA_CNN_SCORE: ScoringFamily.GNINA_NEURAL,
    ScoringFunctionId.GNINA_CNN_AFFINITY: ScoringFamily.GNINA_NEURAL,
    ScoringFunctionId.GNINA_CNN_VS: ScoringFamily.GNINA_NEURAL,
    ScoringFunctionId.GNINA_MINIMIZED_AFFINITY: ScoringFamily.GNINA_NEURAL,
}
_DIRECTION_AND_UNIT: dict[ScoringFunctionId, tuple[ScoreDirection, str]] = {
    ScoringFunctionId.VINA: (ScoreDirection.LOWER_IS_BETTER, "kcal/mol"),
    ScoringFunctionId.VINARDO: (ScoreDirection.LOWER_IS_BETTER, "kcal/mol"),
    ScoringFunctionId.AUTODOCK4: (ScoreDirection.LOWER_IS_BETTER, "kcal/mol"),
    ScoringFunctionId.GNINA_CNN_SCORE: (ScoreDirection.HIGHER_IS_BETTER, "dimensionless"),
    ScoringFunctionId.GNINA_CNN_AFFINITY: (ScoreDirection.HIGHER_IS_BETTER, "pK"),
    ScoringFunctionId.GNINA_CNN_VS: (ScoreDirection.HIGHER_IS_BETTER, "pK"),
    ScoringFunctionId.GNINA_MINIMIZED_AFFINITY: (ScoreDirection.LOWER_IS_BETTER, "kcal/mol"),
}


def _context_mismatch(message: str, **details: object) -> AnkoraDomainError:
    return AnkoraDomainError(
        code="CONSENSUS_SHARED_CONTEXT_MISMATCH",
        stage=_STAGE,
        message=message,
        status_code=422,
        details=details,
    )


def _strip_pose_envelope_for_staging(pose_pdbqt: bytes) -> bytes:
    """Strip MODEL/ENDMDL wrappers and stale score REMARKs on the staging copy only."""
    staged: list[bytes] = []
    for line in pose_pdbqt.splitlines(keepends=True):
        words = line.strip().split(maxsplit=2)
        if words and words[0] in {b"MODEL", b"ENDMDL"}:
            continue
        if len(words) >= 2 and words[0] == b"REMARK" and words[1] in _STALE_SCORE_REMARKS:
            continue
        if not line.strip(b"\x00\r\n"):
            continue
        staged.append(line)
    return b"".join(staged)


def _ligand_center(pdbqt_bytes: bytes) -> tuple[float, float, float]:
    xs: list[float] = []
    ys: list[float] = []
    zs: list[float] = []
    for line in pdbqt_bytes.decode("utf-8", errors="replace").splitlines():
        if not line.startswith(("ATOM  ", "HETATM")):
            continue
        try:
            xs.append(float(line[30:38]))
            ys.append(float(line[38:46]))
            zs.append(float(line[46:54]))
        except ValueError as error:
            raise _context_mismatch(
                "Ligand pose PDBQT contains unreadable atomic coordinates.",
                reason=str(error),
            ) from error
    if not xs:
        raise _context_mismatch("Ligand pose PDBQT contains no ATOM/HETATM coordinate records.")
    n = float(len(xs))
    return (sum(xs) / n, sum(ys) / n, sum(zs) / n)


def _sha256_file(path: Path) -> str | None:
    if not path.is_file():
        return None
    return sha256(path.read_bytes()).hexdigest()


def _default_protocol_spec(
    *,
    scoring_function: ScoringFunctionId,
    context: PoseRescoreContext,
    autodock4_backend: AutoDock4RescoreBackend,
) -> ProtocolSpec:
    engine: Literal["vina", "autodock4", "autodock_gpu", "gnina"]
    if scoring_function in {ScoringFunctionId.VINA, ScoringFunctionId.VINARDO}:
        engine = "vina"
    elif scoring_function is ScoringFunctionId.AUTODOCK4:
        engine = (
            "vina"
            if autodock4_backend is AutoDock4RescoreBackend.VINA_AD4_MAPS
            else "autodock4"
        )
    else:
        engine = "gnina"
    return ProtocolSpec(
        engine=engine,
        scoring_function=scoring_function,
        ligand_flexibility=context.ligand_flexibility,
        receptor_flexibility=context.receptor_flex_spec,
        binding_box_sha256=context.binding_box_sha256,
        autogrid_map_set_sha256=(
            context.autogrid_map_set_sha256
            if scoring_function is ScoringFunctionId.AUTODOCK4
            else None
        ),
    )


def _verify_shared_context(
    *,
    request: PoseRescoreRequest,
    context: PoseRescoreContext,
    receptor_rigid_pdbqt: bytes,
    ligand_pose_pdbqt: bytes,
    pose_flex_sidechains_pdbqt: bytes | None,
    protocol_specs: Mapping[ScoringFunctionId, ProtocolSpec],
) -> None:
    """Enforce ADR-030 E4 and E8 byte-level identity before running any scorer."""
    expected_box_hash = canonical_contract_sha256(context.binding_box)
    if context.binding_box_sha256 != expected_box_hash:
        raise _context_mismatch(
            "The declared binding_box_sha256 does not match the canonical binding box.",
            declared=context.binding_box_sha256,
            computed=expected_box_hash,
        )
    if request.pose_complex.mode != context.receptor_flex_spec.mode:
        raise _context_mismatch(
            "PoseComplex mode does not match receptor flexibility context.",
            pose_mode=request.pose_complex.mode.value,
            receptor_mode=context.receptor_flex_spec.mode.value,
        )
    if (
        request.pose_complex.receptor_rigid_sha256
        != context.receptor_flex_spec.receptor_rigid_sha256
    ):
        raise _context_mismatch(
            "PoseComplex rigid receptor SHA-256 differs from the shared context.",
            pose_receptor_sha256=request.pose_complex.receptor_rigid_sha256,
            context_receptor_sha256=context.receptor_flex_spec.receptor_rigid_sha256,
        )
    actual_rigid = sha256(receptor_rigid_pdbqt).hexdigest()
    if actual_rigid != request.pose_complex.receptor_rigid_sha256:
        raise _context_mismatch(
            "Provided rigid receptor bytes do not match pose_complex.receptor_rigid_sha256.",
            expected=request.pose_complex.receptor_rigid_sha256,
            actual=actual_rigid,
        )
    actual_ligand = sha256(ligand_pose_pdbqt).hexdigest()
    if actual_ligand != request.pose_complex.ligand_pose_sha256:
        raise _context_mismatch(
            "Provided ligand pose bytes do not match pose_complex.ligand_pose_sha256.",
            expected=request.pose_complex.ligand_pose_sha256,
            actual=actual_ligand,
        )
    if request.pose_complex.mode is ReceptorFlexMode.SIDECHAIN_FLEX:
        if pose_flex_sidechains_pdbqt is None:
            raise _context_mismatch(
                "sidechain_flex pose rescoring requires moved pose_flex_sidechains_pdbqt bytes."
            )
        actual_flex = sha256(pose_flex_sidechains_pdbqt).hexdigest()
        if actual_flex != request.pose_complex.pose_flex_sidechains_sha256:
            raise _context_mismatch(
                "Provided flex side-chain bytes do not match pose_flex_sidechains_sha256.",
                expected=request.pose_complex.pose_flex_sidechains_sha256,
                actual=actual_flex,
            )
    elif pose_flex_sidechains_pdbqt is not None:
        raise _context_mismatch(
            "Rigid pose rescoring must not receive pose_flex_sidechains_pdbqt bytes."
        )

    expected_locators = context.receptor_flex_spec.canonical_flex_locators()
    for scoring_function, spec in protocol_specs.items():
        if spec.scoring_function is not scoring_function:
            raise _context_mismatch(
                "ProtocolSpec scoring_function does not match requested scoring function.",
                requested=scoring_function.value,
                protocol=spec.scoring_function.value,
            )
        if spec.binding_box_sha256 != context.binding_box_sha256:
            raise _context_mismatch(
                "ProtocolSpec binding_box_sha256 does not match shared context.",
                scoring_function=scoring_function.value,
            )
        if (
            spec.receptor_flexibility.mode != context.receptor_flex_spec.mode
            or spec.receptor_flexibility.receptor_rigid_sha256
            != context.receptor_flex_spec.receptor_rigid_sha256
            or spec.receptor_flexibility.canonical_flex_locators() != expected_locators
        ):
            raise _context_mismatch(
                "ProtocolSpec receptor flexibility differs from shared context.",
                scoring_function=scoring_function.value,
            )
        if (
            scoring_function is ScoringFunctionId.AUTODOCK4
            and context.autogrid_map_set_sha256 is not None
            and spec.autogrid_map_set_sha256 != context.autogrid_map_set_sha256
        ):
            raise _context_mismatch(
                "ProtocolSpec autogrid_map_set_sha256 differs from shared context.",
                protocol=spec.autogrid_map_set_sha256,
                context=context.autogrid_map_set_sha256,
            )


class PoseRescoringService:
    """In-place multi-engine `--score_only` evaluator emitting canonical `ScoreObservation`s."""

    def rescore_pose(
        self,
        *,
        request: PoseRescoreRequest,
        context: PoseRescoreContext,
        receptor_rigid_pdbqt: bytes,
        ligand_pose_pdbqt: bytes,
        pose_flex_sidechains_pdbqt: bytes | None = None,
        autogrid_maps_dir: Path | None = None,
        protocol_spec_by_function: Mapping[ScoringFunctionId, ProtocolSpec] | None = None,
        cancel_event: threading.Event | None = None,
    ) -> PoseRescoreResult:
        """Score one verified PoseComplex across all requested functions without mutating it."""
        protocol_specs: dict[ScoringFunctionId, ProtocolSpec] = {}
        for fn in request.scoring_functions:
            if protocol_spec_by_function is not None and fn in protocol_spec_by_function:
                protocol_specs[fn] = protocol_spec_by_function[fn]
            else:
                if fn is ScoringFunctionId.AUTODOCK4 and context.autogrid_map_set_sha256 is None:
                    raise _context_mismatch(
                        "AutoDock4 score-only evaluation requires autogrid_map_set_sha256."
                    )
                protocol_specs[fn] = _default_protocol_spec(
                    scoring_function=fn,
                    context=context,
                    autodock4_backend=request.autodock4_backend,
                )

        _verify_shared_context(
            request=request,
            context=context,
            receptor_rigid_pdbqt=receptor_rigid_pdbqt,
            ligand_pose_pdbqt=ligand_pose_pdbqt,
            pose_flex_sidechains_pdbqt=pose_flex_sidechains_pdbqt,
            protocol_specs=protocol_specs,
        )

        # Fail-closed E7 check BEFORE any subprocess when AutoDock4 is requested.
        if ScoringFunctionId.AUTODOCK4 in request.scoring_functions:
            self._verify_autodock4_context(
                context=context,
                protocol_spec=protocol_specs[ScoringFunctionId.AUTODOCK4],
                ligand_pose_pdbqt=ligand_pose_pdbqt,
                pose_flex_sidechains_pdbqt=pose_flex_sidechains_pdbqt,
                autogrid_maps_dir=autogrid_maps_dir,
            )

        event = cancel_event or threading.Event()
        used_flex = request.pose_complex.mode is ReceptorFlexMode.SIDECHAIN_FLEX
        observations_by_fn: dict[ScoringFunctionId, ScoreObservation] = {}
        evidence_list: list[PoseRescoreFunctionEvidence] = []

        staged_ligand_bytes = _strip_pose_envelope_for_staging(ligand_pose_pdbqt)
        staged_flex_bytes = (
            _strip_pose_envelope_for_staging(pose_flex_sidechains_pdbqt)
            if pose_flex_sidechains_pdbqt is not None
            else None
        )

        with tempfile.TemporaryDirectory(prefix="ankora-score-only-") as tmp_dir:
            work = Path(tmp_dir)
            rigid_path = work / "receptor_rigid.pdbqt"
            ligand_path = work / "ligand.pdbqt"
            rigid_path.write_bytes(receptor_rigid_pdbqt)
            ligand_path.write_bytes(staged_ligand_bytes)
            flex_path: Path | None = None
            if staged_flex_bytes is not None:
                flex_path = work / "pose_flex.pdbqt"
                flex_path.write_bytes(staged_flex_bytes)

            # 1. Vina family (`vina`, `vinardo`)
            for fn in (ScoringFunctionId.VINA, ScoringFunctionId.VINARDO):
                if fn not in request.scoring_functions:
                    continue
                obs, ev = self._run_vina_family(
                    scoring="vina" if fn is ScoringFunctionId.VINA else "vinardo",
                    scoring_function=fn,
                    request=request,
                    context=context,
                    protocol_spec=protocol_specs[fn],
                    receptor_path=rigid_path,
                    ligand_path=ligand_path,
                    flex_path=flex_path,
                    working_dir=work,
                    used_flex=used_flex,
                    cancel_event=event,
                )
                observations_by_fn[fn] = obs
                evidence_list.append(ev)

            # 2. AutoDock4 family (`autodock4_epdb` canonical default or `vina_ad4_maps`)
            if ScoringFunctionId.AUTODOCK4 in request.scoring_functions:
                assert autogrid_maps_dir is not None
                assert context.autogrid_map_prefix is not None
                obs, ev = self._run_autodock4_family(
                    request=request,
                    context=context,
                    protocol_spec=protocol_specs[ScoringFunctionId.AUTODOCK4],
                    staged_ligand_bytes=staged_ligand_bytes,
                    ligand_path=ligand_path,
                    flex_path=flex_path,
                    autogrid_maps_dir=autogrid_maps_dir,
                    working_dir=work,
                    used_flex=used_flex,
                    cancel_event=event,
                )
                observations_by_fn[ScoringFunctionId.AUTODOCK4] = obs
                evidence_list.append(ev)

            # 3. Linux GNINA neural family (single invocation for all requested GNINA metrics)
            gnina_fns = tuple(fn for fn in request.scoring_functions if fn in _GNINA_FUNCTIONS)
            if gnina_fns:
                gnina_obs, gnina_ev = self._run_gnina_family(
                    scoring_functions=gnina_fns,
                    request=request,
                    protocol_specs=protocol_specs,
                    receptor_path=rigid_path,
                    ligand_path=ligand_path,
                    flex_path=flex_path,
                    working_dir=work,
                    used_flex=used_flex,
                    cancel_event=event,
                )
                observations_by_fn.update(gnina_obs)
                evidence_list.append(gnina_ev)

        ordered_observations = tuple(observations_by_fn[fn] for fn in request.scoring_functions)
        return PoseRescoreResult(
            pose_complex=request.pose_complex,
            observations=ordered_observations,
            evidence=tuple(evidence_list),
            mutated_original_pose=False,
        )

    def _verify_autodock4_context(
        self,
        *,
        context: PoseRescoreContext,
        protocol_spec: ProtocolSpec,
        ligand_pose_pdbqt: bytes,
        pose_flex_sidechains_pdbqt: bytes | None,
        autogrid_maps_dir: Path | None,
    ) -> None:
        if (
            autogrid_maps_dir is None
            or not autogrid_maps_dir.is_dir()
            or context.autogrid_map_set_sha256 is None
            or context.autogrid_map_prefix is None
            or context.autogrid_map_receptor_sha256 is None
        ):
            raise _context_mismatch(
                "AutoDock4 score-only evaluation requires a verified AutoGrid4 map directory, "
                "prefix, map-set SHA-256, and map receptor SHA-256."
            )
        expected_flex_types = context.expected_flex_atom_types
        if not expected_flex_types and pose_flex_sidechains_pdbqt is not None:
            expected_flex_types = collect_autodock_atom_types(
                [pose_flex_sidechains_pdbqt.decode("utf-8", errors="replace")]
            )
        protocol_spec.verify_autogrid_map_binding(
            map_receptor_sha256=context.autogrid_map_receptor_sha256,
            map_flex_residues=context.autogrid_map_flex_residues,
            expected_flex_atom_types=expected_flex_types,
            map_flex_atom_types=context.autogrid_map_flex_atom_types,
            map_affinity_atom_types=context.autogrid_map_affinity_atom_types,
        )
        # Verify every ligand (and flex) atom type has an existing affinity map file on disk.
        docs = [ligand_pose_pdbqt.decode("utf-8", errors="replace")]
        if pose_flex_sidechains_pdbqt is not None:
            docs.append(pose_flex_sidechains_pdbqt.decode("utf-8", errors="replace"))
        needed_types = collect_autodock_atom_types(docs)
        if context.autogrid_map_affinity_atom_types is not None:
            missing_declared = sorted(
                set(needed_types) - set(context.autogrid_map_affinity_atom_types)
            )
            if missing_declared:
                raise AnkoraDomainError(
                    code="AUTOGRID_FLEXRES_MAP_MISMATCH",
                    stage=_STAGE,
                    status_code=422,
                    message=(
                        "The AutoGrid map set does not cover every atom type in the pose complex."
                    ),
                    details={
                        "missing_atom_types": missing_declared,
                        "required_atom_types": list(needed_types),
                        "map_affinity_atom_types": list(context.autogrid_map_affinity_atom_types),
                        "flex_locators": [
                            flex_residue_locator_key(r)
                            for r in context.receptor_flex_spec.flex_residues
                        ],
                    },
                )
        prefix = context.autogrid_map_prefix
        required_files = [
            f"{prefix}.maps.fld",
            f"{prefix}.e.map",
            f"{prefix}.d.map",
            *(f"{prefix}.{atom_type}.map" for atom_type in needed_types),
        ]
        missing_files = [
            name for name in required_files if not (autogrid_maps_dir / name).is_file()
        ]
        if missing_files:
            raise _context_mismatch(
                "AutoGrid4 map directory is missing required affinity or field map files.",
                missing_files=missing_files,
            )

    def _run_vina_family(
        self,
        *,
        scoring: VinaScoreOnlyFunction,
        scoring_function: ScoringFunctionId,
        request: PoseRescoreRequest,
        context: PoseRescoreContext,
        protocol_spec: ProtocolSpec,
        receptor_path: Path,
        ligand_path: Path,
        flex_path: Path | None,
        working_dir: Path,
        used_flex: bool,
        cancel_event: threading.Event,
    ) -> tuple[ScoreObservation, PoseRescoreFunctionEvidence]:
        installation = probe_vina()
        execution = execute_vina_score_only(
            installation=installation,
            ligand_path=ligand_path,
            working_dir=working_dir,
            scoring=scoring,
            receptor_path=receptor_path,
            box=context.binding_box,
            flex_receptor_path=flex_path,
            cpu_threads=request.cpu_threads,
            timeout_minutes=request.timeout_minutes,
            cancel_event=cancel_event,
        )
        tool_sha = _sha256_file(Path(installation.executable))
        stdout_sha = sha256(execution.stdout.encode("utf-8")).hexdigest()
        stderr_sha = sha256(execution.stderr.encode("utf-8")).hexdigest()
        direction, unit = _DIRECTION_AND_UNIT[scoring_function]

        if execution.timed_out or execution.canceled or execution.exit_code != 0:
            code = "VINA_SCORE_ONLY_TIMEOUT" if execution.timed_out else "VINA_SCORE_ONLY_FAILED"
            return (
                ScoreObservation(
                    protocol_identity_sha256=protocol_spec.protocol_identity_sha256,
                    parent_compound_id=request.parent_compound_id,
                    parent_state_id=request.parent_state_id,
                    pose_complex=request.pose_complex,
                    scoring_family=_FAMILY_FOR_FUNCTION[scoring_function],
                    scoring_function=scoring_function,
                    direction=direction,
                    unit=unit,
                    tool_name="AutoDock Vina",
                    tool_version=installation.version,
                    status=ObservationStatus.FAILED,
                    raw_score=None,
                    failure_code=code,
                ),
                PoseRescoreFunctionEvidence(
                    scoring_functions=(scoring_function,),
                    tool_name="AutoDock Vina",
                    tool_version=installation.version,
                    tool_sha256=tool_sha,
                    command=tuple(execution.command),
                    exit_code=execution.exit_code,
                    stdout_sha256=stdout_sha,
                    stderr_sha256=stderr_sha,
                    used_flex=used_flex,
                    unbound_reference_shifted=used_flex,
                ),
            )

        parsed = parse_vina_score_only_output(
            stdout=execution.stdout,
            scoring=scoring,
            used_flex=used_flex,
        )
        return (
            ScoreObservation(
                protocol_identity_sha256=protocol_spec.protocol_identity_sha256,
                parent_compound_id=request.parent_compound_id,
                parent_state_id=request.parent_state_id,
                pose_complex=request.pose_complex,
                scoring_family=_FAMILY_FOR_FUNCTION[scoring_function],
                scoring_function=scoring_function,
                direction=direction,
                unit=unit,
                tool_name="AutoDock Vina",
                tool_version=installation.version,
                status=ObservationStatus.SCORED,
                raw_score=parsed.energy.estimated_free_energy_kcal_mol,
                failure_code=None,
            ),
            PoseRescoreFunctionEvidence(
                scoring_functions=(scoring_function,),
                tool_name="AutoDock Vina",
                tool_version=installation.version,
                tool_sha256=tool_sha,
                command=tuple(execution.command),
                exit_code=execution.exit_code,
                stdout_sha256=stdout_sha,
                stderr_sha256=stderr_sha,
                used_flex=used_flex,
                unbound_reference_shifted=parsed.unbound_reference_shifted,
                intermolecular_kcal_mol=parsed.energy.intermolecular_kcal_mol,
                total_internal_kcal_mol=parsed.energy.total_internal_kcal_mol,
                torsional_free_energy_kcal_mol=parsed.energy.torsional_free_energy_kcal_mol,
                unbound_system_energy_kcal_mol=parsed.energy.unbound_system_energy_kcal_mol,
            ),
        )

    def _run_autodock4_family(
        self,
        *,
        request: PoseRescoreRequest,
        context: PoseRescoreContext,
        protocol_spec: ProtocolSpec,
        staged_ligand_bytes: bytes,
        ligand_path: Path,
        flex_path: Path | None,
        autogrid_maps_dir: Path,
        working_dir: Path,
        used_flex: bool,
        cancel_event: threading.Event,
    ) -> tuple[ScoreObservation, PoseRescoreFunctionEvidence]:
        assert context.autogrid_map_prefix is not None
        prefix = context.autogrid_map_prefix
        direction, unit = _DIRECTION_AND_UNIT[ScoringFunctionId.AUTODOCK4]

        if request.autodock4_backend is AutoDock4RescoreBackend.VINA_AD4_MAPS:
            installation = probe_vina()
            execution = execute_vina_score_only(
                installation=installation,
                ligand_path=ligand_path,
                working_dir=working_dir,
                scoring="ad4",
                maps_prefix=autogrid_maps_dir / prefix,
                flex_receptor_path=flex_path,
                cpu_threads=request.cpu_threads,
                timeout_minutes=request.timeout_minutes,
                cancel_event=cancel_event,
            )
            tool_sha = _sha256_file(Path(installation.executable))
            stdout_sha = sha256(execution.stdout.encode("utf-8")).hexdigest()
            stderr_sha = sha256(execution.stderr.encode("utf-8")).hexdigest()
            if execution.timed_out or execution.canceled or execution.exit_code != 0:
                return (
                    ScoreObservation(
                        protocol_identity_sha256=protocol_spec.protocol_identity_sha256,
                        parent_compound_id=request.parent_compound_id,
                        parent_state_id=request.parent_state_id,
                        pose_complex=request.pose_complex,
                        scoring_family=ScoringFamily.AUTODOCK4,
                        scoring_function=ScoringFunctionId.AUTODOCK4,
                        direction=direction,
                        unit=unit,
                        tool_name="AutoDock Vina (ad4 maps)",
                        tool_version=installation.version,
                        status=ObservationStatus.FAILED,
                        raw_score=None,
                        failure_code="VINA_AD4_SCORE_ONLY_FAILED",
                    ),
                    PoseRescoreFunctionEvidence(
                        scoring_functions=(ScoringFunctionId.AUTODOCK4,),
                        tool_name="AutoDock Vina (ad4 maps)",
                        tool_version=installation.version,
                        tool_sha256=tool_sha,
                        command=tuple(execution.command),
                        exit_code=execution.exit_code,
                        stdout_sha256=stdout_sha,
                        stderr_sha256=stderr_sha,
                        used_flex=used_flex,
                        unbound_reference_shifted=used_flex,
                    ),
                )
            parsed = parse_vina_score_only_output(
                stdout=execution.stdout,
                scoring="ad4",
                used_flex=used_flex,
            )
            return (
                ScoreObservation(
                    protocol_identity_sha256=protocol_spec.protocol_identity_sha256,
                    parent_compound_id=request.parent_compound_id,
                    parent_state_id=request.parent_state_id,
                    pose_complex=request.pose_complex,
                    scoring_family=ScoringFamily.AUTODOCK4,
                    scoring_function=ScoringFunctionId.AUTODOCK4,
                    direction=direction,
                    unit=unit,
                    tool_name="AutoDock Vina (ad4 maps)",
                    tool_version=installation.version,
                    status=ObservationStatus.SCORED,
                    raw_score=parsed.energy.estimated_free_energy_kcal_mol,
                    failure_code=None,
                ),
                PoseRescoreFunctionEvidence(
                    scoring_functions=(ScoringFunctionId.AUTODOCK4,),
                    tool_name="AutoDock Vina (ad4 maps)",
                    tool_version=installation.version,
                    tool_sha256=tool_sha,
                    command=tuple(execution.command),
                    exit_code=execution.exit_code,
                    stdout_sha256=stdout_sha,
                    stderr_sha256=stderr_sha,
                    used_flex=used_flex,
                    unbound_reference_shifted=parsed.unbound_reference_shifted,
                    intermolecular_kcal_mol=parsed.energy.intermolecular_kcal_mol,
                    total_internal_kcal_mol=parsed.energy.total_internal_kcal_mol,
                    torsional_free_energy_kcal_mol=parsed.energy.torsional_free_energy_kcal_mol,
                    unbound_system_energy_kcal_mol=parsed.energy.unbound_system_energy_kcal_mol,
                ),
            )

        # Canonical AutoDock4 4.2.6 `epdb` evaluation inside an isolated directory.
        ad4_install = probe_autodock4()
        epdb_dir = working_dir / "ad4_epdb"
        epdb_dir.mkdir(parents=True, exist_ok=True)
        for src in autogrid_maps_dir.iterdir():
            if src.is_file() and src.name.startswith(f"{prefix}."):
                shutil.copy2(src, epdb_dir / src.name)
        staged_lig_name = "ligand.pdbqt"
        (epdb_dir / staged_lig_name).write_bytes(staged_ligand_bytes)
        staged_flex_name: str | None = None
        docs = [staged_ligand_bytes.decode("utf-8", errors="replace")]
        if flex_path is not None:
            staged_flex_name = "pose_flex.pdbqt"
            flex_bytes = flex_path.read_bytes()
            (epdb_dir / staged_flex_name).write_bytes(flex_bytes)
            docs.append(flex_bytes.decode("utf-8", errors="replace"))
        atom_types = (
            context.autogrid_map_affinity_atom_types
            if context.autogrid_map_affinity_atom_types is not None
            else collect_autodock_atom_types(docs)
        )
        dpf_text = render_autodock4_epdb_dpf(
            ligand_filename=staged_lig_name,
            map_prefix=prefix,
            ligand_atom_types=atom_types,
            about=_ligand_center(staged_ligand_bytes),
            flexres_filename=staged_flex_name,
        )
        dpf_path = epdb_dir / DOCKING_PARAMETER_FILENAME
        dlg_path = epdb_dir / DOCKING_LOG_FILENAME
        dpf_path.write_text(dpf_text, encoding="utf-8")
        execution = execute_autodock4_cancellable(
            installation=ad4_install,
            job_directory=epdb_dir,
            timeout_seconds=request.timeout_minutes * 60,
            cancel_event=cancel_event,
        )
        stdout_sha = sha256(execution.stdout.encode("utf-8")).hexdigest()
        stderr_sha = sha256(execution.stderr.encode("utf-8")).hexdigest()
        if (
            execution.timed_out
            or execution.canceled
            or execution.exit_code != 0
            or not dlg_path.is_file()
        ):
            return (
                ScoreObservation(
                    protocol_identity_sha256=protocol_spec.protocol_identity_sha256,
                    parent_compound_id=request.parent_compound_id,
                    parent_state_id=request.parent_state_id,
                    pose_complex=request.pose_complex,
                    scoring_family=ScoringFamily.AUTODOCK4,
                    scoring_function=ScoringFunctionId.AUTODOCK4,
                    direction=direction,
                    unit=unit,
                    tool_name="AutoDock",
                    tool_version=ad4_install.version,
                    status=ObservationStatus.FAILED,
                    raw_score=None,
                    failure_code="AUTODOCK4_EPDB_FAILED",
                ),
                PoseRescoreFunctionEvidence(
                    scoring_functions=(ScoringFunctionId.AUTODOCK4,),
                    tool_name="AutoDock",
                    tool_version=ad4_install.version,
                    tool_sha256=ad4_install.sha256,
                    command=tuple(execution.command),
                    exit_code=execution.exit_code,
                    stdout_sha256=stdout_sha,
                    stderr_sha256=stderr_sha,
                    used_flex=used_flex,
                    unbound_reference_shifted=False,
                ),
            )
        parsed_epdb = parse_autodock4_epdb_dlg(dlg_path.read_bytes(), expect_flex=used_flex)
        return (
            ScoreObservation(
                protocol_identity_sha256=protocol_spec.protocol_identity_sha256,
                parent_compound_id=request.parent_compound_id,
                parent_state_id=request.parent_state_id,
                pose_complex=request.pose_complex,
                scoring_family=ScoringFamily.AUTODOCK4,
                scoring_function=ScoringFunctionId.AUTODOCK4,
                direction=direction,
                unit=unit,
                tool_name="AutoDock",
                tool_version=ad4_install.version,
                status=ObservationStatus.SCORED,
                raw_score=parsed_epdb.estimated_free_energy_kcal_mol,
                failure_code=None,
            ),
            PoseRescoreFunctionEvidence(
                scoring_functions=(ScoringFunctionId.AUTODOCK4,),
                tool_name="AutoDock",
                tool_version=ad4_install.version,
                tool_sha256=ad4_install.sha256,
                command=tuple(execution.command),
                exit_code=execution.exit_code,
                stdout_sha256=stdout_sha,
                stderr_sha256=stderr_sha,
                used_flex=used_flex,
                unbound_reference_shifted=False,
                intermolecular_kcal_mol=parsed_epdb.intermolecular_kcal_mol,
                total_internal_kcal_mol=parsed_epdb.total_internal_kcal_mol,
                torsional_free_energy_kcal_mol=parsed_epdb.torsional_free_energy_kcal_mol,
                unbound_system_energy_kcal_mol=parsed_epdb.unbound_system_energy_kcal_mol,
            ),
        )

    def _run_gnina_family(
        self,
        *,
        scoring_functions: tuple[ScoringFunctionId, ...],
        request: PoseRescoreRequest,
        protocol_specs: Mapping[ScoringFunctionId, ProtocolSpec],
        receptor_path: Path,
        ligand_path: Path,
        flex_path: Path | None,
        working_dir: Path,
        used_flex: bool,
        cancel_event: threading.Event,
    ) -> tuple[dict[ScoringFunctionId, ScoreObservation], PoseRescoreFunctionEvidence]:
        installation = probe_gnina()
        need_cnn = any(
            fn
            in {
                ScoringFunctionId.GNINA_CNN_SCORE,
                ScoringFunctionId.GNINA_CNN_AFFINITY,
                ScoringFunctionId.GNINA_CNN_VS,
            }
            for fn in scoring_functions
        )
        execution = execute_gnina_score_only(
            installation=installation,
            receptor_path=receptor_path,
            ligand_path=ligand_path,
            working_dir=working_dir,
            compute=request.gnina_compute,
            device_index=request.gnina_device_index,
            cpu_threads=request.cpu_threads,
            cnn_scoring="rescore" if need_cnn else "none",
            cnn_model=request.gnina_cnn_model,
            flex_receptor_path=flex_path,
            timeout_minutes=request.timeout_minutes,
            cancel_event=cancel_event,
        )
        stdout_sha = sha256(execution.stdout.encode("utf-8")).hexdigest()
        stderr_sha = sha256(execution.stderr.encode("utf-8")).hexdigest()

        if execution.timed_out or execution.canceled or execution.exit_code != 0:
            code = "GNINA_SCORE_ONLY_TIMEOUT" if execution.timed_out else "GNINA_SCORE_ONLY_FAILED"
            failed_obs: dict[ScoringFunctionId, ScoreObservation] = {}
            for fn in scoring_functions:
                direction, unit = _DIRECTION_AND_UNIT[fn]
                failed_obs[fn] = ScoreObservation(
                    protocol_identity_sha256=protocol_specs[fn].protocol_identity_sha256,
                    parent_compound_id=request.parent_compound_id,
                    parent_state_id=request.parent_state_id,
                    pose_complex=request.pose_complex,
                    scoring_family=ScoringFamily.GNINA_NEURAL,
                    scoring_function=fn,
                    direction=direction,
                    unit=unit,
                    tool_name="GNINA",
                    tool_version=installation.version,
                    status=ObservationStatus.FAILED,
                    raw_score=None,
                    failure_code=code,
                )
            return (
                failed_obs,
                PoseRescoreFunctionEvidence(
                    scoring_functions=scoring_functions,
                    tool_name="GNINA",
                    tool_version=installation.version,
                    tool_sha256=installation.sha256,
                    command=tuple(execution.command),
                    exit_code=execution.exit_code,
                    stdout_sha256=stdout_sha,
                    stderr_sha256=stderr_sha,
                    used_flex=used_flex,
                    unbound_reference_shifted=False,
                ),
            )

        parsed = parse_gnina_score_only_stdout(
            execution.stdout,
            used_flex=used_flex,
            require_cnn=need_cnn,
        )
        value_map: dict[ScoringFunctionId, float | None] = {
            ScoringFunctionId.GNINA_CNN_SCORE: parsed.cnn_score,
            ScoringFunctionId.GNINA_CNN_AFFINITY: parsed.cnn_affinity,
            ScoringFunctionId.GNINA_CNN_VS: parsed.cnn_vs,
            ScoringFunctionId.GNINA_MINIMIZED_AFFINITY: parsed.minimized_affinity_kcal_mol,
        }
        scored_obs: dict[ScoringFunctionId, ScoreObservation] = {}
        for fn in scoring_functions:
            direction, unit = _DIRECTION_AND_UNIT[fn]
            value = value_map[fn]
            scored_obs[fn] = ScoreObservation(
                protocol_identity_sha256=protocol_specs[fn].protocol_identity_sha256,
                parent_compound_id=request.parent_compound_id,
                parent_state_id=request.parent_state_id,
                pose_complex=request.pose_complex,
                scoring_family=ScoringFamily.GNINA_NEURAL,
                scoring_function=fn,
                direction=direction,
                unit=unit,
                tool_name="GNINA",
                tool_version=installation.version,
                status=ObservationStatus.SCORED if value is not None else ObservationStatus.FAILED,
                raw_score=value,
                failure_code=None if value is not None else "GNINA_SCORE_MISSING",
            )
        return (
            scored_obs,
            PoseRescoreFunctionEvidence(
                scoring_functions=scoring_functions,
                tool_name="GNINA",
                tool_version=installation.version,
                tool_sha256=installation.sha256,
                command=tuple(execution.command),
                exit_code=execution.exit_code,
                stdout_sha256=stdout_sha,
                stderr_sha256=stderr_sha,
                used_flex=used_flex,
                unbound_reference_shifted=False,
                intramolecular_energy_kcal_mol=parsed.intramolecular_energy_kcal_mol,
                cnn_affinity_variance=parsed.cnn_affinity_variance,
            ),
        )
