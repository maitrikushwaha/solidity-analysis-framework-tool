#!/bin/bash
# Timed variant of run_inside.sh: same deterministic verdict rule, but also
# records per-contract wall-clock (duration_s) for Table 8. Outputs
# rel_hex,reentrant,status,duration_s to /work/vandal_timed.csv.
set -u
DL=/opt/vandal/datalog/demo_analyses.dl
TIMEOUT=120
JOBS=${JOBS:-2}

analyze_one() {
  local hex="$1"
  local rel="${hex#/work/bytecode/}"
  local raw="/work/raw/${rel%.hex}.txt"
  mkdir -p "$(dirname "$raw")"
  local work; work="$(mktemp -d)"
  cp "$hex" "$work/c.hex"
  ( cd "$work"
    local t0 t1 dur
    t0=$(date +%s.%N)
    if timeout "$TIMEOUT" analyze.sh c.hex "$DL" >/dev/null 2>err.log; then
      if [ -s reentrantCall.csv ]; then verdict=1; status=ok
      else verdict=0; status=ok; fi
      { echo "=== Vandal reentrantCall relation (non-empty => reentrant) ==="; \
        cat reentrantCall.csv 2>/dev/null; \
        echo "verdict=${verdict}"; } > "$raw"
    else
      verdict=0; status=error
      grep -qi "Terminated" err.log 2>/dev/null && status=timeout
      { echo "=== Vandal ${status} ==="; tail -5 err.log 2>/dev/null; } > "$raw"
    fi
    t1=$(date +%s.%N)
    dur=$(awk "BEGIN{printf \"%.2f\", $t1-$t0}")
    echo "${rel},${verdict},${status},${dur}"
  )
  rm -rf "$work"
}
export -f analyze_one
export DL TIMEOUT

echo "rel_hex,reentrant,status,duration_s" > /work/vandal_timed.csv
find /work/bytecode -name '*.hex' | sort | \
  xargs -P "$JOBS" -I{} bash -c 'analyze_one "$@"' _ {} >> /work/vandal_timed.csv
echo "DONE $(wc -l < /work/vandal_timed.csv) rows"
