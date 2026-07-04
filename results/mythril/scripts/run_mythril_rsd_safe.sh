#!/usr/bin/env bash
# =============================================================================
# run_mythril_rsd_safe.sh
#
# Runs Mythril (myth analyze) on every _safe*.sol file in the SAFE split
# of the RSD dataset and collects:
#   - per-file raw log (stderr)
#   - per-file JSON output (via -o json)
#   - a final results/mythril_rsd_safe_results.csv
#   - a final results/mythril_rsd_safe_summary.txt
#
# This script is the SAFE-SPLIT MIRROR of run_mythril_rsd_reentrant.sh.
# ALL Mythril arguments are IDENTICAL to the reentrant run.
# The only differences are:
#   - SAFE_DIR instead of REENTRANT_DIR
#   - File pattern: *_safe*.sol  instead of  *_ree*.sol
#   - ground_truth = 0  (not vulnerable)
#   - Metrics:  FP (safe flagged as reentrancy) and TN (safe, clean)
#               instead of TP / FN
#
# USAGE:
#   chmod +x run_mythril_rsd_safe.sh
#   nohup ./run_mythril_rsd_safe.sh > mythril_safe_batch.log 2>&1 &
#   # check in the morning:
#   cat rsd_experiment/results/mythril_rsd_safe_summary.txt
# =============================================================================

set -euo pipefail

# ---------------------------------------------------------------------------
# CONFIGURATION — must be IDENTICAL to run_mythril_rsd_reentrant.sh
# ---------------------------------------------------------------------------

# Safe contracts directory
SAFE_DIR="rsd_experiment/rsd_contracts/safe"

# Output directories — separate from reentrant outputs
OUT_DIR="rsd_experiment/mythril_output_safe"
RESULTS_DIR="rsd_experiment/results"

# Mythril arguments — IDENTICAL to reentrant run for comparability
TRANSACTION_COUNT=5
MAX_DEPTH=50
EXEC_TIMEOUT=300
SOLVER_TIMEOUT=25000
SOLC_VERSION="0.8.20"

WALL_TIMEOUT=$((EXEC_TIMEOUT + 120))

# ---------------------------------------------------------------------------
# PRE-FLIGHT CHECKS
# ---------------------------------------------------------------------------

echo "============================================================"
echo " Mythril batch runner — RSD SAFE contracts"
echo " Started: $(date)"
echo "============================================================"

if ! command -v myth &>/dev/null; then
    echo "ERROR: 'myth' not found on PATH."
    echo "Install: pip3 install mythril  OR activate your venv."
    exit 1
fi

MYTH_VERSION=$(myth version 2>/dev/null || echo "unknown")
echo "Mythril version : ${MYTH_VERSION}"

if [ ! -d "${SAFE_DIR}" ]; then
    echo "ERROR: ${SAFE_DIR} not found."
    echo "Run run_rsd_baselines.sh first, or manually populate with _safe*.sol files."
    exit 1
fi

TOTAL=$(find "${SAFE_DIR}" -maxdepth 1 -name "*_safe*.sol" | wc -l | tr -d ' ')
if [ "${TOTAL}" -eq 0 ]; then
    echo "ERROR: No *_safe*.sol files found in ${SAFE_DIR}"
    exit 1
fi

echo "Safe contracts found : ${TOTAL}"
echo "Transaction count    : ${TRANSACTION_COUNT}"
echo "Max depth            : ${MAX_DEPTH}"
echo "Execution timeout    : ${EXEC_TIMEOUT}s per contract"
echo "Solver timeout       : ${SOLVER_TIMEOUT}ms per Z3 query"
echo "Solc version         : ${SOLC_VERSION}"
echo "Wall-clock limit     : ${WALL_TIMEOUT}s per contract"
echo "Output directory     : ${OUT_DIR}"
echo ""

mkdir -p "${OUT_DIR}" "${RESULTS_DIR}"

# Ensure solc version is installed
if command -v solc-select &>/dev/null; then
    echo "Installing solc ${SOLC_VERSION} via solc-select..."
    solc-select install "${SOLC_VERSION}" 2>/dev/null || true
    solc-select use "${SOLC_VERSION}" 2>/dev/null || true
    echo "Active solc: $(solc --version 2>/dev/null | tail -1)"
fi

# CSV header — ground_truth=0 for all safe contracts
RESULTS_CSV="${RESULTS_DIR}/mythril_rsd_safe_results.csv"
echo '"filename","ground_truth","mythril_flagged","swc107_count","exit_code","status","duration_s"' \
    > "${RESULTS_CSV}"

# ---------------------------------------------------------------------------
# MAIN LOOP
# ---------------------------------------------------------------------------

COUNTER=0
FP=0        # safe AND flagged by Mythril (false alarm)
TN=0        # safe AND NOT flagged (correct)
CRASH=0     # timeout or compile error
BATCH_START=$(date +%s)

