#!/usr/bin/env python3
"""
build_comparison.py
===================
Builds a single comparison table of OUR TOOL vs every baseline,
across all 4 datasets (rsd, sbc, qian, solidifi) and all 4 vulnerability
classes (reentrancy, overflow, timestamp, tod).

Approach
--------
Each tool reported its results in its own format (clean JSON for some, text
summaries for others) and — importantly — each used slightly different ground
-truth subsets / crash-exclusion rules. To stay faithful to every tool's
*reported* performance while keeping the metric math identical for everyone,
we extract each tool's own confusion counts (TP/FP/TN/FN) from its authoritative
output file, then recompute Precision/Recall/F1/Accuracy with one formula.

A (tool, dataset, vulnerability) cell is "NA" when that tool does not support /
was not run for that vulnerability on that dataset.

Outputs (written into ../results/ relative to this script):
  - comparison_metrics.csv   long form: dataset,vuln,tool,TP,FP,TN,FN,P,R,F1,Acc
  - comparison_table.md      pretty markdown, one block per (dataset, vuln)
and prints the markdown to stdout.
"""

import csv
import glob
import json
import os
import re
import shutil
import subprocess
import tempfile

# This script lives in scripts/; per-tool INPUTS live in ../results/, and the
# paper-facing table OUTPUTS are written to ../tables/.
_REPO = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir))
ROOT = os.path.join(_REPO, "results")
TABLES = os.path.join(_REPO, "tables")


def p(*parts):
    return os.path.join(ROOT, *parts)


def gt(ds):
    # Ground truth is canonical at the repo root as <ds>_ground_truth.json — the
    # same files run_ours.py and make_predictions.py read — so every stage shares
    # one source of truth (no second copy under results/ to drift out of sync).
    return os.path.join(_REPO, f"{ds}_ground_truth.json")


def t(*parts):
    os.makedirs(TABLES, exist_ok=True)
    return os.path.join(TABLES, *parts)


# --------------------------------------------------------------------------
# What exists in each dataset (from the ground-truth files)
# --------------------------------------------------------------------------
DATASETS = ["rsd", "sbc", "qian", "solidifi"]
DATASET_VULNS = {
    "rsd": ["reentrancy"],
    "sbc": ["reentrancy", "overflow", "timestamp", "tod"],
    "qian": ["reentrancy", "overflow", "timestamp"],
    "solidifi": ["tod"],
}
VULN_ORDER = ["reentrancy", "overflow", "timestamp", "tod"]

# Display name + ordering for tools. "ours" is pinned first.
TOOLS = ["ours", "slither", "smartcheck", "sailfish", "mythril", "oyente_plus", "osiris", "vandal", "ethersolve"]
TOOL_LABEL = {
    "ours": "Our Tool (ours)",
    "slither": "Slither",
    "smartcheck": "SmartCheck",
    "sailfish": "Sailfish",
    "mythril": "Mythril",
    "oyente_plus": "Oyente+",
    "osiris": "Osiris",
    "vandal": "Vandal",
    "ethersolve": "EtherSolve",
}
DS_TITLE = {
    "rsd": "RSD (Ressi et al.)",
    "sbc": "SBC (SmartBugs Curated)",
    "qian": "Qian",
    "solidifi": "SolidiFI",
}


# --------------------------------------------------------------------------
# Metric helpers
# --------------------------------------------------------------------------
def metrics(counts):
    """counts = (tp, fp, tn, fn) -> dict with the 4 counts + the paper's full
    metric set (P/R/F1/Accuracy/FDR/FNR) plus the ROC coordinates (TPR/FPR) and
    the single-operating-point AUC used in Fig 16.

    AUC for a single-threshold binary detector is the area of the ROC polygon
    (0,0)->(FPR,TPR)->(1,1) = (TPR + (1 - FPR)) / 2  (a.k.a. balanced accuracy).
    This reproduces the per-tool AUC values reported in Fig 16.
    """
    tp, fp, tn, fn = counts
    tot = tp + fp + tn + fn
    prec = tp / (tp + fp) if (tp + fp) else 0.0
    rec = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * prec * rec / (prec + rec) if (prec + rec) else 0.0
    acc = (tp + tn) / tot if tot else 0.0
    fdr = fp / (tp + fp) if (tp + fp) else 0.0
    fnr = fn / (tp + fn) if (tp + fn) else 0.0
    tpr = rec                                    # = recall = sensitivity
    fpr = fp / (fp + tn) if (fp + tn) else 0.0
    auc = (tpr + (1.0 - fpr)) / 2.0
    return {
        "tp": tp, "fp": fp, "tn": tn, "fn": fn,
        "precision": prec, "recall": rec, "f1": f1, "accuracy": acc,
        "fdr": fdr, "fnr": fnr, "tpr": tpr, "fpr": fpr, "auc": auc,
    }


