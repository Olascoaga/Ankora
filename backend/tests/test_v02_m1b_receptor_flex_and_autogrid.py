"""M1b regression coverage using labelled synthetic inputs.

Live Meeko expectations come from the recorded SYNTHETIC_GATE0_GARYMP split
in docs/validation/V02_M1_FLEXIBILITY_GATE0_PROBE.md, sections 1.1 and 3.2.
The other PQR, PDBQT, and map documents exercise contracts and do not represent
scientific results.
"""

import json
import os
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path

import pytest
from pydantic import ValidationError
from test_autogrid_maps import _install_synthetic_autogrid, _installation
from test_m1_gate0_probe import probe

from ankora_backend.adapters.engines.autogrid import GRID_PARAMETER_FILENAME
from ankora_backend.adapters.tools import receptor_preparation as receptor_tools
from ankora_backend.adapters.tools.discovery import DiscoveredTool, discover_tool
from ankora_backend.adapters.tools.receptor_preparation import (
    format_meeko_flex_residue_spec,
    inspect_receptor_flex_pdbqt,
    package_version,
    run_meeko_receptor_flex,
    validate_flex_residues_against_pqr,
)
from ankora_backend.domain.errors import AnkoraDomainError
from ankora_backend.execution.subprocess_runner import ToolExecution
from ankora_backend.persistence.artifact_store import StructureArtifactStore
from ankora_backend.persistence.autogrid_store import AutoGridMapStore
from ankora_backend.persistence.binding_site_store import BindingSiteArtifactStore
from ankora_backend.persistence.ligand_store import LigandArtifactStore
from ankora_backend.persistence.receptor_store import ReceptorArtifactStore
from ankora_backend.schemas import v02_contracts
from ankora_backend.schemas.autogrid import (
    AutoGridLigandSource,
    AutoGridMapKind,
    AutoGridMapSetRecord,
    AutoGridMapSetRequest,
)
from ankora_backend.schemas.binding_sites import (
    BindingBox,
    BindingSiteRecord,
    BindingSiteRequest,
    BindingSiteSource,
)
from ankora_backend.schemas.provenance import ProvenanceEvent, ToolIdentity
from ankora_backend.schemas.receptors import (
    ComponentAction,
    ProtonationSettings,
    ReceptorFlexMode,
    ReceptorFlexRequest,
    ReceptorFlexSpec,
    ReceptorOutputArtifact,
    ReceptorOutputStage,
    ReceptorPreparationRecord,
    ReceptorPreparationRequest,
    ReceptorPreparationStatus,
    ResidueLocator,
)
from ankora_backend.schemas.structures import StructureSource
from ankora_backend.schemas.v02_contracts import ProtocolSpec, ScoringFunctionId
from ankora_backend.schemas.warnings import WarningCode
from ankora_backend.services import autogrid_maps, receptor_preparation
from ankora_backend.services.autogrid_maps import (
    AutoGridMapService,
    verify_autogrid_map_set_for_receptor,
)
from ankora_backend.services.structure_inspection import import_structure_bytes

FLEX_TYPES = ("A", "C", "HD", "OA", "SA")
LIGAND_TYPES = ("A", "C", "HD", "N", "OA")
AFFINITY_TYPES = ("A", "C", "HD", "N", "OA", "SA")


def _residue(name, number, *, chain="A", insertion="") -> ResidueLocator:
    return ResidueLocator(
        chain_id=chain, residue_name=name, sequence_number=number, insertion_code=insertion
    )


def _garymp_flex_residues() -> list[ResidueLocator]:
    return [_residue("TYR", 4), _residue("MET", 5)]


def _prep_request(*, residues=None, protonate=True, pdbqt=True) -> ReceptorPreparationRequest:
    return ReceptorPreparationRequest(
        selected_chains=["A"],
        water_action=ComponentAction.REMOVE,
        component_decisions=[],
        issue_decisions=[],
        protonation=ProtonationSettings(enabled=protonate, force_field="PARSE"),
        generate_pdbqt=pdbqt,
        flexibility=(
            ReceptorFlexRequest(mode=ReceptorFlexMode.SIDECHAIN_FLEX, flex_residues=residues)
            if residues is not None
            else None
        ),
    )


@pytest.mark.parametrize(
    ("mode", "residues", "message"),
    [
        (ReceptorFlexMode.RIGID, [_residue("TYR", 4)], "Rigid receptors"),
        (ReceptorFlexMode.SIDECHAIN_FLEX, [], "at least one"),
        (
            ReceptorFlexMode.SIDECHAIN_FLEX,
            [_residue("TYR", 4), _residue("MET", 4)],
            "unique positions",
        ),
        *[
            (ReceptorFlexMode.SIDECHAIN_FLEX, [_residue(name, 4)], "disallowed")
            for name in ("gly", "ALA", "PRO", "CYX")
        ],
    ],
)
def test_flex_request_rejects_invalid_selections(mode, residues, message):
    with pytest.raises(ValidationError, match=message):
        ReceptorFlexRequest(mode=mode, flex_residues=residues)


