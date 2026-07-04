#!/usr/bin/env python3
"""
run_ours.py — Batch runner for the abstract-interpretation analysis framework.

Runs main.py on every .sol file in a dataset directory, collects results into
a CSV, and (when ground truth is available) computes TP/TN/FP/FN metrics per
vulnerability with per-file breakdown.

Output files (in --output-dir):
    ours_results_{dataset}.csv             per-contract verdicts
    ours_{dataset}_summary.txt             human-readable metrics report
    ours_{dataset}_summary_details.json    machine-readable metrics

Usage:
    python3 run_ours.py sbc                               all vulns on SBC
    python3 run_ours.py sbc --vulns tod                   only TOD on SBC
    python3 run_ours.py sbc --vulns reentrancy,overflow   selected vulns on SBC
    python3 run_ours.py sbc --metrics-only                skip analysis, recompute metrics
    python3 run_ours.py sbc --fresh --workers 4           clean re-run, parallel
    python3 run_ours.py qian_reentrancy --workers 4       Qian dataset
    python3 run_ours.py custom --input-dir path/ --output-dir results/

Dataset key formats (must match build_ground_truth.py):
    sbc              -> filename.sol
    qian_reentrancy  -> reentrancy/filename.sol
    qian_overflow    -> overflow/filename.sol
    qian_timestamp   -> timestamp/filename.sol
    rsd              -> filename.sol
    solidifi         -> filename.sol
"""

import argparse
import csv
import json
import os
import re
import shutil
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

ALL_VULNS = ("reentrancy", "overflow", "timestamp", "tod")

VULN_LABELS = {
    "reentrancy": "REENTRANCY",
    "overflow":   "OVERFLOW / UNDERFLOW",
    "timestamp":  "TIMESTAMP DEPENDENCE",
    "tod":        "TOD (FRONT-RUNNING)",
}

DATASET_DEFAULTS = {
    "sbc": {
        "input_dir":  "datasets/sbc/",
        "output_dir": "results/ours/sbc/",
        "tool_dir":   "src/",
    },
    "qian_reentrancy": {
        "input_dir":  "datasets/qian/reentrancy/",
        "output_dir": "results/ours/qian/qian_reentrancy/",
        "tool_dir":   "src/",
        "default_vulns": ("reentrancy",),
    },
    "qian_overflow": {
        "input_dir":  "datasets/qian/overflow/",
        "output_dir": "results/ours/qian/qian_overflow/",
        "tool_dir":   "src/",
        "default_vulns": ("overflow",),
    },
    "qian_timestamp": {
        "input_dir":  "datasets/qian/timestamp/",
        "output_dir": "results/ours/qian/qian_timestamp/",
        "tool_dir":   "src/",
        "default_vulns": ("timestamp",),
    },
    "rsd": {
        "input_dir":  "datasets/rsd/",
        "output_dir": "results/ours/rsd/",
        "tool_dir":   "src/",
    },
    "solidifi": {
        "input_dir":  "datasets/solidifi/",
        "output_dir": "results/ours/solidifi/",
        "tool_dir":   "src/",
    },
}


# ──────────────────────────────────────────────────────────────────────────────
# KEY COMPUTATION — must match build_ground_truth.py
# ──────────────────────────────────────────────────────────────────────────────

def csv_key(filepath, input_dir, dataset):
    sol  = Path(filepath).resolve()
    base = Path(input_dir).resolve()
    if dataset.startswith("qian"):
        return f"{base.name}/{sol.name}"
    return sol.name


# ──────────────────────────────────────────────────────────────────────────────
# VERDICT PARSING
# ──────────────────────────────────────────────────────────────────────────────

# Matches actual verdict lines only — excludes log/progress lines.
# Each pattern covers ALL verdict variants emitted by main.py.
_VERDICT_RE = {
    "reentrancy": re.compile(
        r'\[REENTRANCY\]\s+'
        r'(Balance-preservation invariant violated'
        r'|Modifier-based reentrancy in function'
        r'|ERC-20 interface reentrancy in function'
        r'|State update after external call in function)',
        re.I,
    ),
    "overflow": re.compile(
        r'\[(OVERFLOW|UNDERFLOW)\]\s+Variable\b', re.I),
    "timestamp": re.compile(
        r'\[TIMESTAMP\]\s+(block\b|State\b|Boolean\b|Return\b)', re.I),
    "tod": re.compile(
        r'\[TOD\]\s+\w', re.I),
}


