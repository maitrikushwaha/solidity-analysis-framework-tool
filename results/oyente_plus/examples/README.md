# Oyente+ example outputs

Committed Oyente+ runs on the example contracts, so the verdicts can be confirmed by
inspection without re-running. Same pinned image (Oyente+ `e225d24`, z3-solver `4.14.1.0`)
and config `-t 10000 -glt 300 -dl 10000 -ll 10000`; solc selected per pragma.

For each contract, `<name>.txt` is the full Oyente+ console output and
`<name>.sol:<Contract>.json` is the structured result.

## `reentrancysafe.sol` — reentrancy **false positive** (solc 0.8.20, 81.9 % coverage)

A **safe** contract: checks-effects-interactions (the reward mapping is zeroed **before** the
external call), so re-entry finds a zero balance and cannot drain funds. Yet Oyente+ reports:

```
Re-Entrancy Vulnerability: True
```

→ a false positive (Oyente+'s pattern-based detector flags the guarded call at `16:28`).

This false positive is **robust**: see [`reentrancysafe_battery.txt`](reentrancysafe_battery.txt)
for the same contract run across a wide budget battery (Z3 `-t` 100 ms–30 s, `-glt` 50 s–7200 s,
`-dl`/`-ll` 50–50000) on **two** images — the reproducible build *and* the official Docker Hub
`smartbugs/oyente_plus@sha256:8c7fe9ec…` — with two solc versions (0.8.20 and 0.8.30). Every
budget that reaches the call site (≥81.9 % coverage), including the **default flagless** run,
reports `Re-Entrancy: True`. The only `False` verdicts come from starving the depth/loop limits
(`-dl 10`) until coverage collapses to 16–38 %, i.e. Oyente abandoning the path, not proving it safe.

## `egame.sol` — TOD **false negative** (solc 0.5.x, 82.8 % coverage)

A game whose `getReward()` payout depends on state (`winner`) set by `play()`, so its outcome
is transaction-ordering dependent. Oyente+ reports:

```
Transaction-Ordering Dependence (TOD): False   ← misses the TOD (false negative)
Timestamp Dependency:                  False
Integer Overflow:                      True     ← spurious flag on `startTime + 5 days`
```

(The contract uses 0.5.0+ syntax — `address payable` — so it is analyzed under `pragma ^0.5.0`.)

## `overflow.sol` — arithmetic on Solidity 0.8 (solc 0.8.0, 86.2 % coverage)

A `uint8 fee` multiplied by 3 in a loop. Oyente+ reports:

```
Integer Overflow:  False
Integer Underflow: False
(all other categories False)
```
