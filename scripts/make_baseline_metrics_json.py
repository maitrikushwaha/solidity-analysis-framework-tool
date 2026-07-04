#!/usr/bin/env python3
"""Generate oyente_plus-style metrics_<ds>.json for every baseline, from the
consolidated predictions.csv + ground truth. One file per (tool, dataset) at
results/<tool>/<ds>/metrics_<ds>.json with: per_vulnerability {counts, files},
macro_average, micro_average, failed_contracts (excluded/N-A), summary, tool."""
import csv, json, os
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RES = ROOT / "results"
PRED = RES / "standardized" / "predictions.csv"
BASELINES = ["slither", "osiris", "smartcheck", "sailfish", "vandal", "ethersolve", "mythril"]
DS_VULNS = {"rsd": ["reentrancy"], "sbc": ["reentrancy", "overflow", "timestamp", "tod"],
            "qian": ["reentrancy", "overflow", "timestamp"], "solidifi": ["tod"]}
QIAN_CAT = {"reentrancy": "reentrancy", "overflow": "overflow", "timestamp": "timestamp"}


def gt_universe(ds, vuln):
    gt = json.load(open(ROOT / ("%s_ground_truth.json" % ds)))
    out = {}
    if ds == "qian":
        pref = QIAN_CAT[vuln] + "/"
        for k, v in gt.items():
            if k.startswith(pref):
                out[os.path.basename(k)] = int(v.get(vuln, 0))
    else:
        for k, v in gt.items():
            out[os.path.basename(k)] = int(v.get(vuln, 0))
    return out


def rate(n, d):
    return round(n / d, 4) if d else 0.0


def main():
    rows = list(csv.DictReader(open(PRED)))
    by = defaultdict(list)
    for r in rows:
        by[(r["tool"], r["dataset"], r["vulnerability"])].append(r)

    for tool in BASELINES:
        for ds, vulns in DS_VULNS.items():
            per = {}
            present = False
            excluded_total = 0
            for vuln in vulns:
                recs = by.get((tool, ds, vuln))
                if not recs:
                    continue
                present = True
                counts = {"tp": 0, "fp": 0, "tn": 0, "fn": 0}
                fp_files, fn_files, analyzed = [], [], set()
                for r in recs:
                    oc = r["outcome"].lower()
                    if oc in counts:
                        counts[oc] += 1
                        analyzed.add(os.path.basename(r["contract"]))
                        if oc == "fp":
                            fp_files.append(os.path.basename(r["contract"]))
                        elif oc == "fn":
                            fn_files.append(os.path.basename(r["contract"]))
                tp, fp, tn, fn = counts["tp"], counts["fp"], counts["tn"], counts["fn"]
                evaluated = tp + fp + tn + fn
                uni = gt_universe(ds, vuln)  # {basename: gt}
                total = len(uni)
                # excluded/N-A = universe contracts with no usable verdict (compile error / timeout)
                excluded_files = sorted(set(uni) - analyzed)
                excluded_total += len(excluded_files)
                # Keep FP/FN (audit-useful) + the (small) excluded list so counts reconcile.
                per[vuln] = {
                    "counts": counts,
                    "precision": rate(tp, tp + fp), "recall": rate(tp, tp + fn),
                    "f1": rate(2 * tp, 2 * tp + fp + fn),
                    "accuracy": rate(tp + tn, tp + fp + tn + fn),
                    "evaluated": evaluated, "total": total, "excluded_na": len(excluded_files),
                    "fp_files": sorted(fp_files), "fn_files": sorted(fn_files),
                    "excluded_na_files": excluded_files,
                }
            if not present:
                continue
            # micro (pooled) + macro (mean of per-vuln)
            mtp = sum(per[v]["counts"]["tp"] for v in per)
            mfp = sum(per[v]["counts"]["fp"] for v in per)
            mtn = sum(per[v]["counts"]["tn"] for v in per)
            mfn = sum(per[v]["counts"]["fn"] for v in per)
            micro = {"counts": {"tp": mtp, "fp": mfp, "tn": mtn, "fn": mfn},
                     "metrics": {"precision": rate(mtp, mtp + mfp), "recall": rate(mtp, mtp + mfn),
                                 "f1": rate(2 * mtp, 2 * mtp + mfp + mfn),
                                 "accuracy": rate(mtp + mtn, mtp + mfp + mtn + mfn)}}
            macro = {m: round(sum(per[v][m] for v in per) / len(per), 4)
                     for m in ("precision", "recall", "f1", "accuracy")}
            out = {"tool": tool, "dataset": ds,
                   "macro_average": macro, "micro_average": micro,
                   "per_vulnerability": per,
                   "summary": {"total_contracts": max(per[v]["total"] for v in per),
                               "excluded_na_total": excluded_total}}
            d = RES / tool / ds
            d.mkdir(parents=True, exist_ok=True)
            json.dump(out, open(d / ("metrics_%s.json" % ds), "w"), indent=2, sort_keys=True)
            print("[ok] %s/%s/metrics_%s.json (%d vulns)" % (tool, ds, ds, len(per)))


if __name__ == "__main__":
    main()
