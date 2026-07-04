#!/usr/bin/env python3
"""
build_ground_truth.py — Build ground truth JSON from folder structure.

Supports four datasets:

SBC (143 contracts, 4 vulnerabilities):
    datasets/sbc/reentrancy/        → reentrancy = 1
    datasets/sbc/arithmetic/        → overflow = 1
    datasets/sbc/time_manipulation/ → timestamp = 1
    datasets/sbc/front_running/     → tod = 1
    all other folders               → all 0

Qian (safe/vulnerable per vulnerability, no FRONTRUNNING):
    datasets/qian/REENTRANCY/{vulnerable,safe}/       → reentrancy
    datasets/qian/ARITHMETIC OVERFLOW UNDERFLOW/{v,s}/ → overflow
    datasets/qian/TIMESTAMP/{vulnerable,safe}/         → timestamp
    tod = 0 always

RSD (reentrancy only):
    datasets/rsd_contracts/reentrant/ → reentrancy = 1
    datasets/rsd_contracts/safe/      → reentrancy = 0

SolidiFI (TOD only):
    datasets/SolidiFI/TOD/vulnerable/ → tod = 1
    datasets/SolidiFI/TOD/safe/       → tod = 0
"""

import json, re
from pathlib import Path

SBC_FOLDER_MAP = {
    "reentrancy": "reentrancy", "arithmetic": "overflow",
    "time_manipulation": "timestamp", "front_running": "tod",
}
ANNOTATION_MAP = {
    "REENTRANCY": "reentrancy", "ARITHMETIC": "overflow",
    "TIME_MANIPULATION": "timestamp", "FRONT_RUNNING": "tod",
}
MANUAL_TIMESTAMP_POSITIVES = {
    "0x93c32845fae42c83a70e5f06214c8433665c2ab5.sol",
    "0xf015c35649c82f5467c9c74b7f28ee67665aad68.sol",
    "0xcead721ef5b11f1a7b530171aab69b16c5e66b6e.sol",
    "0xbe4041d55db380c5ae9d4a9b9703f1ed4e7e3888.sol",
    "0x96edbe868531bd23a6c05e9d0c424ea64fb1b78b.sol",
    "0x7b368c4e805c3870b6c49a3f1f49f69af8662cf3.sol",
    "0x7541b76cb60f4c60af330c208b0623b7f54bf615.sol",
    "timelock.sol", "list_dos.sol",
}

def scan_annotations(filepath):
    found = set()
    pat = re.compile(r'//\s*<yes>\s*<report>\s*(\w+)', re.IGNORECASE)
    try:
        for line in open(filepath, errors='replace'):
            m = pat.search(line)
            if m:
                vuln = ANNOTATION_MAP.get(m.group(1).upper())
                if vuln: found.add(vuln)
    except Exception: pass
    return found

def build_sbc(input_dir):
    gt, base = {}, Path(input_dir)
    file_map = {}
    for sol in base.rglob("*.sol"):
        fname = sol.name
        if fname not in file_map:
            file_map[fname] = sol
        else:
            if sol.parent.name.lower() in SBC_FOLDER_MAP and \
               file_map[fname].parent.name.lower() not in SBC_FOLDER_MAP:
                file_map[fname] = sol
    for fname, sol in sorted(file_map.items()):
        labels = {"reentrancy": 0, "overflow": 0, "timestamp": 0, "tod": 0}
        vuln = SBC_FOLDER_MAP.get(sol.parent.name.lower())
        if vuln: labels[vuln] = 1
        for v in scan_annotations(sol): labels[v] = 1
        if fname in MANUAL_TIMESTAMP_POSITIVES: labels["timestamp"] = 1
        gt[fname] = labels
    return gt

def folder_to_vuln_qian(folder_name):
    fn = folder_name.upper().replace(" ", "").replace("_", "").replace("-", "")
    if fn == "REENTRANCY": return "reentrancy"
    if "OVERFLOW" in fn or "UNDERFLOW" in fn or "ARITHMETIC" in fn: return "overflow"
    if fn == "TIMESTAMP": return "timestamp"
    if "FRONT" in fn or "RUNNING" in fn or "TOD" in fn: return "tod"
    return None

