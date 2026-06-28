"""Tests for language detection and the .NET (C#) glue parsing / matching."""

import tempfile
import unittest
from pathlib import Path

from testgen.languages import (
    DOTNET,
    JAVA,
    compile_step,
    detect_language,
    extract_step_patterns,
)


class DetectionTest(unittest.TestCase):
    def test_java_changed_files(self):
        p = detect_language(".", ["java-component/src/main/java/com/example/Foo.java"])
        self.assertEqual(p.name, "java")

    def test_dotnet_changed_files(self):
        p = detect_language(".", ["dotnet-component/Api/Controllers/ProductsController.cs"])
        self.assertEqual(p.name, "dotnet")

    def test_mixed_diff_goes_with_majority(self):
        p = detect_language(".", ["a/X.cs", "b/Y.cs", "c/Z.java"])
        self.assertEqual(p.name, "dotnet")

    def test_no_source_files_falls_back_to_repo_markers(self):
        with tempfile.TemporaryDirectory() as d:
            repo = Path(d)
            (repo / "Api").mkdir()
            (repo / "Api" / "App.csproj").write_text("<Project/>")
            p = detect_language(str(repo), ["README.md"])
            self.assertEqual(p.name, "dotnet")

    def test_empty_repo_defaults_to_java(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(detect_language(d, []).name, "java")


CSHARP_GLUE = '''
using Reqnroll;

[Binding]
public class ProductSteps
{
    private readonly ScenarioContext _ctx;
    public ProductSteps(ScenarioContext ctx) { _ctx = ctx; }

    [Given(@"the product catalog is empty")]
    public void GivenEmpty() { }

    [When(@"a client creates a product with name '(.*)' and price (.*)")]
    public void WhenCreate(string name, decimal price) { }

    [Then(@"the response status should be (\\d+)")]
    public void ThenStatus(int code) { }
}
'''


class DotnetGlueTest(unittest.TestCase):
    def test_extracts_csharp_step_attributes(self):
        patterns = extract_step_patterns(CSHARP_GLUE, DOTNET)
        self.assertEqual(len(patterns), 3)
        self.assertIn("the product catalog is empty", patterns)
        self.assertIn("a client creates a product with name '(.*)' and price (.*)", patterns)

    def test_java_regex_does_not_match_csharp(self):
        # The Java extractor must not pick up C# [Given(...)] attributes.
        self.assertEqual(extract_step_patterns(CSHARP_GLUE, JAVA), [])


class StepMatchingTest(unittest.TestCase):
    def test_csharp_regex_step_matches_concrete_text(self):
        r = compile_step("a client creates a product with name '(.*)' and price (.*)", "regex")
        self.assertTrue(r.match("a client creates a product with name 'Laptop' and price 9.99"))

    def test_csharp_numeric_regex(self):
        r = compile_step(r"the response status should be (\d+)", "regex")
        self.assertTrue(r.match("the response status should be 404"))
        self.assertFalse(r.match("the response status should be abc"))

    def test_java_cucumber_alternation_without_param(self):
        # The bug the refactor exposed: alternation with no {param} must still be
        # treated as cucumber under the java style, not as a raw regex.
        r = compile_step("the item is/are visible", "cucumber")
        self.assertTrue(r.match("the item is visible"))
        self.assertTrue(r.match("the item are visible"))

    def test_reqnroll_cucumber_expression_under_regex_style(self):
        # Reqnroll allows cucumber expressions too — {param} forces cucumber mode
        # even when the profile's default style is regex.
        r = compile_step("a product with id {int}", "regex")
        self.assertTrue(r.match("a product with id 42"))


if __name__ == "__main__":
    unittest.main()
