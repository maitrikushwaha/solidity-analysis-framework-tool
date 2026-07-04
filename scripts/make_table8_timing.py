#!/usr/bin/env python3
"""
make_table8_timing.py
=====================
Builds Table 8 (tab:avg_exec_time) using the MEDIAN per-contract analysis time,
which is robust to the timeout-skewed means of the symbolic tools (e.g. Oyente+
SBC mean 511 s from one 12781 s outlier vs median 16 s; Mythril RSD median ~305 s
where most contracts hit the per-contract timeout).

Uniform rule for every cell: MEDIAN over all rows with a recorded positive
duration_s (>0 drops the 0 = not-recorded and -1 = sentinel rows, which are the
compile-errors / not-analysed contracts). A (tool,dataset) with no positive
duration, or a class the tool has no detector for / was not run on, is "--".

Sources (each (tool,dataset) -> list of (csv_relative_to_results, duration_col)):
  * Oyente+  : the canonical Docker manifests manifest_<ds>.csv.
  * Mythril  : its native per-dataset result CSVs (RSD = reentrant + safe pools).
  * Slither/Osiris/SmartCheck/Sailfish : each tool's per-dataset result CSV.
  * Ours     : results/ours/timing/timing_runs_<ds>.csv, per the paper's timing
               model -- domain-sensitive contracts timed under each numerical
               domain (mean over reps), domain-invariant contracts run an
               identical path so their single time stands for every column;
               the per-contract times are then medianed across the dataset.

NA / "--" cells (consistent with the metric tables 4-7):
  * Slither  : no overflow/TOD detector -> SolidiFI "--".
  * SmartCheck: no overflow/TOD detector -> SolidiFI "--".
  * Sailfish : no overflow/timestamp detector; RSD is 100% COMPILE_ERROR
               (RSD is Solidity ^0.8.20, Sailfish's EVM front-end cannot compile
               it) -> RSD "--".
  * Osiris   : image ships only solc 0.4.21; RSD (^0.8.20) and SolidiFI (^0.5.1)
               cannot be compiled, so Osiris produces no verdict -> RSD/SolidiFI
               "--" (matches its NA detection cells).

Outputs: tables/table8_timing_median.csv, tables/table8_timing.tex (paste-ready
tabular body), and a notes block printed to stdout.
"""
import csv
import statistics
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "results"
TIMING = RESULTS / "ours" / "timing"
OUT = ROOT / "tables"

DATASETS = ["sbc", "qian", "rsd", "solidifi"]
DS_LABEL = {"sbc": "SBC", "qian": "Qian", "rsd": "RSD", "solidifi": "SolidiFI"}
DOMAINS = ["Box", "Octagon", "Polka"]
DOMAIN_LABEL = {"Box": "Interval", "Octagon": "Octagon", "Polka": "Polyhedra"}
BASELINE_ORDER = ["Mythril", "Oyente+", "Slither", "Osiris", "SmartCheck", "Sailfish", "Vandal", "EtherSolve"]

BASELINE_TIME_CSVS = {
    "Mythril": {
        "sbc": [("mythril/sbc/mythril_results_sbc.csv", "duration_s")],
        "qian": [("mythril/qian/mythril_results_qian.csv", "duration_s")],
        "rsd": [("mythril/rsd/mythril_rsd_reentrant_results.csv", "duration_s"),
                ("mythril/rsd/mythril_rsd_safe_results.csv", "duration_s")],
        "solidifi": [("mythril/solidifi/mythril_results_solidifi.csv", "duration_s")],
    },
    "Oyente+": {  # canonical Docker manifests (medians match METRICS_SUMMARY)
        "sbc": [("oyente_plus/sbc/manifest_sbc.csv", "duration_s")],
        "qian": [("oyente_plus/qian/manifest_qian.csv", "duration_s")],
        "rsd": [("oyente_plus/rsd/manifest_rsd.csv", "duration_s")],
        "solidifi": [("oyente_plus/solidifi/manifest_solidifi.csv", "duration_s")],
    },
    "Slither": {
        "sbc": [("slither/sbc/summary/slither_sbc_results.csv", "duration_s")],
        "qian": [("slither/qian/summary/slither_qian_results.csv", "duration_s")],
        "rsd": [("slither/rsd/summary/slither_rsd_results.csv", "duration_s")],
    },
    "Osiris": {
        "sbc": [("osiris/sbc/summary/osiris_sbc_results_final.csv", "duration_s")],
        "qian": [("osiris/qian/summary/osiris_qian_results.csv", "duration_s")],
    },
    "SmartCheck": {
        "sbc": [("smartcheck/sbc/smartcheck_results_sbc.csv", "duration_s")],
        "qian": [("smartcheck/qian/smartcheck_results_qian.csv", "duration_s")],
        "rsd": [("smartcheck/rsd/smartcheck_results_rsd.csv", "duration_s")],
    },
    "Sailfish": {
        "sbc": [("sailfish/sbc/sailfish_results_sbc.csv", "duration_s")],
        "qian": [("sailfish/qian/sailfish_results_qian.csv", "duration_s")],
        "solidifi": [("sailfish/solidifi/sailfish_results_solidifi.csv", "duration_s")],
    },
    "Vandal": {  # reentrancy-only, bytecode (Datalog/Souffle); no SolidiFI
        "sbc": [("vandal/sbc/vandal_results_sbc.csv", "duration_s")],
        "qian": [("vandal/qian/vandal_results_qian.csv", "duration_s")],
        "rsd": [("vandal/rsd/vandal_results_rsd.csv", "duration_s")],
    },
    "EtherSolve": {  # reentrancy-only, bytecode (CFG + re-entrancy check); no SolidiFI
        "sbc": [("ethersolve/sbc/ethersolve_results_sbc.csv", "duration_s")],
        "qian": [("ethersolve/qian/ethersolve_results_qian.csv", "duration_s")],
        "rsd": [("ethersolve/rsd/ethersolve_results_rsd.csv", "duration_s")],
    },
}


