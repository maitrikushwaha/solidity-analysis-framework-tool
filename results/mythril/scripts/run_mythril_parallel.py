#!/usr/bin/env python3
"""
run_mythril_parallel.py — Parallel Mythril batch runner (self-contained).

SWC mapping:
    107 → reentrancy | 101 → overflow | 116 → timestamp | 114 → tod

Usage:
    conda run -n mythril python3 run_mythril_parallel.py \
        --input-dir datasets/sbc/ --output-dir results/mythril/sbc/ \
        --dataset sbc --workers 2 --fresh

    conda run -n mythril python3 run_mythril_parallel.py \
        --input-dir datasets/sbc/ --output-dir results/mythril/sbc/ \
        --dataset sbc --workers 2 --resume
"""

import argparse
import csv
import json
import logging
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
# Inline solc version detection and installation (no solc_utils.py needed)
# ---------------------------------------------------------------------------

PATCH_MAP = {
    "0.4": "0.4.26",
    "0.5": "0.5.17",
    "0.6": "0.6.12",
    "0.7": "0.7.6",
    "0.8": "0.8.28",
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
    except subprocess.CalledProcessError as e:
        logging.warning(f"[solc-select] Failed to install {version}: "
                        f"{e.stderr.strip()}")
        major_minor = ".".join(version.split(".")[:2])
        fallback = PATCH_MAP.get(major_minor)
        if fallback and fallback != version:
            return ensure_solc_installed(fallback)
        with _cache_lock:
            _installed_cache[version] = False
        return False
    except Exception as e:
        logging.warning(f"[solc-select] Error installing {version}: {e}")
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
# Mythril analysis
# ---------------------------------------------------------------------------

SWC_MAP = {
    "107": "reentrancy",
    "101": "overflow",
    "116": "timestamp",
    "114": "tod",
}
TARGET_SWCS = set(SWC_MAP.keys())


def analyze_one(args_tuple: tuple) -> dict:
    """
    Worker function — must be module-level for multiprocessing pickling.
    """
    (filepath, output_dir, solc_override, execution_timeout,
     max_depth, tx_count, solver_timeout) = args_tuple

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

    version = prepare_solc(filepath, solc_override)
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
            ["pkill", "-f", f"myth analyze.*{Path(filepath).name}"],
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
            if any(
                k in log_txt
                for k in ["compilererror", "parsererror", "fatal error"]
            ):
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
    ap.add_argument("--solc-version", default="auto")
    ap.add_argument("--execution-timeout", type=int, default=300)
    ap.add_argument("--max-depth",  type=int, default=22)
    ap.add_argument("--transaction-count", type=int, default=3)
    ap.add_argument("--solver-timeout", type=int, default=10000)
    ap.add_argument("--workers", type=int, default=2,
                    help="Parallel Mythril processes. "
                         "Use 2 on a 16GB laptop, up to 4 on a 32GB machine.")
    ap.add_argument("--resume", action="store_true",
                    help="Skip contracts that already have a raw_json output.")
    ap.add_argument("--fresh", action="store_true",
                    help="Delete old results and start from scratch.")
    args = ap.parse_args()

    sol_files = sorted(Path(args.input_dir).rglob("*.sol"))
    if not sol_files:
        sys.exit(f"No .sol files found in {args.input_dir}")

    raw_dir = Path(args.output_dir) / "raw_json"
    raw_dir.mkdir(parents=True, exist_ok=True)

    if args.fresh:
        for item in raw_dir.glob("*"):
            if item.is_dir():
                shutil.rmtree(item)
            else:
                item.unlink()
        for csv_f in Path(args.output_dir).glob("*.csv"):
            csv_f.unlink()
        print(f"  [FRESH] Cleaned {args.output_dir}")

    total_all = len(sol_files)
    if args.resume:
        done = {
            f.stem + ".sol"
            for f in raw_dir.glob("*.json")
            if f.stat().st_size > 10
        }
        sol_files = [f for f in sol_files if f.name not in done]

    print(f"\n{'='*75}")
    print(f"  Mythril PARALLEL  {args.dataset.upper()}   "
          f"{datetime.now():%Y-%m-%d %H:%M:%S}")
    print(f"  Contracts : {len(sol_files)} remaining (of {total_all} total)")
    print(f"  Workers   : {args.workers}")
    print(f"  exec_timeout={args.execution_timeout}s  "
          f"max_depth={args.max_depth}  "
          f"tx={args.transaction_count}  "
          f"solver={args.solver_timeout}ms")
    worst = len(sol_files) * args.execution_timeout / args.workers / 3600
    print(f"  Worst-case estimate : ~{worst:.1f}h")
    print(f"{'='*75}\n")

    work_items = [
        (
            str(sf),
            args.output_dir,
            args.solc_version,
            args.execution_timeout,
            args.max_depth,
            args.transaction_count,
            args.solver_timeout,
        )
        for sf in sol_files
    ]

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
            eta = (len(sol_files) - completed) / (completed / elapsed) / 60
            print(
                f"[{completed:>4}/{len(sol_files)}] {r['filename']:<45} "
                f"solc={r['solc_version']:<8} {r['exit_status']:<18} "
                f"[{','.join(flags) or 'clean'}] {r['duration_s']}s  "
                f"ETA={eta:.0f}min"
            )

    csv_path = Path(args.output_dir) / f"mythril_results_{args.dataset}.csv"
    fields = [
        "filename", "reentrancy", "overflow", "timestamp", "tod",
        "duration_s", "exit_status", "solc_version",
        "swc_107_count", "swc_101_count", "swc_116_count", "swc_114_count",
        "raw_json_path",
    ]

    existing = {}
    if args.resume and csv_path.exists():
        with open(csv_path, newline="") as f:
            for row in csv.DictReader(f):
                existing[row["filename"]] = row
    for r in results:
        existing[r["filename"]] = {k: r[k] for k in fields}
    with open(csv_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for fn in sorted(existing):
            w.writerow(existing[fn])

    elapsed = time.time() - t0
    ok   = sum(1 for r in results if r["exit_status"] == "OK")
    to   = sum(1 for r in results if "TIMEOUT" in r["exit_status"])
    merr = sum(1 for r in results if "MYTHRIL_ERROR" in r["exit_status"])
    err  = len(results) - ok - to - merr

    print(f"\n{'='*75}")
    print(f"  DONE  {elapsed:.0f}s ({elapsed/3600:.1f}h)  "
          f"OK={ok}  TIMEOUT={to}  MYTHRIL_ERROR={merr}  OTHER={err}")
    print(f"  CSV → {csv_path}  ({len(existing)} total rows)")
    print(f"{'='*75}\n")


if __name__ == "__main__":
    main()