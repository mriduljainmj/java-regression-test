"""Tests for model-output parsing: block format (preferred) and JSON fallback."""

import unittest

from testgen.nodes import _parse_generation

BLOCK_OUTPUT = '''\
ANALYSIS: Added review endpoints; deletion now blocked for products with orders.
ENDPOINTS: POST /api/v1/products/{id}/reviews, GET /api/v1/products/{id}/rating

=== FEATURE CREATE java-component/src/test/resources/features/review_management.feature ===
Feature: Review management

  Scenario: Submit a review
    Given a product exists with name "Widget" and price 20.00
    When a client adds a review with rating 4
    Then the response status should be 201
=== END ===

=== STEPDEF UPDATE java-component/src/test/java/com/example/products/cucumber/ProductStepDefinitions.java ===
public class ProductStepDefinitions {
    @When("a client adds a review with rating {int}")
    public void addReview(int rating) {
        String body = "{\\"rating\\": " + rating + "}";
    }
}
=== END ===
'''


class BlockFormatTest(unittest.TestCase):
    def test_parses_blocks(self):
        g = _parse_generation(BLOCK_OUTPUT)
        self.assertEqual(len(g.new_or_modified_features), 1)
        self.assertEqual(len(g.new_or_modified_step_definitions), 1)
        self.assertEqual(g.new_or_modified_features[0].action, "CREATE")
        self.assertEqual(g.new_or_modified_step_definitions[0].action, "UPDATE")
        self.assertIn("POST /api/v1/products/{id}/reviews", g.impacted_endpoints)
        self.assertTrue(g.analysis_summary.startswith("Added review endpoints"))

    def test_java_content_is_raw(self):
        # Backslashes and quotes inside the block survive untouched — the whole
        # point of leaving JSON behind.
        g = _parse_generation(BLOCK_OUTPUT)
        self.assertIn('String body = "{\\"rating\\": " + rating + "}";',
                      g.new_or_modified_step_definitions[0].java_content)

    def test_gherkin_content_intact(self):
        g = _parse_generation(BLOCK_OUTPUT)
        content = g.new_or_modified_features[0].gherkin_content
        self.assertTrue(content.startswith("Feature: Review management"))
        self.assertIn("Then the response status should be 201", content)

    def test_internal_change_analysis_only(self):
        g = _parse_generation(
            "ANALYSIS: Pure refactor, nothing observable changed.\nENDPOINTS: none\n"
        )
        self.assertEqual(g.new_or_modified_features, [])
        self.assertEqual(g.impacted_endpoints, [])

    def test_markdown_fenced_blocks_still_parse(self):
        g = _parse_generation("```\n" + BLOCK_OUTPUT + "\n```")
        self.assertEqual(len(g.new_or_modified_features), 1)

    def test_garbage_raises_actionable_error(self):
        with self.assertRaises(ValueError) as ctx:
            _parse_generation("I cannot help with that request.")
        self.assertIn("FEATURE|STEPDEF", str(ctx.exception))


JSON_OUTPUT = '''\
{"analysis_summary": "x", "impacted_endpoints": ["GET /a"],
 "new_or_modified_features": [{"file_name": "f/src/test/resources/features/a.feature",
 "action": "CREATE", "gherkin_content": "Feature: A\\n  Scenario: S\\n    When x\\n"}]}
'''


class JsonFallbackTest(unittest.TestCase):
    def test_legacy_json_still_parses(self):
        g = _parse_generation(JSON_OUTPUT)
        self.assertEqual(g.impacted_endpoints, ["GET /a"])
        self.assertEqual(g.new_or_modified_step_definitions, [])

    def test_invalid_escape_is_repaired(self):
        # "\e" is not a valid JSON escape — the exact failure from the CI run.
        broken = '{"analysis_summary": "uses C:\\example path", "impacted_endpoints": [], "new_or_modified_features": []}'
        g = _parse_generation(broken)
        self.assertIn("example", g.analysis_summary)


if __name__ == "__main__":
    unittest.main()
