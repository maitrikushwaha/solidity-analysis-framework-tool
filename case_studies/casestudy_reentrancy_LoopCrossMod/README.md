# §7.2 — Reentrancy case study (`LoopCrossMod`)

**Contract:** `LoopCrossMod.sol` (RSD `13_LoopCrossMod_ree1`). In `payAll()`, Ether is
sent to each recipient via `r.call{value: balances[r]}("")` **before** `balances[r] = 0`.
The `nonReentrant` modifier does **not** protect the body — `flag` is never set to `true`
before execution — so a malicious recipient can re-enter and be paid more than once.
Manuscript **§7.2, Reentrancy**. Reporting this is a true positive.

## Verdicts (as produced by the files in this folder)

| Tool | File | Verdict | Outcome |
|------|------|---------|---------|
| **Our tool** | `ours.txt` | Reentrancy: **VULNERABLE** | ✅ TP |
| Slither | `slither.txt` | "Reentrancy in C.payAll(...)" | ✅ TP |
| Oyente+ | `oyente_plus.txt` | `Re-Entrancy Vulnerability: True` | ✅ TP |
| Vandal | `vandal.txt` | `verdict=1` (reentrantCall non-empty) | ✅ TP |
| Mythril | `mythril.txt` / `.json` | `"issues": []` | ❌ **FN** |
| EtherSolve | `ethersolve.txt` | compiled; 0 finding rows | ❌ **FN** |
| SmartCheck | `smartcheck.txt` | parser error on `.call{value:}`; external call not analyzed | — N/A&nbsp;* (parser) |
| Osiris | `osiris.txt` | `Solidity compilation failed` (`======= error =======`) | — N/A |
| Sailfish | — | cannot analyze (compiler compatibility) | — N/A |

This matches the manuscript: **Slither, Oyente+, and Vandal** report the vulnerability;
**Mythril and EtherSolve** analyze it but do not report it (false negatives); **SmartCheck,
Osiris, and Sailfish** cannot analyze the contract. Our analysis models re-entry at the
external call and applies the balance-preservation invariant (Algorithm 2).

> \* SmartCheck 2.0.3's parser errors on the `.call{value:}` syntax (Solidity ≥0.6), so it
> never analyzes the external call. The manuscript groups it among the tools that do not
> report the vulnerability; here it is labeled N/A because the call — the vulnerability-relevant
> statement — is not parsed, so this is a tool limitation rather than a genuine miss.

## Reproduce our result
```bash
conda run -n safpy python src/main.py \
  case_studies/casestudy_reentrancy_LoopCrossMod/LoopCrossMod.sol \
  --pipelines reentrancy,overflow,timestamp,tod
```
Baseline images/versions and exact commands: manuscript **Table 9**;
raw per-tool outputs under `results/<tool>/rsd/`.
