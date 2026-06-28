"""Shared state passed between LangGraph nodes."""

from typing import Literal, Optional, TypedDict

from pydantic import BaseModel, Field


class FeatureFile(BaseModel):
    """One Gherkin .feature file to create or update (same format for Cucumber
    and Reqnroll/SpecFlow)."""

    file_name: str = Field(
        description="Path of the .feature file relative to the repository root"
    )
    action: Literal["CREATE", "UPDATE"]
    gherkin_content: str = Field(description="Full Gherkin content of the feature file")


class StepDefinitionFile(BaseModel):
    """One step-definition (glue) file to create or update — Java for Cucumber or
    C# for Reqnroll/SpecFlow, depending on the detected language.

    Only needed when the required behavior cannot be expressed with existing
    step patterns. UPDATE content must be the FULL file and must preserve every
    step definition that already exists in it.
    """

    file_name: str = Field(
        description="Path relative to the repository root, under the test-source tree"
    )
    action: Literal["CREATE", "UPDATE"]
    content: str = Field(description="Full source of the step-definition file")


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

    # Detected language profile (java | dotnet)
    language: str

    # Gathered context
    git_diff: str
    changed_files: list[str]
    target_component_context: str
    existing_feature_examples: str
    api_spec: str
    step_patterns: list[str]  # step expressions parsed from the glue code

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