def build_html(by):
    """Styled HTML table (grouped by dataset, one sub-table per vulnerability),
    with the TP/FP/TN/FN + Analyzed/Total/Failures + P/R/F1/FDR/FNR columns. The 'ours'
    row is highlighted and the best F1 in each block is bolded green."""
    css = """
* { box-sizing: border-box; }
body { font-family: "Segoe UI", Helvetica, Arial, sans-serif; color:#1a1a1a; margin:28px 32px; }
h1 { font-size:22px; margin:0 0 4px; }
.sub { color:#555; font-size:12px; margin-bottom:14px; }
h2 { font-size:15px; margin:20px 0 6px; padding:5px 10px; color:#fff; background:#2c3e50; border-radius:4px; page-break-after:avoid; }
.block { page-break-inside:avoid; margin-bottom:8px; }
table { border-collapse:collapse; width:100%; font-size:11.5px; margin-bottom:6px; page-break-inside:avoid; }
th, td { border:1px solid #d4d4d4; padding:4px 7px; text-align:center; }
th { background:#eef2f6; font-weight:600; }
td.tool { text-align:left; font-weight:500; white-space:nowrap; }
tr.ours { background:#fff6e0; }
tr.ours td.tool { color:#b8860b; font-weight:700; }
td.na { color:#aaa; background:#fafafa; }
td.best { font-weight:700; color:#0a7d33; }
td.excl { color:#9a3b3b; }
.legend { font-size:11px; color:#555; margin:12px 0 0; line-height:1.6; }
"""
    H = ['<!doctype html><html><head><meta charset="utf-8"><style>', css,
         '</style></head><body>',
         '<h1>Smart-Contract Vulnerability Detection — Our Tool vs. Baselines</h1>',
         '<div class="sub">Per-dataset, per-vulnerability detection metrics, recomputed '
         'uniformly from each tool\'s own TP/FP/TN/FN. <b>Analyzed</b> = TP+FP+TN+FN; '
         '<b>Total</b> = contracts in that dataset–vulnerability benchmark; '
         '<b>Failures</b> = Total − Analyzed = contracts the tool could not analyse '
         '(compile error / timeout / crash), excluded from the metrics. '
         '<b>NA</b> = tool has no detector for / was not run on that case.</div>']
    cols = ["TP", "FP", "TN", "FN"]
    for ds in DATASETS:
        H.append(f"<h2>{DS_TITLE.get(ds, ds.upper())}</h2>")
        for v in DATASET_VULNS[ds]:
            block = by[(ds, v)]
            best_f1 = max((r["f1"] for r in block if r["f1"] != "NA"), default=None)
            H.append('<div class="block">')
            H.append('<div style="font-weight:600;margin:8px 0 2px;font-size:12.5px;'
                     f'text-transform:capitalize">▸ {v}</div>')
            H.append("<table><tr><th>Tool</th><th>TP</th><th>FP</th><th>TN</th><th>FN</th>"
                     "<th>Analyzed</th><th>Total</th><th>Failures</th>"
                     "<th>Precision&nbsp;%</th><th>Recall&nbsp;%</th>"
                     "<th>F1&nbsp;%</th><th>FDR&nbsp;%</th><th>FNR&nbsp;%</th></tr>")
            for r in block:
                cls = ' class="ours"' if r["tool"] == "ours" else ""
                lbl = TOOL_LABEL[r["tool"]]
                if r["precision"] == "NA":
                    cells = ('<td class="na">NA</td>' * 4 +
                             '<td class="na">NA</td>' +
                             f'<td>{r["total"]}</td>' +
                             '<td class="na">NA</td>' +
                             '<td class="na">NA</td>' * 5)
                else:
                    def pc(x):
                        return f"{x*100:.1f}"
                    f1cls = ' class="best"' if r["f1"] == best_f1 else ""
                    cells = (f'<td>{r["TP"]}</td><td>{r["FP"]}</td><td>{r["TN"]}</td>'
                             f'<td>{r["FN"]}</td>'
                             f'<td>{r["analyzed"]}</td><td>{r["total"]}</td>'
                             f'<td class="excl">{r["excluded_na"]}</td>'
                             f'<td>{pc(r["precision"])}</td><td>{pc(r["recall"])}</td>'
                             f'<td{f1cls}>{pc(r["f1"])}</td>'
                             f'<td>{pc(r["fdr"])}</td><td>{pc(r["fnr"])}</td>')
                H.append(f'<tr{cls}><td class="tool">{lbl}</td>{cells}</tr>')
            H.append("</table>")
            H.append("</div>")
    H.append('<div class="legend">'
             '<span style="background:#fff6e0;padding:1px 6px;border-radius:3px;color:#b8860b;font-weight:700">'
             'Our Tool (ours)</span> &nbsp; '
             '<span style="color:#0a7d33;font-weight:700">best F1 per block</span> &nbsp; '
             '<span style="color:#9a3b3b">Failures = contracts the tool could not analyse (N/A)</span></div>')
    H.append("</body></html>")
    return "\n".join(H)


