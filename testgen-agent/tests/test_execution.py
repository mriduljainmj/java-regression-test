"""Tests for the execution-feedback parsers (no Maven required)."""

import json
import tempfile
import unittest
from pathlib import Path

from testgen.languages import DOTNET, JAVA
from testgen.nodes import (
    _extract_compile_errors,
    _extract_scenario_failures_dotnet,
    _extract_scenario_failures_java,
)

COMPONENT_DIR = JAVA.component_dir


class CompileErrorTest(unittest.TestCase):
    def test_extracts_java_compiler_errors(self):
        out = (
            "[INFO] Building product-service\n"
            "[ERROR] /r/ReviewStepDefinitions.java:[33,12] cannot find symbol\n"
            "[ERROR] /r/ReviewStepDefinitions.java:[40,5] ';' expected\n"
            "[INFO] BUILD FAILURE\n"
        )
        errs = _extract_compile_errors(out, JAVA)
        self.assertEqual(len(errs), 2)
        self.assertIn("cannot find symbol", errs[0])

    def test_ignores_non_java_error_lines(self):
        self.assertEqual(_extract_compile_errors("[ERROR] Some maven plugin failure\n", JAVA), [])

    def test_extracts_dotnet_compiler_errors(self):
        out = (
            "Determining projects to restore...\n"
            "ProductSteps.cs(20,13): error CS0103: The name 'ctx' does not exist\n"
            "  ProductSteps.cs(20,13): error CS0103: The name 'ctx' does not exist\n"  # repeated
            "Build FAILED.\n"
        )
        errs = _extract_compile_errors(out, DOTNET)
        self.assertEqual(len(errs), 1)  # de-duped
        self.assertIn("CS0103", errs[0])

    def test_dotnet_scenario_failures_from_console(self):
        out = (
            "  Failed ProductTests.AddReview_RejectsRating1 [42 ms]\n"
            "  Error Message:\n"
            "   Assert.Equal() Failure: Expected 4050.00 but was 4000.00\n"
            "  Passed ProductTests.CreateProduct [10 ms]\n"
        )
        failures = _extract_scenario_failures_dotnet(out)
        self.assertEqual(len(failures), 1)
        self.assertIn("AddReview_RejectsRating1", failures[0])
        self.assertIn("4050.00", failures[0])


class ScenarioFailureTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self._tmp.name)
        target = self.repo / COMPONENT_DIR / "target"
        target.mkdir(parents=True)
        self.report = target / "cucumber-report.json"

    def tearDown(self):
        self._tmp.cleanup()

    def _write(self, report):
        self.report.write_text(json.dumps(report))

    def test_captures_failed_scenario_with_reason(self):
        self._write([{
            "name": "Product management",
            "elements": [
                {"type": "background", "name": "bg", "steps": [
                    {"keyword": "Given ", "name": "the catalog is empty",
                     "result": {"status": "passed"}}]},
                {"type": "scenario", "name": "Retrieve a product that does not exist", "steps": [
                    {"keyword": "When ", "name": "a client requests product 9999",
                     "result": {"status": "passed"}},
                    {"keyword": "Then ", "name": 'the error contains "Product not found"',
                     "result": {"status": "failed",
                                "error_message": "Expected: a string containing \"Product not found\"\n     but: was \"No product\""}},
                ]},
            ],
        }])
        failures = _extract_scenario_failures_java(self.repo, JAVA, COMPONENT_DIR)
        self.assertEqual(len(failures), 1)
        self.assertIn("Retrieve a product that does not exist", failures[0])
        self.assertIn("Product not found", failures[0])

    def test_passing_report_yields_no_failures(self):
        self._write([{
            "name": "F",
            "elements": [{"type": "scenario", "name": "ok", "steps": [
                {"keyword": "When ", "name": "x", "result": {"status": "passed"}}]}],
        }])
        self.assertEqual(_extract_scenario_failures_java(self.repo, JAVA, COMPONENT_DIR), [])

    def test_undefined_step_is_a_failure(self):
        self._write([{
            "name": "F",
            "elements": [{"type": "scenario", "name": "new behavior", "steps": [
                {"keyword": "When ", "name": "an undefined step",
                 "result": {"status": "undefined"}}]}],
        }])
        failures = _extract_scenario_failures_java(self.repo, JAVA, COMPONENT_DIR)
        self.assertEqual(len(failures), 1)
        self.assertIn("undefined", failures[0])

    def test_no_report_file_yields_no_failures(self):
        # No report was written (compile failed before tests ran, say).
        self.assertFalse(self.report.exists())
        self.assertEqual(_extract_scenario_failures_java(self.repo, JAVA, COMPONENT_DIR), [])


if __name__ == "__main__":
    unittest.main()
