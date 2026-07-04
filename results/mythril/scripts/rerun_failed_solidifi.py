#!/usr/bin/env python3
"""
rerun_failed_solidifi.py — Rerun TIMEOUT contracts from SolidiFI with higher
                            timeout and lower depth. Saves JSON to same
                            raw_json location and updates CSV in place.

Usage:
    conda run -n mythril python3 rerun_failed_solidifi.py \
        --input-dir  datasets/SolidiFI/TOD/ \
        --output-dir results/mythril/solidifi/ \
        --dataset    solidifi \
        --workers    2
"""

import argparse
import csv
import json
import multiprocessing
import re
import shutil
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# Inline solc utilities
# ---------------------------------------------------------------------------

PATCH_MAP = {
    "0.4": "0.4.26", "0.5": "0.5.17", "0.6": "0.6.12",
    "0.7": "0.7.6",  "0.8": "0.8.28",
}
_installed_cache: dict = {}
_cache_lock = threading.Lock()


def ensure_solc_installed(version: str) -> bool:
    with _cache_lock:
        if version in _installed_cache:
            return _installed_cache[version]
    try:
        r = subprocess.run(["solc-select", "versions"],
                           capture_output=True, text=True, timeout=15)
        if version in r.stdout:
            with _cache_lock:
                _installed_cache[version] = True
            return True
    except Exception:
        pass
    try:
        subprocess.run(["solc-select", "install", version],
                       capture_output=True, text=True, timeout=120, check=True)
        with _cache_lock:
            _installed_cache[version] = True
        return True
    except Exception:
        with _cache_lock:
            _installed_cache[version] = False
        return False


def ensure_solcx_has_version(version: str) -> None:
    try:
        import solcx
        if version in [str(v) for v in solcx.get_installed_solc_versions()]:
            return
        try:
            solcx.install_solc(version, show_progress=False)
            return
        except Exception:
            pass
        ss_bin = (Path.home() / ".solc-select" / "artifacts"
                  / f"solc-{version}" / f"solc-{version}")
        if not ss_bin.exists():
            ss_bin = (Path.home() / ".solc-select" / "artifacts"
                      / version / f"solc-{version}")
        solcx_dir = Path(solcx.install.get_solcx_install_folder())
        solcx_bin = solcx_dir / f"solc-v{version}"
        if ss_bin.exists() and not solcx_bin.exists():
            solcx_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(ss_bin), str(solcx_bin))
            solcx_bin.chmod(0o755)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Worker
# ---------------------------------------------------------------------------

SWC_MAP = {
    "107": "reentrancy", "101": "overflow",
    "116": "timestamp",  "114": "tod",
}
TARGET_SWCS = set(SWC_MAP.keys())

FORCED_SOLC = "0.5.17"


def analyze_one(args_tuple: tuple) -> dict:
    (filepath, output_dir, execution_timeout,
     max_depth, tx_count, solver_timeout) = args_tuple

    fname    = Path(filepath).name
    stem     = fname.replace(".sol", "")
    # Save to same raw_json location as original run
    json_out = Path(output_dir) / "raw_json" / f"{stem}.json"
    log_out  = Path(output_dir) / "raw_json" / f"{stem}.log"
    json_out.parent.mkdir(parents=True, exist_ok=True)

    result = dict(
        filename=fname,
        reentrancy=0, overflow=0, timestamp=0, tod=0,
        duration_s=0, exit_status="OK", solc_version=FORCED_SOLC,
        swc_107_count=0, swc_101_count=0, swc_116_count=0, swc_114_count=0,
        raw_json_path=str(json_out),
    )

    ensure_solc_installed(FORCED_SOLC)
    ensure_solcx_has_version(FORCED_SOLC)

    cmd = [
        "myth", "analyze", str(filepath),
        "-o", "json",
        "-t", str(tx_count),
        "--max-depth", str(max_depth),
        "--execution-timeout", str(execution_timeout),
        "--solver-timeout", str(solver_timeout),
        "--solv", FORCED_SOLC,
        "--no-onchain-data",
    ]

    start = time.time()
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              timeout=execution_timeout + 60)
        json_out.write_text(proc.stdout or "")
        log_out.write_text(proc.stderr or "")
    except subprocess.TimeoutExpired:
        result["exit_status"] = "TIMEOUT"
        log_out.write_text("WALL CLOCK TIMEOUT\n")
        subprocess.run(["pkill", "-f", f"myth analyze.*{fname}"],
                       capture_output=True)
    except Exception as e:
        result["exit_status"] = f"ERROR:{e}"
        log_out.write_text(str(e))

    result["duration_s"] = round(time.time() - start, 2)

    if (result["exit_status"] == "OK"
            and json_out.exists() and json_out.stat().st_size > 0):
        try:
            data = json.loads(json_out.read_text())
            if isinstance(data, dict) and data.get("success") is False:
                result["exit_status"] = (
                    f"MYTHRIL_ERROR:{data.get('error','')[:100]}")
                return result
            issues = data.get("issues", []) if isinstance(data, dict) else []
            for issue in issues:
                swc = str(issue.get("swc-id", issue.get("swc_id", "")))
                if swc in TARGET_SWCS:
                    result[SWC_MAP[swc]] = 1
                    result[f"swc_{swc}_count"] += 1
        except json.JSONDecodeError:
            result["exit_status"] = "JSON_PARSE_ERROR"
        except Exception as e:
            result["exit_status"] = f"PARSE_ERROR:{e}"
        if result["exit_status"] == "OK":
            log_txt = log_out.read_text().lower() if log_out.exists() else ""
            if any(k in log_txt for k in
                   ["compilererror", "parsererror", "fatal error"]):
                result["exit_status"] = "COMPILE_ERROR"

    return result


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

