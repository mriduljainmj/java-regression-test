"""LangGraph nodes for the Cucumber regression test-generation pipeline."""

import logging
import re
import subprocess
import time
from pathlib import Path

import os
from openai import OpenAI
import json


from .prompts import RETRY_SUFFIX_TEMPLATE, SYSTEM_PROMPT, USER_PROMPT_TEMPLATE
from .state import GenerationResult, TestGenState

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 3
MAX_CONTEXT_CHARS = 10000  # guardrail for very large diffs/sources

# Free models are shared pools and get rate-limited upstream (429) without warning.
# Tried in order; on 429/5xx the next model is attempted, so one congested pool
# doesn't fail the whole run. Override the first choice with TESTGEN_MODEL.
MODELS = [
    os.environ.get("TESTGEN_MODEL", "openai/gpt-oss-120b:free"),
    "openai/gpt-oss-20b:free",
    "google/gemma-4-26b-a4b-it:free",
]

JAVA_SOURCE_MARKER = "src/main/java"
FEATURES_DIR_MARKER = "src/test/resources/features"


def _run(cmd: list[str], cwd: str) -> str:
    result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, check=True)
    return result.stdout


def collect_diff(state: TestGenState) -> TestGenState:
    """Compute the git diff between base and head and list changed files."""
    repo = state["repo_path"]
    base, head = state["base_ref"], state["head_ref"]

    diff = _run(["git", "diff", f"{base}..{head}", "--", "."], cwd=repo)
    changed = _run(["git", "diff", "--name-only", f"{base}..{head}"], cwd=repo)
    changed_files = [line.strip() for line in changed.splitlines() if line.strip()]

    java_changes = [f for f in changed_files if JAVA_SOURCE_MARKER in f and f.endswith(".java")]
    update: TestGenState = {"git_diff": diff, "changed_files": changed_files}
    if not java_changes:
        update["skipped_reason"] = (
            "No Java main-source changes between "
            f"{base} and {head}; nothing to generate tests for."
        )
    return update


def gather_context(state: TestGenState) -> TestGenState:
    """Read changed source files, existing feature files, and any API spec."""
    repo = Path(state["repo_path"])
    changed_files = state["changed_files"]

    # Full content of every changed main-source Java file, so the model sees the
    # surrounding class, not just the diff hunks.
    sources: list[str] = []
    for rel in changed_files:
        if JAVA_SOURCE_MARKER not in rel or not rel.endswith(".java"):
            continue
        path = repo / rel
        if path.is_file():
            sources.append(f"// FILE: {rel}\n{path.read_text(encoding='utf-8')}")

    # Step definitions are part of the reuse contract — include them so the model
    # knows exactly which step phrasings already have glue code.
    for step_def in repo.rglob("*StepDefinitions.java"):
        rel = step_def.relative_to(repo)
        sources.append(f"// FILE: {rel}\n{step_def.read_text(encoding='utf-8')}")

    features: list[str] = []
    for feature in sorted(repo.rglob("*.feature")):
        rel = feature.relative_to(repo)
        features.append(f"# FILE: {rel}\n{feature.read_text(encoding='utf-8')}")

    api_spec = ""
    for candidate in ("openapi.yaml", "openapi.yml", "openapi.json", "swagger.yaml", "swagger.json"):
        matches = list(repo.rglob(candidate))
        if matches:
            api_spec = matches[0].read_text(encoding="utf-8")
            break

    return {
        "target_component_context": "\n\n".join(sources)[:MAX_CONTEXT_CHARS],
        "existing_feature_examples": "\n\n".join(features)[:MAX_CONTEXT_CHARS],
        "api_spec": api_spec[:MAX_CONTEXT_CHARS] or "Not available.",
        "attempts": 0,
        "validation_errors": [],
    }





def generate_tests(state: TestGenState) -> TestGenState:
    client = OpenAI(
        api_key=os.environ["OPENROUTER_API_KEY"],
        base_url="https://openrouter.ai/api/v1",
        default_headers={
        "HTTP-Referer": "your-app",
        "X-Title": "testgen-agent"
        }
    )

    user_prompt = USER_PROMPT_TEMPLATE.format(
        target_component_context=state["target_component_context"],
        git_diff=state["git_diff"][:MAX_CONTEXT_CHARS],
        existing_feature_examples=state["existing_feature_examples"],
        api_spec=state["api_spec"],
    )

    if state.get("validation_errors"):
        errors = "\n".join(f"- {e}" for e in state["validation_errors"])
        user_prompt += RETRY_SUFFIX_TEMPLATE.format(errors=errors)

    full_prompt = f"""
    {SYSTEM_PROMPT}

    {user_prompt}

    IMPORTANT:
    Return ONLY valid JSON in this format:
    {{
    "analysis_summary": "string",
    "impacted_endpoints": ["string"],
    "new_or_modified_features": [
        {{
        "file_name": "string",
        "action": "CREATE or UPDATE",
        "gherkin_content": "string"
        }}
    ]
    }}
    """   
    response = None  # ✅ prevent crash
    last_error = None

    # Outer loop: fall back across models. Inner loop: retry each model with
    # exponential backoff (5s, 20s) — free-pool 429s usually clear in seconds.
    for model in MODELS:
        for attempt in range(3):
            try:
                response = client.chat.completions.create(
                    model=model,
                    messages=[{"role": "user", "content": full_prompt}],
                    temperature=0,
                )
                logger.info("Generated with model %s", model)
                break

            except Exception as e:
                last_error = e
                print(f"[{model}] attempt {attempt+1} failed: {e}")

                if "402" in str(e):
                    raise RuntimeError("OpenRouter billing required")

                if "404" in str(e):
                    print(f"[{model}] not found; falling back to next model")
                    break  # no point retrying a missing model

                if attempt < 2:
                    time.sleep(5 * (4 ** attempt))  # 5s, then 20s

        if response is not None:
            break

    # ✅ FINAL SAFETY CHECK
    if response is None:
        raise RuntimeError(
            f"All models exhausted ({', '.join(MODELS)}). Last error: {last_error}"
        )

    raw_text = response.choices[0].message.content.strip()

    # Extract JSON safely
    match = re.search(r"\{.*\}", raw_text, re.DOTALL)
    if not match:
        raise ValueError(f"No JSON found:\n{raw_text}")

    parsed = json.loads(match.group(0))
    generation = GenerationResult(**parsed)

    return {
        "generation": generation,
        "attempts": state.get("attempts", 0) + 1
    }




