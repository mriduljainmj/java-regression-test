"""CLI entry point for the Cucumber regression test-generation agent.

Usage:
    export OPENROUTER_API_KEY=...
    python main.py --repo /path/to/repo --base <base-sha-or-ref> --head <head-sha-or-ref>

Add --no-pr to write the feature files locally without committing or opening a PR
(useful for local runs and dry runs in CI).

Environment overrides:
    TESTGEN_MODEL / TESTGEN_MODELS   model or comma-separated fallback chain
    TESTGEN_MAX_ATTEMPTS             generation retry budget (default 3)
    TESTGEN_MAX_CONTEXT_CHARS        per-section context cap (default 60000)
"""

import argparse
import json
import logging
import sys

from testgen.graph import build_graph

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("testgen.main")


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate Cucumber regression tests from a git diff")
    parser.add_argument("--repo", required=True, help="Path to the git repository root")
    parser.add_argument("--base", required=True, help="Base ref/SHA (state before the change)")
    parser.add_argument("--head", default="HEAD", help="Head ref/SHA (state after the change)")
    parser.add_argument("--no-pr", action="store_true",
                        help="Write feature files only; skip branch/commit/PR creation")
    args = parser.parse_args()

    app = build_graph()
    try:
        result = app.invoke(
            {
                "repo_path": args.repo,
                "base_ref": args.base,
                "head_ref": args.head,
                "create_pr": not args.no_pr,
            }
        )
    except Exception as e:
        logger.error("test generation failed: %s", e)
        return 1

    generation = result.get("generation")
    if generation is None:
        # Skipped before generation (no relevant changes in the diff).
        print(f"Skipped: {result.get('skipped_reason', 'no generation produced')}")
        return 0

    summary = {
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