def test_receptor_flex_schema_preserves_m0_imports_and_legacy_request():
    assert ReceptorFlexSpec is v02_contracts.ReceptorFlexSpec
    assert ReceptorFlexMode is v02_contracts.ReceptorFlexMode
    assert ReceptorFlexRequest().mode is ReceptorFlexMode.RIGID
    with pytest.raises(ValidationError, match="Extra inputs"):
        ReceptorFlexRequest.model_validate({"unexpected": True})
    legacy = (
        '{"selected_chains":["A"],"water_action":"remove","component_decisions":[],'
        '"issue_decisions":[],"reference_component_id":null,'
        '"relaxation":{"enabled":false,"restraint_force_constant_kcal_mol_a2":50.0,'
        '"max_iterations":200},"protonation":{"enabled":true,"ph":7.4,"force_field":"PARSE",'
        '"authorized_terminal_heavy_atom_additions":[],"overrides":[]},"generate_pdbqt":true}'
    )
    assert _prep_request().model_dump_json() == legacy
    assert ReceptorPreparationRequest.model_validate_json(legacy).flexibility is None


@pytest.mark.parametrize(
    ("residues", "protonate", "pdbqt", "message"),
    [
        (_garymp_flex_residues(), True, False, "requires protonation and PDBQT"),
        (_garymp_flex_residues(), False, True, "explicit protonation stage"),
        ([_residue("TYR", 4, chain="B")], True, True, "selected chains"),
    ],
)
def test_flex_requires_a_protonated_pdbqt_in_selected_chains(residues, protonate, pdbqt, message):
    with pytest.raises(ValidationError, match=message):
        _prep_request(residues=residues, protonate=protonate, pdbqt=pdbqt)


def _pqr_atom(residue, *, atom_name="CA", x=0.0) -> str:
    return (
        f"ATOM      1 {atom_name:>4} {residue.residue_name} "
        f"{residue.chain_id}{residue.sequence_number:4d}{residue.insertion_code or ' '}   "
        f"{x:8.3f}{0:8.3f}{0:8.3f}  0.0000 1.5000\n"
    )


def _write_pqr(tmp_path, *lines) -> Path:
    path = tmp_path / "synthetic_receptor.pqr"
    path.write_text("REMARK SYNTHETIC_FLEX_PQR\n" + "".join(lines), encoding="ascii")
    return path


def test_pqr_guard_preserves_chain_order_number_and_insertion(tmp_path):
    tyr = _residue("TYR", 4, insertion="B")
    met = _residue("MET", 1000, chain="C", insertion="D")
    pqr = _write_pqr(tmp_path, _pqr_atom(tyr), _pqr_atom(met))
    requested = [met, tyr]
    assert validate_flex_residues_against_pqr(pqr, requested) == requested
    assert format_meeko_flex_residue_spec(requested) == "C:1000D,A:4B"
    normalized, count = receptor_preparation._normalize_pqr_for_meeko(
        pqr.read_bytes(), separate_insertion_codes=True
    )
    assert count == 1
    assert b"4 B " in normalized and b"C 1000 D " in normalized
    normalized_pqr = tmp_path / "synthetic_meeko_input.pqr"
    normalized_pqr.write_bytes(normalized)
    assert validate_flex_residues_against_pqr(normalized_pqr, requested) == requested


@pytest.mark.parametrize(
    ("requested", "prepared"),
    [
        ("HIS", "HIE"),
        ("HIS", "HID"),
        ("HIS", "HIP"),
        ("ASP", "ASH"),
        ("GLU", "GLH"),
        ("LYS", "LYN"),
        ("CYS", "CYM"),
    ],
)
def test_pqr_guard_resolves_protonation_aliases(tmp_path, requested, prepared):
    prepared_residue = _residue(prepared, 4)
    pqr = _write_pqr(
        tmp_path, _pqr_atom(prepared_residue, atom_name="SG" if prepared == "CYM" else "CA")
    )
    assert validate_flex_residues_against_pqr(pqr, [_residue(requested, 4)]) == [prepared_residue]


@pytest.mark.parametrize("name", ["GLY", "ALA", "PRO", "CYX"])
def test_pqr_guard_rejects_disallowed_residues(tmp_path, name):
    residue = _residue(name, 4)
    pqr = _write_pqr(tmp_path, _pqr_atom(residue))
    with pytest.raises(AnkoraDomainError) as caught:
        validate_flex_residues_against_pqr(pqr, [residue])
    assert (caught.value.code, caught.value.status_code) == (
        "RECEPTOR_FLEXRES_DISALLOWED_RESIDUE",
        422,
    )


