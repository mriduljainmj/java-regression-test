"""LangGraph nodes for the Cucumber regression test-generation pipeline."""

import json
import logging
import os
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Optional

from openai import OpenAI
from pydantic import ValidationError

from . import ado
from .gherkin import find_undefined_steps
from .languages import JAVA, detect_language, extract_step_patterns, profile_for
from .prompts import (
    LANGUAGE_CONTEXT_TEMPLATE,
    OUTPUT_FORMAT_INSTRUCTIONS,
    RETRY_SUFFIX_TEMPLATE,
    SYSTEM_PROMPT,
    TEST_FAILURE_TEMPLATE,
    USER_PROMPT_TEMPLATE,
)
from .state import FeatureFile, GenerationResult, StepDefinitionFile, TestGenState


def _profile(state: TestGenState):
    """The active LanguageProfile for this run (defaults to Java)."""
    return profile_for(state.get("language", "java"))

logger = logging.getLogger(__name__)

# Safety cap on total model calls (structural retries + rotation). Set high
# enough that the execution-feedback rounds below never trip it.
MAX_ATTEMPTS = int(os.environ.get("TESTGEN_MAX_ATTEMPTS", "6"))

# Execution-feedback loop: run the generated tests and feed failures back to the
# model, at most this many times (the user-facing "max 3 retries").
MAX_TEST_ATTEMPTS = int(os.environ.get("TESTGEN_MAX_TEST_ATTEMPTS", "3"))

TEST_TIMEOUT = int(os.environ.get("TESTGEN_TEST_TIMEOUT", "900"))

# Per-section guardrail for very large diffs/sources. ~15K tokens per section —
# comfortably inside the 131K-token windows of the free models below, but large
# enough that the full component source + features + step definitions fit.
MAX_CONTEXT_CHARS = int(os.environ.get("TESTGEN_MAX_CONTEXT_CHARS", "60000"))

# Free models are shared pools and get rate-limited upstream (429) without warning.
# Tried in order; on 429/5xx the next model is attempted, so one congested pool
# doesn't fail the whole run. Override the whole chain with TESTGEN_MODELS
# (comma-separated) or just the first choice with TESTGEN_MODEL.
if os.environ.get("TESTGEN_MODELS"):
    MODELS = [m.strip() for m in os.environ["TESTGEN_MODELS"].split(",") if m.strip()]
else:
    MODELS = [
        os.environ.get("TESTGEN_MODEL", "openai/gpt-oss-120b:free"),
        "openai/gpt-oss-20b:free",
        "google/gemma-4-26b-a4b-it:free",
    ]

# GitHub sends this as `before` on the first push to a branch.
_ZERO_SHA = re.compile(r"^0{7,40}$")
# git's well-known hash of the empty tree: diffing against it shows every file
# as added, which is the correct "everything is new" baseline.
_EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"

# Directories that should never feed the model or the validators.
_SKIP_DIRS = {".git", "target", "build", "node_modules", ".venv", "venv", ".idea"}


def _run(cmd: list, cwd: str) -> str:
    """Run a command; on failure raise with stderr included so CI logs are usable."""
    result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(
            f"command failed ({result.returncode}): {' '.join(cmd)}\n{result.stderr.strip()}"
        )
    return result.stdout


def _iter_repo_files(repo: Path, pattern: str):
    """rglob that skips build output, virtualenvs, and VCS internals."""
    for path in sorted(repo.rglob(pattern)):
        if not any(part in _SKIP_DIRS for part in path.relative_to(repo).parts):
            yield path


def _read(path: Path) -> str:
    # errors="replace": a stray non-UTF8 byte in one file shouldn't kill the run.
    return path.read_text(encoding="utf-8", errors="replace")


def _ref_exists(repo: str, ref: str) -> bool:
    return (
        subprocess.run(
            ["git", "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}"],
            cwd=repo, capture_output=True,
        ).returncode
        == 0
    )


