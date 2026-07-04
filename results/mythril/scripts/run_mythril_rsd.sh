#!/usr/bin/env bash
# =============================================================================
# run_mythril_rsd_reentrant.sh
#
# Runs Mythril (myth analyze) on every _ree*.sol file in the reentrant
# split of the RSD dataset and collects:
#   - per-file raw log (stdout + stderr)
#   - per-file JSON output (via -o json)
#   - a final results CSV and summary table
#
# MYTHRIL CLI REFERENCE (verified from Mythril v0.24.8 docs):
#   myth analyze <file.sol> [options]
#
#   KEY FLAGS:
#     -o json                     Output format: json (we need this for parsing)
#     --max-depth 50              Symbolic execution recursion depth (default=22)
#     -t 5                        Transaction count: max transactions to explore
#                                 (default=2; increasing this is CRITICAL for
#                                 reentrancy — reentrancy needs ≥2 transactions)
#     --execution-timeout 300     Wall-clock seconds for symbolic execution engine
#                                 (default=86400, i.e. 24h — set per your budget)
#     --solver-timeout 25000      Z3 solver timeout in MILLISECONDS (default=25000)
#     --solv 0.8.20               Force specific solc version for compilation
#     --strategy dfs              Search strategy (dfs usually better for reentrancy)
#
#   IMPORTANT CLARIFICATION on your original command:
#     You wrote:  myth analyze ... -t 5 --max-depth 50 -t 5 --execution-timeout
#     ISSUE 1: -t 5 appears TWICE — only the last one takes effect.
#     ISSUE 2: -t is TRANSACTION COUNT, not timeout.
#              -t 5 means "explore up to 5 transactions."
#     ISSUE 3: --execution-timeout has no value in your command.
#              It needs a number of SECONDS, e.g. --execution-timeout 300
#     This script fixes all three issues.
#
# OVERNIGHT RUN BUDGET CALCULATION:
#   71 contracts × 300s execution-timeout = 21,300s ≈ 5.9 hours (worst case)
#   With --max-depth 50 and -t 5, most RSD contracts (< 30 lines) finish
#   well under 300s.  Total expected: 2-4 hours for the full batch.
#
# USAGE:
#   chmod +x run_mythril_rsd_reentrant.sh
#   nohup ./run_mythril_rsd_reentrant.sh > mythril_batch.log 2>&1 &
#   # check in the morning:
#   cat rsd_experiment/results/mythril_rsd_reentrant_summary.txt
#
# =============================================================================

set -euo pipefail

# ---------------------------------------------------------------------------
# CONFIGURATION
# ---------------------------------------------------------------------------

# Directory of reentrant contracts (from run_rsd_baselines.sh step 2)
REENTRANT_DIR="rsd_experiment/rsd_contracts/reentrant"

# Output directories
OUT_DIR="rsd_experiment/mythril_output"
RESULTS_DIR="rsd_experiment/results"

# Mythril analysis arguments
# Adjust these to match your paper's declared configuration:
TRANSACTION_COUNT=5        # -t: number of transactions (≥2 for reentrancy)
MAX_DEPTH=50               # --max-depth: symbolic execution tree depth
EXEC_TIMEOUT=300           # --execution-timeout: seconds per contract
SOLVER_TIMEOUT=25000       # --solver-timeout: milliseconds for Z3 per query
SOLC_VERSION="0.8.20"      # --solv: match RSD pragma

# Wall-clock timeout enforced by the 'timeout' command (safety net).
# Set to EXEC_TIMEOUT + 120s buffer for solc compilation + Mythril startup.
WALL_TIMEOUT=$((EXEC_TIMEOUT + 120))

# ---------------------------------------------------------------------------
# PRE-FLIGHT CHECKS
# ---------------------------------------------------------------------------

echo "============================================================"
echo " Mythril batch runner — RSD reentrant contracts"
echo " Started: $(date)"
echo "============================================================"

# Check myth is available
if ! command -v myth &>/dev/null; then
    echo "ERROR: 'myth' not found on PATH."
    echo "Install: pip3 install mythril"
    echo "Or activate the venv where Mythril is installed."
    exit 1
fi

MYTH_VERSION=$(myth version 2>/dev/null || echo "unknown")
echo "Mythril version : ${MYTH_VERSION}"

# Check reentrant dir
if [ ! -d "${REENTRANT_DIR}" ]; then
    echo "ERROR: ${REENTRANT_DIR} not found."
    echo "Run run_rsd_baselines.sh first, or manually populate with _ree*.sol files."
    exit 1
fi

TOTAL=$(find "${REENTRANT_DIR}" -maxdepth 1 -name "*_ree*.sol" | wc -l | tr -d ' ')
if [ "${TOTAL}" -eq 0 ]; then
    echo "ERROR: No *_ree*.sol files found in ${REENTRANT_DIR}"
    exit 1
fi

echo "Contracts found     : ${TOTAL}"
echo "Transaction count   : ${TRANSACTION_COUNT}"
echo "Max depth           : ${MAX_DEPTH}"
echo "Execution timeout   : ${EXEC_TIMEOUT}s per contract"
echo "Solver timeout      : ${SOLVER_TIMEOUT}ms per Z3 query"
echo "Solc version        : ${SOLC_VERSION}"
echo "Wall-clock limit    : ${WALL_TIMEOUT}s per contract"
echo "Output directory    : ${OUT_DIR}"
echo ""