def parse_verdicts_from_text(text):
    result = {v: 0 for v in _VERDICT_RE}
    for line in text.splitlines():
        for vuln, pat in _VERDICT_RE.items():
            if pat.search(line):
                result[vuln] = 1
    return result


def parse_verdicts_from_json(json_path):
    try:
        jv = json.loads(Path(json_path).read_text())
        verdicts = {v: int(jv.get(v, 0)) for v in _VERDICT_RE}
        if jv.get("skipped_pipelines") or jv.get("error"):
            all_skipped = all(verdicts[v] == -1 for v in _VERDICT_RE)
            verdicts["_partial"] = "ALL_SKIPPED" if all_skipped else "PARTIAL"
            verdicts["_skip_reason"] = jv.get("error", "")
        return verdicts
    except Exception:
        return None


# ──────────────────────────────────────────────────────────────────────────────
# SINGLE CONTRACT
# ──────────────────────────────────────────────────────────────────────────────

def analyze_one(filepath, output_dir, tool_dir, timeout, input_dir, dataset,
                vulns, index=1, total=1):
    fname   = csv_key(filepath, input_dir, dataset)
    stem    = fname.replace("/", "__").replace(".sol", "")
    raw_dir = Path(output_dir) / "raw_output"
    raw_dir.mkdir(parents=True, exist_ok=True)
    log_out = raw_dir / f"{stem}.txt"

    result = dict(
        filename=fname,
        reentrancy=0, overflow=0, timestamp=0, tod=0,
        duration_s=0.0,
        exit_status="OK",
        solc_version="auto",
        raw_output_path=str(log_out),
    )

    main_py = os.path.join(os.path.abspath(tool_dir), "main.py")
    if not os.path.exists(main_py):
        result["exit_status"] = "ERROR:main.py not found"
        log_out.write_text(f"main.py not found at {main_py}\n")
        return result

    cmd = [
        sys.executable, main_py,
        os.path.abspath(filepath),
        "--output-dir", str(raw_dir.resolve()),
        "--json",
    ]
    if vulns:
        cmd.extend(["--pipelines", ",".join(vulns)])

    short = fname[-52:] if len(fname) > 52 else fname
    print(f"[{index:>5}/{total}] → {short:<54}", end="", flush=True)
    t0 = time.time()

    output = ""
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True, text=True,
            timeout=timeout if timeout > 0 else None,
            cwd=os.path.abspath(tool_dir),
        )
        output = (proc.stdout or "") + "\n" + (proc.stderr or "")
        log_out.write_text(output)
        if proc.returncode != 0:
            result["exit_status"] = f"ERROR:rc={proc.returncode}"
    except subprocess.TimeoutExpired:
        result["exit_status"] = "TIMEOUT"
        log_out.write_text("TIMEOUT\n")
    except Exception as e:
        result["exit_status"] = f"ERROR:{e}"
        log_out.write_text(str(e) + "\n")

    elapsed = round(time.time() - t0, 1)
    result["duration_s"] = elapsed

    if result["exit_status"] == "OK" or result["exit_status"].startswith("ERROR:rc="):
        json_path = raw_dir / f"{stem}_verdicts.json"
        verdicts  = None

        if result["exit_status"] == "OK":
            verdicts = parse_verdicts_from_json(json_path)

        if verdicts is None:
            verdicts = parse_verdicts_from_text(output)

        partial_flag = verdicts.pop("_partial",     None)
        _            = verdicts.pop("_skip_reason", None)
        result.update(verdicts)
        if partial_flag == "ALL_SKIPPED":
            result["exit_status"] = "SKIPPED(transform_fail)"
        elif partial_flag == "PARTIAL":
            result["exit_status"] = "PARTIAL(some_skipped)"

    flag_parts = []
    for v in ALL_VULNS:
        val = result[v]
        if val == 1:
            flag_parts.append(v[:4].upper())
        elif val == -1:
            flag_parts.append(v[:4].upper() + "=N/A")
    flags_str = ",".join(flag_parts) if flag_parts else "clean"
    print(f"  {result['exit_status']:<26}  [{flags_str:<22}]  {elapsed}s",
          flush=True)
    return result