def _resolve_base(repo: str, base: str, head: str) -> str:
    """Make the base ref usable.

    Handles the CI edge cases: GitHub sends an all-zero `before` SHA on the
    first push to a branch, and a force-push can make `before` unreachable.
    Fall back to the head's parent, and for a single-commit repo to the empty
    tree (so the whole component counts as changed).
    """
    if not _ZERO_SHA.match(base) and _ref_exists(repo, base):
        return base
    if _ref_exists(repo, f"{head}~1"):
        logger.warning("base %r unusable; falling back to %s~1", base, head)
        return f"{head}~1"
    logger.warning("base %r unusable and %s has no parent; diffing against empty tree", base, head)
    return _EMPTY_TREE


def collect_diff(state: TestGenState) -> TestGenState:
    """Compute the git diff between base and head and list changed files."""
    repo = state["repo_path"]
    head = state["head_ref"]

    if not _ref_exists(repo, head):
        raise RuntimeError(f"head ref {head!r} does not exist in {repo}")
    base = _resolve_base(repo, state["base_ref"], head)

    diff = _run(["git", "diff", f"{base}..{head}", "--", "."], cwd=repo)
    changed = _run(["git", "diff", "--name-only", f"{base}..{head}"], cwd=repo)
    changed_files = [line.strip() for line in changed.splitlines() if line.strip()]
    # Commit messages in range — used to auto-detect ADO work items (AB#123).
    commit_messages = subprocess.run(
        ["git", "log", "--format=%B", f"{base}..{head}"],
        cwd=repo, capture_output=True, text=True,
    ).stdout

    # Detect the language from the changed files, then apply that profile's
    # notion of "main source" to decide whether there's anything to test.
    profile = detect_language(repo, changed_files)
    logger.info("Detected language: %s", profile.label)
    src_changes = [
        f for f in changed_files
        if profile.source_marker in f and f.endswith(profile.source_ext)
    ]
    update: TestGenState = {
        "git_diff": diff, "changed_files": changed_files, "language": profile.name,
        "commit_messages": commit_messages,
    }
    if not src_changes:
        update["skipped_reason"] = (
            f"No {profile.label} main-source changes between "
            f"{base} and {head}; nothing to generate tests for."
        )
    return update


def fetch_ticket_context(state: TestGenState) -> TestGenState:
    """Pull ADO work-item intent (description + acceptance criteria + comments)
    and combine with any direct reviewer input. No-ops gracefully when ADO isn't
    configured — the work-item ids come from --work-item or are auto-detected
    from the commit messages (AB#123)."""
    reviewer_input = (state.get("reviewer_input") or "").strip()

    ids = state.get("work_item_ids") or []
    if not ids:
        ids = ado.extract_work_item_ids(state.get("commit_messages", ""))

    work_items = []
    if ids and ado.is_configured():
        logger.info("Fetching ADO work item(s): %s", ", ".join(ids))
        work_items = [ado.fetch_work_item(wid) for wid in ids]
    elif ids and not ado.is_configured():
        logger.info("Work item(s) referenced (%s) but ADO not configured — skipping fetch",
                    ", ".join(ids))

    ticket_context = ado.format_ticket_context(work_items)

    # Reviewer comments from the ticket augment any directly-supplied guidance.
    ticket_comments = ado.collect_reviewer_comments(work_items)
    if ticket_comments:
        joined = "\n".join(f"- {c}" for c in ticket_comments)
        reviewer_input = (reviewer_input + "\n" if reviewer_input else "") + \
            "From the work-item discussion:\n" + joined

    return {
        "ticket_context": ticket_context,
        "reviewer_input": reviewer_input or "Not provided.",
    }


