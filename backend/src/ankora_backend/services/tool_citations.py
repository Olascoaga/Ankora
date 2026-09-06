"""The published reference each scientific tool's authors ask to be cited.

A Methods section names the tools that produced the numbers; a bibliography has
to name the papers behind them. Ankora already knows exactly which tools and
versions acted in a campaign, so leaving the author to reconstruct that list by
hand was work the record could do.

Two rules make this safe to put in front of an author:

* **Every entry here was resolved against Crossref, not recalled.** Author
  lists, journals, volumes, issues, pages and years come from the DOI's own
  registered metadata. A fabricated reference in a manuscript is exactly the
  failure this project exists to prevent, and a citation is harder to check
  than a sentence — it looks correct until someone follows it.
* **A tool with no verified reference is reported as having none.** It never
  borrows a neighbour's citation and never gets a plausible one invented for
  it.

Where a tool's authors ask for more than one paper, all of them are listed:
AutoDock Vina asks for both the 1.2.0 paper and the original, and PDB2PQR's
protonation depends on PROPKA, whose two papers are cited separately from it.

Method papers are attached to the tool that runs the method. Ankora's prose
names ETKDGv3 and MMFF94s explicitly, so a reader needs those references, and
they are not the RDKit software citation.
"""

from dataclasses import dataclass

# The authors listed on a paper, in order, as `Family II`. Kept as one string
# because that is how a bibliography consumes it; the author restyles it to
# their journal's convention.


@dataclass(frozen=True, slots=True)
class Reference:
    """One published work, as its DOI's registered metadata records it."""

    key: str
    authors: str
    title: str
    container: str
    # Zero for a work with no publication year to state - a software citation
    # is identified by the version that ran, which the Software table already
    # carries. Printing a year that does not match that version would be a
    # small, quiet falsehood in a bibliography.
    year: int
    volume: str = ""
    issue: str = ""
    pages: str = ""
    doi: str = ""
    url: str = ""
    note: str = ""

    def rendered(self) -> str:
        """A single line an author can paste and then restyle."""
        head = f"{self.authors}. {self.title}. {self.container}"
        parts = [f"{head}. {self.year}" if self.year else head]
        if self.volume:
            locator = self.volume
            if self.issue:
                locator += f"({self.issue})"
            if self.pages:
                locator += f":{self.pages}"
            parts.append(f";{locator}")
        parts.append(".")
        if self.doi:
            parts.append(f" doi:{self.doi}")
        if self.url:
            parts.append(f" {self.url}")
        if self.note:
            parts.append(f" {self.note}")
        return "".join(parts)


