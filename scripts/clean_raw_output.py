#!/usr/bin/env python3
"""
clean_raw_output.py
===================
Prune the per-contract artifact clutter under results/ours/<dataset>/raw_output/.

For every analysed contract the tool currently emits SIX files:
    <base>_verdicts.json    (machine-readable verdicts)        KEEP
    <base>_analysis.txt     (full human-readable analysis)     KEEP
    <base>_output.txt       (console/log output)               KEEP
    <base>_transformed.sol  (instrumented source)              DROP
    <base>.txt              (bare scratch dump)                DROP
    <base>_verdicts.txt     (redundant with the .json)         DROP

This keeps exactly the three files requested for the GitHub artifact and removes
the three redundant/intermediate ones.

SAFE BY DEFAULT: dry-run. Prints what *would* be deleted and the space saved.
Pass --apply to actually delete. Pass --keep-verdicts-txt to retain
<base>_verdicts.txt (drop only _transformed.sol and the bare <base>.txt).

Usage:
    python3 scripts/clean_raw_output.py                 # dry run, all datasets
    python3 scripts/clean_raw_output.py --apply         # actually delete
    python3 scripts/clean_raw_output.py --root results/ours/sbc/raw_output
"""
import argparse
import os
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

# raw-output directories for each dataset (qian is split into 3 subsets)
DEFAULT_DIRS = [
    REPO / "results" / "ours" / "sbc" / "raw_output",
    REPO / "results" / "ours" / "rsd" / "raw_output",
    REPO / "results" / "ours" / "solidifi" / "raw_output",
    REPO / "results" / "ours" / "qian" / "qian_reentrancy" / "raw_output",
    REPO / "results" / "ours" / "qian" / "qian_overflow" / "raw_output",
    REPO / "results" / "ours" / "qian" / "qian_timestamp" / "raw_output",
]

KEEP_SUFFIXES = ("_verdicts.json", "_analysis.txt", "_output.txt")


def drop_suffixes(keep_verdicts_txt: bool):
    s = ["_transformed.sol"]
    if not keep_verdicts_txt:
        s.append("_verdicts.txt")
    return tuple(s)


def contract_bases(d: Path):
    """Derive contract base names from the authoritative *_verdicts.json files."""
    return sorted(p.name[: -len("_verdicts.json")]
                  for p in d.glob("*_verdicts.json"))


def plan_for_dir(d: Path, keep_verdicts_txt: bool):
    """Return (to_delete:[Path], kept:int) for one raw_output dir."""
    if not d.is_dir():
        return [], 0
    dsfx = drop_suffixes(keep_verdicts_txt)
    bases = contract_bases(d)
    to_delete = []
    for base in bases:
        for sfx in dsfx:
            f = d / f"{base}{sfx}"
            if f.exists():
                to_delete.append(f)
        # bare <base>.txt (only if it is NOT one of the keep/known files)
        bare = d / f"{base}.txt"
        if bare.exists():
            to_delete.append(bare)
    return to_delete, len(bases)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true",
                    help="actually delete (default: dry run)")
    ap.add_argument("--keep-verdicts-txt", action="store_true",
                    help="retain <base>_verdicts.txt (drop only _transformed.sol + bare .txt)")
    ap.add_argument("--root", default=None,
                    help="clean a single raw_output dir instead of all datasets")
    args = ap.parse_args()

    dirs = [Path(args.root).resolve()] if args.root else DEFAULT_DIRS

    grand_files = 0
    grand_bytes = 0
    grand_contracts = 0
    for d in dirs:
        to_delete, n_contracts = plan_for_dir(d, args.keep_verdicts_txt)
        if not d.is_dir():
            print(f"[skip] {d} (not found)")
            continue
        nbytes = sum(f.stat().st_size for f in to_delete)
        grand_files += len(to_delete)
        grand_bytes += nbytes
        grand_contracts += n_contracts
        print(f"[{'DEL' if args.apply else 'dry'}] {d}")
        print(f"        contracts={n_contracts}  drop_files={len(to_delete)}  "
              f"frees={nbytes/1024:.0f} KiB")
        if args.apply:
            for f in to_delete:
                try:
                    f.unlink()
                except OSError as e:
                    print(f"        WARN could not delete {f.name}: {e}")

    print("-" * 60)
    verb = "deleted" if args.apply else "would delete"
    print(f"TOTAL: {grand_contracts} contracts | {verb} {grand_files} files | "
          f"{grand_bytes/1024/1024:.1f} MiB")
    if not args.apply:
        print("(dry run — re-run with --apply to delete. Keeps "
              "_verdicts.json, _analysis.txt, _output.txt per contract.)")


if __name__ == "__main__":
    main()
