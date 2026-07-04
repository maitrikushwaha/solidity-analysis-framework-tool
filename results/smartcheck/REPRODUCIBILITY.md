# SmartCheck — reproducibility

This directory is provided for reproducibility: it contains the SmartCheck results used for the
SmartCheck columns of the comparison tables (Tables 4–8) and everything needed to reproduce
those numbers. The results were produced with SmartCheck's **official Docker image**, so they
do not depend on any particular host machine.

## What "SmartCheck" is
SmartCheck (SmartDec), an ANTLR-based static analyser that matches rules on the Solidity source
/ parse tree. It does not compile to EVM, so it needs no `solc` and analyses contracts across
compiler versions.

## Official Docker image
| | |
|---|---|
| Image | `smartbugs/smartcheck:latest` |
| Digest | `sha256:3d1e348d7e8e34a9eb59cc70cd7a8020f706c44080272e2fd92ae4ebd9b58b34` |
| Tool | SmartCheck CLI (`ru.smartdec.smartcheck`) |
| solc | not required (source-level analysis) |

Run (the runner `run_smartcheck_docker.py` and the repository `datasets/` + `*_ground_truth.json`
are mounted at `/work`):
```bash
docker run --rm -v "$PWD":/work --entrypoint bash smartbugs/smartcheck:latest \
    -c "cd /work && python3 run_smartcheck_docker.py all"
```

## Vulnerability coverage
| Class | Rule(s) used | Status |
|---|---|---|
| Reentrancy | `SOLIDITY_CALL_WITHOUT_DATA`, `SOLIDITY_SEND`, `SOLIDITY_UNCHECKED_CALL` | scored |
| Timestamp | `SOLIDITY_EXACT_TIME` | scored |
| Integer overflow/underflow (IO/IU) | *none* — encoded as `-1` (no detector) | N/A |
| TOD / front-running | *none* — encoded as `-1` | N/A |

## Datasets and N/A rule
SBC (reentrancy + timestamp), Qian (reentrancy + timestamp) and RSD (reentrancy) are analysed.
SolidiFI is TOD-only, a class SmartCheck has no detector for, so it is not run (`--`). SmartCheck
parses every contract (no compiler step), so all runs complete (`exit_status = OK`); the `-1`
prediction marks the unsupported classes and is never counted as a negative.

## Results (this image, scored against the repository ground truth)
RSD reentrancy 5/12/60/61 · SBC reentrancy 29/56/55/2 · SBC timestamp 1/0/128/13 ·
Qian reentrancy 62/110/43/7 · Qian timestamp 2/1/175/171 (TP/FP/TN/FN).

## Example contracts from the paper figures (`examples/`)
| Contract | Paper figure | SmartCheck verdict (committed) | Meaning |
|---|---|---|---|
| `reentrancysafe.sol` | Fig. 2(a)/(c) — reentrancy | no reentrancy rule fires | **correct true negative**: SmartCheck does not flag the checks-effects-interactions-safe contract |

`examples/reentrancysafe.txt` is the actual SmartCheck output and `examples/reentrancysafe.sol`
the exact contract. (SmartCheck has no IO/IU or TOD detector, so the `overflow.sol` and
`egame.sol` figures do not apply to it.)

## Reproducing the table numbers in this repository
```bash
python scripts/make_predictions.py      # reads smartcheck/<ds>/smartcheck_results_<ds>.csv
python scripts/build_comparison.py      # -> tables/metrics_per_class.csv (SmartCheck rows)
python scripts/make_table8_timing.py    # -> SmartCheck column of Table 8 (median duration_s)
```