def test_pqr_guard_never_accepts_cyx_as_a_cys_alias(tmp_path):
    pqr = _write_pqr(tmp_path, _pqr_atom(_residue("CYX", 4), atom_name="SG"))
    with pytest.raises(AnkoraDomainError) as caught:
        validate_flex_residues_against_pqr(pqr, [_residue("CYS", 4)])
    assert (caught.value.code, caught.value.status_code) == (
        "RECEPTOR_FLEXRES_DISALLOWED_RESIDUE",
        422,
    )


@pytest.mark.parametrize(
    ("residues", "code"),
    [
        ([], "RECEPTOR_FLEXRES_EMPTY"),
        ([_residue("TYR", 4), _residue("MET", 4)], "RECEPTOR_FLEXRES_DUPLICATE"),
        ([_residue("TYR", 999)], "RECEPTOR_FLEXRES_UNRESOLVED"),
        ([_residue("MET", 4)], "RECEPTOR_FLEXRES_UNRESOLVED"),
        ([_residue("TYR", 5)], "RECEPTOR_FLEXRES_UNRESOLVED"),
        ([_residue("TYR", 6)], "RECEPTOR_FLEXRES_UNRESOLVED"),
    ],
)
def test_pqr_guard_rejects_missing_mismatched_or_ambiguous_positions(tmp_path, residues, code):
    pqr = _write_pqr(
        tmp_path,
        _pqr_atom(_residue("TYR", 4)),
        _pqr_atom(_residue("TYR", 5)),
        _pqr_atom(_residue("MET", 5), atom_name="CB"),
        _pqr_atom(_residue("TYR", 6)),
        "TER\n",
        _pqr_atom(_residue("TYR", 6)),
    )
    with pytest.raises(AnkoraDomainError) as caught:
        validate_flex_residues_against_pqr(pqr, residues)
    assert (caught.value.code, caught.value.status_code) == (code, 422)


@pytest.mark.parametrize("partner_name", ["CYS", "CYX"])
@pytest.mark.parametrize("distance", [2.0, 2.2, 2.201])
def test_pqr_guard_checks_sulfur_distance_across_chains(tmp_path, partner_name, distance):
    selected = _residue("CYS", 4)
    partner = _residue(partner_name, 5, chain="B")
    pqr = _write_pqr(
        tmp_path,
        _pqr_atom(selected, atom_name="SG"),
        _pqr_atom(partner, atom_name="SG", x=distance),
    )
    if distance > 2.2:
        assert validate_flex_residues_against_pqr(pqr, [selected]) == [selected]
    else:
        with pytest.raises(AnkoraDomainError) as caught:
            validate_flex_residues_against_pqr(pqr, [selected])
        assert (caught.value.code, caught.value.status_code) == (
            "RECEPTOR_FLEXRES_DISULFIDE_CYS",
            422,
        )
        assert caught.value.details["partner"] == partner.model_dump()


def _pdbqt_atoms(types) -> str:
    return "".join(
        f"ATOM  {serial:5d}  C   UNL A   1       0.000   0.000   0.000"
        f"  1.00  0.00     0.000 {atom_type}\n"
        for serial, atom_type in enumerate(types, start=1)
    )


def _flex_pdbqt(residues, types, *, branches=1) -> str:
    torsions = "".join(f"BRANCH 1 {i + 2}\nENDBRANCH 1 {i + 2}\n" for i in range(branches))
    return "REMARK SYNTHETIC_FLEX_PDBQT\n" + "".join(
        f"BEGIN_RES {r.residue_name} {r.chain_id} {r.sequence_number}\n"
        f"{_pdbqt_atoms(types)}{torsions}"
        f"END_RES {r.residue_name} {r.chain_id} {r.sequence_number}\n"
        for r in residues
    )


def test_inspect_flex_pdbqt_counts_branches_and_deduplicates_atom_types():
    text = _flex_pdbqt(_garymp_flex_residues(), ("SA", "C", "A", "C"), branches=3)
    assert inspect_receptor_flex_pdbqt(text) == (6, ("A", "C", "SA"))


@pytest.mark.parametrize(
    "change",
    [
        lambda text: "",
        lambda text: text.replace("END_RES TYR A 4\n", ""),
        lambda text: "END_RES TYR A 4\n" + text,
        lambda text: text.replace("END_RES TYR A 4", "END_RES MET A 4"),
        lambda text: text.replace("\nBRANCH 1 2\nENDBRANCH 1 2\n", "\n"),
        lambda text: text.replace("0.000 C\n", "0.000 !\n"),
    ],
)
def test_inspect_flex_pdbqt_rejects_invalid_output(change):
    text = _flex_pdbqt([_residue("TYR", 4)], ("C",))
    with pytest.raises(AnkoraDomainError) as caught:
        inspect_receptor_flex_pdbqt(change(text))
    assert (caught.value.code, caught.value.status_code) == ("MEEKO_FLEXRES_OUTPUT_INVALID", 422)


