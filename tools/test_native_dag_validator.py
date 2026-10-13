import json
import subprocess
import sys
import unittest
from pathlib import Path

from native_dag_validator import run_validation


VALID_SOURCE = """
def topological_order(nodes, edges):
    if not isinstance(nodes, list):
        raise ValueError("nodes")
    if not all(isinstance(node, str) and node for node in nodes):
        raise ValueError("node")
    if len(set(nodes)) != len(nodes):
        raise ValueError("duplicate")
    known = set(nodes)
    indegree = {node: 0 for node in nodes}
    outgoing = {node: [] for node in nodes}
    for edge in edges:
        if not isinstance(edge, (list, tuple)) or len(edge) != 2:
            raise ValueError("edge")
        source, target = edge
        if source not in known or target not in known:
            raise ValueError("endpoint")
        if target not in outgoing[source]:
            outgoing[source].append(target)
            indegree[target] += 1
    ready = sorted([node for node in nodes if indegree[node] == 0])
    result = []
    while ready:
        current = ready.pop(0)
        result.append(current)
        for target in sorted(outgoing[current]):
            indegree[target] -= 1
            if indegree[target] == 0:
                ready.append(target)
                ready = sorted(ready)
    if len(result) != len(nodes):
        raise ValueError("cycle")
    return result
"""


class NativeDagValidatorTests(unittest.TestCase):
    def assert_report_shape(self, report):
        self.assertEqual(report["schema_version"], 1)
        self.assertIsInstance(report["passed"], bool)
        self.assertIsInstance(report["tests"], list)
        self.assertIsInstance(report["errors"], list)
        for test in report["tests"]:
            self.assertEqual(set(test), {"name", "passed"})
            self.assertIsInstance(test["name"], str)
            self.assertIsInstance(test["passed"], bool)
        self.assertLessEqual(len(report["errors"]), 16)
        self.assertTrue(all(len(error) <= 160 for error in report["errors"]))

    def test_valid_fixture_passes_and_covers_semantics(self):
        report = run_validation(VALID_SOURCE)
        self.assert_report_shape(report)
        self.assertTrue(report["passed"], report)
        self.assertTrue(all(test["passed"] for test in report["tests"]))

    def test_fifo_queue_cannot_pass_deterministic_dependency_ordering(self):
        source = VALID_SOURCE.replace("                ready = sorted(ready)", "                pass")
        self.assertNotEqual(source, VALID_SOURCE)

        report = run_validation(source)

        self.assert_report_shape(report)
        self.assertFalse(report["passed"], report)
        self.assertIn(
            {"name": "newly_ready_nodes_are_sorted", "passed": False}, report["tests"]
        )

    def test_policy_rejects_import_eval_open_dunder_and_attributes(self):
        sources = [
            "import os\n\ndef topological_order(nodes, edges):\n    return []\n",
            "def topological_order(nodes, edges):\n    return eval('[]')\n",
            "def topological_order(nodes, edges):\n    return open('x')\n",
            "def topological_order(nodes, edges):\n    return nodes.__class__\n",
            "def topological_order(nodes, edges):\n    return nodes.sort()\n",
        ]
        for source in sources:
            with self.subTest(source=source):
                report = run_validation(source)
                self.assert_report_shape(report)
                self.assertFalse(report["passed"])
                self.assertEqual(report["tests"], [])
                self.assertTrue(report["errors"])

    def test_policy_rejects_unknown_calls_and_nested_helpers(self):
        sources = [
            "def topological_order(nodes, edges):\n    return mystery(nodes)\n",
            (
                "def topological_order(nodes, edges):\n"
                "    def helper(value):\n"
                "        return value\n"
                "    return helper(nodes)\n"
            ),
        ]
        for source in sources:
            with self.subTest(source=source):
                self.assertFalse(run_validation(source)["passed"])

    def test_infinite_loop_is_bounded(self):
        source = """
def topological_order(nodes, edges):
    while True:
        pass
"""
        report = run_validation(source)
        self.assert_report_shape(report)
        self.assertFalse(report["passed"])
        self.assertIn("execution step budget exceeded", report["errors"])

    def test_invalid_source_size_and_ast_are_rejected(self):
        oversized = "def topological_order(nodes, edges):\n    return []\n" + (" " * 65536)
        self.assertFalse(run_validation(oversized)["passed"])
        dense = "def topological_order(nodes, edges):\n    return [" + ",".join(["0"] * 4100) + "]\n"
        report = run_validation(dense)
        self.assertFalse(report["passed"])
        self.assertIn("AST node limit", " ".join(report["errors"]))

    def test_cli_emits_json_only_and_returns_zero_when_validation_fails(self):
        source_path = Path(__file__).with_name("native_dag_validator.py")
        completed = subprocess.run(
            [sys.executable, "-B", str(source_path), str(source_path)],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0)
        self.assertEqual(completed.stderr, "")
        report = json.loads(completed.stdout)
        self.assert_report_shape(report)
        self.assertFalse(report["passed"])


if __name__ == "__main__":
    unittest.main()
