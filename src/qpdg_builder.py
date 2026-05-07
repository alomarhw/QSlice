from __future__ import annotations

"""Compatibility builder for statement-level semantic QDGs.

Historically, this module built a per-qubit QPDG with temporal and local
entanglement edges.  The main slicer now defines the paper-aligned model in
``qslice.py``: statement-level nodes and semantic ``ued``/``ed``/``md``/``cd``
edges.  To keep ``src/qpdg_cli.py`` and visualization helpers useful without
maintaining a second, divergent graph algorithm, this module adapts the
canonical ``qslice.build_qdg`` output into the lightweight ``QPDG`` container
used by the ``src`` tools.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from qslice import build_qdg, statement_brief


# -----------------------------
# Core graph data structures
# -----------------------------

NodeId = str


@dataclass(frozen=True)
class Node:
    id: NodeId
    kind: str = "STMT"
    qubit: Optional[str] = None  # Retained for compatibility with older callers.
    time: Optional[int] = None
    line: Optional[int] = None
    action: Optional[str] = None
    gate: Optional[str] = None
    ctrl: Optional[str] = None
    store: Optional[str] = None
    meta: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Edge:
    src: NodeId
    dst: NodeId
    kind: str  # "ued" | "ed" | "md" | "cd" or combined labels like "ed+md"
    meta: Dict[str, Any] = field(default_factory=dict)


@dataclass
class QPDG:
    nodes: Dict[NodeId, Node] = field(default_factory=dict)
    edges: List[Edge] = field(default_factory=list)

    def add_node(self, node: Node) -> None:
        if node.id in self.nodes:
            return
        self.nodes[node.id] = node

    def add_edge(self, src: NodeId, dst: NodeId, kind: str, **meta: Any) -> None:
        self.edges.append(Edge(src=src, dst=dst, kind=kind, meta=dict(meta)))

    def outgoing(self, nid: NodeId) -> List[Edge]:
        return [e for e in self.edges if e.src == nid]

    def incoming(self, nid: NodeId) -> List[Edge]:
        return [e for e in self.edges if e.dst == nid]


# -----------------------------
# Builder
# -----------------------------


class QPDGBuilder:
    """Build a statement-level semantic QDG from QStatic ``out.json``.

    The returned graph uses statement ids of the form ``v0``, ``v1``, ... and
    semantic edge kinds from the paper-aligned model: ``ued``, ``ed``, ``md``,
    and ``cd``.  Combined dependencies are represented as joined labels such as
    ``ed+md``.
    """

    @staticmethod
    def _node_id(statement_id: int) -> NodeId:
        return f"v{statement_id}"

    def build_from_outjson(self, out: Dict[str, Any]) -> QPDG:
        statements, _g_fwd, _g_bwd, edge_type, edge_meta = build_qdg(out)
        graph = QPDG()

        for stmt in statements:
            brief = statement_brief(stmt)
            node_id = self._node_id(stmt.id)
            graph.add_node(
                Node(
                    id=node_id,
                    kind="STMT",
                    qubit=next(iter(sorted(stmt.qubits)), None),
                    time=stmt.time,
                    line=stmt.line,
                    action=stmt.action,
                    gate=stmt.gate,
                    store=next(iter(sorted(stmt.stores)), None),
                    meta={
                        **brief,
                        "statement_id": stmt.id,
                        "actions": stmt.actions,
                    },
                )
            )

        for (src, dst), kind in sorted(edge_type.items()):
            graph.add_edge(
                self._node_id(src),
                self._node_id(dst),
                kind,
                labels=sorted(edge_meta.get((src, dst), set())),
            )

        return graph


def load_outjson(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


if __name__ == "__main__":
    out = load_outjson("out.json")
    builder = QPDGBuilder()
    g = builder.build_from_outjson(out)

    print(f"Nodes: {len(g.nodes)}")
    print(f"Edges: {len(g.edges)}")
    counts: Dict[str, int] = {}
    for e in g.edges:
        counts[e.kind] = counts.get(e.kind, 0) + 1
    print("Edge counts:", counts)