@pytest.mark.parametrize("missing_or_empty", ["rigid", "flex"])
def test_meeko_split_rejects_incomplete_outputs(tmp_path, monkeypatch, missing_or_empty):
    stem = tmp_path / "synthetic_receptor"
    input_path = _write_pqr(tmp_path, _pqr_atom(_residue("TYR", 4)))
    monkeypatch.setattr(
        receptor_tools,
        "discover_tool",
        lambda *args: DiscoveredTool(available=True, path="synthetic-meeko"),
    )

    def synthetic_meeko(*, executable, arguments, cwd, stage):
        assert arguments == [
            "--read_pqr",
            str(input_path),
            "--charge_model",
            "read",
            "-o",
            str(stem),
            "-p",
            f"{stem}.pdbqt",
            "-f",
            "A:4",
        ]
        assert cwd == tmp_path
        if missing_or_empty == "rigid":
            stem.with_name(stem.name + "_flex.pdbqt").write_text("REMARK SYNTHETIC")
        else:
            stem.with_name(stem.name + "_rigid.pdbqt").write_text("REMARK SYNTHETIC")
            stem.with_name(stem.name + "_flex.pdbqt").touch()
        return ToolExecution([executable, *arguments], 0, "synthetic stdout", "synthetic stderr")

    monkeypatch.setattr(receptor_tools, "run_tool", synthetic_meeko)
    with pytest.raises(AnkoraDomainError) as caught:
        run_meeko_receptor_flex(
            input_pqr_path=input_path,
            output_stem_path=stem,
            flex_residues=[_residue("TYR", 4)],
        )
    assert (caught.value.code, caught.value.status_code) == ("MEEKO_FLEXRES_SPLIT_INCOMPLETE", 422)
    assert caught.value.details["incomplete_outputs"] == [f"{stem.name}_{missing_or_empty}.pdbqt"]
    assert caught.value.details["stdout"] == "synthetic stdout"
    assert caught.value.details["stderr"] == "synthetic stderr"


def test_preparation_checks_pqr_before_meeko(tmp_path, monkeypatch):
    def unexpected_meeko(**kwargs):
        pytest.fail("Meeko was invoked for a rejected flexible residue")

    monkeypatch.setattr(receptor_preparation, "run_meeko_receptor_flex", unexpected_meeko)
    store = ReceptorArtifactStore(tmp_path)
    receptor_id = store.new_receptor_id()
    store.create_receptor(receptor_id)
    pqr = _write_pqr(tmp_path, _pqr_atom(_residue("TYR", 4)))
    with pytest.raises(AnkoraDomainError) as caught:
        receptor_preparation._prepare_flexible_pdbqt(
            receptor_store=store,
            receptor_id=receptor_id,
            meeko_input_path=pqr,
            input_artifact="synthetic-pqr",
            requested_residues=[_residue("TYR", 999)],
        )
    assert (caught.value.code, caught.value.status_code) == ("RECEPTOR_FLEXRES_UNRESOLVED", 422)


@pytest.mark.parametrize(("residue_count", "branches_per_residue"), [(5, 1), (1, 13), (4, 3)])
def test_preparation_warns_at_either_budget_without_truncation(
    tmp_path,
    monkeypatch,
    residue_count,
    branches_per_residue,
):
    residues = [_residue("TYR", i) for i in range(1, residue_count + 1)]
    pqr = _write_pqr(tmp_path, *map(_pqr_atom, residues))
    store = ReceptorArtifactStore(tmp_path)
    receptor_id = store.new_receptor_id()
    store.create_receptor(receptor_id)

    def synthetic_meeko(*, input_pqr_path, output_stem_path, flex_residues):
        assert input_pqr_path == pqr
        assert flex_residues == residues
        rigid = output_stem_path.with_name("receptor_rigid.pdbqt")
        flex = output_stem_path.with_name("receptor_flex.pdbqt")
        rigid.write_text("REMARK SYNTHETIC_RIGID\n" + _pdbqt_atoms(("C",)), encoding="ascii")
        flex.write_text(_flex_pdbqt(residues, FLEX_TYPES, branches=branches_per_residue))
        return ToolExecution(["synthetic-meeko"], 0, "stdout", "stderr"), "synthetic", rigid, flex

    monkeypatch.setattr(receptor_preparation, "run_meeko_receptor_flex", synthetic_meeko)
    outputs, event, spec, types = receptor_preparation._prepare_flexible_pdbqt(
        receptor_store=store,
        receptor_id=receptor_id,
        meeko_input_path=pqr,
        input_artifact="synthetic-pqr",
        requested_residues=residues,
    )
    assert [r.model_dump() for r in spec.flex_residues] == [r.model_dump() for r in residues]
    assert types == FLEX_TYPES
    assert [item.stage for item in outputs] == [
        ReceptorOutputStage.PDBQT_RIGID,
        ReceptorOutputStage.PDBQT_FLEX,
    ]
    count = residue_count * branches_per_residue
    assert spec.added_chi_torsion_count == count
    if residue_count > 4 or count > 12:
        (warning,) = event.warnings
        assert warning.code is WarningCode.DOCKING_FLEXRES_DOF_HIGH
        assert warning.stage == "receptor_pdbqt"
        assert warning.details == {
            "flex_residue_count": residue_count,
            "added_chi_torsion_count": count,
            "recommended_max_residues": 4,
            "recommended_max_chi_torsions": 12,
        }
    else:
        assert event.warnings == []


