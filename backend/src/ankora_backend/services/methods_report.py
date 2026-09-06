"""Render one campaign's recorded provenance as a Methods section.

Everything a Methods section needs is already on disk — which chains were
kept, which residues were repaired, at what pH, from which box, under which
filter rules, with which seeds — scattered across the artifacts that recorded
each decision as it was made. This gathers that chain and writes it as prose.

Three rules the renderer follows, in order of importance:

* **Nothing is asserted that was not recorded.** A missing artifact becomes a
  visible `[not recorded: …]` marker and an entry in `gaps`, never a sentence
  that sounds verified. The output goes into a paper; a plausible invention
  here is worse than an obvious hole.
* **A docking score is never described as an affinity**, and no sentence
  claims a biological result. The section describes what was done.
* **Reproducibility is stated only when exact repeats were compared.** Engine
  type and the presence of a seed are never treated as repeat evidence.
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from ankora_backend.domain.errors import AnkoraDomainError
from ankora_backend.persistence.artifact_store import StructureArtifactStore
from ankora_backend.persistence.autodock4_store import AutoDock4JobStore
from ankora_backend.persistence.autodock_gpu_store import AutoDockGpuJobStore
from ankora_backend.persistence.autogrid_store import AutoGridMapStore
from ankora_backend.persistence.binding_site_store import BindingSiteArtifactStore
from ankora_backend.persistence.docking_store import DockingArtifactStore
from ankora_backend.persistence.ligand_store import LigandArtifactStore
from ankora_backend.persistence.receptor_store import ReceptorArtifactStore
from ankora_backend.schemas.methods import MethodsReport, MethodsSoftware
from ankora_backend.schemas.results_catalog import (
    CatalogEntry,
    ReproducibilityStatus,
    ScoringFamily,
)
from ankora_backend.services.result_catalog import (
    AUTODOCK4_BATCH,
    AUTODOCK4_JOB,
    AUTODOCK_GPU_BATCH,
    AUTODOCK_GPU_JOB,
    VINA_BATCH,
    VINA_JOB,
    ResultCatalogService,
)
from ankora_backend.services.tool_citations import Reference, references_for

_STAGE = "methods_report"

_WATER = {
    "remove": "crystallographic waters were removed",
    "keep": "crystallographic waters were retained",
}
_SITE_SOURCE = {
    "co_crystallized_ligand": "the co-crystallized ligand",
    "selected_residues": "a set of explicitly selected residues",
    "manual": "manually entered coordinates",
    "full_protein_blind": "the entire prepared receptor (blind search)",
    "pocket_detected": "a computationally detected pocket",
}
_LOCAL_SEARCH = {"ad": "ADADELTA", "sw": "Solis-Wets", "fire": "FIRE"}
_ALERT_POLICY_EFFECT = {
    "review": "those matches were flagged for review",
    "exclude": "compounds with those matches were excluded",
    "ignore": "those matches were recorded but did not affect selection",
}
_DUPLICATE_POLICY = {
    "exclude": "excluded", "review": "flagged for review", "keep": "retained",
}


@dataclass
class _Draft:
    """Prose under construction, with the holes it could not fill."""

    lines: list[str] = field(default_factory=list)
    gaps: list[str] = field(default_factory=list)
    software: dict[str, MethodsSoftware] = field(default_factory=dict)

    def say(self, text: str) -> None:
        self.lines.append(text)

    def missing(self, what: str) -> str:
        """Record a hole and return the marker that stands in for it."""
        self.gaps.append(what)
        return f"[not recorded: {what}]"

    def tool(self, name: str | None, version: str | None, role: str) -> None:
        if not name or not version:
            return
        self.software.setdefault(f"{name} {version}", MethodsSoftware(
            name=name, version=version, role=role,
        ))


@dataclass(frozen=True)
class _PreparationProtocol:
    embedding_method: str | None
    force_field: str
    max_iterations: int
    random_seed: int | None
    conformer_pool_size: int | None
    independent_from_source_coordinates: bool
    conformer_tool_name: str | None
    conformer_tool_version: str | None
    pdbqt_tool_name: str
    pdbqt_tool_version: str
    charge_model: str


@dataclass(frozen=True)
class _StateDecision:
    kind: str
    tool_name: str | None = None
    tool_version: str | None = None
    ph_min: float | None = None
    ph_max: float | None = None
    candidate_count: int | None = None
    candidate_index: int | None = None
    max_tautomers_per_protomer: int | None = None
    max_microstates_per_parent: int | None = None
    enumeration_truncated: bool = False


@dataclass(frozen=True)
class _StateLineage:
    decisions: tuple[_StateDecision, ...]


@dataclass
class _PreparedLigand:
    ligand_id: str
    preparation_id: str
    conformer: Any
    pdbqt: Any
    protocol: _PreparationProtocol
    state_lineage: _StateLineage | None


@dataclass
class _PreparationSet:
    items: list[_PreparedLigand]
    total_entries: int
    entries_without_preparation: int
    unavailable_preparations: int


class MethodsReportService:
    def __init__(
        self,
        *,
        catalog: ResultCatalogService,
        structures: StructureArtifactStore,
        receptors: ReceptorArtifactStore,
        binding_sites: BindingSiteArtifactStore,
        ligands: LigandArtifactStore,
        maps: AutoGridMapStore,
        docking: DockingArtifactStore,
        autodock4: AutoDock4JobStore,
        autodock_gpu: AutoDockGpuJobStore,
    ) -> None:
        self._catalog = catalog
        self._structures = structures
        self._receptors = receptors
        self._binding_sites = binding_sites
        self._ligands = ligands
        self._maps = maps
        self._docking = docking
        self._autodock4 = autodock4
        self._autodock_gpu = autodock_gpu

    @classmethod
    def from_environment(cls) -> "MethodsReportService":
        return cls(
            catalog=ResultCatalogService.from_environment(),
            structures=StructureArtifactStore.from_environment(),
            receptors=ReceptorArtifactStore.from_environment(),
            binding_sites=BindingSiteArtifactStore.from_environment(),
            ligands=LigandArtifactStore.from_environment(),
            maps=AutoGridMapStore.from_environment(),
            docking=DockingArtifactStore.from_environment(),
            autodock4=AutoDock4JobStore.from_environment(),
            autodock_gpu=AutoDockGpuJobStore.from_environment(),
        )

    def render(self, catalog_id: str) -> MethodsReport:
        entry = self._catalog.get_campaign(catalog_id)
        draft = _Draft()

        self._protein(draft, entry)
        self._site(draft, entry)
        self._ligands_section(draft, entry)
        self._docking_section(draft, entry)
        self._outcome(draft, entry)
        self._software_section(draft)

        return MethodsReport(
            catalog_id=catalog_id,
            generated_at=datetime.now(UTC),
            engine_label=entry.engine_label,
            markdown="\n".join(draft.lines).strip() + "\n",
            gaps=draft.gaps,
            software=list(draft.software.values()),
        )

    # --- sections ---------------------------------------------------------

    def _protein(self, draft: _Draft, entry: CatalogEntry) -> None:
        draft.say("## Protein preparation\n")
        receptor = _load(self._receptors.load_record, entry.receptor_id)
        if receptor is None:
            draft.say(
                "The receptor preparation record for this campaign is no longer "
                f"available. {draft.missing('receptor preparation record')}\n"
            )
            return

        decisions = receptor.decisions
        events = {event.event_type: event for event in receptor.provenance}
        structure = _load(self._structures.load_record, receptor.source_artifact_id)

        origin = ""
        if structure is None:
            origin = draft.missing("source structure record")
        else:
            entry_id = structure.metadata.entry_id
            source = structure.artifact.source
            resolution = structure.metadata.resolution_angstrom
            if source == "rcsb" and entry_id:
                origin = f"the RCSB PDB entry {entry_id}"
            elif source == "alphafold":
                origin = f"the AlphaFold DB prediction {entry_id or ''}".strip()
            else:
                origin = f"the file {structure.artifact.original_filename}"
            if resolution is not None:
                origin += f" (resolution {resolution:.2f} Å)"

        chains = ", ".join(decisions.selected_chains) or draft.missing("selected chains")
        water = _WATER.get(decisions.water_action, str(decisions.water_action))
        removed = [
            item.component_id.split("|")[2]
            for item in decisions.component_decisions
            if item.action == "remove" and len(item.component_id.split("|")) > 2
        ]
        sentence = (
            f"The receptor was prepared from {origin}. "
            f"Chain{'s' if ',' in chains else ''} {chains} "
            f"{'were' if ',' in chains else 'was'} retained and {water}"
        )
        if removed:
            sentence += f"; the co-crystallized component{'s' if len(removed) > 1 else ''} "
            sentence += f"{', '.join(sorted(set(removed)))} "
            sentence += f"{'were' if len(removed) > 1 else 'was'} removed"
        draft.say(sentence + ".")

        repaired = events.get("receptor_residues_repaired")
        if repaired is not None:
            residues = repaired.parameters.get("residues") or []
            tool = repaired.tool
            draft.tool(tool.name, tool.version, "missing side-chain repair")
            draft.say(
                f"Missing side-chain atoms in {len(residues)} residue"
                f"{'s' if len(residues) != 1 else ''} were rebuilt with "
                f"{tool.name} {tool.version}."
            )

        relax = events.get("receptor_clashes_relaxed")
        if relax is not None and getattr(decisions.relaxation, "enabled", False):
            parameters = relax.parameters
            displacement = parameters.get("max_restrained_atom_displacement_angstrom")
            tool = relax.tool
            draft.tool(tool.name, tool.version, "restrained clash relaxation")
            moved = (
                f" No previously observed atom moved more than "
                f"{float(displacement):.2f} Å."
                if isinstance(displacement, (int, float))
                else ""
            )
            draft.say(
                "Newly placed atoms were relaxed against a purely repulsive "
                f"potential with {tool.name} {tool.version}, using a positional "
                "restraint of "
                f"{parameters.get('restraint_force_constant_kcal_mol_a2')} "
                "kcal mol⁻¹ Å⁻² on every previously observed atom and at most "
                f"{parameters.get('max_iterations')} iterations.{moved}"
            )

        protonation = events.get("receptor_protonated")
        if protonation is not None:
            tool = protonation.tool
            draft.tool(tool.name, tool.version, "protonation and charge assignment")
            draft.say(
                "Protonation states were assigned at pH "
                f"{protonation.parameters.get('ph')} with the "
                f"{protonation.parameters.get('force_field')} force field using "
                f"{_cite(tool.name, tool.version)}."
            )
        else:
            draft.say(
                "Protonation of the receptor was "
                f"{draft.missing('receptor protonation record')}."
            )

        pdbqt = events.get("receptor_pdbqt_generated")
        if pdbqt is not None:
            draft.tool(pdbqt.tool.name, pdbqt.tool.version, "receptor PDBQT conversion")
            draft.say(
                "The prepared receptor was converted to PDBQT with "
                f"{pdbqt.tool.name} {pdbqt.tool.version}."
            )
        draft.say("")

    def _site(self, draft: _Draft, entry: CatalogEntry) -> None:
        draft.say("## Binding site definition\n")
        site = _load(self._binding_sites.load_record, entry.binding_site_id)
        if site is None:
            draft.say(
                "The binding-site record is no longer available. "
                f"{draft.missing('binding site record')}\n"
            )
            return

        decisions = site.decisions
        source = _SITE_SOURCE.get(str(decisions.source), str(decisions.source))
        detail = ""
        if decisions.ligand_origin is not None:
            heterogen = decisions.ligand_origin.heterogen
            detail = (
                f" ({heterogen.residue_name} {heterogen.chain_id}:"
                f"{heterogen.sequence_number}, padded by "
                f"{decisions.ligand_origin.padding_angstrom:g} Å on every side)"
            )
        elif decisions.residue_selection is not None:
            count = len(decisions.residue_selection.residues)
            detail = (
                f" ({count} residue{'s' if count != 1 else ''}, padded by "
                f"{decisions.residue_selection.padding_angstrom:g} Å)"
            )

        box = site.box
        draft.say(
            f"The search space was defined from {source}{detail}. The resulting "
            f"box was centred at ({box.center_x:.2f}, {box.center_y:.2f}, "
            f"{box.center_z:.2f}) Å with dimensions {box.size_x:.2f} × "
            f"{box.size_y:.2f} × {box.size_z:.2f} Å, in the coordinate frame of "
            "the prepared receptor."
        )

        if entry.map_set_id:
            maps = _load(self._maps.load_record, entry.map_set_id)
            if maps is not None:
                geometry = maps.geometry
                draft.tool(
                    maps.autogrid.tool.name, maps.autogrid.tool.version,
                    "affinity grid map calculation",
                )
                draft.say(
                    "Affinity grid maps were precomputed over this box with "
                    f"{maps.autogrid.tool.name} {maps.autogrid.tool.version} at "
                    f"{geometry.spacing_angstrom:g} Å spacing "
                    f"({geometry.npts[0]} × {geometry.npts[1]} × "
                    f"{geometry.npts[2]} intervals)."
                )
            else:
                draft.say(
                    "The grid map set used for this campaign is "
                    f"{draft.missing('AutoGrid map set record')}."
                )
        draft.say("")

    def _ligands_section(self, draft: _Draft, entry: CatalogEntry) -> None:
        draft.say("## Ligand preparation\n")
        if entry.library_id is None:
            draft.say("A single ligand was docked; no compound library was screened.")
            self._preparation(draft, entry)
            draft.say("")
            return

        library = _load(self._ligands.load_library_record, entry.library_id)
        if library is None:
            draft.say(
                "The compound library record is no longer available. "
                f"{draft.missing('compound library record')}\n"
            )
            return

        artifact = library.artifact
        draft.say(
            f"{artifact.record_count} compounds were imported from "
            f"{artifact.filename} ({artifact.format.upper()}); "
            f"{library.imported_count} were parsed successfully and "
            f"{library.failed_count} could not be read."
        )

        run = (
            _load2(self._ligands.load_filter_run, entry.library_id, entry.filter_run_id)
            if entry.filter_run_id
            else None
        )
        if run is None:
            draft.say(
                "The filter run that produced this selection is "
                f"{draft.missing('library filter run record')}.\n"
            )
            return

        draft.tool("RDKit", run.rdkit_version, "descriptor calculation and filtering")
        microstate_plan = getattr(run, "microstate_plan", None)
        if (
            microstate_plan is not None
            and _text(microstate_plan.mode) == "enumerated_selection"
        ):
            draft.say(
                "Before filtering, one protonation/tautomer microstate was "
                "explicitly selected for each retained parent compound from a "
                f"bounded enumeration at pH {microstate_plan.ph_min:g}-"
                f"{microstate_plan.ph_max:g} (pKa precision "
                f"{microstate_plan.precision:g}; at most "
                f"{microstate_plan.max_tautomers_per_protomer} tautomers per "
                f"protomer and {microstate_plan.max_microstates_per_parent} "
                "microstates per parent). Candidate order was not interpreted "
                "as a population or suitability ranking."
            )
        else:
            draft.say(
                "Library filtering used each compound's exact submitted or "
                "explicitly component-resolved chemical state; no protonation "
                "or tautomer alternative was selected automatically."
            )
        plan = run.plan
        required = _required_rules(plan)
        summary = run.summary
        draft.say(
            "Physicochemical descriptors were computed with RDKit "
            f"{run.rdkit_version} and the library was filtered against "
            f"{_join(required)}."
            if required
            else "Physicochemical descriptors were computed with RDKit "
            f"{run.rdkit_version}; no rule was applied as a requirement."
        )
        if plan.custom_rules:
            draft.say(
                "Additional user-defined criteria were applied: "
                f"{_join([_custom_rule(rule) for rule in plan.custom_rules])}."
            )
        draft.say(
            f"{_alert_policy_sentence('PAINS', summary.pains_match_count, plan.pains_policy)} "
            f"{_alert_policy_sentence('Brenk', summary.brenk_match_count, plan.brenk_policy)} "
            "Exact canonical-SMILES duplicates were "
            f"{_DUPLICATE_POLICY.get(str(plan.duplicate_policy), str(plan.duplicate_policy))} "
            f"({summary.duplicate_count} found)."
        )
        classified_count = (
            summary.eligible_count
            + summary.excluded_count
            + summary.needs_decision_count
        )
        census = (
            f"Of {summary.imported_count} compounds evaluated, "
            f"{summary.eligible_count} were eligible for selection, "
            f"{summary.excluded_count} were excluded, and "
            f"{summary.needs_decision_count} required an explicit chemical-state "
            "decision (undefined stereochemistry or multiple fragments)."
        )
        if classified_count == summary.imported_count:
            draft.say(
                f"{census} These mutually exclusive outcomes account for all "
                f"{summary.imported_count} compounds."
            )
        else:
            census_gap = draft.missing("internally consistent library filter census")
            draft.say(
                f"{census} The categories account for {classified_count} compounds; "
                f"the discrepancy is {census_gap}."
            )
        draft.say(
            f"The recorded campaign carried {entry.selected_count} compound entries "
            "forward to docking."
        )
        self._preparation(draft, entry)
        draft.say("")

    def _preparation(self, draft: _Draft, entry: CatalogEntry) -> None:
        """Describe every exact preparation used by this campaign.

        A library campaign may contain multiple preparation protocols. A
        sentence in the plural is allowed only after every referenced record
        has been read and its protocol compared.
        """
        preparations = _load_preparations(self._ligands, self._record(entry))
        if not preparations.items:
            draft.say(
                "How the selected ligand compounds were converted to "
                "three-dimensional structures is "
                f"{draft.missing('ligand conformer and PDBQT records')}."
            )
            return

        for item in preparations.items:
            protocol = item.protocol
            draft.tool(
                protocol.conformer_tool_name,
                protocol.conformer_tool_version,
                "ligand conformer generation and minimization",
            )
            draft.tool(
                protocol.pdbqt_tool_name,
                protocol.pdbqt_tool_version,
                "ligand PDBQT conversion",
            )
            if item.state_lineage is not None:
                for decision in item.state_lineage.decisions:
                    draft.tool(
                        decision.tool_name,
                        decision.tool_version,
                        "ligand chemical-state resolution",
                    )

        if entry.library_id is None:
            draft.say(_single_preparation_sentence(preparations.items[0].protocol))
        else:
            _batch_preparation_prose(draft, preparations)
        _chemical_state_prose(draft, preparations, single=entry.library_id is None)

    def _docking_section(self, draft: _Draft, entry: CatalogEntry) -> None:
        draft.say("## Molecular docking\n")
        parameters = self._parameters(entry)
        if parameters is None:
            draft.say(
                "The docking parameters for this campaign are "
                f"{draft.missing('docking request parameters')}.\n"
            )
            return

        name, version = _engine_identity(entry)
        draft.tool(name, version, "molecular docking")
        engine = _engine_prose(entry, name, version)
        if entry.scoring_family is ScoringFamily.VINA:
            sampling_protocol = parameters.get("sampling_protocol")
            if sampling_protocol is None:
                draft.say(
                    "This historical campaign did not record a named Vina sampling "
                    "purpose, so no screening or refinement intent was inferred."
                )
            else:
                purpose = {
                    "screening": "Screening",
                    "pose_refinement": "Pose refinement",
                    "custom": "Custom",
                }.get(str(sampling_protocol), str(sampling_protocol))
                draft.say(
                    f"The recorded Vina sampling purpose was {purpose}. This label "
                    "describes protocol intent only; it is not evidence of sampling "
                    "convergence or publication suitability."
                )
            draft.say(
                f"Docking was performed with {engine} using an "
                f"exhaustiveness of {parameters.get('exhaustiveness')}, at most "
                f"{parameters.get('num_modes')} binding modes per compound, a "
                "minimum inter-mode RMSD of "
                f"{parameters.get('min_rmsd_angstrom')} Å and an energy range of "
                f"{parameters.get('energy_range_kcal_mol')} kcal mol⁻¹. "
                f"The random seed was fixed at {parameters.get('seed')}."
            )
        else:
            runs = parameters.get("runs", parameters.get("ga_runs"))
            population = parameters.get(
                "population_size", parameters.get("ga_population_size")
            )
            evaluations = parameters.get(
                "energy_evaluations", parameters.get("ga_energy_evaluations")
            )
            sentence = (
                f"Docking was performed with {engine} using the "
                f"Lamarckian genetic algorithm with {runs} independent runs per "
                f"compound, a population of {population} and a budget of "
                f"{_scientific(evaluations)} energy evaluations"
            )
            method = parameters.get("local_search_method")
            if method:
                sentence += f", with {_LOCAL_SEARCH.get(str(method), str(method))} local search"
            generations = parameters.get("ga_generations")
            if generations:
                sentence += f" over at most {generations} generations"
            draft.say(sentence + ".")
            draft.say(
                "Resulting poses were clustered by AutoDock at an RMSD "
                "tolerance of "
                f"{parameters.get('cluster_rmsd_tolerance_angstrom')} Å."
            )
        if entry.executable_sha256:
            draft.say(
                "The exact executable used is identified by SHA-256 "
                f"{entry.executable_sha256}."
            )
        if entry.device_name:
            draft.say(f"Docking ran on an {entry.device_name}.")
        draft.say("")

    def _outcome(self, draft: _Draft, entry: CatalogEntry) -> None:
        draft.say("## Results and reproducibility\n")
        value = (
            "Vina score"
            if entry.scoring_family is ScoringFamily.VINA
            else "AutoDock4 binding energy"
        )
        draft.say(
            f"{entry.selected_count} compounds were submitted, of which "
            f"{entry.succeeded_count} produced poses and {entry.failed_count} "
            "failed. Compounds are ranked by their best "
            f"{value} in kcal mol⁻¹; these values are computational estimates "
            "from an empirical scoring function and are not measured binding "
            "affinities."
        )
        assessment = entry.reproducibility
        if assessment.status is ReproducibilityStatus.MEASURED_REPRODUCIBLE:
            draft.say(
                f"Repeat behavior was measured across {len(assessment.executions)} "
                "exactly comparable recorded executions. Their parsed scientific "
                "outputs and retained pose-artifact bytes were identical."
            )
            draft.say(_reproducibility_evidence(assessment))
        elif assessment.status is ReproducibilityStatus.MEASURED_VARIABLE:
            draft.say(
                f"Repeat behavior was measured across {len(assessment.executions)} "
                "exactly comparable recorded executions. At least two parsed "
                "scientific-output or retained pose-artifact fingerprints differed; "
                "the values reported here belong to this exact recorded execution."
            )
            draft.say(_reproducibility_evidence(assessment))
        else:
            draft.say(
                "Repeat reproducibility was not assessed for this exact combination "
                "of inputs, recorded tool identity and protocol. Recorded seeds "
                "support an exact "
                "rerun request but do not establish that its outputs will match."
            )
        draft.say("")

    def _software_section(self, draft: _Draft) -> None:
        draft.say("## Software\n")
        if not draft.software:
            draft.say(f"{draft.missing('tool versions')}\n")
            return

        tools = sorted(draft.software.values(), key=lambda tool: tool.name)
        # Numbered in the order a reader meets them, so the list reads down the
        # table rather than by some internal key.
        numbers: dict[str, int] = {}
        ordered: list[Reference] = []
        uncited: list[str] = []
        for item in tools:
            found = references_for(item.name)
            if not found:
                uncited.append(item.name)
            for reference in found:
                if reference.key not in numbers:
                    numbers[reference.key] = len(ordered) + 1
                    ordered.append(reference)

        draft.say("| Software | Version | Role | References |")
        draft.say("| --- | --- | --- | --- |")
        for item in tools:
            cited = ", ".join(
                str(numbers[reference.key]) for reference in references_for(item.name)
            )
            draft.say(
                f"| {item.name} | {item.version} | {item.role} | {cited or 'none recorded'} |"
            )
        draft.say("")

        if uncited:
            # Not a campaign gap: the records are complete, Ankora simply holds
            # no verified reference for this tool. Saying which one keeps the
            # author from assuming the list is exhaustive.
            draft.say(
                "Ankora holds no verified published reference for "
                f"{_join(sorted(set(uncited)))}; supply it from the tool's own "
                "documentation."
            )
            draft.say("")

        if not ordered:
            return
        draft.say("## References\n")
        for index, reference in enumerate(ordered, start=1):
            draft.say(f"{index}. {reference.rendered()}")
        draft.say("")
        draft.say(
            "*Each reference above is the one that tool's authors ask to be "
            "cited, with author list, year, volume and pages taken from the "
            "DOI's registered metadata. Restyle them to the target journal, and "
            "cite Ankora itself separately.*"
        )

    # --- record access ----------------------------------------------------

    def _parameters(self, entry: CatalogEntry) -> dict[str, Any] | None:
        record = self._record(entry)
        if record is None:
            return None
        return dict(record.request.parameters.model_dump(mode="json"))

    def _record(self, entry: CatalogEntry) -> Any:
        """The docking record itself, loaded by the one accessor it needs.

        Resolved per engine rather than through a table of bound methods: a
        campaign should not have to hold a reference to the single-job loader
        it will never call.
        """
        if entry.engine_key == AUTODOCK4_BATCH:
            return _load(self._autodock4.load_batch, entry.record_id)
        if entry.engine_key == AUTODOCK_GPU_BATCH:
            return _load(self._autodock_gpu.load_batch, entry.record_id)
        if entry.engine_key == AUTODOCK4_JOB:
            return _load(self._autodock4.load_job, entry.record_id)
        if entry.engine_key == AUTODOCK_GPU_JOB:
            return _load(self._autodock_gpu.load_job, entry.record_id)
        if entry.engine_key == "vina_batch":
            return _load(self._docking.load_batch_record, entry.record_id)
        return _load(self._docking.load_record, entry.record_id)


def _reproducibility_evidence(assessment: Any) -> str:
    executions = "; ".join(
        f"{execution.catalog_id} (output fingerprint SHA-256 "
        f"{execution.output_fingerprint_sha256})"
        for execution in assessment.executions
    )
    return (
        f"The comparison used {assessment.protocol}, input fingerprint SHA-256 "
        f"{assessment.input_fingerprint_sha256}, and covered {assessment.scope}. "
        f"The exact recorded executions were {executions}."
    )


def _cite(name: str, version: str) -> str:
    """`PDB2PQR/PROPKA` with version `pdb2pqr 3.7.1; propka 3.5.1` stutters."""
    if any(part.lower() in version.lower() for part in name.replace("/", " ").split()):
        return version
    return f"{name} {version}"


def _engine_prose(entry: CatalogEntry, name: str, version: str) -> str:
    """`AutoDock-GPU 1.6 (AutoDock4 scoring function)` reads; the UI label does not."""
    if entry.backend == "autodock_gpu":
        return f"{name} {version} (AutoDock4 scoring function)"
    return f"{name} {version}"


def _load_preparations(ligands: Any, record: Any) -> _PreparationSet:
    """Load every preparation this campaign actually used.

    A single job records the exact identifiers on its request; each batch
    entry records them beside its result. Looking a ligand's preparations up
    by hand would answer a different question - a compound can be prepared
    more than once, and only one of those runs is the protocol being written
    about.
    """
    references: list[tuple[str, str]] = []
    request = getattr(record, "request", None)
    request_ligand_id = getattr(request, "ligand_id", None)
    request_preparation_id = getattr(request, "ligand_preparation_id", None)
    if request_ligand_id and request_preparation_id:
        references.append((request_ligand_id, request_preparation_id))
        total_entries = 1
        entries_without_preparation = 0
    else:
        entries = list(getattr(record, "entries", []))
        total_entries = len(entries)
        for campaign_entry in entries:
            preparation_id = getattr(campaign_entry, "ligand_preparation_id", None)
            if preparation_id:
                references.append((campaign_entry.ligand_id, preparation_id))
        entries_without_preparation = total_entries - len(references)

    items: list[_PreparedLigand] = []
    for ligand_id, preparation_id in references:
        prepared = _load_preparation(ligands, ligand_id, preparation_id)
        if prepared is not None:
            items.append(prepared)
    return _PreparationSet(
        items=items,
        total_entries=total_entries,
        entries_without_preparation=entries_without_preparation,
        unavailable_preparations=len(references) - len(items),
    )


def _load_preparation(
    ligands: Any, ligand_id: str, preparation_id: str,
) -> _PreparedLigand | None:
    pdbqt = _load2(ligands.load_pdbqt_record, ligand_id, preparation_id)
    if pdbqt is None:
        return None
    conformer = _load2(
        ligands.load_conformer_record, ligand_id, pdbqt.artifact.conformer_id,
    )
    if conformer is None:
        return None
    minimization = conformer.minimization
    conformer_tool = getattr(getattr(conformer, "provenance", None), "tool", None)
    protocol = _PreparationProtocol(
        embedding_method=getattr(minimization, "embedding_method", None),
        force_field=_text(minimization.force_field),
        max_iterations=minimization.max_iterations,
        random_seed=getattr(minimization, "random_seed", None),
        conformer_pool_size=getattr(minimization, "conformer_pool_size", None),
        independent_from_source_coordinates=getattr(
            minimization, "independent_from_source_coordinates", False
        ),
        conformer_tool_name=getattr(conformer_tool, "name", None),
        conformer_tool_version=getattr(conformer_tool, "version", None),
        pdbqt_tool_name=pdbqt.tool.name,
        pdbqt_tool_version=pdbqt.tool.version,
        charge_model=_text(pdbqt.charge_model),
    )
    return _PreparedLigand(
        ligand_id=ligand_id,
        preparation_id=preparation_id,
        conformer=conformer,
        pdbqt=pdbqt,
        protocol=protocol,
        state_lineage=_state_lineage(ligands, ligand_id, conformer),
    )


def _single_preparation_sentence(protocol: _PreparationProtocol) -> str:
    return (
        "The selected ligand was converted to a three-dimensional conformer "
        f"using {_protocol_description(protocol)}."
    )


def _batch_preparation_prose(draft: _Draft, preparations: _PreparationSet) -> None:
    missing = (
        preparations.entries_without_preparation
        + preparations.unavailable_preparations
    )
    if missing:
        draft.say(
            f"Preparation evidence was available for {len(preparations.items)} of "
            f"{preparations.total_entries} campaign entries; {missing} did not "
            "name an available conformer and PDBQT lineage. "
            f"{draft.missing('complete batch ligand preparation records')}"
        )

    groups: dict[_PreparationProtocol, int] = {}
    for item in preparations.items:
        groups[item.protocol] = groups.get(item.protocol, 0) + 1
    if len(groups) == 1:
        protocol, count = next(iter(groups.items()))
        scope = "docked" if not missing else "available"
        draft.say(
            f"All {count} {scope} ligand{'s' if count != 1 else ''} were prepared "
            f"with {_protocol_description(protocol)}."
        )
        return

    draft.say(
        f"The {len(preparations.items)} available ligand preparations used "
        f"{len(groups)} distinct recorded protocol{'s' if len(groups) != 1 else ''}:"
    )
    for protocol, count in sorted(
        groups.items(), key=lambda pair: (_protocol_description(pair[0]), pair[1])
    ):
        draft.say(
            f"- {count} ligand{'s' if count != 1 else ''}: "
            f"{_protocol_description(protocol)}."
        )


def _protocol_description(protocol: _PreparationProtocol) -> str:
    coordinate_source = (
        f"independent {protocol.embedding_method} coordinates"
        if protocol.independent_from_source_coordinates and protocol.embedding_method
        else (
            f"{protocol.embedding_method} coordinates"
            if protocol.embedding_method
            else "the recorded source coordinates"
        )
    )
    details = []
    if protocol.conformer_pool_size is not None:
        details.append(f"a {protocol.conformer_pool_size}-conformer pool")
    if protocol.random_seed is not None:
        details.append(f"seed {protocol.random_seed}")
    generation = coordinate_source
    if details:
        generation += f" ({', '.join(details)})"
    minimizer = (
        f"{protocol.conformer_tool_name} {protocol.conformer_tool_version}"
        if protocol.conformer_tool_name and protocol.conformer_tool_version
        else "the recorded conformer tool"
    )
    charge = protocol.charge_model.replace("_", " ").title()
    return (
        f"{generation}, {protocol.force_field} minimization with {minimizer} "
        f"(up to {protocol.max_iterations} iterations), and "
        f"{protocol.pdbqt_tool_name} {protocol.pdbqt_tool_version} PDBQT "
        f"conversion with {charge} partial charges"
    )


def _state_lineage(ligands: Any, ligand_id: str, conformer: Any) -> _StateLineage | None:
    provenance = getattr(conformer, "provenance", None)
    inputs = list(getattr(provenance, "input_artifacts", []))
    if len(inputs) != 1:
        return None
    current_state_id = inputs[0]
    ligand = _load(ligands.load_record, ligand_id)
    if ligand is None:
        return None
    initial_state = getattr(ligand, "state", None)
    initial_state_id = getattr(initial_state, "state_id", ligand_id)
    if current_state_id == initial_state_id:
        return _StateLineage(decisions=())

    decisions: list[_StateDecision] = []
    visited: set[str] = set()
    while current_state_id != initial_state_id:
        if current_state_id in visited:
            return None
        visited.add(current_state_id)
        state = _load2(ligands.load_state_record, ligand_id, current_state_id)
        if state is None:
            return None
        event = state.provenance
        if event.event_type == "ligand_protonation_resolved":
            decisions.append(
                _StateDecision(
                    kind="protonation",
                    tool_name=event.tool.name,
                    tool_version=event.tool.version,
                    ph_min=state.selection.ph_min,
                    ph_max=state.selection.ph_max,
                    candidate_count=state.selection.candidate_count,
                )
            )
        elif event.event_type == "ligand_microstate_selected":
            plan = state.selection.plan
            decisions.append(
                _StateDecision(
                    kind="microstate",
                    tool_name=event.tool.name,
                    tool_version=event.tool.version,
                    ph_min=plan.ph_min,
                    ph_max=plan.ph_max,
                    candidate_count=state.selection.candidate_count,
                    candidate_index=state.selection.candidate_index,
                    max_tautomers_per_protomer=plan.max_tautomers_per_protomer,
                    max_microstates_per_parent=plan.max_microstates_per_parent,
                    enumeration_truncated=state.selection.enumeration_truncated,
                )
            )
        elif event.event_type == "ligand_chemical_state_resolved":
            decisions.append(
                _StateDecision(
                    kind="component/stereochemistry",
                    tool_name=event.tool.name,
                    tool_version=event.tool.version,
                )
            )
        else:
            return None
        current_state_id = state.parent_state_id
    decisions.reverse()
    return _StateLineage(decisions=tuple(decisions))


def _chemical_state_prose(
    draft: _Draft, preparations: _PreparationSet, *, single: bool,
) -> None:
    known = [item.state_lineage for item in preparations.items if item.state_lineage]
    unknown = len(preparations.items) - len(known)
    if unknown:
        draft.say(
            f"Chemical-state lineage was available for {len(known)} of "
            f"{len(preparations.items)} prepared ligand records. "
            f"{draft.missing('complete ligand chemical-state lineage')}"
        )
    if not known:
        return

    groups: dict[_StateLineage, int] = {}
    for lineage in known:
        groups[lineage] = groups.get(lineage, 0) + 1
    if len(groups) == 1:
        lineage, count = next(iter(groups.items()))
        subject = "The selected ligand" if single else f"All {count} verified ligands"
        draft.say(f"{subject} {_state_description(lineage)}.")
    else:
        draft.say(
            f"The {len(known)} verified ligands comprised "
            f"{len(groups)} chemical-state lineages:"
        )
        for lineage, count in sorted(
            groups.items(), key=lambda pair: (_state_description(pair[0]), pair[1])
        ):
            draft.say(
                f"- {count} ligand{'s' if count != 1 else ''} "
                f"{_state_description(lineage)}."
            )
    if all(
        decision.kind not in {"protonation", "microstate"}
        for lineage in known
        for decision in lineage.decisions
    ):
        draft.say("No pH-based ligand protonation enumeration was recorded.")
    if all(
        decision.kind != "microstate"
        for lineage in known
        for decision in lineage.decisions
    ):
        draft.say("No ligand tautomer enumeration was recorded.")


def _state_description(lineage: _StateLineage) -> str:
    if not lineage.decisions:
        return "used the initial imported or extracted chemical state"
    descriptions = []
    for decision in lineage.decisions:
        if decision.kind == "component/stereochemistry":
            descriptions.append("underwent explicit component/stereochemistry resolution")
            continue
        ph = (
            f"pH {decision.ph_min:g}"
            if decision.ph_min == decision.ph_max
            else f"pH {decision.ph_min:g}-{decision.ph_max:g}"
        )
        if decision.kind == "microstate":
            truncation = (
                ", with the configured bound reached"
                if decision.enumeration_truncated
                else ""
            )
            descriptions.append(
                "used explicitly selected protonation/tautomer candidate "
                f"{(decision.candidate_index or 0) + 1} of "
                f"{decision.candidate_count} generated by {decision.tool_name} "
                f"{decision.tool_version} at {ph} (limits: "
                f"{decision.max_tautomers_per_protomer} tautomers per protomer, "
                f"{decision.max_microstates_per_parent} states per parent"
                f"{truncation}; candidate order was unranked)"
            )
        else:
            descriptions.append(
                "used an explicitly selected protonation candidate "
                f"({decision.candidate_count} enumerated by {decision.tool_name} "
                f"{decision.tool_version} at {ph})"
            )
    return " and ".join(descriptions)


def _text(value: Any) -> str:
    return str(getattr(value, "value", value))


_ENGINE_NAMES = {
    VINA_BATCH: "AutoDock Vina",
    VINA_JOB: "AutoDock Vina",
    AUTODOCK4_BATCH: "AutoDock4",
    AUTODOCK4_JOB: "AutoDock4",
    AUTODOCK_GPU_BATCH: "AutoDock-GPU",
    AUTODOCK_GPU_JOB: "AutoDock-GPU",
}


def _engine_identity(entry: CatalogEntry) -> tuple[str, str]:
    """The engine's name and version, from the record's own key.

    This used to parse `engine_label`, which is written for the interface, not
    for prose. `AutoDock 4.2.6 · CPU` names the backend last, so taking the
    trailing segment produced the tool name `CPU` — every AutoDock4 CPU
    campaign, the reproducible reference backend, rendered "Docking was
    performed with CPU 4.2.6" and listed `CPU` in the Software table. A label
    is a display string; identity comes from the key.
    """
    name = _ENGINE_NAMES.get(entry.engine_key)
    if name is None:
        return entry.engine_label, entry.engine_version
    return name, entry.engine_version


def _required_rules(plan: Any) -> list[str]:
    rules = []
    if plan.require_lipinski:
        rules.append(
            "Lipinski's rule of five (at most "
            f"{plan.max_lipinski_violations} violation"
            f"{'s' if plan.max_lipinski_violations != 1 else ''})"
        )
    if plan.require_veber:
        rules.append("the Veber criteria")
    if plan.require_ghose:
        rules.append("the Ghose filter")
    if plan.require_muegge:
        rules.append("the Muegge filter")
    if plan.minimum_qed is not None:
        rules.append(f"a minimum QED of {plan.minimum_qed}")
    return rules


def _custom_rule(rule: Any) -> str:
    operators = {
        "lt": "<", "le": "≤", "gt": ">", "ge": "≥", "eq": "=", "between": "between",
    }
    symbol = operators.get(str(rule.operator), str(rule.operator))
    label = rule.label or str(rule.descriptor).replace("_", " ")
    if symbol == "between" and rule.value_upper is not None:
        body = f"{label} between {rule.value:g} and {rule.value_upper:g}"
    else:
        body = f"{label} {symbol} {rule.value:g}"
    return body if rule.required else f"{body} (recorded only)"


def _alert_policy_sentence(label: str, count: int, policy: Any) -> str:
    noun = "compound" if count == 1 else "compounds"
    effect = _ALERT_POLICY_EFFECT.get(str(policy), f"policy {policy} was recorded")
    return f"{label} alerts matched {count} {noun}; {effect}."


def _join(items: list[str]) -> str:
    if len(items) == 1:
        return items[0]
    return f"{', '.join(items[:-1])} and {items[-1]}"


def _scientific(value: Any) -> str:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return str(value)
    if number >= 1_000_000 and number % 100_000 == 0:
        return f"{number / 1_000_000:g} × 10⁶"
    return f"{number:,}"


def _load(loader: Any, identifier: str) -> Any:
    """A record that has been deleted becomes a hole, not an exception."""
    try:
        return loader(identifier)
    except (AnkoraDomainError, OSError, ValueError):
        return None


def _load2(loader: Any, first: str, second: str) -> Any:
    try:
        return loader(first, second)
    except (AnkoraDomainError, OSError, ValueError):
        return None
