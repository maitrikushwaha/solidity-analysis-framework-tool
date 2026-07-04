import numpy as np
import matplotlib.pyplot as plt
from matplotlib.colors import Normalize
from matplotlib.patches import Rectangle
from pathlib import Path

# Write figures into this repo's figure/ dir, regardless of the current working directory.
FIGDIR = Path(__file__).resolve().parent.parent / "figure"

USE_TEX = False

if USE_TEX:
    plt.rcParams.update({
        "text.usetex": True,
        "font.family": "serif",
        "font.serif": ["Times New Roman", "Times"],
    })
else:
    plt.rcParams.update({
        "font.family": "serif",
        "mathtext.fontset": "dejavuserif",
    })

tools = ["Ours", "Mythril", "Oyente+", "Slither", "Osiris",
         "SmartCheck", "Sailfish", "Vandal", "EtherSolve"]

col_labels = ["Reentrancy", "Overflow", "Timestamp", "TOD",
              "Reentrancy", "Overflow", "Timestamp",
              "Reentrancy", "TOD"]

groups = [("SBC", 0, 4), ("Qian", 4, 7), ("RSD", 7, 8), ("SolidiFI", 8, 9)]

nan = np.nan
data = np.array([
    [88, 55, 76, 35, 93, 95, 92, 85, 81],
    [59, 53, 86,  5, 44, 41, 37, 67, 59],
    [84, 20, 81, 10, 60, 65,  1, 60, 80],
    [67, nan, 76, nan, 91, nan, 55, 75, nan],
    [69, 30, 44, 12, 47, 66,  2, nan, nan],
    [50, nan, 13, nan, 51, nan,  2, 12, nan],
    [79, nan, nan,  6, 79, nan, nan, nan, 93],
    [40, nan, nan, nan, 46, nan, nan, 69, nan],
    [51, nan, nan, nan, 60, nan, nan,  0, nan],
], dtype=float)

nrows, ncols = data.shape
masked = np.ma.masked_invalid(data)

cmap = plt.cm.Blues.copy()
cmap.set_bad("#dadada")
norm = Normalize(vmin=0, vmax=100)

fig, ax = plt.subplots(figsize=(11, 6.6))
im = ax.imshow(masked, cmap=cmap, norm=norm, aspect="auto")

col_best = np.nanargmax(data, axis=0)

for i in range(nrows):
    for j in range(ncols):
        v = data[i, j]
        if np.isnan(v):
            ax.text(j, i, "--", ha="center", va="center",
                    color="#6f6f6f", fontsize=12)
            continue
        r, g, b, _ = cmap(norm(v))
        lum = 0.299 * r + 0.587 * g + 0.114 * b
        tcol = "white" if lum < 0.6 else "#1a1a1a"
        weight = "bold" if col_best[j] == i else "normal"
        ax.text(j, i, f"{int(round(v))}", ha="center", va="center",
                color=tcol, fontsize=12, fontweight=weight)

ax.set_xticks(np.arange(ncols))
ax.set_xticklabels(col_labels, fontsize=11)
ax.set_yticks(np.arange(nrows))
ax.set_yticklabels(tools, fontsize=12)
ax.get_yticklabels()[0].set_fontweight("bold")
ax.tick_params(length=0)

ax.set_xticks(np.arange(-0.5, ncols, 1), minor=True)
ax.set_yticks(np.arange(-0.5, nrows, 1), minor=True)
ax.grid(which="minor", color="white", linewidth=1.6)
ax.tick_params(which="minor", length=0)

for _, start, _end in groups[1:]:
    ax.axvline(start - 0.5, color="#2b2b2b", linewidth=2.4)
ax.axhline(0.5, color="#2b2b2b", linewidth=2.4)

for name, start, end in groups:
    ax.text((start + end - 1) / 2.0, -1.05, name, ha="center", va="center",
            fontsize=13, fontweight="bold")

ax.add_patch(Rectangle((-0.5, -0.5), ncols, nrows, fill=False,
                       edgecolor="#2b2b2b", linewidth=1.4))

ax.set_xlim(-0.5, ncols - 0.5)
ax.set_ylim(nrows - 0.5, -1.7)

cbar = fig.colorbar(im, ax=ax, fraction=0.025, pad=0.015)
cbar.set_label("F1 score (%)", fontsize=12)
cbar.ax.tick_params(labelsize=10)
cbar.outline.set_linewidth(0.6)

for spine in ax.spines.values():
    spine.set_visible(False)

fig.tight_layout()
fig.savefig(FIGDIR / "vuln_f1_heatmap.pdf", bbox_inches="tight", pad_inches=0.12)
fig.savefig(FIGDIR / "vuln_f1_heatmap.png", dpi=220, bbox_inches="tight", pad_inches=0.12)