def gather_context(state: TestGenState) -> TestGenState:
    """Read source files, glue code, existing features, and any API spec."""
    repo = Path(state["repo_path"])
    changed_files = state["changed_files"]
    profile = _profile(state)

    # All main-source files, with the changed ones FIRST so truncation by
    # MAX_CONTEXT_CHARS sacrifices the least relevant context. The model needs
    # the unchanged files too: stale-assertion detection means executing the
    # existing scenarios against the post-change code, and the behavior an
    # assertion depends on often lives outside the diffed files.
    changed_src = [
        rel for rel in changed_files
        if profile.source_marker in rel and rel.endswith(profile.source_ext)
    ]
    other_src = [
        str(p.relative_to(repo))
        for p in _iter_repo_files(repo, f"*{profile.source_ext}")
        if profile.source_marker in str(p) and str(p.relative_to(repo)) not in changed_src
    ]
    sources: list = []
    for rel in changed_src + other_src:
        path = repo / rel
        if path.is_file():
            marker = "CHANGED IN THIS DIFF" if rel in changed_src else "unchanged"
            sources.append(f"// FILE ({marker}): {rel}\n{_read(path)}")

    # Glue code is the reuse contract. Find it by content (any test-source file
    # with step annotations/attributes), not by file-naming convention, and keep
    # the parsed step expressions for the post-generation validator.
    step_patterns: list = []
    for src in _iter_repo_files(repo, f"*{profile.glue_ext}"):
        rel = str(src.relative_to(repo))
        if profile.test_marker not in rel:
            continue
        text = _read(src)
        patterns = extract_step_patterns(text, profile)
        if patterns:
            step_patterns.extend(patterns)
            sources.append(f"// FILE (step definitions): {rel}\n{text}")
    if not step_patterns:
        logger.warning("no step definitions found — undefined-step validation disabled")

    features: list = []
    for feature in _iter_repo_files(repo, "*.feature"):
        rel = feature.relative_to(repo)
        features.append(f"# FILE: {rel}\n{_read(feature)}")

    api_spec = ""
    for candidate in ("openapi.yaml", "openapi.yml", "openapi.json", "swagger.yaml", "swagger.json"):
        matches = list(_iter_repo_files(repo, candidate))
        if matches:
            api_spec = _read(matches[0])
            break

    return {
        "target_component_context": "\n\n".join(sources)[:MAX_CONTEXT_CHARS],
        "existing_feature_examples": "\n\n".join(features)[:MAX_CONTEXT_CHARS],
        "api_spec": api_spec[:MAX_CONTEXT_CHARS] or "Not available.",
        "step_patterns": step_patterns,
        "attempts": 0,
        "validation_errors": [],
    }


def _strip_markdown_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n", "", text)
        text = re.sub(r"\n```$", "", text.strip())
    return text


_FILE_BLOCK_RE = re.compile(
    r"===\s*(FEATURE|STEPDEF)\s+(CREATE|UPDATE)\s+(\S+)\s*===\s*\n(.*?)\n\s*===\s*END\s*===",
    re.DOTALL | re.IGNORECASE,
)


def _parse_file_blocks(text: str) -> GenerationResult:
    """Parse the delimited-block output format (the preferred format: raw file
    contents need no escaping, which weak models reliably get wrong in JSON)."""
    analysis_match = re.search(r"^ANALYSIS:\s*(.+)$", text, re.MULTILINE)
    endpoints_match = re.search(r"^ENDPOINTS:\s*(.+)$", text, re.MULTILINE)
    blocks = _FILE_BLOCK_RE.findall(text)

    if not blocks and not analysis_match:
        raise ValueError(
            "no '=== FEATURE|STEPDEF CREATE|UPDATE <path> ===' file blocks and "
            "no ANALYSIS line found"
        )

    endpoints = []
    if endpoints_match:
        endpoints = [e.strip() for e in endpoints_match.group(1).split(",")
                     if e.strip() and e.strip().lower() not in ("none", "n/a")]

    features, stepdefs = [], []
    for kind, action, path, content in blocks:
        if kind.upper() == "FEATURE":
            features.append(FeatureFile(
                file_name=path, action=action.upper(), gherkin_content=content,
            ))
        else:
            stepdefs.append(StepDefinitionFile(
                file_name=path, action=action.upper(), content=content,
            ))

    return GenerationResult(
        impacted_endpoints=endpoints,
        analysis_summary=analysis_match.group(1).strip() if analysis_match else "",
        new_or_modified_features=features,
        new_or_modified_step_definitions=stepdefs,
    )


def _repair_json_escapes(text: str) -> str:
    """Escape lone backslashes that aren't valid JSON escapes — the most common
    model error when Java source ends up inside a JSON string."""
    return re.sub(r'\\(?!["\\/bfnrtu])', r"\\\\", text)


