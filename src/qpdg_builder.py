from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple
import json
import itertools


# -----------------------------
# Core graph data structures
# -----------------------------

NodeId = str

@dataclass(frozen=True)
class Node:
    id: NodeId
    kind: str                   # "QOP" | "MEASURE" | "CDEF" | later: "CPRED", "CSTMT"
    qubit: Optional[str] = None # for quantum nodes
    time: Optional[int] = None
    line: Optional[int] = None
    action: Optional[str] = None
    gate: Optional[str] = None
    ctrl: Optional[str] = None
    store: Optional[str] = None # for measurement and cdef
    meta: Dict[str, Any] = field(default_factory=dict)

@dataclass(frozen=True)
class Edge:
    src: NodeId
    dst: NodeId
    kind: str                   # "q_temporal" | "q_entanglement" | "q_measure" | "q2c_measure" | ...
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
    """
    Builds a QPDG from QStatic's out.json structure (qubit -> actions[]).
    Supports:
      - per-qubit temporal deps
      - entanglement deps for multi-qubit ops at same (time,line)
      - measurement deps: last quantum op -> measure -> classical def (store)
    """

    def __init__(self) -> None:
        self.g = QPDG()
        # Track last node per qubit to create temporal edges
        self._last_on_wire: Dict[str, NodeId] = {}
        # Group quantum event node-ids by (time, line) to infer entanglement deps
        self._by_time_line: Dict[Tuple[int, int], List[NodeId]] = {}
        # Map (qubit, time, line) -> node id (useful for debugging)
        self._q_event_index: Dict[Tuple[str, int, int], NodeId] = {}
        # Map classical store name -> last defining node id
        self._c_last_def: Dict[str, NodeId] = {}

    @staticmethod
    def _is_qubit_entry(key: str, value: Any) -> bool:
        return isinstance(value, dict) and "actions" in value and key != "_filename"

    @staticmethod
    def _make_qnode_id(qubit: str, time: int, line: int, action: str, gate: str = "") -> NodeId:
        # Stable identifier
        return f"Q::{qubit}::t{time}::l{line}::{action}::{gate or '-'}"

    @staticmethod
    def _make_measure_id(qubit: str, time: int, line: int, store: str) -> NodeId:
        return f"M::{qubit}::t{time}::l{line}::store::{store}"

    @staticmethod
    def _make_cdef_id(store: str, time: int, line: int, qubit: str) -> NodeId:
        return f"CDEF::{store}::t{time}::l{line}::from::{qubit}"

    def build_from_outjson(self, out: Dict[str, Any]) -> QPDG:
        # 1) Create nodes + temporal edges wire-by-wire
        for qubit, entry in out.items():
            if not self._is_qubit_entry(qubit, entry):
                continue

            actions = entry.get("actions", [])
            # Sort actions by time (and line as tie-breaker)
            actions = sorted(actions, key=lambda a: (a.get("time", 0), a.get("line", 0)))

            for a in actions:
                action = a.get("action", "")
                time = int(a.get("time", 0))
                line = int(a.get("line", 0))

                if action == "measure":
                    store = str(a.get("store", ""))
                    mid = self._make_measure_id(qubit, time, line, store)
                    mnode = Node(
                        id=mid, kind="MEASURE", qubit=qubit, time=time, line=line,
                        action="measure", store=store
                    )
                    self.g.add_node(mnode)

                    # Temporal edge on wire
                    self._add_temporal_edge(qubit, mid)

                    # Measurement dependence: last quantum op on this wire -> measure
                    # (If temporal edge already encodes that, we still label explicitly for QPDG)
                    prev = self._prev_on_wire(qubit, mid)
                    if prev is not None:
                        self.g.add_edge(prev, mid, "q_measure")

                    # Measurement -> classical def
                    if store:
                        cid = self._make_cdef_id(store, time, line, qubit)
                        cnode = Node(
                            id=cid, kind="CDEF", time=time, line=line,
                            action="def", store=store,
                            meta={"source": "measure", "qubit": qubit}
                        )
                        self.g.add_node(cnode)
                        self.g.add_edge(mid, cid, "q2c_measure")

                        # Track last def of that classical symbol for future c_data edges
                        self._c_last_def[store] = cid

                    continue  # measurement handled

                # Otherwise: quantum op node (includes ctrl/targ/ctrl-gate-call/gate-call etc.)
                gate = str(a.get("type", ""))  # QStatic uses "type" for gate name on some actions
                ctrl = str(a.get("ctrl", "")) if "ctrl" in a else None
                local_name = str(a.get("local_name", qubit))

                qid = self._make_qnode_id(qubit, time, line, action, gate)
                qnode = Node(
                    id=qid, kind="QOP", qubit=qubit, time=time, line=line,
                    action=action, gate=gate, ctrl=ctrl,
                    meta={"local_name": local_name}
                )
                self.g.add_node(qnode)

                # Temporal edge on wire
                self._add_temporal_edge(qubit, qid)

                # Track for entanglement grouping
                self._by_time_line.setdefault((time, line), []).append(qid)
                self._q_event_index[(qubit, time, line)] = qid

        # 2) Add entanglement edges by (time,line) groups
        self._add_entanglement_edges(out)

        # (Future) 3) Add classical data/control deps if out.json includes classical actions
        # self._add_classical_deps_if_present(out)

        return self.g

    def _prev_on_wire(self, qubit: str, current: NodeId) -> Optional[NodeId]:
        # Find immediate predecessor based on stored last pointer before updating.
        # We store last pointer during _add_temporal_edge, so to get prev we need a lookup:
        # We'll approximate by scanning incoming temporal edges.
        inc = [e for e in self.g.incoming(current) if e.kind == "q_temporal"]
        if not inc:
            return None
        # There should be at most one temporal predecessor.
        return inc[0].src

    def _add_temporal_edge(self, qubit: str, nid: NodeId) -> None:
        prev = self._last_on_wire.get(qubit)
        if prev is not None:
            self.g.add_edge(prev, nid, "q_temporal")
        self._last_on_wire[qubit] = nid

    def _add_entanglement_edges(self, out: Dict[str, Any]) -> None:
        """
        Your current qslice.py entanglement rule:
          - group nodes at same (time,line)
          - connect ctrl <-> (targ or ctrl-gate-call or ctrl-gate-call style)
        We'll implement a robust version that uses the action labels present in out.json.
        """
        for (time, line), node_ids in self._by_time_line.items():
            if len(node_ids) < 2:
                continue

            # Partition nodes by action type
            def node_action(nid: NodeId) -> str:
                return self.g.nodes[nid].action or ""

            ctrls = [nid for nid in node_ids if node_action(nid) == "ctrl"]
            # Commonly targets appear as "targ" or "ctrl-gate-call" (as in your out.json)
            tgts = [nid for nid in node_ids if node_action(nid) in {"targ", "ctrl-gate-call"}]

            # If we can't classify cleanly, fall back to fully connecting within the group
            if not ctrls or not tgts:
                for u, v in itertools.combinations(node_ids, 2):
                    self.g.add_edge(u, v, "q_entanglement")
                    self.g.add_edge(v, u, "q_entanglement")
                continue

            for c in ctrls:
                for t in tgts:
                    self.g.add_edge(c, t, "q_entanglement")
                    self.g.add_edge(t, c, "q_entanglement")


def load_outjson(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


if __name__ == "__main__":
    out = load_outjson("out.json")
    builder = QPDGBuilder()
    g = builder.build_from_outjson(out)

    print(f"Nodes: {len(g.nodes)}")
    print(f"Edges: {len(g.edges)}")
    # Quick edge-type counts
    counts: Dict[str, int] = {}
    for e in g.edges:
        counts[e.kind] = counts.get(e.kind, 0) + 1
    print("Edge counts:", counts)

