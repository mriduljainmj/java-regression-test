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
    """One Java step-definition (glue) file to create or update.

    Only needed when the required behavior cannot be expressed with existing
    step patterns. UPDATE content must be the FULL file and must preserve every
    step definition that already exists in it.
    """

    file_name: str = Field(
        description="Path relative to the repository root, under src/test/java/, "
        "e.g. java-component/src/test/java/com/example/products/cucumber/OrderStepDefinitions.java"
    )
    action: Literal["CREATE", "UPDATE"]
    java_content: str = Field(description="Full Java source of the step-definition file")


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

    # Outputs
    written_files: list[str]
    pr_url: Optional[str]
    skipped_reason: Optional[str]