def render_table(html_path, pdf_path, png_path):
    """HTML -> PDF (chrome headless, soffice fallback) -> single PNG (pdftoppm +
    Pillow stitch). Best-effort: warns and returns if a renderer is missing."""
    chrome = next((b for b in ("google-chrome", "google-chrome-stable",
                               "chromium", "chromium-browser") if shutil.which(b)), None)
    made_pdf = False
    if chrome:
        try:
            subprocess.run([chrome, "--headless=new", "--disable-gpu", "--no-sandbox",
                            "--no-pdf-header-footer",
                            f"--print-to-pdf={pdf_path}", html_path],
                           capture_output=True, timeout=180, check=True)
            made_pdf = os.path.exists(pdf_path)
        except Exception as e:
            print(f"[warn] chrome PDF failed: {e}")
    if not made_pdf and shutil.which("soffice"):
        try:
            subprocess.run(["soffice", "--headless", "--convert-to", "pdf",
                            "--outdir", os.path.dirname(pdf_path), html_path],
                           capture_output=True, timeout=240, check=True)
            made_pdf = os.path.exists(pdf_path)
        except Exception as e:
            print(f"[warn] soffice PDF failed: {e}")
    if made_pdf:
        print(f"[ok] wrote {pdf_path}")
    else:
        print("[warn] no PDF produced -> skipping PNG"); return
    if not shutil.which("pdftoppm"):
        print("[warn] no pdftoppm -> skipping PNG"); return
    with tempfile.TemporaryDirectory() as td:
        pref = os.path.join(td, "pg")
        subprocess.run(["pdftoppm", "-png", "-r", "150", pdf_path, pref],
                       capture_output=True, timeout=180)
        pages = sorted(glob.glob(pref + "*.png"))
        if not pages:
            print("[warn] pdftoppm produced nothing"); return
        try:
            from PIL import Image
            imgs = [Image.open(x).convert("RGB") for x in pages]
            W = max(i.width for i in imgs)
            Htot = sum(i.height for i in imgs)
            canvas = Image.new("RGB", (W, Htot), "white")
            y = 0
            for im in imgs:
                canvas.paste(im, (0, y))
                y += im.height
            canvas.save(png_path)
            print(f"[ok] wrote {png_path} ({len(pages)} page(s) stitched)")
        except Exception as e:
            shutil.copy(pages[0], png_path)
            print(f"[ok] wrote {png_path} (page 1 only; stitch failed: {e})")


def load_json(path):
    with open(path) as fh:
        return json.load(fh)


def read_text(path):
    with open(path) as fh:
        return fh.read()


# Statuses that mean the tool could not analyse the contract -> excluded as N/A
# (never counted as TN/FN). Everything else is a genuine analysed result. Note
# the older overflow CSV folds the outcome into `status` (TP/FP/TN/FN), while the
# newer reentrancy/timestamp CSVs use status=OK + a separate `outcome` column;
# this set excludes only true crashes, so both schemas work.
CRASH_STATUSES = {"COMPILE_ERROR", "TIMEOUT", "OYENTE_CRASH", "ERROR", "CRASH",
                  "NO_JSON", "SKIPPED"}


