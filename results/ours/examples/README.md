# Our tool — example outputs

Committed runs of our analyzer on the paper's three figure / driving-example
contracts, so the verdicts can be confirmed by inspection without re-running.
These contracts are **not** part of any dataset; they are the illustrative
contracts from the manuscript (Fig. 1, Fig. 2, and the §7.2 case studies), kept
here to mirror the `examples/` folder shipped with every baseline
(`results/<tool>/examples/`).

Unlike the single-class baselines, our tool supports **all four** vulnerability
classes (reentrancy, integer overflow/underflow, timestamp dependency, TOD), so every example is a supported input and produces an applicable verdict. For each contract, `<name>.txt` is the verbatim console output of `src/main.py`.

**Environment / config.** Runs use the pinned `safpy` conda environment; `solc`
is auto-selected per pragma (`0.8.28` for the `^0.8.x` contracts, `0.5.17` for
the `^0.5.0` contract). Reentrancy and TOD are analyzed in the multi-domain
configuration (Box + Octagon + Polyhedra); the summary is domain-agnostic here
because all three domains agree.

| Contract               | Paper figure               | Class exercised            | Our verdict (committed)                                    | Outcome                                               |
| ---------------------- | -------------------------- | -------------------------- | ---------------------------------------------------------- | ----------------------------------------------------- |
| `reentrancysafe.sol` | Fig. 2a — reentrancy      | reentrancy (safe contract) | **Reentrancy: NOT VULNERABLE**                       | ✅ correct**true negative** (no false positive) |
| `overflow.sol`       | Fig. 1 — integer overflow | integer overflow           | **Integer Overflow: VULNERABLE**                     | ✅ correct**true positive**                     |
| `egame.sol`          | Fig. 2d / §7.2 — TOD     | TOD (and timestamp)        | **TOD: VULNERABLE**, **Timestamp: VULNERABLE** | ✅ correct**true positive**                     |

## `reentrancysafe.sol` — reentrancy **true negative** (solc 0.8.28)

A **safe** contract using checks-effects-interactions: the reward mapping is
zeroed **before** the external `call`, so re-entry finds a zero balance and
cannot drain funds. The analyzer inserts the reentrancy back-edge
(`ExpressionStatement_6 → IfStatement_0`) and runs the fixpoint in all three
domains; each proves the **balance-preservation invariant** holds at the claim:

```
[NO REENTRANCY] Balance-preservation invariant maintained at claim.   (Box, Octagon, Polka)
[SUMMARY] Reentrancy: NOT VULNERABLE
```

→ a correct true negative. This is the Fig. 2 driving example: pattern-based
detectors (e.g. Oyente+, Mythril) flag the guarded call as a **false positive**,
whereas our semantic invariant does not. See
`results/oyente_plus/examples/` and `results/mythril/examples/` for the
contrasting baseline verdicts on the same contract.

## `overflow.sol` — integer overflow **true positive** (solc 0.8.28)

A `uint8 fee` repeatedly multiplied by 3 in a loop (`fee = fee * 3`). The
overflow pipeline reports the unbounded arithmetic on the externally-influenced
loop:

```
[OVERFLOW] Variable fee (uint8) at ForLoopContinue_0: arithmetic op '*' with external input can exceed type max 255. (Solidity >=0.8: overflow reverts)
[SUMMARY] Integer Overflow: VULNERABLE
```

→ a correct true positive. (Under Solidity ≥0.8 the overflow is a checked
runtime revert rather than a silent wrap, but the value is still
attacker-reachable and the arithmetic is unsafe.)

## `egame.sol` — TOD (and timestamp) **true positive** (solc 0.5.17)

`winner` is assigned in `play()` (guarded by a `block.timestamp` condition) and
later used as the transfer recipient in `getReward()`. The order in which the
two functions are mined can change who receives the Ether — a transaction-
ordering dependence. The def–use analysis over `winner` reports it, and the
`block.timestamp` arithmetic is flagged as timestamp-dependent:

```
[TOD] Variable 'winner' is assigned in play() and used as ether transfer recipient in getReward(). Transaction reordering may change the transfer target.
[TIMESTAMP] block.timestamp/now used in arithmetic that computes a value.
[SUMMARY] Timestamp Dependency: VULNERABLE
[SUMMARY] TOD: VULNERABLE
```

→ correct true positives. Mythril and Oyente+ miss the TOD (false negatives);
Osiris cannot analyze the required Solidity version; Sailfish also reports it.
See `results/<tool>/examples/` for those verdicts.

## Reproduce

```bash
conda run -n safpy python src/main.py \
  results/ours/examples/<contract>.sol \
  --pipelines reentrancy,overflow,timestamp,tod
```

The verdict summary is deterministic and matches the committed `<name>.txt`
(timing lines vary run to run). The same three contracts, with every baseline's
output side by side, are also under `case_studies/` (Fig. 1, Fig. 2a,
Fig. 2d).
