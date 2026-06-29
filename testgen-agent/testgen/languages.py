"""Language profiles: make the pipeline work for Java (Cucumber/JUnit) and
.NET (Reqnroll/SpecFlow) by isolating everything language-specific behind one
`LanguageProfile`. The nodes stay language-agnostic and read the active profile.

What actually differs between the two stacks:
  - source/glue file extension (.java vs .cs) and directory conventions
  - how step definitions are declared: Java `@Given("…")` vs C# `[Given(@"…")]`
  - the build/test command: `mvn test` vs `dotnet test`
  - how failures surface: a Cucumber JSON report vs `dotnet test` console output

What is the SAME (and why this is tractable): the Gherkin `.feature` files. A
scenario written for Cucumber runs unchanged under Reqnroll/SpecFlow.
"""

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass(frozen=True)
class LanguageProfile:
    name: str                     # "java" | "dotnet"
    label: str                    # human label for prompts/logs
    component_dir: str            # default component directory for this language
    source_ext: str               # main-source extension
    glue_ext: str                 # step-definition extension
    source_marker: str            # path fragment identifying MAIN source
    test_marker: str              # path fragment identifying test/glue code
    features_marker: str          # path fragment identifying .feature files
    glue_language: str            # "Java" | "C#" — for the prompt
    framework: str                # BDD framework name — for the prompt
    step_style: str               # "cucumber" | "regex" — how step text is matched
    step_attr_re: "re.Pattern"    # extracts step expressions from glue source
    test_cmd: list                # argv template; {pom}/{dir} filled at call time
    report_rel: Optional[str]     # relative Cucumber-JSON report path, or None
    prompt_notes: str             # language-specific glue-writing guidance
    build_files: tuple = ()       # filenames/globs that mark a component root


# Matches Java Cucumber step annotations: @Given("…"), @When("…"), @Then("…"), …
_JAVA_STEP_RE = re.compile(
    r'@(?:Given|When|Then|And|But)\s*\(\s*"((?:[^"\\]|\\.)*)"'
)

# Matches C# SpecFlow/Reqnroll step attributes: [Given(@"…")], [When("…")],
# [Then(@"…")], also [StepDefinition(@"…")]. Handles verbatim (@"…") and regular
# string literals.
_DOTNET_STEP_RE = re.compile(
    r'\[\s*(?:Given|When|Then|StepDefinition|Step)\s*\(\s*@?"((?:[^"\\]|\\.)*)"'
)


JAVA = LanguageProfile(
    name="java",
    label="Java / Spring Boot (Cucumber + JUnit)",
    component_dir="java-component",
    source_ext=".java",
    glue_ext=".java",
    source_marker="src/main/java",
    test_marker="src/test/java",
    features_marker="src/test/resources/features",
    glue_language="Java",
    framework="Cucumber (cucumber-java + JUnit Platform)",
    step_style="cucumber",
    step_attr_re=_JAVA_STEP_RE,
    test_cmd=["mvn", "-B", "-f", "{pom}", "test"],
    report_rel="target/cucumber-report.json",
    build_files=("pom.xml", "build.gradle", "build.gradle.kts"),
    prompt_notes=(
        "Write Java step definitions with cucumber-java annotations "
        '(@Given/@When/@Then) and cucumber expressions ({string}, {int}, '
        "{double}). Use RestAssured for HTTP calls and the shared scenario-scoped "
        "TestContext bean for state (last response, last-created ids) — never "
        "private fields in one glue class."
    ),
)

DOTNET = LanguageProfile(
    name="dotnet",
    label="C# / ASP.NET Core (Reqnroll/SpecFlow + xUnit)",
    component_dir="dotnet-component",
    source_ext=".cs",
    glue_ext=".cs",
    # ASP.NET project vs test project. Anything under the Tests project is glue;
    # everything else .cs is production source.
    source_marker="/Api/",
    test_marker="/Tests/",
    features_marker="/Features/",
    glue_language="C#",
    framework="Reqnroll (or SpecFlow — identical step attributes) + xUnit",
    step_style="regex",
    step_attr_re=_DOTNET_STEP_RE,
    test_cmd=["dotnet", "test", "{dir}"],
    report_rel=None,  # parse `dotnet test` console output instead of a JSON report
    build_files=("*.sln", "*.csproj"),
    prompt_notes=(
        "Write C# step definitions with Reqnroll/SpecFlow attributes "
        '([Given(@"…")], [When(@"…")], [Then(@"…")]) using REGEX step text with '
        "capture groups, e.g. [When(@\"a client creates a product with name '(.*)' "
        "and price (.*)\")]. Bind the class with [Binding]. Use HttpClient from a "
        "shared WebApplicationFactory fixture for requests, and a scenario-scoped "
        "context object (injected via Reqnroll context injection) for shared state "
        "— never static fields."
    ),
)

PROFILES = {p.name: p for p in (JAVA, DOTNET)}


def detect_language(repo: str, changed_files: list) -> LanguageProfile:
    """Pick the profile from the changed files first, then fall back to repo
    project markers. Prefers the language whose MAIN source actually changed."""
    repo_path = Path(repo)
    cs = [f for f in changed_files if f.endswith(".cs")]
    java = [f for f in changed_files if f.endswith(".java")]

    # Strongest signal: which language's source files are in the diff.
    if cs and not java:
        return DOTNET
    if java and not cs:
        return JAVA
    if cs and java:
        # Mixed diff — go with whichever has more changed source files.
        return DOTNET if len(cs) > len(java) else JAVA

    # No source files in the diff — fall back to what the repo contains.
    if any(repo_path.rglob("*.csproj")) or any(repo_path.rglob("*.sln")):
        if not any(repo_path.rglob("pom.xml")):
            return DOTNET
    return JAVA