def counts_from_flag_csv(path, flag_col):
    """TP/FP/TN/FN from a per-contract results CSV, recomputed from the tool's
    flag column vs ground_truth. Crash/compile-error/timeout rows are EXCLUDED
    as N/A — never counted as TN/FN (paper convention)."""
    tp = fp = tn = fn = 0
    with open(path) as fh:
        for r in csv.DictReader(fh):
            st = (r.get("status", "") or "").strip().upper()
            if st in CRASH_STATUSES or st.startswith("ERROR"):
                continue
            pred = int(r[flag_col])
            gt = int(r["ground_truth"])
            if pred and gt:        tp += 1
            elif not pred and not gt: tn += 1
            elif pred and not gt:  fp += 1
            else:                  fn += 1
    return (tp, fp, tn, fn)


def oyente_qian_from_csv():
    """Oyente+ Qian counts derived directly from the per-contract CSVs (one per
    vulnerability subset) — fully consistent with the per-contract evidence,
    superseding the older text-summary parse."""
    base = "oyente_plus/qian/summary"
    return {
        "reentrancy": counts_from_flag_csv(p(base, "oyente_reentrancy_results.csv"), "reentrancy_flag"),
        "overflow":   counts_from_flag_csv(p(base, "oyente_overflow_results.csv"),   "overflow_flag"),
        "timestamp":  counts_from_flag_csv(p(base, "oyente_timestamp_results.csv"),  "timestamp_flag"),
    }


# --------------------------------------------------------------------------
# Generic text-summary parsers
# --------------------------------------------------------------------------
VULN_HEADERS = {
    "REENTRANCY": "reentrancy",
    "OVERFLOW": "overflow",
    "TIMESTAMP": "timestamp",
    "TOD": "tod",
}
TP_LINE = re.compile(
    r"TP\s*=\s*(\d+)\s+FP\s*=\s*(\d+)\s+TN\s*=\s*(\d+)\s+FN\s*=\s*(\d+)")


def parse_block_summary(text):
    """Parse the '  REENTRANCY / ----- / TP=.. FP=.. TN=.. FN=..' style used by
    slither (sbc, qian), osiris (qian) and oyente+ (qian). Returns
    {vuln: (tp,fp,tn,fn) | 'NA'}."""
    out = {}
    cur = None
    buf = []

    def flush():
        if not cur:
            return
        seg = "\n".join(buf)
        m = TP_LINE.search(seg)
        if m:
            out[cur] = tuple(int(x) for x in m.groups())
        elif re.search(r"N/?\\?A|does not|not support", seg, re.I):
            out[cur] = "NA"

    for line in text.splitlines():
        s = line.strip()
        key = None
        for hdr, v in VULN_HEADERS.items():
            if s == hdr or s.startswith(hdr + " ") or s.startswith(hdr + "("):
                key = v
                break
        # A header is a short standalone line, never the "TP=" data line.
        if key and len(s) < 45 and not s.startswith("TP"):
            flush()
            cur = key
            buf = []
        else:
            buf.append(line)
    flush()
    return out


def parse_confmatrix_summary(text):
    """slither rsd: lines like 'TP  (reentrant, correctly flagged) : 62'."""
    d = {}
    for lab in ("TP", "FP", "TN", "FN"):
        m = re.search(rf"^\s*{lab}\s*\(.*?\)\s*:\s*(\d+)", text, re.M)
        if not m:
            return {}
        d[lab] = int(m.group(1))
    return {"reentrancy": (d["TP"], d["FP"], d["TN"], d["FN"])}


def parse_smartcheck_summary(text):
    """smartcheck/summary.txt: 'SBC Dataset' / 'Qian Dataset' sections with
    rows 'reentrancy 29 56 55 2 ...'. Returns {ds: {vuln: counts|'NA'}}."""
    res = {"sbc": {}, "qian": {}}
    cur = None
    row = re.compile(
        r"^\s*(reentrancy|overflow|timestamp|tod)\s+"
        r"([\d—]+|N/A)\s+([\d—]+)\s+([\d—]+)\s+([\d—]+)")
    for line in text.splitlines():
        if "SBC Dataset" in line:
            cur = "sbc"
        elif "Qian Dataset" in line:
            cur = "qian"
        m = row.match(line)
        if m and cur:
            v = m.group(1)
            if "—" in (m.group(2), m.group(3), m.group(4), m.group(5)) or m.group(2) == "N/A":
                res[cur][v] = "NA"
            else:
                res[cur][v] = tuple(int(m.group(i)) for i in range(2, 6))
    return res


