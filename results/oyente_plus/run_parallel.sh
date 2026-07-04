#!/usr/bin/env bash
#
# run_parallel.sh  --  race-free parallel driver for the reproducible oyente+ batch.
#
# Why containers instead of background processes: oyente picks the compiler via
# `solc-select use`, which sets a SINGLE global version inside the container. Running
# several analyses in one container in parallel would race on that global state and
# compile contracts with the wrong solc. So we shard the contract list and give each
# shard its OWN container (its own isolated /root/.solc-select), all writing into the
# shared /work/results_docker tree (distinct files; per-shard manifest + log, merged here).
#
# Results are identical to the sequential run: each contract still gets its exact pragma
# solc and the uniform config from run_all_datasets.sh (-t 10000, -glt 300, -dl/-ll 10000,
# hard-kill 600), on a dedicated core (workers <= cores) so timeouts never feel contention.
#
# Usage:   WORKERS=6 ./run_parallel.sh                 # all four datasets
#          WORKERS=6 ./run_parallel.sh rsd solidifi    # selected datasets
#
set -uo pipefail
cd /home/maitri/oyente_plus_repo

IMAGE="oyente-plus-repro:latest"
WORKERS="${WORKERS:-6}"
RESULTS="${RESULTS:-results_docker}"          # override for a cross-check run
SHARDDIR="$RESULTS/_shards"
DATASETS=("$@"); [ ${#DATASETS[@]} -eq 0 ] && DATASETS=(rsd solidifi sbc qian)

echo "=== clean previous results + any old shard containers ==="
for i in $(seq 0 31); do docker rm -f "oyente_sh$i" >/dev/null 2>&1; done
# Wipe contents AND hand the (root-owned) results_docker tree back to the host user,
# so the host can write shard lists / merged manifest into it.
docker run --rm -v "$PWD":/work --entrypoint bash "$IMAGE" -c \
  "rm -rf /work/$RESULTS/* /work/$RESULTS/.[!.]* 2>/dev/null; mkdir -p /work/$SHARDDIR; chown -R $(id -u):$(id -g) /work/$RESULTS" 2>/dev/null
mkdir -p "$SHARDDIR"

echo "=== build contract list (container paths) ==="
: > "$SHARDDIR/all.list"
for d in "${DATASETS[@]}"; do
    find "datasets/$d" -name '*.sol' | sort | sed 's#^#/work/#'
done >> "$SHARDDIR/all.list"
TOTAL=$(wc -l < "$SHARDDIR/all.list")
echo "    $TOTAL contracts across: ${DATASETS[*]}"

echo "=== round-robin split into $WORKERS shards ==="
rm -f "$SHARDDIR"/shard_*.list
awk -v w="$WORKERS" -v dir="$SHARDDIR" '{ print > (dir "/shard_" (NR % w) ".list") }' "$SHARDDIR/all.list"
for i in $(seq 0 $((WORKERS-1))); do
    [ -f "$SHARDDIR/shard_$i.list" ] && echo "    shard $i: $(wc -l < "$SHARDDIR/shard_$i.list") contracts"
done

echo "=== launch $WORKERS detached worker containers ==="
for i in $(seq 0 $((WORKERS-1))); do
    [ -f "$SHARDDIR/shard_$i.list" ] || continue
    docker run -d --name "oyente_sh$i" -v "$PWD":/work \
        --memory="${MEM:-3g}" --memory-swap="${MEM:-3g}" \
        -e HOST_UID="$(id -u)" -e HOST_GID="$(id -g)" \
        -e RESULTS="/work/$RESULTS" \
        -e ZTIMEOUT -e GLT -e DL -e LL -e HARDKILL \
        -e SHARD_ID="$i" -e SHARD_LIST="/work/$SHARDDIR/shard_$i.list" \
        --entrypoint bash "$IMAGE" /work/run_all_datasets.sh >/dev/null
    echo "    started oyente_sh$i"
done

echo "=== waiting for all workers to finish (this is the long part) ==="
for i in $(seq 0 $((WORKERS-1))); do
    docker ps -a --format '{{.Names}}' | grep -qx "oyente_sh$i" || continue
    code=$(docker wait "oyente_sh$i" 2>/dev/null)
    echo "    oyente_sh$i exited ($code)"
done

echo "=== merge per-shard manifests + logs ==="
first=$(ls "$RESULTS"/manifest_*.csv 2>/dev/null | head -1)
if [ -n "${first:-}" ]; then
    head -1 "$first" > "$RESULTS/manifest.csv"
    for f in "$RESULTS"/manifest_*.csv; do tail -n +2 "$f"; done >> "$RESULTS/manifest.csv"
fi
cat "$RESULTS"/solc_per_contract_*.log > "$RESULTS/solc_per_contract.log" 2>/dev/null

echo "=== cleanup worker containers ==="
for i in $(seq 0 $((WORKERS-1))); do docker rm -f "oyente_sh$i" >/dev/null 2>&1; done

DONE=$(($(wc -l < "$RESULTS/manifest.csv" 2>/dev/null)-1))
echo "============================================================"
echo " PARALLEL RUN COMPLETE   contracts in merged manifest: $DONE / $TOTAL"
echo " merged manifest: $RESULTS/manifest.csv"
echo "============================================================"
