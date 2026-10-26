"""A process is an owned, reproducible presentation of one frozen retail simulation."""

from typing import Annotated, Literal, Self

from pydantic import Field, StrictBool, model_validator

from app.schemas.provenance import FrozenModel, Text
from app.schemas.scene import Quantity
from app.schemas.simulation import NonNegativeResult, SafeResult, SimulationSnapshot

Revision = Annotated[int, Field(strict=True, ge=0, le=3)]


class CreateProcess(FrozenModel):
    scenario_label: Text
    confirmed: StrictBool

    @model_validator(mode="after")
    def confirmation(self) -> Self:
        if not self.confirmed:
            raise ValueError("confirm the process assumptions first")
        return self


class AdvanceProcess(FrozenModel):
    expected_revision: Revision
    action: Literal["next", "finish"] = "next"


class ProcessProfile(FrozenModel):
    rule_version: Literal["retail-process-1"] = "retail-process-1"
    demand_by_stage: tuple[Quantity, Quantity, Quantity]
    allocation_source: Literal["demo_assumption"] = "demo_assumption"
    note: str = "总需求均分为三个逻辑营业阶段，余数从前到后分配；不是实际客流规律。"
    confirmed: Literal[True] = True


class ProcessState(FrozenModel):
    revision: Revision
    sold: NonNegativeResult
    remaining_stock: NonNegativeResult
    demand_seen: NonNegativeResult
    unserved: NonNegativeResult
    revenue_cents: NonNegativeResult
    cash_out_cents: NonNegativeResult
    budget_balance_cents: SafeResult | None
    summary: str


class ProcessStepView(FrozenModel):
    sequence: Revision
    demand: NonNegativeResult
    sold: NonNegativeResult
    revenue_cents: NonNegativeResult
    cash_out_cents: NonNegativeResult
    before: ProcessState | None
    after: ProcessState


class ProcessView(FrozenModel):
    id: str
    scene_version_id: str
    simulation_run_id: str
    scenario_label: str
    status: Literal["open", "completed"]
    profile: ProcessProfile
    state: ProcessState
    steps: tuple[ProcessStepView, ...]
    calculation: SimulationSnapshot | None


class AssistantStatus(FrozenModel):
    available: bool
    message: str
