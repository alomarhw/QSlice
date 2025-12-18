# QSlice Artifact Description and Reproducibility Guide

This document describes how to **reproduce the core functionality and claims**
of the QSlice artifact.

The artifact demonstrates:
- construction of a Quantum Dependency Graph (QDG), and
- forward and backward program slicing over quantum operations.

This artifact is intended for **research evaluation and reproducibility**.

----------------------------------------------------------------

## Artifact Scope

The QSlice artifact supports the following claims:

- Quantum programs can be represented using a dependency graph (QDG)
  that captures both wire (sequential) and entanglement dependencies.
- Forward and backward slicing can be computed over this graph
  with respect to a slicing criterion (qubit + program point).
- Extracted slices can be visualized and inspected.

The artifact does NOT claim:
- completeness for all OpenQASM constructs
- production-level robustness
- integration with quantum compilers or simulators

----------------------------------------------------------------

## Environment

The artifact has been tested with:

- macOS (Apple Silicon and Intel)
- Python 3.9+
- srcML
- Graphviz (dot)

Other Unix-like systems should work but are not guaranteed.

----------------------------------------------------------------

## Dependencies

Install required tools on macOS:

  brew install srcml graphviz

Python dependencies are limited to the standard library.

----------------------------------------------------------------

## Artifact Structure

.
├── qslice.py               QDG construction and slicing logic
├── parser.py               QStatic-based OpenQASM parser
├── examples/               Example OpenQASM programs
├── README.md               User-oriented documentation
└── ARTIFACT.md             This reproducibility guide

----------------------------------------------------------------

## Reproducing the Artifact Results

### Step 1: Parse OpenQASM into intermediate representation

Run:

  python3 parser.py examples/chain3.qasm.xml

Expected output:
- File created: out.json
- No runtime errors

This step extracts quantum operations and metadata
from a srcML-marked OpenQASM file.

----------------------------------------------------------------

### Step 2: Construct the Quantum Dependency Graph (QDG)

Run:

  python3 qslice.py --export-dot

Expected output:
- File created: qdg.dot

To visualize the graph:

  dot -Tpng -Gdpi=300 qdg.dot -o qdg.png
  open qdg.png

The resulting graph should show:
- nodes representing quantum operations
- edges representing wire and entanglement dependencies

----------------------------------------------------------------

### Step 3: Reproduce a Backward Slice

Example slicing criterion:
- qubit: q3
- line number: 11

Run:

  python3 qslice.py \
    --qubit q3 \
    --line 11 \
    --direction backward \
    --export-dot \
    --dot-highlight-slice

Expected output:
- File created: slice.json
- Updated qdg.dot highlighting slice nodes

Render the slice:

  dot -Tpng -Gdpi=300 qdg.dot -o qdg_backward.png
  open qdg_backward.png

The highlighted nodes represent all operations
that can influence the slicing criterion.

----------------------------------------------------------------

### Step 4: Reproduce a Forward Slice

Example slicing criterion:
- qubit: q2
- line number: 10

Run:

  python3 qslice.py \
    --qubit q2 \
    --line 10 \
    --direction forward \
    --export-dot \
    --dot-highlight-slice

Expected output:
- Updated qdg.dot highlighting the forward slice

Render:

  dot -Tpng -Gdpi=300 qdg.dot -o qdg_forward.png
  open qdg_forward.png

The highlighted nodes represent all operations
influenced by the slicing criterion.

----------------------------------------------------------------

## Expected Outputs Summary

After successful reproduction, the following files should exist:

- out.json
- qdg.dot
- qdg.png
- slice.json
- qdg_backward.png
- qdg_forward.png

All commands should execute without errors.

----------------------------------------------------------------

## Known Limitations

- OpenQASM support depends on QStatic and srcML
- Some example XML files contain manually added position attributes
- Classical–quantum interaction is not fully modeled
- Large circuits may produce dense visualizations

----------------------------------------------------------------

## Artifact Maintenance

This artifact is a **research prototype**.
It is provided to support reproducibility and future research,
not as a maintained software product.

----------------------------------------------------------------

## Contact

For questions regarding the artifact or reproduction issues,
please open an issue on the GitHub repository:

https://github.com/alomarhw/QSlice
