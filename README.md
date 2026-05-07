# QSlice: Semantics-Driven Quantum Program Slicing

QSlice is an experimental research prototype for constructing a
**Quantum Dependency Graph (QDG)** and computing **qubit-centric quantum
slices** from QStatic parser output.

The current implementation follows a semantics-driven view of quantum slicing:
a slice is not just a forward or backward graph traversal over syntactic actions.
Instead, QSlice reconstructs source-level statements, extracts semantic
quantum/classical dependencies, and computes the statements required to preserve
the observable behavior of a target qubit.

QSlice builds on top of **QStatic** (<https://github.com/srcML/QStatic>) for
OpenQASM parsing and action extraction.

> **Prototype status**
>
> QSlice is intended for research, experimentation, and program-analysis
> prototyping. It is not a production compiler, verifier, or quantum simulator.

---

## What QSlice Computes

Given a parsed quantum program and a target qubit `q`, QSlice computes:

1. A **statement-level QDG** `QDG(P) = (V, E)`.
2. The qubit slicing criterion `Γ(q)`: statements that directly operate on or
   measure `q`.
3. A quantum slice `S(q)`: statements that are semantic predecessors of `Γ(q)`
   through dependency edges.

In the default mode, QSlice computes a **qubit-centric decomposition slice**:

```text
S(q) = fixed point of semantic predecessors starting from Γ(q)
```

This default is exposed as:

```bash
python3 qslice.py --qubit q3 --mode quantum
```

`--mode quantum` is the default. Legacy directed traversals are still available
as `--mode backward` and `--mode forward` for debugging and comparison.

---

## Semantic Model

### Statement-level QDG nodes

QStatic emits per-qubit action records. For example, a controlled operation may
appear as one `ctrl` action on the control qubit and one `ctrl-gate-call` action
on the target qubit.

QSlice groups action records with the same `(time, line)` into one
source-level statement node. This means a statement such as:

```qasm
cx q1, q2;
```

is represented as one QDG node touching both `q1` and `q2`, rather than as two
separate per-qubit nodes.

Each statement node records:

- statement id,
- source line,
- parser time,
- statement action kind,
- gate name, if available,
- touched qubits,
- classical variables defined by measurement/classical statements,
- classical variables used in guards or expressions,
- guard conditions, when available.

### Semantic dependency edges

QSlice uses four semantic edge types:

| Edge | Meaning |
| --- | --- |
| `ued` | **Unitary Evolution Dependency**: uninterrupted unitary evolution on the same qubit until measurement or reset. |
| `ed` | **Entanglement Dependency**: influence from a multi-qubit unitary to later statements touching qubits in the active entangled set. |
| `md` | **Measurement Dependency**: prior quantum evolution that contributes to a measurement outcome. |
| `cd` | **Classical Dependency**: classical data/control influence, including measurement-driven guarded quantum execution. |

These edges are intended to capture semantic influence relevant to preserving a
target qubit's observable behavior. Execution-order constraints and physical
constraints that do not express semantic influence are not modeled as QDG edges.

---

## Repository Layout

```text
.
├── qslice.py                 Statement-level QDG construction and slicing CLI
├── parser.py                 QStatic-derived OpenQASM XML parser
├── src/
│   ├── qpdg_builder.py       Earlier/alternate graph builder prototype
│   ├── qpdg_cli.py           Prototype CLI
│   └── qpdg_viz.py           Prototype visualization helpers
├── tests/
│   └── test_qslice.py        Unit tests for semantic QDG/slicing behavior
├── examples/
│   ├── chain3.qasm
│   ├── chain3.qasm.xml
│   ├── encapsulation.qasm
│   ├── encapsulation.qasm.xml
│   ├── hadamard_cnot.qasm
│   ├── hadamard_cnot.qasm.xml
│   ├── horizontal.qasm
│   └── horizontal.qasm.xml
└── images/                   Existing graph example images
```

Generated files such as `out.json`, `slice.json`, `qdg.json`, and `qdg.dot` are
created by the commands below and are not required to be committed.

---

## Requirements

- Python 3.9+
- Graphviz, if DOT rendering is desired
- srcML/QStatic-compatible XML input for `parser.py`

On macOS:

```bash
brew install graphviz srcml
```

---

## Quick Start

### 1. Parse an OpenQASM XML file

```bash
python3 parser.py examples/chain3.qasm.xml
```

This writes `out.json`, the QStatic-style intermediate action representation.

### 2. Build a QDG export

```bash
python3 qslice.py --in out.json --qubit q3 --export-qdg --qdg-out qdg.json
```

This writes:

- `qdg.json`: statement-level QDG nodes and semantic edges,
- `slice.json`: the default quantum slice for `q3`.

### 3. Compute a qubit-centric quantum slice

```bash
python3 qslice.py \
  --in out.json \
  --qubit q3 \
  --mode quantum \
  --out slice.json
```

The output includes:

- `criterion`: the matched criterion statements `Γ(q3)`,
- `slice_lines`: source lines included in the slice,
- `slice_statements`: statement-level slice nodes with dependency explanations.

### 4. Export a highlighted DOT graph

```bash
python3 qslice.py \
  --in out.json \
  --qubit q3 \
  --mode quantum \
  --export-dot \
  --dot-out qdg.dot \
  --dot-highlight-slice
```

Render the DOT file with Graphviz:

```bash
dot -Tpng -Gdpi=300 qdg.dot -o qdg.png
```

---

## CLI Reference

```bash
python3 qslice.py --help
```

Common options:

| Option | Description |
| --- | --- |
| `--in out.json` | Input QStatic-style JSON file. |
| `--out slice.json` | Output slice JSON file. |
| `--qubit q3` | Target qubit for the slicing criterion. |
| `--line 11` | Optional line filter for criterion matching. |
| `--time 3` | Optional parser-time filter for criterion matching. |
| `--action unitary` | Optional statement action filter. |
| `--gate cx` | Optional gate filter. |
| `--mode quantum` | Default paper-aligned qubit-centric slice. |
| `--mode backward` | Legacy directed predecessor traversal. |
| `--mode forward` | Legacy directed successor traversal. |
| `--export-qdg` | Write QDG JSON. |
| `--export-dot` | Write QDG DOT. |
| `--dot-highlight-slice` | Highlight slice nodes in DOT output. |
| `--explain-paths` | Include parent-chain explanation paths in `slice.json`. |

`--direction backward|forward` is retained as a deprecated alias for the legacy
directed modes.

---

## Output Formats

### `qdg.json`

The QDG export has this shape:

```json
{
  "nodes": [
    {
      "id": 0,
      "time": 0,
      "line": 7,
      "action": "unitary",
      "gate": "h",
      "qubits": ["q1"],
      "stores": [],
      "uses": [],
      "conditions": [],
      "local_names": ["q1"]
    }
  ],
  "edges": [
    {
      "from": 0,
      "to": 2,
      "type": "ued",
      "labels": ["q1"]
    }
  ]
}
```

An edge type can contain multiple semantic labels, such as `ed+md`, when the
same ordered pair has more than one semantic dependency.

### `slice.json`

The slice output includes both `slice_actions` and `slice_statements`. They are
currently the same statement-level list; `slice_actions` is retained for
backward compatibility with older scripts.

Important fields:

- `criterion`: CLI filters and matched criterion nodes,
- `slice_qubits`: qubits touched by the slice,
- `slice_lines`: source lines included in the slice,
- `slice_statements`: statement nodes included in the slice,
- `reason_type`: why a non-criterion statement was included,
- `reason_next_toward_criterion`: next statement along the dependency chain.

---

## Printing a Slice in QASM-like Form

After generating `slice.json`, you can print a compact statement summary:

```bash
python3 - <<'PY'
import json

d = json.load(open("slice.json"))
for stmt in d["slice_statements"]:
    qubits = ", ".join(stmt["qubits"]) or "classical"
    if stmt["action"] in {"unitary", "guarded-unitary"}:
        guard = f" if {'; '.join(stmt['conditions'])}" if stmt["conditions"] else ""
        print(f"line {stmt['line']}: {stmt['gate']} {qubits};{guard}")
    elif stmt["action"] == "measure":
        stores = ", ".join(stmt["stores"]) or "?"
        print(f"line {stmt['line']}: measure {qubits} -> {stores};")
    elif stmt["action"] == "reset":
        print(f"line {stmt['line']}: reset {qubits};")
    else:
        print(f"line {stmt['line']}: {stmt['action']} {qubits};")
PY
```

---

## Classical Dependencies

The parser can attach guard conditions to quantum actions using the `if` field.
QSlice extracts identifiers from these conditions and creates `cd` edges from
previous statements that define those identifiers, such as measurements that
store into classical bits.

QSlice also supports an optional `_classical` list in hand-authored `out.json`
files for classical post-processing statements:

```json
{
  "_classical": [
    {
      "action": "classical",
      "time": 6,
      "line": 15,
      "store": "c[2]",
      "expr": "c[0] ^ c[1]"
    }
  ]
}
```

This allows tests and experiments to model classical statements that may not yet
be emitted by the parser.

---

## Development and Tests

Run the unit tests:

```bash
python3 -m unittest discover -s tests -v
```

Run a syntax check:

```bash
python3 -m py_compile qslice.py parser.py src/qpdg_builder.py src/qpdg_cli.py src/qpdg_viz.py
```

The tests cover:

- statement-level grouping of controlled operations,
- extraction of `ued`, `ed`, `md`, and `cd` edges,
- expected qubit slices for the paper-style running example,
- termination of unitary evolution at measurement.

---

## Known Limitations

- QSlice depends on the structure and metadata emitted by `parser.py`.
- Classical dependencies are limited to classical stores/uses visible in
  `out.json` metadata, guard conditions, or optional `_classical` records.
- The slicer constructs semantic dependency graphs; it does not simulate quantum
  programs or statistically compare measurement distributions.
- DOT images in `images/` are historical/example artifacts and may not represent
  every current CLI output mode.

---

## License

This project is licensed under the GNU General Public License v3.0 (GPL-3.0).
See [`LICENSE`](LICENSE) for details.
