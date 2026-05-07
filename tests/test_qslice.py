import unittest

from qslice import build_qdg, find_criterion_nodes, quantum_slice_with_explanations


def action(kind, time, line, **extra):
    data = {"action": kind, "time": time, "line": line}
    data.update(extra)
    return data


RUNNING_EXAMPLE = {
    "q[0]": {
        "actions": [
            action("gate-call", 0, 7, type="h", local_name="q[0]"),
            action("ctrl", 1, 8, local_name="q[0]"),
            action("measure", 2, 9, store="c[0]"),
        ]
    },
    "q[1]": {
        "actions": [
            action("ctrl-gate-call", 1, 8, type="cx", ctrl="q[0]", local_name="q[1]"),
            action("measure", 3, 10, store="c[1]"),
        ]
    },
    "q[2]": {
        "actions": [
            action("gate-call", 4, 11, type="rz", local_name="q[2]"),
            action("gate-call", 5, 13, type="rz", local_name="q[2]", **{"if": "c[0] == 1"}),
        ]
    },
    "_classical": [
        {"action": "classical", "time": 6, "line": 15, "store": "c[2]", "expr": "c[0] ^ c[1]"}
    ],
}


class StatementLevelQDGTests(unittest.TestCase):
    def setUp(self):
        self.nodes, self.g_fwd, self.g_bwd, self.edge_type, self.edge_meta = build_qdg(RUNNING_EXAMPLE)
        self.by_id = {stmt.id: stmt for stmt in self.nodes}

    def edge_lines(self, etype):
        lines = set()
        for (u, v), kind in self.edge_type.items():
            if etype in kind.split("+"):
                lines.add((self.by_id[u].line, self.by_id[v].line))
        return lines

    def slice_lines(self, qubit):
        starts = find_criterion_nodes(self.nodes, qubit, None, None, None, None)
        result, _explanation, _parent = quantum_slice_with_explanations(
            starts, self.g_bwd, self.edge_type, self.by_id
        )
        return {self.by_id[n].line for n in result}

    def test_controlled_gate_is_one_statement_node(self):
        cnot_nodes = [stmt for stmt in self.nodes if stmt.line == 8]
        self.assertEqual(len(cnot_nodes), 1)
        self.assertEqual(cnot_nodes[0].gate, "cx")
        self.assertEqual(cnot_nodes[0].qubits, {"q[0]", "q[1]"})

    def test_qdg_contains_paper_dependency_types(self):
        self.assertIn((7, 8), self.edge_lines("ued"))
        self.assertIn((8, 9), self.edge_lines("ed"))
        self.assertIn((7, 9), self.edge_lines("md"))
        self.assertIn((8, 10), self.edge_lines("md"))
        self.assertIn((9, 13), self.edge_lines("cd"))
        self.assertIn((9, 15), self.edge_lines("cd"))
        self.assertIn((10, 15), self.edge_lines("cd"))

    def test_running_example_qubit_slices_match_paper(self):
        self.assertEqual(self.slice_lines("q[0]"), {7, 8, 9})
        self.assertEqual(self.slice_lines("q[1]"), {7, 8, 10})
        self.assertEqual(self.slice_lines("q[2]"), {7, 8, 9, 11, 13})

    def test_measurement_terminates_unitary_evolution(self):
        out = {
            "q": {
                "actions": [
                    action("gate-call", 0, 1, type="h"),
                    action("measure", 1, 2, store="c"),
                    action("gate-call", 2, 3, type="x"),
                ]
            }
        }
        nodes, _gf, _gb, edge_type, _em = build_qdg(out)
        by_id = {stmt.id: stmt for stmt in nodes}
        ued_lines = {
            (by_id[u].line, by_id[v].line)
            for (u, v), kind in edge_type.items()
            if "ued" in kind.split("+")
        }
        self.assertNotIn((1, 3), ued_lines)


if __name__ == "__main__":
    unittest.main()
