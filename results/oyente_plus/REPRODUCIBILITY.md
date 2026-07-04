# Oyente+ — reproducibility

This directory is provided for reproducibility: it contains the Oyente+ results used for the
Oyente+ columns of the comparison tables (Tables 4–8), together with everything needed to
reproduce those numbers from the committed per-contract outputs and to regenerate the verdicts
from scratch. The results were produced with a Docker image built from the official Oyente+
source (see *Docker image* below), so they do not depend on any particular host machine.

## What "Oyente+" is
Oyente (Luu et al., CCS 2016) via the **Oyente+** extension from SmartBugs
(`github.com/smartbugs/oyente_plus`, commit `e225d24`). Oyente+ adds Solidity 0.5–0.8
compiler support **without adding or changing any vulnerability detector**.

## Vulnerability coverage
Oyente+ detects all four classes evaluated in this study: **reentrancy**, **integer
overflow/underflow (IO/IU)**, **timestamp dependence**, and **transaction-ordering dependence
(TOD)**.

## Docker image
The Oyente+ verdicts were produced with a pinned Docker image **built locally from the
official Oyente+ source**, using the `Dockerfile`, `run_all_datasets.sh`, and `run_parallel.sh`
committed alongside this file **in this directory**. The image is tagged `oyente-plus-repro:latest`
(local image id
`sha256:ee602e77d171d95c2bb6910401e5b0b8116dd4e44c6e189fe130537cc71b651a`) and its base image is
pinned by digest, so verdicts do not depend on any particular host machine.

> **Note — this is *not* the Docker Hub image `smartbugs/oyente_plus`.** That registry image
> (`smartbugs/oyente_plus@sha256:8c7fe9eca284…`) is mutable and ships Oyente+'s *default*
> analysis budget; it does **not** reproduce the numbers reported here. Reproduction must use
> the image built from the `Dockerfile` in this directory at the source commit named below.
> Because this image is built locally, it has no pullable registry digest — it is pinned instead
> by its `Dockerfile`, its pinned base-image digest (below), and the Oyente+ source commit `e225d24`.

Build the image (turn-key from this directory):

```bash
docker build -t oyente-plus-repro:latest .
```

`run_all_datasets.sh` (run inside the image) and `run_parallel.sh` (the race-free driver that
launches it) are committed here as the **exact** invocation used: they encode the per-dataset
analysis budget tabulated below and select `solc` per contract. They reference the Oyente+ build
directory's `datasets/` layout and the `oyente-plus-repro:latest` tag; adjust the dataset path to
this repository's layout before re-running. The pinned components are listed below.

## Pinned environment (so verdicts don't depend on the host)
| Component | Pinned value |
|---|---|
| Base image | `python:3.11-slim@sha256:ae52c5bef62a6bdd42cd1e8dffef86b9cd284bde9427da79839de7a4b983e7ca` |
| z3-solver | `4.14.1.0` |
| crytic-compile | `0.3.8` |
| ethutils | git `10f15fa5` |
| solc | 32 versions pre-installed offline (0.4.0–0.8.30); chosen per-contract from `pragma`, floor-first with bump-on-failure (logged in `*/solc_per_contract_*.log`) |

## Per-dataset analysis budget (not uniform)
| Dataset | `-t` (z3 ms) | `-glt` (s) | `-dl` | `-ll` |
|---|---|---|---|---|
| SBC, SolidiFI | 300 | 600 | 10000 | 10000 |
| Qian | 7200 | 1800 | 10000 | 10000 |
| RSD | 10000 | 300 | 10000 | 10000 |

`-dl/-ll 10000` (vs Oyente defaults 50/10) let deep/looping reentrancy be reached; RSD's
mutex-guarded contracts need the extended `-t`/`-glt` or recall collapses to ~38 %.

## Verdict and exclusion rules
- **Multi-contract file:** positive if **any** contract in the `.sol` prints `True` (OR-rule).
- **N/A exclusion:** a contract is excluded **only when Oyente+ produces no verdict at all**
  (compile error / crash / hard-kill before any coverage line). A verdict emitted before a
  late timeout **is counted**. The 4 N/A contracts across all 1242:

  | Contract | exit | reason |
  |---|---|---|
  | `rsd/.../15_ReadOnly_ree2.sol` (vuln) | 124 | non-terminating, hard-kill |
  | `rsd/.../12_OnlyOwner_safe1.sol` (safe) | 137 | OOM (reproducible) |
  | `sbc/access_control/parity_wallet_bug_1.sol` | 1 | un-analyzable |
  | `qian/timestamp/safe/40737.sol` | 139 | reproducible segfault |

  Hence Oyente+ RSD denominators are vuln 65 / safe 71 (not 66/72), and Qian timestamp safe
  is 175 (not 176) — the same per-tool N/A convention used for Mythril.

## Committed evidence (one folder per dataset)
- `raw/<path>/<contract>.txt` — the actual Oyente+ console output (verdicts) per contract
- `manifest_<ds>.csv`, `oyente_results_<ds>.csv` — per-contract flags derived from `raw/`
- `metrics_<ds>.json`, `METRICS_SUMMARY.md` — TP/FP/TN/FN/P/R/F1 (against the GT in this repo)
- `solc_per_contract_<ds>.log` — compiler chosen per contract

## How the table numbers are reproduced **in this repository**
The Oyente+ columns are recomputed by the **main pipeline**, scoring the committed
per-contract verdicts against this repository's current ground truth (so the comparison stays
fair under the ground-truth revisions documented in the paper):

```bash
python scripts/make_predictions.py     # reads results/oyente_plus/<ds>/oyente_results_<ds>.csv
                                       #   + <ds>_ground_truth.json, applies the N/A rule
python scripts/build_comparison.py     # -> tables/metrics_per_class.csv  (Oyente+ rows)
```
These reproduce the Oyente+ values in `METRICS_SUMMARY.md` exactly (e.g. SBC reentrancy
29/9/101/2, Qian timestamp 1/15/160/172, RSD reentrancy 41/30/41/24).

## Example contracts from the paper figures (`examples/`)
Three contracts used as illustrative examples in the paper are **not part of any dataset**, so
their Oyente+ console output is pinned here (`examples/<name>.txt`) for direct confirmation of
the figure claims:

| Contract | Paper figure | Oyente+ verdict (committed) | Coverage | Meaning |
|---|---|---|---|---|
| `reentrancysafe.sol` | Fig. 2(a)/(c) — reentrancy | `Re-Entrancy = True` | 81.9 % | **false positive**: flags a checks-effects-interactions-safe contract (balance zeroed before the external call) |
| `overflow.sol` | Fig. 1 — overflow motivating example | `Integer Overflow = False`, `Integer Underflow = False` | 86.2 % | **false negative**: misses the `uint8 fee*3` overflow (fee reaches 729 > 255) |
| `egame.sol` | Fig. 2(d) — TOD | `Transaction-Ordering Dependence = False` | 82.8 % | **false negative**: misses the EGame transaction-ordering dependence |

Each `examples/<name>.txt` is the actual Oyente+ console output and `examples/<name>.sol` the
exact contract, so these verdicts can be confirmed by inspection. They substantiate Figures 1
and 2 with reproducible evidence rather than asserted behaviour.
