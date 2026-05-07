#!/usr/bin/env python3
"""
Quantum slicer built on QStatic's out.json.

QSlice constructs the statement-level Quantum Dependency Graph (QDG)
described by the research paper:

  * nodes are program statements, not per-qubit action fragments;
  * edges are semantic dependencies: UED, ED, MD, and CD; and
  * the default slice is the qubit-centric fixed-point of semantic
    predecessors starting from Γ(q), the statements that directly operate on
    or measure the target qubit.

The parser still emits per-qubit action records.  This tool groups records that
share the same (time, line) into a single statement node before extracting
semantic dependencies.
"""

from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

Node = int
Edge = Tuple[Node, Node]
UNITARY_ACTIONS = {"gate-call", "ctrl", "negctrl", "ctrl-gate-call", "targ"}
IDENT_RE = re.compile(r"[A-Za-z_]\w*(?:\[\d+\])?")


@dataclass
class Statement:
    """A statement-level QDG node reconstructed from QStatic actions."""

    id: Node
    time: int
    line: int
    actions: List[Dict[str, Any]] = field(default_factory=list)
    qubits: Set[str] = field(default_factory=set)
    action: str = "unknown"
    gate: str = ""
    stores: Set[str] = field(default_factory=set)
    uses: Set[str] = field(default_factory=set)
    conditions: Set[str] = field(default_factory=set)
    local_names: Set[str] = field(default_factory=set)

    @property
    def is_unitary(self) -> bool:
        return self.action in {"unitary", "guarded-unitary"}

    @property
    def is_measure(self) -> bool:
        return self.action == "measure"

    @property
    def is_reset(self) -> bool:
        return self.action == "reset"

    @property
    def is_terminator(self) -> bool:
        return self.is_measure or self.is_reset

    @property
    def is_multi_qubit_unitary(self) -> bool:
        return self.is_unitary and len(self.qubits) > 1


# ----------------------------
# Helpers
# ----------------------------