def test_real_meeko_preserves_gate0_garymp_split(tmp_path):
    for distribution, expected in (
        ("rdkit", "2025.9.6"),
        ("pdb2pqr", "3.7.1"),
        ("propka", "3.5.1"),
        ("meeko", "0.7.1"),
    ):
        if package_version(distribution) != expected:
            pytest.skip(f"Live Gate 0 replay requires {distribution} {expected}")
    for executable, variable in (
        ("pdb2pqr", "ANKORA_PDB2PQR_PATH"),
        ("mk_prepare_receptor", "ANKORA_MEEKO_PATH"),
    ):
        if not discover_tool(executable, os.getenv(variable)).available:
            pytest.skip(f"Live Gate 0 replay requires {executable}")

    case = probe.Case(tmp_path, "synthetic_garymp")
    probe.write_peptide(case)
    structures = StructureArtifactStore(tmp_path)
    receptors = ReceptorArtifactStore(tmp_path)
    structure = import_structure_bytes(
        content=(case.work / "receptor.pdb").read_bytes(),
        filename="synthetic_gate0_garymp.pdb",
        source=StructureSource.LOCAL,
        source_uri=None,
        store=structures,
    )
    arguments = dict(
        source_artifact_id=structure.artifact.artifact_id,
        structure_store=structures,
        receptor_store=receptors,
    )
    rigid_record = receptor_preparation.prepare_receptor(request=_prep_request(), **arguments)
    split = receptor_preparation.prepare_receptor(
        request=_prep_request(residues=_garymp_flex_residues()),
        **arguments,
    )
    assert split.status is ReceptorPreparationStatus.DOCKING_READY
    output_by_stage = {output.stage: output for output in split.outputs}
    assert ReceptorOutputStage.PDBQT not in output_by_stage
    rigid = output_by_stage[ReceptorOutputStage.PDBQT_RIGID]
    flex = output_by_stage[ReceptorOutputStage.PDBQT_FLEX]
    assert (rigid.filename, flex.filename) == ("receptor_rigid.pdbqt", "receptor_flex.pdbqt")
    full = next(item for item in rigid_record.outputs if item.stage is ReceptorOutputStage.PDBQT)

    def content(record, output):
        data = receptors.content_path(record.receptor_id, output.artifact_id).read_bytes()
        assert sha256(data).hexdigest() == output.sha256
        return data

    assert [
        sum(line.startswith((b"ATOM  ", b"HETATM")) for line in data.splitlines())
        for data in (content(split, rigid), content(split, flex), content(rigid_record, full))
    ] == [46, 15, 61]
    assert split.flex_spec is not None
    assert split.flex_spec.added_chi_torsion_count == 6
    assert split.flex_spec.receptor_rigid_sha256 == rigid.sha256
    assert split.flex_spec.receptor_flex_sha256 == flex.sha256
    assert split.flex_atom_types == list(FLEX_TYPES)
    assert WarningCode.DOCKING_FLEXRES_DOF_HIGH not in {warning.code for warning in split.warnings}
    event = split.provenance[-1]
    assert event.event_type == "receptor_flex_pdbqt_generated"
    assert event.output_artifacts == [rigid.artifact_id, flex.artifact_id]
    assert event.tool.version == "0.7.1"
    assert event.command[-2:] == ["-f", "A:4,A:5"]
    assert event.parameters["flex_residues"] == [
        item.model_dump() for item in _garymp_flex_residues()
    ]
    assert event.parameters["flex_atom_types"] == list(FLEX_TYPES)
    assert event.parameters["added_chi_torsion_count"] == 6
    assert event.parameters["raw_logs"] == ["meeko.stdout.log", "meeko.stderr.log"]
    for filename in event.parameters["raw_logs"]:
        assert receptors.output_path(split.receptor_id, filename).is_file()
    assert receptors.load_record(split.receptor_id) == split


