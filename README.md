# Abstract Interpretation based Solidity Analysis Framework

## Overview
This tool is a static analysis framework for Solidity smart contracts. It follows a modular, layered architecture that separates Solidity parsing, control-flow construction, dependency analysis, and abstract semantics evaluation.

Functionally, it serves as a semantics-aware smart contract vulnerability detection (SCVD) framework by extending the **Abstract Interpretation** theory. This is a unifying framework for computing safe approximations of dynamic behavioral properties of Solidity smart contracts at different levels of abstraction. 

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

## Repository Structure

All source code of the framework is located in the `src/` directory.
The implementation follows a modular design that mirrors the analysis pipeline described in the paper, from Solidity compilation to abstract semantics evaluation.

```text
src/
├── compiler/
├── control_flow_graph/
├── static_analysis/
├── dependency_analysis.py
├── invariant_generator/
├── java_wrapper/
├── utils/
└── main.py
```

Module Overview

- **`compiler/`** 
Handles Solidity compilation and compiler version selection using `solcx`.

- **`control_flow_graph/`**  
  Constructs an **augmented Control Flow Graph (CFG)** from the Solidity AST.

  - **`node_processor/`**  
    Contains handlers for individual Solidity AST nodes. Each file corresponds to a specific language construct (e.g., `IfStatement`, `FunctionDefinition`, `WhileStatement`).

  - **`extra_nodes/`**  
    Introduces auxiliary CFG nodes such as entry, exit, and join nodes to represent structured control flow and looping constructs.

- **`static_analysis/`** 
Contains the semantic analysis core of the framework.
    - **`collecting_semantics/`** 
    implements the concrete collecting semantics of Solidity constructs
    - **`abstract_collecting_semantics/`**
    defines the corresponding abstract semantics used for static analysis and performs fixpoint-based abstract interpretation over numerical domains, including Intervals, Octagons, and Polyhedra.

- **`dependency_analysis.py`**
Implements flow- and context-sensitive `data and control dependency analysis` over the CFG.
This information is used to detect vulnerabilities such as timestamp dependency and Transaction Ordering Dependency (TOD).

- **`invariant_generator/`**
Includes utilities for generating and managing invariants derived from abstract states, supporting semantic vulnerability detection.

- **`java_wrapper/`**
Provides a lightweight interface between Python and APRON via JPype, enabling numerical abstract domain operations used during abstract semantics evaluation.

- **`utils/`**
Contains shared helper functions for expression handling and internal transformations.

- **`main.py`**
Entry point of the framework.
It orchestrates compilation, CFG construction, dependency analysis, and abstract semantics evaluation for a given Solidity contract.

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
```


## Execution
First, ensure your Conda environment is active:
```bash
conda activate safpy
```

Then, navigate to the source directory and  execute the main analysis script:

```bash
cd src
python main.py path/to/your_contract.sol