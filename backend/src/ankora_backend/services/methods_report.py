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
* **An engine's score axes are never merged into one another.** GNINA returns a
  dimensionless CNN pose score, a predicted CNN affinity in pK and a minimized
  empirical affinity in kcal/mol. They are three quantities, they are reported
  as three quantities, and none of them is pooled with a Vina score or an
  AutoDock4 binding energy.
"""

import math
from dataclasses import dataclass, field
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any

from ankora_backend.domain.errors import AnkoraDomainError
from ankora_backend.persistence.artifact_store import StructureArtifactStore
from ankora_backend.persistence.autodock4_store import AutoDock4JobStore
from ankora_backend.persistence.autodock_gpu_store import AutoDockGpuJobStore
from ankora_backend.persistence.autogrid_store import AutoGridMapStore
from ankora_backend.persistence.binding_site_store import BindingSiteArtifactStore
from ankora_backend.persistence.docking_store import DockingArtifactStore
from ankora_backend.persistence.gnina_screening_store import GninaScreeningStore
from ankora_backend.persistence.gnina_store import GninaJobStore
from ankora_backend.persistence.ligand_store import LigandArtifactStore
from ankora_backend.persistence.pocket_detection_store import PocketDetectionArtifactStore
from ankora_backend.persistence.receptor_store import ReceptorArtifactStore
from ankora_backend.schemas.methods import MethodsReport, MethodsSoftware
from ankora_backend.schemas.results_catalog import (
    CatalogEntry,
    ReproducibilityStatus,
    ScoringFamily,
)
from ankora_backend.services.gnina_screening_evidence import verified_campaign_entry_job
from ankora_backend.services.gnina_screening_selection import verified_screening_selection
from ankora_backend.services.result_catalog import (
    AUTODOCK4_BATCH,
    AUTODOCK4_JOB,
    AUTODOCK_GPU_BATCH,
    AUTODOCK_GPU_JOB,
    GNINA_JOB,
    GNINA_SCREENING,
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
    "exclude": "excluded",
    "review": "flagged for review",
    "keep": "retained",
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
        self.software.setdefault(
            f"{name} {version}",
            MethodsSoftware(
                name=name,
                version=version,
                role=role,
            ),
        )


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


@dataclass(frozen=True)
class _Verified:
    """A record that may be described, or the reason it may not be.

    `record` is populated only when every hash the engine recorded still
    matches the stored artifact, so a caller cannot accidentally describe a
    preparation that was redone after the run it is writing about.
    """

    record: Any = None
    gap: str | None = None


@dataclass(frozen=True)
class _GninaInputs:
    receptor: _Verified = field(default_factory=lambda: _Verified(gap="the GNINA job record"))
    ligand: _Verified = field(default_factory=lambda: _Verified(gap="the GNINA job record"))


class MethodsReportService:
    def __init__(
        self,
        *,
        catalog: ResultCatalogService,
        structures: StructureArtifactStore,
        receptors: ReceptorArtifactStore,
        binding_sites: BindingSiteArtifactStore,
        pockets: PocketDetectionArtifactStore,
        ligands: LigandArtifactStore,
        maps: AutoGridMapStore,
        docking: DockingArtifactStore,
        autodock4: AutoDock4JobStore,
        autodock_gpu: AutoDockGpuJobStore,
        gnina: GninaJobStore | None = None,
        gnina_screening: GninaScreeningStore | None = None,
    ) -> None:
        self._catalog = catalog
        self._structures = structures
        self._receptors = receptors
        self._binding_sites = binding_sites
        self._pockets = pockets
        self._ligands = ligands
        self._maps = maps
        self._docking = docking
        self._autodock4 = autodock4
        self._autodock_gpu = autodock_gpu
        self._gnina = gnina
        self._gnina_screening = gnina_screening

    @classmethod
    def from_environment(cls) -> "MethodsReportService":
        return cls(
            catalog=ResultCatalogService.from_environment(),
            structures=StructureArtifactStore.from_environment(),
            receptors=ReceptorArtifactStore.from_environment(),
            binding_sites=BindingSiteArtifactStore.from_environment(),
            pockets=PocketDetectionArtifactStore.from_environment(),
            ligands=LigandArtifactStore.from_environment(),
            maps=AutoGridMapStore.from_environment(),
            docking=DockingArtifactStore.from_environment(),
            autodock4=AutoDock4JobStore.from_environment(),
            autodock_gpu=AutoDockGpuJobStore.from_environment(),
            gnina=GninaJobStore.from_environment(),
            gnina_screening=GninaScreeningStore.from_environment(),
        )

    def render(self, catalog_id: str) -> MethodsReport:
        entry = self._catalog.get_campaign(catalog_id)
        draft = _Draft()

        if entry.engine_key == GNINA_JOB:
            self._gnina_sections(draft, entry)
        elif entry.engine_key == GNINA_SCREENING:
            self._gnina_screening_sections(draft, entry)
        else:
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

    # --- GNINA ------------------------------------------------------------

    def _gnina_sections(self, draft: _Draft, entry: CatalogEntry) -> None:
        """A GNINA single job, described from its own record and nothing else.

        GNINA's record is self-contained in a way the other engines' are not:
        it stores the box it actually searched and the SHA-256 of every input
        it was handed. That makes a stronger guarantee available here than
        elsewhere, so this path takes it — a preparation is described only when
        the stored artifact still hashes to what GNINA was given. A receptor
        prepared again since the run is a different receptor, and describing it
        would put a protocol in the Methods section that did not produce these
        numbers.
        """
        job = self._gnina_job(entry)
        inputs = self._gnina_inputs(job)

        self._gnina_protein(draft, job, inputs)
        self._gnina_site(draft, entry, job)
        self._gnina_ligand(draft, job, inputs)
        self._gnina_docking(draft, entry, job, inputs)
        self._gnina_outcome(draft, entry, job)

    def _gnina_job(self, entry: CatalogEntry) -> Any:
        if self._gnina is None:
            return None
        return _load(self._gnina.load_job, entry.record_id)

    def _gnina_inputs(self, job: Any) -> "_GninaInputs":
        """Resolve each input only as far as its recorded hash still matches."""
        if job is None:
            return _GninaInputs()
        return _GninaInputs(
            receptor=self._gnina_receptor(job),
            ligand=self._gnina_ligand_preparation(job),
        )

    def _gnina_receptor(self, job: Any) -> "_Verified":
        receptor = _load(self._receptors.load_record, job.request.receptor_id)
        if receptor is None:
            return _Verified(gap="the receptor preparation record for this GNINA job")
        output = next(
            (
                item
                for item in getattr(receptor, "outputs", [])
                if item.artifact_id == job.receptor_output_artifact_id
            ),
            None,
        )
        if output is None:
            return _Verified(
                gap="the prepared receptor artifact GNINA was given, in the receptor record"
            )
        stored = _stored_digest(
            self._receptors.content_path, job.request.receptor_id, output.artifact_id
        )
        if stored is None:
            return _Verified(gap="readable stored bytes for the prepared receptor GNINA was given")
        if stored != job.receptor_sha256 or output.sha256 != job.receptor_sha256:
            return _Verified(
                gap=("a prepared receptor whose stored bytes still match the hash GNINA recorded")
            )
        return _Verified(record=receptor)

    def _gnina_ligand_preparation(self, job: Any) -> "_Verified":
        request = job.request
        pdbqt = _load2(
            self._ligands.load_pdbqt_record, request.ligand_id, request.ligand_preparation_id
        )
        if pdbqt is None:
            return _Verified(gap="the prepared ligand record for this GNINA job")
        if getattr(pdbqt.artifact, "ligand_id", request.ligand_id) != request.ligand_id:
            return _Verified(gap="a prepared ligand record belonging to the docked ligand")
        ligand_bytes = _stored_digest(
            self._ligands.pdbqt_content_path, request.ligand_id, request.ligand_preparation_id
        )
        if ligand_bytes is None:
            return _Verified(gap="readable stored bytes for the prepared ligand GNINA was given")
        if ligand_bytes != job.ligand_sha256 or pdbqt.artifact.sha256 != job.ligand_sha256:
            return _Verified(
                gap=("a prepared ligand whose stored bytes still match the hash GNINA recorded")
            )
        conformer = _load2(
            self._ligands.load_conformer_record, request.ligand_id, pdbqt.artifact.conformer_id
        )
        if conformer is None:
            return _Verified(gap="the conformer record behind this GNINA job's prepared ligand")
        conformer_bytes = _stored_digest(
            self._ligands.conformer_content_path, request.ligand_id, pdbqt.artifact.conformer_id
        )
        if conformer_bytes is None:
            return _Verified(gap="readable stored bytes for the conformer GNINA was given")
        if (
            conformer_bytes != job.conformer_sha256
            or conformer.artifact.sha256 != job.conformer_sha256
        ):
            return _Verified(
                gap=("a conformer whose stored bytes still match the hash GNINA recorded")
            )
        return _Verified(record=(pdbqt, conformer))

    def _gnina_protein(self, draft: _Draft, job: Any, inputs: "_GninaInputs") -> None:
        draft.say("## Protein preparation\n")
        if job is None:
            draft.say(
                "The GNINA job record for this result is no longer available, so no "
                "receptor preparation can be described. "
                f"{draft.missing('the GNINA job record')}\n"
            )
            return
        receptor = inputs.receptor
        if receptor.record is None:
            draft.say(
                "Ankora describes a receptor preparation only when the stored artifact "
                "still matches the hash GNINA was given. That check did not pass here, "
                f"so the preparation is not described: {draft.missing(receptor.gap or '')}\n"
            )
            return
        draft.say(
            "The receptor GNINA received is the prepared PDBQT identified by SHA-256 "
            f"{job.receptor_sha256}, which still matches the stored artifact."
        )
        self._protein_prose(draft, receptor.record)

    def _gnina_site(
        self,
        draft: _Draft,
        entry: CatalogEntry,
        job: Any,
        *,
        record_noun: str = "docking job",
    ) -> None:
        short_noun = "job" if record_noun == "docking job" else record_noun
        draft.say("## Binding site definition\n")
        if job is None:
            draft.say(
                f"The search space cannot be stated without the {short_noun} record. "
                f"{draft.missing('the recorded GNINA search box')}\n"
            )
            return

        box = job.box
        draft.say(
            f"The search box recorded on the {record_noun} itself was centred at "
            f"({box.center_x}, {box.center_y}, {box.center_z}) Å with "
            f"dimensions {box.size_x} × {box.size_y} × {box.size_z} Å, in "
            "the coordinate frame of the prepared receptor. These are the values "
            "GNINA was given, taken from the run's own record rather than from the "
            "binding-site artifact, which can be superseded after a run."
        )

        site = _load(self._binding_sites.load_record, job.request.binding_site_id)
        if site is None:
            draft.say(
                "How that box was originally derived is "
                f"{draft.missing(f'the binding site record for this GNINA {short_noun}')}.\n"
            )
            return
        if site.receptor_id != job.request.receptor_id or not _same_box(site.box, box):
            inconsistent = draft.missing(
                "a binding site record consistent with the recorded GNINA box"
            )
            draft.say(
                f"The binding-site artifact this {short_noun} names no longer describes the same "
                f"receptor and box, so its derivation is not used here: {inconsistent}.\n"
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
        draft.say(f"That box was defined from {source}{detail}.")
        if entry.map_set_id:
            # GNINA scores from the structures themselves. A map set on the entry
            # would mean a record from another engine's pipeline reached this one.
            draft.say(
                "No precomputed affinity grid maps were used; GNINA scores directly "
                "from the prepared structures."
            )
        draft.say("")

    def _gnina_ligand(self, draft: _Draft, job: Any, inputs: "_GninaInputs") -> None:
        draft.say("## Ligand preparation\n")
        if job is None:
            draft.say(
                "No ligand preparation can be described without the job record. "
                f"{draft.missing('the GNINA prepared ligand identity')}\n"
            )
            return
        draft.say(
            "A single ligand was docked; no compound library was screened."
            if _gnina_executed(job)
            else "The job was configured for a single ligand, not a compound library."
        )
        ligand = inputs.ligand
        if ligand.record is None:
            draft.say(
                "Ankora describes a ligand preparation only when the stored conformer "
                "and PDBQT still match the hashes GNINA was given. That check did not "
                "pass here, so the preparation is not described: "
                f"{draft.missing(ligand.gap or '')}\n"
            )
            return

        pdbqt, conformer = ligand.record
        protocol = _protocol_from(pdbqt, conformer)
        draft.tool(
            protocol.conformer_tool_name,
            protocol.conformer_tool_version,
            "ligand conformer generation and minimization",
        )
        draft.tool(protocol.pdbqt_tool_name, protocol.pdbqt_tool_version, "ligand PDBQT conversion")
        lineage = _state_lineage(self._ligands, job.request.ligand_id, conformer)
        if lineage is not None:
            for decision in lineage.decisions:
                draft.tool(
                    decision.tool_name, decision.tool_version, "ligand chemical-state resolution"
                )
        draft.say(
            "The prepared ligand PDBQT and its conformer still match the hashes GNINA "
            f"recorded ({job.ligand_sha256} and {job.conformer_sha256})."
        )
        draft.say(_single_preparation_sentence(protocol))
        _chemical_state_prose(
            draft,
            _PreparationSet(
                items=[
                    _PreparedLigand(
                        ligand_id=job.request.ligand_id,
                        preparation_id=job.request.ligand_preparation_id,
                        conformer=conformer,
                        pdbqt=pdbqt,
                        protocol=protocol,
                        state_lineage=lineage,
                    )
                ],
                total_entries=1,
                entries_without_preparation=0,
                unavailable_preparations=0,
            ),
            single=True,
        )
        draft.say("")

    def _gnina_docking(
        self, draft: _Draft, entry: CatalogEntry, job: Any, inputs: "_GninaInputs"
    ) -> None:
        draft.say("## Molecular docking\n")
        if job is None:
            draft.say(
                "The docking parameters for this job are "
                f"{draft.missing('the GNINA request parameters')}.\n"
            )
            return

        executed = _gnina_executed(job)
        tool = job.tool
        draft.tool("GNINA", tool.version, "molecular docking")
        identity = (
            f"GNINA {tool.version}, a native {tool.architecture} Linux build "
            f"identified by executable SHA-256 {tool.sha256}"
        )
        if executed:
            draft.say(f"Docking was performed with {identity}.")
        else:
            draft.say(
                f"This job was configured for {identity}. It did not complete a "
                "successful run, so this section states the configuration that was "
                "recorded rather than a protocol that produced results."
            )

        parameters = job.request.parameters
        search = (
            f"a fixed random seed of {parameters.seed}, an exhaustiveness of "
            f"{parameters.exhaustiveness}, at most {parameters.num_modes} binding mode"
            f"{'s' if parameters.num_modes != 1 else ''}, and a minimum inter-mode "
            f"RMSD filter of {parameters.min_rmsd_filter_angstrom:g} Å"
        )
        draft.say(
            f"The search used {search}."
            if executed
            else f"The recorded search configuration specified {search}."
        )
        scoring = (
            f"scoring mode `{parameters.cnn_scoring}` with the engine's built-in "
            f"`{parameters.cnn_model}` model"
        )
        draft.say(
            (
                f"Pose scoring used the recorded GNINA CNN configuration: {scoring}."
                if executed
                else f"Pose scoring was configured as {scoring}."
            )
            + " The mode and model are reported as recorded."
        )
        if executed:
            draft.say(
                "Receptor and ligand were supplied as independently prepared PDBQT "
                "files, and GNINA was run with both hydrogen addition and hydrogen "
                "stripping disabled, so the engine neither added nor removed hydrogens "
                "from the prepared inputs."
            )
        else:
            draft.say(
                "The configuration supplies receptor and ligand as independently "
                "prepared PDBQT files with both hydrogen addition and hydrogen "
                "stripping disabled, so the engine would neither add nor remove "
                "hydrogens from the prepared inputs."
            )
        # Only claimable once both inputs were verified against their stored bytes;
        # otherwise Ankora does not know which protonation the engine received.
        if inputs.receptor.record is not None and inputs.ligand.record is not None:
            draft.say(
                "The protonation those inputs carry is the one recorded in their own preparation."
            )
        draft.say(_gnina_compute_prose(parameters, executed=executed))
        if parameters.compute == "cuda":
            if job.execution is None:
                # Nothing launched, so there is no observation to miss.
                draft.say(
                    "No GNINA execution was recorded for this job, so there is no GPU "
                    "process observation to report."
                )
            else:
                observation = _gnina_gpu_observation(job.execution)
                if observation is None:
                    draft.say(
                        "The recorded execution carries no GPU process observation, so "
                        "execution on the selected device is "
                        f"{draft.missing('recorded GNINA GPU process observation')}."
                    )
                else:
                    draft.say(observation)
        if entry.device_name and entry.device_name != _gnina_observed_uuid(job.execution):
            draft.say(
                "The catalog device label and the job's own GPU observation disagree, so "
                "the device is reported only as the job recorded it: "
                f"{draft.missing('a single consistent recorded GNINA device identity')}."
            )
        draft.say("")

    def _gnina_outcome(self, draft: _Draft, entry: CatalogEntry, job: Any) -> None:
        draft.say("## Results and reproducibility\n")
        if job is None:
            draft.say(
                "No outcome can be reported without the job record. "
                f"{draft.missing('the recorded GNINA outcome')}\n"
            )
            return

        status = _text(job.status)
        poses = list(job.poses)
        if status != "completed" or not poses:
            draft.say(_gnina_unfinished_prose(status, job.failure))
            draft.say(
                "No CNN score, affinity prediction or pose is reported for this job, "
                "because its record holds none."
            )
            draft.say("")
            return

        top = poses[0]
        draft.say(
            f"One ligand was docked and GNINA returned {len(poses)} pose"
            f"{'s' if len(poses) != 1 else ''}, retained in the order the engine "
            "produced them."
        )
        draft.say(
            "Poses are ordered by descending CNN pose score, which is the engine's own "
            "ranking. The CNN pose score is dimensionless and bounded between 0 and 1; a "
            "higher value ranks a pose earlier. It is not an energy and has no kcal/mol "
            "interpretation."
        )
        draft.say(
            "Ankora records two further quantities per pose and keeps them distinct from "
            "that ranking and from each other:"
        )
        draft.say(
            "- the CNN affinity prediction, in pK units, where a higher value means a "
            "stronger predicted affinity;"
        )
        draft.say(
            "- the minimized affinity from GNINA's empirical scoring function, in "
            "kcal mol⁻¹, where a more negative value means a more favourable predicted "
            "interaction."
        )
        draft.say(
            f"For the top-ranked pose these were a CNN pose score of {top.cnn_score:g}, a "
            f"predicted CNN affinity of {top.cnn_affinity:g} pK, and a minimized affinity "
            f"of {top.minimized_affinity_kcal_mol:g} kcal mol⁻¹. The ranking did not use "
            "the minimized affinity, so the top-ranked pose is not necessarily the one "
            "with the lowest recorded energy."
        )
        top_cnn_vs = getattr(top, "cnn_vs", None)
        if top_cnn_vs is not None:
            vs_origin = (
                "emitted directly by GNINA"
                if getattr(top, "cnn_vs_source", None) == "engine_emitted"
                else "derived from the recorded CNN pose score and CNN affinity axes"
            )
            draft.say(
                f"Ankora also recorded a virtual-screening score (`CNN_VS = CNNscore × "
                f"CNNaffinity`, {vs_origin}) of {top_cnn_vs:g} for the top-ranked pose; "
                "within-ligand pose ordering remained descending CNN pose score."
            )
        draft.say(
            "All of these GNINA quantities are predictions of this engine for this pose. "
            "None is a measured binding affinity and none is evidence of biological activity."
        )
        draft.say(
            "They come from GNINA's own empirical function and convolutional model, and "
            "they do not share a scale with the score of any other docking engine. Ankora "
            "does not pool or jointly rank results across engines."
        )
        self._reproducibility_prose(draft, entry)
        draft.say("")

    def _gnina_screening_sections(self, draft: _Draft, entry: CatalogEntry) -> None:
        """A multi-ligand GNINA screening campaign, verified across every input and child job."""
        campaign = self._gnina_screening_campaign(entry)
        receptor = (
            self._gnina_receptor(campaign)
            if campaign is not None
            else _Verified(gap="the GNINA screening campaign record")
        )
        verified_jobs, job_verification_failed = self._gnina_screening_verified_jobs(campaign)

        self._gnina_screening_protein(draft, campaign, receptor)
        self._gnina_site(draft, entry, campaign, record_noun="screening campaign")
        ligands_verified = self._gnina_screening_ligands(draft, campaign)
        self._gnina_screening_docking(
            draft,
            entry,
            campaign,
            verified_jobs,
            job_verification_failed=job_verification_failed,
            receptor_verified=receptor.record is not None,
            ligands_verified=ligands_verified,
        )
        self._gnina_screening_outcome(
            draft,
            entry,
            campaign,
            verified_jobs,
            job_verification_failed=job_verification_failed,
        )

    def _gnina_screening_campaign(self, entry: CatalogEntry) -> Any:
        if self._gnina_screening is None:
            return None
        return _load(self._gnina_screening.load_campaign, entry.record_id)

    def _gnina_screening_job_store(self) -> GninaJobStore | None:
        if self._gnina is not None:
            return self._gnina
        if self._gnina_screening is not None:
            return self._gnina_screening.jobs
        return None

    def _gnina_screening_verified_jobs(self, campaign: Any) -> tuple[dict[str, Any], bool]:
        if campaign is None:
            return {}, False
        job_store = self._gnina_screening_job_store()
        verified: dict[str, Any] = {}
        failed_verification = False
        for item in campaign.entries:
            if _text(item.status) != "completed":
                continue
            if job_store is None:
                failed_verification = True
                continue
            try:
                verified[item.ligand_id] = verified_campaign_entry_job(
                    store=job_store,
                    campaign=campaign,
                    entry=item,
                )
            except (AnkoraDomainError, OSError, ValueError):
                failed_verification = True
        return verified, failed_verification

    def _gnina_screening_protein(
        self, draft: _Draft, campaign: Any, receptor: "_Verified"
    ) -> None:
        draft.say("## Protein preparation\n")
        if campaign is None:
            draft.say(
                "The GNINA screening campaign record for this result is no longer "
                "available, so no receptor preparation can be described. "
                f"{draft.missing('the GNINA screening campaign record')}\n"
            )
            return
        if receptor.record is None:
            draft.say(
                "Ankora describes a receptor preparation only when the stored artifact "
                "still matches the hash GNINA was given. That check did not pass here, "
                f"so the preparation is not described: {draft.missing(receptor.gap or '')}\n"
            )
            return
        draft.say(
            "The receptor GNINA received across this screening campaign is the prepared "
            f"PDBQT identified by SHA-256 {campaign.receptor_sha256}, which still matches "
            "the stored artifact."
        )
        self._protein_prose(draft, receptor.record)

    def _gnina_screening_ligands(self, draft: _Draft, campaign: Any) -> bool:
        draft.say("## Ligand preparation\n")
        if campaign is None:
            draft.say(
                "No compound library or ligand preparation can be described without the "
                "screening campaign record. "
                f"{draft.missing('the GNINA screening ligand selection')}\n"
            )
            return False

        library = _load(self._ligands.load_library_record, campaign.selection.library_id)
        if library is None:
            draft.say(
                "The compound library record for this screening campaign is no longer "
                f"available. {draft.missing('compound library record')}"
            )
        else:
            artifact = library.artifact
            draft.say(
                f"{artifact.record_count} compounds were imported from "
                f"{artifact.filename} ({artifact.format.upper()}); "
                f"{library.imported_count} were parsed successfully and "
                f"{library.failed_count} could not be read."
            )

        run = _verified_gnina_selection_run(self._ligands, campaign)
        if run is None:
            manifest_gap = draft.missing(
                "a verified library filter selection manifest matching the recorded GNINA campaign"
            )
            draft.say(
                "Ankora describes library filtering for a GNINA screening campaign only "
                "when the stored selection manifest still matches the SHA-256 hash and "
                "selection order pinned on the campaign. That check did not pass here, so "
                f"the filter protocol is not described: {manifest_gap}."
            )
        else:
            _gnina_filter_run_prose(
                draft,
                run,
                selected_count=campaign.selected_count,
                manifest_sha256=campaign.selection.manifest_sha256,
            )

        ligands_verified = self._gnina_screening_preparations(draft, campaign)
        draft.say("")
        return ligands_verified

    def _gnina_screening_preparations(self, draft: _Draft, campaign: Any) -> bool:
        preflight_unprepared = [
            item
            for item in campaign.entries
            if item.is_preflight_failure
            and (
                item.ligand_preparation_id is None
                or item.ligand_sha256 is None
                or item.conformer_id is None
                or item.conformer_sha256 is None
            )
        ]
        recorded_entries = [
            item for item in campaign.entries if item not in preflight_unprepared
        ]
        if preflight_unprepared:
            count = len(preflight_unprepared)
            draft.say(
                f"{count} selected compound{'s' if count != 1 else ''} lacked a verified "
                f"docking-ready preparation at preflight and {'were' if count != 1 else 'was'} "
                "recorded as failed without launching GNINA."
            )
        if not recorded_entries:
            return False

        verified_items: list[_PreparedLigand] = []
        for item in recorded_entries:
            prepared = _gnina_entry_preparation(self._ligands, item)
            if prepared is not None:
                verified_items.append(prepared)
        unverified_count = len(recorded_entries) - len(verified_items)
        if unverified_count:
            prep_gap = draft.missing(
                "verified ligand conformer and PDBQT artifacts for every recorded "
                "GNINA screening entry"
            )
            draft.say(
                "Ankora describes ligand preparations only when stored conformer and "
                "PDBQT bytes still match the SHA-256 hashes recorded by the campaign; "
                f"{len(verified_items)} of {len(recorded_entries)} recorded ligand "
                f"preparations passed verification: {prep_gap}."
            )
        if not verified_items:
            return False

        for prepared in verified_items:
            protocol = prepared.protocol
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
            if prepared.state_lineage is not None:
                for decision in prepared.state_lineage.decisions:
                    draft.tool(
                        decision.tool_name,
                        decision.tool_version,
                        "ligand chemical-state resolution",
                    )

        groups: dict[_PreparationProtocol, int] = {}
        for prepared in verified_items:
            groups[prepared.protocol] = groups.get(prepared.protocol, 0) + 1
        if len(groups) == 1:
            protocol, count = next(iter(groups.items()))
            prefix = "All" if unverified_count == 0 else "The"
            draft.say(
                f"{prefix} {count} verified ligand preparation"
                f"{'s' if count != 1 else ''} used {_protocol_description(protocol)}."
            )
        else:
            draft.say(
                f"The {len(verified_items)} verified ligand preparations used "
                f"{len(groups)} distinct recorded protocols:"
            )
            for protocol, count in sorted(
                groups.items(), key=lambda pair: (_protocol_description(pair[0]), pair[1])
            ):
                draft.say(
                    f"- {count} ligand{'s' if count != 1 else ''}: "
                    f"{_protocol_description(protocol)}."
                )

        _chemical_state_prose(
            draft,
            _PreparationSet(
                items=verified_items,
                total_entries=len(verified_items),
                entries_without_preparation=0,
                unavailable_preparations=0,
            ),
            single=False,
        )
        return unverified_count == 0

    def _gnina_screening_docking(
        self,
        draft: _Draft,
        entry: CatalogEntry,
        campaign: Any,
        verified_jobs: dict[str, Any],
        *,
        job_verification_failed: bool,
        receptor_verified: bool,
        ligands_verified: bool,
    ) -> None:
        draft.say("## Molecular docking\n")
        if campaign is None:
            draft.say(
                "The docking parameters for this screening campaign are "
                f"{draft.missing('the GNINA screening request parameters')}.\n"
            )
            return

        executed = (
            not job_verification_failed
            and campaign.succeeded_count > 0
            and len(verified_jobs) == campaign.succeeded_count
            and all(_gnina_executed(job) for job in verified_jobs.values())
        )
        tool = campaign.tool
        draft.tool("GNINA", tool.version, "molecular docking")
        identity = (
            f"GNINA {tool.version}, a native {tool.architecture} Linux build "
            f"identified by executable SHA-256 {tool.sha256}"
        )
        if executed:
            draft.say(
                f"Library screening was performed with {identity}. Prepared compounds "
                f"were docked sequentially (worker_count = {campaign.worker_count}), "
                "executing one independent GNINA single-ligand job per entry in selection "
                "order without concurrent scheduling."
            )
        else:
            draft.say(
                f"This screening campaign was configured for {identity} with sequential "
                f"execution (worker_count = {campaign.worker_count}, one independent "
                "GNINA job per prepared entry in selection order). Because a complete "
                "verified run set is not available, this section states the recorded "
                "configuration rather than a completed campaign protocol."
            )

        parameters = campaign.request.parameters
        search = (
            f"a fixed random seed of {parameters.seed}, an exhaustiveness of "
            f"{parameters.exhaustiveness}, at most {parameters.num_modes} binding mode"
            f"{'s' if parameters.num_modes != 1 else ''} per compound, and a minimum "
            f"inter-mode RMSD filter of {parameters.min_rmsd_filter_angstrom:g} Å"
        )
        draft.say(
            f"Each docking job used {search}."
            if executed
            else f"The recorded search configuration specified {search}."
        )
        scoring = (
            f"scoring mode `{parameters.cnn_scoring}` with the engine's built-in "
            f"`{parameters.cnn_model}` model"
        )
        draft.say(
            (
                f"Pose scoring used the recorded GNINA CNN configuration: {scoring}."
                if executed
                else f"Pose scoring was configured as {scoring}."
            )
            + " The mode and model are reported as recorded."
        )
        if executed:
            draft.say(
                "Receptor and ligands were supplied as independently prepared PDBQT "
                "files, and GNINA was run with both hydrogen addition and hydrogen "
                "stripping disabled, so the engine neither added nor removed hydrogens "
                "from the prepared inputs."
            )
        else:
            draft.say(
                "The configuration supplies receptor and ligands as independently "
                "prepared PDBQT files with both hydrogen addition and hydrogen "
                "stripping disabled, so the engine would neither add nor remove "
                "hydrogens from the prepared inputs."
            )
        if receptor_verified and ligands_verified:
            draft.say(
                "The protonation those inputs carry is the one recorded in their own preparation."
            )
        draft.say(_gnina_compute_prose(parameters, executed=executed))
        if parameters.compute == "cuda":
            self._gnina_screening_gpu_prose(
                draft,
                entry,
                campaign,
                verified_jobs,
                job_verification_failed=job_verification_failed,
            )
        draft.say("")

    def _gnina_screening_gpu_prose(
        self,
        draft: _Draft,
        entry: CatalogEntry,
        campaign: Any,
        verified_jobs: dict[str, Any],
        *,
        job_verification_failed: bool,
    ) -> None:
        if campaign.succeeded_count == 0 and not verified_jobs:
            draft.say(
                "No completed GNINA execution was recorded for this campaign, so there "
                "is no GPU process observation to report."
            )
            return
        if job_verification_failed or len(verified_jobs) < campaign.succeeded_count:
            gpu_gap = draft.missing(
                "recorded GNINA GPU process observation for every completed screening entry"
            )
            draft.say(
                "Because not all completed child GNINA job records passed verification, "
                f"GPU process observation across the campaign is {gpu_gap}."
            )
            return
        observed_uuids: list[str] = []
        requested_uuids: set[str] = set()
        for job in verified_jobs.values():
            execution = getattr(job, "execution", None)
            observed = _gnina_observed_uuid(execution)
            if (
                execution is None
                or not getattr(execution, "gpu_process_observed", False)
                or not observed
            ):
                draft.say(
                    "At least one completed child execution carries no GPU process "
                    "observation, so execution on the selected device across the "
                    f"campaign is {draft.missing('recorded GNINA GPU process observation')}."
                )
                return
            observed_uuids.append(observed)
            requested = getattr(execution, "requested_gpu_uuid", None)
            if requested:
                requested_uuids.add(requested)

        unique_observed = sorted(set(observed_uuids))
        count = len(observed_uuids)
        if len(unique_observed) == 1:
            device = unique_observed[0]
            sentence = (
                f"Ankora observed the GNINA process in all {count} completed child "
                f"execution{'s' if count != 1 else ''} occupying GPU {device}"
            )
            if len(requested_uuids) == 1:
                requested_only = next(iter(requested_uuids))
                sentence += (
                    f", the device requested for this campaign ({requested_only})"
                    if requested_only == device
                    else f", while the device requested for this campaign was {requested_only}"
                )
        else:
            sentence = (
                f"Ankora observed the GNINA processes across {count} completed child "
                f"executions occupying GPUs {_join(unique_observed)}"
            )
        draft.say(
            f"{sentence}. This confirms that each engine process was reported on the "
            "observed device; it is not independent proof that every neural-network "
            "operation executed on the GPU."
        )
        if entry.device_name and (
            len(unique_observed) != 1 or entry.device_name != unique_observed[0]
        ):
            device_gap = draft.missing("a single consistent recorded GNINA device identity")
            draft.say(
                "The catalog device label and the child jobs' GPU observations disagree, "
                f"so the device is reported only from the verified job records: {device_gap}."
            )

    def _gnina_screening_outcome(
        self,
        draft: _Draft,
        entry: CatalogEntry,
        campaign: Any,
        verified_jobs: dict[str, Any],
        *,
        job_verification_failed: bool,
    ) -> None:
        draft.say("## Results and reproducibility\n")
        if campaign is None:
            draft.say(
                "No outcome can be reported without the screening campaign record. "
                f"{draft.missing('the recorded GNINA screening outcome')}\n"
            )
            return

        preflight_failures = sum(1 for item in campaign.entries if item.is_preflight_failure)
        engine_failures = campaign.failed_count - preflight_failures
        failure_detail = ""
        if campaign.failed_count:
            failure_detail = (
                f" ({preflight_failures} refused at preflight before launching GNINA "
                f"and {engine_failures} failed during docking)"
            )
        canceled_clause = (
            f", and {campaign.canceled_count} were canceled"
            if campaign.canceled_count
            else ""
        )
        draft.say(
            f"{campaign.selected_count} selected compound entries were evaluated in "
            f"selection order: {campaign.succeeded_count} completed with poses, "
            f"{campaign.failed_count} failed{failure_detail}{canceled_clause}."
        )
        if job_verification_failed:
            jobs_gap = draft.missing(
                "verified child GNINA jobs and pose artifacts for every completed screening entry"
            )
            draft.say(
                "One or more completed child GNINA job records or pose artifacts no "
                "longer match the hashes recorded for this campaign, so campaign scores "
                f"and rankings are not reported: {jobs_gap}.\n"
            )
            return

        status = _text(campaign.status)
        if status != "completed" or campaign.succeeded_count == 0 or not verified_jobs:
            described = _GNINA_UNFINISHED.get(status, f"has the recorded status `{status}`")
            sentence = f"This GNINA screening campaign {described}."
            code = getattr(campaign.failure, "code", None)
            if code:
                message = str(getattr(campaign.failure, "message", "") or "").rstrip(".")
                sentence += f" The recorded campaign failure was {code}"
                sentence += f": {message}." if message else "."
            draft.say(sentence)
            draft.say(
                "Campaign-level hit ranking is reported only for completed campaigns; "
                "any partial child jobs remain individually inspectable from their own "
                "verified records."
            )
            draft.say("")
            return

        rank_by_cnn_vs = getattr(campaign, "hit_ranking_metric", "cnn_score") == "cnn_vs"
        ranked_completed: list[tuple[int, Any, Any]] = []
        for selection_index, item in enumerate(campaign.entries):
            if _text(item.status) != "completed":
                continue
            job = verified_jobs.get(item.ligand_id)
            if job is not None and job.poses:
                ranked_completed.append((selection_index, item, job.poses[0]))
        if rank_by_cnn_vs:
            ranked_completed.sort(
                key=lambda row: (
                    -(
                        row[2].cnn_vs
                        if getattr(row[2], "cnn_vs", None) is not None
                        else row[2].cnn_score * row[2].cnn_affinity
                    ),
                    row[0],
                )
            )
        else:
            ranked_completed.sort(key=lambda row: (-row[2].cnn_score, row[0]))
        _, best_item, best_pose = ranked_completed[0]
        best_label = best_item.name or best_item.ligand_id
        best_cnn_vs = getattr(best_pose, "cnn_vs", None)

        if rank_by_cnn_vs:
            effective_best_vs = (
                best_cnn_vs
                if best_cnn_vs is not None
                else best_pose.cnn_score * best_pose.cnn_affinity
            )
            draft.say(
                "Completed compounds are prioritized across the campaign by descending "
                "top-pose `CNN_VS` (`CNNscore × CNNaffinity`), with exact ties broken by "
                "applied selection order, while poses within each individual ligand job "
                "remain ordered by descending CNN pose score. The CNN pose score is "
                "dimensionless and bounded between 0 and 1; `CNN_VS` weights that pose "
                "confidence by predicted affinity in pK units. Neither is an energy in "
                "kcal/mol."
            )
            draft.say(
                "Ankora records each underlying GNINA quantity separately alongside `CNN_VS`:"
            )
            draft.say(
                "- the CNN affinity prediction, in pK units, where a higher value means a "
                "stronger predicted affinity;"
            )
            draft.say(
                "- the minimized affinity from GNINA's empirical scoring function, in "
                "kcal mol⁻¹, where a more negative value means a more favourable predicted "
                "interaction."
            )
            draft.say(
                f"The top-ranked compound ({best_label}) had a top-pose `CNN_VS` of "
                f"{effective_best_vs:g} (CNN pose score {best_pose.cnn_score:g} and "
                f"predicted CNN affinity {best_pose.cnn_affinity:g} pK) and a minimized "
                f"affinity of {best_pose.minimized_affinity_kcal_mol:g} kcal mol⁻¹. "
                "Campaign ranking did not use the minimized affinity, so the highest-ranked "
                "compound is not necessarily the one with the lowest recorded energy."
            )
            nonpositive_count = sum(
                1 for _, _, pose in ranked_completed if pose.cnn_affinity <= 0.0
            )
            has_sign_warning = nonpositive_count > 0 or any(
                str(getattr(warning, "code", "")) == "GNINA_CNN_VS_NONPOSITIVE_AFFINITY"
                for warning in getattr(campaign, "warnings", ())
            )
            if has_sign_warning:
                draft.say(
                    f"Sign-ambiguity note (`GNINA_CNN_VS_NONPOSITIVE_AFFINITY`): "
                    f"{nonpositive_count} completed compound"
                    f"{'s' if nonpositive_count != 1 else ''} recorded a non-positive "
                    "top-pose CNN affinity (`<= 0 pK`, corresponding to predicted "
                    "dissociation above 1 M). Where `CNNaffinity <= 0`, `CNN_VS = CNNscore × "
                    "CNNaffinity` becomes zero or negative and inverts `CNNscore` monotonicity "
                    "among negative-pK decoys, so negative `CNN_VS` tail rankings should not "
                    "be interpreted without inspecting `CNNscore` and `CNNaffinity` separately."
                )
        else:
            draft.say(
                "Completed compounds are ranked by descending top-pose CNN pose score, with "
                "ties broken by selection order. The CNN pose score is dimensionless and "
                "bounded between 0 and 1; a higher value ranks a compound earlier. It is not "
                "an energy and has no kcal/mol interpretation."
            )
            draft.say(
                "Ankora records two further quantities for each completed compound's top pose "
                "and keeps them distinct from that ranking and from each other:"
            )
            draft.say(
                "- the CNN affinity prediction, in pK units, where a higher value means a "
                "stronger predicted affinity;"
            )
            draft.say(
                "- the minimized affinity from GNINA's empirical scoring function, in "
                "kcal mol⁻¹, where a more negative value means a more favourable predicted "
                "interaction."
            )
            draft.say(
                f"The top-ranked compound ({best_label}) had a top-pose CNN pose score of "
                f"{best_pose.cnn_score:g}, a predicted CNN affinity of "
                f"{best_pose.cnn_affinity:g} pK, and a minimized affinity of "
                f"{best_pose.minimized_affinity_kcal_mol:g} kcal mol⁻¹. Campaign ranking did "
                "not use the minimized affinity, so the highest-ranked compound is not "
                "necessarily the one with the lowest recorded energy."
            )
            if best_cnn_vs is not None:
                draft.say(
                    f"Ankora also recorded a top-pose `CNN_VS` (`CNNscore × CNNaffinity`) of "
                    f"{best_cnn_vs:g} for {best_label}."
                )
        draft.say(
            "All of these GNINA quantities are computational predictions of this engine. "
            "None is a measured binding affinity and none is evidence of biological activity."
        )
        draft.say(
            "They come from GNINA's own empirical function and convolutional model, and "
            "they do not share a scale with the score of any other docking engine. Ankora "
            "does not pool or jointly rank results across engines."
        )
        self._reproducibility_prose(draft, entry)
        draft.say("")

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
        self._protein_prose(draft, receptor)

    def _protein_prose(self, draft: _Draft, receptor: Any) -> None:
        """Everything a receptor record says about how it was prepared.

        Shared with the GNINA path, which reaches it only after confirming that
        the stored artifact still hashes to what the engine was handed.
        """
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
            if repaired.parameters.get("repair_method") == "topology_guard_v3":
                openmm_version = repaired.parameters.get("openmm_version")
                if openmm_version:
                    draft.tool("OpenMM", str(openmm_version), "topology-guarded reconstruction")
                draft.say(
                    "The topology_guard_v3 geometry protocol used the recorded repair seed "
                    f"{repaired.parameters.get('repair_seed')} and OpenMM Reference. "
                    "Native bonded terms were retained with strengthened restraints on bonds "
                    "involving reconstructed atoms and a repulsive steric wall; observed heavy "
                    "atoms were fixed. Inferred connectivity and rebuilt template chirality "
                    "were checked before protonation. This is not full protein minimization."
                )
                bond_limit = repaired.parameters.get("maximum_rebuilt_bond_deviation_angstrom")
                if repaired.parameters.get("geometry_qc_version") == "template_bonds_v1":
                    draft.say(
                        f"Reconstructed template-known bonds were required to differ by no more "
                        f"than {bond_limit} Å from template lengths; incompatible observed-anchor "
                        "spans were rejected. This is an internal construction safeguard, not "
                        "general chemical validation."
                    )

        relax = events.get("receptor_clashes_relaxed")
        if relax is not None and getattr(decisions.relaxation, "enabled", False):
            parameters = relax.parameters
            displacement = parameters.get("max_restrained_atom_displacement_angstrom")
            tool = relax.tool
            draft.tool(tool.name, tool.version, "restrained clash relaxation")
            moved = (
                f" No previously observed atom moved more than {float(displacement):.2f} Å."
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
                f"Protonation of the receptor was {draft.missing('receptor protonation record')}."
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
        origin = site
        visited = {site.binding_site_id}
        while getattr(origin.decisions, "parent_binding_site_id", None) and not getattr(
            origin.decisions, "pocket_selection", None
        ):
            parent_id = origin.decisions.parent_binding_site_id
            parent = _load(self._binding_sites.load_record, parent_id)
            if parent is None or parent_id in visited or parent.receptor_id != site.receptor_id:
                draft.say(
                    f"Earlier site provenance was {draft.missing('binding site origin lineage')}.\n"
                )
                break
            visited.add(parent_id)
            origin = parent
        pocket_selection = getattr(origin.decisions, "pocket_selection", None)
        if pocket_selection is not None:
            pocket = _load(self._pockets.load_record, pocket_selection.report_id)
            gap = None
            if pocket is None:
                gap = "pocket detection report"
            elif pocket.receptor_id != site.receptor_id:
                gap = "matching pocket detection receptor"
            elif not any(
                candidate.pocket_id == pocket_selection.pocket_id for candidate in pocket.candidates
            ):
                gap = "selected pocket in detection report"
            else:
                draft.tool(pocket.tool.name, pocket.tool.version, "binding pocket detection")
                if pocket.tool.version:
                    draft.say(
                        f"Candidate pockets were detected with {pocket.tool.name} "
                        f"{pocket.tool.version}; the recorded initial selection was "
                        f"{pocket_selection.pocket_id}.\n"
                    )
                else:
                    gap = "pocket detection tool version"
            if gap:
                draft.say(f"Pocket detection provenance was {draft.missing(gap)}.\n")
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
                    maps.autogrid.tool.name,
                    maps.autogrid.tool.version,
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
        if microstate_plan is not None and _text(microstate_plan.mode) == "enumerated_selection":
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
            summary.eligible_count + summary.excluded_count + summary.needs_decision_count
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
            population = parameters.get("population_size", parameters.get("ga_population_size"))
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
                f"The exact executable used is identified by SHA-256 {entry.executable_sha256}."
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
        self._reproducibility_prose(draft, entry)
        draft.say("")

    def _reproducibility_prose(self, draft: _Draft, entry: CatalogEntry) -> None:
        """The three repeat-behavior states, shared by every engine.

        The distinction between them is load-bearing: "we did not check" and
        "we checked and it varies" are different claims, and neither may be
        inferred from an engine's reputation or from the presence of a seed.
        """
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
        f"{execution.catalog_id} (output fingerprint SHA-256 {execution.output_fingerprint_sha256})"
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
    ligands: Any,
    ligand_id: str,
    preparation_id: str,
) -> _PreparedLigand | None:
    pdbqt = _load2(ligands.load_pdbqt_record, ligand_id, preparation_id)
    if pdbqt is None:
        return None
    conformer = _load2(
        ligands.load_conformer_record,
        ligand_id,
        pdbqt.artifact.conformer_id,
    )
    if conformer is None:
        return None
    return _PreparedLigand(
        ligand_id=ligand_id,
        preparation_id=preparation_id,
        conformer=conformer,
        pdbqt=pdbqt,
        protocol=_protocol_from(pdbqt, conformer),
        state_lineage=_state_lineage(ligands, ligand_id, conformer),
    )


def _verified_gnina_selection_run(ligands: Any, campaign: Any) -> Any:
    """Return the filter run only when its stored manifest still matches the campaign."""
    selection = campaign.selection
    try:
        run = verified_screening_selection(
            store=ligands,
            library_id=selection.library_id,
            filter_run_id=selection.filter_run_id,
        )
    except (AnkoraDomainError, OSError, ValueError):
        return None
    if (
        run.artifact.filter_run_id != selection.manifest_artifact_id
        or run.artifact.sha256 != selection.manifest_sha256
        or tuple(run.selected_ligand_ids) != campaign.selected_ligand_ids
    ):
        return None
    return run


def _gnina_filter_run_prose(
    draft: _Draft,
    run: Any,
    *,
    selected_count: int,
    manifest_sha256: str,
) -> None:
    draft.tool("RDKit", run.rdkit_version, "descriptor calculation and filtering")
    microstate_plan = getattr(run, "microstate_plan", None)
    if microstate_plan is not None and _text(microstate_plan.mode) == "enumerated_selection":
        draft.say(
            "Before filtering, one protonation/tautomer microstate was explicitly "
            "selected for each retained parent compound from a bounded enumeration at "
            f"pH {microstate_plan.ph_min:g}-{microstate_plan.ph_max:g} (pKa precision "
            f"{microstate_plan.precision:g}; at most "
            f"{microstate_plan.max_tautomers_per_protomer} tautomers per protomer and "
            f"{microstate_plan.max_microstates_per_parent} microstates per parent). "
            "Candidate order was not interpreted as a population or suitability ranking."
        )
    else:
        draft.say(
            "Library filtering used each compound's exact submitted or explicitly "
            "component-resolved chemical state; no protonation or tautomer alternative "
            "was selected automatically."
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
        summary.eligible_count + summary.excluded_count + summary.needs_decision_count
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
        f"The applied selection manifest (SHA-256 {manifest_sha256}) carried "
        f"{selected_count} compound entries forward to docking in selection order."
    )


def _gnina_entry_preparation(ligands: Any, entry: Any) -> _PreparedLigand | None:
    """Verify one screening entry's stored conformer and PDBQT bytes against campaign hashes."""
    if (
        not entry.ligand_preparation_id
        or not entry.ligand_sha256
        or not entry.conformer_id
        or not entry.conformer_sha256
    ):
        return None
    pdbqt = _load2(ligands.load_pdbqt_record, entry.ligand_id, entry.ligand_preparation_id)
    if pdbqt is None:
        return None
    if (
        getattr(pdbqt.artifact, "ligand_id", entry.ligand_id) != entry.ligand_id
        or pdbqt.artifact.conformer_id != entry.conformer_id
        or pdbqt.artifact.sha256 != entry.ligand_sha256
    ):
        return None
    ligand_bytes = _stored_digest(
        ligands.pdbqt_content_path, entry.ligand_id, entry.ligand_preparation_id
    )
    if ligand_bytes != entry.ligand_sha256:
        return None
    conformer = _load2(ligands.load_conformer_record, entry.ligand_id, entry.conformer_id)
    if conformer is None or conformer.artifact.sha256 != entry.conformer_sha256:
        return None
    conformer_bytes = _stored_digest(
        ligands.conformer_content_path, entry.ligand_id, entry.conformer_id
    )
    if conformer_bytes != entry.conformer_sha256:
        return None
    return _PreparedLigand(
        ligand_id=entry.ligand_id,
        preparation_id=entry.ligand_preparation_id,
        conformer=conformer,
        pdbqt=pdbqt,
        protocol=_protocol_from(pdbqt, conformer),
        state_lineage=_state_lineage(ligands, entry.ligand_id, conformer),
    )


