#!/usr/bin/env python3
"""
make_paper_tables.py
====================
Emit the paper-facing Tables 4-7 (one per vulnerability) as styled LaTeX, read
straight from tables/metrics_per_class.csv. Reproduces the comparison_table look
(dark dataset header bar, gold 'Ours' row, bold-green best F1) natively in LaTeX,
now at full page width with the complete confusion-matrix columns.

Columns: Tool | TP FP TN FN | Analyzed Total Excl | P R F1 FDR FNR.
  Analyzed = TP+FP+TN+FN ; Total = benchmark size ; Excl = Total - Analyzed
  (contracts the tool could not analyse: compile error / timeout / crash).
Each table is wrapped in \\resizebox{\\textwidth}{!}{...} so it fills the column.

Preamble requirements (tell the user):
  \\usepackage[table]{xcolor}     % (replace plain \\usepackage{xcolor})
  \\usepackage{booktabs}
  \\usepackage{graphicx}          % for \\resizebox
Colour definitions are emitted once at the top of the output file.

Output: tables/tables_3_6.tex
"""
import csv
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "tables" / "metrics_per_class.csv"
OUT = ROOT / "tables" / "tables_3_6.tex"

TOOL_ORDER = ["ours", "mythril", "oyente_plus", "slither", "osiris",
              "smartcheck", "sailfish"]
TOOL_LABEL = {"ours": "Ours", "mythril": "Mythril", "oyente_plus": "Oyente+",
              "slither": "Slither", "osiris": "Osiris",
              "smartcheck": "SmartCheck", "sailfish": "Sailfish"}
DS_ORDER = ["sbc", "qian", "rsd", "solidifi"]
DS_TITLE = {"sbc": "SBC (SmartBugs Curated)", "qian": "Qian",
            "rsd": "RSD (Ressi et al.)", "solidifi": "SolidiFI"}
VULNS = [("reentrancy", "Reentrancy", "tab:reentrancy_combined"),
         ("overflow", "Integer Overflow/Underflow", "tab:arithmetic_combined"),
         ("timestamp", "Timestamp Dependency", "tab:timestamp_combined"),
         ("tod", "Transaction Ordering Dependency (TOD)", "tab:tod_combined")]

NCOL = 13  # Tool + 12 data columns


def pct(x):
    return "NA" if x == "NA" else f"{float(x) * 100:.1f}"


def main():
    rows = list(csv.DictReader(open(SRC)))
    idx = {(r["dataset"], r["vulnerability"], r["tool"]): r for r in rows}

    L = [
        "% ====================================================================",
        "% Tables 4-7 - per-vulnerability detection results (auto-generated).",
        "% Preamble: \\usepackage[table]{xcolor}, \\usepackage{booktabs},",
        "%           \\usepackage{graphicx}  (for \\resizebox).",
        "% ====================================================================",
        "\\definecolor{tblhead}{HTML}{2C3E50}   % dark dataset header bar",
        "\\definecolor{oursbg}{HTML}{FFF6E0}    % shaded 'Ours' row",
        "\\definecolor{ourstext}{HTML}{B8860B}  % 'Ours' label colour",
        "\\definecolor{bestf1}{HTML}{0A7D33}    % best F1 per block",
        "",
    ]

    head = ("\\textbf{Tool} & \\textbf{TP} & \\textbf{FP} & \\textbf{TN} & "
            "\\textbf{FN} & \\textbf{Analyzed} & \\textbf{Total} & \\textbf{Excl} & "
            "\\textbf{P} & \\textbf{R} & \\textbf{F1} & \\textbf{FDR} & \\textbf{FNR} \\\\")

    for vkey, vtitle, label in VULNS:
        ds_here = [ds for ds in DS_ORDER
                   if any((ds, vkey, t) in idx and idx[(ds, vkey, t)]["precision"] != "NA"
                          for t in TOOL_ORDER)]
        tools_here = [t for t in TOOL_ORDER
                      if any((ds, vkey, t) in idx and idx[(ds, vkey, t)]["precision"] != "NA"
                             for ds in ds_here)]
        L += [
            "\\begin{table}[t]",
            "\t\\centering",
            "\t\\setlength{\\tabcolsep}{5pt}",
            "\t\\renewcommand{\\arraystretch}{1.25}",
            f"\t\\caption{{{vtitle} detection results. Analyzed $=$ "
            "TP$+$FP$+$TN$+$FN; Total $=$ benchmark size; Excl $=$ contracts "
            "excluded as N/A (compile error / timeout); P, R, F1, FDR, FNR in \\%.}",
            f"\t\\label{{{label}}}",
            "\t\\resizebox{\\textwidth}{!}{%",
            "\t\\begin{tabular}{@{}lrrrrrrrrrrrr@{}}",
            "\t\t\\toprule",
            f"\t\t{head}",
        ]
        for ds in ds_here:
            f1s = [float(idx[(ds, vkey, t)]["f1"]) for t in tools_here
                   if (ds, vkey, t) in idx and idx[(ds, vkey, t)]["f1"] != "NA"]
            best = max(f1s) if f1s else None
            L.append("\t\t\\midrule")
            L.append(f"\t\t\\rowcolor{{tblhead}}\\multicolumn{{{NCOL}}}{{@{{}}l@{{}}}}"
                     f"{{\\textcolor{{white}}{{\\textbf{{{DS_TITLE[ds]}}}}}}} \\\\")
            for t in tools_here:
                r = idx.get((ds, vkey, t))
                is_ours = t == "ours"
                name = (f"\\textcolor{{ourstext}}{{\\textbf{{{TOOL_LABEL[t]}}}}}"
                        if is_ours else TOOL_LABEL[t])
                pre = "\\rowcolor{oursbg}" if is_ours else ""
                total = r["total"] if r is not None else ""
                if r is None or r["precision"] == "NA":
                    # NA row: only the benchmark Total is shown.
                    body = (f"NA & NA & NA & NA & NA & {total} & NA & "
                            "NA & NA & NA & NA & NA")
                else:
                    f1s_str = pct(r["f1"])
                    if best is not None and abs(float(r["f1"]) - best) < 1e-9:
                        f1s_str = f"\\textcolor{{bestf1}}{{\\textbf{{{f1s_str}}}}}"
                    # No positive predictions (complete miss): P and FDR are
                    # undefined (0/0) -> show as an em-dash, not a misleading 0.0.
                    no_pos = int(r["TP"]) + int(r["FP"]) == 0
                    p_str = "--" if no_pos else pct(r["precision"])
                    fdr_str = "--" if no_pos else pct(r["fdr"])
                    body = (f"{r['TP']} & {r['FP']} & {r['TN']} & {r['FN']} & "
                            f"{r['analyzed']} & {r['total']} & {r['excluded_na']} & "
                            f"{p_str} & {pct(r['recall'])} & {f1s_str} & "
                            f"{fdr_str} & {pct(r['fnr'])}")
                L.append(f"\t\t{pre}{name} & {body} \\\\")
        L += ["\t\t\\bottomrule", "\t\\end{tabular}}", "\\end{table}", ""]

    OUT.write_text("\n".join(L) + "\n")
    print(f"[ok] wrote {OUT}")
    print(f"tables: {[v[2] for v in VULNS]}")


if __name__ == "__main__":
    main()
