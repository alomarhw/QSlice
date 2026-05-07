import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from qpdg_builder import QPDGBuilder
from qpdg_viz import to_dot
from test_qslice import RUNNING_EXAMPLE


class SrcQPDGCompatibilityTests(unittest.TestCase):
    def setUp(self):
        self.graph = QPDGBuilder().build_from_outjson(RUNNING_EXAMPLE)

    def test_src_builder_uses_statement_level_nodes(self):
        cnot_nodes = [node for node in self.graph.nodes.values() if node.line == 8]
        self.assertEqual(len(cnot_nodes), 1)
        self.assertEqual(cnot_nodes[0].kind, "STMT")
        self.assertEqual(cnot_nodes[0].gate, "cx")
        self.assertEqual(cnot_nodes[0].meta["qubits"], ["q[0]", "q[1]"])

    def test_src_builder_exposes_semantic_edge_kinds(self):
        edge_kinds = {edge.kind for edge in self.graph.edges}
        self.assertTrue(any("ued" in kind.split("+") for kind in edge_kinds))
        self.assertTrue(any("ed" in kind.split("+") for kind in edge_kinds))
        self.assertTrue(any("md" in kind.split("+") for kind in edge_kinds))
        self.assertTrue(any("cd" in kind.split("+") for kind in edge_kinds))

    def test_src_dot_uses_semantic_labels(self):
        dot = to_dot(self.graph)
        self.assertIn("digraph QDG", dot)
        self.assertIn('label="ued', dot)
        self.assertIn('label="cd', dot)
        self.assertIn('v1: l8', dot)


if __name__ == "__main__":
    unittest.main()
