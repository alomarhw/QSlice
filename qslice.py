#!/usr/bin/env python3
"""
Quantum slicer built on QStatic's out.json.

Pipeline:
  QStatic parser.py -> out.json -> this tool -> slice.json (+ optional qdg.json / qdg.dot)

QDG (Quantum Dependency Graph):
  Node:
    (qubit, time, line, action, gate, local_name)

  Edge types:
    - wire: temporal order on the same qubit (consecutive actions)
    - entanglement: coupling from multi-qubit operations at same (time,line),
                    modeled as ctrl <-> (targ | ctrl-gate-call)

Outputs:
  - slice.json: slice result + explanations
  - qdg.json  : explicit QDG export (optional)
  - qdg.dot   : Graphviz visualization export (optional)

Explanations (direction-aware keys):
  - reason_type: criterion | wire | entanglement | dependency | unknown
  - reason_direction: backward | forward
  - backward slicing:
      reason_next_toward_criterion: node or None
  - forward slicing:
      reason_prev_from_source: node or None

Optional:
  - --explain-paths adds reason_path (parent-chain) to each slice node.
"""

import argparse
import json
from collections import defaultdict, deque
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

Node = Tuple[str, int, int, str, str, str]  # (qubit, time, line, action, gate, local_name)
Edge = Tuple[Node, Node]


# ----------------------------
# Helpers
# ----------------------------

def load_out(path: str) -> Dict[str, Any]:
    with open(path, "r") as f:
        return json.load(f)


def is_logical_key(key: str) -> bool:
    # QStatic uses "$0"..."$n" for physical qubits and "_filename" (and other _) for metadata.
    return not key.startswith("$") and not key.startswith("_")


