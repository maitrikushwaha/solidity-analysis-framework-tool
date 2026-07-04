#!/usr/bin/env python3
"""Slither batch runner — runs INSIDE smartbugs/slither container over mounted /work.
Emits CSVs in the exact schema the SCVD make_predictions.py adapter expects.
Detector map: reentrancy = check startswith 'reentrancy'; timestamp = 'timestamp';
overflow/tod = -1 (Slither has no detector). solc chosen per pragma from the
versions baked into the image (0.4.26/0.5.17/0.6.12/0.7.6/0.8.28)."""
import csv, json, os, re, subprocess, sys, time
from pathlib import Path

WORK = Path("/work")
DATA = WORK / "datasets"
OUT = WORK / "out"
PRAGMA = re.compile(r'pragma\s+solidity\s+[\^~>=<\s]*([0-9]+\.[0-9]+(?:\.[0-9]+)?)')
SOLC_MAP = {"0.4": "0.4.26", "0.5": "0.5.17", "0.6": "0.6.12", "0.7": "0.7.6", "0.8": "0.8.28"}
TIMEOUT = 120


def pick_solc(sol):
    try:
        txt = sol.read_text(errors="ignore")
    except Exception:
        return "0.4.26"
    m = PRAGMA.search(txt)
    if not m:
        return "0.4.26"
    v = m.group(1)
    parts = v.split(".")
    mm = f"{parts[0]}.{parts[1]}"
    if len(parts) == 3 and v in ("0.4.26", "0.5.17", "0.6.12", "0.7.6", "0.8.28"):
        return v
    return SOLC_MAP.get(mm, "0.4.26")


def run_one(sol):
    """Return (flags dict, detectors dict, solc, exit_code, status_raw, duration)."""
    solc = pick_solc(sol)
    jf = Path("/tmp/out.json")
    if jf.exists():
        jf.unlink()
    t0 = time.time()
    ec = 0
    try:
        p = subprocess.run(
            ["slither", str(sol), "--json", str(jf), "--solc-solcs-select", solc, "--disable-color"],
            capture_output=True, text=True, timeout=TIMEOUT)
        ec = p.returncode
        err = p.stderr
    except subprocess.TimeoutExpired:
        _save_raw(sol, "TIMEOUT after %ds\n" % TIMEOUT)
        return None, None, solc, 124, "TIMEOUT", round(time.time() - t0, 2)
    # slither prints its human-readable findings to stderr
    _save_raw(sol, (p.stdout or "") + "\n" + (p.stderr or ""))
    dur = round(time.time() - t0, 2)
    checks = set()
    if jf.exists() and jf.stat().st_size > 0:
        try:
            d = json.load(open(jf))
            for x in (d.get("results", {}) or {}).get("detectors", []) or []:
                if x.get("check"):
                    checks.add(x["check"])
        except Exception:
            pass
    else:
        # no JSON -> compile failure
        if re.search(r"Error|CompilationError|ParserError|Traceback", err or ""):
            return None, None, solc, ec, "COMPILE_ERROR", dur
    re_hits = sorted(c for c in checks if c.startswith("reentrancy"))
    ts_hits = sorted(c for c in checks if c.startswith("timestamp"))
    flags = {"reentrancy": 1 if re_hits else 0, "overflow": -1,
             "timestamp": 1 if ts_hits else 0, "tod": -1}
    dets = {"reentrancy": "|".join(re_hits) or "none", "timestamp": "|".join(ts_hits) or "none"}
    return flags, dets, solc, ec, "OK", dur


def _save_raw(sol, text):
    """Write the tool's raw console output to out/<ds>/raw/<subtree>/<name>.txt."""
    parts = Path(sol).parts
    if "datasets" not in parts:
        return
    i = parts.index("datasets")
    ds = parts[i + 1]
    sub = Path(*parts[i + 2:]).with_suffix(".txt")
    rp = OUT / ds / "raw" / sub
    rp.parent.mkdir(parents=True, exist_ok=True)
    rp.write_text(text)


def status(gt, flag):
    if flag == -1:
        return "N/A"
    return ("TP" if gt else "FP") if flag else ("FN" if gt else "TN")


def sols_in(d):
    return sorted(Path(d).rglob("*.sol"))


