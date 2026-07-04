#!/usr/bin/env python3
"""
make_predictions.py — build a UNIFIED, self-describing per-contract prediction
table for every tool, dataset and vulnerability, in one consistent schema:

  tool, dataset, contract, vulnerability, label, ground_truth, predicted,
  outcome, source

  * contract     : canonical id (qian = "<category>/<file>.sol"; rsd/sbc/
                   solidifi = "<file>.sol")
  * label        : safe | vulnerable  (= vulnerable iff ground_truth == 1)
  * ground_truth : 0/1
  * predicted    : 0/1
  * outcome      : TP | FP | TN | FN
  * source       : which authoritative artifact the row was derived from

Outputs:
  results/standardized/predictions.csv          (consolidated, all rows)
  results/standardized/<tool>__<dataset>.csv     (per tool x dataset)
  results/standardized/_validation.csv           (reconstructed counts vs
                                                   metrics_per_class.csv)

Each (tool,dataset,vulnerability) cell's reconstructed TP/FP/TN/FN is checked
against metrics_per_class.csv; mismatches and cells that cannot be produced
per-contract are reported (never silently wrong). Raw native outputs are left
untouched.
"""
import csv
import json
import os
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RES = ROOT / "results"
OUT = RES / "standardized"
OUT.mkdir(parents=True, exist_ok=True)

DATASET_VULNS = {
    "rsd": ["reentrancy"],
    "sbc": ["reentrancy", "overflow", "timestamp", "tod"],
    "qian": ["reentrancy", "overflow", "timestamp"],
    "solidifi": ["tod"],
}
QIAN_CAT = {"reentrancy": "reentrancy", "overflow": "overflow", "timestamp": "timestamp"}


def gt_load(ds):
    return json.load(open(ROOT / f"{ds}_ground_truth.json"))


def universe(ds, vuln, gt):
    """Return {contract_id: ground_truth_bit} for this dataset+vuln."""
    out = {}
    if ds == "qian":
        pref = QIAN_CAT[vuln] + "/"
        for k, v in gt.items():
            if k.startswith(pref):
                out[k] = int(v.get(vuln, 0))
    elif ds in ("rsd", "solidifi"):
        for k, v in gt.items():
            out[k] = int(v.get(vuln, 0))
    elif ds == "sbc":
        for k, v in gt.items():
            out[k] = int(v.get(vuln, 0))
    return out


def base(name):
    return name.split("/")[-1]


# ---------- outcomes directly from the tool's own tp/fp/tn/fn file lists -----
def outcomes_from_filelists(univ, tp_f, fp_f, tn_f, fn_f):
    """The tool lists all four outcome sets.  We recover the GT-INDEPENDENT
    prediction from list membership (tp/fp => predicted vulnerable; tn/fn =>
    predicted safe) and recompute the outcome against the CANONICAL ground truth
    in `univ`.  Contracts not in the current universe (e.g. removed from the
    dataset) are dropped — this keeps the result correct under GT revisions and
    avoids leaking stale ids."""
    byb = {base(c): c for c in univ}
    rows = {}
    for files, pred in [(tp_f, 1), (fp_f, 1), (tn_f, 0), (fn_f, 0)]:
        for f in files:
            cid = byb.get(base(f))
            if cid is None:
                continue
            g = univ[cid]
            rows[cid] = (g, pred, outcome_of(g, pred))
    return rows


def outcomes_from_fp_fn(univ, fp_files, fn_files, exclude=()):
    """Source lists only FP and FN files (e.g. mythril, ours). TP/TN derived
    from ground truth over the evaluated universe (GT minus `exclude`)."""
    fp = {base(x) for x in fp_files}
    fn = {base(x) for x in fn_files}
    ex = {base(x) for x in exclude}
    rows = {}
    for cid, g in univ.items():
        b = base(cid)
        if b in ex:
            continue
        if b in fp:
            pred, oc = 1, "FP"
        elif b in fn:
            pred, oc = 0, "FN"
        elif g == 1:
            pred, oc = 1, "TP"
        else:
            pred, oc = 0, "TN"
        rows[cid] = (g, pred, oc)
    return rows


def outcome_of(g, pred):
    return ("TP" if g else "FP") if pred else ("FN" if g else "TN")