def _grid_fixture(
    tmp_path,
    monkeypatch,
    *,
    flexible=True,
    ligand_types=LIGAND_TYPES,
    flex_types=FLEX_TYPES,
    tamper=None,
):
    receptors = ReceptorArtifactStore(tmp_path)
    sites = BindingSiteArtifactStore(tmp_path)
    ligand_store = LigandArtifactStore(tmp_path)
    maps = AutoGridMapStore(tmp_path)
    service = AutoGridMapService(
        map_store=maps,
        receptor_store=receptors,
        binding_site_store=sites,
        ligand_store=ligand_store,
    )
    now = datetime(2026, 11, 18, tzinfo=UTC)
    receptor_id = receptors.new_receptor_id()
    receptors.create_receptor(receptor_id)

    def output(stage, document):
        filename = f"synthetic_{stage.value}.pdbqt"
        data = document.encode("ascii")
        path = receptors.write_bytes(receptor_id, filename, data)
        if tamper == stage.value:
            path.write_bytes(data + b"REMARK SYNTHETIC_TAMPER\n")
        return ReceptorOutputArtifact(
            artifact_id=f"synthetic-{stage.value}",
            stage=stage,
            filename=filename,
            format="pdbqt",
            sha256=sha256(data).hexdigest(),
            size_bytes=len(data),
            created_at=now,
            content_url="/synthetic/receptor",
        )

    rigid_document = "REMARK SYNTHETIC_RIGID\n" + _pdbqt_atoms(("C", "N", "OA"))
    rigid = output(
        ReceptorOutputStage.PDBQT_RIGID if flexible else ReceptorOutputStage.PDBQT, rigid_document
    )
    outputs = [rigid]
    residues = _garymp_flex_residues() if flexible else None
    spec = None
    if flexible:
        flex = output(ReceptorOutputStage.PDBQT_FLEX, _flex_pdbqt(residues, flex_types, branches=3))
        outputs.extend(
            [
                flex,
                output(ReceptorOutputStage.PDBQT, "REMARK SYNTHETIC_FULL\n" + _pdbqt_atoms(("S",))),
            ]
        )
        spec = ReceptorFlexSpec(
            mode=ReceptorFlexMode.SIDECHAIN_FLEX,
            flex_residues=tuple(residues),
            receptor_rigid_sha256="1" * 64 if tamper == "spec_rigid" else rigid.sha256,
            receptor_flex_sha256="2" * 64 if tamper == "spec_flex" else flex.sha256,
            added_chi_torsion_count=6,
        )
    receptor = ReceptorPreparationRecord(
        receptor_id=receptor_id,
        source_artifact_id="synthetic-source",
        created_at=now,
        status=ReceptorPreparationStatus.DOCKING_READY,
        decisions=_prep_request(residues=residues),
        outputs=outputs,
        warnings=[],
        provenance=[],
        display_output_artifact_id=rigid.artifact_id,
        flex_spec=spec,
        flex_atom_types=list(flex_types) if flexible else [],
    )
    receptors.save_record(receptor)
    site_id = sites.new_binding_site_id()
    box = BindingBox(center_x=0, center_y=0, center_z=0, size_x=10, size_y=10, size_z=10)
    site = BindingSiteRecord(
        binding_site_id=site_id,
        receptor_id=receptor_id,
        source_artifact_id=rigid.artifact_id,
        created_at=now,
        decisions=BindingSiteRequest(source=BindingSiteSource.MANUAL, manual_box=box),
        box=box,
        warnings=[],
        provenance=[
            ProvenanceEvent(
                event_id="synthetic-binding-site",
                event_type="synthetic_fixture",
                timestamp=now,
                tool=ToolIdentity(name="synthetic test fixture", version="1"),
            )
        ],
    )
    sites.save_record(site)
    request = AutoGridMapSetRequest(
        receptor_id=receptor_id,
        binding_site_id=site_id,
        source=AutoGridLigandSource.LIGAND_PREPARATION,
        ligand_id="synthetic-ligand",
        ligand_preparation_id="synthetic-ligand-preparation",
    )
    monkeypatch.setattr(
        service,
        "_single_ligand_row",
        lambda request: service._row_from_document(
            ligand_id="synthetic-ligand",
            source_index=0,
            name="SYNTHETIC_SULFUR_FREE_LIGAND",
            document=_pdbqt_atoms(ligand_types),
        ),
    )
    _install_synthetic_autogrid(monkeypatch)
    return service, request, receptor, site


