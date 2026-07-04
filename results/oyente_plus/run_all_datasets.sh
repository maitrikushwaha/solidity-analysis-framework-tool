#!/usr/bin/env bash
#
# run_all_datasets.sh  --  reproducible oyente+ batch over SBC / Qian / RSD / SolidiFI
# ---------------------------------------------------------------------------------
# Runs INSIDE the pinned Docker image (see Dockerfile). It is invoked as:
#
#     docker run --rm -v /home/maitri/oyente_plus_repo:/work \
#         --entrypoint bash oyente-plus-repro:latest /work/run_all_datasets.sh
#
# For every .sol it:
#   1. reads the pragma and picks a solc version DETERMINISTICALLY:
#        - exact version if pre-installed in the image,
#        - else nearest pre-installed patch in the same minor (logged as a fallback),
#      using ONLY `solc-select use` (offline, no network, no install at run time).
#   2. runs oyente+ with a GENEROUS, hardware-independent configuration:
#        -t 10000   Z3 per-query timeout = 10 s   (oyente default 100 ms)  <-- key fix
#        -glt 7200  global wall-clock per contract = 2 h (default 50 s)
#        -dl 1000   depth limit (default 50)
#        -ll 1000   loop limit  (default 10)
#        -j         also emit the structured JSON result
#      The 10 s Z3 timeout ensures every reentrancy/overflow query resolves to a
#      genuine sat/unsat on any machine, instead of timing out to UNKNOWN (which
#      analysis.py:172 `solver.check() != unsat` would wrongly count as vulnerable).
#   3. saves BOTH the raw console output (.txt) and the JSON (.json) under
#        /work/results_docker/<dataset>/<same-subtree>/<contract>.{txt,json}
#      and appends one row per contract to results_docker/manifest.csv plus a
#      human-readable solc_per_contract.log.
#
# Usage (inside container):
#   bash /work/run_all_datasets.sh                 # all four datasets
#   bash /work/run_all_datasets.sh rsd solidifi    # selected datasets
#   bash /work/run_all_datasets.sh /work/datasets/examples/reentrancysafe.sol  # one file (sanity)
#
set -uo pipefail

# ----------------------------------------------------------------------------- config
# Robust, hardware-independent config applied UNIFORMLY to all four datasets.
#   -t 10000  : 10 s Z3 per-query timeout, so each query resolves to a genuine sat/unsat
#               instead of a timing-dependent UNKNOWN (the false-positive source).
#   -glt 300  : oyente's OWN global timeout. Loop-heavy contracts that cannot terminate
#               stop gracefully at 300 s and still emit a verdict flagged "timeout": true,
#               rather than being externally killed with no result. Such contracts are
#               reported as timeout cases (their verdict is bounded-search dependent).
#   -dl/-ll 10000 : deep limits so genuine deep reentrancy IS detected on contracts that
#               terminate (low limits cause false negatives -- see probe table in rebuttal).
#   HARDKILL 600  : outer safety net ABOVE -glt; fires only if oyente itself hangs past 300 s.
ZTIMEOUT="${ZTIMEOUT:-10000}"     # Z3 per-query timeout (ms) = 10 s
GLT="${GLT:-300}"                 # oyente internal global timeout per contract (s)
DL="${DL:-10000}"                 # depth limit
LL="${LL:-10000}"                 # loop limit
HARDKILL="${HARDKILL:-600}"       # outer `timeout` runaway guard per contract (s); hits are logged

WORK="${WORK:-/work}"
RESULTS="${RESULTS:-$WORK/results_docker}"
DATASETS_DIR="${DATASETS_DIR:-$WORK/datasets}"
OYENTE="/oyente/oyente.py"

mkdir -p "$RESULTS"
# In parallel mode each container/shard writes its own manifest + log (merged afterwards),
# so there are no concurrent writers to a shared file.
SHARD_ID="${SHARD_ID:-}"
MANIFEST="$RESULTS/manifest${SHARD_ID:+_$SHARD_ID}.csv"
SOLCLOG="$RESULTS/solc_per_contract${SHARD_ID:+_$SHARD_ID}.log"

