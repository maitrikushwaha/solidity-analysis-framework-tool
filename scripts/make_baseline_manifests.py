#!/usr/bin/env python3
"""Emit a UNIFORM per-contract manifest_<ds>.csv for each baseline, from the
already-saved verdict CSVs (no re-run). Columns:
  filename, solc_version, exit_status, duration_s, reentrancy, overflow, timestamp, tod
A flag of -1 = the tool has no detector for that class. Long-form (Qian and
Osiris rsd/solidifi) contributes one row per contract carrying its category flag.
Oyente+ and Mythril already ship their own richer manifests and are left as-is."""
import csv, glob, os, re
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RES = ROOT / "results"
COLS = ["filename", "solc_version", "exit_status", "duration_s",
        "reentrancy", "overflow", "timestamp", "tod"]

# Slither's image only carries these solc patches; pick highest in the pragma's minor.
SLITHER_SOLC = {"0.4": "0.4.26", "0.5": "0.5.17", "0.6": "0.6.12", "0.7": "0.7.6", "0.8": "0.8.28"}
_PRAGMA = re.compile(r'pragma\s+solidity\s+[\^~>=<\s]*([0-9]+\.[0-9]+)')
_dsfiles = {}


def _solc_from_pragma(ds, fn, solcmap):
    if ds not in _dsfiles:
        _dsfiles[ds] = {os.path.basename(p): p for p in
                        glob.glob(str(ROOT / ("datasets/%s/**/*.sol" % ds)), recursive=True)}
    p = _dsfiles[ds].get(fn)
    if not p:
        return "?"
    m = _PRAGMA.search(open(p, errors="ignore").read())
    return solcmap.get(m.group(1), solcmap["0.4"]) if m else solcmap["0.4"]


def _ds_basenames(ds):
    """Canonical scored-contract basenames for a dataset (datasets/<ds>)."""
    return {os.path.basename(p) for p in
            glob.glob(str(ROOT / ("datasets/%s/**/*.sol" % ds)), recursive=True)}