mkdir -p "${OUT_DIR}" "${RESULTS_DIR}"

# Ensure solc version is installed
if command -v solc-select &>/dev/null; then
    echo "Installing solc ${SOLC_VERSION} via solc-select..."
    solc-select install "${SOLC_VERSION}" 2>/dev/null || true
    solc-select use "${SOLC_VERSION}" 2>/dev/null || true
    echo "Active solc: $(solc --version 2>/dev/null | tail -1)"
fi

# CSV header
RESULTS_CSV="${RESULTS_DIR}/mythril_rsd_reentrant_results.csv"
echo '"filename","ground_truth","mythril_flagged","swc107_count","exit_code","status","duration_s"' \
    > "${RESULTS_CSV}"

# ---------------------------------------------------------------------------
# MAIN LOOP
# ---------------------------------------------------------------------------

COUNTER=0
TP=0
FN=0
CRASH=0
BATCH_START=$(date +%s)

for SOLFILE in $(find "${REENTRANT_DIR}" -maxdepth 1 -name "*_ree*.sol" | sort); do

    BASENAME=$(basename "${SOLFILE}")
    STEM="${BASENAME%.sol}"
    COUNTER=$((COUNTER + 1))

    LOG_FILE="${OUT_DIR}/${STEM}.log"
    JSON_FILE="${OUT_DIR}/${STEM}.json"

    echo -n "[${COUNTER}/${TOTAL}] ${BASENAME} ... "
    FILE_START=$(date +%s)

    # -----------------------------------------------------------------
    # Run Mythril
    #
    # myth analyze <file>
    #   -o json              → structured output for parsing
    #   -t N                 → transaction count (NOT timeout)
    #   --max-depth N        → symbolic execution depth
    #   --execution-timeout  → seconds for the SE engine
    #   --solver-timeout     → milliseconds for Z3
    #   --solv               → force solc version
    #   --no-onchain-data    → don't query Infura (offline analysis)
    # -----------------------------------------------------------------

    EXIT_CODE=0
    timeout "${WALL_TIMEOUT}" \
        myth analyze "${SOLFILE}" \
            -o json \
            -t "${TRANSACTION_COUNT}" \
            --max-depth "${MAX_DEPTH}" \
            --execution-timeout "${EXEC_TIMEOUT}" \
            --solver-timeout "${SOLVER_TIMEOUT}" \
            --solv "${SOLC_VERSION}" \
            --no-onchain-data \
        > "${JSON_FILE}" 2>"${LOG_FILE}" \
        || EXIT_CODE=$?

    FILE_END=$(date +%s)
    DURATION=$((FILE_END - FILE_START))

    # -----------------------------------------------------------------
    # PARSE MYTHRIL JSON OUTPUT
    #
    # Mythril JSON format (with -o json):
    # {
    #   "error": null,
    #   "issues": [
    #     {
    #       "address": 1234,
    #       "contract": "ContractName",
    #       "description": "...",
    #       "function": "withdraw(uint256)",
    #       "max_gas_used": 99999,
    #       "min_gas_used": 1234,
    #       "severity": "High",
    #       "swc-id": "107",           ← THIS IS THE KEY: SWC-107 = reentrancy
    #       "title": "External Call To User-Supplied Address"
    #     }
    #   ],
    #   "success": true
    # }
    #
    # We count findings where "swc-id" == "107" (reentrancy).
    # Note: the JSON key is "swc-id" (hyphenated), NOT "swc_id".
    # -----------------------------------------------------------------

    FLAGGED=0
    SWC107_COUNT=0

    if [ -f "${JSON_FILE}" ] && [ -s "${JSON_FILE}" ]; then
        # Use Python for reliable JSON parsing (grep on JSON is fragile)
        SWC107_COUNT=$(python3 -c "
import json, sys
try:
    with open('${JSON_FILE}') as f:
        data = json.load(f)
    issues = data.get('issues', [])
    # Mythril uses 'swc-id' (string) in JSON output
    count = sum(1 for i in issues if str(i.get('swc-id', '')) == '107')
    print(count)
except Exception:
    print(0)
" 2>/dev/null || echo "0")

        if [ "${SWC107_COUNT}" -gt 0 ]; then
            FLAGGED=1
        fi
    fi

    # Classify result
    if [ "${EXIT_CODE}" -eq 124 ]; then
        STATUS="TIMEOUT"
        CRASH=$((CRASH + 1))
    elif [ "${EXIT_CODE}" -ne 0 ] && [ "${FLAGGED}" -eq 0 ]; then
        # Check if stderr has compilation errors
        if grep -qi "CompilerError\|ParserError\|Solc.*fatal\|Error compiling\|Traceback\|Exception" \
                "${LOG_FILE}" 2>/dev/null; then
            STATUS="CRASH_COMPILE"
            CRASH=$((CRASH + 1))
        elif grep -qi "timeout\|Timed out" "${LOG_FILE}" 2>/dev/null; then
            STATUS="TIMEOUT_INTERNAL"
            CRASH=$((CRASH + 1))
        else
            STATUS="NO_FINDING"
            FN=$((FN + 1))
        fi
    elif [ "${FLAGGED}" -eq 1 ]; then
        STATUS="FLAGGED_TP"
        TP=$((TP + 1))
    else
        STATUS="NO_FINDING"
        FN=$((FN + 1))
    fi

    # Print per-file result
    case "${STATUS}" in
        FLAGGED_TP)
            echo "TP (${SWC107_COUNT} SWC-107 finding(s)) [${DURATION}s]" ;;
        TIMEOUT|TIMEOUT_INTERNAL)
            echo "TIMEOUT [${DURATION}s]" ;;
        CRASH_COMPILE)
            echo "CRASH (compile error) [${DURATION}s]" ;;
        *)
            echo "not detected [${DURATION}s]" ;;
    esac

    # Write CSV row (all ground_truth = 1 for reentrant contracts)
    echo "\"${BASENAME}\",1,${FLAGGED},${SWC107_COUNT},${EXIT_CODE},${STATUS},${DURATION}" \
        >> "${RESULTS_CSV}"