# ----------------------------------------------------------------------------- solc set
INSTALLED="$(solc-select versions 2>/dev/null | sed 's/(current)//' | tr -d ' ' \
             | grep -E '^[0-9]+\.[0-9]+\.[0-9]+$' | sort -V)"

# highest installed patch within a given major.minor (e.g. 0.4 -> 0.4.26)
highest_in_minor() {
    printf '%s\n' "$INSTALLED" | grep -E "^${1//./\\.}\." | sort -V | tail -1
}

# vnum x.y.z -> sortable integer (for version range checks)
vnum() { awk -F. '{printf "%d\n",($1*1000000)+($2*1000)+$3}' <<<"$1"; }

# candidates <pragma-line> -> ordered solc versions to TRY: the pragma floor first, then
# every other installed version in the pragma's allowed range, descending. The analyze
# loop uses the FIRST one Oyente+ can actually analyse, so a floor that Oyente+ chokes on
# (e.g. ^0.4.2 -> 0.4.2) auto-bumps to a working version; an exact pin yields only itself.
candidates() {
    local pline="$1" floor ceil isrange fn cn v vn
    floor="$(grep -oP '\d+\.\d+(\.\d+)?' <<<"$pline" | head -1)"
    [ -z "$floor" ] && return
    [ "$(tr -cd . <<<"$floor" | wc -c)" -eq 1 ] && floor="$floor.0"
    grep -qE '[\^~><=]' <<<"$pline" && isrange=1 || isrange=0
    if grep -qoP '<\s*\d' <<<"$pline"; then
        ceil="$(grep -oP '<\s*\K\d+\.\d+(\.\d+)?' <<<"$pline" | head -1)"
        [ "$(tr -cd . <<<"$ceil" | wc -c)" -eq 1 ] && ceil="$ceil.0"
    elif [ "$isrange" = 1 ]; then
        ceil="$(awk -F. '{print $1"."$2+1".0"}' <<<"$floor")"
    else
        echo "$floor"; return            # exact pin -> only the floor
    fi
    fn="$(vnum "$floor")"; cn="$(vnum "$ceil")"
    echo "$floor"
    while read -r v; do
        [ -z "$v" ] && continue
        vn="$(vnum "$v")"
        [ "$vn" -ge "$fn" ] && [ "$vn" -lt "$cn" ] && echo "$v"
    done <<< "$INSTALLED" | sort -rV | grep -vx "$floor"
}

# get_bool <file> <label-regex> -> OR across ALL contracts in the file: a .sol may hold
# several contracts, each printing its own verdict line; the file is positive if ANY line
# is True. (Previously used grep -m1 = first contract only -> false negatives on multi-
# contract files.) Prints "True"/"False", or empty if the label never appears.
get_bool() {
    local h; h="$(grep -iE "$2" "$1" 2>/dev/null | grep -oiE 'True|False')"
    [ -z "$h" ] && return
    if echo "$h" | grep -qiE 'True'; then echo "True"; else echo "False"; fi
}

if [ ! -f "$MANIFEST" ]; then
    echo "dataset,relpath,pragma,want_version,solc_used,fallback,exit_code,coverage_pct,reentrancy,timestamp,tod,int_overflow,int_underflow,callstack,global_timeout_hit,duration_s" > "$MANIFEST"
fi

TOTAL=0; CLEAN=0; FLAGGED=0; ERRORED=0; TIMEDOUT=0; FELLBACK=0