FIELDS = [
    "filename", "reentrancy", "overflow", "timestamp", "tod",
    "duration_s", "exit_status", "solc_version",
    "swc_107_count", "swc_101_count", "swc_116_count", "swc_114_count",
    "raw_json_path",
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input-dir",  required=True)
    ap.add_argument("--output-dir", required=True)
    ap.add_argument("--dataset",    required=True)
    ap.add_argument("--execution-timeout", type=int, default=600)
    ap.add_argument("--max-depth",         type=int, default=16)
    ap.add_argument("--transaction-count", type=int, default=3)
    ap.add_argument("--solver-timeout",    type=int, default=30000)
    ap.add_argument("--workers",           type=int, default=2)
    args = ap.parse_args()

    csv_path = Path(args.output_dir) / f"mythril_results_{args.dataset}.csv"
    if not csv_path.exists():
        sys.exit(f"CSV not found: {csv_path}")

    # Read existing CSV
    existing = {}
    with open(csv_path, newline="") as f:
        for row in csv.DictReader(f):
            existing[row["filename"]] = row

    # Find all TIMEOUT rows
    timeout_files = [
        fname for fname, row in existing.items()
        if "TIMEOUT" in row["exit_status"]
    ]
    print(f"\n{'='*65}")
    print(f"  SolidiFI Timeout Rerun — {datetime.now():%Y-%m-%d %H:%M:%S}")
    print(f"  TIMEOUT contracts to rerun : {len(timeout_files)}")
    print(f"  Forced solc                : {FORCED_SOLC}")
    print(f"  exec_timeout={args.execution_timeout}s  "
          f"max_depth={args.max_depth}  tx={args.transaction_count}")
    worst = len(timeout_files) * args.execution_timeout / args.workers / 3600
    print(f"  Worst-case estimate        : ~{worst:.1f}h")
    print(f"{'='*65}\n")

    # Build filepath lookup
    sol_lookup = {sf.name: str(sf)
                  for sf in Path(args.input_dir).rglob("*.sol")}

    work_items = []
    for fname in sorted(timeout_files):
        fp = sol_lookup.get(fname)
        if fp is None:
            print(f"  [WARN] Not found: {fname}")
            continue
        work_items.append((
            fp, args.output_dir,
            args.execution_timeout, args.max_depth,
            args.transaction_count, args.solver_timeout,
        ))

    new_results = []
    completed = 0
    t0 = time.time()

    ctx = multiprocessing.get_context("fork")
    with ctx.Pool(processes=args.workers) as pool:
        for r in pool.imap_unordered(analyze_one, work_items):
            new_results.append(r)
            completed += 1
            flags = [
                v[:4].upper()
                for v in ["reentrancy", "overflow", "timestamp", "tod"]
                if r[v]
            ]
            elapsed = time.time() - t0
            eta = ((len(work_items) - completed) / (completed / elapsed) / 60
                   if completed > 0 else 0)
            print(
                f"[{completed:>3}/{len(work_items)}] {r['filename']:<35} "
                f"{r['exit_status']:<18} "
                f"[{','.join(flags) or 'clean'}] "
                f"{r['duration_s']}s  ETA={eta:.0f}min"
            )

    # Merge back into CSV
    for r in new_results:
        if r["filename"] in existing:
            existing[r["filename"]] = {k: r[k] for k in FIELDS}

    with open(csv_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        for fn in sorted(existing):
            w.writerow(existing[fn])

    elapsed = time.time() - t0
    ok      = sum(1 for r in new_results if r["exit_status"] == "OK")
    to      = sum(1 for r in new_results if "TIMEOUT" in r["exit_status"])
    err     = len(new_results) - ok - to

    tod_found = sum(1 for r in new_results if r["tod"] == 1)

    print(f"\n{'='*65}")
    print(f"  DONE  {elapsed:.0f}s ({elapsed/3600:.1f}h)")
    print(f"  OK={ok}  TIMEOUT={to}  ERROR={err}")
    print(f"  TOD detected in this rerun : {tod_found}")
    print(f"  CSV updated → {csv_path}")
    print(f"{'='*65}\n")


if __name__ == "__main__":
    main()