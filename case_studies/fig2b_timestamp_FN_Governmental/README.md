# Fig. 2b / §7.2 — Timestamp Dependency (`Governmental`)

**Contract:** `governmental_survey.sol` — `invest()` stores `block.timestamp` in
`lastInvestmentTimestamp`; `resetInvestment()` later gates the payout on
`block.timestamp < lastInvestmentTimestamp + ONE_MINUTE`. The payout decision therefore
depends on a miner-influenceable timestamp across two functions. Manuscript
**Figure 2b** and the **Timestamp dependence** case study in §7.2. Missing this is a
**false negative**.

> **This file defines two contracts — `Governmental` (the vulnerable one) and
> `Attacker`.** Tools that report per contract emit a separate verdict for each; the
> vulnerability lives in `Governmental`, so the file-level verdict is the logical OR over
> its contracts. Read every contract's line before concluding — e.g. Oyente+ and Osiris
> print `False` for `Attacker` **and** `True` for `Governmental`.

## Verdicts (as produced by the files in this folder)

| Tool | File | Verdict (per contract where applicable) | Outcome |
|------|------|------------------------------------------|---------|
| **Our tool** | `ours.txt` | Timestamp Dependency: **VULNERABLE** | ✅ TP |
| Slither | `slither.txt` | `Governmental.resetInvestment() uses timestamp for comparisons` | ✅ TP |
| Oyente+ | `oyente_plus.txt` | `Attacker`: `False`; **`Governmental`: `Timestamp Dependency: True`** | ✅ TP |
| Osiris | `osiris.txt` | `Attacker`: `False`; **`Governmental`: `Time dependency bug: True`** | ✅ TP |
| Mythril | `mythril.txt` / `.json` | issues only on `Attacker` (SWC-123/107); **no SWC-116** on `Governmental` | ❌ **FN** |
| SmartCheck | `smartcheck.txt` | no timestamp rule fires | ❌ **FN** |
| EtherSolve | `ethersolve.txt` | no timestamp detector | — N/A |
| Vandal | `vandal.txt` | `verdict=0` (no timestamp detector) | — N/A |
| Sailfish | `sailfish.txt` | reentrancy/TOD-focused; no timestamp finding | — N/A |

The manuscript highlights **Mythril and SmartCheck** as the timestamp false negatives
(Mythril does not track the stored timestamp across functions; SmartCheck's XPath rule
matches the legacy `now` keyword, not `block.timestamp`) — and the files here confirm
exactly that: those two miss it, while our tool, Slither, Oyente+, and Osiris all report
the timestamp dependency on the `Governmental` contract. Our cross-function dependency +
abstract-state analysis (Example 5.17) reports it.

## Reproduce our result
```bash
conda run -n safpy python src/main.py \
  case_studies/fig2b_timestamp_FN_Governmental/governmental_survey.sol \
  --pipelines reentrancy,overflow,timestamp,tod
```
Baseline images/versions and exact commands: manuscript **Table 9**;
raw per-tool outputs under `results/<tool>/sbc/`.
