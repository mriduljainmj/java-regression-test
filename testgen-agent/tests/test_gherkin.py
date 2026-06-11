"""Unit tests for the Gherkin step-matching validator.

Run from testgen-agent/:  python -m unittest discover tests
"""

import unittest

from testgen.gherkin import (
    cucumber_expression_to_regex,
    extract_scenario_steps,
    extract_step_patterns,
    find_undefined_steps,
)

JAVA_GLUE = '''
public class Steps {
    @Given("the product catalog is empty")
    public void empty() {}

    @When("a client creates a product with name {string} and price {double}")
    public void create(String name, double price) {}

    @When("a client creates a product with payload:")
    public void createWithPayload(String payload) {}

    @Then("the response status should be {int}")
    public void status(int code) {}

    @Then("the response should contain {int} product(s)")
    public void count(int n) {}

    @Then("the item is/are visible")
    public void visible() {}

    @Then("the error message should contain {string}")
    public void error(String fragment) {}

    @Given("a label of \\"{word}\\" exists")
    public void escaped(String w) {}
}
'''


class ExtractPatternsTest(unittest.TestCase):
    def test_extracts_all_annotations(self):
        patterns = extract_step_patterns(JAVA_GLUE)
        self.assertEqual(len(patterns), 8)
        self.assertIn("the product catalog is empty", patterns)
        self.assertIn("a client creates a product with name {string} and price {double}", patterns)

    def test_unescapes_java_quotes(self):
        patterns = extract_step_patterns(JAVA_GLUE)
        self.assertIn('a label of "{word}" exists', patterns)


class ExpressionRegexTest(unittest.TestCase):
    def match(self, expr, text):
        return cucumber_expression_to_regex(expr).match(text) is not None

    def test_string_param(self):
        expr = "a client creates a product with name {string} and price {double}"
        self.assertTrue(self.match(expr, 'a client creates a product with name "Laptop" and price 9.99'))
        self.assertTrue(self.match(expr, 'a client creates a product with name "" and price 0'))
        self.assertFalse(self.match(expr, "a client creates a product with name Laptop and price 9.99"))

    def test_numeric_params(self):
        self.assertTrue(self.match("the response status should be {int}", "the response status should be 404"))
        self.assertFalse(self.match("the response status should be {int}", "the response status should be abc"))
        self.assertTrue(self.match("price is {double}", "price is -5.00"))
        self.assertTrue(self.match("price is {double}", "price is 10"))

    def test_optional_text(self):
        self.assertTrue(self.match("the response should contain {int} product(s)",
                                   "the response should contain 1 product"))
        self.assertTrue(self.match("the response should contain {int} product(s)",
                                   "the response should contain 3 products"))

    def test_alternation(self):
        self.assertTrue(self.match("the item is/are visible", "the item is visible"))
        self.assertTrue(self.match("the item is/are visible", "the item are visible"))
        self.assertFalse(self.match("the item is/are visible", "the item was visible"))

    def test_no_partial_match(self):
        self.assertFalse(self.match("the product catalog is empty",
                                    "the product catalog is empty and shiny"))


FEATURE = '''
Feature: Product management

  Background:
    Given the product catalog is empty

  Scenario: Create a valid product
    When a client creates a product with name "Laptop" and price 999.99
    Then the response status should be 201

  Scenario: Create with raw payload
    When a client creates a product with payload:
      """
      {"name": "X", "price": not-a-step}
      """
    Then the response status should be 400

  Scenario Outline: Reject invalid products
    When a client creates a product with name "<name>" and price <price>
    Then the response status should be 400
    And the error message should contain "<message>"

    Examples:
      | name | price | message                |
      |      | 9.99  | name must not be blank |
      | A    | -1    | price must be positive |
'''


class ScenarioStepsTest(unittest.TestCase):
    def test_extracts_background_and_scenario_steps(self):
        steps = extract_scenario_steps(FEATURE)
        self.assertIn("the product catalog is empty", steps)
        self.assertIn('a client creates a product with name "Laptop" and price 999.99', steps)

    def test_docstring_content_is_not_a_step(self):
        steps = extract_scenario_steps(FEATURE)
        self.assertFalse(any("not-a-step" in s for s in steps))

    def test_outline_placeholders_substituted_from_first_row(self):
        steps = extract_scenario_steps(FEATURE)
        self.assertIn('a client creates a product with name "" and price 9.99', steps)
        self.assertIn('the error message should contain "name must not be blank"', steps)

    def test_table_rows_are_not_steps(self):
        steps = extract_scenario_steps(FEATURE)
        self.assertFalse(any(s.startswith("|") or "9.99  |" in s for s in steps))


class UndefinedStepsTest(unittest.TestCase):
    def setUp(self):
        self.patterns = extract_step_patterns(JAVA_GLUE)

    def test_valid_feature_has_no_undefined_steps(self):
        self.assertEqual(find_undefined_steps(FEATURE, self.patterns), [])

    def test_invented_step_is_flagged(self):
        feature = FEATURE + "\n  Scenario: Bad\n    When the client sends an update request\n"
        undefined = find_undefined_steps(feature, self.patterns)
        self.assertEqual(undefined, ["the client sends an update request"])

    def test_numeric_text_in_string_slot_is_flagged(self):
        feature = (
            "Feature: F\n  Scenario: S\n"
            "    When a client creates a product with name Laptop and price 9.99\n"
        )
        undefined = find_undefined_steps(feature, self.patterns)
        self.assertEqual(len(undefined), 1)


if __name__ == "__main__":
    unittest.main()