def emit(tool, ds, recs, universe=None):
    """recs: dict filename -> {solc,status,duration, flags...}.
    If `universe` (a set of basenames) is given, only those contracts are emitted
    -- used to drop out-of-scope raw-run extras so every tool's manifest matches
    the scored dataset (e.g. the 5 RSD delegatecall/inline non-ether contracts)."""
    d = RES / tool / ds
    if not d.exists():
        return
    keys = [fn for fn in sorted(recs) if (universe is None or fn in universe)]
    with open(d / ("manifest_%s.csv" % ds), "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(COLS)
        for fn in keys:
            r = recs[fn]
            solc = r.get("solc", "?")
            if solc in ("?", "", None) and tool in ("slither", "vandal", "mythril"):
                solc = _solc_from_pragma(ds, fn, SLITHER_SOLC)  # backfill from pragma
            if solc in ("?", "", None) and tool == "smartcheck":
                solc = "N/A"  # SmartCheck analyses source directly; no solc compilation
            w.writerow([fn, solc, r.get("status", "OK"), r.get("dur", ""),
                        r.get("reentrancy", -1), r.get("overflow", -1),
                        r.get("timestamp", -1), r.get("tod", -1)])
    print("[ok] %s/%s/manifest_%s.csv (%d rows)" % (tool, ds, ds, len(keys)))


def read_csv(p):
    return list(csv.DictReader(open(p))) if p.exists() else []


def g(r, *names, default=""):
    for n in names:
        if n in r and r[n] != "":
            return r[n]
    return default


def wide(tool, ds, path, flagmap, solc_keys=("solc_version",), status_keys=("exit_status", "status"), universe=None):
    recs = {}
    for r in read_csv(path):
        fn = os.path.basename(r["filename"])
        rec = {"solc": g(r, *solc_keys, default="?"), "status": g(r, *status_keys, default="OK"),
               "dur": g(r, "duration_s")}
        for vuln, col in flagmap.items():
            rec[vuln] = r.get(col, -1) if col else -1
        recs[fn] = rec
    if recs:
        emit(tool, ds, recs, universe=universe)


def longform(tool, ds, path, flag_col, solc_keys=("solc_version",), status_keys=("status", "exit_status")):
    """one row per (contract, vulnerability); merge to per-contract, others -1."""
    recs = {}
    for r in read_csv(path):
        fn = os.path.basename(r["filename"])
        v = r["vulnerability"]
        rec = recs.setdefault(fn, {"reentrancy": -1, "overflow": -1, "timestamp": -1, "tod": -1})
        rec["solc"] = g(r, *solc_keys, default="?")
        rec["status"] = g(r, *status_keys, default="OK")
        rec["dur"] = g(r, "duration_s")
        rec[v] = r.get(flag_col, -1)
    if recs:
        emit(tool, ds, recs)


def main():
    # Slither: reentrancy + timestamp; no overflow/tod
    wide("slither", "sbc", RES / "slither/sbc/summary/slither_sbc_results.csv",
         {"reentrancy": "reentrancy_flag", "overflow": None, "timestamp": "timestamp_flag", "tod": None})
    longform("slither", "qian", RES / "slither/qian/summary/slither_qian_results.csv", "slither_flagged")
    # slither rsd: reentrancy-only wide-ish
    recs = {}
    for r in read_csv(RES / "slither/rsd/summary/slither_rsd_results.csv"):
        fn = os.path.basename(r["filename"])
        recs[fn] = {"solc": "?", "status": g(r, "status"), "dur": g(r, "duration_s"),
                    "reentrancy": g(r, "slither_flagged", default=-1), "overflow": -1, "timestamp": -1, "tod": -1}
    emit("slither", "rsd", recs)

    # Osiris: sbc wide (all 4), qian/rsd/solidifi long
    wide("osiris", "sbc", RES / "osiris/sbc/summary/osiris_sbc_results_final.csv",
         {"reentrancy": "reentrancy_flag", "overflow": "overflow_flag",
          "timestamp": "timestamp_flag", "tod": "tod_flag"})
    longform("osiris", "qian", RES / "osiris/qian/summary/osiris_qian_results.csv", "osiris_flagged")
    longform("osiris", "rsd", RES / "osiris/rsd/summary/osiris_rsd_results.csv", "osiris_flagged")
    longform("osiris", "solidifi", RES / "osiris/solidifi/summary/osiris_solidifi_results.csv", "osiris_flagged")

    # SmartCheck: sbc/rsd wide (re,of=-1,ts,tod=-1), qian long
    for ds in ("sbc", "rsd"):
        wide("smartcheck", ds, RES / ("smartcheck/%s/smartcheck_results_%s.csv" % (ds, ds)),
             {"reentrancy": "reentrancy", "overflow": "overflow", "timestamp": "timestamp", "tod": "tod"},
             solc_keys=("solc_version",))
    longform("smartcheck", "qian", RES / "smartcheck/qian/smartcheck_results_qian.csv", "smartcheck_flagged")

    # Sailfish: wide (re, tod; of/ts=-1)
    for ds in ("sbc", "qian", "solidifi", "rsd"):
        wide("sailfish", ds, RES / ("sailfish/%s/sailfish_results_%s.csv" % (ds, ds)),
             {"reentrancy": "reentrancy", "overflow": "overflow", "timestamp": "timestamp", "tod": "tod"})

    # Vandal / EtherSolve: reentrancy-only wide. Restrict rsd to the scored 138
    # contracts (some raw runs also carry the 5 out-of-scope delegatecall/inline files).
    rsd_uni = _ds_basenames("rsd")
    for tool in ("vandal", "ethersolve"):
        for ds in ("sbc", "qian", "rsd"):
            wide(tool, ds, RES / ("%s/%s/%s_results_%s.csv" % (tool, ds, tool, ds)),
                 {"reentrancy": "reentrancy", "overflow": None, "timestamp": None, "tod": None},
                 solc_keys=("solc_version",), universe=(rsd_uni if ds == "rsd" else None))

    # Mythril (all 4 classes): sbc/qian/solidifi are wide with solc_version in-CSV;
    # rsd is split into vulnerable/safe partitions (reentrancy only).
    for ds in ("sbc", "qian", "solidifi"):
        wide("mythril", ds, RES / ("mythril/%s/mythril_results_%s.csv" % (ds, ds)),
             {"reentrancy": "reentrancy", "overflow": "overflow", "timestamp": "timestamp", "tod": "tod"},
             solc_keys=("solc_version",), status_keys=("exit_status", "status"))
    recs = {}
    for sub in ("mythril_rsd_reentrant_results.csv", "mythril_rsd_safe_results.csv"):
        for r in read_csv(RES / "mythril/rsd" / sub):
            fn = os.path.basename(r["filename"])
            recs[fn] = {"solc": "?", "status": g(r, "status"), "dur": g(r, "duration_s"),
                        "reentrancy": g(r, "mythril_flagged", default=-1),
                        "overflow": -1, "timestamp": -1, "tod": -1}
    if recs:
        emit("mythril", "rsd", recs, universe=rsd_uni)  # scored 138 only


if __name__ == "__main__":
    main()
