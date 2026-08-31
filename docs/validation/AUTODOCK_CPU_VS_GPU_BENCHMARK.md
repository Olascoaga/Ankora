# AutoDock4 CPU vs AutoDock-GPU — benchmark (ADR-015 item 5)

Measured on 2026-08-26 on the development machine: Intel CPU with 16 logical
processors, NVIDIA GeForce RTX 5050 Laptop GPU (4 GB), driver 32.0.16.1088.
AutoDock 4.2.6 and AutoDock-GPU 1.6, both official Windows builds.

Matched where matching is possible: same receptor, same map set, same ligands,
same number of LGA runs, same evaluation budget, same population, same
clustering tolerance, same seeds. **What cannot be matched is the local
search** — the CPU protocol is Solis-Wets and AutoDock-GPU's is ADADELTA. This
measures two real engines doing the job they actually do, not a synthetic
equivalence.

## Library scale: 257 molecules

The scientist's AutoDock4 campaign `e3728f21` docked 259 molecules at the
production protocol and its per-molecule results are persisted, so the CPU side
was **read rather than recomputed**. The GPU redid the same 257 against the same
map set in one `--filelist` pass.

| | wall time | workers |
| --- | --- | --- |
| AutoDock4 CPU campaign | **6,296 s** (104.9 min) | 15 parallel processes |
| AutoDock-GPU, one pass | **298 s** (5.0 min) | 1 process |

**21× wall-clock. 317× core-for-core** — the CPU number already includes
fifteen-way parallelism, so the per-core comparison is the honest one for asking
what the hardware does.

### Do they agree?

| | |
| --- | --- |
| Spearman ρ | **0.9463** (p = 4×10⁻¹²⁷) |
| Pearson r | 0.9414 |
| mean signed difference | **−0.102 kcal/mol** (GPU finds lower) |
| mean / median / max \|difference\| | 0.122 / 0.040 / 1.05 |
| within 0.1 / 0.5 / 1.0 kcal/mol | 72% / 93% / 99% |
| GPU lower / tied / CPU lower | 146 (57%) / 78 (30%) / 33 (13%) |
| top-10 / top-20 / top-50 overlap | 9/10, 17/20, 45/50 |

The GPU **systematically finds lower minima**, on 57% of molecules against 13%
the other way. That is what a more effective local search does; it is not
evidence that either number is closer to reality. Both are estimates from the
same scoring function.

### Cluster population predicts where they disagree

| GPU top-cluster population | |
| --- | --- |
| where the backends agree (\|diff\| ≤ 0.05, n=144) | **7.8 / 10 runs** |
| where they disagree by ≥ 0.5 (n=18) | **4.3 / 10 runs** |

Mann-Whitney p < 0.0001; rank correlation between \|difference\| and cluster
population ρ = −0.465, p = 3×10⁻¹⁵.

So the reproducibility evidence Ankora already records and displays — how many
of the independent runs landed in the top cluster — is a usable reliability
signal for a GPU result. A molecule whose top cluster holds most of its runs is
one both backends agree on.

**This was tested once before and rejected.** At n=49, on the Vina/AutoDock4
comparison, the same hypothesis gave p = 0.126 and was reported as not
established. At n=257 it holds. The earlier sample was simply too small.

## Per-ligand, single process: 8 molecules

Eight molecules run one at a time, the way a single-ligand job runs.

| | total | per ligand | vs CPU |
| --- | --- | --- | --- |
| AutoDock4 CPU | 1,093 s | 103–185 s | — |
| AutoDock-GPU, matched protocol | 12.8 s | 1.5–1.9 s | **85×** |
| AutoDock-GPU, its own defaults | 6.6 s | 0.8 s | **165×** |

The tool's own defaults — the ligand-based heuristic plus automatic stopping —
are **1.93× faster again** than the matched protocol, and over these eight
molecules they ranked identically to the CPU (Spearman ρ = 1.000) with a mean
absolute difference of 0.116 kcal/mol. Eight well-separated energies is a weak
basis for a ranking claim; the 257-molecule figures above are the ones to cite.

## Repeatability

Three repeats of one seed per ligand, eight ligands: best-energy spread
**mean 0.041, max 0.18 kcal/mol**, identical in 3 of 8. A seed narrows
AutoDock-GPU's variability but does not remove it, which is why every GPU record
states `bitwise_reproducible: false`. The CPU engine repeated one seed twice and
produced bit-identical ranking tables.

## What this means

- The GPU is worth having: 21× on a real campaign, and the agreement with the
  CPU is strong enough that a screening campaign can reasonably be run on it.
- It is not a drop-in replacement for a reproducible result. When an exactly
  repeatable number is required, the CPU backend is the one that delivers it.
- Neither engine's number should be treated as more correct than the other's.
  They are the same scoring function reached by different searches, and Ankora
  records the backend so the two are never pooled.
