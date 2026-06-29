"""Wires the nodes into the LangGraph state machine.

    collect_diff ──(no java changes)──▶ END
         │
         ▼
    gather_context ──▶ generate_tests ──▶ validate_output
                            ▲   ▲              │
              (structural ──┘   │              │ (structurally clean)
               errors,          │              ▼
               retries left)    │         write_features ──▶ run_generated_tests
                                │                                   │
              (tests failed, ───┘                                   │
               attempts left)                    (pass, or out of test retries)
                                                                    ▼
                                                          create_pull_request ──▶ END
"""

from langgraph.graph import END, StateGraph

from .nodes import (
    MAX_ATTEMPTS,
    MAX_TEST_ATTEMPTS,
    collect_diff,
    create_pull_request,
    gather_context,
    generate_tests,
    run_generated_tests,
    validate_output,
    write_features,
)
from .state import TestGenState


def _after_collect_diff(state: TestGenState) -> str:
    return END if state.get("skipped_reason") else "gather_context"


def _after_validate(state: TestGenState) -> str:
    if state["validation_errors"]:
        # Check for infinite loop: model keeps generating Java @Given/@When/@Then in C# files
        curr_errors = state["validation_errors"]
        has_csharp_syntax_error = any(
            "Java-style annotations" in str(err) or "@(Given|When|Then)" in str(err)
            for err in curr_errors
        )
        
        if has_csharp_syntax_error and state["attempts"] >= 3:
            # This error has persisted; model doesn't understand C# syntax
            raise RuntimeError(
                f"Generation failed validation after {state['attempts']} attempts: INFINITE LOOP DETECTED\n"
                f"The model keeps generating Java annotations (@Given/@When/@Then) in C# files.\n"
                f"This is a fundamental syntax misunderstanding.\n\n"
                f"Errors: {'; '.join(curr_errors)}\n\n"
                f"C# SpecFlow MUST use square brackets [Given], [When], [Then], NOT @ symbols.\n"
                f"Example CORRECT syntax:\n"
                f"  [Given(\"I have a product\")]\n"
                f"  public void GivenIHaveAProduct() {{ }}\n"
            )
        
        if state["attempts"] < MAX_ATTEMPTS:
            return "generate_tests"
        raise RuntimeError(
            f"Generation failed validation after {MAX_ATTEMPTS} attempts: "
            + "; ".join(curr_errors)
        )
    if not state["generation"].new_or_modified_features:
        return END  # purely internal change — nothing to write
    return "write_features"


def _after_run_tests(state: TestGenState) -> str:
    """Pass → open the PR. Fail with retries left → regenerate from the failure
    feedback. Fail and out of retries → open the PR anyway, flagged as failing
    (don't lose the work; the human + the PR's own regression check take over)."""
    if not state.get("tests_passed", True):
        if state.get("test_attempts", 0) < MAX_TEST_ATTEMPTS:
            return "generate_tests"
    return "create_pull_request" if state.get("create_pr") else END


def build_graph():
    graph = StateGraph(TestGenState)

    graph.add_node("collect_diff", collect_diff)
    graph.add_node("gather_context", gather_context)
    graph.add_node("generate_tests", generate_tests)
    graph.add_node("validate_output", validate_output)
    graph.add_node("write_features", write_features)
    graph.add_node("run_generated_tests", run_generated_tests)
    graph.add_node("create_pull_request", create_pull_request)

    graph.set_entry_point("collect_diff")
    graph.add_conditional_edges("collect_diff", _after_collect_diff)
    graph.add_edge("gather_context", "generate_tests")
    graph.add_edge("generate_tests", "validate_output")
    graph.add_conditional_edges("validate_output", _after_validate)
    graph.add_edge("write_features", "run_generated_tests")
    graph.add_conditional_edges("run_generated_tests", _after_run_tests)
    graph.add_edge("create_pull_request", END)

    return graph.compile()
