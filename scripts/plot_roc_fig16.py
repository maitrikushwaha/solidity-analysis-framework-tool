#!/usr/bin/env python3
"""
plot_roc_fig16.py
=================
Regenerate Figure 16 (ROC curves) from the canonical metric table
`tables/metrics_per_class.csv`. Each detector emits a single binary verdict per
contract, so every tool contributes one operating point (FPR, TPR); the ROC is
the polyline (0,0) -> (FPR, TPR) -> (1,1) and the reported AUC is the
single-operating-point value (TPR + (1 - FPR)) / 2 already stored in the table.

The extended evaluation spans four benchmarks with dataset-specific coverage:
  SBC      : reentrancy, overflow, timestamp, TOD
  Qian     : reentrancy, overflow, timestamp
  RSD      : reentrancy
  SolidiFI : TOD
giving nine panels. A tool absent for a (dataset, vulnerability) cell (no
detector / not run) is simply omitted from that panel.

Outputs (tables/):
  fig16_roc.pdf   vector, for \\includegraphics in the manuscript
  fig16_roc.png   raster preview
"""
import csv
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "tables" / "metrics_per_class.csv"
OUT = ROOT / "tables"
FIGDIR = ROOT / "figure"

# Tool order (Ours first). Default Matplotlib colours (Ours=blue, Mythril=orange,
# Oyente+=green, Slither=red, Osiris=purple, then brown/pink) and circular markers,
# matching the original Figure 16 style.
TOOLS = ["ours", "mythril", "oyente_plus", "slither", "osiris",
         "smartcheck", "sailfish", "vandal", "ethersolve"]
LABEL = {"ours": "Ours", "mythril": "Mythril", "oyente_plus": "Oyente+",
         "slither": "Slither", "osiris": "Osiris", "smartcheck": "SmartCheck",
         "sailfish": "Sailfish", "vandal": "Vandal", "ethersolve": "EtherSolve"}
# Ours is a bold BLACK curve; baselines use distinct tab10 colours.
COLOR = {"ours": "#000000", "mythril": "#d62728", "oyente_plus": "#ff7f0e",
         "slither": "#1f77b4", "osiris": "#2ca02c", "smartcheck": "#9467bd",
         "sailfish": "#8c564b", "vandal": "#17becf", "ethersolve": "#bcbd22"}

# Panel grid: (row, col, dataset, vulnerability, sub-label, title). Nine panels
# laid out 3x3 (row-major, reading order a..i); the four SBC classes lead, then
# the three Qian classes, then the single-vulnerability RSD and SolidiFI cells.
PANELS = [
    (0, 0, "sbc", "reentrancy", "a", "Reentrancy (SBC)"),
    (0, 1, "sbc", "overflow",   "b", "Overflow (SBC)"),
    (0, 2, "sbc", "timestamp",  "c", "Timestamp (SBC)"),
    (1, 0, "sbc", "tod",        "d", "TOD (SBC)"),
    (1, 1, "qian", "reentrancy", "e", "Reentrancy (Qian)"),
    (1, 2, "qian", "overflow",   "f", "Overflow (Qian)"),
    (2, 0, "qian", "timestamp",  "g", "Timestamp (Qian)"),
    (2, 1, "rsd", "reentrancy",  "h", "Reentrancy (RSD)"),
    (2, 2, "solidifi", "tod",    "i", "TOD (SolidiFI)"),
]
NROWS, NCOLS = 3, 3


def load():
    data = {}
    for r in csv.DictReader(open(SRC)):
        key = (r["dataset"], r["vulnerability"], r["tool"])
        try:
            fpr, tpr, auc = float(r["fpr"]), float(r["tpr"]), float(r["auc"])
        except (ValueError, TypeError):
            continue  # NA cell
        data[key] = (fpr, tpr, auc)
    return data


