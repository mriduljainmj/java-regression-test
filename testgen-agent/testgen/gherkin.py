"""Feature-file parsing + step matching, for BOTH languages.

The single biggest failure mode of LLM-generated Gherkin is an invented step
phrasing with no matching step definition — it passes structural checks, lands
in the PR, and only fails when the tests run. This module parses concrete steps
out of a `.feature` file and checks each against the glue's step expressions
(extracted per the active LanguageProfile), so the error is caught pre-PR and
fed back to the model.

Step extraction and expression→regex compilation are language-specific and live
in `languages.py` (Java `@Given("…")` cucumber expressions, or C# `[Given(@"…")]`
regex/cucumber attributes). Feature parsing here is identical for both stacks.
"""

import re
from typing import Optional

from .languages import JAVA, compile_step
from .languages import extract_step_patterns as _extract_step_patterns

_STEP_KEYWORDS = ("Given ", "When ", "Then ", "And ", "But ", "* ")


def extract_step_patterns(source: str, profile=JAVA) -> list:
    """Return the step expressions declared in a glue file. Defaults to the Java
    profile so existing callers/tests keep working."""
    return _extract_step_patterns(source, profile)


def cucumber_expression_to_regex(expr: str):
    """Backward-compatible alias for the shared step compiler."""
    return compile_step(expr)


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


def find_undefined_steps(gherkin_text: str, step_patterns: list, style: str = "cucumber") -> list:
    """Return generated step texts that match no known step definition."""
    compiled = [compile_step(p, style) for p in step_patterns]
    undefined = []
    for step in extract_scenario_steps(gherkin_text):
        if not any(r.match(step) for r in compiled):
            undefined.append(step)
    # Deduplicate, preserve order.
    return list(dict.fromkeys(undefined))