def _parse_json(text: str) -> GenerationResult:
    """Legacy JSON format, kept as a fallback for models that emit it anyway."""
    candidates = [text]
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match and match.group(0) != text:
        candidates.append(match.group(0))
    candidates += [_repair_json_escapes(c) for c in list(candidates)]

    parsed = None
    last_err = None
    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
            break
        except json.JSONDecodeError as e:
            last_err = e
    if parsed is None:
        raise ValueError(f"response contained invalid JSON: {last_err}")
    try:
        return GenerationResult.model_validate(parsed)
    except ValidationError as e:
        compact = "; ".join(
            f"{'.'.join(str(p) for p in err['loc'])}: {err['msg']}" for err in e.errors()
        )
        raise ValueError(f"JSON did not match the required schema: {compact}")


def _parse_generation(raw_text: str) -> GenerationResult:
    """Parse model output into a GenerationResult; raise ValueError with a
    model-actionable message on any failure."""
    text = _strip_markdown_fences(raw_text)

    # Preferred: delimited file blocks. Fallback: legacy JSON.
    if _FILE_BLOCK_RE.search(text) or text.lstrip().upper().startswith("ANALYSIS:"):
        try:
            return _parse_file_blocks(text)
        except (ValueError, ValidationError) as block_err:
            if not text.lstrip().startswith("{"):
                raise ValueError(str(block_err))
    if text.lstrip().startswith("{"):
        return _parse_json(text)
    return _parse_file_blocks(text)  # raises with the block-format guidance


def generate_tests(state: TestGenState) -> TestGenState:
    """Call the model (with model fallback + backoff) and parse its output.

    Parse failures do NOT crash the run: they are returned as validation_errors
    so the graph's retry loop feeds them back to the model, exactly like Gherkin
    validation failures.
    """
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY is not set")
    client = OpenAI(
        api_key=api_key,
        base_url="https://openrouter.ai/api/v1",
        default_headers={
            "HTTP-Referer": "your-app",
            "X-Title": "testgen-agent",
        },
    )

    profile = _profile(state)
    user_prompt = LANGUAGE_CONTEXT_TEMPLATE.format(
        label=profile.label,
        glue_language=profile.glue_language,
        framework=profile.framework,
        glue_ext=profile.glue_ext,
        features_marker=profile.features_marker,
        test_marker=profile.test_marker,
        notes=profile.prompt_notes,
    ) + USER_PROMPT_TEMPLATE.format(
        target_component_context=state["target_component_context"],
        git_diff=state["git_diff"][:MAX_CONTEXT_CHARS],
        existing_feature_examples=state["existing_feature_examples"],
        api_spec=state["api_spec"],
        ticket_context=state.get("ticket_context", "Not provided.")[:MAX_CONTEXT_CHARS],
        reviewer_input=state.get("reviewer_input", "Not provided.")[:MAX_CONTEXT_CHARS],
    )

    if state.get("validation_errors"):
        errors = "\n".join(f"- {e}" for e in state["validation_errors"])
        user_prompt += RETRY_SUFFIX_TEMPLATE.format(errors=errors)

    # Runtime failures from a prior `mvn test` — the strongest signal we have,
    # because it reflects how the tests actually behave against the real code.
    if state.get("test_failures"):
        failures = "\n".join(state["test_failures"])
        user_prompt += TEST_FAILURE_TEMPLATE.format(failures=failures)

    full_prompt = f"""
    {SYSTEM_PROMPT}

    {user_prompt}

    {OUTPUT_FORMAT_INSTRUCTIONS}
    """

    response_text: Optional[str] = None
    last_error: Optional[Exception] = None

    # Validation-retry diversity: re-asking the same model after it failed
    # validation tends to reproduce the same misunderstanding. Rotate the chain
    # so later attempts start from a different model.
    rotation = state.get("attempts", 0) % len(MODELS)
    models = MODELS[rotation:] + MODELS[:rotation]

    # Outer loop: fall back across models. Inner loop: retry each model with
    # exponential backoff (5s, 20s) — free-pool 429s usually clear in seconds.
    for model in models:
        retries_left = 3
        while retries_left > 0 and response_text is None:
            try:
                response = client.chat.completions.create(
                    model=model,
                    messages=[{"role": "user", "content": full_prompt}],
                    temperature=0,
                )
                content = response.choices[0].message.content
                if not content or not content.strip():
                    raise ValueError("model returned an empty response")
                response_text = content
                logger.info("Generated with model %s", model)
            except Exception as e:
                last_error = e
                # Typed status from the SDK; substring checks on str(e) can
                # false-positive (digits appear in IDs and token counts).
                status = getattr(e, "status_code", None)
                logger.warning("[%s] failed (status=%s): %s", model, status, e)
                if status == 402:
                    raise RuntimeError("OpenRouter billing required") from e
                if status in (400, 404):
                    break  # bad request shape or model removed — next model
                retries_left -= 1
                if retries_left > 0:
                    time.sleep(5 * 4 ** (2 - retries_left))  # 5s, then 20s
        if response_text is not None:
            break

    if response_text is None:
        raise RuntimeError(
            f"All models exhausted ({', '.join(MODELS)}). Last error: {last_error}"
        )

    attempts = state.get("attempts", 0) + 1
    try:
        generation = _parse_generation(response_text)
    except ValueError as e:
        logger.warning("attempt %d produced unparseable output: %s", attempts, e)
        return {
            "generation": None,
            "attempts": attempts,
            "validation_errors": [
                f"Your previous response could not be used: {e}. "
                "Follow the OUTPUT FORMAT exactly: an ANALYSIS line, an ENDPOINTS "
                "line, then one '=== FEATURE|STEPDEF CREATE|UPDATE <path> ===' "
                "block per file ending with '=== END ==='. Raw file contents only "
                "— no JSON, no markdown fences."
            ],
        }
    return {"generation": generation, "attempts": attempts, "validation_errors": []}