# --------------------------------------------------------------------------
# Per-tool adapters: each returns {dataset: {vuln: (tp,fp,tn,fn) | 'NA'}}
# Missing dataset/vuln keys are treated as NA downstream.
# --------------------------------------------------------------------------
def tool_ours():
    out = {}
    def counts(d, v):
        x = d[v]
        return (x["tp"], x["fp"], x["tn"], x["fn"])
    rsd = load_json(p("ours/rsd/ours_rsd_summary_details.json"))
    out["rsd"] = {"reentrancy": counts(rsd, "reentrancy")}
    sbc = load_json(p("ours/sbc/ours_sbc_summary_details.json"))
    out["sbc"] = {v: counts(sbc, v) for v in ("reentrancy", "overflow", "timestamp", "tod")}
    sol = load_json(p("ours/solidifi/ours_solidifi_summary_details.json"))
    out["solidifi"] = {"tod": counts(sol, "tod")}
    out["qian"] = {}
    for v, sub in (("reentrancy", "qian_reentrancy"),
                   ("overflow", "qian_overflow"),
                   ("timestamp", "qian_timestamp")):
        d = load_json(p(f"ours/qian/{sub}/ours_{sub}_summary_details.json"))
        out["qian"][v] = counts(d, v)
    return out


def tool_mythril():
    d = load_json(p("mythril/metrics_all_report.json"))
    out = {}
    for ds, vulns in d.items():
        out[ds] = {}
        for v, x in vulns.items():
            out[ds][v] = (x["TP"], x["FP"], x["TN"], x["FN"])
    return out


def tool_sailfish():
    out = {}
    for ds in ("rsd", "sbc", "qian", "solidifi"):
        d = load_json(p(f"sailfish/{ds}/sailfish_metrics_{ds}.json"))
        out[ds] = {}
        for v, x in d.items():
            out[ds][v] = (x["tp"], x["fp"], x["tn"], x["fn"])
    return out


def tool_oyente():
    out = {}
    # sbc + solidifi: clean JSON with per-vuln 'counts'
    sbc = load_json(p("oyente_plus/sbc/metrics_sbc.json"))
    out["sbc"] = {}
    for v, node in sbc["per_vulnerability"].items():
        c = node["counts"]
        out["sbc"][v] = (c["tp"], c["fp"], c["tn"], c["fn"])
    sol = load_json(p("oyente_plus/solidifi/metrics_solidifi.json"))
    c = sol["tod"]["counts"]
    out["solidifi"] = {"tod": (c["tp"], c["fp"], c["tn"], c["fn"])}
    # qian: derived directly from per-contract CSVs (reentrancy/overflow/timestamp)
    out["qian"] = oyente_qian_from_csv()
    # rsd: reentrant subset (TP,FN) + safe subset (FP,TN)
    rt = read_text(p("oyente_plus/rsd/reentrant_summary.txt"))
    sf = read_text(p("oyente_plus/rsd/safe_summary.txt"))
    m1 = re.search(r"TP\s*=\s*(\d+)\s+FN\s*=\s*(\d+)", rt)
    fp = re.search(r"^\s*FP\b.*:\s*(\d+)", sf, re.M)
    tn = re.search(r"^\s*TN\b.*:\s*(\d+)", sf, re.M)
    if m1 and fp and tn:
        out["rsd"] = {"reentrancy": (int(m1.group(1)), int(fp.group(1)),
                                     int(tn.group(1)), int(m1.group(2)))}
    return out


def tool_slither():
    out = {}
    out["rsd"] = parse_confmatrix_summary(read_text(p("slither/rsd/summary/slither_rsd_summary.txt")))
    out["sbc"] = parse_block_summary(read_text(p("slither/sbc/summary/slither_sbc_summary.txt")))
    out["qian"] = parse_block_summary(read_text(p("slither/qian/summary/slither_qian_summary.txt")))
    return out


