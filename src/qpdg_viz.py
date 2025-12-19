from __future__ import annotations
from typing import Optional
from pathlib import Path

from qpdg_builder import QPDG


def _node_label(n) -> str:
    # Compact label that still debugs well
    if n.kind == "QOP":
        g = n.gate or ""
        a = n.action or ""
        return f"{n.kind}\\n{n.qubit}@t{n.time},l{n.line}\\n{a}:{g}"
    if n.kind == "MEASURE":
        return f"MEASURE\\n{n.qubit}@t{n.time},l{n.line}\\n-> {n.store}"
    if n.kind == "CDEF":
        return f"CDEF\\n{n.store}@t{n.time},l{n.line}"
    return f"{n.kind}\\n{n.id}"


def to_dot(g: QPDG, *, show_edge_labels: bool = True) -> str:
    # Colors are optional; keep it simple
    lines = []
    lines.append("digraph QPDG {")
    lines.append('  rankdir="LR";')
    lines.append('  node [shape=box, fontsize=10];')

    # Nodes
    for nid, n in g.nodes.items():
        label = _node_label(n).replace('"', '\\"')
        lines.append(f'  "{nid}" [label="{label}"];')

    # Edges
    for e in g.edges:
        if show_edge_labels:
            lines.append(f'  "{e.src}" -> "{e.dst}" [label="{e.kind}"];')
        else:
            lines.append(f'  "{e.src}" -> "{e.dst}";')

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