def load_out(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def is_logical_key(key: str) -> bool:
    # QStatic uses "$0"..."$n" for physical qubits and "_filename" for metadata.
    return not key.startswith("$") and not key.startswith("_")


def normalize_actions(actions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return sorted(actions, key=lambda a: (a.get("time", -1), a.get("line", -1), a.get("action", "")))


def extract_identifiers(expr: str) -> Set[str]:
    """Extract simple variable/array identifiers from parser metadata."""
    if not expr:
        return set()
    keywords = {"if", "then", "else", "measure", "true", "false", "and", "or", "not"}
    return {tok for tok in IDENT_RE.findall(expr) if tok not in keywords and not tok.isdigit()}


def action_uses(a: Dict[str, Any]) -> Set[str]:
    uses: Set[str] = set()
    for key in ("if", "condition", "uses", "expr"):
        value = a.get(key)
        if isinstance(value, str):
            uses.update(extract_identifiers(value))
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, str):
                    uses.update(extract_identifiers(item))
    return uses


def statement_brief(stmt: Statement) -> Dict[str, Any]:
    return {
        "id": stmt.id,
        "time": stmt.time,
        "line": stmt.line,
        "action": stmt.action,
        "gate": stmt.gate,
        "qubits": sorted(stmt.qubits),
        "stores": sorted(stmt.stores),
        "uses": sorted(stmt.uses),
        "conditions": sorted(stmt.conditions),
        "local_names": sorted(stmt.local_names),
    }


def reconstruct_path(n: Node, parent: Dict[Node, Optional[Node]], by_id: Dict[Node, Statement]) -> List[Dict[str, Any]]:
    chain: List[Dict[str, Any]] = []
    cur: Optional[Node] = n
    while cur is not None:
        chain.append(statement_brief(by_id[cur]))
        cur = parent.get(cur)
    return chain


# ----------------------------
# QDG construction + export
# ----------------------------


def collect_statements(out: Dict[str, Any]) -> List[Statement]:
    """Group per-qubit parser actions into statement-level QDG nodes."""
    grouped: Dict[Tuple[int, int], List[Tuple[str, Dict[str, Any]]]] = defaultdict(list)

    for qubit, info in out.items():
        if not isinstance(info, dict) or not is_logical_key(qubit):
            continue
        for action in normalize_actions(info.get("actions", [])):
            time = action.get("time")
            line = action.get("line")
            if time is None or line is None or action.get("action") is None:
                continue
            grouped[(int(time), int(line))].append((qubit, dict(action)))

    statements: List[Statement] = []
    for sid, ((time, line), entries) in enumerate(sorted(grouped.items())):
        stmt = Statement(id=sid, time=time, line=line)
        action_kinds = {str(a.get("action", "")) for _q, a in entries}
        gates = [str(a.get("type") or a.get("gate") or "") for _q, a in entries if a.get("type") or a.get("gate")]

        for qubit, action in entries:
            stmt.qubits.add(qubit)
            stmt.actions.append(action)
            if action.get("store"):
                stmt.stores.add(str(action["store"]).strip())
            if action.get("local_name"):
                stmt.local_names.add(str(action["local_name"]))
            if action.get("if"):
                stmt.conditions.add(str(action["if"]))
            stmt.uses.update(action_uses(action))

        if "measure" in action_kinds:
            stmt.action = "measure"
        elif "reset" in action_kinds:
            stmt.action = "reset"
        elif action_kinds & UNITARY_ACTIONS:
            stmt.action = "guarded-unitary" if stmt.conditions else "unitary"
        else:
            stmt.action = ",".join(sorted(action_kinds)) or "unknown"

        # For controlled operations the useful gate name is usually on the target action.
        stmt.gate = next((g for g in gates if g), "")
        statements.append(stmt)

    # Optional extension point for classical statements in hand-authored out.json.
    # Shape: "_classical": [{"time": 7, "line": 15, "action": "classical", "store": "c[2]", "expr": "c[0] ^ c[1]"}]
    for raw in sorted(out.get("_classical", []), key=lambda a: (a.get("time", 10**9), a.get("line", 10**9))):
        time = int(raw.get("time", len(statements)))
        line = int(raw.get("line", time))
        stmt = Statement(id=len(statements), time=time, line=line, action=str(raw.get("action", "classical")))
        stmt.actions.append(dict(raw))
        if raw.get("store"):
            stmt.stores.add(str(raw["store"]).strip())
        if raw.get("stores"):
            stmt.stores.update(str(s).strip() for s in raw["stores"])
        stmt.uses.update(action_uses(raw))
        if raw.get("if"):
            stmt.conditions.add(str(raw["if"]))
        statements.append(stmt)

    return sorted(statements, key=lambda s: (s.time, s.line, s.id))


def build_qdg(out: Dict[str, Any]):
    """
    Build the paper-aligned statement-level Quantum Dependency Graph.

    Returns:
      nodes: List[Statement]
      G_fwd: node id -> set(node id)
      G_bwd: node id -> set(node id)
      edge_type: (u, v) -> "ued" | "ed" | "md" | "cd"
    """
    nodes = collect_statements(out)
    by_id = {s.id: s for s in nodes}
    G_fwd: Dict[Node, Set[Node]] = defaultdict(set)
    G_bwd: Dict[Node, Set[Node]] = defaultdict(set)
    edge_type: Dict[Edge, str] = {}
    edge_meta: Dict[Edge, Set[str]] = defaultdict(set)

    def add_edge(u: Statement, v: Statement, etype: str, label: str = "") -> None:
        if u.id == v.id:
            return
        G_fwd[u.id].add(v.id)
        G_bwd[v.id].add(u.id)
        # Keep a stable label if duplicate semantic routes are discovered.
        if (u.id, v.id) not in edge_type:
            edge_type[(u.id, v.id)] = etype
        elif edge_type[(u.id, v.id)] != etype:
            edge_type[(u.id, v.id)] = "+".join(sorted(set(edge_type[(u.id, v.id)].split("+")) | {etype}))
        if label:
            edge_meta[(u.id, v.id)].add(label)

    def quantum_state_contributors(stmt_id: Node) -> Set[Node]:
        """Return unitary/entanglement predecessors that contribute to a unitary."""
        contributors: Set[Node] = set()
        work = deque([stmt_id])
        while work:
            cur = work.popleft()
            for pred in G_bwd.get(cur, set()):
                kinds = set(edge_type.get((pred, cur), "").split("+"))
                if not (kinds & {"ued", "ed"}):
                    continue
                if pred in contributors:
                    continue
                contributors.add(pred)
                work.append(pred)
        return contributors

    # UED and MD: track all uninterrupted unitary contributors per qubit.
    active_unitaries: Dict[str, List[Statement]] = defaultdict(list)
    for stmt in nodes:
        for q in sorted(stmt.qubits):
            if stmt.is_unitary:
                for prev in active_unitaries[q]:
                    add_edge(prev, stmt, "ued", q)
                active_unitaries[q].append(stmt)
            elif stmt.is_measure:
                # A measurement outcome depends on prior unitary evolution of the
                # measured qubit and on the quantum contributors to those unitaries.
                measurement_contributors: Set[Node] = set()
                for prev in active_unitaries[q]:
                    measurement_contributors.add(prev.id)
                    measurement_contributors.update(quantum_state_contributors(prev.id))
                for pred_id in sorted(measurement_contributors):
                    add_edge(by_id[pred_id], stmt, "md", q)
                active_unitaries[q] = []
            elif stmt.is_reset:
                active_unitaries[q] = []

    # ED: an entangling statement remains semantically relevant to later accesses
    # of any qubit in its entangled set until measurement/reset terminates that set.
    active_entanglers: List[Tuple[Statement, Set[str]]] = []
    for stmt in nodes:
        remaining: List[Tuple[Statement, Set[str]]] = []
        for entangler, qset in active_entanglers:
            touched = stmt.qubits & qset
            if touched:
                add_edge(entangler, stmt, "ed", ",".join(sorted(qset)))
            if not (stmt.is_terminator and touched):
                remaining.append((entangler, qset))
        active_entanglers = remaining

        if stmt.is_multi_qubit_unitary:
            active_entanglers.append((stmt, set(stmt.qubits)))

    # CD: classical stores influence later statements that use those values.
    last_defs: Dict[str, List[Statement]] = defaultdict(list)
    for stmt in nodes:
        for used in sorted(stmt.uses):
            for definition in last_defs.get(used, []):
                add_edge(definition, stmt, "cd", used)
        for store in sorted(stmt.stores):
            last_defs[store].append(stmt)

    return nodes, G_fwd, G_bwd, edge_type, edge_meta


def export_qdg_json(nodes: List[Statement],
                    G_fwd: Dict[Node, Set[Node]],
                    edge_type: Dict[Edge, str],
                    edge_meta: Dict[Edge, Set[str]],
                    path: str) -> None:
    out = {"nodes": [], "edges": []}

    for stmt in nodes:
        out["nodes"].append(statement_brief(stmt))

    for u, targets in sorted(G_fwd.items()):
        for v in sorted(targets):
            out["edges"].append({
                "from": u,
                "to": v,
                "type": edge_type.get((u, v), "dependency"),
                "labels": sorted(edge_meta.get((u, v), set())),
            })

    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2)