def validate_output(state: TestGenState) -> TestGenState:
    """Structurally validate the generated Gherkin before touching the repo."""
    repo = Path(state["repo_path"]).resolve()
    generation = state["generation"]
    errors: list[str] = []

    for feature in generation.new_or_modified_features:
        name = feature.file_name
        target = (repo / name).resolve()

        if not name.endswith(".feature"):
            errors.append(f"{name}: file name must end with .feature")
        if FEATURES_DIR_MARKER not in name:
            errors.append(f"{name}: must live under {FEATURES_DIR_MARKER}/")
        if not target.is_relative_to(repo):
            errors.append(f"{name}: path escapes the repository root")
        if feature.action == "UPDATE" and not target.is_file():
            errors.append(f"{name}: action is UPDATE but the file does not exist (use CREATE)")
        if feature.action == "CREATE" and target.is_file():
            errors.append(f"{name}: action is CREATE but the file already exists (use UPDATE)")

        lines = [line.strip() for line in feature.gherkin_content.splitlines()]
        if not any(line.startswith("Feature:") for line in lines):
            errors.append(f"{name}: content has no 'Feature:' declaration")
        if not any(line.startswith(("Scenario:", "Scenario Outline:")) for line in lines):
            errors.append(f"{name}: content has no scenarios")
        outline_count = sum(1 for line in lines if line.startswith("Scenario Outline:"))
        examples_count = sum(1 for line in lines if line.startswith("Examples:"))
        if outline_count > examples_count:
            errors.append(f"{name}: a Scenario Outline is missing its Examples table")

    if errors:
        logger.warning("Validation failed (attempt %d): %s", state["attempts"], errors)
    return {"validation_errors": errors}


def write_features(state: TestGenState) -> TestGenState:
    """Write the validated feature files into the repository."""
    repo = Path(state["repo_path"])
    written: list[str] = []
    for feature in state["generation"].new_or_modified_features:
        target = repo / feature.file_name
        target.parent.mkdir(parents=True, exist_ok=True)
        content = feature.gherkin_content
        if not content.endswith("\n"):
            content += "\n"
        target.write_text(content, encoding="utf-8")
        written.append(feature.file_name)
        logger.info("%s %s", feature.action, feature.file_name)
    return {"written_files": written}


def create_pull_request(state: TestGenState) -> TestGenState:
    """Commit the generated features on a new branch and open a PR via the gh CLI."""
    repo = state["repo_path"]
    generation = state["generation"]
    branch = f"testgen/{state['head_ref'][:12]}-{int(time.time())}"

    _run(["git", "checkout", "-b", branch], cwd=repo)
    _run(["git", "add", *state["written_files"]], cwd=repo)
    _run(
        ["git", "commit", "-m", "test: regenerate Cucumber regression tests\n\n"
         + generation.analysis_summary],
        cwd=repo,
    )
    _run(["git", "push", "-u", "origin", branch], cwd=repo)

    endpoints = "\n".join(f"- `{e}`" for e in generation.impacted_endpoints) or "- none"
    body = (
        "## Auto-generated regression tests\n\n"
        f"{generation.analysis_summary}\n\n"
        f"### Impacted endpoints\n{endpoints}\n\n"
        f"### Files\n" + "\n".join(f"- `{f}`" for f in state["written_files"]) + "\n\n"
        "Please review the scenarios before merging. Regression runs automatically "
        "after merge.\n\n"
        "🤖 Generated with [Claude Code](https://claude.com/claude-code)"
    )
    pr_url = _run(
        ["gh", "pr", "create",
         "--title", "test: update Cucumber regression suite for latest code changes",
         "--body", body,
         "--head", branch],
        cwd=repo,
    ).strip()
    logger.info("Opened PR: %s", pr_url)
    return {"pr_url": pr_url}