# ──────────────────────────────────────────────────────────────────────────────
# GROUND TRUTH
# ──────────────────────────────────────────────────────────────────────────────

def find_ground_truth(dataset, explicit_path=None):
    if explicit_path:
        p = Path(explicit_path)
        if p.exists():
            return p
        print(f"  [WARN] --ground-truth path not found: {p}")
        return None
    names = [dataset]
    base = dataset.split("_")[0]
    if base != dataset:
        names.append(base)
    for name in names:
        for template in ["{}_ground_truth.json",
                         "ground_truth/{}_ground_truth.json",
                         "results/{}_ground_truth.json"]:
            p = Path(template.format(name))
            if p.exists():
                return p
    return None


# ──────────────────────────────────────────────────────────────────────────────
# METRICS
# ──────────────────────────────────────────────────────────────────────────────

def _classify(gt, tool_csv, vuln):
    tp, fp, tn, fn, na = [], [], [], [], []
    for fname, labels in sorted(gt.items()):
        gt_v  = labels.get(vuln, 0)
        entry = tool_csv.get(fname)
        if entry is None:
            continue
        pred = int(entry.get(vuln, 0))
        if pred == -1:
            na.append(fname)
            continue
        if   gt_v == 1 and pred == 1: tp.append(fname)
        elif gt_v == 0 and pred == 1: fp.append(fname)
        elif gt_v == 0 and pred == 0: tn.append(fname)
        else:                         fn.append(fname)
    return tp, fp, tn, fn, na


