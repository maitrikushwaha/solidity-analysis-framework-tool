# Sailfish — reproducibility

This directory is provided for reproducibility: it contains the Sailfish results used for the
Sailfish columns of the comparison tables (Tables 4–8) and everything needed to reproduce those
numbers. The results were produced with Sailfish's **official Docker image**, so they do not
depend on any particular host machine.

## What "Sailfish" is
Sailfish (Bose et al., S&P 2022), a hybrid tool combining storage-dependency analysis with
symbolic evaluation, specialised for state-inconsistency bugs: reentrancy and
transaction-ordering dependence (TOD).

## Official Docker image
| | |
|---|---|
| Image | `holmessherlock/sailfish:latest` (the authors' published image) |
| Digest | `sha256:ba0770955356b0f7d9bcb25ba2c65af6042cf0256a2fa843c1b8aa4821c5d166` |
| Tool | `contractlint.py` (`-p DAO,TOD`, solver cvc4) |
| solc | 0.4.x / 0.5.x / 0.6.x (selected per contract; bundled in the image) |

Run (the runner `run_sailfish_docker.py` and the repository `datasets/` + `*_ground_truth.json`
are mounted at `/work`):
```bash
docker run --rm -v "$PWD":/work --entrypoint bash holmessherlock/sailfish:latest \
    -c "cd /work && python3 run_sailfish_docker.py all"
```
DAO dependencies map to **reentrancy** and TOD dependencies to **TOD**.

## Vulnerability coverage
| Class | Source | Status |
|---|---|---|
| Reentrancy | storage-dependency + symbolic check (DAO) | scored |
| TOD / front-running | storage-dependency + symbolic check (TOD) | scored |
| Integer overflow/underflow (IO/IU) | *none* — encoded as `-1` (no detector) | N/A |
| Timestamp | *none* — encoded as `-1` | N/A |

## Datasets and N/A rule
SBC (reentrancy + TOD), Qian (reentrancy) and SolidiFI (TOD) are analysed. RSD is Solidity
`^0.8.20`, which the image's compilers (≤ 0.6.x) cannot build, so all 138 contracts return
`COMPILE_ERROR` and RSD is N/A (`--`) — the per-contract evidence is committed in `rsd/`. A
contract is excluded (N/A) whenever Sailfish emits no verdict (`exit_status = COMPILE_ERROR`).

## Results (this image, scored against the repository ground truth)
SBC reentrancy 23/4/104/8 · SBC tod 2/62/73/2 · Qian reentrancy 46/2/151/23 ·
SolidiFI tod 40/5/43/1 (TP/FP/TN/FN).

## Example contracts from the paper figures (`examples/`)
| Contract | Paper figure | Sailfish verdict (committed) | Meaning |
|---|---|---|---|
| `egame.sol` | Fig. 2(d) — TOD | TOD dependency detected (composing `getReward`/`play`) | **true positive**: Sailfish flags the EGame transaction-ordering dependence |
| `reentrancysafe.sol` | Fig. 2(a)/(c) — reentrancy | `COMPILE_ERROR` | the figure contract is Solidity 0.8.20, beyond Sailfish's bundled compilers (≤ 0.6.x) |

`examples/<name>.txt` is the actual Sailfish output. (Sailfish has no IO/IU detector, so
`overflow.sol` does not apply to it.)

## Reproducing the table numbers in this repository
```bash
python scripts/make_predictions.py      # reads sailfish/<ds>/sailfish_metrics_<ds>.json
python scripts/build_comparison.py      # -> tables/metrics_per_class.csv (Sailfish rows)
python scripts/make_table8_timing.py    # -> Sailfish column of Table 8 (median duration_s)
```
