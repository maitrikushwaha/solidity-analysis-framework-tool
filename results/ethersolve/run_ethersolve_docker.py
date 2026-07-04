#!/usr/bin/env python3
# Timing + raw-capture for EtherSolve (Table 8 + reviewer raw evidence): re-run the
# pinned jar on frozen runtime bytecode, recording per-source wall-clock and saving
# the tool's re-entrancy findings per contract. Verdicts unchanged (deterministic).
import csv, glob, os, subprocess, tempfile, time

OUT = "/work/out"
BYTE = os.path.join(OUT, "bytecode")
JAR = os.environ.get("ETHERSOLVE_JAR", "/opt/ethersolve/EtherSolve.jar")

# map frozen-evm filename -> (dataset, source path) from results.csv
keymap = {}
for r in csv.DictReader(open(os.path.join(OUT, "results.csv"))):
    k = r["dataset"] + "__" + r["path"].replace("/", "_") + ".evm"
    keymap[k] = (r["dataset"], r["path"])


def run_one(bc_hex):
    d = tempfile.mkdtemp(prefix="es_")
    try:
        ev = os.path.join(d, "c.evm")
        open(ev, "w").write(bc_hex)
        subprocess.run(["java", "-jar", JAR, "-r", "-j", "-o",
                        os.path.join(d, "r.json"), "--re-entrancy", ev],
                       cwd=d, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        csvs = glob.glob(os.path.join(d, "*-re-entrancy.csv"))
        return open(csvs[0]).read() if csvs else "(no re-entrancy output / analyze fail)\n"
    finally:
        import shutil
        shutil.rmtree(d, ignore_errors=True)


def raw_path(dataset, path):
    rel = path
    pref = "datasets/%s/" % dataset
    if rel.startswith(pref):
        rel = rel[len(pref):]
    return os.path.join(OUT, "..", dataset, "raw", rel[:-4] + ".txt")


rows = []
for evm in sorted(glob.glob(os.path.join(BYTE, "*.evm"))):
    name = os.path.basename(evm)
    dataset, path = keymap.get(name, (name.split("__", 1)[0], name))
    t0 = time.time()
    findings = []
    for line in open(evm):
        parts = line.strip().split(" ", 1)
        if len(parts) == 2 and parts[1]:
            findings.append("# contract %s\n%s" % (parts[0], run_one(parts[1])))
    dur = round(time.time() - t0, 2)
    rp = os.path.abspath(raw_path(dataset, path))
    os.makedirs(os.path.dirname(rp), exist_ok=True)
    with open(rp, "w") as fh:
        fh.write("=== EtherSolve --re-entrancy findings (non-empty => reentrant) ===\n" + "\n".join(findings))
    rows.append([name, dataset, dur])
    print("[ethersolve] %s %.2fs" % (name, dur), flush=True)

with open(os.path.join(OUT, "ethersolve_timed.csv"), "w", newline="") as fh:
    w = csv.writer(fh)
    w.writerow(["evm_file", "dataset", "duration_s"])
    w.writerows(rows)
print("[done] ethersolve timing+raw: %d files" % len(rows), flush=True)
