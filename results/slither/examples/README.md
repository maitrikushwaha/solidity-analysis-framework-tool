# Slither on the paper's figure contracts (`examples/`)

The figure contracts are not part of any dataset, so Slither's output on them is
stored here for the classes Slither supports (reentrancy and timestamp; Slither
has no integer-overflow or TOD detector). Each `<name>.txt` is the verbatim
Slither console output produced by image `smartbugs/slither:0.10.4`.

| Contract | Paper figure | Class | Slither verdict (committed) | Meaning |
|---|---|---|---|---|
| `reentrancysafe.sol` | Fig. 2 — reentrancy | reentrancy | **No reentrancy finding** — only an *informational* low-level-call note plus version/naming warnings | **correct true negative**: Slither's `reentrancy-*` detectors do not fire on the checks-effects-interactions-safe contract (the balance is zeroed before the external call), so it raises no reentrancy false positive |

`reentrancysafe.txt` is the actual Slither console output and `reentrancysafe.sol`
the exact contract analysed. The `overflow.sol` and `egame.sol` figure contracts
are kept here for reference, but Slither has no integer-overflow or TOD detector,
so it produces no applicable finding for them.
