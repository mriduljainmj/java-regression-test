"""CLI entry point for the Cucumber regression test-generation agent.

Usage:
    export ANTHROPIC_API_KEY=...
    python main.py --repo /path/to/repo --base <base-sha-or-ref> --head <head-sha-or-ref>

Add --no-pr to write the feature files locally without committing or opening a PR
(useful for local runs and dry runs in CI).
"""

import argparse
import json
import logging
import sys

from testgen.graph import build_graph

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate Cucumber regression tests from a git diff")
    parser.add_argument("--repo", required=True, help="Path to the git repository root")
    parser.add_argument("--base", required=True, help="Base ref/SHA (state before the change)")
    parser.add_argument("--head", default="HEAD", help="Head ref/SHA (state after the change)")
    parser.add_argument("--no-pr", action="store_true",
                        help="Write feature files only; skip branch/commit/PR creation")
    args = parser.parse_args()

    app = build_graph()
    result = app.invoke(
        {
            "repo_path": args.repo,
            "base_ref": args.base,
            "head_ref": args.head,
            "create_pr": not args.no_pr,
        }
    )

    if result.get("skipped_reason"):
        print(f"Skipped: {result['skipped_reason']}")
        return 0

    generation = result["generation"]
    summary = {
        "impacted_endpoints": generation.impacted_endpoints,
        "analysis_summary": generation.analysis_summary,
        "written_files": result.get("written_files", []),
        "pr_url": result.get("pr_url"),
    }
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
