#!/usr/bin/env python3
"""Sailfish batch runner - runs INSIDE holmessherlock/sailfish container over /work.
contractlint.py -p DAO,TOD ; DAO->reentrancy, TOD->tod. overflow/timestamp = no detector.
Per-contract solc chosen from the image's solc-binaries (0.4.x/0.5.x/0.6.x); RSD is
Solidity 0.8.x -> no compatible solc -> COMPILE_ERROR (NA), so RSD is not run here.
Emits per dataset: sailfish_results_<ds>.csv (verdicts+timing) and
sailfish_metrics_<ds>.json (per-vuln tp/fp/tn/fn filelists for the adapter)."""
import csv, json, os, re, subprocess, sys, time

WORK = "/work"
DATA = os.path.join(WORK, "datasets")
OUT = os.path.join(WORK, "out")
LINT = "/root/sailfish/code/static_analysis/analysis"
SOLC_DIR = "/root/solc-binaries/.solc-select/usr/bin"
PRAGMA = re.compile(r'pragma\s+solidity\s+[\^~>=<\s]*([0-9]+\.[0-9]+(?:\.[0-9]+)?)')
# preferred patch per minor, among those baked into the image
MINOR_PREF = {"0.4": ["0.4.26", "0.4.20", "0.4.18", "0.4.15", "0.4.9", "0.4.0"],
              "0.5": ["0.5.15", "0.5.11", "0.5.6", "0.5.5", "0.5.3"],
              "0.6": ["0.6.4", "0.6.1", "0.6.0"]}
TIMEOUT = 600


def sols(d):
    out = []
    for root, _, files in os.walk(d):
        for f in sorted(files):
            if f.endswith(".sol"):
                out.append(os.path.join(root, f))
    return sorted(out)


def solc_bin(ver):
    return os.path.join(SOLC_DIR, "solc-v" + ver)


def find_solc(sol):
    try:
        txt = open(sol, errors="ignore").read()
    except Exception:
        return None, None
    m = PRAGMA.search(txt)
    minor = ".".join(m.group(1).split(".")[:2]) if m else "0.4"
    cands = MINOR_PREF.get(minor, MINOR_PREF["0.4"])
    for ver in cands:
        b = solc_bin(ver)
        if not os.path.exists(b):
            continue
        try:
            p = subprocess.run([b, "--combined-json", "abi", sol],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=20)
            if p.returncode == 0:
                return ver, b
        except Exception:
            continue
    return None, None


def parse_dep(outdir, stem):
    dao = tod = False
    dj = os.path.join(outdir, stem, "dependency_info.json")
    try:
        data = json.load(open(dj))
        for deps in data.values():
            for e in deps:
                at = (e.get("attack_type") or "").upper()
                if at == "DAO":
                    dao = True
                elif at == "TOD":
                    tod = True
    except Exception:
        pass
    return dao, tod


def analyze(sol):
    stem = os.path.basename(sol)[:-4]
    ver, b = find_solc(sol)
    if ver is None:
        return None, "COMPILE_ERROR", "none", 0.0
    outdir = "/tmp/sf_" + stem
    os.makedirs(outdir, exist_ok=True)
    t0 = time.time()
    try:
        subprocess.run(["python3", "contractlint.py", "-c", sol, "-o", outdir,
                        "-r", "none", "-p", "DAO,TOD", "-oo", "-sv", "cvc4", "-sc", b],
                       cwd=LINT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=TIMEOUT)
    except subprocess.TimeoutExpired:
        return None, "TIMEOUT", ver, round(time.time() - t0, 2)
    except Exception:
        return None, "ERROR", ver, round(time.time() - t0, 2)
    dur = round(time.time() - t0, 2)
    dao, tod = parse_dep(outdir, stem)
    return {"reentrancy": 1 if dao else 0, "tod": 1 if tod else 0}, "OK", ver, dur


def classify(cls, vuln, name, flag, g):
    cls.setdefault(vuln, {"tp_files": [], "fp_files": [], "tn_files": [], "fn_files": []})
    k = ("tp_files" if flag and g else "fp_files" if flag else "fn_files" if g else "tn_files")
    cls[vuln][k].append(name)


def finalize(cls):
    out = {}
    for v, d in cls.items():
        e = dict(d)
        e.update(tp=len(d["tp_files"]), fp=len(d["fp_files"]),
                 tn=len(d["tn_files"]), fn=len(d["fn_files"]))
        out[v] = e
    return out


def run(ds, root_sub, vulns):
    gt = json.load(open(os.path.join(WORK, ds + "_ground_truth.json")))
    od = os.path.join(OUT, ds)
    os.makedirs(od, exist_ok=True)
    cls = {}
    rows = []
    for sol in sols(os.path.join(DATA, ds, root_sub) if root_sub else os.path.join(DATA, ds)):
        name = os.path.basename(sol)
        # qian GT is keyed by "<category>/<basename>"; others by basename
        gtkey = "{}/{}".format(root_sub, name) if ds == "qian" else name
        if gtkey not in gt:
            continue
        gg = gt[gtkey]
        flags, st, ver, dur = analyze(sol)
        if flags is None:
            rows.append([name, 0, -1, -1, 0, dur, st, ver, ""])
            print("[{}] {} {} {}s".format(ds, name, st, dur), flush=True)
            continue
        rows.append([name, flags["reentrancy"], -1, -1, flags["tod"], dur, "OK", ver, ""])
        for v in vulns:
            classify(cls, v, name, flags[v], int(gg.get(v, 0)))
        print("[{}] {} re={} tod={} {}s".format(ds, name, flags["reentrancy"], flags["tod"], dur), flush=True)
    with open(os.path.join(od, "sailfish_results_{}.csv".format(ds)), "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["filename", "reentrancy", "overflow", "timestamp", "tod",
                    "duration_s", "exit_status", "solc_version", "raw_json_path"])
        w.writerows(rows)
    json.dump(finalize(cls), open(os.path.join(od, "sailfish_metrics_{}.json".format(ds)), "w"),
              indent=2, sort_keys=True)


if __name__ == "__main__":
    which = sys.argv[1] if len(sys.argv) > 1 else "all"
    if which in ("sbc", "all"):
        run("sbc", "", ["reentrancy", "tod"])
    if which in ("qian", "all"):
        run("qian", "reentrancy", ["reentrancy"])
    if which in ("solidifi", "all"):
        run("solidifi", "tod", ["tod"])
    print("[done] sailfish " + which, flush=True)
