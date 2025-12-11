# Solidity Analysis Framework

## Overview
This tool is a static analysis framework for Solidity smart contracts. It follows a modular, layered architecture that separates Solidity parsing, control-flow construction, dependency analysis, and abstract semantics evaluation.

The tool detects various vulnerabilities, including:
* Reentrancy
* Integer Overflow/Underflow
* Timestamp Dependencies
* Transaction Ordering Dependencies (TOD)

## Architecture
The tool takes a Solidity smart contract (`.sol`) as input, compiles it using `solcx`, and constructs an Augmented Control Flow Graph (CFG). It utilizes the **APRON** numerical library (via JPype) to perform Fixpoint Abstract Semantics evaluation.

## Semantic Preprocessing & Normalization
To ensure high precision in Abstract Interpretation, the framework employs a **Semantic Preprocessing** module (`mapping_transformer.py`). This engine normalizes complex Solidity constructs into explicit numerical constraints compatible with the **APRON** domain.

Key transformations include:

* **Abstract State Modeling:** Transforms sparse `mappings` and nested `structs` into representative scalar variables. This allows the numerical engine to track constraints on state variables (like user balances) that are usually invisible to abstract domains.

* **External Call Normalization:** Converts low-level operations (`call.value`, `transfer`, `send`) into explicit conditional logic blocks. This exposes the control flow and state changes (e.g., balance deductions) necessary for detecting **Reentrancy** and **TOD**.

* **Semantics Preservation:** The normalization is a **sound over-approximation**; it removes syntactic irregularities while preserving all execution paths and behaviors relevant to vulnerability detection.

## Installation

### Prerequisites
* Python 3.10+
* Conda (recommended)
* Java (for APRON / JPype)
* `solc` (Solidity compiler), accessible via `solcx`

To reproduce our environment:

```bash
conda env create -f safpy-env.yml
conda activate safpy