_OOS_RE     = re.compile(r'\bassembly\b\s*(\(.*?\))?\s*\{|\blibrary\b\s+\w+', re.S)
_COMMENT_RE = re.compile(r'//[^\n]*|/\*.*?\*/', re.S)
_STRING_RE  = re.compile(r'(?:hex)?"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'', re.S)


def _strip_comments_and_strings(text):
    text = _COMMENT_RE.sub(lambda m: " " * len(m.group(0)), text)
    text = _STRING_RE.sub(lambda m: " " * len(m.group(0)), text)
    return text


def _find_source(fname, input_dir):
    if not input_dir:
        return None
    base = Path(input_dir)
    direct = base / fname
    if direct.exists():
        return direct
    matches = list(base.rglob(fname))
    return matches[0] if matches else None


def _is_out_of_scope(fname, input_dir):
    src = _find_source(fname, input_dir)
    if src is None:
        return False
    try:
        text = src.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return False
    return bool(_OOS_RE.search(_strip_comments_and_strings(text)))


def _sbc_oos_set(gt, tool_csv, input_dir):
    _, _, _, _, re_na = _classify(gt, tool_csv, "reentrancy")
    return [f for f in re_na if _is_out_of_scope(f, input_dir)]


def _apply_sbc_oos(vuln, tp_f, fp_f, tn_f, fn_f, na_f, oos_set, gt):
    oos = set(oos_set)
    tp_f = [f for f in tp_f if f not in oos]
    fp_f = [f for f in fp_f if f not in oos]
    tn_f = [f for f in tn_f if f not in oos]
    fn_f = [f for f in fn_f if f not in oos]
    still_na = []
    for fname in na_f:
        if fname in oos:
            continue
        elif gt.get(fname, {}).get(vuln, 0) == 0:
            tn_f.append(fname)
        else:
            still_na.append(fname)
    oos_f = [f for f in oos_set if f in gt]
    return tp_f, fp_f, tn_f, fn_f, still_na, oos_f


def _rates(tp, fp, tn, fn):
    p   = tp / (tp + fp)      if tp + fp > 0      else None
    r   = tp / (tp + fn)      if tp + fn > 0      else None
    f1  = 2 * p * r / (p + r) if p and r and p + r > 0 else None
    acc = (tp + tn) / (tp + fp + tn + fn) if tp + fp + tn + fn > 0 else None
    return p, r, f1, acc


def _pct(v):
    return f"{v * 100:.1f}%" if v is not None else "N/A"


def run_metrics(gt_path, csv_path, output_dir, dataset, vulns, batch_time,
                total_files, status_counts, input_dir=None):
    gt = json.loads(gt_path.read_text())
    tool_csv = {}
    with open(csv_path, newline="") as f:
        for row in csv.DictReader(f):
            tool_csv[row["filename"]] = row

    gt = {k: v for k, v in gt.items() if k in tool_csv}

    active = sorted(vulns) if vulns else list(ALL_VULNS)
    out_dir = Path(output_dir)
    W = 65

    # ── Per-vulnerability results ────────────────────────────────────────────
    all_metrics = {}
    lines = []

    lines.append("=" * W)
    lines.append(f"OUR TOOL {dataset.upper()} — PER-VULNERABILITY RESULTS")
    lines.append("=" * W)
    lines.append(f"Total files  : {len(tool_csv)} unique contracts")
    lines.append(f"Analysis OK  : {status_counts.get('ok',0)}  |  "
                 f"Partial: {status_counts.get('partial',0)}  |  "
                 f"Timeout: {status_counts.get('timeout',0)}  |  "
                 f"Error: {status_counts.get('error',0)}  |  "
                 f"Skipped: {status_counts.get('skipped',0)}")
    if batch_time:
        lines.append(f"Batch time   : {batch_time:.0f}s "
                     f"({batch_time/60:.0f} min)")
    lines.append("=" * W)
    lines.append("")

    agg_tp = agg_fp = agg_tn = agg_fn = 0

    oos_set = _sbc_oos_set(gt, tool_csv, input_dir) if dataset == "sbc" else []

    for vuln in active:
        gt_pos = sum(1 for l in gt.values() if l.get(vuln, 0) == 1)
        gt_neg = len(gt) - gt_pos
        if gt_pos == 0 and vuln not in [v for v in active]:
            continue

        tp_f, fp_f, tn_f, fn_f, na_f = _classify(gt, tool_csv, vuln)

        oos_f = []
        if dataset == "sbc":
            tp_f, fp_f, tn_f, fn_f, na_f, oos_f = _apply_sbc_oos(
                vuln, tp_f, fp_f, tn_f, fn_f, na_f, oos_set, gt)

        tp, fp, tn, fn = len(tp_f), len(fp_f), len(tn_f), len(fn_f)
        na = len(na_f)
        oos = len(oos_f)
        p, r, f1, acc = _rates(tp, fp, tn, fn)
        evaluated = tp + fp + tn + fn

        agg_tp += tp; agg_fp += fp; agg_tn += tn; agg_fn += fn

        all_metrics[vuln] = {
            "tp": tp, "fp": fp, "tn": tn, "fn": fn, "na": na,
            "precision": round(p, 4)   if p   is not None else None,
            "recall":    round(r, 4)   if r   is not None else None,
            "f1":        round(f1, 4)  if f1  is not None else None,
            "accuracy":  round(acc, 4) if acc is not None else None,
            "fp_files":  sorted(fp_f),
            "fn_files":  sorted(fn_f),
            "na_files":  sorted(na_f),
        }
        if oos_f:
            all_metrics[vuln]["out_of_scope"] = oos
            all_metrics[vuln]["out_of_scope_files"] = sorted(oos_f)

        label = VULN_LABELS.get(vuln, vuln.upper())
        lines.append(f"  {label}")
        lines.append(f"  {'-'*55}")
        lines.append(f"  Ground truth : {gt_pos} positive + {gt_neg} negative")
        oos_note = f"  |  Out-of-scope: {oos}" if oos_f else ""
        lines.append(f"  Evaluated    : {evaluated}  |  Excluded (N/A): {na}"
                     f"{oos_note}")
        oos_tag = f"  OOS={oos}" if oos_f else ""
        lines.append(f"  TP={tp}  FP={fp}  TN={tn}  FN={fn}  N/A={na}{oos_tag}")
        lines.append(f"  Precision : {_pct(p)}  "
                     f"[TP/(TP+FP) = {tp}/{tp+fp}]")
        lines.append(f"  Recall    : {_pct(r)}  "
                     f"[TP/(TP+FN) = {tp}/{tp+fn}]")
        lines.append(f"  F1        : {_pct(f1)}")
        lines.append(f"  Accuracy  : {_pct(acc)}  "
                     f"[(TP+TN)/evaluated = {tp+tn}/{evaluated}]")
        if fp_f:
            lines.append(f"  FP files ({fp}):")
            for fname in sorted(fp_f):
                lines.append(f"    - {fname}")
        if fn_f:
            lines.append(f"  FN files ({fn}):")
            for fname in sorted(fn_f):
                lines.append(f"    - {fname}")
        if na_f:
            lines.append(f"  N/A files ({na}) — excluded (tool could not decide):")
            for fname in sorted(na_f):
                lines.append(f"    - {fname}")
        if oos_f:
            lines.append(f"  Out-of-scope files ({oos}) — unsupported Solidity "
                         f"constructs (assembly/library), excluded from metrics:")
            for fname in sorted(oos_f):
                lines.append(f"    - {fname}")
        lines.append("")

    # ── Aggregate ────────────────────────────────────────────────────────────
    if len(active) > 1:
        mp, mr, mf1, macc = _rates(agg_tp, agg_fp, agg_tn, agg_fn)
        lines.append("=" * W)
        lines.append(f"  AGGREGATE (all {len(active)} vulnerabilities)")
        lines.append("=" * W)
        lines.append(f"  TP={agg_tp}  FP={agg_fp}  TN={agg_tn}  FN={agg_fn}")
        lines.append(f"  Micro-Precision : {_pct(mp)}")
        lines.append(f"  Micro-Recall    : {_pct(mr)}")
        lines.append(f"  Micro-F1        : {_pct(mf1)}")
        denom = agg_tp + agg_fp + agg_tn + agg_fn
        lines.append(f"  Micro-Accuracy  : {_pct(macc)}  [denominator = {denom}]")
        lines.append("")
        lines.append(f"  {'─'*61}")
        lines.append(f"  {'Vulnerability':<24} {'TP':>4} {'FP':>4} {'TN':>4} "
                     f"{'FN':>4}   {'P':>6} {'R':>6} {'F1':>6}")
        lines.append(f"  {'─'*61}")
        for vuln in active:
            m = all_metrics.get(vuln, {})
            label = VULN_LABELS.get(vuln, vuln.upper())
            lines.append(
                f"  {label:<24} {m.get('tp',0):>4} {m.get('fp',0):>4} "
                f"{m.get('tn',0):>4} {m.get('fn',0):>4}   "
                f"{_pct(m.get('precision')):>6} "
                f"{_pct(m.get('recall')):>6} "
                f"{_pct(m.get('f1')):>6}")
        lines.append(f"  {'─'*61}")
        lines.append(
            f"  {'MICRO-AVERAGE':<24} {agg_tp:>4} {agg_fp:>4} "
            f"{agg_tn:>4} {agg_fn:>4}   "
            f"{_pct(mp):>6} {_pct(mr):>6} {_pct(mf1):>6}")
        lines.append("")
    lines.append("=" * W)

    report = "\n".join(lines)
    print("\n" + report)

    # ── Save files ───────────────────────────────────────────────────────────
    summary_txt  = out_dir / f"ours_{dataset}_summary.txt"
    summary_json = out_dir / f"ours_{dataset}_summary_details.json"

    summary_txt.write_text(report + "\n")
    summary_json.write_text(json.dumps(all_metrics, indent=2) + "\n")

    print(f"\n  Summary TXT  → {summary_txt}")
    print(f"  Summary JSON → {summary_json}")


# ──────────────────────────────────────────────────────────────────────────────
# CSV WRITE
# ──────────────────────────────────────────────────────────────────────────────

CSV_FIELDS = [
    "filename", "reentrancy", "overflow", "timestamp", "tod",
    "duration_s", "exit_status", "solc_version", "raw_output_path",
]


def write_csv(csv_path, results, resume):
    existing = {}
    if resume and csv_path.exists():
        with open(csv_path, newline="") as f:
            for row in csv.DictReader(f):
                existing[row["filename"]] = row
    for r in results:
        existing[r["filename"]] = {k: r[k] for k in CSV_FIELDS}
    with open(csv_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        w.writeheader()
        for fn in sorted(existing):
            w.writerow(existing[fn])
    return existing


def count_statuses(csv_path):
    counts = {"ok": 0, "partial": 0, "timeout": 0, "error": 0, "skipped": 0}
    with open(csv_path, newline="") as f:
        for row in csv.DictReader(f):
            s = row.get("exit_status", "OK")
            if s == "OK":              counts["ok"] += 1
            elif "PARTIAL" in s:       counts["partial"] += 1
            elif "TIMEOUT" in s:       counts["timeout"] += 1
            elif "SKIPPED" in s:       counts["skipped"] += 1
            else:                      counts["error"] += 1
    return counts


# ──────────────────────────────────────────────────────────────────────────────
# MAIN
# ──────────────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(
        description="Batch runner for abstract-interpretation Solidity analysis",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""examples:
  %(prog)s sbc                               all vulns on SBC
  %(prog)s sbc --vulns tod                   only TOD on SBC
  %(prog)s sbc --vulns reentrancy,overflow   selected vulns on SBC
  %(prog)s qian_reentrancy --workers 4       parallel on Qian
  %(prog)s sbc --metrics-only                skip analysis, just compute metrics
  %(prog)s custom --input-dir path/ --output-dir results/
""",
    )
    ap.add_argument(
        "dataset",
        choices=list(DATASET_DEFAULTS.keys()) + ["custom"],
        help="Dataset name (or 'custom' with --input-dir/--output-dir)",
    )
    ap.add_argument(
        "--vulns", type=str, default=None,
        help="Comma-separated vulnerabilities to detect: "
             "reentrancy,overflow,timestamp,tod (default: all)",
    )
    ap.add_argument("--input-dir",     type=str, default=None)
    ap.add_argument("--output-dir",    type=str, default=None)
    ap.add_argument("--tool-dir",      type=str, default=None)
    ap.add_argument("--ground-truth",  type=str, default=None,
                    help="Path to ground truth JSON (auto-discovered if omitted)")
    ap.add_argument("--timeout",       type=int, default=120)
    ap.add_argument("--workers",       type=int, default=1)
    ap.add_argument("--resume",        action="store_true",
                    help="Skip contracts that already have output")
    ap.add_argument("--fresh",         action="store_true",
                    help="Delete all previous output before running")
    ap.add_argument("--metrics-only",  action="store_true",
                    help="Skip analysis, compute metrics from existing CSV")
    ap.add_argument("--no-metrics",    action="store_true",
                    help="Skip metrics computation after analysis")
    args = ap.parse_args()

    # ── Resolve paths ────────────────────────────────────────────────────────
    defaults   = DATASET_DEFAULTS.get(args.dataset, {})
    input_dir  = args.input_dir  or defaults.get("input_dir")
    output_dir = args.output_dir or defaults.get("output_dir")
    tool_dir   = args.tool_dir   or defaults.get("tool_dir", "src/")

    if not input_dir or not output_dir:
        ap.error(
            f"Dataset '{args.dataset}' requires --input-dir and --output-dir "
            f"(no defaults configured)."
        )

    # Resolve all paths against the REPO ROOT (not the current working dir), so
    # outputs always land in <repo>/results/ regardless of where this script is
    # launched from. (Running it from inside src/ previously created a stray
    # src/results/ copy.)
    REPO = Path(__file__).resolve().parent.parent
    input_dir  = str((REPO / input_dir).resolve())
    output_dir = str((REPO / output_dir).resolve())
    tool_dir   = str((REPO / tool_dir).resolve())

    # ── Parse --vulns ────────────────────────────────────────────────────────
    vulns = None
    if args.vulns:
        vulns = set(v.strip() for v in args.vulns.split(","))
        bad = vulns - set(ALL_VULNS)
        if bad:
            ap.error(f"Unknown vulnerability type(s): {bad}. "
                     f"Valid: {set(ALL_VULNS)}")
    elif defaults.get("default_vulns"):
        vulns = set(defaults["default_vulns"])

    csv_path = Path(output_dir) / f"ours_results_{args.dataset}.csv"

    # ── Metrics-only mode ────────────────────────────────────────────────────
    if args.metrics_only:
        if not csv_path.exists():
            sys.exit(f"[ERROR] CSV not found: {csv_path}\n"
                     f"  Run the analysis first: python3 run_ours.py "
                     f"{args.dataset}")
        gt_path = find_ground_truth(args.dataset, args.ground_truth)
        if gt_path is None:
            sys.exit(f"[ERROR] Ground truth not found for '{args.dataset}'.\n"
                     f"  Use --ground-truth path/to/file.json")
        Path(output_dir).mkdir(parents=True, exist_ok=True)
        status_counts = count_statuses(csv_path)
        run_metrics(gt_path, csv_path, output_dir, args.dataset, vulns,
                    batch_time=None,
                    total_files=sum(status_counts.values()),
                    status_counts=status_counts, input_dir=input_dir)
        return

    # ── Discover .sol files ──────────────────────────────────────────────────
    sol_files = sorted(Path(input_dir).rglob("*.sol"))
    if not sol_files:
        sys.exit(f"No .sol files found in {input_dir}")

    raw_dir = Path(output_dir) / "raw_output"
    raw_dir.mkdir(parents=True, exist_ok=True)

    if args.fresh:
        for item in raw_dir.glob("*"):
            (shutil.rmtree if item.is_dir() else item.unlink)(item)
        for f in Path(output_dir).glob("*.csv"):
            f.unlink()
        print(f"[FRESH] cleaned {output_dir}")
    elif not args.resume:
        stale = list(raw_dir.glob("*_verdicts.json"))
        if stale:
            for f in stale:
                f.unlink()
            print(f"[RERUN] deleted {len(stale)} stale _verdicts.json files")

    total_all = len(sol_files)
    if args.resume:
        done_stems = {f.stem for f in raw_dir.glob("*.txt")
                      if f.stat().st_size > 10}
        sol_files = [
            f for f in sol_files
            if csv_key(str(f), input_dir, args.dataset)
               .replace("/", "__").replace(".sol", "")
               not in done_stems
        ]

    total_rem = len(sol_files)
    vulns_str = ",".join(sorted(vulns)) if vulns else "all"

    print(f"\n{'='*82}")
    print(f"  DATASET  : {args.dataset}")
    print(f"  INPUT    : {input_dir}")
    print(f"  OUTPUT   : {output_dir}")
    print(f"  VULNS    : {vulns_str}")
    print(f"  FILES    : {total_rem} remaining of {total_all} total")
    print(f"  TIMEOUT  : {args.timeout}s   WORKERS: {args.workers}")
    print(f"  STARTED  : {datetime.now():%Y-%m-%d %H:%M:%S}")
    print(f"{'='*82}\n")

    if sol_files:
        print(f"  Key sample: "
              f"{csv_key(str(sol_files[0]), input_dir, args.dataset)}\n")

    def _run(idx_sf):
        idx, sf = idx_sf
        return analyze_one(
            str(sf), output_dir, tool_dir,
            args.timeout, input_dir, args.dataset,
            vulns=vulns,
            index=idx, total=total_rem,
        )

    indexed = list(enumerate(sol_files, 1))
    results = []
    t_batch = time.time()

    if args.workers <= 1:
        for item in indexed:
            results.append(_run(item))
    else:
        with ThreadPoolExecutor(max_workers=args.workers) as ex:
            futures = {ex.submit(_run, item): item for item in indexed}
            for fut in as_completed(futures):
                try:
                    results.append(fut.result())
                except Exception as e:
                    print(f"  [THREAD ERROR] {e}")

    # ── Write CSV ────────────────────────────────────────────────────────────
    existing = write_csv(csv_path, results, args.resume)
    elapsed = time.time() - t_batch

    ok  = sum(1 for r in results if r["exit_status"] == "OK")
    to  = sum(1 for r in results if "TIMEOUT" in r["exit_status"])
    err = len(results) - ok - to

    print(f"\n{'='*82}")
    print(f"  DONE  {elapsed:.0f}s  |  OK={ok}  TIMEOUT={to}  ERROR={err}")
    print(f"  CSV → {csv_path}   ({len(existing)} total rows)")
    print(f"{'='*82}")

    # ── Metrics ──────────────────────────────────────────────────────────────
    if not args.no_metrics:
        gt_path = find_ground_truth(args.dataset, args.ground_truth)
        if gt_path:
            print(f"\n  Ground truth: {gt_path}")
            status_counts = count_statuses(csv_path)
            run_metrics(gt_path, csv_path, output_dir, args.dataset, vulns,
                        batch_time=elapsed,
                        total_files=len(existing),
                        status_counts=status_counts, input_dir=input_dir)
        else:
            print(f"\n  [INFO] Ground truth not found for '{args.dataset}'.")
            print(f"         To see metrics, provide --ground-truth path.")
            print(f"         Or build one with: python3 build_ground_truth.py "
                  f"--dataset {args.dataset.split('_')[0]} "
                  f"--input-dir {input_dir} "
                  f"--output {args.dataset}_ground_truth.json\n")


if __name__ == "__main__":
    main()