def normalize_actions(actions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return sorted(actions, key=lambda a: (a.get("time", -1), a.get("line", -1)))


def node_brief(n: Node) -> Dict[str, Any]:
    q, t, ln, act, gate, lname = n
    return {"qubit": q, "time": t, "line": ln, "action": act, "gate": gate, "local_name": lname}


def reconstruct_path(n: Node, parent: Dict[Node, Optional[Node]]) -> List[Dict[str, Any]]:
    """
    Follow parent pointers back to a start node and return the chain (as node briefs).
    First item is n, last is a start node.
    """
    chain: List[Dict[str, Any]] = []
    cur: Optional[Node] = n
    while cur is not None:
        chain.append(node_brief(cur))
        cur = parent.get(cur)
    return chain  # n -> ... -> start


# ----------------------------
# QDG construction + export
# ----------------------------

def build_qdg(out: Dict[str, Any]):
    """
    Build a typed Quantum Dependency Graph (QDG).

    Returns:
      nodes: List[Node]
      G_fwd: node -> set(node)
      G_bwd: node -> set(node)
      edge_type: (u,v) -> "wire" | "entanglement"
    """
    nodes: List[Node] = []
    by_qubit: Dict[str, List[Node]] = {}
    by_time_line: Dict[Tuple[int, int], List[Node]] = defaultdict(list)

    # Collect nodes
    for q, info in out.items():
        if not isinstance(info, dict):
            continue
        if not is_logical_key(q):
            continue

        actions = normalize_actions(info.get("actions", []))
        q_nodes: List[Node] = []

        for a in actions:
            t = a.get("time")
            line = a.get("line")
            act = a.get("action")
            gate = a.get("type", "") or a.get("gate", "") or ""
            lname = a.get("local_name", "") or ""

            # Need time, line, action to participate
            if t is None or line is None or act is None:
                continue

            node: Node = (q, int(t), int(line), str(act), str(gate), str(lname))
            q_nodes.append(node)
            nodes.append(node)
            by_time_line[(int(t), int(line))].append(node)

        by_qubit[q] = q_nodes

    G_fwd: Dict[Node, Set[Node]] = defaultdict(set)
    G_bwd: Dict[Node, Set[Node]] = defaultdict(set)
    edge_type: Dict[Edge, str] = {}

    def add_edge(u: Node, v: Node, etype: str) -> None:
        G_fwd[u].add(v)
        G_bwd[v].add(u)
        edge_type[(u, v)] = etype

    # 1) wire edges: consecutive actions on same qubit
    for _q, q_nodes in by_qubit.items():
        for u, v in zip(q_nodes, q_nodes[1:]):
            add_edge(u, v, "wire")

    # 2) entanglement edges: ctrl <-> (targ | ctrl-gate-call) at same time+line
    for (_t, _line), group in by_time_line.items():
        ctrls = [n for n in group if n[3] == "ctrl"]
        targets = [n for n in group if n[3] in ("targ", "ctrl-gate-call")]
        if ctrls and targets:
            for c in ctrls:
                for g in targets:
                    add_edge(c, g, "entanglement")
                    add_edge(g, c, "entanglement")  # symmetric coupling

    return nodes, G_fwd, G_bwd, edge_type


def export_qdg_json(nodes: List[Node],
                    G_fwd: Dict[Node, Set[Node]],
                    edge_type: Dict[Edge, str],
                    path: str) -> None:
    node_ids = {n: i for i, n in enumerate(nodes)}
    out = {"nodes": [], "edges": []}

    for n, i in node_ids.items():
        out["nodes"].append({"id": i, **node_brief(n)})

    for u, targets in G_fwd.items():
        for v in targets:
            out["edges"].append({
                "from": node_ids[u],
                "to": node_ids[v],
                "type": edge_type.get((u, v), "dependency"),
            })

    with open(path, "w") as f:
        json.dump(out, f, indent=2)


def export_qdg_dot(nodes: List[Node],
                   G_fwd: Dict[Node, Set[Node]],
                   edge_type: Dict[Edge, str],
                   slice_nodes: Optional[Set[Node]],
                   path: str,
                   max_nodes: Optional[int]) -> None:
    """
    Export a Graphviz DOT file clustered by qubit (circuit-like).

    Visual conventions:
      - wire edges: solid
      - entanglement edges: dashed + thicker
      - slice nodes: filled light gray
      - node labels: (t, line) + action (+ gate)

    Layout hints:
      - rankdir=LR (time left-to-right)
      - per-time rank constraints to align multi-qubit ops
      - invisible edges within each qubit to keep temporal order
    """
    slice_nodes = slice_nodes or set()

    # Stable ordering; optionally limit for readability
    ordered = sorted(nodes, key=lambda x: (x[1], x[2], x[0], x[3]))
    if max_nodes is not None:
        ordered = ordered[: max_nodes]

    included = set(ordered)

    # Group nodes by qubit and by time
    by_qubit: Dict[str, List[Node]] = defaultdict(list)
    by_time: Dict[int, List[Node]] = defaultdict(list)
    for n in ordered:
        by_qubit[n[0]].append(n)
        by_time[n[1]].append(n)

    # Stable qubit ordering: try to parse p[12] -> 12
    def qubit_key(q: str):
        try:
            if "[" in q and q.endswith("]"):
                return (0, int(q.split("[", 1)[1].rstrip("]")))
        except Exception:
            pass
        return (1, q)

    qubits = sorted(by_qubit.keys(), key=qubit_key)

    # Assign ids
    node_ids = {n: i for i, n in enumerate(ordered)}

    # Compact node label (cluster already shows qubit)
    def label(n: Node) -> str:
        _q, t, ln, act, gate, _lname = n
        gate_part = f" {gate}" if gate else ""
        #return f"(t={t}, l={ln})\\n{act}{gate_part}"
        return f"{act}{(' ' + gate) if gate else ''}"


    lines: List[str] = []
    lines.append("digraph QDG {")
    lines.append("  rankdir=LR;")
    lines.append("  compound=true;")
    lines.append('  node [shape=box, fontsize=10];')
    lines.append('  graph [fontsize=12];')

        # ---- Legend (static, single instance) ----
    #lines.append('  subgraph cluster_legend {')
    #lines.append('    label="Legend";')
    #lines.append('    fontsize=11;')
    #lines.append('    style="rounded,dashed";')
    #lines.append('    color="gray50";')

    #lines.append('    key_wire [label="Wire dependency", shape=plaintext];')
    #lines.append('    key_ent  [label="Entanglement dependency", shape=plaintext];')
    #lines.append('    key_slice [label="Slice node", shape=plaintext];')

    #lines.append('    wire_edge [shape=plaintext, label=""];')
    #lines.append('    ent_edge  [shape=plaintext, label=""];')
    #lines.append('    slice_node [shape=box, style="filled", fillcolor="lightgray", label=""];')

    #lines.append('    key_wire -> wire_edge [style="solid"];')
    #lines.append('    key_ent  -> ent_edge  [style="dashed", penwidth=2];')
    #lines.append('    key_slice -> slice_node [style="invis"];')

    #lines.append('  }')


    # Clusters per qubit
    for qi, qname in enumerate(qubits):
        cluster_name = f"cluster_q{qi}"
        lines.append(f"  subgraph {cluster_name} {{")
        lines.append('    style="rounded";')
        lines.append(f'    label="{qname}";')

        # Nodes
        qnodes_sorted = sorted(by_qubit[qname], key=lambda x: (x[1], x[2], x[3]))
        for n in qnodes_sorted:
            i = node_ids[n]
            if n in slice_nodes:
                lines.append(f'    n{i} [style="filled", fillcolor="lightgray", label="{label(n)}"];')
            else:
                lines.append(f'    n{i} [style="solid", label="{label(n)}"];')

        # Invisible edges to enforce time order within qubit
        for u, v in zip(qnodes_sorted, qnodes_sorted[1:]):
            lines.append(f'    n{node_ids[u]} -> n{node_ids[v]} [style=invis, weight=10];')

        lines.append("  }")


    # Real edges (no labels to reduce clutter)
    for u, targets in G_fwd.items():
        if u not in included:
            continue
        for v in targets:
            if v not in included:
                continue

            et = edge_type.get((u, v), "dependency")
            if et == "entanglement":
                lines.append(f'  n{node_ids[u]} -> n{node_ids[v]} [style="dashed", penwidth=2];')
            else:
                lines.append(f'  n{node_ids[u]} -> n{node_ids[v]} [style="solid"];')

    lines.append("}")

    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")



# ----------------------------
# Criterion + slicing + explanations
# ----------------------------

def find_criterion_nodes(nodes: Iterable[Node],
                         qubit: Optional[str],
                         line: Optional[int],
                         time: Optional[int],
                         action: Optional[str],
                         gate: Optional[str]) -> List[Node]:
    hits: List[Node] = []
    for n in nodes:
        q, t, ln, act, g, _lname = n
        if qubit is not None and q != qubit:
            continue
        if line is not None and ln != line:
            continue
        if time is not None and t != time:
            continue
        if action is not None and act != action:
            continue
        if gate is not None and g != gate:
            continue
        hits.append(n)
    return hits


def bfs_with_explanations(starts: List[Node],
                          adjacency: Dict[Node, Set[Node]],
                          edge_type: Dict[Edge, str],
                          mode: str) -> Tuple[Set[Node], Dict[Node, Dict[str, Any]], Dict[Node, Optional[Node]]]:
    """
    BFS reachability + direction-aware explanations.

    mode:
      - "backward": adjacency must be G_bwd (reverse edges)
      - "forward" : adjacency must be G_fwd (forward edges)
    """
    if mode not in ("backward", "forward"):
        raise ValueError("mode must be 'backward' or 'forward'")

    seen: Set[Node] = set(starts)
    dq = deque(starts)

    parent: Dict[Node, Optional[Node]] = {s: None for s in starts}
    explanation: Dict[Node, Dict[str, Any]] = {}

    # Initialize criterion nodes
    for s in starts:
        if mode == "backward":
            explanation[s] = {
                "reason_type": "criterion",
                "reason_direction": "backward",
                "reason_next_toward_criterion": None,
            }
        else:
            explanation[s] = {
                "reason_type": "criterion",
                "reason_direction": "forward",
                "reason_prev_from_source": None,
            }

    while dq:
        u = dq.popleft()
        for v in adjacency.get(u, ()):
            if v in seen:
                continue
            seen.add(v)
            dq.append(v)
            parent[v] = u

            if mode == "forward":
                # Traversal is u -> v in G_fwd
                et = edge_type.get((u, v), "dependency")
                explanation[v] = {
                    "reason_type": et,
                    "reason_direction": "forward",
                    "reason_prev_from_source": node_brief(u),
                }
            else:
                # Traversal is u -> v in G_bwd, which corresponds to original forward edge (v -> u)
                et = edge_type.get((v, u), "dependency")
                explanation[v] = {
                    "reason_type": et,
                    "reason_direction": "backward",
                    "reason_next_toward_criterion": node_brief(u),
                }

    return seen, explanation, parent


def format_slice(nodes_set: Set[Node],
                 explanation: Dict[Node, Dict[str, Any]],
                 parent: Dict[Node, Optional[Node]],
                 include_paths: bool) -> Dict[str, Any]:
    items: List[Dict[str, Any]] = []

    for n in sorted(nodes_set, key=lambda x: (x[1], x[2], x[0], x[3])):
        entry = node_brief(n)

        ex = explanation.get(n, {"reason_type": "unknown", "reason_direction": None})
        entry.update(ex)

        if include_paths:
            entry["reason_path"] = reconstruct_path(n, parent)

        items.append(entry)

    return {
        "slice_qubits": sorted({it["qubit"] for it in items}),
        "slice_times": sorted({it["time"] for it in items}),
        "slice_lines": sorted({it["line"] for it in items}),
        "slice_actions": items,
    }


# ----------------------------
# CLI
# ----------------------------

def main():
    ap = argparse.ArgumentParser(description="Quantum slicer on top of QStatic out.json (QDG + explanations + DOT)")
    ap.add_argument("--in", dest="inp", default="out.json", help="Path to out.json (default: out.json)")
    ap.add_argument("--out", dest="outp", default="slice.json", help="Output slice file (default: slice.json)")

    ap.add_argument("--direction", choices=["backward", "forward"], default="backward", help="Slice direction")
    ap.add_argument("--qubit", default=None, help='Criterion qubit, e.g., "p[1]"')
    ap.add_argument("--line", type=int, default=None, help="Criterion line number (optional)")
    ap.add_argument("--time", type=int, default=None, help="Criterion time step (optional)")
    ap.add_argument("--action", default=None, help='Criterion action (optional), e.g., "ctrl"')
    ap.add_argument("--gate", default=None, help='Criterion gate type (optional), e.g., "cx" or "h"')

    ap.add_argument("--export-qdg", action="store_true", help="Export QDG as qdg.json (or --qdg-out)")
    ap.add_argument("--qdg-out", default="qdg.json", help="Path for QDG JSON export (default: qdg.json)")

    ap.add_argument("--export-dot", action="store_true", help="Export QDG as Graphviz DOT (qdg.dot or --dot-out)")
    ap.add_argument("--dot-out", default="qdg.dot", help="Path for DOT export (default: qdg.dot)")
    ap.add_argument("--dot-max-nodes", type=int, default=None, help="Limit nodes in DOT output (optional)")
    ap.add_argument("--dot-highlight-slice", action="store_true",
                    help="Highlight current slice nodes in the DOT output")

    ap.add_argument("--explain-paths", action="store_true",
                    help="Include a full parent-chain path per node (can make slice.json larger)")

    args = ap.parse_args()

    out = load_out(args.inp)
    nodes, G_fwd, G_bwd, edge_type = build_qdg(out)

    if args.export_qdg:
        export_qdg_json(nodes, G_fwd, edge_type, args.qdg_out)
        print(f"Wrote {args.qdg_out}")

    # Find criterion nodes
    crit = find_criterion_nodes(
        nodes,
        qubit=args.qubit,
        line=args.line,
        time=args.time,
        action=args.action,
        gate=args.gate,
    )
    if not crit:
        raise SystemExit(
            f"No criterion nodes matched. Try relaxing filters. "
            f"(qubit={args.qubit}, line={args.line}, time={args.time}, action={args.action}, gate={args.gate})"
        )

    # Slice + explanations
    if args.direction == "backward":
        S, explanation, parent = bfs_with_explanations(crit, G_bwd, edge_type, mode="backward")
    else:
        S, explanation, parent = bfs_with_explanations(crit, G_fwd, edge_type, mode="forward")

    # DOT export (optional)
    if args.export_dot:
        highlight = S if args.dot_highlight_slice else None
        export_qdg_dot(
            nodes=nodes,
            G_fwd=G_fwd,
            edge_type=edge_type,
            slice_nodes=highlight,
            path=args.dot_out,
            max_nodes=args.dot_max_nodes,
        )
        print(f"Wrote {args.dot_out}")

    # Slice JSON output
    result = format_slice(S, explanation, parent, include_paths=args.explain_paths)
    result["criterion"] = {
        "qubit": args.qubit,
        "line": args.line,
        "time": args.time,
        "action": args.action,
        "gate": args.gate,
        "direction": args.direction,
        "matched_nodes": [node_brief(n) for n in sorted(crit, key=lambda x: (x[1], x[2], x[0]))],
    }

    with open(args.outp, "w") as f:
        json.dump(result, f, indent=2)

    print(f"Wrote {args.outp}")
    print("Criterion matched:", len(crit), "node(s)")
    print("Slice lines:", result["slice_lines"])
    print("Slice actions:", len(result["slice_actions"]))


if __name__ == "__main__":
    main()
