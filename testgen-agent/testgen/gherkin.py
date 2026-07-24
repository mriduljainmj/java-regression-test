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
_STEP_ANNOTATION_RE = re.compile(
    # Match Java-style @Given("...") and C#-style [Given("...")] or [Given(@"...")].
    # Group 1 captures verbatim C# strings; group 2 captures regular escaped strings.
    r'(?:@|\[)(?:Given|When|Then|And|But)\s*\(\s*(?:@"((?:[^"]|"")*)"|"((?:[^"\\]|\\.)*)")\s*\)\]?'
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


def _decode_annotation_string(verbatim_value: str, regular_value: str) -> str:
    if verbatim_value is not None:
        # C# verbatim strings escape quotes as doubled double-quotes.
        return verbatim_value.replace('""', '"')
    return _unescape_java_string(regular_value or "")


def extract_step_patterns(java_source: str) -> list:
    """Return the cucumber expressions declared in a Java/C# glue file."""
    return [
        _decode_annotation_string(m.group(1), m.group(2))
        for m in _STEP_ANNOTATION_RE.finditer(java_source)
    ]


# Cucumber-JS glue calls the bindings as bare functions — Given("...")/When(...)/
# Then(...) — with no @ or [ prefix, and the pattern in a single- or double-quoted
# JS string. The (?<![\w.$]) lookbehind avoids matching method calls like
# `ctx.Given(`. Regex-literal patterns (/.../ ) are intentionally not extracted
# here (the generated glue uses cucumber-expression strings).
_JS_STEP_RE = re.compile(
    r'(?<![\w.$])(?:Given|When|Then|And|But)\s*\(\s*'
    r'(?:"((?:[^"\\]|\\.)*)"|\'((?:[^\'\\]|\\.)*)\')'
)


def extract_step_patterns_js(js_source: str) -> list:
    """Return the cucumber expressions declared in a Cucumber-JS glue file."""
    out = []
    for m in _JS_STEP_RE.finditer(js_source):
        raw = m.group(1) if m.group(1) is not None else m.group(2)
        out.append(_unescape_java_string(raw or ""))
    return out


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


def step_pattern_to_regex(pattern: str):
    """Compile a step definition pattern (regex-style or cucumber-expression)."""
    text = (pattern or "").strip()
    # SpecFlow/Cucumber regex definitions often use anchors/capture groups and
    # backslash tokens (e.g. ^... (\d+) ...$). Treat those as raw regex.
    looks_like_regex = (
        text.startswith("^")
        or text.endswith("$")
        or "\\d" in text
        or "(" in text
        or "[" in text
        or "|" in text
    )
    if looks_like_regex:
        candidate = text
        if not candidate.startswith("^"):
            candidate = "^" + candidate
        if not candidate.endswith("$"):
            candidate = candidate + "$"
        try:
            return re.compile(candidate)
        except re.error:
            # Fall back to cucumber-expression parsing if malformed regex slips in.
            pass
    return cucumber_expression_to_regex(text)


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
    examples_rows: list = []
    docstring_delim: Optional[str] = None

    def flush_outline():
        nonlocal pending_outline_steps, examples_header, examples_rows
        if pending_outline_steps:
            # Substitute EVERY data row, not just the first: a later row can hold
            # a value that is type-incompatible with the step's glue parameter
            # (e.g. "null" in an {int} slot) and must be caught too.
            row_values = (
                [dict(zip(examples_header, row)) for row in examples_rows]
                if examples_header and examples_rows
                else [{}]
            )
            for values in row_values:
                for raw in pending_outline_steps:
                    steps.append(
                        re.sub(r"<([^<>]+)>", lambda m: values.get(m.group(1).strip(), "1"), raw)
                    )
        pending_outline_steps = []
        examples_header = None
        examples_rows = []

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
                else:
                    examples_rows.append(cells)
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
    compiled = [step_pattern_to_regex(p) for p in step_patterns]
    undefined = []
    for step in extract_scenario_steps(gherkin_text):
        if not any(r.match(step) for r in compiled):
            undefined.append(step)
    # Deduplicate, preserve order.
    return list(dict.fromkeys(undefined))
