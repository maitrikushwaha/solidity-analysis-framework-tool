#!/usr/bin/env python3
"""
rerun_failed_sbc.py — Targeted rerun for TIMEOUT and MYTHRIL_ERROR contracts.

Strategy:
    MYTHRIL_ERROR  → caused by solc < 0.4.11 (Mythril v0.24.8 incompatibility)
                     Fix: force --solv 0.4.26 (backward compatible)

    TIMEOUT        → contract too complex for 300s budget
                     Fix: raise execution-timeout to 600s, lower max-depth to 16

Reads the existing CSV, reruns only failed contracts, merges results back.

Usage:
    conda run -n mythril python3 rerun_failed_sbc.py \
        --input-dir datasets/sbc/ \
        --output-dir results/mythril/sbc/ \
        --dataset sbc \
        --workers 2
"""

import argparse
import csv
import json
import multiprocessing
import os
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


def detect_pragma_version(filepath: str):
    patterns = [
        re.compile(r'pragma\s+solidity\s+[^;]*?(\d+\.\d+\.\d+)'),
        re.compile(r'pragma\s+solidity\s+[\^~>=<\s]*(\d+\.\d+)'),
    ]
    try:
        with open(filepath, "r", errors="replace") as f:
            for line in f:
                line = line.split("//")[0]
                for pat in patterns:
                    m = pat.search(line)
                    if m:
                        raw = m.group(1)
                        if raw.count(".") == 1:
                            raw = PATCH_MAP.get(raw, raw + ".0")
                        return raw
    except Exception:
        pass
    return None


def resolve_version(filepath: str, override: str = "auto") -> str:
    if override and override != "auto":
        return override
    detected = detect_pragma_version(filepath)
    if detected:
        major_minor = ".".join(detected.split(".")[:2])
        if detected.count(".") == 1:
            detected = PATCH_MAP.get(major_minor, detected + ".0")
        return detected
    return "0.4.26"


def ensure_solc_installed(version: str) -> bool:
    with _cache_lock:
        if version in _installed_cache:
            return _installed_cache[version]
    try:
        result = subprocess.run(
            ["solc-select", "versions"],
            capture_output=True, text=True, timeout=15,
        )
        if version in result.stdout:
            with _cache_lock:
                _installed_cache[version] = True
            return True
    except Exception:
        pass
    try:
        subprocess.run(
            ["solc-select", "install", version],
            capture_output=True, text=True, timeout=120, check=True,
        )
        with _cache_lock:
            _installed_cache[version] = True
        return True
    except Exception:
        with _cache_lock:
            _installed_cache[version] = False
        return False


def prepare_solc(filepath: str, override: str = "auto") -> str:
    version = resolve_version(filepath, override)
    ok = ensure_solc_installed(version)
    if not ok:
        ensure_solc_installed("0.4.26")
        return "0.4.26"
    return version


def ensure_solcx_has_version(version: str) -> None:
    try:
        import solcx
        installed = [str(v) for v in solcx.get_installed_solc_versions()]
        if version in installed:
            return
        try:
            solcx.install_solc(version, show_progress=False)
            return
        except Exception:
            pass
        ss_bin = (
            Path.home() / ".solc-select" / "artifacts"
            / f"solc-{version}" / f"solc-{version}"
        )
        if not ss_bin.exists():
            ss_bin = (
                Path.home() / ".solc-select" / "artifacts"
                / version / f"solc-{version}"
            )
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

# Minimum solc version Mythril v0.24.8 can handle
MIN_SUPPORTED_SOLC = (0, 4, 11)


def _solc_too_old(version: str) -> bool:
    try:
        parts = tuple(int(x) for x in version.split(".")[:3])
        return parts < MIN_SUPPORTED_SOLC
    except Exception:
        return False


