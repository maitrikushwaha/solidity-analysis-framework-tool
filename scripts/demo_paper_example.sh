#!/usr/bin/env bash
# Regenerate the paper's worked example (governmental_survey.sol) with the
# genuine multi-domain semantics-based collecting-semantics fixpoint
# (Interval/Box + Octagon + Polyhedra confirmation for timestamp & TOD —
# Example 5.16). The verdict is unchanged (timestamp=1, tod=1); this only
# enriches the per-contract evidence under results/ours/sbc/raw_output/ to show
# the relational fixpoint that the paper describes.
#
# Run this after any full `run_ours.py sbc` re-run (which uses the fast 'auto'
# path and would otherwise overwrite the example with structural-only output).
#
# Usage:
#   SAFPY=/home/maitri/miniconda3/envs/safpy/bin/python ./scripts/demo_paper_example.sh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PY="${SAFPY:-/home/maitri/miniconda3/envs/safpy/bin/python}"
EXAMPLE="$ROOT/datasets/sbc/time_manipulation/governmental_survey.sol"
OUT="$ROOT/results/ours/sbc/raw_output"

"$PY" "$ROOT/src/main.py" "$EXAMPLE" \
    --reentrancy-domain all --json --output-dir "$OUT" \
    --pipelines reentrancy,overflow,timestamp,tod

echo "[demo] regenerated governmental_survey with multi-domain fixpoint -> $OUT"
"$PY" - "$OUT/governmental_survey_verdicts.json" <<'PY'
import json, sys
j = json.load(open(sys.argv[1]))
assert j.get("timestamp") == 1 and j.get("tod") == 1, "verdict changed! expected timestamp=1, tod=1"
print("[demo] verdict preserved: timestamp=1, tod=1; confirm_fixpoint_times present:",
      bool(j.get("confirm_fixpoint_times")))
PY
