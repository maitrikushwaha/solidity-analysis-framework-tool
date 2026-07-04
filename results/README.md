# Results — data dictionary and layout

This directory holds the detection results for **our tool** and eight
baselines (Mythril, Oyente+, Slither, Osiris, SmartCheck, Sailfish, Vandal,
EtherSolve) on four benchmark datasets, plus the harmonised metrics used in the paper.

## How to read the results (start here)

Two kinds of files coexist:

1. **Harmonised, uniform metrics** — generated, identical schema for every tool,
   written to the top-level [`../tables/`](../tables/) directory:
   - [`../tables/metrics_per_class.csv`](../tables/metrics_per_class.csv) / `comparison_metrics.csv`
   - [`../tables/comparison_table.pdf`](../tables/comparison_table.pdf) (human-readable, grouped)
   - [`../tables/table8_timing_median.csv`](../tables/table8_timing_median.csv) (Table 8, median detection time)
2. **Per-tool raw outputs** — one sub-directory per tool here under `results/`, in
   that tool's own native format (kept for full reproducibility). These are the
   inputs that the harmoniser ([`build_comparison.py`](../scripts/build_comparison.py)) reads.

If you only want "how did each tool do", read `../tables/metrics_per_class.csv`.
The raw per-tool outputs are evidence, not the headline.

## Provenance — how each tool's results were produced

- **Our tool** — fully reproducible from this repo:
  `python3 scripts/run_ours.py <dataset>` (see the top-level `README.md`).
  Per-domain detection times come from `scripts/run_timing_experiment.py`.