# ----------------------- per-tool source adapters --------------------------
def src_mythril(ds, vuln, univ):
    if ds == "rsd":
        # rsd per-contract CSVs encode the outcome in 'status'; TIMEOUT -> N/A.
        byb = {base(c): c for c in univ}
        rows = {}
        st_map = {"FLAGGED_TP": "TP", "NO_FINDING": "FN", "FP": "FP", "TN": "TN"}
        for sub in ("mythril_rsd_reentrant_results.csv", "mythril_rsd_safe_results.csv"):
            p = RES / "mythril/rsd" / sub
            if not p.exists():
                continue
            for r in _read(p):
                cid = byb.get(base(r["filename"]))
                if cid is None:
                    continue
                oc = st_map.get(str(r.get("status", "")).strip().upper().replace('"', ''))
                if not oc:
                    continue  # TIMEOUT / crash -> excluded
                g = univ[cid]
                rows[cid] = (g, 1 if oc in ("TP", "FP") else 0, oc)
        return (rows, "mythril/rsd/{reentrant,safe}_results.csv") if rows else (None, None)
    rep = json.load(open(RES / "mythril/metrics_all_report.json"))
    node = rep.get(ds, {}).get(vuln)
    if not node:
        return None, None
    return outcomes_from_fp_fn(univ, node.get("FP_files", []), node.get("FN_files", [])), "mythril/metrics_all_report.json"


def src_sailfish(ds, vuln, univ):
    p = RES / f"sailfish/{ds}/sailfish_metrics_{ds}.json"
    if not p.exists():
        return None, None
    d = json.load(open(p)).get(vuln)
    if not d:
        return None, None
    return outcomes_from_filelists(univ, d.get("tp_files", []), d.get("fp_files", []),
                                   d.get("tn_files", []), d.get("fn_files", [])), str(p.relative_to(RES))


def src_osiris(ds, vuln, univ):
    if ds == "sbc":
        p = RES / "osiris/sbc/summary/osiris_sbc_classification.json"
        if not p.exists():
            return None, None
        d = json.load(open(p)).get(vuln)
        if not d:
            return None, None
        return outcomes_from_filelists(univ, d.get("tp_files", []), d.get("fp_files", []),
                                       d.get("tn_files", []), d.get("fn_files", [])), str(p.relative_to(RES))
    if ds == "qian":
        return from_status_csv(RES / "osiris/qian/summary/osiris_qian_results.csv",
                               vuln, univ)
    return None, None


def src_oyente(ds, vuln, univ):
    """Oyente+ from the canonical Docker-reproducible per-contract CSV
    results/oyente_plus/<ds>/oyente_results_<ds>.csv (pinned image, per-contract
    solc auto-search, OR-rule multi-contract harvesting).

    The CSV carries GT-independent per-vulnerability flags (reentrancy, overflow,
    timestamp, tod); the outcome is recomputed here from the flag vs the CURRENT
    SCVD ground truth in `univ`, so the comparison stays fair under GT
    revisions. Rows whose exit_status is not OK (OYENTE_CRASH / TIMEOUT with no
    verdict) are excluded as N/A — verdict emitted ⇒ counted, no verdict ⇒
    excluded, matching the policy used for the other tools.
    """
    p = RES / f"oyente_plus/{ds}/oyente_results_{ds}.csv"
    if not p.exists() or vuln not in ("reentrancy", "overflow", "timestamp", "tod"):
        return None, None
    rows = {}
    for r in _read(p):
        if str(r.get("exit_status", "")).strip().upper() != "OK":
            continue  # no verdict produced -> N/A (excluded)
        relpath = r.get("relpath", "")
        fn = base(r.get("filename", ""))
        # Qian GT keys are "<category>/<file>" (ids reused across subsets);
        # sbc/rsd/solidifi GT keys are the bare filename.
        if ds == "qian":
            parts = relpath.split("/")
            cid = (parts[1] + "/" + fn) if len(parts) > 1 else fn
        else:
            cid = fn
        if cid not in univ:
            continue
        g = univ[cid]
        pred = 1 if str(r.get(vuln, "")).strip() in ("1", "True", "true") else 0
        rows[cid] = (g, pred, outcome_of(g, pred))
    return (rows, f"oyente_plus/{ds}/oyente_results_{ds}.csv") if rows else (None, None)


def src_slither(ds, vuln, univ):
    if ds == "qian":
        return from_status_csv(RES / "slither/qian/summary/slither_qian_results.csv",
                               vuln, univ)
    if ds == "sbc":
        return from_wide_csv(RES / "slither/sbc/summary/slither_sbc_results.csv",
                             vuln, univ, flag_col=f"{vuln}_flag", key="filename",
                             status_col="status")
    if ds == "rsd":
        return from_status_csv(RES / "slither/rsd/summary/slither_rsd_results.csv",
                               vuln, univ)
    return None, None