def validate_output(state: TestGenState) -> TestGenState:
    """Validate generated Gherkin (structure, paths, CREATE/UPDATE consistency,
    and that every step matches an existing step definition)."""
    generation = state.get("generation")
    if generation is None:
        # generate_tests already recorded parse errors; pass them through.
        return {}

    repo = Path(state["repo_path"]).resolve()
    profile = _profile(state)
    step_patterns = state.get("step_patterns", [])
    errors: list = []
    seen_names = set()

    # Validate proposed glue first: its step patterns extend the set the
    # generated Gherkin is allowed to use.
    generated_patterns: list = []
    for glue in generation.new_or_modified_step_definitions:
        name = glue.file_name.lstrip("./")
        target = (repo / name).resolve()

        if name in seen_names:
            errors.append(f"{name}: appears more than once in the output")
        seen_names.add(name)

        if not name.endswith(profile.glue_ext):
            errors.append(f"{name}: step-definition file name must end with {profile.glue_ext}")
        if profile.test_marker not in name:
            errors.append(f"{name}: step definitions must live under a {profile.test_marker} path")
        if not target.is_relative_to(repo):
            errors.append(f"{name}: path escapes the repository root")

        patterns_in_file = extract_step_patterns(glue.content, profile)
        if not patterns_in_file:
            errors.append(
                f"{name}: contains no step definitions ({profile.glue_language} "
                "step annotations/attributes) — if no new glue is needed, return "
                "an empty new_or_modified_step_definitions list"
            )
        # The real invariant (independent of the CREATE/UPDATE label): if the file
        # already exists, the new content must keep every step it currently has —
        # otherwise existing scenarios break. We DON'T reject on a CREATE/UPDATE
        # label mismatch: the model returns full content either way, and rejecting
        # it makes the retry loop thrash once a prior attempt has written the file.
        if target.is_file():
            removed = [
                p for p in extract_step_patterns(_read(target), profile)
                if p not in patterns_in_file
            ]
            if removed:
                errors.append(
                    f"{name}: this rewrite drops existing step definition(s) "
                    f"{removed} — return the FULL file content preserving every "
                    "existing step"
                )
        generated_patterns.extend(patterns_in_file)

    # Steps may match existing glue OR glue proposed in this same generation.
    all_patterns = step_patterns + generated_patterns

    for feature in generation.new_or_modified_features:
        name = feature.file_name.lstrip("./")
        target = (repo / name).resolve()

        if name in seen_names:
            errors.append(f"{name}: appears more than once in new_or_modified_features")
        seen_names.add(name)

        if not name.endswith(".feature"):
            errors.append(f"{name}: file name must end with .feature")
        if profile.features_marker not in name:
            errors.append(f"{name}: must live under a {profile.features_marker} path")
        if not target.is_relative_to(repo):
            errors.append(f"{name}: path escapes the repository root")
        # No CREATE/UPDATE-vs-existence check: the model returns full feature
        # content either way, so the label is cosmetic — and rejecting on it made
        # the retry loop thrash once an earlier attempt had written the file.

        lines = [line.strip() for line in feature.gherkin_content.splitlines()]
        if not any(line.startswith("Feature:") for line in lines):
            errors.append(f"{name}: content has no 'Feature:' declaration")
        if not any(line.startswith(("Scenario:", "Scenario Outline:")) for line in lines):
            errors.append(f"{name}: content has no scenarios")
        outline_count = sum(1 for line in lines if line.startswith("Scenario Outline:"))
        examples_count = sum(1 for line in lines if line.startswith("Examples:"))
        if outline_count > examples_count:
            errors.append(f"{name}: a Scenario Outline is missing its Examples table")

        # The reuse contract: every step must have glue code — existing or
        # proposed in this generation — or Cucumber will fail the PR with
        # undefined steps. Feed exact offenders back.
        if all_patterns:
            for step in find_undefined_steps(feature.gherkin_content, all_patterns, profile.step_style):
                message = (
                    f'{name}: step "{step}" matches no existing step definition. '
                    "Rephrase it using one of the step patterns from the provided "
                    "step definitions, or add the missing glue in a STEPDEF block."
                )
                if "<" in step:
                    message += (
                        " Note: <name> placeholders are only substituted inside "
                        "Scenario Outlines that have a matching Examples column. "
                        "If this placeholder stands for a server-generated id, "
                        "you cannot know it — rewrite the step using the "
                        "'the last created <entity>' idiom (see the existing "
                        "steps) and make the glue track the id internally."
                    )
                errors.append(message)

    if errors:
        logger.warning("Validation failed (attempt %d): %s", state["attempts"], errors)
    return {"validation_errors": errors}