def test_autogrid_builds_affinity_union_on_rigid_split_and_records_binding(tmp_path, monkeypatch):
    service, request, receptor, _ = _grid_fixture(tmp_path, monkeypatch)
    result = service.ensure_map_set(request)
    record = result.record
    rigid, flex, _ = receptor.outputs
    assert not result.reused_existing_map_set
    assert record.preflight.receptor_atom_types == ["C", "N", "OA"]
    assert record.preflight.ligand_atom_types == list(AFFINITY_TYPES)
    assert record.preflight.ligand_only_atom_types == list(LIGAND_TYPES)
    assert record.preflight.flex_atom_types == list(FLEX_TYPES)
    assert record.receptor_output_artifact_id == rigid.artifact_id
    assert record.receptor_sha256 == rigid.sha256
    assert record.receptor_flex_mode is ReceptorFlexMode.SIDECHAIN_FLEX
    assert record.receptor_flex_output_artifact_id == flex.artifact_id
    assert record.receptor_flex_sha256 == flex.sha256
    assert record.flex_atom_types == list(FLEX_TYPES)
    assert record.flex_residues == _garymp_flex_residues()
    assert record.provenance.input_artifacts[:2] == [rigid.artifact_id, flex.artifact_id]
    for name in (
        "receptor_flex_mode",
        "receptor_flex_output_artifact_id",
        "receptor_flex_sha256",
        "flex_residues",
        "flex_atom_types",
    ):
        assert record.provenance.parameters[name] == record.model_dump(mode="json")[name]

    grid_input = next(item for item in record.artifacts if item.kind is AutoGridMapKind.RECEPTOR)
    stored_receptor = service.content_path(record.map_set_id, grid_input.artifact_id).read_bytes()
    assert sha256(stored_receptor).hexdigest() == rigid.sha256
    gpf = next(item for item in record.artifacts if item.filename == GRID_PARAMETER_FILENAME)
    gpf_text = service.content_path(record.map_set_id, gpf.artifact_id).read_text()
    assert "ligand_types A C HD N OA SA" in gpf_text.splitlines()
    assert "map receptor.SA.map" in gpf_text.splitlines()
    assert any(item.atom_type == "SA" for item in record.artifacts)
    verify_autogrid_map_set_for_receptor(record, receptor)
    reused = service.ensure_map_set(request)
    assert reused.reused_existing_map_set
    assert reused.record.map_set_id == record.map_set_id


@pytest.mark.parametrize("invalidity", ["overflow", "invalid", "macrocycle_glue"])
def test_autogrid_rejects_invalid_flex_unions_before_even_probing(
    tmp_path, monkeypatch, invalidity
):
    ligand_types = (
        (*LIGAND_TYPES, "Br", "Cl", "F", "I", "Mg", "Mn", "NA", "P", "Zn")
        if invalidity == "overflow"
        else LIGAND_TYPES
    )
    flex_types = {
        "overflow": FLEX_TYPES,
        "invalid": ("C", "!"),
        "macrocycle_glue": ("C", "CG0"),
    }[invalidity]
    service, request, _, _ = _grid_fixture(
        tmp_path,
        monkeypatch,
        ligand_types=ligand_types,
        flex_types=flex_types,
    )

    def unexpected_autogrid(**kwargs):
        pytest.fail("AutoGrid was invoked for a rejected affinity-map union")

    monkeypatch.setattr(autogrid_maps, "probe_autogrid4", unexpected_autogrid)
    monkeypatch.setattr(autogrid_maps, "execute_autogrid_cancellable", unexpected_autogrid)
    with pytest.raises(AnkoraDomainError) as caught:
        service.start_map_set(request)
    assert (caught.value.code, caught.value.status_code) == ("AUTOGRID_LIGAND_TYPES_EXCEEDED", 422)
    if invalidity == "overflow":
        assert caught.value.details["max_ligand_types"] == 14
        assert len(caught.value.details["ligand_only_atom_types"]) == 14
        assert "SA" in caught.value.details["flex_atom_types"]


@pytest.mark.parametrize("tamper", ["pdbqt_rigid", "pdbqt_flex", "spec_rigid", "spec_flex"])
def test_autogrid_verifies_both_split_hashes(tmp_path, monkeypatch, tamper):
    service, request, _, _ = _grid_fixture(tmp_path, monkeypatch, tamper=tamper)
    with pytest.raises(AnkoraDomainError) as caught:
        service.ensure_map_set(request)
    assert (caught.value.code, caught.value.status_code) == ("AUTOGRID_INPUT_HASH_MISMATCH", 422)


