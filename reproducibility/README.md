# Reproducibility — worked examples behind Figures 1–2 and the §7.2 case studies

This directory collects, **per figure / case-study contract**, the raw output of our
tool and every baseline, so the false-positive (FP) and false-negative (FN) claims made
in the manuscript can be confirmed by inspection without re-running the tools. It
supports **reviewer comment 2.4**.

Each subfolder contains the contract `.sol`, one `<tool>.txt` (verbatim tool output;
Mythril also has `<tool>.json`), and a `README.md` with the verdict table and the paper
reference. Baseline tool versions, Docker image digests, and exact commands are in
manuscript **Table 9**; the full per-dataset outputs live under `results/<tool>/`.

## Index

| Folder                                                                        | Paper               | Vulnerability     | Our tool | Baselines (FP/FN highlighted in the paper)                                                                          |
| ----------------------------------------------------------------------------- | ------------------- | ----------------- | -------- | ------------------------------------------------------------------------------------------------------------------- |
| [`fig1_overflow_FeeAccumulator/`](fig1_overflow_FeeAccumulator/)               | Fig 1 · §7.2 IO   | Integer overflow  | ✅ TP    | Mythril FN · Oyente+ FN · Osiris FN · Slither (no IO detector)                                                   |
| [`fig2a_reentrancy_FP_Reentrancy_safe/`](fig2a_reentrancy_FP_Reentrancy_safe/) | Fig 2a              | Reentrancy (safe) | ✅ no FP | Mythril·Oyente+·Vandal**FP** · Slither·EtherSolve TN · Osiris·SmartCheck·Sailfish N/A (cannot analyze) |
| [`fig2b_timestamp_FN_Governmental/`](fig2b_timestamp_FN_Governmental/)         | Fig 2b · §7.2 TS  | Timestamp         | ✅ TP    | Mythril·SmartCheck**FN** · Slither·Oyente+·Osiris TP · EtherSolve/Vandal/Sailfish N/A                    |
| [`fig2d_TOD_EGame/`](fig2d_TOD_EGame/)                                         | Fig 2d · §7.2 TOD | TOD               | ✅ TP    | Sailfish TP · Mythril**FN** · Oyente+ **FN** · Osiris N/A                                            |
| [`casestudy_reentrancy_LoopCrossMod/`](casestudy_reentrancy_LoopCrossMod/)     | §7.2 Reentrancy    | Reentrancy        | ✅ TP    | Slither/Oyente+/Vandal TP · Mythril/EtherSolve**FN** · SmartCheck/Osiris/Sailfish N/A                       |

Legend: **TP** true positive · **FP** false positive · **FN** false negative ·
**N/A** tool cannot analyze the contract (compiler/version incompatibility or no
detector for that class).

## Reproducing our tool's verdicts

```bash
conda run -n safpy python src/main.py <folder>/<Contract>.sol \
    --pipelines reentrancy,overflow,timestamp,tod
```

Each subfolder's README gives the exact command. Baseline runs are reproduced from the
images/commands in Table 9.
