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
To ensure maximum precision in Abstract Interpretation, our framework includes a Semantic Preprocessing (mapping_transformer.py). Standard static analysis tools often lose context when encountering complex Ethereum storage structures (like sparse mappings) or low-level external calls.

Our tool overcomes this by normalizing these constructs into explicit numerical constraints before the Control Flow Graph (CFG) construction. This step ensures that the underlying numerical domains (Box, Octagon, Polyhedra) can mathematically prove the presence or absence of vulnerabilities without semantics loss.

Key transformation advantages include:

* Abstract State Modeling. Solidity mappings are transformed into representative abstract variables. This allows the APRON engine to track data flow and constraints on state variables (e.g., user balances) that are otherwise invisible to numerical domains.

* Explicit Control Flow for External Calls. Low-level operations like call.value, send, and transfer are normalized into conditional logic blocks that model the exact state changes (such as balance deductions). This exposes the logical flow to the analyzer, allowing it to detect Reentrancy and Transaction Ordering Dependencies (TOD) by observing how state variables change relative to external interaction points.

* Struct Flattening. Nested structures are flattened into scalar variables, preventing information loss during the conversion to the abstract domain.

* No semantic loss. All transformations are sound over-approximations:

- No feasible execution path of the original contract is removed.

- No behaviour relevant to vulnerability detection is lost.

- The transformation simply removes syntactic irregularities that hinder abstract interpretation engines.

As a result, the preprocessed program preserves all behaviours detectable at the semantic level, while enabling the analysis engine to operate on a uniform program representation.

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