def build_qian(input_dir):
    """
    Qian has 201 filenames duplicated across vulnerability folders.
    Key format: "FOLDER/filename.sol" to preserve all 848 entries.
    Tool runners for Qian must use the same keying (see run_*.py --dataset qian).
    """
    gt, base = {}, Path(input_dir)
    for folder in sorted(base.iterdir()):
        if not folder.is_dir(): continue
        vuln = folder_to_vuln_qian(folder.name)
        if vuln is None:
            print(f"  [SKIP] unrecognised folder: {folder.name}")
            continue
        vuln_dir, safe_dir = folder / "vulnerable", folder / "safe"
        if vuln_dir.exists() or safe_dir.exists():
            vf = list(vuln_dir.rglob("*.sol")) if vuln_dir.exists() else []
            sf = list(safe_dir.rglob("*.sol")) if safe_dir.exists() else []
            print(f"  {folder.name:<45} → {vuln:<12} ({len(vf)} vuln + {len(sf)} safe)")
            for sol in sorted(vf):
                key = f"{folder.name}/{sol.name}"
                gt.setdefault(key, {"reentrancy":0,"overflow":0,"timestamp":0,"tod":0})
                gt[key][vuln] = 1
            for sol in sorted(sf):
                key = f"{folder.name}/{sol.name}"
                gt.setdefault(key, {"reentrancy":0,"overflow":0,"timestamp":0,"tod":0})
        else:
            sol_files = list(folder.glob("*.sol"))
            if not sol_files:
                src_dir = folder / "sourcecode"
                sol_files = list(src_dir.glob("*.sol")) if src_dir.exists() else []
            print(f"  {folder.name:<45} → {vuln:<12} ({len(sol_files)} contracts)")
            for sol in sorted(sol_files):
                key = f"{folder.name}/{sol.name}"
                gt.setdefault(key, {"reentrancy":0,"overflow":0,"timestamp":0,"tod":0})
                gt[key][vuln] = 1
    return gt

def build_rsd(input_dir):
    gt, base = {}, Path(input_dir)
    for sol in sorted((base/"reentrant").glob("*.sol")) if (base/"reentrant").exists() else []:
        gt[sol.name] = {"reentrancy":1,"overflow":0,"timestamp":0,"tod":0}
    for sol in sorted((base/"safe").glob("*.sol")) if (base/"safe").exists() else []:
        gt[sol.name] = {"reentrancy":0,"overflow":0,"timestamp":0,"tod":0}
    r = sum(1 for v in gt.values() if v["reentrancy"]==1)
    print(f"  reentrant/: {r}  safe/: {len(gt)-r}")
    return gt

def build_solidifi(input_dir):
    gt, base = {}, Path(input_dir)
    tod_dir = base/"TOD" if (base/"TOD").exists() else base
    for sol in sorted((tod_dir/"vulnerable").rglob("*.sol")) if (tod_dir/"vulnerable").exists() else []:
        gt[sol.name] = {"reentrancy":0,"overflow":0,"timestamp":0,"tod":1}
    for sol in sorted((tod_dir/"safe").rglob("*.sol")) if (tod_dir/"safe").exists() else []:
        gt[sol.name] = {"reentrancy":0,"overflow":0,"timestamp":0,"tod":0}
    v = sum(1 for x in gt.values() if x["tod"]==1)
    print(f"  vulnerable/: {v}  safe/: {len(gt)-v}")
    return gt

def print_summary(gt, name):
    total = len(gt)
    print(f"\n{name.upper()} ground truth: {total} total contracts")
    for v in ["reentrancy","overflow","timestamp","tod"]:
        pos = sum(1 for l in gt.values() if l[v]==1)
        print(f"  {v:<12}: {pos:>4} positive + {total-pos:>4} negative = {total}")

if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", required=True, choices=["sbc","qian","rsd","solidifi"])
    ap.add_argument("--input-dir", required=True)
    ap.add_argument("--output", required=True)
    args = ap.parse_args()
    print(f"Scanning {args.input_dir} ...")
    gt = {"sbc":build_sbc,"qian":build_qian,"rsd":build_rsd,"solidifi":build_solidifi}[args.dataset](args.input_dir)
    with open(args.output,'w') as f: json.dump(gt,f,indent=2,sort_keys=True)
    print_summary(gt, args.dataset)
    print(f"\nWritten to: {args.output}")
