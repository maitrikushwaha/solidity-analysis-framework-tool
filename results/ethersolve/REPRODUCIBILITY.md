# EtherSolve — reproducibility

This directory is provided for reproducibility: it contains the EtherSolve results used for the
EtherSolve rows of the comparison tables (Table 4 reentrancy, Table 8 timing) and everything
needed to reproduce them. EtherSolve was added at Reviewer 3.7's request and is run in a
**pinned Docker image**, so its results do not depend on any particular host machine.

## What "EtherSolve" is
EtherSolve (Pasqua et al., 2023), which reconstructs an accurate control-flow graph from EVM
bytecode; its `--re-entrancy` check flags reentrancy on that CFG.

## Docker image
| | |
|---|---|
| Image | `ethersolve-repro:v1.1` |
| Source | `SeUniVr/EtherSolve`, tag `V1.1`, commit `59fe4412f7` |
| Jar SHA-256 | `77fd261027958953fbaae7406c088e9670faf4ae58a99c684ca8709aea4c6775` |
| Runtime | Java 11 (`eclipse-temurin:11-jdk-jammy`) |
| Input | EVM **runtime bytecode** (`solc --bin-runtime`, solc pinned per contract pragma) |

Run (the runner re-runs the jar on the frozen bytecode, recording verdicts, raw findings and timing):
```bash
docker run --rm --entrypoint python3 -v "$PWD":/work ethersolve-repro:v1.1 /work/run_ethersolve_docker.py
```
Verdict rule: a contract is **reentrant** iff EtherSolve's `--re-entrancy` report is non-empty.
Deterministic on fixed bytecode.

## Vulnerability coverage
| Class | Status |
|---|---|
| Reentrancy (`--re-entrancy`) | scored |
| Integer overflow/underflow (IO/IU) | N/A — no detector |
| Timestamp | N/A — no detector |
| TOD | N/A — no detector |

## Datasets and N/A rule
SBC, Qian and RSD are analysed for reentrancy. SolidiFI (TOD-only) is N/A (`--`). A contract is
excluded (N/A) when EtherSolve cannot compile/analyze it (`COMPILE_FAIL`/`ANALYZE_FAIL`); this
affects one SBC contract.

## Results (this image, scored against the repository ground truth)
SBC reentrancy 30/56/54/1 · Qian reentrancy 65/82/71/4 · RSD reentrancy 0/0/72/66 (TP/FP/TN/FN).
(On RSD's Solidity-0.8 contracts EtherSolve compiles the bytecode but its reentrancy check fires
on none of them — recall 0 — which is itself the relevant finding.)

## Example contract from the paper figures (`examples/`)
| Contract | Paper figure | EtherSolve verdict (committed) | Meaning |
|---|---|---|---|
| `reentrancysafe.sol` | Fig. 2(a)/(c) — reentrancy | `--re-entrancy` report empty → not reentrant | **correct true negative**: does not flag the checks-effects-interactions-safe contract |

## Reproducing the table numbers in this repository
```bash
python scripts/make_predictions.py      # reads ethersolve/<ds>/ethersolve_results_<ds>.csv
python scripts/build_comparison.py      # -> tables/metrics_per_class.csv (EtherSolve rows)
python scripts/make_table8_timing.py    # -> EtherSolve column of Table 8 (median duration_s)
```
