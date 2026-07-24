"""Shared state passed between LangGraph nodes."""

from typing import Literal, Optional, TypedDict

from pydantic import BaseModel, Field


class FeatureFile(BaseModel):
    """One Cucumber feature file to create or update."""

    file_name: str = Field(
        description="Path of the feature file relative to the repository root, "
        "e.g. java-component/src/test/resources/features/product_pricing.feature"
    )
    action: Literal["CREATE", "UPDATE"]
    gherkin_content: str = Field(description="Full Gherkin content of the feature file")


class StepDefinitionFile(BaseModel):
    """One Java or C# step-definition (glue) file to create or update.

    Only needed when the required behavior cannot be expressed with existing
    step patterns. UPDATE content must be the FULL file and must preserve every
    step definition that already exists in it.
    """

    file_name: str = Field(
        description="Path relative to the repository root, e.g. Tests/StepDefinitions/OrderStepDefinitions.cs or src/test/java/…/OrderStepDefinitions.java"
    )
    action: Literal["CREATE", "UPDATE"]
    content: str = Field(
        description="Full source of the step-definition file (C# or Java)",
        alias="java_content",
    )
    language: Optional[Literal["java", "csharp", "javascript"] ] = Field(
        default=None,
        description="Optional language hint: 'java', 'csharp', or 'javascript' (Playwright/Cucumber-JS UI glue). If omitted, inferred from file extension."
    )

    model_config = {
        "populate_by_name": True,
    }

    @property
    def java_content(self) -> str:
        return self.content


class GenerationResult(BaseModel):
    """Structured output produced by the LLM."""

    impacted_endpoints: list[str] = Field(
        description='Impacted endpoints, e.g. ["POST /api/v1/products"]'
    )
    analysis_summary: str = Field(
        description="Brief explanation of what changed and what needs regression testing"
    )
    new_or_modified_features: list[FeatureFile]
    new_or_modified_step_definitions: list[StepDefinitionFile] = Field(default_factory=list)


class TestGenState(TypedDict, total=False):
    # Inputs
    repo_path: str
    base_ref: str
    head_ref: str
    create_pr: bool
    ado_work_item_id: str
    ado_work_item_context: str
    reviewer_guidance: str  # free-text edge-case hints from a human, injected into the prompt
    resolved_base: str
    project_type: str  # "java" | "dotnet" | "ui" — detected in collect_diff, must persist end-to-end

    # Gathered context
    git_diff: str
    changed_files: list[str]
    target_component_context: str
    existing_feature_examples: str
    api_spec: str
    step_patterns: list[str]  # cucumber expressions parsed from Java glue code

    # Generation + validation loop
    generation: Optional[GenerationResult]
    validation_errors: list[str]
    attempts: int

    # Execution-feedback loop: run the generated tests, feed failures back
    test_failures: list[str]
    test_attempts: int
    tests_passed: bool
    test_report: Optional[str]  # human-readable note shown in the PR body

    # Outputs
    written_files: list[str]
    pr_url: Optional[str]
    skipped_reason: Optional[str]
