# Ankora v0.2 External Comparison Benchmark Harness (`ADR-031`)

This directory lives **strictly outside** the shipped Ankora desktop product (`backend/src/`, `apps/desktop/`, `requirements/`, Windows `.exe`, Linux `.deb` / `.tar.zst`, and optional GNINA pack) per [`docs/architecture/ADR/ADR-031-external-benchmark-boundary.md`](../../docs/architecture/ADR/ADR-031-external-benchmark-boundary.md).

## Architectural Guarantees

1. **Zero product coupling:** Nothing under `backend/src/` or `apps/desktop/` imports, calls, or depends on anything in `benchmarks/`. Removing this directory has zero effect on Ankora's offline desktop product.
2. **One-directional structured consumption:** `evaluate_comparison.py` consumes Ankora **only** via verified `Export v4` / `Export v5` bundle archives or directories (invoking `scripts/verify_export_bundle.py` first) and consumes pinned third-party platforms (e.g., pinned `DockM8`, scientist-supplied reference `PMC13613745`) via hash-verified CSV outputs alongside preserved raw outputs.
3. **Mandatory two-axis evaluation (`ADR-031 §2`):** Admissible comparison verdicts require **both** Axis A (`controlled`: identical prepared receptor, ligand set, search box, split, and denominator) and Axis B (`end_to_end`: each platform's own complete documented workflow).
4. **Out-of-sample discipline (`ADR-031 §3`):** Locked parent + Bemis–Murcko scaffold Confirmation splits, primary metric `BEDROC_20` with paired parent-compound bootstrap `95% CI`, `1-SE` parsimony, verbatim `"Insufficient evidence to prefer over baseline"` null verdict, `PoseBusters` physical-validity stratification, and mandatory publication of negative and null results.
5. **Pure Python 3.12 standard library:** Runs cleanly under `python -S` with zero third-party dependencies.

## Quick Usage

```bash
python -S benchmarks/external_comparison/evaluate_comparison.py \
  --protocol path/to/comparison_protocol.json \
  --ankora-controlled path/to/ankora_controlled_export_v5_bundle.zip \
  --external-controlled path/to/external_controlled_scores.csv \
  --ankora-end-to-end path/to/ankora_e2e_export_v5_bundle.zip \
  --external-end-to-end path/to/external_e2e_scores.csv \
  --output-json path/to/comparison_report.json \
  --output-markdown path/to/comparison_report.md
```
