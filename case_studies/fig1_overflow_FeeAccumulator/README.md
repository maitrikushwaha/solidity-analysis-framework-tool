# Fig. 1 / §7.2 — Integer Overflow (`FeeAccumulator`)

**Contract:** `FeeAccumulator.sol` — `applyCompoundFee()` repeatedly multiplies the
`uint8` state variable `fee` by 3 in a loop. For `periods >= 5` the value exceeds
the `uint8` maximum (255). Manuscript **Figure 1** (motivating example) and the
**Integer overflow/underflow** case study in §7.2.

## Verdicts (as produced by the files in this folder)

| Tool | File | Verdict | Outcome |
|------|------|---------|---------|
| **Our tool** | `ours.txt` | Integer Overflow: **VULNERABLE** | ✅ TP |
| Mythril | `mythril.txt` | "No issues were detected" | ❌ FN |
| Oyente+ | `oyente_plus.txt` | Integer Overflow: `False`, Underflow: `False` | ❌ FN |
| Osiris | `osiris.txt` | no overflow (loop iteration under-approximated) | ❌ FN |
| Slither | — | no integer-overflow detector | — N/A |

Our interval-domain fixpoint (Algorithm 3) widens `fee` to `[0, +∞)`, which exceeds
the declared `uint8` bound, so the overflow is reported. See manuscript §7.2.

## Reproduce our result
```bash
conda run -n safpy python src/main.py \
  case_studies/fig1_overflow_FeeAccumulator/FeeAccumulator.sol \
  --pipelines reentrancy,overflow,timestamp,tod
```
Baseline images/versions and exact commands: manuscript **Table 9** and `results/<tool>/examples/`.
