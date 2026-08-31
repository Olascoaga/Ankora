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
* **Reproducibility is stated as it was measured.** AutoDock-GPU does not
  reproduce a run from its seeds, so its Methods says so rather than listing
  seeds as if they settled it.
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
from ankora_backend.schemas.results_catalog import CatalogEntry, ScoringFamily
from ankora_backend.services.result_catalog import (
    AUTODOCK4_BATCH,
    AUTODOCK4_JOB,
    AUTODOCK_GPU_BATCH,
    AUTODOCK_GPU_JOB,
    ResultCatalogService,
)

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
_ALERT_POLICY = {
    "review": "flagged for review",
    "exclude": "excluded",
    "ignore": "not applied",
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
            draft.say(
                "A single ligand was docked; no compound library was screened.\n"
            )
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
            "Compounds matching PAINS and Brenk structural alerts were "
            f"{_ALERT_POLICY.get(str(plan.pains_policy), str(plan.pains_policy))} "
            "and "
            f"{_ALERT_POLICY.get(str(plan.brenk_policy), str(plan.brenk_policy))} "
            f"respectively ({summary.pains_match_count} and "
            f"{summary.brenk_match_count} compounds matched); exact "
            "canonical-SMILES duplicates were "
            f"{_DUPLICATE_POLICY.get(str(plan.duplicate_policy), str(plan.duplicate_policy))} "
            f"({summary.duplicate_count} found)."
        )
        if summary.needs_decision_count:
            draft.say(
                f"{summary.needs_decision_count} compounds required an explicit "
                "chemical-state decision (undefined stereochemistry or multiple "
                "fragments) and were not included unless resolved."
            )
        draft.say(
            f"Of {summary.imported_count} compounds evaluated, "
            f"{summary.eligible_count} met every required criterion and "
            f"{summary.excluded_count} were excluded. "
            f"{entry.selected_count} compounds were carried forward to docking."
        )
        self._preparation(draft, entry)
        draft.say("")

    def _preparation(self, draft: _Draft, entry: CatalogEntry) -> None:
        """Read one prepared compound rather than describe the pipeline.

        Ankora always minimizes and converts, but the force field, the
        iteration budget and the Meeko version are decisions this campaign
        recorded, and a Methods section that recited the pipeline instead
        would be describing the software, not the experiment.
        """
        sample = _sample_preparation(self._ligands, self._record(entry))
        if sample is None:
            draft.say(
                "How the selected compounds were converted to three-dimensional "
                "structures is "
                f"{draft.missing('ligand conformer and PDBQT records')}."
            )
            return
        conformer, pdbqt = sample
        minimization = conformer.minimization
        embedding = (
            f" from coordinates generated with {minimization.embedding_method}"
            if minimization.embedding_method
            else ""
        )
        draft.say(
            "Each selected compound was converted to a three-dimensional "
            f"conformer{embedding} and energy-minimized with the "
            f"{minimization.force_field} force field "
            f"(up to {minimization.max_iterations} iterations)."
        )
        draft.tool(pdbqt.tool.name, pdbqt.tool.version, "ligand PDBQT conversion")
        draft.say(
            "Minimized conformers were written to PDBQT with "
            f"{pdbqt.tool.name} {pdbqt.tool.version}, applying "
            f"{str(pdbqt.charge_model).replace('_', ' ').title()} partial charges."
        )

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
        if entry.bitwise_reproducible:
            draft.say(
                "Repeating this campaign with the same inputs, protocol and "
                "seeds reproduces the reported values."
            )
        else:
            draft.say(
                "This backend does not reproduce a run from its seeds: repeating "
                "the campaign with identical inputs yields different rankings, "
                "so the reported values are those of the single recorded run. "
                "Cluster population is reported as the reproducibility evidence "
                "for each pose."
            )
        draft.say("")

    def _software_section(self, draft: _Draft) -> None:
        draft.say("## Software\n")
        if not draft.software:
            draft.say(f"{draft.missing('tool versions')}\n")
            return
        draft.say("| Software | Version | Role |")
        draft.say("| --- | --- | --- |")
        for item in sorted(draft.software.values(), key=lambda tool: tool.name):
            draft.say(f"| {item.name} | {item.version} | {item.role} |")
        draft.say("")
        draft.say(
            "*Citations for these tools are not generated by Ankora and must be "
            "added by the author.*"
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


def _sample_preparation(ligands: Any, record: Any) -> tuple[Any, Any] | None:
    """The preparation this campaign actually used, not one of the ligand's.

    Each campaign entry records the exact `ligand_preparation_id` that was
    docked. Looking a ligand's preparations up by hand would answer a
    different question - a compound can be prepared more than once, and only
    one of those runs is the protocol being written about.
    """
    for entry in getattr(record, "entries", []):
        preparation_id = getattr(entry, "ligand_preparation_id", None)
        if not preparation_id:
            continue
        pdbqt = _load2(ligands.load_pdbqt_record, entry.ligand_id, preparation_id)
        if pdbqt is None:
            continue
        conformer = _load2(
            ligands.load_conformer_record, entry.ligand_id,
            pdbqt.artifact.conformer_id,
        )
        if conformer is not None:
            return conformer, pdbqt
    return None


def _engine_identity(entry: CatalogEntry) -> tuple[str, str]:
    label = entry.engine_label.split(" · ")[-1]
    parts = label.rsplit(" ", 1)
    return (parts[0], parts[1]) if len(parts) == 2 else (label, entry.engine_version)


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