- **Baselines (Mythril, Oyente+, Slither, Osiris, SmartCheck, Sailfish, Vandal,
  EtherSolve)** — each
  baseline was executed with **its own native tooling, in its own repository/
  environment**, using that tool's recommended invocation (and, where needed,
  per-contract `solc` version selection). The analyses were iterative and
  tool-specific, so this repo does **not** ship a single uniform runner per
  baseline (a script that did not actually generate the numbers would be
  misleading). Instead, the **authoritative artifacts are the raw outputs
  themselves**, preserved verbatim under `results/<tool>/<dataset>/` (raw logs/
  JSON + the tool's own summary), from which `scripts/build_comparison.py`
  extracts each tool's reported TP/FP/TN/FN. Coverage of raw outputs:

  | tool | datasets with raw outputs |
  |---|---|
  | mythril | rsd, sbc, qian, solidifi |
  | oyente_plus | rsd, sbc, qian, solidifi |
  | slither | rsd, sbc, qian |
  | osiris | sbc, qian |
  | smartcheck | rsd, sbc, qian |
  | sailfish | rsd, sbc, qian, solidifi |
  | vandal | rsd, sbc, qian |
  | ethersolve | rsd, sbc, qian |

  (A blank cell in `metrics_per_class.csv` = that tool has no detector for / was
  not run on that dataset–vulnerability, i.e. genuinely N/A.)

## `metrics_per_class.csv` — the canonical metric table

One row per **(dataset, vulnerability, tool)**. Columns:

| column | meaning |
|---|---|
| `dataset` | `rsd`, `sbc`, `qian`, `solidifi` |
| `vulnerability` | `reentrancy`, `overflow`, `timestamp`, `tod` |
| `tool` | `ours`, `mythril`, `oyente_plus`, `slither`, `osiris`, `smartcheck`, `sailfish`, `vandal`, `ethersolve` |
| `TP,FP,TN,FN` | confusion counts (integers) |
| `analyzed` | contracts with a usable verdict = TP+FP+TN+FN |
| `total` | number of contracts in that dataset–vulnerability benchmark |
| `excluded_na` | `total − analyzed` = the paper's **Failures** column (Tables 4–7) — contracts the tool could **not** analyse (compile error / timeout / crash), excluded from the metrics as N/A |
| `precision,recall,f1,accuracy` | standard metrics (0–1) |
| `fdr` | false discovery rate = FP/(TP+FP) |
| `fnr` | false negative rate = FN/(TP+FN) |
| `tpr` | true positive rate = recall (ROC y-axis) |
| `fpr` | false positive rate = FP/(FP+TN) (ROC x-axis) |
| `auc` | single-operating-point AUC = (TPR + (1−FPR))/2 — the value plotted in Fig 16 |

`NA` = the tool has **no detector** for that vulnerability, or was not run on
that dataset. All metrics are recomputed by one formula from each tool's own
TP/FP/TN/FN, so the comparison is apples-to-apples.

This file (in `../tables/`) regenerates **Tables 4–7** (P/R/F1/FDR/FNR) and the AUC values
in **Fig 16**.

## Per-tool raw CSV conventions

Each tool's per-contract CSV lists one row per analysed contract. **Prediction
columns are encoded as:**

| value | meaning |
|---|---|
| `1` | tool flagged this vulnerability |
| `0` | tool ran and did **not** flag it (a true/false negative) |
| `-1` | tool has **no detector** for this vulnerability → excluded from metrics (N/A), never counted as a negative |

Other common columns: `duration_s` (analysis time, seconds), `exit_status` /
`status` (OK / COMPILE_ERROR / PARTIAL / timeout), `solc_version` (`?`/`N/A` =
not recorded), `raw_json_path` / `raw_output_path` (repo-relative pointer to the
tool's raw log for that contract).

> Why some raw CSVs look terse (e.g. `mythril_results_qian.csv` is just
> `filename, reentrancy, overflow, …`): those are the tool's native dumps and do
> **not** carry the ground truth, so a bare `0` there is ambiguous on its own.
> The ground truth and the resulting TP/FP/TN/FN are joined in
> `metrics_per_class.csv` — always interpret a tool's flags against
> `*_ground_truth.json`, not in isolation. (A fully-joined per-contract
> `predictions.csv` with explicit `ground_truth` + `outcome` columns is provided
> under `standardized/` — see "Tidy predictions" below.)

## Ground truth

The `<dataset>_ground_truth.json` files (at the repo root) map each contract to
`{reentrancy, overflow, timestamp, tod} ∈ {0,1}`. Keys:
- `sbc`, `solidifi`, `rsd`: `<filename>.sol`
- `qian`: `<subset>/<filename>.sol` where subset ∈ `reentrancy`, `overflow`,
  `timestamp` (Qian reuses numeric ids across subsets but the files differ, so
  the subset prefix is significant).

## Datasets (universe sizes)

| dataset | contracts | vulnerabilities evaluated |
|---|---|---|
| RSD (Ressi et al.) | 138 | reentrancy |
| SBC (SmartBugs Curated) | 142 | reentrancy, overflow, timestamp, tod |
| Qian | 222 / 275 / 349 (reentrancy / overflow / timestamp subsets) | reentrancy, overflow, timestamp |
| SolidiFI | 100 | tod |

## Timing (Table 8)

`ours/timing/` holds the per-domain timing experiment (Interval/Octagon/
Polyhedra). It is measured **serially** with repeated trials (rep1/rep2/rep3);
`../tables/table8_timing_median.csv` reports the median (Table 8).

## Regenerating everything

```bash
python3 scripts/build_comparison.py        # -> ../tables/metrics_per_class.csv, comparison_metrics.csv,
                                           #    comparison_table.{md,html,pdf,png}  (all from one source)
python3 scripts/make_table8_timing.py      # -> ../tables/table8_timing_median.csv (Table 8)
python3 scripts/make_predictions.py        # -> standardized/ tidy predictions (+ validation)
```

## Tidy predictions — `standardized/`

`standardized/predictions.csv` (+ per-tool `<tool>__<dataset>.csv`) gives one
self-describing row per **(tool, dataset, contract, vulnerability)** with
explicit `ground_truth`, `predicted`, `outcome`, `label` columns. Generated by
`scripts/make_predictions.py` and validated against `../tables/metrics_per_class.csv`:
**all 54 / 54 cells match exactly** (crashes/compile-errors/timeouts excluded as
N/A, per the paper convention). See `standardized/README.md`.