def tool_osiris():
    out = {}
    cls = load_json(p("osiris/sbc/summary/osiris_sbc_classification.json"))
    out["sbc"] = {v: (cls[v]["tp"], cls[v]["fp"], cls[v]["tn"], cls[v]["fn"]) for v in cls}
    out["qian"] = parse_block_summary(read_text(p("osiris/qian/summary/osiris_qian_summary.txt")))
    return out


def tool_smartcheck():
    return parse_smartcheck_summary(read_text(p("smartcheck/summary.txt")))


ADAPTERS = {
    "ours": tool_ours,
    "slither": tool_slither,
    "smartcheck": tool_smartcheck,
    "sailfish": tool_sailfish,
    "mythril": tool_mythril,
    "oyente_plus": tool_oyente,
    "osiris": tool_osiris,
}


def counts_from_predictions():
    """Single source of truth: aggregate results/standardized/predictions.csv
    (per-contract: tool, dataset, vulnerability, ground_truth, predicted) into
    {tool: {ds: {vuln: (tp,fp,tn,fn)}}}.

    Each contract's outcome is recomputed from `predicted` (GT-independent) vs
    the *canonical* `ground_truth` carried per row, so the comparison tables are
    reproducible and stay correct under ground-truth revisions — unlike the
    per-tool raw adapters below, which read pre-aggregated reports frozen against
    whatever GT was current when the tool last ran.  The legacy ADAPTERS are kept
    for provenance / regenerating predictions.csv from raw, but the published
    metrics are derived here."""
    path = p("standardized/predictions.csv")
    agg = {}
    with open(path) as fh:
        for r in csv.DictReader(fh):
            g = int(r["ground_truth"]); pred = int(r["predicted"])
            oc = ("TP" if g else "FP") if pred else ("FN" if g else "TN")
            d = agg.setdefault(r["tool"], {}).setdefault(r["dataset"], {})
            tp, fp, tn, fn = d.get(r["vulnerability"], (0, 0, 0, 0))
            if oc == "TP":   tp += 1
            elif oc == "FP": fp += 1
            elif oc == "TN": tn += 1
            else:            fn += 1
            d[r["vulnerability"]] = (tp, fp, tn, fn)
    return agg