def src_smartcheck(ds, vuln, univ):
    # qian: long-form per-category CSV (basenames collide across categories, so a
    # wide-by-basename schema is lossy) -> status-based adapter like osiris/slither.
    if ds == "qian":
        return from_status_csv(RES / "smartcheck/qian/smartcheck_results_qian.csv",
                               vuln, univ)
    fmap = {"sbc": RES / "smartcheck/sbc/smartcheck_results_sbc.csv",
            "rsd": RES / "smartcheck/rsd/smartcheck_results_rsd.csv"}
    if ds in fmap:
        # smartcheck reports no crashes (exit_status OK); flag col per vuln (1/0/-1)
        return from_wide_csv(fmap[ds], vuln, univ, flag_col=vuln, key="filename",
                             status_col="exit_status")
    return None, None


def src_ours(ds, vuln, univ):
    keymap = {("qian", "reentrancy"): "ours/qian/qian_reentrancy/ours_qian_reentrancy_summary_details.json",
              ("qian", "overflow"): "ours/qian/qian_overflow/ours_qian_overflow_summary_details.json",
              ("qian", "timestamp"): "ours/qian/qian_timestamp/ours_qian_timestamp_summary_details.json",
              ("sbc", None): "ours/sbc/ours_sbc_summary_details.json",
              ("rsd", None): "ours/rsd/ours_rsd_summary_details.json",
              ("solidifi", None): "ours/solidifi/ours_solidifi_summary_details.json"}
    rel = keymap.get((ds, vuln)) or keymap.get((ds, None))
    if not rel or not (RES / rel).exists():
        return None, None
    d = json.load(open(RES / rel)).get(vuln)
    if not d:
        return None, None
    exclude = list(d.get("na_files", [])) + list(d.get("out_of_scope_files", []))
    return outcomes_from_fp_fn(univ, d.get("fp_files", []), d.get("fn_files", []),
                               exclude=exclude), rel


# ----------------------- generic CSV readers -------------------------------
def _read(path):
    with open(path, newline="") as fh:
        return list(csv.DictReader(fh))


def from_long_csv(path, vuln, univ, flag_col):
    """tidy-long CSV: rows keyed by filename, with a 'vulnerability' column and
    a flag column. Returns outcomes for rows whose vulnerability == vuln."""
    if not path.exists():
        return None, None
    byb = {base(c): c for c in univ}
    rows = {}
    for r in _read(path):
        if r.get("vulnerability") and r["vulnerability"] != vuln:
            continue
        b = base(r["filename"])
        cid = byb.get(b)
        if cid is None:
            continue
        g = univ[cid]
        pred = 1 if str(r.get(flag_col, "")).strip() in ("1", "True", "true") else 0
        rows[cid] = (g, pred, outcome_of(g, pred))
    return rows, str(path.relative_to(RES))


def from_wide_csv(path, vuln, univ, flag_col, key="filename", status_col=None):
    """wide CSV: one row per contract, a per-vuln flag column (1/0/-1).
    If status_col is given, rows whose status indicates a crash/compile-error/
    timeout are EXCLUDED (treated as N/A), per the paper's convention."""
    if not path.exists():
        return None, None
    byb = {base(c): c for c in univ}
    rows = {}
    for r in _read(path):
        b = base(r[key])
        cid = byb.get(b)
        if cid is None:
            continue
        if status_col and _is_crash(r.get(status_col, "")):
            continue  # crash / compile-error / timeout -> N/A
        raw = str(r.get(flag_col, "")).strip()
        if raw in ("-1", "", "NA"):
            continue  # no detector -> excluded
        pred = 1 if raw in ("1", "True", "true") else 0
        g = univ[cid]
        rows[cid] = (g, pred, outcome_of(g, pred))
    return rows, str(path.relative_to(RES))


CRASH_STATUSES = {"COMPILE_ERROR", "TIMEOUT", "CRASH", "ERROR", "SKIP",
                  "SKIPPED", "N/A", "NA", "FAILED"}


def _is_crash(s):
    return str(s).strip().upper() in CRASH_STATUSES


def from_status_csv(path, vuln, univ):
    """tidy-long CSV with a 'status' column already holding the per-contract
    outcome (TP/FP/TN/FN). Crash/compile-error/timeout statuses are excluded as
    N/A. The most authoritative source when present (no flag re-derivation)."""
    if not path.exists():
        return None, None
    byb = {base(c): c for c in univ}
    rows = {}
    for r in _read(path):
        if r.get("vulnerability") and r["vulnerability"] != vuln:
            continue
        cid = byb.get(base(r["filename"]))
        if cid is None:
            continue
        st = str(r.get("status", "")).strip().upper()
        if st in ("TP", "FP", "TN", "FN"):
            g = univ[cid]
            # Recover the GT-INDEPENDENT prediction from the stored outcome
            # (TP/FP => predicted vulnerable) and recompute the outcome against
            # the current canonical ground truth, so the result stays correct
            # under GT revisions instead of trusting the frozen status label.
            pred = 1 if st in ("TP", "FP") else 0
            rows[cid] = (g, pred, outcome_of(g, pred))
        # crash/compile-error/N-A -> skip (excluded)
    return rows, str(path.relative_to(RES))


