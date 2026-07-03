"""Tests for validate_output's step-definition (glue) handling."""

import tempfile
import unittest
from pathlib import Path

from testgen.nodes import validate_output
from testgen.state import FeatureFile, GenerationResult, StepDefinitionFile

EXISTING_GLUE = '''
public class Steps {
    @Given("the catalog is empty")
    public void empty() {}

    @Then("the response status should be {int}")
    public void status(int code) {}
}
'''

NEW_GLUE = '''
public class InventorySteps {
    @When("a client checks inventory for {string}")
    public void check(String sku) {}
}
'''

GLUE_PATH = "component/src/test/java/com/example/InventorySteps.java"
FEATURE_PATH = "component/src/test/resources/features/inventory.feature"


def make_state(repo, generation):
    return {
        "repo_path": str(repo),
        "generation": generation,
        "step_patterns": ["the catalog is empty", "the response status should be {int}"],
        "attempts": 1,
    }


class GlueValidationTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self._tmp.name)
        (self.repo / "component/src/test/java/com/example").mkdir(parents=True)
        (self.repo / "component/src/test/resources/features").mkdir(parents=True)

    def tearDown(self):
        self._tmp.cleanup()

    def test_new_glue_makes_new_steps_valid(self):
        generation = GenerationResult(
            impacted_endpoints=["GET /inventory"],
            analysis_summary="x",
            new_or_modified_features=[FeatureFile(
                file_name=FEATURE_PATH,
                action="CREATE",
                gherkin_content=(
                    "Feature: Inventory\n  Scenario: S\n"
                    '    When a client checks inventory for "ABC"\n'
                    "    Then the response status should be 200\n"
                ),
            )],
            new_or_modified_step_definitions=[StepDefinitionFile(
                file_name=GLUE_PATH, action="CREATE", java_content=NEW_GLUE,
            )],
        )
        out = validate_output(make_state(self.repo, generation))
        self.assertEqual(out["validation_errors"], [])

    def test_dotnet_glue_and_feature_paths_are_allowed(self):
        generation = GenerationResult(
            impacted_endpoints=["GET /weatherforecast/today"],
            analysis_summary="x",
            new_or_modified_features=[FeatureFile(
                file_name="dotnet-component/Tests/Features/weatherforecast_today.feature",
                action="CREATE",
                gherkin_content=(
                    "Feature: Today forecast\n  Scenario: Get today forecast\n"
                    "    When a client requests the today's weather forecast\n"
                    "    Then the response status should be 200\n"
                ),
            )],
            new_or_modified_step_definitions=[StepDefinitionFile(
                file_name="dotnet-component/Tests/WeatherForecastStepDefinitions.cs",
                action="CREATE",
                java_content='''using TechTalk.SpecFlow;\n\n[Binding]\npublic class WeatherForecastStepDefinitions {\n    [When("a client requests the today's weather forecast")]\n    public void WhenAClientRequestsTheTodaysWeatherForecast() {}\n    [Then("the response status should be {int}")]\n    public void ThenTheResponseStatusShouldBe(int status) {}\n}''',
                language="csharp",
            )],
        )
        state = make_state(self.repo, generation)
        state["project_type"] = "dotnet"
        out = validate_output(state)
        self.assertEqual(out["validation_errors"], [])

    def test_dotnet_java_stepdef_is_rejected(self):
        generation = GenerationResult(
            impacted_endpoints=[],
            analysis_summary="x",
            new_or_modified_features=[],
            new_or_modified_step_definitions=[StepDefinitionFile(
                file_name="dotnet-component/Tests/WeatherForecastStepDefinitions.java",
                action="CREATE",
                java_content=NEW_GLUE,
                language="java",
            )],
        )
        state = make_state(self.repo, generation)
        state["project_type"] = "dotnet"
        out = validate_output(state)
        self.assertTrue(any(
            ".java step-definition files are invalid for dotnet projects" in e
            for e in out["validation_errors"]
        ))

    def test_dotnet_selects_dotnet_prompt_module(self):
        from testgen.nodes import _get_prompt_module
        self.assertIs(_get_prompt_module("dotnet"), __import__("testgen.dotnet_prompt", fromlist=["*"]))
        self.assertIsNot(_get_prompt_module("java"), __import__("testgen.dotnet_prompt", fromlist=["*"]))

    def test_new_step_without_glue_is_flagged(self):
        generation = GenerationResult(
            impacted_endpoints=[],
            analysis_summary="x",
            new_or_modified_features=[FeatureFile(
                file_name=FEATURE_PATH,
                action="CREATE",
                gherkin_content=(
                    "Feature: Inventory\n  Scenario: S\n"
                    '    When a client checks inventory for "ABC"\n'
                ),
            )],
        )
        out = validate_output(make_state(self.repo, generation))
        self.assertTrue(any("matches no existing step definition" in e
                            for e in out["validation_errors"]))

    def test_rewrite_dropping_existing_steps_is_flagged(self):
        # Whenever the file exists, dropping a step it currently has is an error —
        # regardless of the CREATE/UPDATE label the model put on it.
        existing = self.repo / GLUE_PATH
        existing.write_text(EXISTING_GLUE)
        for label in ("UPDATE", "CREATE"):
            generation = GenerationResult(
                impacted_endpoints=[], analysis_summary="x",
                new_or_modified_features=[],
                new_or_modified_step_definitions=[StepDefinitionFile(
                    file_name=GLUE_PATH, action=label, java_content=NEW_GLUE,
                )],
            )
            out = validate_output(make_state(self.repo, generation))
            self.assertTrue(any("drops existing step definition" in e
                                for e in out["validation_errors"]),
                            f"label={label} should flag dropped steps")

    def test_create_label_on_existing_file_is_not_rejected(self):
        # Regression for the retry-loop thrash: after attempt 1 writes a feature,
        # a later attempt that still says CREATE must NOT be rejected just for the
        # label — only real problems (undefined steps, bad paths) should fail it.
        existing = self.repo / FEATURE_PATH
        existing.parent.mkdir(parents=True, exist_ok=True)
        existing.write_text("Feature: Inventory\n  Scenario: old\n    Given the catalog is empty\n")
        generation = GenerationResult(
            impacted_endpoints=[], analysis_summary="x",
            new_or_modified_features=[FeatureFile(
                file_name=FEATURE_PATH, action="CREATE",  # stale label, file exists
                gherkin_content=(
                    "Feature: Inventory\n  Scenario: S\n"
                    "    Given the catalog is empty\n"
                    "    Then the response status should be 200\n"
                ),
            )],
        )
        out = validate_output(make_state(self.repo, generation))
        self.assertEqual(out["validation_errors"], [])

    def test_glue_outside_test_sources_is_flagged(self):
        generation = GenerationResult(
            impacted_endpoints=[],
            analysis_summary="x",
            new_or_modified_features=[],
            new_or_modified_step_definitions=[StepDefinitionFile(
                file_name="component/src/main/java/com/example/Steps.java",
                action="CREATE",
                java_content=NEW_GLUE,
            )],
        )
        out = validate_output(make_state(self.repo, generation))
        self.assertTrue(any("must live under" in e for e in out["validation_errors"]))

    def test_glue_without_annotations_is_flagged(self):
        generation = GenerationResult(
            impacted_endpoints=[],
            analysis_summary="x",
            new_or_modified_features=[],
            new_or_modified_step_definitions=[StepDefinitionFile(
                file_name=GLUE_PATH, action="CREATE",
                java_content="public class Empty {}",
            )],
        )
        out = validate_output(make_state(self.repo, generation))
        self.assertTrue(any("contains no [Given]/[When]/[Then]" in e
                            for e in out["validation_errors"]))


if __name__ == "__main__":
    unittest.main()
