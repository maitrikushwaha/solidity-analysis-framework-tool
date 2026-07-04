#!/usr/bin/env python3
"""SmartCheck batch runner - runs INSIDE smartbugs/smartcheck container over /work.
SmartCheck parses Solidity source (no solc). Rule->vuln map (prefix match):
  reentrancy = SOLIDITY_CALL_WITHOUT_DATA | SOLIDITY_SEND | SOLIDITY_UNCHECKED_CALL
  timestamp  = SOLIDITY_EXACT_TIME
  overflow/tod = -1 (no detector).
Emits: sbc/rsd -> wide CSV (one row/contract, basename unique);
       qian     -> long CSV per category (basename collisions across categories)."""
import csv, json, os, re, subprocess, sys, time

WORK = "/work"
DATA = os.path.join(WORK, "datasets")
OUT = os.path.join(WORK, "out")
RULES = {"reentrancy": ("SOLIDITY_CALL_WITHOUT_DATA", "SOLIDITY_SEND", "SOLIDITY_UNCHECKED_CALL"),
         "timestamp": ("SOLIDITY_EXACT_TIME",)}
TIMEOUT = 120


def sols(d):
    out = []
    for root, _, files in os.walk(d):
        for f in sorted(files):
            if f.endswith(".sol"):
                out.append(os.path.join(root, f))
    return sorted(out)


def analyze(sol):
    t0 = time.time()
    try:
        p = subprocess.run(["smartcheck", "-p", sol], stdout=subprocess.PIPE,
                           stderr=subprocess.STDOUT, timeout=TIMEOUT)
        out = p.stdout.decode("utf-8", "ignore")
    except subprocess.TimeoutExpired:
        return None, "TIMEOUT", round(time.time() - t0, 2), {}
    dur = round(time.time() - t0, 2)
    found = re.findall(r"SOLIDITY_[A-Z0-9_]+", out)
    counts = {}
    flags = {}
    for vuln, prefixes in RULES.items():
        hits = sum(1 for r in found if any(r.startswith(p) for p in prefixes))
        flags[vuln] = 1 if hits else 0
        counts[vuln] = hits
    flags["overflow"] = -1
    flags["tod"] = -1
    return flags, "OK", dur, counts


def run_wide(ds):
    gt = json.load(open(os.path.join(WORK, ds + "_ground_truth.json")))
    od = os.path.join(OUT, ds)
    os.makedirs(od, exist_ok=True)
    rows = []
    for sol in sols(os.path.join(DATA, ds)):
        name = os.path.basename(sol)
        if name not in gt:
            continue
        flags, st, dur, counts = analyze(sol)
        if flags is None:
            rows.append([name, 0, -1, 0, -1, dur, st, "N/A", 0, 0, ""])
            print("[{}] {} {} {}s".format(ds, name, st, dur), flush=True)
            continue
        rows.append([name, flags["reentrancy"], -1, flags["timestamp"], -1, dur, "OK", "N/A",
                     counts.get("reentrancy", 0), counts.get("timestamp", 0), ""])
        print("[{}] {} re={} ts={} {}s".format(ds, name, flags["reentrancy"], flags["timestamp"], dur), flush=True)
    with open(os.path.join(od, "smartcheck_results_{}.csv".format(ds)), "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["filename", "reentrancy", "overflow", "timestamp", "tod", "duration_s",
                    "exit_status", "solc_version", "reentrancy_count", "timestamp_count", "raw_json_path"])
        w.writerows(rows)


def status(g, f):
    return ("TP" if g else "FP") if f else ("FN" if g else "TN")


def run_qian():
    gt = json.load(open(os.path.join(WORK, "qian_ground_truth.json")))
    od = os.path.join(OUT, "qian")
    os.makedirs(od, exist_ok=True)
    rows = []
    for cat in ["reentrancy", "overflow", "timestamp"]:
        for sol in sols(os.path.join(DATA, "qian", cat)):
            name = os.path.basename(sol)
            key = "{}/{}".format(cat, name)
            if key not in gt:
                continue
            g = int(gt[key].get(cat, 0))
            flags, st, dur, counts = analyze(sol)
            if cat == "overflow":  # no detector
                rows.append([name, cat, g, -1, "N/A", dur, "OK"])
                continue
            if flags is None:
                rows.append([name, cat, g, 0, st, dur, st])
                continue
            f = flags[cat]
            rows.append([name, cat, g, f, status(g, f), dur, "OK"])
            print("[qian/{}] {} gt={} flag={} {}s".format(cat, name, g, f, dur), flush=True)
    with open(os.path.join(od, "smartcheck_results_qian.csv"), "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["filename", "vulnerability", "ground_truth", "smartcheck_flagged",
                    "status", "duration_s", "exit_status"])
        w.writerows(rows)


if __name__ == "__main__":
    which = sys.argv[1] if len(sys.argv) > 1 else "all"
    if which in ("sbc", "all"):
        run_wide("sbc")
    if which in ("rsd", "all"):
        run_wide("rsd")
    if which in ("qian", "all"):
        run_qian()
    print("[done] smartcheck " + which, flush=True)