def export_qdg_dot(nodes: List[Statement],
                   G_fwd: Dict[Node, Set[Node]],
                   edge_type: Dict[Edge, str],
                   slice_nodes: Optional[Set[Node]],
                   path: str,
                   max_nodes: Optional[int]) -> None:
    """Export a Graphviz DOT file for the statement-level QDG."""
    slice_nodes = slice_nodes or set()
    ordered = sorted(nodes, key=lambda s: (s.time, s.line, s.id))
    if max_nodes is not None:
        ordered = ordered[:max_nodes]
    included = {s.id for s in ordered}

    def label(stmt: Statement) -> str:
        qubits = ",".join(sorted(stmt.qubits)) or "classical"
        gate = f" {stmt.gate}" if stmt.gate else ""
        store = f" -> {','.join(sorted(stmt.stores))}" if stmt.stores else ""
        return f"v{stmt.id}: l{stmt.line}\\n{stmt.action}{gate}\\n{qubits}{store}"

    edge_styles = {
        "ued": 'color="black", style="solid"',
        "ed": 'color="blue", style="dashed", penwidth=2',
        "md": 'color="purple", style="solid"',
        "cd": 'color="darkgreen", style="dotted", penwidth=2',
    }

    lines = [
        "digraph QDG {",
        "  rankdir=LR;",
        '  node [shape=box, fontsize=10];',
    ]
    for stmt in ordered:
        fill = ', style="filled", fillcolor="lightgray"' if stmt.id in slice_nodes else ""
        lines.append(f'  n{stmt.id} [label="{label(stmt)}"{fill}];')

    for u, targets in sorted(G_fwd.items()):
        if u not in included:
            continue
        for v in sorted(targets):
            if v not in included:
                continue
            et = edge_type.get((u, v), "dependency")
            primary = et.split("+")[0]
            style = edge_styles.get(primary, 'style="solid"')
            lines.append(f'  n{u} -> n{v} [label="{et}", {style}];')

    lines.append("}")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