def main():
    ds = sys.argv[1]
    gt = json.load(open(WORK / f"{ds}_ground_truth.json"))
    outdir = OUT / ds
    outdir.mkdir(parents=True, exist_ok=True)

    if ds == "qian":
        cats = {"reentrancy": "reentrancy", "overflow": "overflow", "timestamp": "timestamp"}
        rows = []
        for cat, vuln in cats.items():
            for sol in sols_in(DATA / "qian" / cat):
                key = f"{cat}/{sol.name}"
                if key not in gt:
                    continue
                g = int(gt[key].get(vuln, 0))
                flags, dets, solc, ec, st, dur = run_one(sol)
                if flags is None:
                    fl, det, stt = (-1 if vuln == "overflow" else 0), "none", st
                else:
                    fl, det, stt = flags[vuln], dets.get(vuln, "none"), status(g, flags[vuln])
                rows.append([sol.name, vuln, g, fl, det, solc, ec, stt, dur])
                print(f"[qian/{vuln}] {sol.name} gt={g} flag={fl} {stt} {dur}s", flush=True)
        with open(outdir / "slither_qian_results.csv", "w", newline="") as fh:
            w = csv.writer(fh, quoting=csv.QUOTE_NONNUMERIC)
            w.writerow(["filename", "vulnerability", "ground_truth", "slither_flagged",
                        "detectors_hit", "solc_version", "exit_code", "status", "duration_s"])
            w.writerows(rows)

    elif ds == "rsd":
        rows = []
        for sol in sols_in(DATA / "rsd"):
            if sol.name not in gt:
                continue
            g = int(gt[sol.name].get("reentrancy", 0))
            flags, dets, solc, ec, st, dur = run_one(sol)
            if flags is None:
                fl, det, stt = 0, "none", st
            else:
                fl, det, stt = flags["reentrancy"], dets["reentrancy"], status(g, flags["reentrancy"])
            rows.append([sol.name, g, fl, det, ec, stt, dur])
            print(f"[rsd] {sol.name} gt={g} flag={fl} {stt} {dur}s", flush=True)
        with open(outdir / "slither_rsd_results.csv", "w", newline="") as fh:
            w = csv.writer(fh, quoting=csv.QUOTE_NONNUMERIC)
            w.writerow(["filename", "ground_truth", "slither_flagged",
                        "reentrancy_detectors", "exit_code", "status", "duration_s"])
            w.writerows(rows)

    elif ds == "sbc":
        rows = []
        for sol in sols_in(DATA / "sbc"):
            if sol.name not in gt:
                continue
            gg = gt[sol.name]
            folder = sol.parent.name
            flags, dets, solc, ec, st, dur = run_one(sol)
            if flags is None:
                rows.append([sol.name, folder, int(gg.get("reentrancy", 0)), int(gg.get("overflow", 0)),
                             int(gg.get("timestamp", 0)), int(gg.get("tod", 0)),
                             0, -1, 0, -1, "none", "none", "?", ec, st, dur])
                print(f"[sbc] {sol.name} {st} {dur}s", flush=True)
                continue
            rows.append([sol.name, folder, int(gg.get("reentrancy", 0)), int(gg.get("overflow", 0)),
                         int(gg.get("timestamp", 0)), int(gg.get("tod", 0)),
                         flags["reentrancy"], flags["overflow"], flags["timestamp"], flags["tod"],
                         dets["reentrancy"], dets["timestamp"], "?", ec, "OK", dur])
            print(f"[sbc] {sol.name} re={flags['reentrancy']} ts={flags['timestamp']} {dur}s", flush=True)
        with open(outdir / "slither_sbc_results.csv", "w", newline="") as fh:
            w = csv.writer(fh, quoting=csv.QUOTE_NONNUMERIC)
            w.writerow(["filename", "folder", "reentrancy_gt", "overflow_gt", "timestamp_gt", "tod_gt",
                        "reentrancy_flag", "overflow_flag", "timestamp_flag", "tod_flag",
                        "reentrancy_detectors", "timestamp_detectors", "solc_version",
                        "exit_code", "status", "duration_s"])
            w.writerows(rows)
    print(f"[done] {ds}", flush=True)


if __name__ == "__main__":
    main()
