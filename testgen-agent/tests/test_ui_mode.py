"""Tests for the front-end UI generation mode (project_type == 'ui')."""

import tempfile
import unittest
from pathlib import Path

from testgen import ui_prompt
from testgen.gherkin import extract_step_patterns_js
from testgen.nodes import _get_prompt_module, _glue_language, _glue_patterns, validate_output
from testgen.state import FeatureFile, GenerationResult, StepDefinitionFile

JS_GLUE = '''
import { Given, When, Then } from "@cucumber/cucumber";

Given("I open the widget", async function () {});
When("I click save", async function () {});
Then("I see {string}", async function (msg) {});
// a method call must NOT be picked up as a binding:
ctx.When("ignored", () => {});
'''

FEATURE = (
    "Feature: Widget\n"
    "  Scenario: Save\n"
    "    Given I open the widget\n"
    "    When I click save\n"
    '    Then I see "Saved"\n'
)

FEATURE_PATH = "frontend-react/tests/features/widget.feature"
GLUE_PATH = "frontend-react/tests/steps/widget.steps.js"


class JsExtractionTest(unittest.TestCase):
    def test_extracts_bare_cucumber_js_bindings(self):
        patterns = extract_step_patterns_js(JS_GLUE)
        self.assertEqual(patterns, ["I open the widget", "I click save", "I see {string}"])

    def test_ignores_method_call_form(self):
        self.assertNotIn("ignored", extract_step_patterns_js(JS_GLUE))


class GlueLanguageTest(unittest.TestCase):
    def test_language_from_extension(self):
        self.assertEqual(_glue_language("a/b.steps.js", None), "javascript")
        self.assertEqual(_glue_language("a/B.java", None), "java")
        self.assertEqual(_glue_language("a/B.cs", None), "csharp")

    def test_hint_wins(self):
        self.assertEqual(_glue_language("a/B.cs", "javascript"), "javascript")

    def test_glue_patterns_uses_js_parser_for_js(self):
        self.assertEqual(
            _glue_patterns(GLUE_PATH, JS_GLUE),
            ["I open the widget", "I click save", "I see {string}"],
        )


class PromptModuleTest(unittest.TestCase):
    def test_ui_routes_to_ui_prompt(self):
        self.assertIs(_get_prompt_module("ui"), ui_prompt)

    def test_java_and_dotnet_unchanged(self):
        self.assertIsNot(_get_prompt_module("java"), ui_prompt)
        self.assertIsNot(_get_prompt_module("dotnet"), ui_prompt)


def _ui_state(repo, generation):
    return {
        "repo_path": str(repo),
        "generation": generation,
        "project_type": "ui",
        "step_patterns": [],  # all steps are bound by the generated JS glue
        "attempts": 1,
    }


class UiValidationTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self._tmp.name)
        (self.repo / "frontend-react/tests/features").mkdir(parents=True)
        (self.repo / "frontend-react/tests/steps").mkdir(parents=True)

    def tearDown(self):
        self._tmp.cleanup()

    def _gen(self, feature_path=FEATURE_PATH, glue_path=GLUE_PATH):
        return GenerationResult(
            impacted_endpoints=["Widget"],
            analysis_summary="x",
            new_or_modified_features=[FeatureFile(
                file_name=feature_path, action="CREATE", gherkin_content=FEATURE,
            )],
            new_or_modified_step_definitions=[StepDefinitionFile(
                file_name=glue_path, action="CREATE", java_content=JS_GLUE, language="javascript",
            )],
        )

    def test_clean_ui_generation_passes(self):
        out = validate_output(_ui_state(self.repo, self._gen()))
        self.assertEqual(out["validation_errors"], [])

    def test_feature_outside_ui_dir_rejected(self):
        out = validate_output(_ui_state(self.repo, self._gen(feature_path="legacy-ui/features/widget.feature")))
        self.assertTrue(any("UI run" in e for e in out["validation_errors"]))

    def test_non_js_glue_rejected(self):
        out = validate_output(_ui_state(
            self.repo,
            self._gen(glue_path="frontend-react/tests/steps/widget.steps.cs"),
        ))
        self.assertTrue(any("must end with .js" in e for e in out["validation_errors"]))

    def test_empty_generation_for_changed_ui_source_is_rejected(self):
        """Parity with the .NET guard: a UI source change that produces NO feature
        and NO step-definition update must be forced to retry, not silently accepted."""
        empty = GenerationResult(
            impacted_endpoints=[], analysis_summary="nothing observable",
            new_or_modified_features=[], new_or_modified_step_definitions=[],
        )
        state = _ui_state(self.repo, empty)
        state["changed_files"] = ["frontend-react/src/ProductCatalog.jsx"]
        out = validate_output(state)
        self.assertTrue(any("CRITICAL VALIDATION FAILURE" in e for e in out["validation_errors"]))

    def test_empty_generation_without_ui_source_change_is_allowed(self):
        """No UI source in changed_files (e.g. only a test file touched) — the
        empty-generation guard must not fire."""
        empty = GenerationResult(
            impacted_endpoints=[], analysis_summary="nothing to do",
            new_or_modified_features=[], new_or_modified_step_definitions=[],
        )
        state = _ui_state(self.repo, empty)
        state["changed_files"] = ["README.md"]
        out = validate_output(state)
        self.assertEqual(out["validation_errors"], [])


if __name__ == "__main__":
    unittest.main()