def write_features(state: TestGenState) -> TestGenState:
    """Write the validated feature and glue files; skip unchanged content."""
    repo = Path(state["repo_path"])
    generation = state["generation"]
    written: list = []

    outputs = [(f.file_name, f.action, f.gherkin_content)
               for f in generation.new_or_modified_features]
    outputs += [(g.file_name, g.action, g.content)
                for g in generation.new_or_modified_step_definitions]

    for file_name, _action, raw_content in outputs:
        target = repo / file_name.lstrip("./")
        target.parent.mkdir(parents=True, exist_ok=True)
        content = raw_content.replace("\r\n", "\n")
        if not content.endswith("\n"):
            content += "\n"
        if target.is_file() and _read(target) == content:
            logger.info("UNCHANGED %s (generated content identical; skipping)", file_name)
            continue
        # Log the real action from disk state, not the model's (often wrong) label.
        action = "UPDATE" if target.is_file() else "CREATE"
        target.write_text(content, encoding="utf-8")
        written.append(str(target.relative_to(repo)))
        logger.info("%s %s", action, file_name)
    return {"written_files": written}


def _extract_compile_errors(output: str, profile) -> list:
    """Pull compiler errors out of the build output (build failed before tests)."""
    errors = []
    for line in output.splitlines():
        if profile.name == "java":
            # e.g. "[ERROR] /path/Foo.java:[12,34] cannot find symbol"
            if ".java:[" in line and "ERROR" in line:
                errors.append(line.split("ERROR]", 1)[-1].strip())
        else:  # dotnet — "Foo.cs(12,34): error CS0103: The name 'x' ..."
            if "error CS" in line:
                errors.append(line.strip())
    # De-dupe (dotnet repeats errors across projects), cap.
    return list(dict.fromkeys(errors))[:25]