def analyze_one(args_tuple: tuple) -> dict:
    (filepath, output_dir, forced_solc,
     execution_timeout, max_depth, tx_count, solver_timeout) = args_tuple

    fname    = Path(filepath).name
    stem     = fname.replace(".sol", "")
    json_out = Path(output_dir) / "raw_json" / f"{stem}.json"
    log_out  = Path(output_dir) / "raw_json" / f"{stem}.log"
    json_out.parent.mkdir(parents=True, exist_ok=True)

    result = dict(
        filename=fname,
        reentrancy=0, overflow=0, timestamp=0, tod=0,
        duration_s=0, exit_status="OK", solc_version="?",
        swc_107_count=0, swc_101_count=0, swc_116_count=0, swc_114_count=0,
        raw_json_path=str(json_out),
    )

    # forced_solc="0.4.26" for old-pragma contracts, "auto" for timeouts
    version = prepare_solc(filepath, forced_solc)
    result["solc_version"] = version
    ensure_solcx_has_version(version)

    cmd = [
        "myth", "analyze", str(filepath),
        "-o", "json",
        "-t", str(tx_count),
        "--max-depth", str(max_depth),
        "--execution-timeout", str(execution_timeout),
        "--solver-timeout", str(solver_timeout),
        "--solv", version,
        "--no-onchain-data",
    ]

    start = time.time()
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True,
            timeout=execution_timeout + 60,
        )
        json_out.write_text(proc.stdout or "")
        log_out.write_text(proc.stderr or "")
    except subprocess.TimeoutExpired:
        result["exit_status"] = "TIMEOUT"
        log_out.write_text("WALL CLOCK TIMEOUT\n")
        subprocess.run(
            ["pkill", "-f", f"myth analyze.*{fname}"],
            capture_output=True,
        )
    except Exception as e:
        result["exit_status"] = f"ERROR:{e}"
        log_out.write_text(str(e))

    result["duration_s"] = round(time.time() - start, 2)

    if (
        result["exit_status"] == "OK"
        and json_out.exists()
        and json_out.stat().st_size > 0
    ):
        try:
            data = json.loads(json_out.read_text())
            if isinstance(data, dict) and data.get("success") is False:
                result["exit_status"] = (
                    f"MYTHRIL_ERROR:{data.get('error', '')[:100]}"
                )
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
            if any(k in log_txt for k in ["compilererror", "parsererror", "fatal error"]):
                result["exit_status"] = "COMPILE_ERROR"

    return result


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input-dir",  required=True)
    ap.add_argument("--output-dir", required=True)
    ap.add_argument("--dataset",    required=True)
    ap.add_argument("--workers", type=int, default=2)
    # Timeout rerun settings (lower depth to give more contracts a chance)
    ap.add_argument("--timeout-execution-timeout", type=int, default=600)
    ap.add_argument("--timeout-max-depth",         type=int, default=16)
    ap.add_argument("--timeout-tx-count",          type=int, default=3)
    ap.add_argument("--timeout-solver-timeout",    type=int, default=10000)
    args = ap.parse_args()

    csv_path = (
        Path(args.output_dir) / f"mythril_results_{args.dataset}.csv"
    )
    if not csv_path.exists():
        sys.exit(f"CSV not found: {csv_path}\nRun the main batch first.")

    # Read existing results
    existing: dict = {}
    with open(csv_path, newline="") as f:
        for row in csv.DictReader(f):
            existing[row["filename"]] = row

    # Build file lookup: filename → full path
    sol_lookup: dict = {}
    for sf in Path(args.input_dir).rglob("*.sol"):
        sol_lookup[sf.name] = str(sf)

    # Separate failed rows into two groups
    error_files   = []   # MYTHRIL_ERROR — use forced solc 0.4.26
    timeout_files = []   # TIMEOUT       — use higher timeout, lower depth

    for fname, row in existing.items():
        status = row["exit_status"]
        if "MYTHRIL_ERROR" in status:
            error_files.append(fname)
        elif "TIMEOUT" in status:
            timeout_files.append(fname)

    print(f"\n{'='*70}")
    print(f"  Rerun Failed Contracts — {args.dataset.upper()}   "
          f"{datetime.now():%Y-%m-%d %H:%M:%S}")
    print(f"  MYTHRIL_ERROR (old solc → force 0.4.26) : {len(error_files)}")
    print(f"  TIMEOUT (higher limit, lower depth)     : {len(timeout_files)}")
    print(f"  Workers                                 : {args.workers}")
    print(f"{'='*70}\n")

    work_items = []

    # Error files: force solc 0.4.26
    for fname in error_files:
        fp = sol_lookup.get(fname)
        if fp is None:
            print(f"  [WARN] File not found in input-dir: {fname}")
            continue
        work_items.append((
            fp, args.output_dir,
            "0.4.26",           # forced solc
            300,                # short timeout is fine — these fail fast
            22, 3, 10000,
        ))

    # Timeout files: auto solc but relaxed settings
    for fname in timeout_files:
        fp = sol_lookup.get(fname)
        if fp is None:
            print(f"  [WARN] File not found in input-dir: {fname}")
            continue
        work_items.append((
            fp, args.output_dir,
            "auto",
            args.timeout_execution_timeout,
            args.timeout_max_depth,
            args.timeout_tx_count,
            args.timeout_solver_timeout,
        ))

    if not work_items:
        print("  Nothing to rerun. All contracts already resolved.")
        return

    results = []
    completed = 0
    t0 = time.time()

    ctx = multiprocessing.get_context("fork")
    with ctx.Pool(processes=args.workers) as pool:
        for r in pool.imap_unordered(analyze_one, work_items):
            results.append(r)
            completed += 1
            flags = [
                v[:4].upper()
                for v in ["reentrancy", "overflow", "timestamp", "tod"]
                if r[v]
            ]
            elapsed = time.time() - t0
            eta = (
                (len(work_items) - completed) / (completed / elapsed) / 60
                if completed > 0 else 0
            )
            print(
                f"[{completed:>3}/{len(work_items)}] {r['filename']:<50} "
                f"solc={r['solc_version']:<8} {r['exit_status']:<18} "
                f"[{','.join(flags) or 'clean'}] {r['duration_s']}s  "
                f"ETA={eta:.0f}min"
            )

    # Merge back into existing CSV
    fields = [
        "filename", "reentrancy", "overflow", "timestamp", "tod",
        "duration_s", "exit_status", "solc_version",
        "swc_107_count", "swc_101_count", "swc_116_count", "swc_114_count",
        "raw_json_path",
    ]
    for r in results:
        existing[r["filename"]] = {k: r[k] for k in fields}

    with open(csv_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for fn in sorted(existing):
            w.writerow(existing[fn])

    elapsed = time.time() - t0
    ok      = sum(1 for r in results if r["exit_status"] == "OK")
    to      = sum(1 for r in results if "TIMEOUT" in r["exit_status"])
    merr    = sum(1 for r in results if "MYTHRIL_ERROR" in r["exit_status"])
    cerr    = sum(1 for r in results if "COMPILE_ERROR" in r["exit_status"])
    other   = len(results) - ok - to - merr - cerr

    print(f"\n{'='*70}")
    print(f"  RERUN DONE  {elapsed:.0f}s ({elapsed/3600:.1f}h)")
    print(f"  OK={ok}  TIMEOUT={to}  MYTHRIL_ERROR={merr}  "
          f"COMPILE_ERROR={cerr}  OTHER={other}")
    print(f"  CSV updated → {csv_path}  ({len(existing)} total rows)")
    print(f"\n  Remaining failures after rerun:")

    still_failed = {
        fn: row for fn, row in existing.items()
        if any(s in row["exit_status"]
               for s in ["TIMEOUT", "MYTHRIL_ERROR", "COMPILE_ERROR", "ERROR"])
    }
    for fn, row in sorted(still_failed.items()):
        print(f"    {fn:<50} {row['exit_status']}")
    print(f"{'='*70}\n")


if __name__ == "__main__":
    main()