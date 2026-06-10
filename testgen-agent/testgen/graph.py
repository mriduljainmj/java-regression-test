"""Wires the nodes into the LangGraph state machine.

    collect_diff ──(no java changes)──▶ END
         │
         ▼
    gather_context ──▶ generate_tests ──▶ validate_output
                            ▲                   │
                            │ (errors,          │ (clean, or out of retries)
                            │  retries left)    ▼
                            └────────── write_features ──▶ create_pull_request ──▶ END
"""

from langgraph.graph import END, StateGraph

from .nodes import (
    MAX_ATTEMPTS,
    collect_diff,
    create_pull_request,
    gather_context,
    generate_tests,
    validate_output,
    write_features,
)
from .state import TestGenState


def _after_collect_diff(state: TestGenState) -> str:
    return END if state.get("skipped_reason") else "gather_context"


def _after_validate(state: TestGenState) -> str:
    if state["validation_errors"]:
        if state["attempts"] < MAX_ATTEMPTS:
            return "generate_tests"
        raise RuntimeError(
            f"Generation failed validation after {MAX_ATTEMPTS} attempts: "
            + "; ".join(state["validation_errors"])
        )
    if not state["generation"].new_or_modified_features:
        return END  # purely internal change — nothing to write
    return "write_features"


def _after_write(state: TestGenState) -> str:
    return "create_pull_request" if state.get("create_pr") else END


def build_graph():
    graph = StateGraph(TestGenState)

    graph.add_node("collect_diff", collect_diff)
    graph.add_node("gather_context", gather_context)
    graph.add_node("generate_tests", generate_tests)
    graph.add_node("validate_output", validate_output)
    graph.add_node("write_features", write_features)
    graph.add_node("create_pull_request", create_pull_request)

    graph.set_entry_point("collect_diff")
    graph.add_conditional_edges("collect_diff", _after_collect_diff)
    graph.add_edge("gather_context", "generate_tests")
    graph.add_edge("generate_tests", "validate_output")
    graph.add_conditional_edges("validate_output", _after_validate)
    graph.add_conditional_edges("write_features", _after_write)
    graph.add_edge("create_pull_request", END)

    return graph.compile()
