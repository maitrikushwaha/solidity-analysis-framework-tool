# Vandal — reproducibility

This directory is provided for reproducibility: it contains the Vandal results used for the
Vandal rows of the comparison tables (Table 4 reentrancy, Table 8 timing) and everything needed
to reproduce them. Vandal was added at Reviewer 3.7's request and is run in a **pinned Docker
image**, so its results do not depend on any particular host machine.

## What "Vandal" is
Vandal (Brent et al., 2018), a logic-driven static analyzer that decompiles EVM bytecode to a
register-transfer IR and expresses security analyses as Soufflé/Datalog specifications.

## Docker image
| | |
|---|---|
| Image | `vandal:pinned-d2b0043` |
| Source | `usyd-blockchain/vandal`, commit `d2b0043` (2020-07-29) |
| Runtime | Ubuntu 18.04, Soufflé 2.0.2, Python 3.6.9 |
| Input | EVM **runtime bytecode** (`solc --bin-runtime`, solc pinned per contract pragma) |

Run (the runner `run_vandal_docker.sh` analyses every `.hex` under `bytecode/`):
```bash
docker run --rm -v "$PWD":/work vandal:pinned-d2b0043 bash /work/run_vandal_docker.sh
```
Verdict rule: a contract is **reentrant** iff Vandal's `reentrantCall` relation is non-empty.
Deterministic: identical bytecode → identical verdict.

## Vulnerability coverage
| Class | Status |
|---|---|
| Reentrancy (`reentrantCall`) | scored |
| Integer overflow/underflow (IO/IU) | N/A — no detector |
| Timestamp | N/A — no detector |
| TOD | N/A — no detector |

Vandal's bundled specification implements `reentrantCall`, `uncheckedCall`, `unsecuredValueSend`,
`destroyable`, `originUsed`; of our four classes only **reentrancy** applies.

## Datasets and N/A rule
SBC, Qian and RSD are analysed for reentrancy. SolidiFI (TOD-only) is N/A (`--`). A contract is
excluded (N/A) when Vandal produces no verdict (decompilation/analysis failure or timeout); on
RSD a few contracts are excluded this way.

## Results (this image, scored against the repository ground truth)
SBC reentrancy 20/48/63/11 · Qian reentrancy 62/137/16/7 · RSD reentrancy 61/51/19/4 (TP/FP/TN/FN).

## Example contract from the paper figures (`examples/`)
| Contract | Paper figure | Vandal verdict (committed) | Meaning |
|---|---|---|---|
| `reentrancysafe.sol` | Fig. 2(a)/(c) — reentrancy | `reentrantCall` non-empty → reentrant | **false positive**: flags the checks-effects-interactions-safe contract (detects the external-call pattern without modelling that the balance is zeroed first) |

## Reproducing the table numbers in this repository
```bash
python scripts/make_predictions.py      # reads vandal/<ds>/vandal_results_<ds>.csv
python scripts/build_comparison.py      # -> tables/metrics_per_class.csv (Vandal rows)
python scripts/make_table8_timing.py    # -> Vandal column of Table 8 (median duration_s)
```