_VINA_1_2_0 = Reference(
    key="vina-1.2.0",
    authors="Eberhardt J, Santos-Martins D, Tillack AF, Forli S",
    title=(
        "AutoDock Vina 1.2.0: New Docking Methods, Expanded Force Field, and "
        "Python Bindings"
    ),
    container="Journal of Chemical Information and Modeling",
    year=2021, volume="61", issue="8", pages="3891-3898",
    doi="10.1021/acs.jcim.1c00203",
)
_VINA_ORIGINAL = Reference(
    key="vina-original",
    authors="Trott O, Olson AJ",
    title=(
        "AutoDock Vina: improving the speed and accuracy of docking with a new "
        "scoring function, efficient optimization, and multithreading"
    ),
    container="Journal of Computational Chemistry",
    year=2010, volume="31", issue="2", pages="455-461",
    doi="10.1002/jcc.21334",
)
_AUTODOCK4 = Reference(
    key="autodock4",
    authors="Morris GM, Huey R, Lindstrom W, Sanner MF, Belew RK, Goodsell DS, Olson AJ",
    title="AutoDock4 and AutoDockTools4: Automated docking with selective receptor flexibility",
    container="Journal of Computational Chemistry",
    year=2009, volume="30", issue="16", pages="2785-2791",
    doi="10.1002/jcc.21256",
)
_AUTODOCK_GPU = Reference(
    key="autodock-gpu",
    authors=(
        "Santos-Martins D, Solis-Vasquez L, Tillack AF, Sanner MF, Koch A, Forli S"
    ),
    title="Accelerating AutoDock4 with GPUs and Gradient-Based Local Search",
    container="Journal of Chemical Theory and Computation",
    year=2021, volume="17", issue="2", pages="1060-1073",
    doi="10.1021/acs.jctc.0c01006",
)
_MEEKO = Reference(
    key="meeko",
    authors=(
        "Santos-Martins D, He Y, Eberhardt J, Sharma P, Bruciaferri N, Holcomb M, "
        "Llanos MA, Hansel-Harris A, Barkdull AP, Tillack AF, Bianco G, "
        "Paulsen ML, Mato J, Taneja I, Forli S"
    ),
    title=(
        "Meeko: Molecule Parametrization and Software Interoperability for "
        "Docking and Beyond"
    ),
    container="Journal of Chemical Information and Modeling",
    year=2025, volume="65", issue="24", pages="13045-13050",
    doi="10.1021/acs.jcim.5c02271",
)
_OPENMM = Reference(
    key="openmm",
    authors=(
        "Eastman P, Swails J, Chodera JD, McGibbon RT, Zhao Y, Beauchamp KA, "
        "Wang LP, Simmonett AC, Harrigan MP, Stern CD, Wiewiora RP, Brooks BR, "
        "Pande VS"
    ),
    title=(
        "OpenMM 7: Rapid development of high performance algorithms for "
        "molecular dynamics"
    ),
    container="PLOS Computational Biology",
    year=2017, volume="13", issue="7", pages="e1005659",
    doi="10.1371/journal.pcbi.1005659",
    note="(PDBFixer is distributed as part of the OpenMM project.)",
)
_PDB2PQR = Reference(
    key="pdb2pqr",
    authors=(
        "Jurrus E, Engel D, Star K, Monson K, Brandi J, Felberg LE, Brookes DH, "
        "Wilson L, Chen J, Liles K, Chun M, Li P, Gohara DW, Dolinsky T, "
        "Konecny R, Koes DR, Nielsen JE, Head-Gordon T, Geng W, Krasny R, "
        "Wei GW, Holst MJ, McCammon JA, Baker NA"
    ),
    title="Improvements to the APBS biomolecular solvation software suite",
    container="Protein Science",
    year=2018, volume="27", issue="1", pages="112-128",
    doi="10.1002/pro.3280",
)
_PROPKA_OLSSON = Reference(
    key="propka3-olsson",
    authors="Olsson MHM, Søndergaard CR, Rostkowski M, Jensen JH",
    title=(
        "PROPKA3: Consistent Treatment of Internal and Surface Residues in "
        "Empirical pKa Predictions"
    ),
    container="Journal of Chemical Theory and Computation",
    year=2011, volume="7", issue="2", pages="525-537",
    doi="10.1021/ct100578z",
)
_PROPKA_SONDERGAARD = Reference(
    key="propka3-sondergaard",
    authors="Søndergaard CR, Olsson MHM, Rostkowski M, Jensen JH",
    title=(
        "Improved Treatment of Ligands and Coupling Effects in Empirical "
        "Calculation and Rationalization of pKa Values"
    ),
    container="Journal of Chemical Theory and Computation",
    year=2011, volume="7", issue="7", pages="2284-2295",
    doi="10.1021/ct200133y",
)
_DIMORPHITE = Reference(
    key="dimorphite-dl",
    authors="Ropp PJ, Kaminsky JC, Yablonski S, Durrant JD",
    title=(
        "Dimorphite-DL: an open-source program for enumerating the ionization "
        "states of drug-like small molecules"
    ),
    container="Journal of Cheminformatics",
    year=2019, volume="11", pages="14",
    doi="10.1186/s13321-019-0336-9",
)
_PROLIF = Reference(
    key="prolif",
    authors="Bouysset C, Fiorucci S",
    title="ProLIF: a library to encode molecular interactions as fingerprints",
    container="Journal of Cheminformatics",
    year=2021, volume="13", pages="72",
    doi="10.1186/s13321-021-00548-6",
)
_P2RANK = Reference(
    key="p2rank",
    authors="Krivák R, Hoksza D",
    title=(
        "P2Rank: machine learning based tool for rapid and accurate prediction "
        "of ligand binding sites from protein structure"
    ),
    container="Journal of Cheminformatics",
    year=2018, volume="10", pages="39",
    doi="10.1186/s13321-018-0285-8",
)
_RDKIT = Reference(
    key="rdkit",
    authors="Landrum G, et al",
    title="RDKit: Open-source cheminformatics",
    container="Software",
    year=0,
    doi="10.5281/zenodo.591637",
    url="https://www.rdkit.org",
    note=(
        "(RDKit has no peer-reviewed paper; its maintainers ask that the "
        "software be cited, naming the version recorded in the Software table "
        "above. The DOI resolves to the release series - substitute the DOI of "
        "that exact version where a journal requires it.)"
    ),
)
_ETKDG = Reference(
    key="etkdg",
    authors="Riniker S, Landrum GA",
    title=(
        "Better Informed Distance Geometry: Using What We Know To Improve "
        "Conformation Generation"
    ),
    container="Journal of Chemical Information and Modeling",
    year=2015, volume="55", issue="12", pages="2562-2574",
    doi="10.1021/acs.jcim.5b00654",
)
_ETKDG_V3 = Reference(
    key="etkdg-v3",
    authors="Wang S, Witek J, Landrum GA, Riniker S",
    title=(
        "Improving Conformer Generation for Small Rings and Macrocycles Based "
        "on Distance Geometry and Experimental Torsional-Angle Preferences"
    ),
    container="Journal of Chemical Information and Modeling",
    year=2020, volume="60", issue="4", pages="2044-2058",
    doi="10.1021/acs.jcim.0c00025",
)
_MMFF94 = Reference(
    key="mmff94",
    authors="Halgren TA",
    title=(
        "Merck molecular force field. I. Basis, form, scope, parameterization, "
        "and performance of MMFF94"
    ),
    container="Journal of Computational Chemistry",
    year=1996, volume="17", issue="5-6", pages="490-519",
    doi="10.1002/(SICI)1096-987X(199604)17:5/6<490::AID-JCC1>3.0.CO;2-P",
)
_MMFF94S = Reference(
    key="mmff94s",
    authors="Halgren TA",
    title=(
        "MMFF VI. MMFF94s option for energy minimization studies"
    ),
    container="Journal of Computational Chemistry",
    year=1999, volume="20", issue="7", pages="720-729",
    doi="10.1002/(SICI)1096-987X(199905)20:7<720::AID-JCC7>3.0.CO;2-X",
)