def src_vandal(ds, vuln, univ):
    # Vandal (Datalog/Souffle on decompiled bytecode) detects reentrancy only.
    if vuln != "reentrancy" or ds not in ("sbc", "qian", "rsd"):
        return None, None
    return from_wide_csv(RES / ("vandal/%s/vandal_results_%s.csv" % (ds, ds)),
                         vuln, univ, flag_col="reentrancy", key="filename", status_col="status")


def src_ethersolve(ds, vuln, univ):
    # EtherSolve (CFG + re-entrancy check on runtime bytecode) detects reentrancy only.
    if vuln != "reentrancy" or ds not in ("sbc", "qian", "rsd"):
        return None, None
    return from_wide_csv(RES / ("ethersolve/%s/ethersolve_results_%s.csv" % (ds, ds)),
                         vuln, univ, flag_col="reentrancy", key="filename", status_col="status")


ADAPTERS = {
    "ours": src_ours, "mythril": src_mythril, "oyente_plus": src_oyente,
    "slither": src_slither, "osiris": src_osiris, "smartcheck": src_smartcheck,
    "sailfish": src_sailfish, "vandal": src_vandal, "ethersolve": src_ethersolve,
}
TOOLS = list(ADAPTERS)


def load_expected():
    exp = {}
    p = ROOT / "tables" / "metrics_per_class.csv"   # paper tables live in ../tables/
    for r in _read(p):
        if r["TP"] == "NA":
            continue
        exp[(r["dataset"], r["vulnerability"], r["tool"])] = (
            int(r["TP"]), int(r["FP"]), int(r["TN"]), int(r["FN"]))
    return exp


def main():
    expected = load_expected()
    all_rows = []
    validation = []
    gtc = {ds: gt_load(ds) for ds in DATASET_VULNS}

    for ds in DATASET_VULNS:
        for vuln in DATASET_VULNS[ds]:
            for tool in TOOLS:
                exp = expected.get((ds, vuln, tool))
                univ = universe(ds, vuln, gtc[ds])
                rows, source = ADAPTERS[tool](ds, vuln, univ)
                if not rows:
                    # tool has no detector / not run / all contracts excluded -> NA
                    if exp is not None:
                        validation.append([tool, ds, vuln, "NO_PER_CONTRACT_SOURCE",
                                           exp, None])
                    continue
                # counts
                c = {"TP": 0, "FP": 0, "TN": 0, "FN": 0}
                for cid, (g, pred, oc) in rows.items():
                    c[oc] += 1
                got = (c["TP"], c["FP"], c["TN"], c["FN"])
                state = "NEW" if exp is None else ("OK" if got == exp else "MISMATCH")
                validation.append([tool, ds, vuln, state, exp, got])
                for cid, (g, pred, oc) in sorted(rows.items()):
                    all_rows.append({
                        "tool": tool, "dataset": ds, "contract": cid,
                        "vulnerability": vuln,
                        "label": "vulnerable" if g else "safe",
                        "ground_truth": g, "predicted": pred,
                        "outcome": oc, "source": source})

    # consolidated
    cols = ["tool", "dataset", "contract", "vulnerability", "label",
            "ground_truth", "predicted", "outcome", "source"]
    with open(OUT / "predictions.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols); w.writeheader(); w.writerows(all_rows)

    # per tool x dataset
    bytd = defaultdict(list)
    for r in all_rows:
        bytd[(r["tool"], r["dataset"])].append(r)
    for (tool, ds), rs in bytd.items():
        with open(OUT / f"{tool}__{ds}.csv", "w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=cols); w.writeheader(); w.writerows(rs)

    # validation report
    with open(OUT / "_validation.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["tool", "dataset", "vulnerability", "status",
                    "expected_TP_FP_TN_FN", "got_TP_FP_TN_FN"])
        for v in validation:
            w.writerow(v)

    nmis = sum(1 for v in validation if v[3] == "MISMATCH")
    nno = sum(1 for v in validation if v[3] == "NO_PER_CONTRACT_SOURCE")
    nok = sum(1 for v in validation if v[3] == "OK")
    print(f"[predictions] {len(all_rows)} rows | cells: {nok} OK, "
          f"{nmis} MISMATCH, {nno} no-per-contract")
    for v in validation:
        if v[3] != "OK":
            print(f"   {v[3]:22} {v[0]}/{v[1]}/{v[2]}  exp={v[4]} got={v[5]}")


if __name__ == "__main__":
    main()