for SOLFILE in $(find "${SAFE_DIR}" -maxdepth 1 -name "*_safe*.sol" | sort); do

    BASENAME=$(basename "${SOLFILE}")
    STEM="${BASENAME%.sol}"
    COUNTER=$((COUNTER + 1))

    LOG_FILE="${OUT_DIR}/${STEM}.log"
    JSON_FILE="${OUT_DIR}/${STEM}.json"

    echo -n "[${COUNTER}/${TOTAL}] ${BASENAME} ... "
    FILE_START=$(date +%s)

    # -----------------------------------------------------------------
    # Run Mythril — IDENTICAL flags to reentrant script
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
    # PARSE MYTHRIL JSON — identical logic to reentrant script
    # SWC-107 finding on a SAFE contract = FALSE POSITIVE
    # -----------------------------------------------------------------

    FLAGGED=0
    SWC107_COUNT=0

    if [ -f "${JSON_FILE}" ] && [ -s "${JSON_FILE}" ]; then
        SWC107_COUNT=$(python3 -c "
import json, sys
try:
    with open('${JSON_FILE}') as f:
        data = json.load(f)
    issues = data.get('issues', [])
    count = sum(1 for i in issues if str(i.get('swc-id', '')) == '107')
    print(count)
except Exception:
    print(0)
" 2>/dev/null || echo "0")

        if [ "${SWC107_COUNT}" -gt 0 ]; then
            FLAGGED=1
        fi
    fi

    # Classify — for safe contracts flagged = FP, not flagged = TN
    if [ "${EXIT_CODE}" -eq 124 ]; then
        STATUS="TIMEOUT"
        CRASH=$((CRASH + 1))
    elif [ "${EXIT_CODE}" -ne 0 ] && [ "${FLAGGED}" -eq 0 ]; then
        if grep -qi "CompilerError\|ParserError\|Solc.*fatal\|Error compiling\|Traceback\|Exception" \
                "${LOG_FILE}" 2>/dev/null; then
            STATUS="CRASH_COMPILE"
            CRASH=$((CRASH + 1))
        elif grep -qi "timeout\|Timed out" "${LOG_FILE}" 2>/dev/null; then
            STATUS="TIMEOUT_INTERNAL"
            CRASH=$((CRASH + 1))
        else
            STATUS="TN"
            TN=$((TN + 1))
        fi
    elif [ "${FLAGGED}" -eq 1 ]; then
        STATUS="FP"          # ← safe contract, Mythril raised SWC-107 alarm
        FP=$((FP + 1))
    else
        STATUS="TN"          # ← safe contract, Mythril correctly silent
        TN=$((TN + 1))
    fi

    # Print per-file result
    case "${STATUS}" in
        FP)
            echo "FP — FALSE ALARM (${SWC107_COUNT} SWC-107) [${DURATION}s]" ;;
        TN)
            echo "TN (correct) [${DURATION}s]" ;;
        TIMEOUT|TIMEOUT_INTERNAL)
            echo "TIMEOUT [${DURATION}s]" ;;
        CRASH_COMPILE)
            echo "CRASH (compile error) [${DURATION}s]" ;;
        *)
            echo "TN (correct) [${DURATION}s]" ;;
    esac

    # Write CSV row — ground_truth=0 for all safe contracts
    echo "\"${BASENAME}\",0,${FLAGGED},${SWC107_COUNT},${EXIT_CODE},${STATUS},${DURATION}" \
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
# SUMMARY
# ---------------------------------------------------------------------------

SUMMARY_FILE="${RESULTS_DIR}/mythril_rsd_safe_summary.txt"

python3 - <<PYEOF
fp    = ${FP}
tn    = ${TN}
crash = ${CRASH}
total = ${TOTAL}
duration = ${BATCH_DURATION}
myth_ver = """${MYTH_VERSION}"""

fdr = fp / (fp + tn) if (fp + tn) > 0 else 0.0
tnr = tn / (fp + tn) if (fp + tn) > 0 else 0.0

lines = []
lines.append("=" * 65)
lines.append("MYTHRIL RSD SAFE SUBSET — RESULTS SUMMARY")
lines.append("=" * 65)
lines.append(f"Dataset      : RSD (Ressi et al., 2026), Solidity ^0.8.20")
lines.append(f"Subset       : Safe contracts only (_safe*.sol)")
lines.append(f"Total files  : {total}")
lines.append(f"Mythril ver  : {myth_ver.strip()}")
lines.append(f"Config       : -t ${TRANSACTION_COUNT}, --max-depth ${MAX_DEPTH}, "
             f"--execution-timeout ${EXEC_TIMEOUT}s, "
             f"--solver-timeout ${SOLVER_TIMEOUT}ms")
lines.append(f"Batch time   : {duration}s ({duration // 60} min)")
lines.append("=" * 65)
lines.append("")
lines.append(f"  FP    (safe, incorrectly flagged SWC-107) : {fp}")
lines.append(f"  TN    (safe, correctly not flagged)       : {tn}")
lines.append(f"  CRASH (timeout / compile error)           : {crash}")
lines.append("")
lines.append("  NOTE: All contracts have ground_truth = 0 (safe).")
lines.append("  TP and FN are not applicable here.")
lines.append("  Combine with reentrant results for full P/R/F1.")
lines.append("")
lines.append(f"  False Discovery Rate (FDR) : {fdr:.1%}  [FP/(FP+TN) = {fp}/{fp+tn}]")
lines.append(f"  Specificity (TNR)          : {tnr:.1%}  [TN/(TN+FP) = {tn}/{fp+tn}]")
lines.append("")
lines.append("HOW TO COMPUTE FULL P/R/F1:")
lines.append("  From reentrant summary get: TP, FN")
lines.append("  From this summary get:      FP, TN")
lines.append("  Precision = TP / (TP + FP)")
lines.append("  Recall    = TP / (TP + FN)")
lines.append("  F1        = 2 * P * R / (P + R)")
lines.append("")
lines.append("  OR run: python3 compute_combined_metrics.py")
lines.append("  (reads both CSVs automatically)")
lines.append("")
lines.append("NEXT STEPS:")
lines.append("  1. Review FP contracts — understand why Mythril false-alarmed:")
lines.append(f"     grep ',FP,' ${RESULTS_CSV}")
lines.append("  2. For each FP, inspect the JSON for the specific finding:")
lines.append(f"     cat ${OUT_DIR}/<filename>.json")
lines.append("  3. Inspect CRASH/TIMEOUT rows:")
lines.append(f"     grep 'CRASH\\|TIMEOUT' ${RESULTS_CSV}")
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