done

BATCH_END=$(date +%s)
BATCH_DURATION=$((BATCH_END - BATCH_START))
BATCH_MINS=$((BATCH_DURATION / 60))

echo ""
echo "============================================================"
echo " BATCH COMPLETE — $(date)"
echo " Total wall-clock time: ${BATCH_DURATION}s (${BATCH_MINS} min)"
echo "============================================================"

# ---------------------------------------------------------------------------
# COMPUTE AND WRITE SUMMARY
# ---------------------------------------------------------------------------

SUMMARY_FILE="${RESULTS_DIR}/mythril_rsd_reentrant_summary.txt"

python3 - <<PYEOF
tp    = ${TP}
fn    = ${FN}
crash = ${CRASH}
total = ${TOTAL}
duration = ${BATCH_DURATION}
myth_ver = """${MYTH_VERSION}"""

# Recall variants
tp_fn_strict  = tp + fn + crash
tp_fn_lenient = tp + fn

recall_strict  = tp / tp_fn_strict  if tp_fn_strict  > 0 else 0.0
recall_lenient = tp / tp_fn_lenient if tp_fn_lenient > 0 else 0.0

lines = []
lines.append("=" * 65)
lines.append("MYTHRIL RSD REENTRANT SUBSET — RESULTS SUMMARY")
lines.append("=" * 65)
lines.append(f"Dataset      : RSD (Ressi et al., 2026), Solidity ^0.8.20")
lines.append(f"Subset       : Reentrant contracts only (_ree*.sol)")
lines.append(f"Total files  : {total}")
lines.append(f"Mythril ver  : {myth_ver.strip()}")
lines.append(f"Config       : -t ${TRANSACTION_COUNT}, --max-depth ${MAX_DEPTH}, "
             f"--execution-timeout ${EXEC_TIMEOUT}s, "
             f"--solver-timeout ${SOLVER_TIMEOUT}ms")
lines.append(f"Batch time   : {duration}s ({duration // 60} min)")
lines.append("=" * 65)
lines.append("")
lines.append(f"  TP    (reentrant, SWC-107 found)   : {tp}")
lines.append(f"  FN    (reentrant, no SWC-107)      : {fn}")
lines.append(f"  CRASH (timeout / compile error)    : {crash}")
lines.append("")
lines.append("  NOTE: All contracts have ground_truth = 1 (reentrant).")
lines.append("  FP and TN are not applicable here.")
lines.append("  Run the safe split separately for FP / TN counts.")
lines.append("")
lines.append(f"  Recall (strict,  crash=FN)  : {recall_strict:.1%}  "
             f"[{tp}/{tp_fn_strict}]")
lines.append(f"  Recall (lenient, crash excl): {recall_lenient:.1%}  "
             f"[{tp}/{tp_fn_lenient}]")
lines.append("")
lines.append("  SWC-107 = 'State access after external call'")
lines.append("  (Mythril's reentrancy detector)")
lines.append("")
lines.append("NEXT STEPS:")
lines.append("  1. Inspect CRASH/TIMEOUT rows:")
lines.append("     grep 'CRASH\\|TIMEOUT' ${RESULTS_CSV}")
lines.append("  2. Run the SAFE split for FP/TN:")
lines.append("     Copy this script, change REENTRANT_DIR to .../safe/")
lines.append("     and change _ree*.sol pattern to _safe*.sol")
lines.append("  3. Combine TP/FN (this) + FP/TN (safe) for full P/R/F1")
lines.append("=" * 65)

text = "\n".join(lines)
print(text)
with open("${SUMMARY_FILE}", "w") as f:
    f.write(text + "\n")
PYEOF

echo ""
echo "Results CSV : ${RESULTS_CSV}"
echo "Summary     : ${SUMMARY_FILE}"
echo "Per-file logs : ${OUT_DIR}/<filename>.log"
echo "Per-file JSON : ${OUT_DIR}/<filename>.json"
echo ""