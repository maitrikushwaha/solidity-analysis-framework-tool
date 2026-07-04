# Fig. 2a — Reentrancy **False Positive** (`Reentrancy_safe`)

**Contract:** `Reentrancy_safe.sol` — a **safe** contract. `withdrawReward()` follows
checks-effects-interactions: `rewardsForA[msg.sender] = 0` is executed **before** the
external `call`, so a re-entrant call reads a zero balance and is stopped by
`require(amountToWithdraw > 0)`. The reward can be withdrawn only once.
Manuscript **Figure 2a**. A reentrancy report on this contract is a **false positive**.

## Verdicts (as produced by the files in this folder)

| Tool | File | Verdict | Outcome |
|------|------|---------|---------|
| **Our tool** | `ours.txt` | Reentrancy: **NOT VULNERABLE** | ✅ correct (no FP) |
| Mythril | `mythril.txt` | reports reentrancy | ❌ **FP** |
| Oyente+ | `oyente_plus.txt` | `Re-Entrancy Vulnerability: True` | ❌ **FP** |
| Vandal | `vandal.txt` | `reentrantCall` relation non-empty | ❌ **FP** |
| Slither | `slither.txt` | analyzed (93 detectors); no reentrancy finding | ✅ correct (TN) |
| EtherSolve | `ethersolve.txt` | compiled (solc 0.8.20); 0 finding rows | ✅ correct (TN) |
| Osiris | `osiris.txt` | `CRITICAL: Solidity compilation failed` | — N/A (cannot compile ^0.8.20) |
| SmartCheck | `smartcheck.txt` | parser error on `.call{value:}` (`no viable alternative`); external call not analyzed | — N/A (parser predates ≥0.6 call syntax) |
| Sailfish | `sailfish.txt` | COMPILE_ERROR (bundled solc ≤0.6 vs ^0.8.20) | — N/A (cannot compile) |

The manuscript highlights **Mythril and Oyente+** as the reentrancy false positives;
the files here show **Vandal** false-positives as well. **Slither** and **EtherSolve**
successfully analyze the contract and correctly report no reentrancy (true negatives).
**Osiris**, **SmartCheck**, and **Sailfish** do **not** analyze this contract — Osiris and
Sailfish fail to compile the `^0.8.20` source and SmartCheck's parser errors on the
`.call{value:}` syntax — so their silence is *not* a true negative. Our analysis checks
feasibility of re-entry from the contract state at the call site (Algorithm 2), so it does
not flag it.

## Reproduce our result
```bash
conda run -n safpy python src/main.py \
  reproducibility/fig2a_reentrancy_FP_Reentrancy_safe/Reentrancy_safe.sol \
  --pipelines reentrancy,overflow,timestamp,tod
```
Baseline images/versions and exact commands: manuscript **Table 9** and `results/<tool>/examples/`.