# ----------------------------
# Criterion + slicing + explanations
# ----------------------------


def find_criterion_nodes(nodes: Iterable[Statement],
                         qubit: Optional[str],
                         line: Optional[int],
                         time: Optional[int],
                         action: Optional[str],
                         gate: Optional[str]) -> List[Node]:
    hits: List[Node] = []
    for stmt in nodes:
        if qubit is not None and qubit not in stmt.qubits:
            continue
        if line is not None and stmt.line != line:
            continue
        if time is not None and stmt.time != time:
            continue
        if action is not None and stmt.action != action:
            continue
        if gate is not None and stmt.gate != gate:
            continue
        hits.append(stmt.id)
    return hits


def quantum_slice_with_explanations(starts: List[Node],
                                    G_bwd: Dict[Node, Set[Node]],
                                    edge_type: Dict[Edge, str],
                                    by_id: Dict[Node, Statement]) -> Tuple[Set[Node], Dict[Node, Dict[str, Any]], Dict[Node, Optional[Node]]]:
    """Algorithm 1: fixed-point over semantic predecessors from Γ(q)."""
    seen: Set[Node] = set(starts)
    dq = deque(starts)
    parent: Dict[Node, Optional[Node]] = {s: None for s in starts}
    explanation: Dict[Node, Dict[str, Any]] = {
        s: {"reason_type": "criterion", "reason_direction": "criterion", "reason_next_toward_criterion": None}
        for s in starts
    }

    while dq:
        v = dq.popleft()
        for u in sorted(G_bwd.get(v, set())):
            if u in seen:
                continue
            seen.add(u)
            dq.append(u)
            parent[u] = v
            explanation[u] = {
                "reason_type": edge_type.get((u, v), "dependency"),
                "reason_direction": "semantic-predecessor",
                "reason_next_toward_criterion": statement_brief(by_id[v]),
            }
    return seen, explanation, parent


def bfs_with_explanations(starts: List[Node],
                          adjacency: Dict[Node, Set[Node]],
                          edge_type: Dict[Edge, str],
                          mode: str,
                          by_id: Dict[Node, Statement]) -> Tuple[Set[Node], Dict[Node, Dict[str, Any]], Dict[Node, Optional[Node]]]:
    """Legacy directed traversal retained for comparison/debugging."""
    seen: Set[Node] = set(starts)
    dq = deque(starts)
    parent: Dict[Node, Optional[Node]] = {s: None for s in starts}
    explanation: Dict[Node, Dict[str, Any]] = {
        s: {"reason_type": "criterion", "reason_direction": mode, "reason_next_toward_criterion": None}
        for s in starts
    }

    while dq:
        u = dq.popleft()
        for v in sorted(adjacency.get(u, set())):
            if v in seen:
                continue
            seen.add(v)
            dq.append(v)
            parent[v] = u
            edge = (u, v) if mode == "forward" else (v, u)
            explanation[v] = {
                "reason_type": edge_type.get(edge, "dependency"),
                "reason_direction": mode,
                "reason_next_toward_criterion": statement_brief(by_id[u]) if mode == "backward" else None,
                "reason_prev_from_source": statement_brief(by_id[u]) if mode == "forward" else None,
            }
    return seen, explanation, parent


def format_slice(nodes_set: Set[Node],
                 nodes: List[Statement],
                 explanation: Dict[Node, Dict[str, Any]],
                 parent: Dict[Node, Optional[Node]],
                 include_paths: bool) -> Dict[str, Any]:
    by_id = {s.id: s for s in nodes}
    items: List[Dict[str, Any]] = []

    for nid in sorted(nodes_set, key=lambda i: (by_id[i].time, by_id[i].line, by_id[i].id)):
        entry = statement_brief(by_id[nid])
        entry.update(explanation.get(nid, {"reason_type": "unknown", "reason_direction": None}))
        if include_paths:
            entry["reason_path"] = reconstruct_path(nid, parent, by_id)
        items.append(entry)

    return {
        "slice_qubits": sorted({q for it in items for q in it["qubits"]}),
        "slice_times": sorted({it["time"] for it in items}),
        "slice_lines": sorted({it["line"] for it in items}),
        "slice_actions": items,
        "slice_statements": items,
    }


