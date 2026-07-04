# Osiris — reproducibility

This directory is provided for reproducibility: it contains the Osiris results used for the
Osiris columns of the comparison tables (Tables 4–8) and everything needed to reproduce those
numbers. The results were produced with Osiris's **official Docker image**, so they do not
depend on any particular host machine.

## What "Osiris" is
Osiris (Torres et al.), a symbolic-execution tool specialised for integer bugs, built on the
Oyente engine. It is run here through the SmartBugs distribution image.

## Official Docker image
| | |
|---|---|
| Image | `smartbugs/osiris:d1ecc37` |
| Digest | `sha256:17cf6e59968191b43e330b9f4a64e70ebb1cfc34a27e7b4d16f91970ff925ec9` |
| Tool | Osiris (`/root/osiris/osiris.py`) |
| solc | `0.4.21` (the only compiler bundled in the image) |

Run (the runner `run_osiris_docker.py` and the repository `datasets/` + `*_ground_truth.json`
are mounted at `/work`):
```bash
docker run --rm -v "$PWD":/work --entrypoint bash smartbugs/osiris:d1ecc37 \
    -c "cd /work && python3 run_osiris_docker.py all"
```
Because the image ships only `solc 0.4.21`, the 0.4.x benchmark contracts (SBC, Qian) declare
newer 0.4.x pragmas; the runner normalises each pragma to `^0.4.21` before analysis (the same
back-porting the original Osiris evaluation uses) so its compiler accepts them. Contracts that
genuinely require a newer compiler (RSD = 0.8.x, SolidiFI = 0.5.x) cannot be compiled and are
reported as `COMPILE_ERROR`.

## Vulnerability coverage
| Class | Source | Status |
|---|---|---|
| Integer overflow/underflow (IO/IU) | Osiris' integer-error analysis (its specialty) | scored |
| Reentrancy | Oyente base | scored |
| Timestamp | Oyente base | scored |
| TOD | Oyente base | scored |

Osiris detects all four classes, but only on contracts its `solc 0.4.21` can compile.

## Datasets and N/A rule
SBC (all four classes) and Qian (reentrancy + IO/IU + timestamp) are analysed. RSD (Solidity
`^0.8.20`) and SolidiFI (Solidity `^0.5.1`) cannot be compiled by `solc 0.4.21`, so every
contract returns `COMPILE_ERROR` and those datasets are N/A (`--`) — the per-contract evidence
is committed in `rsd/summary/` and `solidifi/summary/`. A contract is excluded (N/A) whenever
Osiris emits no verdict (compile error / timeout / crash).

## Results (this image, scored against the repository ground truth)
SBC: reentrancy 12/22/69/14 · overflow 13/46/56/2 · timestamp 3/1/103/10 · tod 2/26/89/0.
Qian: reentrancy 64/139/14/5 · overflow 52/18/169/34 · timestamp 2/16/157/164 (TP/FP/TN/FN).

## Example contracts from the paper figures (`examples/`)
| Contract | Paper figure | Osiris verdict (committed) | Meaning |
|---|---|---|---|
| `reentrancysafe.sol` | Fig. 2 — reentrancy | `COMPILE_ERROR` | the figure contract is Solidity 0.8.20, beyond Osiris's `solc 0.4.21` |
| `overflow.sol` | Fig. 1 — IO/IU | `COMPILE_ERROR` | the figure contract is Solidity 0.8.0, beyond Osiris's `solc 0.4.21` |
| `egame.sol` | Fig. 2(d) — TOD | `COMPILE_ERROR` | the figure contract is Solidity 0.5.0, beyond Osiris's `solc 0.4.21` |

`examples/<name>.txt` is the actual Osiris console output. Osiris supports all four classes but
its bundled compiler cannot build these modern-Solidity figure contracts, which is itself the
relevant finding.

## Reproducing the table numbers in this repository
```bash
python scripts/make_predictions.py      # reads osiris/sbc/summary/osiris_sbc_classification.json + qian CSV
python scripts/build_comparison.py      # -> tables/metrics_per_class.csv (Osiris rows)
python scripts/make_table8_timing.py    # -> Osiris column of Table 8 (median duration_s)
```