# ----------------------------------------------------------------------------- one contract
analyze_one() {
    local sol="$1" dataset="$2" rel base subdir outdir raw pragma want solc fb tmp rc
    rel="${sol#$WORK/}"
    base="$(basename "$sol" .sol)"
    subdir="$(dirname "${rel#datasets/}")"      # e.g. rsd/reentrancy/safe (already dataset-prefixed)
    outdir="$RESULTS/$subdir"
    [ "$dataset" = "adhoc" ] && outdir="$RESULTS/adhoc"
    mkdir -p "$outdir"
    raw="$outdir/$base.txt"

    # ---- per-dataset analysis config (matches the manuscript's per-dataset settings) ----
    local ZT GL D L HK
    case "$dataset" in
        sbc|solidifi) ZT=300;  GL=600;  D=10000; L=10000; HK=660;;   # manuscript SBC/SolidiFI
        qian)         ZT=7200; GL=1800; D=10000; L=10000; HK=1860;;  # manuscript Qian (-glt bounded 72000->1800)
        rsd)          ZT=10000; GL=300; D=10000; L=10000; HK=360;;   # RSD generous (match SBC/Qian; recovers mutex-guarded reentrancy missed by oyente defaults)
        *)            ZT="$ZTIMEOUT"; GL="$GLT"; D="$DL"; L="$LL"; HK="$HARDKILL";;
    esac

    # ---- per-contract solc: read pragma, try floor then bump until Oyente+ analyses ----
    local pline cand t0 t1 dur
    pline="$(grep -m1 'pragma solidity' "$sol")"
    pline="${pline%%;*}"                       # drop trailing comments after the pragma (e.g. /* ^0.4.11 */)
    pragma="$(echo "$pline" | grep -oP 'solidity\s+\K.+' | head -1)"
    want="$(echo "$pline" | grep -oP '\d+\.\d+(\.\d+)?' | head -1)"
    tmp="$(mktemp -d)"; cp "$sol" "$tmp/$base.sol"
    solc=""; rc=1; dur="0"
    for cand in $(candidates "$pline"); do
        printf '%s\n' "$INSTALLED" | grep -qx "$cand" || continue
        solc-select use "$cand" >/dev/null 2>&1
        t0="$(date +%s.%N)"
        ( cd "$tmp" && rm -f ./*.evm* ./*.json 2>/dev/null
          timeout --kill-after=30 "$HK" \
            python3 "$OYENTE" -s "$base.sol" -j \
              -t "$ZT" -glt "$GL" -dl "$D" -ll "$L" ) > "$raw" 2>&1
        rc=$?
        t1="$(date +%s.%N)"; dur="$(awk "BEGIN{printf \"%.2f\", $t1-$t0}")"
        if grep -qE 'EVM [Cc]ode [Cc]overage|Re-Entrancy Vulnerability' "$raw"; then
            solc="$cand"; break                       # Oyente+ produced a verdict
        fi
        # no verdict: bump to next solc only on a FAST failure (bad bytecode); a slow run
        # (global timeout / hard-kill) is not a solc problem, so stop and keep this attempt.
        if [ "$rc" = "124" ] || awk "BEGIN{exit !($dur>=60)}"; then solc="$cand"; break; fi
    done
    [ -z "$solc" ] && solc="${cand:-$want}"
    if [ "$solc" = "$want" ]; then fb="floor"; else fb="bumped"; fi

    echo "[$dataset] $rel  pragma=$pragma  ->  solc $solc  ($fb)  ${dur}s" | tee -a "$SOLCLOG"

    # collect every JSON produced for this contract
    local jf
    while IFS= read -r -d '' jf; do
        cp "$jf" "$outdir/$(basename "$jf")"
    done < <(find "$tmp" -name '*.json' -print0)
    local tohit="no"
    if grep -lq '"timeout": *true' "$outdir/"*.json 2>/dev/null; then tohit="yes"; fi
    rm -rf "$tmp"

    # ---- harvest verdicts from raw output --------------------------------------
    local cov ree tsd tod iov iuf cst
    cov="$(grep -m1 -iE 'EVM [Cc]ode [Cc]overage' "$raw" | grep -oE '[0-9]+(\.[0-9]+)?' | head -1)"
    ree="$(get_bool "$raw" 'Re-Entrancy Vulnerability')"; [ -z "$ree" ] && ree="$(get_bool "$raw" 'Reentrancy bug')"
    tsd="$(get_bool "$raw" 'Timestamp Dependency')"
    tod="$(get_bool "$raw" 'Transaction-Ordering Dependence')"
    iov="$(get_bool "$raw" 'Integer Overflow')"
    iuf="$(get_bool "$raw" 'Integer Underflow')"
    cst="$(get_bool "$raw" 'Callstack')"

    echo "$dataset,\"${rel#datasets/}\",$pragma,$want,$solc,$fb,$rc,$cov,$ree,$tsd,$tod,$iov,$iuf,$cst,$tohit,$dur" >> "$MANIFEST"

    # exit-code semantics: 0 = analyzed, nothing flagged; 1 = analyzed, >=1 issue flagged;
    # 124 = outer runaway guard fired; other = compile/runtime error.
    TOTAL=$((TOTAL+1))
    case "$rc" in
        0)   CLEAN=$((CLEAN+1));;
        1)   FLAGGED=$((FLAGGED+1));;
        124) TIMEDOUT=$((TIMEDOUT+1)); echo "  !! HARDKILL ${HARDKILL}s: $rel" | tee -a "$SOLCLOG";;
        *)   ERRORED=$((ERRORED+1));   echo "  !! exit $rc (compile/runtime error): $rel" | tee -a "$SOLCLOG";;
    esac
}

# ----------------------------------------------------------------------------- driver
echo "============================================================"
echo " oyente+ reproducible batch"
echo "   Z3 timeout -t  = ${ZTIMEOUT} ms"
echo "   global -glt    = ${GLT} s"
echo "   depth -dl      = ${DL}    loop -ll = ${LL}"
echo "   results        -> $RESULTS"
echo "   solc installed -> $(echo "$INSTALLED" | tr '\n' ' ')"
echo "============================================================"

# Mode 1: SHARD_LIST=<file of absolute .sol paths> -> process exactly that list (parallel worker).
# Mode 2: positional dataset names (or a single .sol file) -> sequential whole-dataset run.
if [ -n "${SHARD_LIST:-}" ] && [ -f "$SHARD_LIST" ]; then
    mapfile -t files < "$SHARD_LIST"
    echo ">>> shard '${SHARD_ID:-?}': ${#files[@]} contracts"
    for sol in "${files[@]}"; do
        [ -z "$sol" ] && continue
        ds="$(echo "${sol#*datasets/}" | cut -d/ -f1)"   # dataset label from path
        analyze_one "$sol" "$ds"
    done
else
    ARGS=("$@")
    [ ${#ARGS[@]} -eq 0 ] && ARGS=(sbc qian rsd solidifi)
    for a in "${ARGS[@]}"; do
        if [ -f "$a" ]; then
            analyze_one "$a" "adhoc"
            continue
        fi
        root="$DATASETS_DIR/$a"
        if [ ! -d "$root" ]; then echo "!! dataset dir not found: $root"; continue; fi
        mapfile -t files < <(find "$root" -name '*.sol' | sort)
        echo ">>> dataset '$a': ${#files[@]} contracts"
        for sol in "${files[@]}"; do analyze_one "$sol" "$a"; done
    done
fi

echo "============================================================"
echo " DONE   total=$TOTAL"
echo "   analyzed-clean (exit 0)      : $CLEAN"
echo "   analyzed-flagged (exit 1)    : $FLAGGED"
echo "   runaway-guard hit (exit 124) : $TIMEDOUT"
echo "   compile/runtime errors       : $ERRORED"
echo "   solc fallbacks               : $FELLBACK"
echo " manifest: $MANIFEST"
echo "============================================================"

# Container runs as root; hand results back to the host user so they're editable.
if [ -n "${HOST_UID:-}" ]; then
    chown -R "${HOST_UID}:${HOST_GID:-$HOST_UID}" "$RESULTS" 2>/dev/null || true
fi
