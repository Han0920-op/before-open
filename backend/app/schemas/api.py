from datetime import datetime
from typing import Annotated, Any, Literal, Self

from pydantic import AwareDatetime, Field, StrictBool, StringConstraints, model_validator

from app.schemas.provenance import FrozenModel, Text
from app.schemas.scene import SceneSpec
from app.schemas.simulation import SimulationSnapshot

Title = Annotated[str, StringConstraints(strict=True, min_length=1, max_length=200)]
Description = Annotated[str, StringConstraints(strict=True, min_length=1, max_length=10000)]
Identifier = Annotated[str, StringConstraints(pattern=r"^[0-9a-f-]{36}$")]


class Envelope[T](FrozenModel):
    request_id: str
    data: T


class ErrorDetail(FrozenModel):
    code: str
    message: str


class ErrorEnvelope(FrozenModel):
    request_id: str
    error: ErrorDetail


class SessionView(FrozenModel):
    csrf_token: str
    expires_at: datetime


class CreateProject(FrozenModel):
    original_idea: Description
    title: Title


class ProjectView(FrozenModel):
    id: str
    original_idea: str
    title: str
    created_at: datetime


class ConfirmScene(FrozenModel):
    scene: SceneSpec
    confirmed: StrictBool

    @model_validator(mode="after")
    def require_confirmation(self) -> Self:
        if not self.confirmed:
            raise ValueError("user confirmation required")
        return self


class VersionView(FrozenModel):
    id: str
    project_id: str
    parent_version_id: str | None
    scene: SceneSpec
    created_at: datetime


class ProjectDetail(FrozenModel):
    project: ProjectView
    versions: tuple[VersionView, ...]
    latest_version_id: str | None


class SimulateRequest(FrozenModel):
    scenario_label: Text


class PreviewRequest(FrozenModel):
    scene: SceneSpec
    scenario_label: Text


class RunView(FrozenModel):
    id: str
    snapshot: SimulationSnapshot


class CompareRequest(FrozenModel):
    left_version_id: Identifier
    right_version_id: Identifier
    left_scenario_label: Text
    right_scenario_label: Text


class FieldChange(FrozenModel):
    path: str
    left: Any
    right: Any


class ComparisonView(FrozenModel):
    left: SimulationSnapshot
    right: SimulationSnapshot
    changed_fields: tuple[FieldChange, ...]
    unchanged_fields: tuple[str, ...]
    same_calculation_inputs: bool
    same_demand_assumption: bool | None
    same_period: bool
    result_deltas: dict[str, int | None]
    warning: str


class CreateExperiment(FrozenModel):
    scene_version_id: Identifier
    question: Description
    method: Description
    warnings: tuple[Description, ...] = ()


class ExperimentView(FrozenModel):
    id: str
    project_id: str
    scene_version_id: str
    question: str
    method: str
    warnings: tuple[str, ...]
    status: str


class ObservedValue(FrozenModel):
    value: Annotated[int, Field(strict=True, ge=0, le=10**9)]
    unit: Literal["cents", "qty", "minutes"]


class CreateObservation(FrozenModel):
    recorded_at: AwareDatetime
    sample_size: Annotated[int, Field(strict=True, ge=1, le=10**6)]
    notes: Description
    limitations: Description
    observed_values: dict[Text, ObservedValue] = Field(min_length=1, max_length=50)


class ObservationView(CreateObservation):
    id: str
    task_id: str
    provenance: Literal["user_observation"] = "user_observation"


class ToolView(FrozenModel):
    id: str
    tool_name: str
    input_summary: dict[str, Any]
    output_summary: dict[str, Any]
    status: str
    duration_ms: int
    request_id: str | None = None
    scene_version_id: str | None = None


class AgentRunView(FrozenModel):
    id: str
    thread_id: str
    stage: str
    status: str
    total_steps: int
    tools: tuple[ToolView, ...]


class SummaryView(FrozenModel):
    project: ProjectView
    versions: tuple[VersionView, ...]
    simulations: tuple[RunView, ...]
    experiments: tuple[ExperimentView, ...]
    observations: tuple[ObservationView, ...]
