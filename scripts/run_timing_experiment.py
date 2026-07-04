#!/usr/bin/env python3
"""
run_timing_experiment.py
========================
Per-domain detection-time experiment for Table 7 (and the domain-agreement
study). Measures the *whole-tool* wall-clock time of the abstract-interpretation
analyzer when the reentrancy fixpoint uses each numerical domain
(Box=Interval, Octagon, Polka=Polyhedra), on the SBC and Qian benchmarks.

Methodology (defensible, matches static-analysis/AI timing practice)
--------------------------------------------------------------------
* SERIAL execution — exactly one contract analysed at a time, so wall-clock is
  free of CPU contention and directly comparable to the baselines' end-to-end
  times (which were measured serially).
* SEPARATE per-domain runs — each domain is timed as an independent end-to-end
  invocation of main.py (--reentrancy-domain X), yielding a clean
  "Total analysis time" per contract per domain.
* DOMAIN-INVARIANCE for non-reentrancy-encoded contracts — when a contract has
  no reentrancy encoding, --reentrancy-domain provably collapses to the same
  Box-only code path (overflow/timestamp/tod always use Box). Such contracts
  are timed once (Box) and that time is reused for the Octagon/Polka columns.
  This is exact, not an approximation.
* REPETITIONS — the domain-sensitive (encoded) subset is timed REPS times and
  the mean is reported, to control measurement noise.
* CONTENT DEDUP — Qian reuses numeric ids across vuln subsets but the files
  differ; contracts are de-duplicated by SHA-256 of their source so each
  distinct contract is timed exactly once.

Outputs (under results/ours/timing/):
    raw/<dataset>/<domain>/rep<k>/<base>_verdicts.json   per-run JSON
    timing_runs.csv      long form: dataset,contract,domain,rep,total_s,fixpoint_s,encoded
    (aggregation into Table 8 is done by make_table8_timing.py)

Usage:
    python3 run_timing_experiment.py sbc                 # full SBC
    python3 run_timing_experiment.py qian                # full Qian (content-deduped)
    python3 run_timing_experiment.py sbc --limit 3       # dry run: first 3 contracts
    python3 run_timing_experiment.py sbc --reps 3
Resumable: existing per-run JSON outputs are skipped.
"""
import argparse
import csv
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC_MAIN = ROOT / "src" / "main.py"
PY = os.environ.get("SAFPY_PYTHON",
                    "/home/maitri/miniconda3/envs/safpy/bin/python")
OUT_ROOT = ROOT / "results" / "ours" / "timing"
DOMAINS = ["Box", "Octagon", "Polka"]
PER_CONTRACT_TIMEOUT = 420  # seconds (> 3x fixpoint timeout)

DATASET_DIRS = {
    "sbc": [ROOT / "datasets" / "sbc"],
    "qian": [
        ROOT / "datasets" / "qian" / "reentrancy",
        ROOT / "datasets" / "qian" / "overflow",
        ROOT / "datasets" / "qian" / "timestamp",
    ],
    "rsd": [ROOT / "datasets" / "rsd" / "reentrancy"],
    "solidifi": [ROOT / "datasets" / "solidifi" / "tod"],
}


def enumerate_contracts(dataset):
    """Return [(contract_id, path)] de-duplicated by file content (SHA-256).
    contract_id is the basename; on a content collision the first path wins."""
    seen_hashes = {}
    out = []
    for base_dir in DATASET_DIRS[dataset]:
        for sol in sorted(base_dir.rglob("*.sol")):
            try:
                data = sol.read_bytes()
            except OSError:
                continue
            h = hashlib.sha256(data).hexdigest()
            if h in seen_hashes:
                continue
            seen_hashes[h] = sol
            out.append((sol.stem, sol))
    return out


