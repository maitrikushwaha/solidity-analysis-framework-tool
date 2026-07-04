# Mythril — reproducibility

This directory contains the Mythril results used for the Mythril columns of the
comparison tables (Tables 4–8) and everything needed to reproduce those numbers.

Mythril is the **one documented exception** to the artifact's Docker policy: as
stated in the paper, *"except Mythril, all baseline tools were executed using
their official Docker images."* Mythril was instead run from its **official
release v0.24.8**, downloaded from the upstream ConsenSys repository, with the
exact flags and `solc` selection documented below. This matches the revision's
methodology (each baseline run from its official source at a pinned version, with
versions and commit IDs recorded).

## What "Mythril" is
ConsenSys **Mythril**, a security analyser for EVM bytecode based on symbolic
execution, SMT solving and taint analysis. It compiles each contract with the
appropriate `solc`, explores transaction sequences symbolically, and reports
findings as SWC entries.

## Version and configuration
| | |
|---|---|
| Mythril | **v0.24.8** (PyPI / upstream release; identical to image `smartbugs/mythril:0.24.8`) |
| `solc` | auto-selected per contract from its `pragma` (minimum 0.4.11, which Mythril v0.24.8 requires); contracts pinned below 0.4.11 are forced to 0.4.26 (backward compatible) |
| Primary flags | `--execution-timeout 300 --max-depth 22 -t 3 --solver-timeout 10000 --solv <version>` |
| Heavy-contract recovery | contracts that exceed the wall-clock budget are re-run once with `--execution-timeout 600 --max-depth 16` (lower depth, longer time) before being declared N/A |

### SWC → vulnerability-class mapping
| SWC | Class |
|---|---|
| SWC-107 | reentrancy |
| SWC-101 | integer overflow / underflow (IO/IU) |
| SWC-116 | timestamp dependence |
| SWC-114 | transaction-ordering dependence (TOD) |

## Vulnerability coverage
| Class | Detector | Status |
|---|---|---|
| Reentrancy | SWC-107 | scored |
| Integer overflow/underflow | SWC-101 | scored |
| Timestamp | SWC-116 | scored |
| TOD / front-running | SWC-114 | scored |

Mythril is the only baseline scored on **all four** classes.

## Datasets and N/A rule
SBC (all four classes), Qian (reentrancy + overflow + timestamp), RSD
(reentrancy) and SolidiFI (TOD) are analysed. A contract is excluded (N/A) only
when Mythril produces no usable verdict after the heavy-contract recovery pass
(`COMPILE_ERROR`, or a genuine `TIMEOUT` that does not finish even at
`--max-depth 16 --execution-timeout 600`).

## Results (this run, scored against the repository ground truth)
TP/FP/TN/FN per dataset and class:

| Dataset | reentrancy | overflow | timestamp | tod |
|---|---|---|---|---|
| SBC | 29/39/72/2 | 12/18/109/3 | 12/2/126/2 | 1/37/101/3 |
| Qian | 36/60/93/33 | 23/2/187/63 | 59/86/90/114 | — |
| RSD | 56/44/26/10 (2 N/A) | — | — | — |
| SolidiFI | — | — | — | 21/0/50/29 |

## Files in this directory
| Path | Contents |
|---|---|
| `sbc/mythril_results_sbc.csv` | per-contract verdicts + `swc_*_count`, `duration_s`, `exit_status`, `solc_version`, `raw_json_path` |
| `qian/mythril_results_qian.csv` | per-contract verdicts (wide; one row per contract) |
| `rsd/mythril_rsd_{reentrant,safe}_results.csv` | per-contract reentrancy verdicts (vulnerable / safe partitions) |
| `solidifi/mythril_results_solidifi.csv` | per-contract TOD verdicts |
| `*/raw_json/` | the raw `myth analyze -o json` output per contract |
| `metrics_all_report.json` | consolidated counts + FP/FN file lists per dataset/class |
| `scripts/` | the exact native runner scripts (below) |
| `examples/` | Mythril's output on the paper's figure contracts (see `examples/README.md`) |

## Runner scripts (`scripts/`)
The native run was driven by:
- `run_mythril_parallel.py` — main batch runner (per-pragma `solc`, the primary flags above)
- `rerun_failed_sbc.py`, `rerun_failed_solidifi.py` — heavy-contract recovery pass (depth 16 / 600 s)
- `run_mythril_rsd.sh`, `run_mythril_rsd_safe.sh` — RSD vulnerable / safe partitions

## Reproducing the table numbers in this repository
```bash
python scripts/make_predictions.py      # reads mythril/metrics_all_report.json + mythril/rsd/*.csv
python scripts/build_comparison.py      # -> tables/metrics_per_class.csv (Mythril rows)
python scripts/make_table8_timing.py    # -> Mythril column of Table 8 (median duration_s)
```

## Note on reproducibility (symbolic execution)
Mythril is a symbolic-execution tool: the set of states it explores within a
fixed `--execution-timeout` depends on the host's CPU/RAM and on SMT-solver
timing, so **re-runs are not bit-identical** — counts vary slightly between runs
and across machines. The numbers above are from a single consistent run of
v0.24.8 with the flags documented here. The same version is published as the
official image `smartbugs/mythril:0.24.8` for containerized re-runs on
adequately-resourced (≥32 GB RAM) hosts; on memory-constrained machines the
heaviest SBC/SolidiFI contracts will exceed the timeout and be reported N/A,
which is why those datasets are reported from the native release run.
