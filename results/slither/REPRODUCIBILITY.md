# Slither — reproducibility

This directory is provided for reproducibility: it contains the Slither results used for the
Slither columns of the comparison tables (Tables 4–8) and everything needed to reproduce those
numbers. The results were produced with Slither's **official Docker image**, so they do not
depend on any particular host machine.

## What "Slither" is
Slither (Trail of Bits), a source-level static analyser for Solidity. It is run here through
the SmartBugs distribution image, which packages a fixed Slither release together with the
`solc` versions the benchmarks need.

## Official Docker image
| | |
|---|---|
| Image | `smartbugs/slither:0.10.4` |
| Digest | `sha256:c5987e3b1de90de46ac197818dc6a17bbb61a751ba5406679c30b39ca90906d2` |
| Slither | 0.10.4 |
| solc | 0.4.26 / 0.5.17 / 0.6.12 / 0.7.6 / 0.8.28 (selected per contract from its pragma) |

Run (the runner `run_slither_docker.py` and the repository `datasets/` + `*_ground_truth.json`
are mounted at `/work`):
```bash
docker run --rm -v "$PWD":/work --entrypoint bash smartbugs/slither:0.10.4 \
    -c "cd /work && python3 run_slither_docker.py rsd && \
                    python3 run_slither_docker.py sbc && \
                    python3 run_slither_docker.py qian"
```

## Vulnerability coverage
| Class | Detector(s) used | Status |
|---|---|---|
| Reentrancy | `reentrancy-eth`, `reentrancy-benign`, `reentrancy-no-eth` | scored |
| Timestamp | `timestamp` (block-timestamp dependence) | scored |
| Integer overflow/underflow (IO/IU) | *none* — Slither has no arithmetic-overflow detector | N/A |
| TOD / front-running | *none* | N/A |

## Datasets and N/A rule
SBC (reentrancy + timestamp), Qian (reentrancy + timestamp) and RSD (reentrancy) are analysed.
SolidiFI is TOD-only, a class Slither has no detector for, so it is not run (`--`). A contract
is excluded (N/A) only when Slither emits no verdict (`status = COMPILE_ERROR`).

## Results (this image, scored against the repository ground truth)
RSD reentrancy 62/38/34/4 · SBC reentrancy 29/28/78/0 · SBC timestamp 14/9/112/0 ·
Qian reentrancy 68/12/140/1 · Qian timestamp 110/117/59/63 (TP/FP/TN/FN).

## Example contracts from the paper figures (`examples/`)
The figure contracts are not part of any dataset, so Slither's output on them is stored here
for the classes Slither supports.

| Contract | Paper figure | Slither verdict (committed) | Meaning |
|---|---|---|---|
| `reentrancysafe.sol` | Fig. 2(a)/(c) — reentrancy | no reentrancy finding (only an informational low-level-call note) | **correct true negative**: Slither does not flag the checks-effects-interactions-safe contract |

`examples/reentrancysafe.txt` is the actual Slither console output and `examples/reentrancysafe.sol`
the exact contract. (Slither has no IO/IU or TOD detector, so the `overflow.sol` and `egame.sol`
figures do not apply to it.)

## Reproducing the table numbers in this repository
```bash
python scripts/make_predictions.py      # reads slither/<ds>/summary/slither_<ds>_results.csv
python scripts/build_comparison.py      # -> tables/metrics_per_class.csv (Slither rows)
python scripts/make_table8_timing.py    # -> Slither column of Table 8 (median duration_s)
```