def main():
    data = load()
    # Serif look, matching the F1-heatmap figure for a consistent paper style.
    plt.rcParams.update({"font.size": 11, "axes.titlesize": 12,
                         "font.family": "serif", "mathtext.fontset": "dejavuserif"})
    # Canvas sized so the square (equal-aspect) 3x3 grid is width-limited and
    # fills the figure horizontally (otherwise square panels leave side margins).
    fig, axes = plt.subplots(NROWS, NCOLS, figsize=(9.2, 10.0),
                             constrained_layout=True)

    from matplotlib.lines import Line2D
    used = set()
    for (rr, cc, ds, vuln, tag, title) in PANELS:
        ax = axes[rr][cc]
        used.add((rr, cc))
        ax.plot([0, 1], [0, 1], ls="--", lw=1.1, color="0.55", zorder=1)  # chance line
        present = [(t,) + data[(ds, vuln, t)] for t in TOOLS if (ds, vuln, t) in data]
        order = sorted(present, key=lambda x: (-x[3], x[0] != "ours"))  # best AUC first
        # piecewise-linear ROC (0,0)->(FPR,TPR)->(1,1); baselines thin, Ours bold black on top
        for t, fpr, tpr, auc in order:
            if t == "ours":
                continue
            ax.plot([0, fpr, 1], [0, tpr, 1], color=COLOR[t], lw=1.5,
                    marker="o", markersize=5, markevery=[1], zorder=3)
        ofpr, otpr, _ = data[(ds, vuln, "ours")]
        ax.plot([0, ofpr, 1], [0, otpr, 1], color=COLOR["ours"], lw=3.0,
                marker="o", markersize=6, markevery=[1], zorder=6)
        # text-only AUC legend inside the panel, colour-coded, sorted, Ours bold
        labels = [f"{LABEL[t]}, AUC = {auc:.2f}" for (t, fpr, tpr, auc) in order]
        leg = ax.legend([Line2D([], [], color="none") for _ in order], labels,
                        loc="lower right", fontsize=8.5, frameon=False,
                        handlelength=0, handletextpad=0, labelspacing=0.28,
                        borderpad=0.2)
        for text, (t, *_ ) in zip(leg.get_texts(), order):
            text.set_color(COLOR[t])
            if t == "ours":
                text.set_fontweight("bold")
        ax.set_xlim(-0.02, 1.02)
        ax.set_ylim(-0.02, 1.02)
        ax.set_xticks([0, 0.2, 0.4, 0.6, 0.8, 1.0])
        ax.set_yticks([0, 0.2, 0.4, 0.6, 0.8, 1.0])
        ax.tick_params(labelsize=9)
        ax.set_title(f"({tag}) {title}")
        ax.set_aspect("equal", adjustable="box")
        for s in ax.spines.values():
            s.set_linewidth(0.8)
        if cc == 0:
            ax.set_ylabel("True Positive Rate", fontsize=11)
        if rr == 2:
            ax.set_xlabel("False Positive Rate", fontsize=11)

    for rr in range(NROWS):
        for cc in range(NCOLS):
            if (rr, cc) not in used:
                axes[rr][cc].axis("off")

    fig.savefig(FIGDIR / "fig16_roc.pdf")   # where the manuscript \includegraphics points
    fig.savefig(OUT / "fig16_roc.pdf")
    fig.savefig(OUT / "fig16_roc.png", dpi=220)
    print(f"[ok] wrote {FIGDIR/'fig16_roc.pdf'}, {OUT/'fig16_roc.pdf'} and {OUT/'fig16_roc.png'}")
    print("\nAUC by panel (single-operating-point):")
    hdr = ["dataset/vuln"] + [LABEL[t] for t in TOOLS]
    print("  " + " | ".join(f"{h:>10}" for h in hdr))
    for (_, _, ds, vuln, _, _) in PANELS:
        cells = []
        for t in TOOLS:
            v = data.get((ds, vuln, t))
            cells.append(f"{v[2]:.2f}" if v else "—")
        print(f"  {ds+'/'+vuln:>20} " + " | ".join(f"{c:>10}" for c in cells))


if __name__ == "__main__":
    main()
