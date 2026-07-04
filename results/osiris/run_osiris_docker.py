#!/usr/bin/env python3
# Osiris batch runner - runs INSIDE smartbugs/osiris:d1ecc37 over mounted /work.
# python3.5 compatible (no f-strings). Osiris itself is invoked via python2.
# Emits: sbc -> osiris_sbc_classification.json (per-vuln tp/fp/tn/fn filelists)
#               + osiris_sbc_results_final.csv (timing/flags)
#        qian -> osiris_qian_results.csv (long-form per category, like slither)
# Osiris uses its OWN bundled solc (~0.4.21); we do NOT pass --solc. Contracts
# needing newer solc fail to compile -> excluded (N/A). OR-rule across contracts.
import csv, json, os, re, subprocess, sys, time

WORK = "/work"
DATA = os.path.join(WORK, "datasets")
OUT = os.path.join(WORK, "out")
OSIRIS = "/root/osiris/osiris.py"
TIMEOUT = 300


def sols(d):
    out = []
    for root, _, files in os.walk(d):
        for f in sorted(files):
            if f.endswith(".sol"):
                out.append(os.path.join(root, f))
    return sorted(out)


def is_true(log, pat):
    # File-level OR across ALL contracts in the file: Osiris prints one result
    # block per contract, and a .sol is flagged if ANY contract reports the bug
    # True. re.search returned only the first contract's value, which discarded
    # detections when a benign contract (e.g. a Log/Ownable helper) preceded the
    # vulnerable one; re.findall + any() restores the intended OR-rule.
    return 1 if any("true" in g.lower()
                    for g in re.findall(pat, log, re.IGNORECASE)) else 0


PRAGMA_RE = re.compile(r'pragma\s+solidity[^;]*;')


def backport(sol):
    """Osiris bundles only solc 0.4.21; the 0.4.x benchmark contracts declare
    newer 0.4.x pragmas. Rewrite the pragma to ^0.4.21 (as the original Osiris
    evaluation does) so its compiler accepts them. Returns a temp path."""
    try:
        txt = open(sol, errors="ignore").read()
    except Exception:
        return sol
    new = PRAGMA_RE.sub("pragma solidity ^0.4.21;", txt)
    if new == txt:
        return sol
    tmp = "/tmp/bp_" + os.path.basename(sol)
    open(tmp, "w").write(new)
    return tmp


def analyze(sol):
    """Return (flags or None, exit_code, status, duration)."""
    sol = backport(sol)
    t0 = time.time()
    ec = 0
    try:
        p = subprocess.run(["python2", OSIRIS, "-s", sol],
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                           timeout=TIMEOUT)
        log = p.stdout.decode("utf-8", "ignore")
        ec = p.returncode
    except subprocess.TimeoutExpired:
        return None, 124, "TIMEOUT", round(time.time() - t0, 2)
    except Exception:
        return None, 1, "ERROR", round(time.time() - t0, 2)
    dur = round(time.time() - t0, 2)
    if "Analysis Completed" not in log:
        if re.search(r"compilation failed|syntax error|parse error", log, re.IGNORECASE):
            return None, ec, "COMPILE_ERROR", dur
        return None, ec, "ERROR", dur
    ree = is_true(log, r"Reentrancy bug\s*:\s*(True|False)")
    ovf = 0
    for pat in [r"Overflow bugs\s*:\s*(True|False)", r"Underflow bugs\s*:\s*(True|False)",
                r"Division bugs\s*:\s*(True|False)", r"Modulo bugs\s*:\s*(True|False)",
                r"Truncation bugs\s*:\s*(True|False)", r"Signedness bugs\s*:\s*(True|False)"]:
        if is_true(log, pat):
            ovf = 1
            break
    tst = is_true(log, r"Time dependency bug\s*:\s*(True|False)")
    tod = is_true(log, r"Concurrency bug\s*:\s*(True|False)")
    return {"reentrancy": ree, "overflow": ovf, "timestamp": tst, "tod": tod}, ec, "OK", dur


