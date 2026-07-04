# Excluded RSD reentrancy contracts — out of scope of the numerical abstract domain

These 5 reentrancy-vulnerable contracts were removed from the RSD reentrancy
evaluation on 2026-06-17 and preserved here for transparency/reproducibility.
**Baseline results for the RSD reentrancy dataset must be recomputed without these
contracts so all tools are evaluated on the same set.**

## Rationale (verified against the tool's own output)
Our framework detects reentrancy as a BALANCE-PRESERVATION invariant (Algorithm 1
/ Algorithm 2) over APRON numerical abstract domains (Interval/Octagon/Polyhedra).
APRON is a *numerical* abstract-domain library: it models relations over integer/
rational program variables (e.g. ether balances moved by `.call.value()` /
`.call{value:}` transfers). Reentrancy that is NOT expressible as a numerical
ether-balance property is outside this domain — no external-call encoding is built,
so Alg 1 / Alg 2 do not apply. For each contract below the tool reports
"[CFG] No reentrancy back-edge: no external-call encoding detected."

### 14_DelegateCall_ree1.sol … ree4.sol  (GT reentrancy=1)
Reentrancy via `logic.delegatecall(abi.encodeWithSignature("withdraw(address)", ...))`.
`delegatecall` executes external code in THIS contract's storage context — a
code/storage-semantics operation, not an ether-value transfer. Delegatecall
behaviour cannot be represented in a numerical abstract domain, and no
balance-preservation invariant governs it. (ree2/ree3/ree4 additionally wrap the
call in broken/partial `nonReentrant` mutexes — also non-numerical reasoning.)

### 00_BasicInline_ree1.sol  (GT reentrancy=1)
`balances[msg.sender] -= SomeInterface(a).someFunction();` — the external call is a
non-ether interface method call returning a uint, inlined into the balance
arithmetic. No ether is transferred, so the ether-conservation balance-preservation
invariant does not model it; this is a structural/callback reentrancy outside the
numerical domain.