def profile_for(name: str) -> LanguageProfile:
    if name not in PROFILES:
        raise ValueError(f"unknown language profile {name!r}; have {list(PROFILES)}")
    return PROFILES[name]


_SKIP_PARTS = {".git", "target", "bin", "obj", "build", "node_modules", ".venv", "venv"}


def _dir_has_build_file(d: Path, profile: LanguageProfile) -> bool:
    for pat in profile.build_files:
        if "*" in pat:
            if any(d.glob(pat)):
                return True
        elif (d / pat).is_file():
            return True
    return False


def discover_component_root(repo, profile: LanguageProfile, changed_files: list) -> str:
    """Find the component's build root for an ARBITRARY repo layout, so the agent
    isn't tied to the sample's `java-component/` etc. Returns a path relative to
    the repo (or "." for the repo root).

    Strategy: (1) walk up from each changed source file to the nearest build file
    (pom.xml/gradle for Java, .sln/.csproj for .NET — .sln preferred so
    `dotnet test` covers the whole solution); (2) else the shallowest build file
    in the repo; (3) else the repo root."""
    repo = Path(repo).resolve()

    def rel(d: Path) -> str:
        r = d.resolve().relative_to(repo)
        return str(r) if str(r) != "." else "."

    def _dir_matches(d: Path, pat: str) -> bool:
        return any(d.glob(pat)) if "*" in pat else (d / pat).is_file()

    # 1. Walk up from a changed source file, honoring build-file PREFERENCE across
    #    levels: a higher .sln beats a nearer .csproj (so `dotnet test` runs the
    #    whole solution), and pom.xml beats gradle. Patterns are in preference order.
    for cf in changed_files:
        if not cf.endswith(profile.source_ext):
            continue
        for pat in profile.build_files:
            d = (repo / cf).parent
            while True:
                if _dir_matches(d, pat):
                    return rel(d)
                if d == repo or repo not in d.parents:
                    break
                d = d.parent
        break  # only consider the first changed source file

    # 2. Shallowest build file anywhere in the repo. For .NET, a directory with a
    #    .sln wins over one with only a .csproj (so `dotnet test` runs everything).
    def candidates(pattern):
        out = []
        for p in repo.rglob(pattern):
            if not any(part in _SKIP_PARTS for part in p.relative_to(repo).parts):
                out.append(p.parent)
        return out

    for pat in profile.build_files:  # build_files is ordered by preference
        dirs = candidates(pat)
        if dirs:
            return rel(min(dirs, key=lambda d: len(d.relative_to(repo).parts)))

    # 3. Fallback: repo root.
    return "."


# --------------------------------------------------------------------------- #
# Step-definition parsing + matching (shared by both languages)
# --------------------------------------------------------------------------- #
_PARAM_REGEX = {
    "int": r"-?\d+", "long": r"-?\d+", "short": r"-?\d+", "byte": r"-?\d+",
    "biginteger": r"-?\d+", "float": r"-?\d+(?:[.,]\d+)?",
    "double": r"-?\d+(?:[.,]\d+)?", "bigdecimal": r"-?\d+(?:[.,]\d+)?",
    "word": r"[^\s]+", "string": r'"[^"]*"', "": r".*",
}


def _unescape(s: str) -> str:
    return s.replace('\\"', '"').replace("\\\\", "\\")


def extract_step_patterns(source: str, profile: LanguageProfile) -> list:
    """Return the step expressions declared in a glue source file."""
    return [_unescape(m.group(1)) for m in profile.step_attr_re.finditer(source)]


def _cucumber_to_regex(expr: str) -> str:
    parts = []
    for part in re.split(r"(\{[^{}]*\})", expr):
        if part.startswith("{") and part.endswith("}"):
            parts.append(_PARAM_REGEX.get(part[1:-1].strip().lower(), r".+?"))
            continue
        piece = re.escape(part)
        piece = re.sub(r"\\\(([^()]*?)\\\)", r"(?:\1)?", piece)          # optional (s)
        piece = re.sub(r"(\w+(?:/\w+)+)",
                       lambda m: "(?:" + "|".join(m.group(1).split("/")) + ")", piece)
        parts.append(piece)
    return "".join(parts)


def compile_step(expr: str, style: str = "cucumber"):
    """Compile a step expression to a regex matching concrete step text.

    style="cucumber" (Java, and Reqnroll cucumber mode): the expression uses
    cucumber syntax — {param} placeholders, optional `(s)`, alternation `a/b`.
    style="regex" (C# SpecFlow/Reqnroll regex attributes): the expression is a
    raw regex — UNLESS it contains a {param}, in which case it's a cucumber
    expression (Reqnroll supports both, so we detect per-expression there)."""
    if style == "cucumber" or re.search(r"\{\w*\}", expr):
        body = _cucumber_to_regex(expr)
    else:
        body = expr  # raw regex
    try:
        return re.compile("^" + body + "$")
    except re.error:
        # A malformed regex in glue shouldn't crash matching — match nothing.
        return re.compile(r"(?!x)x")
