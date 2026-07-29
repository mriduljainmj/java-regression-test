"""Proves the agent is relocatable: every Java/.NET path marker is derived from a
single overridable component-dir constant, not a hardcoded literal. These tests
patch the *derived* module-level constants directly (the values validate_output
etc. actually read) rather than the env vars, because COMPONENT_DIR/DOTNET_
COMPONENT_DIR are only consulted once, at import time, to compute them — exactly
mirroring what setting TESTGEN_COMPONENT_DIR / TESTGEN_DOTNET_COMPONENT_DIR /
TESTGEN_DOTNET_TEST_PROJECT before the process starts would produce.
"""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from testgen import nodes
from testgen.nodes import validate_output
from testgen.state import FeatureFile, GenerationResult, StepDefinitionFile

JAVA_GLUE = '''
public class Steps {
    @When("a client checks inventory for {string}")
    public void check(String sku) {}
}
'''

DOTNET_GLUE = '''
[When(@"a client checks inventory for ""(.*)""")]
public void Check(string sku) {}
'''


class RelocatedJavaComponentTest(unittest.TestCase):
    """Simulates TESTGEN_COMPONENT_DIR=backend (a real repo's actual folder name,
    not our demo's 'java-component')."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self._tmp.name)
        (self.repo / "backend/src/test/java/com/example").mkdir(parents=True)
        (self.repo / "backend/src/test/resources/features").mkdir(parents=True)
        self._patches = [
            patch.object(nodes, "COMPONENT_DIR", "backend"),
            patch.object(nodes, "JAVA_SOURCE_MARKER", "backend/src/main/java"),
            patch.object(nodes, "JAVA_TEST_MARKER", "backend/src/test/java"),
            patch.object(nodes, "FEATURES_DIR_MARKER", "backend/src/test/resources/features"),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in self._patches:
            p.stop()
        self._tmp.cleanup()

    def _state(self, generation):
        return {
            "repo_path": str(self.repo),
            "generation": generation,
            "project_type": "java",
            "step_patterns": [],
            "attempts": 1,
        }

    def test_relocated_paths_are_accepted(self):
        generation = GenerationResult(
            impacted_endpoints=["GET /inventory"], analysis_summary="x",
            new_or_modified_features=[FeatureFile(
                file_name="backend/src/test/resources/features/inventory.feature",
                action="CREATE",
                gherkin_content=(
                    "Feature: Inventory\n  Scenario: S\n"
                    '    When a client checks inventory for "ABC"\n'
                ),
            )],
            new_or_modified_step_definitions=[StepDefinitionFile(
                file_name="backend/src/test/java/com/example/InventorySteps.java",
                action="CREATE", java_content=JAVA_GLUE,
            )],
        )
        out = validate_output(self._state(generation))
        self.assertEqual(out["validation_errors"], [])

    def test_old_default_path_is_now_rejected(self):
        """The point of relocation: java-component/... must NOT still silently
        match once the repo is configured to use a different folder."""
        generation = GenerationResult(
            impacted_endpoints=["GET /inventory"], analysis_summary="x",
            new_or_modified_features=[FeatureFile(
                file_name="java-component/src/test/resources/features/inventory.feature",
                action="CREATE",
                gherkin_content="Feature: Inventory\n  Scenario: S\n    Given x\n",
            )],
        )
        out = validate_output(self._state(generation))
        self.assertTrue(any("must live under" in e for e in out["validation_errors"]))


class RelocatedDotnetComponentTest(unittest.TestCase):
    """Simulates TESTGEN_DOTNET_COMPONENT_DIR=services/billing-api and
    TESTGEN_DOTNET_TEST_PROJECT=Billing.Tests.csproj — a real .NET solution's
    actual layout, not our demo's 'dotnet-component/BP.Tests.csproj'."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self._tmp.name)
        self._patches = [
            patch.object(nodes, "DOTNET_COMPONENT_DIR", "services/billing-api"),
            patch.object(nodes, "DOTNET_TEST_PROJECT", "Billing.Tests.csproj"),
            patch.object(nodes, "FEATURES_DIR_MARKER_DOTNET", "services/billing-api/Tests/Features"),
            patch.object(nodes, "DOTNET_TESTS_DIR_MARKER", "services/billing-api/Tests/"),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in self._patches:
            p.stop()
        self._tmp.cleanup()

    def _state(self, generation):
        return {
            "repo_path": str(self.repo),
            "generation": generation,
            "project_type": "dotnet",
            "step_patterns": [],
            "attempts": 1,
        }

    def test_relocated_feature_path_is_accepted(self):
        generation = GenerationResult(
            impacted_endpoints=["GET /inventory"], analysis_summary="x",
            new_or_modified_features=[FeatureFile(
                file_name="services/billing-api/Tests/Features/inventory.feature",
                action="CREATE",
                gherkin_content=(
                    "Feature: Inventory\n  Scenario: S\n"
                    '    When a client checks inventory for "ABC"\n'
                ),
            )],
            new_or_modified_step_definitions=[StepDefinitionFile(
                file_name="services/billing-api/Tests/InventorySteps.cs",
                action="CREATE", java_content=DOTNET_GLUE, language="csharp",
            )],
        )
        out = validate_output(self._state(generation))
        self.assertEqual(out["validation_errors"], [])

    def test_old_default_path_is_now_rejected(self):
        generation = GenerationResult(
            impacted_endpoints=["GET /inventory"], analysis_summary="x",
            new_or_modified_features=[FeatureFile(
                file_name="dotnet-component/Tests/Features/inventory.feature",
                action="CREATE",
                gherkin_content="Feature: Inventory\n  Scenario: S\n    Given x\n",
            )],
        )
        out = validate_output(self._state(generation))
        self.assertTrue(any("MUST be under" in e for e in out["validation_errors"]))

    @patch("testgen.nodes.subprocess.run")
    @patch("testgen.nodes.shutil.which", return_value="/usr/bin/dotnet")
    def test_relocated_test_project_path_is_actually_invoked(self, mock_which, mock_run):
        """Confirms _run_dotnet_tests builds the command from the overridden
        constants, not the hardcoded 'dotnet-component/BP.Tests.csproj'."""
        mock_run.return_value.returncode = 0
        state = {"written_files": ["x"], "test_attempts": 0}
        nodes._run_dotnet_tests(self.repo, state)
        invoked_cmd = mock_run.call_args[0][0]
        expected_project = str(self.repo / "services/billing-api" / "Billing.Tests.csproj")
        self.assertIn(expected_project, invoked_cmd)
        self.assertNotIn(str(self.repo / "dotnet-component" / "BP.Tests.csproj"), invoked_cmd)


class RelocatedUiComponentTest(unittest.TestCase):
    """Simulates TESTGEN_UI_COMPONENT_DIR=web/app — a real repo's actual UI folder
    name, not our demo's 'frontend-react'. UI_SOURCE_MARKER/UI_TESTS_DIR_MARKER/
    UI_FEATURES_DIR_MARKER derive from UI_COMPONENT_DIR by default, so setting
    just the one component-dir var should be enough."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self._tmp.name)
        self._patches = [
            patch.object(nodes, "UI_COMPONENT_DIR", "web/app"),
            patch.object(nodes, "UI_SOURCE_MARKER", "web/app/src"),
            patch.object(nodes, "UI_TESTS_DIR_MARKER", "web/app/tests/"),
            patch.object(nodes, "UI_FEATURES_DIR_MARKER", "web/app/tests/features"),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in self._patches:
            p.stop()
        self._tmp.cleanup()

    def test_relocated_paths_are_accepted(self):
        generation = GenerationResult(
            impacted_endpoints=["Widget"], analysis_summary="x",
            new_or_modified_features=[FeatureFile(
                file_name="web/app/tests/features/widget.feature",
                action="CREATE",
                gherkin_content="Feature: Widget\n  Scenario: S\n    Given I open the widget\n",
            )],
            new_or_modified_step_definitions=[StepDefinitionFile(
                file_name="web/app/tests/steps/widget.steps.js",
                action="CREATE",
                java_content='Given("I open the widget", async function () {});',
                language="javascript",
            )],
        )
        out = validate_output({
            "repo_path": str(self.repo), "generation": generation,
            "project_type": "ui", "step_patterns": [], "attempts": 1,
        })
        self.assertEqual(out["validation_errors"], [])

    def test_old_default_path_is_now_rejected(self):
        generation = GenerationResult(
            impacted_endpoints=["Widget"], analysis_summary="x",
            new_or_modified_features=[FeatureFile(
                file_name="frontend-react/tests/features/widget.feature",
                action="CREATE",
                gherkin_content="Feature: Widget\n  Scenario: S\n    Given x\n",
            )],
        )
        out = validate_output({
            "repo_path": str(self.repo), "generation": generation,
            "project_type": "ui", "step_patterns": [], "attempts": 1,
        })
        self.assertTrue(any("MUST be under" in e for e in out["validation_errors"]))


if __name__ == "__main__":
    unittest.main()
