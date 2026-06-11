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

    def test_update_removing_existing_steps_is_flagged(self):
        existing = self.repo / GLUE_PATH
        existing.write_text(EXISTING_GLUE)
        generation = GenerationResult(
            impacted_endpoints=[],
            analysis_summary="x",
            new_or_modified_features=[],
            new_or_modified_step_definitions=[StepDefinitionFile(
                file_name=GLUE_PATH, action="UPDATE", java_content=NEW_GLUE,
            )],
        )
        out = validate_output(make_state(self.repo, generation))
        self.assertTrue(any("removes existing step definition" in e
                            for e in out["validation_errors"]))

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
        self.assertTrue(any("contains no @Given/@When/@Then" in e
                            for e in out["validation_errors"]))


if __name__ == "__main__":
    unittest.main()
