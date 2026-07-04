# Mythril on the paper's figure contracts (`examples/`)

The figure contracts are not part of any dataset, so Mythril's output on them is
stored here for the three classes Mythril supports (reentrancy = SWC-107,
integer overflow/underflow = SWC-101, TOD = SWC-114). Each `<name>.txt` is the
verbatim `myth analyze` console output of **Mythril v0.24.8** (the same version
used for the table results, identical to image `smartbugs/mythril:0.24.8`), run
with `--execution-timeout 60 --max-depth 22 -t 3 --solver-timeout 10000`.

| Contract | Paper figure | Class | `solc` | Mythril verdict (committed) | Meaning |
|---|---|---|---|---|---|
| `reentrancysafe.sol` | Fig. 2 — reentrancy | reentrancy (107) | 0.8.28 | **SWC-107 raised** — *External Call To User-Supplied Address* (Severity Low) | **false positive**: the contract is checks-effects-interactions-safe — `rewardsForA[msg.sender]` is zeroed at line 15 *before* the `msg.sender.call` at line 16, so a re-entrant call hits the zero-balance `require` and reverts. Mythril flags the external call regardless of the preceding state update. (It additionally raises **SWC-114/TOD** — also a false positive — and **SWC-105**, an out-of-scope class.) |
| `overflow.sol` | overflow — `FeeAccumulator` | overflow/underflow (101) | 0.8.28 | **No issues detected** | **correct**: under `pragma ^0.8.0` the `fee = fee * 3` overflow triggers the compiler's built-in checked-arithmetic revert rather than a silent wraparound, so there is no exploitable SWC-101 |
| `egame.sol` | TOD — `EGame` | TOD (114) | 0.5.0 | **No issues detected** | **false negative**: `egame.sol` is the TOD figure contract — the `getReward()` payout (`winner.transfer`) depends on the `winner` storage write made in `play()` — yet Mythril v0.24.8 raises no SWC-114. (Its `pragma` was changed from `^0.4.16` to `^0.5.0` so it compiles, since the contract uses `address payable`, a 0.5+ construct; without this it cannot be analysed at all.) Note the asymmetry: Mythril raises a *spurious* SWC-114 on the safe `reentrancysafe.sol` above but misses the genuine TOD here. |

`reentrancysafe.txt`, `overflow.txt` and `egame.txt` are the actual Mythril
console outputs and the `.sol` files are the exact contracts analysed.

The reentrancy false positive on `reentrancysafe.sol` is **configuration-robust**:
[`reentrancysafe_extended.txt`](reentrancysafe_extended.txt) records the same
contract analysed under the default `myth analyze` invocation plus three extended
budgets (`-t 3 --max-depth 50 --solver-timeout 30000`; `-t 4 --execution-timeout
300`; and `-t 3 --max-depth 22 --execution-timeout 300 --solver-timeout 10000
--solv 0.8.20 --no-onchain-data`). Mythril raises **SWC-107 at line 16 in every
one of them**, so the false positive does not depend on the search configuration.

### Note on Mythril's TOD (SWC-114) capability
On the `egame.sol` figure contract Mythril produces no SWC-114 finding (a false
negative, see above). Its `pragma` had to be changed from `^0.4.16` to `^0.5.0`
to compile, because the contract uses `address payable` (a 0.5+ construct) — the
`egame.sol` shipped here therefore carries `pragma solidity ^0.5.0`. Mythril's
broader TOD behaviour on real benchmarks is captured on the **SolidiFI** dataset,
where its SWC-114 detector scores **21 TP / 0 FP / 50 TN / 29 FN** (see
`../solidifi/`).