# Keyed by the tool name exactly as the Methods renderer records it. A name
# absent from this map is reported as having no recorded reference.
_BY_TOOL: dict[str, tuple[Reference, ...]] = {
    "AutoDock Vina": (_VINA_1_2_0, _VINA_ORIGINAL),
    "AutoDock4": (_AUTODOCK4,),
    "AutoGrid": (_AUTODOCK4,),
    "AutoDock-GPU": (_AUTODOCK_GPU,),
    "Meeko": (_MEEKO,),
    "Meeko ligand preparation": (_MEEKO,),
    "PDBFixer": (_OPENMM,),
    "OpenMM declash (PDBFixer worker)": (_OPENMM,),
    "PDB2PQR/PROPKA": (_PDB2PQR, _PROPKA_OLSSON, _PROPKA_SONDERGAARD),
    "Dimorphite-DL": (_DIMORPHITE,),
    "ProLIF": (_PROLIF,),
    "P2Rank": (_P2RANK,),
    "RDKit": (_RDKIT,),
    "RDKit ETKDG/MMFF": (_RDKIT, _ETKDG, _ETKDG_V3, _MMFF94, _MMFF94S),
}


def references_for(tool_name: str) -> tuple[Reference, ...]:
    """Every reference this tool's authors ask for, or an empty tuple."""
    return _BY_TOOL.get(tool_name, ())