# --------------------------------------------------------------------------
# Assemble
# --------------------------------------------------------------------------
def main():
    # Derive every tool's counts from the per-contract predictions.csv (the
    # single source of truth), so the tables are reproducible and reflect the
    # current ground truth.  Falls back to the legacy raw adapters only if
    # predictions.csv is missing.
    try:
        data = counts_from_predictions()  # tool -> {ds -> {vuln -> counts}}
    except FileNotFoundError:
        print("[warn] predictions.csv missing — falling back to raw adapters")
        data = {}
        for tool, fn in ADAPTERS.items():
            try:
                data[tool] = fn()
            except Exception as exc:
                print(f"[warn] {tool}: {exc}")
                data[tool] = {}

    # Benchmark total per (dataset, vulnerability) from the ground truth, so we
    # can report how many contracts each tool could NOT analyse (crash / compile
    # error / timeout) — these are excluded from the metrics as N/A. qian has a
    # distinct per-vulnerability subset; rsd/sbc/solidifi share one contract set.
    total = {}
    qgt = load_json(gt("qian"))
    for k in qgt:
        cat = k.split("/")[0]
        total[("qian", cat)] = total.get(("qian", cat), 0) + 1
    for ds in ("rsd", "sbc", "solidifi"):
        n = len(load_json(gt(ds)))
        for v in DATASET_VULNS[ds]:
            total[(ds, v)] = n

    rows = []  # long form
    for ds in DATASETS:
        for v in DATASET_VULNS[ds]:
            U = total.get((ds, v), "NA")
            for tool in TOOLS:
                cell = data.get(tool, {}).get(ds, {}).get(v, "NA")
                # zero-total (e.g. every contract skipped) == not evaluated -> NA
                if isinstance(cell, tuple) and sum(cell) == 0:
                    cell = "NA"
                if cell == "NA" or cell is None:
                    rows.append({"dataset": ds, "vulnerability": v, "tool": tool,
                                 "TP": "NA", "FP": "NA", "TN": "NA", "FN": "NA",
                                 "analyzed": "NA", "total": U, "excluded_na": "NA",
                                 "precision": "NA", "recall": "NA",
                                 "f1": "NA", "accuracy": "NA",
                                 "fdr": "NA", "fnr": "NA",
                                 "tpr": "NA", "fpr": "NA", "auc": "NA"})
                else:
                    m = metrics(cell)
                    analyzed = m["tp"] + m["fp"] + m["tn"] + m["fn"]
                    excluded = (U - analyzed) if isinstance(U, int) else "NA"
                    rows.append({"dataset": ds, "vulnerability": v, "tool": tool,
                                 "TP": m["tp"], "FP": m["fp"], "TN": m["tn"], "FN": m["fn"],
                                 "analyzed": analyzed, "total": U,
                                 "excluded_na": excluded,
                                 "precision": round(m["precision"], 4),
                                 "recall": round(m["recall"], 4),
                                 "f1": round(m["f1"], 4),
                                 "accuracy": round(m["accuracy"], 4),
                                 "fdr": round(m["fdr"], 4),
                                 "fnr": round(m["fnr"], 4),
                                 "tpr": round(m["tpr"], 4),
                                 "fpr": round(m["fpr"], 4),
                                 "auc": round(m["auc"], 4)})

    # ---- long-form CSV ----
    fieldnames = ["dataset", "vulnerability", "tool",
                  "TP", "FP", "TN", "FN",
                  "analyzed", "total", "excluded_na",
                  "precision", "recall", "f1", "accuracy",
                  "fdr", "fnr", "tpr", "fpr", "auc"]
    csv_path = t("comparison_metrics.csv")
    with open(csv_path, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)
    # alias with a clearer name for the paper (Tables 3-6 + Fig 16 AUC source)
    with open(t("metrics_per_class.csv"), "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)

    # ---- markdown ----
    def fmt(x):
        return f"{x*100:5.1f}" if isinstance(x, float) else " NA "

    md = []
    md.append("# Tool vs Baselines — Detection Metrics\n")
    md.append("Cells are **NA** when a tool has no detector for that vulnerability "
              "or was not run on that dataset. Metrics are recomputed uniformly "
              "from each tool's own TP/FP/TN/FN counts.\n")
    md.append("**Analyzed** = TP+FP+TN+FN (contracts with a usable verdict). "
              "**Total** = number of contracts in that dataset–vulnerability benchmark. "
              "**Failures** = Total − Analyzed = contracts the tool could not analyse "
              "(compile error / timeout / crash), excluded from the metrics as N/A.\n")
    by = {(r["dataset"], r["vulnerability"]): [] for r in rows}
    for r in rows:
        by[(r["dataset"], r["vulnerability"])].append(r)

    for ds in DATASETS:
        for v in DATASET_VULNS[ds]:
            md.append(f"\n## {ds.upper()} — {v}\n")
            md.append("| Tool | TP | FP | TN | FN | Analyzed | Total | Failures | Precision % | Recall % | F1 % | FDR % | FNR % |")
            md.append("|------|----|----|----|----|----------|------|-----------|-------------|----------|------|-------|-------|")
            for r in by[(ds, v)]:
                lbl = TOOL_LABEL[r["tool"]]
                if r["precision"] == "NA":
                    md.append(f"| {lbl} | NA | NA | NA | NA | NA | {r['total']} | NA "
                              f"| NA | NA | NA | NA | NA |")
                else:
                    md.append(
                        f"| {lbl} | {r['TP']} | {r['FP']} | {r['TN']} | {r['FN']} "
                        f"| {r['analyzed']} | {r['total']} | {r['excluded_na']} "
                        f"| {fmt(r['precision'])} | {fmt(r['recall'])} "
                        f"| {fmt(r['f1'])} | {fmt(r['fdr'])} | {fmt(r['fnr'])} |")

    md_text = "\n".join(md) + "\n"
    with open(t("comparison_table.md"), "w") as fh:
        fh.write(md_text)

    # ---- styled HTML + PDF + PNG (all regenerated from the same rows) ----
    html_path = t("comparison_table.html")
    with open(html_path, "w") as fh:
        fh.write(build_html(by))

    print(f"[ok] wrote {csv_path}")
    print(f"[ok] wrote {t('metrics_per_class.csv')}")
    print(f"[ok] wrote {t('comparison_table.md')}")
    print(f"[ok] wrote {html_path}")
    render_table(html_path, t("comparison_table.pdf"), t("comparison_table.png"))


if __name__ == "__main__":
    main()
