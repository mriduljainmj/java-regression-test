"""Step-definition matching: verify generated Gherkin steps against Java glue.

The single biggest failure mode of LLM-generated Gherkin is an invented step
phrasing with no matching step definition — it passes structural checks, lands
in the PR, and only fails when Cucumber runs. This module parses the cucumber
expressions out of the Java glue code and checks every generated step against
them, so the error is caught pre-PR and fed back to the model.

Supported cucumber-expression syntax: {int}/{long}/{short}/{byte}/{biginteger},
{float}/{double}/{bigdecimal}, {word}, {string}, {} (anonymous), optional
text `(s)`, and alternation `one/two`. Custom parameter types are matched
loosely (any text) rather than rejected.
"""

import re
from typing import Optional

# Matches @Given("..."), @When("..."), etc. in Java source, including escaped
# quotes inside the annotation string.
_STEP_ANNOTATION_RE = re.compile(
    r'@(?:Given|When|Then|And|But)\s*\(\s*"((?:[^"\\]|\\.)*)"'
)

_PARAM_REGEX = {
    "int": r"-?\d+",
    "long": r"-?\d+",
    "short": r"-?\d+",
    "byte": r"-?\d+",
    "biginteger": r"-?\d+",
    "float": r"-?\d+(?:[.,]\d+)?",
    "double": r"-?\d+(?:[.,]\d+)?",
    "bigdecimal": r"-?\d+(?:[.,]\d+)?",
    "word": r"[^\s]+",
    "string": r'"[^"]*"',
    "": r".*",
}

_STEP_KEYWORDS = ("Given ", "When ", "Then ", "And ", "But ", "* ")


def _unescape_java_string(s: str) -> str:
    return s.replace('\\"', '"').replace("\\\\", "\\")


def extract_step_patterns(java_source: str) -> list:
    """Return the cucumber expressions declared in a Java glue file."""
    return [_unescape_java_string(m.group(1)) for m in _STEP_ANNOTATION_RE.finditer(java_source)]


def cucumber_expression_to_regex(expr: str):
    """Compile a cucumber expression into a regex matching concrete step text."""
    regex_parts = []
    # Split on {param} placeholders, keeping them as their own tokens.
    for part in re.split(r"(\{[^{}]*\})", expr):
        if part.startswith("{") and part.endswith("}"):
            param = part[1:-1].strip().lower()
            # Unknown/custom parameter types match loosely instead of failing.
            regex_parts.append(_PARAM_REGEX.get(param, r".+?"))
            continue
        piece = re.escape(part)
        # Optional text: "product(s)" matches "product" and "products".
        piece = re.sub(r"\\\(([^()]*?)\\\)", r"(?:\1)?", piece)
        # Alternation: "is/are" matches "is" or "are". re.escape (3.7+) leaves
        # "/" unescaped, so split on the literal slash between word tokens.
        piece = re.sub(
            r"(\w+(?:/\w+)+)",
            lambda m: "(?:" + "|".join(m.group(1).split("/")) + ")",
            piece,
        )
        regex_parts.append(piece)
    return re.compile("^" + "".join(regex_parts) + "$")


def extract_scenario_steps(gherkin_text: str) -> list:
    """Extract concrete step texts from a feature file.

    Skips comments, tags, docstring bodies, and data-table rows. For Scenario
    Outlines, <placeholder> tokens are substituted with values from the first
    Examples data row so the result is matchable against glue regexes.
    """
    steps: list = []
    pending_outline_steps: list = []
    in_outline = False
    examples_header: Optional[list] = None
    examples_first_row: Optional[list] = None
    docstring_delim: Optional[str] = None

    def flush_outline():
        nonlocal pending_outline_steps, examples_header, examples_first_row
        if pending_outline_steps:
            values = {}
            if examples_header and examples_first_row:
                values = dict(zip(examples_header, examples_first_row))
            for raw in pending_outline_steps:
                steps.append(
                    re.sub(r"<([^<>]+)>", lambda m: values.get(m.group(1).strip(), "1"), raw)
                )
        pending_outline_steps = []
        examples_header = None
        examples_first_row = None

    for raw_line in gherkin_text.splitlines():
        line = raw_line.strip()

        if docstring_delim:
            if line.startswith(docstring_delim):
                docstring_delim = None
            continue
        if line.startswith(('"""', "```")):
            docstring_delim = line[:3]
            continue

        if not line or line.startswith(("#", "@")):
            continue

        if line.startswith(("Scenario Outline:", "Scenario Template:")):
            flush_outline()
            in_outline = True
            continue
        if line.startswith(("Scenario:", "Background:", "Feature:", "Rule:", "Example:")):
            flush_outline()
            in_outline = False
            continue
        if line.startswith(("Examples:", "Scenarios:")):
            continue

        if line.startswith("|"):
            cells = [c.strip() for c in line.strip("|").split("|")]
            if in_outline:
                if examples_header is None:
                    examples_header = cells
                elif examples_first_row is None:
                    examples_first_row = cells
            continue

        for kw in _STEP_KEYWORDS:
            if line.startswith(kw):
                text = line[len(kw):].strip()
                if in_outline:
                    pending_outline_steps.append(text)
                else:
                    steps.append(text)
                break

    flush_outline()
    return steps


def find_undefined_steps(gherkin_text: str, step_patterns: list) -> list:
    """Return generated step texts that match no known step definition."""
    compiled = [cucumber_expression_to_regex(p) for p in step_patterns]
    undefined = []
    for step in extract_scenario_steps(gherkin_text):
        if not any(r.match(step) for r in compiled):
            undefined.append(step)
    # Deduplicate, preserve order.
    return list(dict.fromkeys(undefined))
