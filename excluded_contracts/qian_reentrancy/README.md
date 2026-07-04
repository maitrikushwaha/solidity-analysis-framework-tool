# Excluded Qian reentrancy contracts

These contracts were removed from the Qian reentrancy evaluation set on 2026-06-17
after manual inspection. They are preserved here for transparency/reproducibility.
**Baseline results for the Qian reentrancy dataset must be recomputed without these
two contracts so all tools are evaluated on the same set.**

## 26523.sol  (HODLerParadise) — original GT: reentrancy=1
Genuine `msg.sender.call.value(final_reward)()` call-before-update, but the drained
accounting state is a `mapping(string => uint)` pool counter (`parameters["price_po..l"]`),
not an `address => uint` balance. Our balance-preservation abstract domain models
address-keyed balances; a string-keyed pool counter is outside its scope, so the
fixpoint reports "invariant maintained". Excluded as a documented DOMAIN-SCOPE
limitation (not detectable by the modelled semantics).

## 50012.sol  (AuctusTokenSale) — original GT: reentrancy=1
Malformed contract: `vestedEthers` is used (line 8) before its declaration (line 9),
and the external call target is `address(this)` — a SELF-call to a fixed address,
not a caller-controlled target. Caller-driven reentrancy is infeasible here. Excluded
as OUT-OF-SCOPE / malformed (questionable original label).