def status(g, f):
    return ("TP" if g else "FP") if f else ("FN" if g else "TN")


def run_sbc():
    gt = json.load(open(os.path.join(WORK, "sbc_ground_truth.json")))
    od = os.path.join(OUT, "sbc")
    os.makedirs(od, exist_ok=True)
    vulns = ["reentrancy", "overflow", "timestamp", "tod"]
    cls = {v: {"tp_files": [], "fp_files": [], "tn_files": [], "fn_files": [], "crash_files": []} for v in vulns}
    rows = []
    for sol in sols(os.path.join(DATA, "sbc")):
        name = os.path.basename(sol)
        if name not in gt:
            continue
        gg = gt[name]
        folder = os.path.basename(os.path.dirname(sol))
        flags, ec, st, dur = analyze(sol)
        if flags is None:
            for v in vulns:
                cls[v]["crash_files"].append(name)
            rows.append([name, folder, gg.get("reentrancy", 0), gg.get("overflow", 0),
                         gg.get("timestamp", 0), gg.get("tod", 0), 0, 0, 0, 0, "0.4.21", ec, st, dur])
            print("[sbc] {} {} {}s".format(name, st, dur), flush=True)
            continue
        for v in vulns:
            g = int(gg.get(v, 0))
            f = flags[v]
            cls[v][("tp_files" if f and g else "fp_files" if f else "fn_files" if g else "tn_files")].append(name)
        rows.append([name, folder, gg.get("reentrancy", 0), gg.get("overflow", 0),
                     gg.get("timestamp", 0), gg.get("tod", 0),
                     flags["reentrancy"], flags["overflow"], flags["timestamp"], flags["tod"],
                     "0.4.21", ec, "OK", dur])
        print("[sbc] {} re={} of={} ts={} tod={} {}s".format(
            name, flags["reentrancy"], flags["overflow"], flags["timestamp"], flags["tod"], dur), flush=True)
    # finalize classification.json with counts
    out = {}
    for v in vulns:
        d = cls[v]
        e = {k: d[k] for k in d}
        e["tp"] = len(d["tp_files"]); e["fp"] = len(d["fp_files"])
        e["tn"] = len(d["tn_files"]); e["fn"] = len(d["fn_files"])
        e["crash"] = len(d["crash_files"])
        out[v] = e
    json.dump(out, open(os.path.join(od, "osiris_sbc_classification.json"), "w"), indent=2, sort_keys=True)
    with open(os.path.join(od, "osiris_sbc_results_final.csv"), "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["filename", "folder", "reentrancy_gt", "overflow_gt", "timestamp_gt", "tod_gt",
                    "reentrancy_flag", "overflow_flag", "timestamp_flag", "tod_flag",
                    "solc_version", "exit_code", "status", "duration_s"])
        w.writerows(rows)


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
            flags, ec, st, dur = analyze(sol)
            if flags is None:
                rows.append([name, cat, g, 0, "0.4.21", ec, st, dur])
                print("[qian/{}] {} {} {}s".format(cat, name, st, dur), flush=True)
                continue
            f = flags[cat]
            rows.append([name, cat, g, f, "0.4.21", ec, status(g, f), dur])
            print("[qian/{}] {} gt={} flag={} {}s".format(cat, name, g, f, dur), flush=True)
    with open(os.path.join(od, "osiris_qian_results.csv"), "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["filename", "vulnerability", "ground_truth", "osiris_flagged",
                    "solc_version", "exit_code", "status", "duration_s"])
        w.writerows(rows)


if __name__ == "__main__":
    which = sys.argv[1] if len(sys.argv) > 1 else "all"
    if which in ("sbc", "all"):
        run_sbc()
    if which in ("qian", "all"):
        run_qian()
    print("[done] osiris " + which, flush=True)