def _mean(xs):
    xs = [x for x in xs if x is not None]
    return statistics.fmean(xs) if xs else None


def baseline_stats(agg):
    """agg = statistics.median or statistics.fmean."""
    out = defaultdict(dict)
    for tool, dsmap in BASELINE_TIME_CSVS.items():
        for ds, sources in dsmap.items():
            vals = []
            for rel, col in sources:
                p = RESULTS / rel
                if not p.exists():
                    continue
                for r in csv.DictReader(open(p)):
                    try:
                        v = float(r.get(col))
                    except (ValueError, TypeError):
                        continue
                    if v > 0:
                        vals.append(v)
            out[tool][ds] = agg(vals) if vals else None
    return out


def ours_stats(dataset, agg):
    """Per-contract time for each numerical domain (paper timing model), aggregated by `agg`."""
    path = TIMING / f"timing_runs_{dataset}.csv"
    runs = defaultdict(lambda: defaultdict(list))
    encoded = {}
    if not path.exists():
        return {DOMAIN_LABEL[d]: None for d in DOMAINS}
    for r in csv.DictReader(open(path)):
        try:
            t = float(r["total_s"])
        except (ValueError, TypeError):
            continue
        runs[r["contract"]][r["domain"]].append(t)
        encoded[r["contract"]] = encoded.get(r["contract"], False) or (r["encoded"] == "True")
    per_domain = {d: [] for d in DOMAINS}
    for c, doms in runs.items():
        box = _mean(doms.get("Box", []))
        if box is None:
            continue
        for d in DOMAINS:
            if encoded.get(c) and doms.get(d):
                per_domain[d].append(_mean(doms[d]))
            else:
                per_domain[d].append(box)
    return {DOMAIN_LABEL[d]: (agg(per_domain[d]) if per_domain[d] else None)
            for d in DOMAINS}


def fmt(v):
    return f"{v:.2f}" if v is not None else "--"


def build_rows(agg):
    base = baseline_stats(agg)
    ours = {ds: ours_stats(ds, agg) for ds in DATASETS}
    rows = []
    for ds in DATASETS:
        row = {"dataset": DS_LABEL[ds]}
        for tool in BASELINE_ORDER:
            row[tool] = base.get(tool, {}).get(ds)
        for d in DOMAINS:
            row[f"Ours ({DOMAIN_LABEL[d]})"] = ours[ds].get(DOMAIN_LABEL[d])
        rows.append(row)
    return rows


def emit(rows, stat, csv_name, tex_name):
    our_cols = [f"Ours ({DOMAIN_LABEL[d]})" for d in DOMAINS]
    cols = ["dataset"] + BASELINE_ORDER + our_cols
    with open(OUT / csv_name, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        for r in rows:
            w.writerow({c: (fmt(r[c]) if c != "dataset" else r[c]) for c in cols})
    tex = []
    for r in rows:
        cells = [f"\\textbf{{{r['dataset']}}}"]
        cells += [fmt(r[t]) for t in BASELINE_ORDER]
        cells += [fmt(r[f"Ours ({DOMAIN_LABEL[d]})"]) for d in DOMAINS]
        tex.append("\t\t" + " & ".join(cells) + r" \\")
    (OUT / tex_name).write_text("\n".join(tex) + "\n")
    print(f"Table 8 -- {stat} per-contract analysis time (s)\n")
    print(" | ".join(c.rjust(10) for c in cols))
    for r in rows:
        print(" | ".join((r["dataset"] if c == "dataset" else fmt(r[c])).rjust(10) for c in cols))
    print(f"[ok] wrote tables/{csv_name} and tables/{tex_name}\n")


def main():
    emit(build_rows(statistics.median), "MEDIAN",
         "table8_timing_median.csv", "table8_timing.tex")
    emit(build_rows(_mean), "MEAN",
         "table8_timing_mean.csv", "table8_timing_mean.tex")


if __name__ == "__main__":
    main()
