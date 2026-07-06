# A Sound Semantics Approximation of Solidity for Enhanced Vulnerability Detection

Our tool is a **semantics-aware smart-contract vulnerability detection (SCVD)
framework** that extends the theory of **Abstract Interpretation** to Solidity.
It provides a unifying framework for computing sound over-approximations of a
contract's dynamic behaviour at different levels of abstraction. By formally
modelling both concrete and abstract semantics over several numerical domains,
namely **Interval (Box)**, **Octagon**, and **Polyhedra (Polka)**, it detects
**reentrancy**, **integer overflow/underflow**, **timestamp dependence**, and
**transaction-ordering dependence (TOD)**, capturing semantic dependencies that
symbolic or rule-based tools often miss.

This repository is the **replication package** for the accompanying paper. It
contains the analyzer, the scripts that reproduce every reported number, the four
benchmark datasets, and the complete results comparing our tool against eight
state-of-the-art baselines (Mythril, Oyente+, Slither, Osiris, SmartCheck,
Sailfish, Vandal, and EtherSolve).

---

## Contents

- [Highlights](#highlights)
- [Approach](#approach)
- [Architecture](#architecture)
- [Repository layout](#repository-layout)
- [Installation](#installation)
- [Quick start — analyzing one contract](#quick-start--analyzing-one-contract)
- [Reproducing the evaluation](#reproducing-the-evaluation)
- [Datasets](#datasets)
- [Results and metrics](#results-and-metrics)
- [Output files of a run](#output-files-of-a-run)
- [Citation](#citation)
- [License](#license)

---

## Highlights

- **Four vulnerability classes** in one pass: reentrancy, integer
  overflow/underflow, timestamp dependence, and TOD.
- **Multiple numerical domains.** Interval gives the fast non-relational view;
  Octagon and Polyhedra add *relational* invariants (relationships *between*
  variables, e.g. `balance ≥ credit`) that an interval cannot express, which is
  what makes the feasibility check precise.
- **Per-contract compiler selection.** Each contract is compiled with the exact
  `solc` version from its `pragma` (0.4.x through 0.8.x), so legacy and modern
  contracts are handled by the same pipeline.
- **A fully reproducible study.** One command per stage regenerates the metric tables, the per-domain timing table, and the cross-tool comparison reported in the paper.

---

## Approach

The analyzer treats each contract as a program over integer-valued state and
runs a classic abstract-interpretation fixpoint on its control-flow graph. The
novelty is twofold:

1. **Semantic preprocessing for solidity-specific constructs.** Complex Solidity
   constructs — mappings, structs, balance transfers, and low-level external
   calls — are normalized into an equivalent *scalar* form that the numerical
   domains can reason about, while keeping the
   abstraction a sound over-approximation of the original behaviour. For
   reentrancy, this step injects explicit balance/credit variables and the
   call-back edge that models a re-entrant invocation.
2. **Multi-domain feasibility confirmation.** A vulnerability is first detected semantically, then *confirmed* by checking whether the abstract
   state at the suspect program point actually admits the dangerous condition. A
   non-relational domain (Interval) is enough to flag, but a relational domain
   (Octagon / Polyhedra) is often needed to *prove infeasibility* and safely
   drop a spurious warning.

Each vulnerability class runs as an **isolated pipeline** — it builds its own
abstract state, runs its own fixpoint, and emits its own verdict, with no shared
mutable state crossing pipeline boundaries:

| Pipeline                       | Domain(s)           | Verdict criterion                                                              |
| ------------------------------ | ------------------- | ------------------------------------------------------------------------------ |
| **Reentrancy**           | Box, Octagon, Polka | Δ-width mismatch on`{BAL, attacker_bal, credit}` across the re-entrant edge |
| **Overflow / underflow** | Box                 | computed interval`[lo, hi]` vs the declared type range                       |
| **Timestamp dependence** | Polyhedra (Polka)   | control/data influence of`block.timestamp` on a sensitive sink               |
| **TOD**                  | Polyhedra (Polka)   | order-dependent state/transfer flagged by the dependency engine                |

---

## Architecture

```
   Smart Contract  (.sol)
        │
        ▼
   [1] AST Extraction
        SolcSelector → SolCompiler → AST Builder (ast.json)
        │
        ▼
   [2] CFG Generation & Augmentation
        Node Processor · CFG Metadata · Graph Builder
        Semantic CFG → Augmented CFG (fallback re-entry edges)
        │
        ▼
   [3] Fixpoint Abstract Semantics Engine
        APRON Domain Manager: Interval · Octagon · Polyhedra (via JPype)
        Transfer-Function Engine · Fixpoint Computation (join / widening)
        │
        ▼
   [4] Dependency Analysis Engine
        Syntactic Dependency Analyzer: intra/inter-data + control deps
        Semantic Refinement Engine: feasible-path check · abstract-state filter
        │
        ▼
   [5] Semantics Vulnerability Detection
        Reentrancy (balance-invariant) · Integer Overflow/Underflow (interval-bound)
        Timestamp (timestamp-gated control) · TOD (ordering-sensitive state)
```

### Modules inside `src/`

| Module                                                  | Responsibility                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                         |
| ------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| [`compiler/`](src/compiler/)                           | Front-end.`SolCompiler` extracts the `pragma`, and `SolcSelector` installs/selects the matching `solc` (every release from 0.4.11 to 0.8.28 is supported) via `py-solc-x`; `CompiledOutputGenerator` produces the AST consumed downstream.                                                                                                                                                                                                                                                                                                                                                                                                                                                                 |
| [`mapping_transformer.py`](src/mapping_transformer.py) | Front-end semantic normalization — a **preprocessing prerequisite**, not a detector. Complex Solidity constructs (mappings and structs → scalar proxies; balance transfers and low-level calls → explicit conditional logic) are rewritten into an equivalent scalar form so the numerical domains can reason about them; for reentrancy it additionally injects the balance/credit variables and the re-entrant back-edge. The rewrite is a **sound over-approximation**: it only ever adds behaviour rather than removing feasible paths, which helps avoid introducing false negatives. |
| [`control_flow_graph/`](src/control_flow_graph/)       | `ControlFlowGraph` builds an augmented CFG recursively from the AST. There is one *node processor* per AST construct (`IfStatement`, `ForStatement`, `WhileStatement`, `FunctionDefinition`, `Assignment`, `FunctionCall`, …) under `node_processor/nodes/`, plus explicit entry/exit nodes.                                                                                                                                                                                                                                                                                                                                                                                                       |
| [`static_analysis/`](src/static_analysis/)             | The abstract interpreter.`abstract_collecting_semantics/` runs the iterative **fixpoint with widening** over a chosen APRON domain (`Box`, `Octagon`, or `Polka`), tracking a per-program-point abstract state (`PointState`, `VariableRegistry`). `collecting_semantics/` provides the concrete reference semantics, and `dataflow_analysis/` supplies the reaching-definition / available-expression machinery used by dependency analysis.                                                                                                                                                                                                                                                    |
| [`dependency_analysis.py`](src/dependency_analysis.py) | `DependencyAnalysisEngine` computes flow- and context-sensitive data and control dependencies over the CFG and uses them to detect timestamp dependence and TOD. `SemanticRefinementEngine` performs the feasibility refinement that backs sound false-positive suppression.                                                                                                                                                                                                                                                                                                                                                                                                                                       |
| [`java_wrapper/`](src/java_wrapper/)                   | Thin bridge to **APRON**. Starts the JVM via **JPype**, loads `apron.jar` / `gmp.jar` from `$APRON_HOME`, and exposes the `Box`, `Octagon`, and `Polka` managers (and the APRON expression API) to Python.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    |
| [`utils/`](src/utils/)                                 | Shared expression helpers.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                             |
| [`main.py`](src/main.py)                               | Orchestrator. Compiles, transforms, builds the CFG(s), runs the four pipelines, and writes the verdicts. The module docstring documents exactly which source, CFG, and domain each pipeline uses.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                      |

---

## Repository layout

```
src/                     the analyzer (entry point: src/main.py)
scripts/                 evaluation and aggregation pipeline (see below)
datasets/                benchmarks: sbc/, qian/, rsd/, solidifi/
results/                 per-tool raw outputs + normalized predictions
  ├─ ours/                     our tool's raw outputs (+ examples/ = worked verdicts on the figure contracts)
  ├─ mythril/  oyente_plus/  slither/  osiris/            one directory per baseline tool;
  │  smartcheck/  sailfish/  vandal/  ethersolve/         each has a REPRODUCIBILITY.md + examples/
  └─ standardized/             one self-describing row per (tool, dataset, contract, vulnerability)
tables/                  result tables reported in the paper (regenerated from results/)
  ├─ metrics_per_class.csv     canonical metric table (Tables 4–7, Figs 15–16)
  ├─ comparison_metrics.csv    the same metrics in long (one-row-per-cell) form
  ├─ comparison_table.pdf      human-readable cross-tool comparison
  └─ table8_timing_median.csv  Table 8 — median per-contract detection time
figure/                  paper figures: fig16_roc.pdf (Fig 16 ROC), vuln_f1_heatmap.pdf (Fig 15 F1)
case_studies/            worked examples behind Figs 1–2 and §7.2 case studies (per-tool FP/FN outputs)
environment.yml          conda environment specification
```

A detailed data dictionary for everything under `results/` (column meanings,
prediction encoding, ground-truth format, provenance of each baseline's numbers)
is in [`results/README.md`](results/README.md).

---

## Installation

The analyzer needs three things: a Python environment, a Java runtime with the
APRON numerical-domain library, and the Solidity compiler versions used by the
benchmarks.

### 0. Get the code

```bash
git clone https://github.com/maitrikushwaha/solidity-analysis-framework-tool.git
cd solidity-analysis-framework-tool
```

### 1. Python environment (conda)

If you do not already have conda, install
[Miniconda](https://docs.conda.io/en/latest/miniconda.html), then create the
environment:

```bash
conda env create -f environment.yml
conda activate safpy
```

This installs the Python dependencies, including `py-solc-x` (compiler
management), `JPype1` (the Java bridge), and the `graphviz` Python bindings.

### 2. Java + APRON

Install a JRE/JDK (11+) and the
[APRON numerical abstract domain library](https://antoinemine.github.io/Apron/doc/)
together with its Java (JNI) bindings. APRON is built from source
([github.com/antoinemine/apron](https://github.com/antoinemine/apron)); its
`japron` bindings require a JDK plus the GMP and MPFR development libraries
(`sudo apt-get install libgmp-dev libmpfr-dev` on Debian/Ubuntu). After building
`japron`, you should have, in one directory:

```
apron.jar   gmp.jar   libjapron.so   libjgmp.so
```

Point the analyzer at that directory with the **`APRON_HOME`** environment
variable (default if unset: `~/apron/japron`):

```bash
export APRON_HOME=/path/to/japron
```

No source edits are required — the JVM classpath and `java.library.path` are
derived from `APRON_HOME` at runtime.

> **System Graphviz (optional).** The CFG can be rendered to an image with
> Graphviz. Importing the analyzer only needs the `graphviz` *Python* package
> (already in `environment.yml`); to actually render a `.png`/`.pdf` you also
> need the Graphviz system binaries (`sudo apt-get install graphviz` on
> Debian/Ubuntu). Detection itself does not require rendering.

### 3. Solidity compilers (solc-select / solc-x)

The benchmark contracts span Solidity 0.4.x–0.8.x. `py-solc-x` downloads and
caches the required compiler automatically on first use; each contract is then
compiled with the version named in its own `pragma`. No manual version pinning
is needed.

> If you run inside a Python virtual environment, note that `solc-select`
> resolves its home from `VIRTUAL_ENV` when that variable is set; unset it (or
> point it at a writable location) if compiler selection fails.

### 4. Verify the installation

Run the analyzer on one of the bundled example contracts and confirm you get a
verdict summary:

```bash
python src/main.py results/ours/examples/overflow.sol \
    --pipelines reentrancy,overflow,timestamp,tod
```

Expected tail of the output:

```
[SUMMARY] Integer Overflow: VULNERABLE
```

The three contracts under `results/ours/examples/` (with their expected verdicts
explained in that folder's `README.md`) form a quick end-to-end smoke test that
exercises compilation, the APRON bridge, and all four pipelines.

---

## Quick start — analyzing one contract

```bash
python src/main.py path/to/contract.sol --json --output-dir out \
    --pipelines reentrancy,overflow,timestamp,tod
```

**Where results go.** Use `--output-dir <dir>` to choose where the generated
files (`_output.txt`, `_analysis.txt`, `gen/ast.json`, and the optional JSON
verdicts) are written. If you omit `--output-dir`, they default to
`./analysis_output/` in your current directory. Result files are **never** written
next to the input `.sol`, so running the analyzer over a dataset never pollutes
the dataset directory:

```bash
# explicit location
python src/main.py datasets/sbc/reentrancy/foo.sol --output-dir results/manual
# no flag -> writes to ./analysis_output/ (dataset stays clean)
python src/main.py datasets/sbc/reentrancy/foo.sol
```

Choose the numerical domain for the relational pipelines (reentrancy, and the
timestamp/TOD confirmation):

```bash
python src/main.py contract.sol --reentrancy-domain Box       # Interval
python src/main.py contract.sol --reentrancy-domain Octagon
python src/main.py contract.sol --reentrancy-domain Polka     # Polyhedra
python src/main.py contract.sol --reentrancy-domain all       # run all three (agreement study)
```

### Command-line options

| Option                      | Meaning                                                                                                                                                      |
| --------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `solidity_filepath`       | one or more`.sol` files to analyze (positional)                                                                                                            |
| `--pipelines`             | comma-separated subset of`reentrancy,overflow,timestamp,tod` (default: all)                                                                                |
| `--reentrancy-domain`     | `auto` (default fast path), `Box`, `Octagon`, `Polka`, or `all`                                                                                    |
| `--json`                  | also emit a machine-readable JSON verdict file                                                                                                               |
| `--output-dir`            | directory for generated result files. Default:`./analysis_output/` in the current directory. Files are **never** written next to the input `.sol`. |
| `--annotate-dependencies` | include the dependency chain in the report                                                                                                                   |
| `--verbose`               | show full interval details in each verdict                                                                                                                   |

---

## Reproducing the evaluation

The scripts in [`scripts/`](scripts/) reproduce every number in the paper.

```bash
# 1. Run the analyzer on a dataset
#    (sbc | qian_reentrancy | qian_overflow | qian_timestamp | rsd | solidifi)
python scripts/run_ours.py sbc --workers 8

# 2. Per-contract detection-time experiment (run serially; backs Table 8)
python scripts/run_timing_experiment.py sbc --reps 3

# 3. Compute the comparison metrics and the cross-tool table
python scripts/build_comparison.py        # -> tables/metrics_per_class.csv
                                          #    (also renders comparison_table.*; the repo keeps the .pdf)

# 4. Aggregate Table 8 (median detection time)
python scripts/make_table8_timing.py      # -> tables/table8_timing_median.csv (Table 8)

# 5. Build the normalized per-prediction records (one schema for every tool)
python scripts/make_predictions.py        # -> results/standardized/
```

Step 5 cross-validates the normalized predictions against
`tables/metrics_per_class.csv` and reports any mismatch. The exact invocations
used to (re)generate the result files are the numbered steps above.

### Reproducing the baselines

Each baseline was run in a fixed, version-pinned environment (Mythril from its
official `v0.24.8` release; every other baseline in a pinned Docker image). The
exact image reference and content digest — or the Dockerfile and pinned source
commit — together with the execution command, timeout settings, and the raw
per-contract outputs, are documented **per baseline** in that tool's own
`results/<tool>/REPRODUCIBILITY.md`:

```
results/mythril/REPRODUCIBILITY.md      results/sailfish/REPRODUCIBILITY.md
results/oyente_plus/REPRODUCIBILITY.md  results/smartcheck/REPRODUCIBILITY.md
results/slither/REPRODUCIBILITY.md      results/vandal/REPRODUCIBILITY.md
results/osiris/REPRODUCIBILITY.md       results/ethersolve/REPRODUCIBILITY.md
```

These correspond to **Table 9** (tool versions and execution environments) in the
paper. In addition, each `results/<tool>/examples/` folder holds that tool's
committed verdicts on the paper's figure contracts, so the qualitative claims can
be confirmed by inspection without re-running the tool.

---

## Datasets

| Dataset                           | Contracts                                                   | Vulnerabilities evaluated            |
| --------------------------------- | ----------------------------------------------------------- | ------------------------------------ |
| **SBC** (SmartBugs Curated) | 142                                                         | reentrancy, overflow, timestamp, TOD |
| **Qian**                    | 222 / 275 / 349 (reentrancy / overflow / timestamp subsets) | reentrancy, overflow, timestamp      |
| **RSD**                     | 138                                                         | reentrancy                           |
| **SolidiFI**                | 100                                                         | TOD                                  |

Ground truth is provided per dataset as `*_ground_truth.json`, mapping each
contract to `{reentrancy, overflow, timestamp, tod} ∈ {0,1}`. See
[`results/README.md`](results/README.md) for the key conventions (notably that
Qian reuses numeric IDs across subsets, so the subset prefix is significant).

---

## Results and metrics

The canonical results live in [`tables/`](tables/):

- **`metrics_per_class.csv`** — one row per *(dataset, vulnerability, tool)* with
  the confusion counts (TP/FP/TN/FN), the number of contracts actually analyzed
  vs. the benchmark total, and the derived metrics (precision, recall, F1,
  accuracy, FDR, FNR, TPR, FPR, single-operating-point AUC). This file
  regenerates **Tables 4–7**, the per-class F1 in **Fig 15**, and the AUC values
  in **Fig 16**.
- **`comparison_table.pdf`** — a human-readable side-by-side of all nine
  tools, with an explicit **Failures** column (contracts the tool could not
  analyze — compile error / crash / timeout) so coverage is transparent.
- **`table8_timing_median.csv`** — per-contract detection time for every tool
  (and our Interval / Octagon / Polyhedra domains), measured serially with
  repeated trials and reported as the **median** (**Table 8**).

Every metric is recomputed by a single formula from each tool's own
TP/FP/TN/FN, so the comparison is strictly apples-to-apples. A blank cell means
that tool has no detector for, or was not run on, that dataset–vulnerability
(genuinely N/A, never silently counted as a negative). The provenance of each
baseline's numbers is documented in [`results/README.md`](results/README.md).

---

## Output files of a run

For each analyzed contract the tool writes the following into the output directory
(`--output-dir`, or `./analysis_output/` by default — never next to the input `.sol`):

| File                     | Contents                                                                                  |
| ------------------------ | ----------------------------------------------------------------------------------------- |
| `<name>_verdicts.json` | machine-readable verdicts (the authoritative per-contract record; written with`--json`) |
| `<name>_analysis.txt`  | the abstract-interpretation trace and intermediate state                                  |
| `<name>_output.txt`    | the human-readable`[SUMMARY]` of detected vulnerabilities                               |
| `gen/ast.json`         | the compiled AST dump for the contract                                                    |

---

## Citation

This artifact accompanies a manuscript currently under peer review. Citation
details will be added here once the paper is published. In the meantime, please
cite the repository.

---

## License

See [`LICENSE`](LICENSE) (to be finalized by the authors).