def run_one(path, domain, out_dir):
    """Invoke main.py on one contract for one domain. Returns parsed JSON dict
    (with total_s, encoded, fixpoint_s) or None on failure.

    Resumable: if a valid output JSON already exists for this contract+domain,
    it is parsed and returned WITHOUT re-running (so a relaunch skips completed
    work)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    base = Path(path).stem
    jpath = out_dir / f"{base}_verdicts.json"
    if jpath.exists():
        try:
            with open(jpath) as fh:
                _j = json.load(fh)
            return _summarise(_j, domain, _j.get("duration_s", 0.0))
        except Exception:
            pass  # corrupt/partial -> re-run below
    cmd = [
        PY, str(SRC_MAIN), str(path),
        "--reentrancy-domain", domain,
        "--json", "--output-dir", str(out_dir),
        "--pipelines", "reentrancy,overflow,timestamp,tod",
    ]
    t0 = time.time()
    try:
        subprocess.run(cmd, capture_output=True, text=True,
                       timeout=PER_CONTRACT_TIMEOUT)
    except subprocess.TimeoutExpired:
        return {"total_s": float(PER_CONTRACT_TIMEOUT), "encoded": True,
                "fixpoint_s": None, "status": "TIMEOUT"}
    wall = time.time() - t0
    if not jpath.exists():
        return {"total_s": round(wall, 3), "encoded": False,
                "fixpoint_s": None, "status": "NO_JSON"}
    with open(jpath) as fh:
        j = json.load(fh)
    return _summarise(j, domain, round(wall, 3))


def _summarise(j, domain, wall):
    """Reduce one main.py JSON verdict to the timing-run row fields."""
    fixtimes = j.get("reentrancy_fixpoint_times") or {}
    confirm = j.get("confirm_fixpoint_times") or {}   # {vuln: {domain: s}}
    # A contract is "domain-sensitive" if ANY relational fixpoint ran for it:
    # the reentrancy fixpoint OR a timestamp/TOD confirmation fixpoint.
    confirm_sum = 0.0
    for vt in confirm.values():
        confirm_sum += float(vt.get(domain, 0.0) or 0.0)
    return {
        "total_s": j.get("duration_s", wall),
        "encoded": bool(fixtimes) or bool(confirm),
        "fixpoint_s": (fixtimes.get(domain) or 0.0) + confirm_sum,
        "status": "OK" if not j.get("error") else "ERR",
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dataset", choices=["sbc", "qian", "rsd", "solidifi"])
    ap.add_argument("--reps", type=int, default=3,
                    help="repetitions for the domain-sensitive subset")
    ap.add_argument("--limit", type=int, default=None,
                    help="only first N contracts (dry run)")
    args = ap.parse_args()

    contracts = enumerate_contracts(args.dataset)
    if args.limit:
        contracts = contracts[: args.limit]
    print(f"[timing] {args.dataset}: {len(contracts)} content-unique contracts "
          f"| python={PY}")

    runs_csv = OUT_ROOT / f"timing_runs_{args.dataset}.csv"
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    rows = []

    for i, (cid, path) in enumerate(contracts, 1):
        # ---- Pass A: Box, rep 1 — also classifies encoded vs not ----
        out_dir = OUT_ROOT / "raw" / args.dataset / "Box" / "rep1"
        r = run_one(path, "Box", out_dir)
        encoded = r["encoded"]
        rows.append([args.dataset, cid, "Box", 1, r["total_s"], r["fixpoint_s"], encoded, r["status"]])

        if not encoded:
            # Domain-invariant: Box time stands for all three domains.
            print(f"  [{i}/{len(contracts)}] {cid:40s} non-encoded  Box={r['total_s']}s")
            continue

        # ---- Encoded: extra Box reps + Octagon + Polka (+ agreement via all) ----
        for dom in DOMAINS:
            reps = range(2, args.reps + 1) if dom == "Box" else range(1, args.reps + 1)
            for rep in reps:
                od = OUT_ROOT / "raw" / args.dataset / dom / f"rep{rep}"
                rr = run_one(path, dom, od)
                rows.append([args.dataset, cid, dom, rep, rr["total_s"],
                             rr["fixpoint_s"], rr["encoded"], rr["status"]])
        # agreement study: genuine all-domain verdicts (single pass)
        od = OUT_ROOT / "raw" / args.dataset / "all" / "rep1"
        run_one(path, "all", od)
        print(f"  [{i}/{len(contracts)}] {cid:40s} ENCODED   (Box+Oct+Polka x{args.reps})")

        # checkpoint every 10 encoded contracts
        if i % 10 == 0:
            _write_rows(runs_csv, rows)

    _write_rows(runs_csv, rows)
    print(f"[timing] wrote {runs_csv}  ({len(rows)} run rows)")


def _write_rows(path, rows):
    with open(path, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["dataset", "contract", "domain", "rep", "total_s",
                    "fixpoint_s", "encoded", "status"])
        w.writerows(rows)


if __name__ == "__main__":
    main()
