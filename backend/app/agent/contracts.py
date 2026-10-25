from typing import Annotated, Literal, Self

from pydantic import Field, SecretStr, StrictBool, StrictInt, model_validator

from app.schemas.api import ExperimentView, ToolView
from app.schemas.provenance import FrozenModel, Text
from app.schemas.scene import SceneSpec

BusinessType = Literal["retail_perishable", "retail_durable", "appointment_service"]
NumericField = Literal[
    "budget_cents",
    "unit_price_cents",
    "unit_cost_cents",
    "stock_qty",
    "fixed_cost_cents",
    "demand_qty",
    "minutes_per_job",
    "available_minutes",
    "booked",
    "cancelled",
]
ToolName = Literal[
    "validate_scene",
    "calculate_retail",
    "calculate_service",
    "check_budget",
    "run_demand_scenarios",
    "compare_versions",
]


class NumberFact(FrozenModel):
    field: NumericField
    value: Annotated[int, Field(strict=True, ge=0, le=10**9)]
    evidence: Annotated[str, Field(min_length=1, max_length=100)]


class TextFact(FrozenModel):
    field: Literal["product", "location", "target_audience"]
    value: Annotated[str, Field(min_length=1, max_length=200)]
    evidence: Annotated[str, Field(min_length=1, max_length=300)]


class Extraction(FrozenModel):
    business_type: BusinessType | Literal["unsupported", "uncertain"]
    business_evidence: str
    numbers: Annotated[tuple[NumberFact, ...], Field(max_length=10)]
    texts: Annotated[tuple[TextFact, ...], Field(max_length=3)]


class ToolPlan(FrozenModel):
    tools: Annotated[tuple[ToolName, ...], Field(min_length=2, max_length=3)]


class ExperimentDraft(FrozenModel):
    question: Annotated[str, Field(min_length=1, max_length=500)]
    method: Annotated[str, Field(min_length=1, max_length=2000)]
    warnings: Annotated[tuple[str, ...], Field(max_length=3)]


class Question(FrozenModel):
    field: str
    text: str
    unit: str


class Change(FrozenModel):
    field: NumericField
    value: Annotated[int, Field(strict=True, ge=0, le=10**9)]


class ProposedAction(FrozenModel):
    id: str
    label: str
    changes: tuple[Change, ...]
    requires_confirmation: Literal[True] = True


class RiskCardView(FrozenModel):
    type: str
    text: str
    severity: Literal["info", "warning"]
    evidence: dict[str, str | int | None]
    action: ProposedAction | None = None


class AgentResult(FrozenModel):
    id: str
    thread_id: str
    status: str
    stage: str
    total_steps: int
    total_calls: int
    request_id: str | None = None
    error_code: str | None = None
    scene: SceneSpec | None = None
    questions: tuple[Question, ...] = ()
    facts: tuple[TextFact, ...] = ()
    risk_cards: tuple[RiskCardView, ...] = ()
    proposed_actions: tuple[ProposedAction, ...] = ()
    scene_version_id: str | None = None
    branch_version_id: str | None = None
    tools: tuple[ToolView, ...] = ()
    experiment_draft: ExperimentDraft | None = None
    saved_experiment: ExperimentView | None = None
    message: str = ""
    model: str | None = None
    model_calls: tuple[dict[str, str | int], ...] = ()


class ClarificationInput(FrozenModel):
    run_id: str
    answers: dict[NumericField, StrictInt] = Field(default_factory=dict, max_length=10)
    use_demo_assumptions: StrictBool = False


class ExplicitConfirmation(FrozenModel):
    confirmed: StrictBool

    @model_validator(mode="after")
    def require_confirmation(self) -> Self:
        if self.confirmed is not True:
            raise ValueError("explicit confirmation required")
        return self


class AgentConfirmation(ExplicitConfirmation):
    run_id: str


class AnalyzeInput(FrozenModel):
    scene_version_id: str
    scenario_label: Text


class ActionInput(ExplicitConfirmation):
    action_id: str


class RetryInput(ExplicitConfirmation):
    run_id: str


class StartInput(FrozenModel):
    pass


class ConnectionInput(FrozenModel):
    provider: Literal["deepseek", "openai", "qwen"]
    model: Text
    api_key: SecretStr = Field(min_length=8, max_length=512)
    authorize_paid_calls: StrictBool


class ModelStatus(FrozenModel):
    connected: bool
    provider: str | None = None
    model: str | None = None
    retention_seconds: int = 1800
    available_models: dict[str, tuple[str, ...]]
    verified: bool = False
