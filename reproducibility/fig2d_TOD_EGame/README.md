# Fig. 2d / §7.2 — Transaction-Ordering Dependence (`EGame`)

**Contract:** `EGame.sol` — `winner` is assigned in `play()` (guarded by a
`block.timestamp` condition) and later used as the transfer recipient in
`getReward()`. The order in which the two functions are mined can change who
receives the Ether — a TOD vulnerability. Manuscript **Figure 2d** and the
**Transaction-ordering dependence** case study in §7.2. Missing this is a
**false negative**.

## Verdicts (as produced by the files in this folder)

| Tool | File | Verdict | Outcome |
|------|------|---------|---------|
| **Our tool** | `ours.txt` | TOD: **VULNERABLE** (also Timestamp) | ✅ TP |
| Sailfish | `sailfish.txt` | "TOD dependency detected … composing getReward and play" | ✅ TP |
| Mythril | `mythril.txt` | "No issues were detected" | ❌ **FN** |
| Oyente+ | `oyente_plus.txt` | `Transaction-Ordering Dependence (TOD): False` | ❌ **FN** |
| Osiris | `osiris.txt` | `======= error =======` (cannot analyze this version) | — N/A |

The manuscript notes **Sailfish also reports** this contract, while **Mythril and
Oyente+** miss it and **Osiris** cannot analyze the required Solidity version. Our
def–use analysis over `winner` with the three Algorithm-4 checks (Example 5.18)
reports the TOD.

## Reproduce our result
```bash
conda run -n safpy python src/main.py \
  reproducibility/fig2d_TOD_EGame/EGame.sol \
  --pipelines reentrancy,overflow,timestamp,tod
```
Baseline images/versions and exact commands: manuscript **Table 9** and `results/<tool>/examples/`.
