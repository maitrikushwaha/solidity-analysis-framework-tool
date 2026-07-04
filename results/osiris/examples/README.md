Figure-contract evidence for Osiris (official Docker image `smartbugs/osiris:d1ecc37`, bundled solc 0.4.21).

- `egame.txt`, `reentrancysafe.txt`: the figure contracts are modern Solidity (0.5/0.8) beyond Osiris's bundled solc 0.4.21, so each `.txt` records the COMPILE_ERROR.
- `overflow.txt`: the Figure-1 FeeAccumulator pragma is back-ported to `^0.4.21` (the only version the image supports) so Osiris can actually analyze it. Osiris compiles and runs (99.5% code coverage) but reports no overflow — a genuine miss (false negative) caused by under-approximating the iterated `fee = fee*3` loop, not a compile failure. `overflow.sol` here is the back-ported source; the canonical `^0.8.0` version is in `results/oyente_plus/examples/overflow.sol`.
