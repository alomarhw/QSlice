from __future__ import annotations
from pathlib import Path

from qpdg_builder import QPDG


EDGE_STYLES = {
    "ued": 'color="black", style="solid"',
    "ed": 'color="blue", style="dashed", penwidth=2',
    "md": 'color="purple", style="solid"',
    "cd": 'color="darkgreen", style="dotted", penwidth=2',
}


def _node_label(n) -> str:
    if n.kind == "STMT":
        qubits = ",".join(n.meta.get("qubits", [])) or "classical"
        stores = n.meta.get("stores", [])
        store = f" -> {','.join(stores)}" if stores else ""
        gate = f" {n.gate}" if n.gate else ""
        return f"{n.id}: l{n.line}\n{n.action}{gate}\n{qubits}{store}"
    # Legacy fallback labels for callers that still construct old-style nodes.
    if n.kind == "QOP":
        g = n.gate or ""
        a = n.action or ""
        return f"{n.kind}\n{n.qubit}@t{n.time},l{n.line}\n{a}:{g}"
    if n.kind == "MEASURE":
        return f"MEASURE\n{n.qubit}@t{n.time},l{n.line}\n-> {n.store}"
    if n.kind == "CDEF":
        return f"CDEF\n{n.store}@t{n.time},l{n.line}"
    return f"{n.kind}\n{n.id}"


def _edge_style(kind: str) -> str:
    parts = kind.split("+")
    for part in parts:
        if part in EDGE_STYLES:
            return EDGE_STYLES[part]
    return 'style="solid"'


def to_dot(g: QPDG, *, show_edge_labels: bool = True) -> str:
    lines = []
    lines.append("digraph QDG {")
    lines.append('  rankdir="LR";')
    lines.append('  node [shape=box, fontsize=10];')

    for nid, n in g.nodes.items():
        label = _node_label(n).replace('"', '\\"')
        lines.append(f'  "{nid}" [label="{label}"];')

    for e in g.edges:
        style = _edge_style(e.kind)
        if show_edge_labels:
            labels = e.meta.get("labels") or []
            label = e.kind if not labels else f"{e.kind} ({'; '.join(labels)})"
            lines.append(f'  "{e.src}" -> "{e.dst}" [label="{label}", {style}];')
        else:
            lines.append(f'  "{e.src}" -> "{e.dst}" [{style}];')

    lines.append("}")
    return "\n".join(lines)


def write_dot(g: QPDG, out_path: str | Path, *, show_edge_labels: bool = True) -> Path:
    out_path = Path(out_path)
    out_path.write_text(to_dot(g, show_edge_labels=show_edge_labels), encoding="utf-8")
    return out_path


def render_with_graphviz(dot_path: str | Path, out_path: str | Path, fmt: str = "png") -> None:
    """
    Requires graphviz installed:
      - macOS: brew install graphviz
      - Ubuntu: sudo apt-get install graphviz
    """
    import subprocess
    dot_path = str(dot_path)
    out_path = str(out_path)
    subprocess.run(["dot", f"-T{fmt}", dot_path, "-o", out_path], check=True)