def _extract_scenario_failures_java(repo: Path, profile) -> list:
    """Parse the Cucumber JSON report for failed scenarios + the reason."""
    report_path = repo / profile.component_dir / profile.report_rel
    if not report_path.is_file():
        return []
    try:
        report = json.loads(_read(report_path))
    except (ValueError, OSError):
        return []

    failures = []
    for feature in report:
        background = []
        for el in feature.get("elements", []):
            steps = el.get("steps", [])
            if el.get("type") == "background":
                background = steps
                continue
            for step in background + steps:
                res = step.get("result", {})
                if res.get("status") in ("failed", "undefined", "pending", "ambiguous"):
                    why = res.get("error_message", res.get("status", "")).splitlines()
                    failures.append(
                        f'- [{feature.get("name")}] "{el.get("name")}" → '
                        f'step "{step.get("keyword","").strip()} {step.get("name")}" '
                        f'{res.get("status")}: {why[0] if why else ""}'
                    )
                    break  # one failure per scenario is enough signal
    return failures


# `dotnet test` console: "  Failed Namespace.Scenario_xyz [12 ms]" then an
# indented "Error Message:" / assertion line.
_DOTNET_FAIL_RE = re.compile(r"^\s*(?:Failed|\[FAIL\])\s+(.+?)(?:\s+\[[\d.]+\s*\w+\])?\s*$")


def _extract_scenario_failures_dotnet(output: str) -> list:
    """Parse `dotnet test` console output for failed tests + the message."""
    lines = output.splitlines()
    failures = []
    for i, line in enumerate(lines):
        m = _DOTNET_FAIL_RE.match(line)
        if not m:
            continue
        name = m.group(1).strip()
        # The assertion/error message usually follows within a few lines. Skip the
        # bare "Error Message:" header and grab the actual assertion text.
        why = ""
        for nxt in lines[i + 1:i + 6]:
            s = nxt.strip()
            if not s or s == "Error Message:":
                continue
            if s.startswith(("Assert", "Expected:", "Actual:", "System.")) or "Expected" in s:
                why = s
                break
        failures.append(f'- {name}: {why}')
    return list(dict.fromkeys(failures))


def run_generated_tests(state: TestGenState) -> TestGenState:
    """Run the generated tests (`mvn test` for Java, `dotnet test` for .NET); on
    failure, capture *why* (compile errors + per-scenario failures) so the model
    can correct itself.

    Skips gracefully (tests_passed=True) when there's nothing to run or the build
    tool isn't available, so the agent still works in a toolchain-less environment
    — just without execution feedback."""
    repo = Path(state["repo_path"]).resolve()  # absolute, so paths and cwd agree
    profile = _profile(state)

    if not state.get("written_files"):
        return {"tests_passed": True, "test_failures": [],
                "test_report": "no files written; nothing to run"}

    component = repo / profile.component_dir
    # Fill the command template: {pom} for Java, {dir} for .NET.
    pom = str(component / "pom.xml")
    cmd = [arg.format(pom=pom, dir=str(component)) for arg in profile.test_cmd]
    tool = cmd[0]
    if shutil.which(tool) is None:
        logger.warning("'%s' not found on PATH — skipping test execution", tool)
        return {"tests_passed": True, "test_failures": [],
                "test_report": f"test execution skipped ({tool} not available in this environment)"}

    logger.info("Running generated tests: %s", " ".join(cmd))
    proc = subprocess.run(
        cmd, cwd=str(repo), capture_output=True, text=True, timeout=TEST_TIMEOUT,
    )

    if proc.returncode == 0:
        logger.info("Generated tests passed.")
        return {"tests_passed": True, "test_failures": [],
                "test_report": "all generated tests passed"}

    test_attempts = state.get("test_attempts", 0) + 1
    output = proc.stdout + "\n" + proc.stderr

    compile_errors = _extract_compile_errors(output, profile)
    if profile.report_rel:
        scenario_failures = _extract_scenario_failures_java(repo, profile)
    else:
        scenario_failures = _extract_scenario_failures_dotnet(output)

    feedback: list = []
    if compile_errors:
        feedback.append(
            f"COMPILATION ERROR (the generated {profile.glue_language} does not compile):")
        feedback += [f"- {e}" for e in compile_errors]
    if scenario_failures:
        feedback.append("SCENARIO FAILURES:")
        feedback += scenario_failures
    if not feedback:
        # The build failed for some other reason — hand back the tail.
        tail = "\n".join(output.splitlines()[-25:])
        feedback.append(f"`{' '.join(cmd)}` failed; tail of the output:\n" + tail)

    logger.warning("Test attempt %d failed (%d compile, %d scenario)",
                   test_attempts, len(compile_errors), len(scenario_failures))
    return {
        "tests_passed": False,
        "test_attempts": test_attempts,
        "test_failures": feedback,
        "test_report": f"{len(scenario_failures)} scenario failure(s), "
                       f"{len(compile_errors)} compile error(s) on attempt {test_attempts}",
        # Clear structural errors so the next generate uses the test feedback.
        "validation_errors": [],
    }


