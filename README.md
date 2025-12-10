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

