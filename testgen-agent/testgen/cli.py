"""Command-line entry point for the test-generation agent.

Installed as the `testgen` console script (see pyproject.toml), so it can run
against ANY repo without copying this folder in:

    pip install testgen-agent          # or: pip install git+https://…
    cd /path/to/your/component/repo
    export OPENROUTER_API_KEY=...
    testgen --repo . --base origin/main --head HEAD

Add --no-pr to write the test files locally without committing or opening a PR.

Environment (all optional):
    TESTGEN_MODEL / TESTGEN_MODELS   model or comma-separated fallback chain
    TESTGEN_MAX_ATTEMPTS             generation retry safety cap
    TESTGEN_MAX_TEST_ATTEMPTS        run-tests → fix retry budget
    TESTGEN_MAX_CONTEXT_CHARS        per-section context cap
    TESTGEN_COMPONENT_DIR            override the auto-discovered build root
    ADO_ORG / AZURE_DEVOPS_PAT / ADO_PROJECT   ticket context (Azure DevOps)
"""

import argparse
import json
import logging
import sys

from .graph import build_graph

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("testgen.cli")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="testgen",
        description="Generate Cucumber/Reqnroll regression tests from a git diff "
                    "(Java or .NET, auto-detected).",
    )
    parser.add_argument("--repo", default=".", help="Path to the git repository root (default: .)")
    parser.add_argument("--base", default="HEAD~1",
                        help="Base ref/SHA — state before the change (default: HEAD~1)")
    parser.add_argument("--head", default="HEAD", help="Head ref/SHA (default: HEAD)")
    parser.add_argument("--no-pr", action="store_true",
                        help="Write test files only; skip branch/commit/PR creation")
    parser.add_argument("--work-item", action="append", default=[], metavar="ID",
                        help="ADO work-item id for ticket context (repeatable). "
                             "If omitted, ids are auto-detected from commit messages (AB#123).")
    parser.add_argument("--reviewer-input", default="",
                        help="Free-text reviewer guidance fed into generation")
    parser.add_argument("--reviewer-input-file", default=None,
                        help="Path to a file whose contents are used as reviewer guidance")
    args = parser.parse_args(argv)

    reviewer_input = args.reviewer_input
    if args.reviewer_input_file:
        with open(args.reviewer_input_file, encoding="utf-8") as fh:
            reviewer_input = (reviewer_input + "\n" + fh.read()).strip()

    app = build_graph()
    try:
        result = app.invoke({
            "repo_path": args.repo,
            "base_ref": args.base,
            "head_ref": args.head,
            "create_pr": not args.no_pr,
            "work_item_ids": args.work_item,
            "reviewer_input": reviewer_input,
        })
    except Exception as e:
        logger.error("test generation failed: %s", e)
        return 1

    generation = result.get("generation")
    if generation is None:
        print(f"Skipped: {result.get('skipped_reason', 'no generation produced')}")
        return 0

    summary = {
        "language": result.get("language"),
        "component_root": result.get("component_root"),
        "impacted_endpoints": generation.impacted_endpoints,
        "analysis_summary": generation.analysis_summary,
        "written_files": result.get("written_files", []),
        "pr_url": result.get("pr_url"),
    }
    if result.get("skipped_reason"):
        summary["note"] = result["skipped_reason"]
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