def test_rigid_identity_is_frozen_and_legacy_records_deserialize(tmp_path, monkeypatch):
    service, request, receptor, site = _grid_fixture(tmp_path, monkeypatch, flexible=False)
    record = service.ensure_map_set(request).record
    assert record.preflight.ligand_atom_types == list(LIGAND_TYPES)
    assert record.preflight.flex_atom_types == []
    assert record.preflight.ligand_only_atom_types is None
    expected_v01 = {
        "receptor_sha256": record.receptor_sha256,
        "box": site.box.model_dump(mode="json"),
        "spacing_angstrom": record.geometry.spacing_angstrom,
        "npts": list(record.geometry.npts),
        "realized_size_angstrom": list(record.geometry.realized_size_angstrom),
        "receptor_atom_types": record.preflight.receptor_atom_types,
        "ligand_atom_types": record.preflight.ligand_atom_types,
        "smoothing_angstrom": request.parameters.smoothing_angstrom,
        "dielectric": request.parameters.dielectric,
        "autogrid_version": record.autogrid.tool.version,
        "autogrid_sha256": record.autogrid.sha256,
    }
    canonical = json.dumps(expected_v01, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    assert record.identity_key == sha256(canonical.encode("utf-8")).hexdigest()

    args = dict(
        receptor_sha256=record.receptor_sha256,
        binding_site=site,
        geometry=record.geometry,
        receptor_atom_types=tuple(record.preflight.receptor_atom_types),
        ligand_atom_types=LIGAND_TYPES,
        request=request,
        installation=_installation(),
    )
    residues = tuple(_garymp_flex_residues())
    split_key = service._identity_key(**args, flex_residues=residues, flex_atom_types=FLEX_TYPES)
    assert split_key != record.identity_key
    assert split_key == service._identity_key(
        **args, flex_residues=residues[::-1], flex_atom_types=FLEX_TYPES
    )
    assert split_key != service._identity_key(
        **args, flex_residues=residues, flex_atom_types=FLEX_TYPES[:-1]
    )

    legacy_receptor = ReceptorPreparationRecord.model_validate_json(
        receptor.model_dump_json(exclude={"flex_spec", "flex_atom_types"})
    )
    legacy_maps = AutoGridMapSetRecord.model_validate_json(
        record.model_dump_json(
            exclude={
                "receptor_flex_mode": True,
                "receptor_flex_output_artifact_id": True,
                "receptor_flex_sha256": True,
                "flex_residues": True,
                "flex_atom_types": True,
                "preflight": {"flex_atom_types", "ligand_only_atom_types"},
            }
        )
    )
    assert legacy_receptor == receptor
    assert legacy_maps == record
    verify_autogrid_map_set_for_receptor(legacy_maps, legacy_receptor)
    with pytest.raises(AnkoraDomainError) as caught:
        verify_autogrid_map_set_for_receptor(
            legacy_maps.model_copy(update={"receptor_sha256": "0" * 64}), legacy_receptor
        )
    assert caught.value.code == "AUTOGRID_FLEXRES_MAP_MISMATCH"


@pytest.mark.parametrize("mismatch", ["rigid", "locator", "flex_type", "affinity_type", "hash"])
def test_e7_contract_and_service_fail_closed_on_map_mismatch(tmp_path, monkeypatch, mismatch):
    service, request, receptor, _ = _grid_fixture(tmp_path, monkeypatch)
    good = service.ensure_map_set(request).record
    assert receptor.flex_spec is not None
    protocol = ProtocolSpec(
        engine="autodock4",
        scoring_function=ScoringFunctionId.AUTODOCK4,
        receptor_flexibility=receptor.flex_spec,
        binding_box_sha256="0" * 64,
        autogrid_map_set_sha256=good.identity_key,
    )
    reordered = good.model_copy(
        update={
            "flex_residues": list(reversed(good.flex_residues)),
            "flex_atom_types": list(reversed(good.flex_atom_types)),
        }
    )
    verify_autogrid_map_set_for_receptor(reordered, receptor)

    def verify_protocol(record):
        protocol.verify_autogrid_map_binding(
            map_receptor_sha256=record.receptor_sha256,
            map_flex_residues=tuple(record.flex_residues),
            expected_flex_atom_types=(*FLEX_TYPES[::-1], "C"),
            map_flex_atom_types=tuple(record.flex_atom_types),
            map_affinity_atom_types=tuple(record.preflight.ligand_atom_types),
        )

    verify_protocol(reordered)
    changes = {
        "rigid": {
            "receptor_flex_mode": ReceptorFlexMode.RIGID,
            "receptor_sha256": receptor.outputs[-1].sha256,
            "flex_residues": [],
            "flex_atom_types": [],
        },
        "locator": {"flex_residues": [_residue("TYR", 4), _residue("MET", 5, insertion="A")]},
        "flex_type": {"flex_atom_types": list(FLEX_TYPES[:-1])},
        "affinity_type": {
            "preflight": good.preflight.model_copy(update={"ligand_atom_types": list(LIGAND_TYPES)})
        },
        "hash": {"receptor_sha256": "0" * 64},
    }
    rejected = good.model_copy(update=changes[mismatch])
    for verify, stage in (
        (
            lambda record: verify_autogrid_map_set_for_receptor(record, receptor),
            "autogrid_map_verification",
        ),
        (verify_protocol, "protocol_contract"),
    ):
        with pytest.raises(AnkoraDomainError) as caught:
            verify(rejected)
        assert (caught.value.code, caught.value.status_code, caught.value.stage) == (
            "AUTOGRID_FLEXRES_MAP_MISMATCH",
            422,
            stage,
        )