def create_pull_request(state: TestGenState) -> TestGenState:
    """Commit the generated features on a new branch and open a PR via the gh CLI."""
    repo = state["repo_path"]
    generation = state["generation"]

    if not state["written_files"]:
        logger.info("no feature files changed on disk; skipping PR")
        return {"pr_url": None, "skipped_reason": "generated tests are identical to the existing suite"}

    head_sha = _run(["git", "rev-parse", "--short=12", state["head_ref"]], cwd=repo).strip()
    branch = f"testgen/{head_sha}-{int(time.time())}"

    original_ref = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=repo).strip()
    _run(["git", "checkout", "-b", branch], cwd=repo)
    try:
        _run(["git", "add", *state["written_files"]], cwd=repo)
        staged = _run(["git", "diff", "--cached", "--name-only"], cwd=repo).strip()
        if not staged:
            logger.info("nothing staged after add; skipping PR")
            return {"pr_url": None, "skipped_reason": "no effective changes to commit"}
        _run(
            ["git", "commit", "-m",
             "test: regenerate Cucumber regression tests\n\n" + generation.analysis_summary],
            cwd=repo,
        )
        _run(["git", "push", "-u", "origin", branch], cwd=repo)

        endpoints = "\n".join(f"- `{e}`" for e in generation.impacted_endpoints) or "- none"

        tests_passed = state.get("tests_passed", True)
        if tests_passed:
            title = "test: update Cucumber regression suite for latest code changes"
            status = f"✅ Generated tests **passed** locally ({state.get('test_report','')})."
        else:
            title = "test: update Cucumber suite (⚠️ still failing — needs review)"
            failures = "\n".join(state.get("test_failures", []))
            status = (
                f"⚠️ Generated tests **still failing** after "
                f"{state.get('test_attempts', 0)} self-correction attempt(s). "
                "A human needs to resolve these — the most likely cause is the model "
                "asserting a wrong expected value, or the change being too large for "
                "one pass.\n\n<details><summary>Remaining failures</summary>\n\n"
                f"```\n{failures}\n```\n</details>"
            )

        body = (
            "## Auto-generated regression tests\n\n"
            f"{generation.analysis_summary}\n\n"
            f"### Test status\n{status}\n\n"
            f"### Impacted endpoints\n{endpoints}\n\n"
            f"### Files\n" + "\n".join(f"- `{f}`" for f in state["written_files"]) + "\n\n"
            "Please review the scenarios before merging. Regression runs automatically "
            "after merge.\n\n"
            "🤖 Generated with [Claude Code](https://claude.com/claude-code)"
        )
        pr_url = _run(
            ["gh", "pr", "create", "--title", title, "--body", body, "--head", branch],
            cwd=repo,
        ).strip()
        logger.info("Opened PR: %s", pr_url)
        return {"pr_url": pr_url}
    finally:
        # Best-effort return to where we started (matters for local runs;
        # harmless in CI). "HEAD" means we began detached — stay put then.
        if original_ref != "HEAD":
            subprocess.run(["git", "checkout", original_ref], cwd=repo, capture_output=True)