def _protocol_from(pdbqt: Any, conformer: Any) -> _PreparationProtocol:
    """The recorded protocol behind one prepared ligand."""
    minimization = conformer.minimization
    conformer_tool = getattr(getattr(conformer, "provenance", None), "tool", None)
    return _PreparationProtocol(
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


def _stored_digest(resolve: Any, *identifiers: str) -> str | None:
    """SHA-256 of the bytes actually on disk, or None if they cannot be read.

    The record's own `sha256` field is metadata written beside the artifact, so
    comparing it to the engine's recorded hash only proves two JSON documents
    agree. The Methods section claims the stored artifact still matches what
    GNINA was handed, and only reading the file establishes that.
    """
    try:
        path = Path(resolve(*identifiers))
    except (AnkoraDomainError, OSError, ValueError, TypeError):
        return None
    digest = sha256()
    try:
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError:
        return None
    return digest.hexdigest()


def _gnina_executed(job: Any) -> bool:
    """Whether this job actually completed a successful GNINA run.

    Everything written in the past tense depends on this. A queued job has no
    execution at all, and a failed or canceled one has an execution that did
    not produce the protocol it was configured for.
    """
    execution = getattr(job, "execution", None)
    return (
        _text(job.status) == "completed"
        and execution is not None
        and getattr(execution, "exit_code", None) == 0
        and not getattr(execution, "canceled", False)
        and not getattr(execution, "timed_out", False)
    )


def _same_box(first: Any, second: Any) -> bool:
    """Whether two records describe the same search space.

    Compared numerically rather than by identifier: two binding-site records
    can name the same pocket, and the box is what says whether they searched
    the same space.
    """
    names = ("center_x", "center_y", "center_z", "size_x", "size_y", "size_z")
    try:
        return all(
            math.isclose(
                float(getattr(first, name)),
                float(getattr(second, name)),
                rel_tol=0.0,
                abs_tol=1e-6,
            )
            for name in names
        )
    except (AttributeError, TypeError, ValueError):
        return False


_GNINA_UNFINISHED = {
    "failed": "did not complete; its recorded status is `failed`",
    "canceled": "was canceled before it finished",
    "cancel_requested": "has a pending cancellation and no terminal outcome",
    "running": "was still running when this record was read",
    "queued": "had not started when this record was read",
}


def _gnina_unfinished_prose(status: str, failure: Any) -> str:
    described = _GNINA_UNFINISHED.get(status, f"has the recorded status `{status}`")
    sentence = f"This GNINA job {described}, and no poses were published for it."
    code = getattr(failure, "code", None)
    if code:
        message = str(getattr(failure, "message", "") or "").rstrip(".")
        sentence += f" The recorded failure was {code}"
        sentence += f": {message}." if message else "."
    return sentence


def _gnina_compute_prose(parameters: Any, *, executed: bool) -> str:
    threads = parameters.cpu_threads
    plural = "s" if threads != 1 else ""
    if parameters.compute == "cpu":
        placement = (
            f"The run was executed on the CPU with {threads} thread{plural} and GPU "
            "execution explicitly disabled."
            if executed
            else f"The run was configured for the CPU with {threads} thread{plural} "
            "and GPU execution explicitly disabled."
        )
        return (
            f"{placement} Ankora never falls back between compute devices: the "
            "recorded policy is the one that applies."
        )
    placement = (
        f"The run was requested on CUDA logical device {parameters.device_index} with "
        f"{threads} CPU thread{plural}."
        if executed
        else f"The run was configured to request CUDA logical device "
        f"{parameters.device_index} with {threads} CPU thread{plural}."
    )
    return (
        f"{placement} Ankora never falls back from a requested GPU to the CPU; a run "
        "that cannot be observed on the selected device fails instead of producing "
        "poses."
    )


def _gnina_observed_uuid(execution: Any) -> str | None:
    return getattr(execution, "observed_gpu_uuid", None)


def _gnina_gpu_observation(execution: Any) -> str | None:
    """What the GPU observation does and does not establish.

    A detected executable or a reported device is not proof that GPU inference
    ran, so this states the narrower thing that was actually observed.
    """
    if execution is None or not getattr(execution, "gpu_process_observed", False):
        return None
    observed = _gnina_observed_uuid(execution)
    if not observed:
        return None
    requested = getattr(execution, "requested_gpu_uuid", None)
    sentence = f"Ankora observed the GNINA process occupying GPU {observed}"
    if requested:
        sentence += (
            f", the device requested for this run ({requested})"
            if requested == observed
            else f", while the device requested for this run was {requested}"
        )
    return (
        f"{sentence}. This confirms that the engine's own process was reported on that "
        "device; it is not independent proof that every neural-network operation "
        "executed on the GPU."
    )


def _single_preparation_sentence(protocol: _PreparationProtocol) -> str:
    return (
        "The selected ligand was converted to a three-dimensional conformer "
        f"using {_protocol_description(protocol)}."
    )


def _batch_preparation_prose(draft: _Draft, preparations: _PreparationSet) -> None:
    missing = preparations.entries_without_preparation + preparations.unavailable_preparations
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
            f"- {count} ligand{'s' if count != 1 else ''}: {_protocol_description(protocol)}."
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
    draft: _Draft,
    preparations: _PreparationSet,
    *,
    single: bool,
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
            f"The {len(known)} verified ligands comprised {len(groups)} chemical-state lineages:"
        )
        for lineage, count in sorted(
            groups.items(), key=lambda pair: (_state_description(pair[0]), pair[1])
        ):
            draft.say(f"- {count} ligand{'s' if count != 1 else ''} {_state_description(lineage)}.")
    if all(
        decision.kind not in {"protonation", "microstate"}
        for lineage in known
        for decision in lineage.decisions
    ):
        draft.say("No pH-based ligand protonation enumeration was recorded.")
    if all(decision.kind != "microstate" for lineage in known for decision in lineage.decisions):
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
                ", with the configured bound reached" if decision.enumeration_truncated else ""
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
    GNINA_JOB: "GNINA",
    GNINA_SCREENING: "GNINA",
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
        "lt": "<",
        "le": "≤",
        "gt": ">",
        "ge": "≥",
        "eq": "=",
        "between": "between",
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