# ----------------------------
# CLI
# ----------------------------


def main() -> None:
    ap = argparse.ArgumentParser(description="Statement-level quantum slicer on top of QStatic out.json")
    ap.add_argument("--in", dest="inp", default="out.json", help="Path to out.json (default: out.json)")
    ap.add_argument("--out", dest="outp", default="slice.json", help="Output slice file (default: slice.json)")

    ap.add_argument("--mode", choices=["quantum", "backward", "forward"], default="quantum",
                    help="quantum uses the paper's qubit-centric semantic predecessor fixed-point; backward/forward are legacy directed traversals")
    ap.add_argument("--direction", choices=["backward", "forward"], default=None,
                    help="Deprecated alias for --mode backward/forward")
    ap.add_argument("--qubit", default=None, help='Target/criterion qubit, e.g., "q[1]"')
    ap.add_argument("--line", type=int, default=None, help="Criterion line number (optional)")
    ap.add_argument("--time", type=int, default=None, help="Criterion time step (optional)")
    ap.add_argument("--action", default=None, help='Criterion statement action, e.g., "unitary" or "measure"')
    ap.add_argument("--gate", default=None, help='Criterion gate type, e.g., "cx" or "h"')

    ap.add_argument("--export-qdg", action="store_true", help="Export QDG as qdg.json (or --qdg-out)")
    ap.add_argument("--qdg-out", default="qdg.json", help="Path for QDG JSON export (default: qdg.json)")

    ap.add_argument("--export-dot", action="store_true", help="Export QDG as Graphviz DOT (qdg.dot or --dot-out)")
    ap.add_argument("--dot-out", default="qdg.dot", help="Path for DOT export (default: qdg.dot)")
    ap.add_argument("--dot-max-nodes", type=int, default=None, help="Limit nodes in DOT output (optional)")
    ap.add_argument("--dot-highlight-slice", action="store_true", help="Highlight current slice nodes in DOT output")
    ap.add_argument("--explain-paths", action="store_true", help="Include parent-chain paths per statement")

    args = ap.parse_args()
    mode = args.direction or args.mode

    out = load_out(args.inp)
    nodes, G_fwd, G_bwd, edge_type, edge_meta = build_qdg(out)
    by_id = {s.id: s for s in nodes}

    if args.export_qdg:
        export_qdg_json(nodes, G_fwd, edge_type, edge_meta, args.qdg_out)
        print(f"Wrote {args.qdg_out}")

    crit = find_criterion_nodes(nodes, args.qubit, args.line, args.time, args.action, args.gate)
    if not crit:
        raise SystemExit(
            f"No criterion statements matched. Try relaxing filters. "
            f"(qubit={args.qubit}, line={args.line}, time={args.time}, action={args.action}, gate={args.gate})"
        )

    if mode == "quantum":
        S, explanation, parent = quantum_slice_with_explanations(crit, G_bwd, edge_type, by_id)
    elif mode == "backward":
        S, explanation, parent = bfs_with_explanations(crit, G_bwd, edge_type, "backward", by_id)
    else:
        S, explanation, parent = bfs_with_explanations(crit, G_fwd, edge_type, "forward", by_id)

    if args.export_dot:
        highlight = S if args.dot_highlight_slice else None
        export_qdg_dot(nodes, G_fwd, edge_type, highlight, args.dot_out, args.dot_max_nodes)
        print(f"Wrote {args.dot_out}")

    result = format_slice(S, nodes, explanation, parent, include_paths=args.explain_paths)
    result["criterion"] = {
        "qubit": args.qubit,
        "line": args.line,
        "time": args.time,
        "action": args.action,
        "gate": args.gate,
        "mode": mode,
        "matched_nodes": [statement_brief(by_id[n]) for n in sorted(crit)],
    }

    with open(args.outp, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)

    print(f"Wrote {args.outp}")
    print("Criterion matched:", len(crit), "statement(s)")
    print("Slice lines:", result["slice_lines"])
    print("Slice statements:", len(result["slice_statements"]))


if __name__ == "__main__":
    main()
