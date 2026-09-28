"""Tests for the execution-feedback parsers (no Maven required)."""

import json
import tempfile
import unittest
from pathlib import Path

from testgen.nodes import (
    COMPONENT_DIR,
    _extract_compile_errors,
    _extract_scenario_failures,
    run_generated_tests,
)
from testgen.state import FeatureFile, GenerationResult


class CompileErrorTest(unittest.TestCase):
    def test_extracts_java_compiler_errors(self):
        out = (
            "[INFO] Building product-service\n"
            "[ERROR] /r/ReviewStepDefinitions.java:[33,12] cannot find symbol\n"
            "[ERROR] /r/ReviewStepDefinitions.java:[40,5] ';' expected\n"
            "[INFO] BUILD FAILURE\n"
        )
        errs = _extract_compile_errors(out)
        self.assertEqual(len(errs), 2)
        self.assertIn("cannot find symbol", errs[0])

    def test_ignores_non_java_error_lines(self):
        self.assertEqual(_extract_compile_errors("[ERROR] Some maven plugin failure\n"), [])


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
        failures = _extract_scenario_failures(self.repo)
        self.assertEqual(len(failures), 1)
        self.assertIn("Retrieve a product that does not exist", failures[0])
        self.assertIn("Product not found", failures[0])

    def test_passing_report_yields_no_failures(self):
        self._write([{
            "name": "F",
            "elements": [{"type": "scenario", "name": "ok", "steps": [
                {"keyword": "When ", "name": "x", "result": {"status": "passed"}}]}],
        }])
        self.assertEqual(_extract_scenario_failures(self.repo), [])

    def test_undefined_step_is_a_failure(self):
        self._write([{
            "name": "F",
            "elements": [{"type": "scenario", "name": "new behavior", "steps": [
                {"keyword": "When ", "name": "an undefined step",
                 "result": {"status": "undefined"}}]}],
        }])
        failures = _extract_scenario_failures(self.repo)
        self.assertEqual(len(failures), 1)
        self.assertIn("undefined", failures[0])

    def test_no_report_file_yields_no_failures(self):
        # No report was written (compile failed before tests ran, say).
        self.assertFalse(self.report.exists())
        self.assertEqual(_extract_scenario_failures(self.repo), [])


class NoOpGenerationFailureTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_candidate_outputs_with_no_written_files_raise(self):
        state = {
            "repo_path": str(self.repo),
            "project_type": "dotnet",
            "written_files": [],
            "generation": GenerationResult(
                impacted_endpoints=["GET /api/discount-policy"],
                analysis_summary="discount percent changed",
                new_or_modified_features=[FeatureFile(
                    file_name="dotnet-component/Tests/Features/pricing_orchestration.feature",
                    action="UPDATE",
                    gherkin_content="Feature: Pricing orchestration\n  Scenario: S\n    Given x\n",
                )],
            ),
        }

        with self.assertRaises(RuntimeError) as ctx:
            run_generated_tests(state)

        self.assertIn("identical to what is already on disk", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
