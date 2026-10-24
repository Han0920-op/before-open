"""Execution parameters are complete; results and snapshots are immutable value objects."""

from datetime import UTC
from typing import Annotated, Literal, Self

from pydantic import AwareDatetime, Field, model_validator

from app.schemas.provenance import FrozenModel, Text
from app.schemas.scene import JobMinutes, Money, Quantity, SceneSpec

SafeResult = Annotated[int, Field(strict=True, ge=-(2**53 - 1), le=2**53 - 1)]
NonNegativeResult = Annotated[int, Field(strict=True, ge=0, le=2**53 - 1)]


class RetailInput(FrozenModel):
    unit_price_cents: Money
    unit_cost_cents: Money
    stock_qty: Quantity
    demand_qty: Quantity
    fixed_cost_cents: Money
    budget_cents: Money | None


class ServiceInput(FrozenModel):
    unit_price_cents: Money
    unit_cost_cents: Money
    minutes_per_job: JobMinutes
    available_minutes: Quantity
    booked: Quantity
    cancelled: Quantity
    fixed_cost_cents: Money

    @model_validator(mode="after")
    def check_cancellations(self) -> Self:
        if self.cancelled > self.booked:
            raise ValueError("cancelled must not exceed booked")
        return self


class ResultProvenance(FrozenModel):
    field: Text
    source: Literal["derived", "unknown"]
    derived_from: tuple[Text, ...]


class PerishableResult(FrozenModel):
    business_type: Literal["retail_perishable"] = "retail_perishable"
    sold: NonNegativeResult
    unsold: NonNegativeResult
    revenue_cents: NonNegativeResult
    cash_out_cents: NonNegativeResult
    result_cents: SafeResult
    budget_gap_cents: NonNegativeResult | None


class DurableResult(FrozenModel):
    business_type: Literal["retail_durable"] = "retail_durable"
    sold: NonNegativeResult
    unsold: NonNegativeResult
    revenue_cents: NonNegativeResult
    cash_out_cents: NonNegativeResult
    cash_change_cents: SafeResult
    simplified_period_profit_cents: SafeResult
    remaining_inventory_cost_cents: NonNegativeResult
    budget_gap_cents: NonNegativeResult | None


class ServiceResult(FrozenModel):
    business_type: Literal["appointment_service"] = "appointment_service"
    capacity: NonNegativeResult
    valid_bookings: NonNegativeResult
    completed: NonNegativeResult
    revenue_cents: NonNegativeResult
    cost_cents: NonNegativeResult
    simplified_result_cents: SafeResult
    idle_minutes: NonNegativeResult


SimulationResult = Annotated[
    PerishableResult | DurableResult | ServiceResult, Field(discriminator="business_type")
]


class ValidationIssue(FrozenModel):
    path: str
    code: str
    message: str


class ValidationResult(FrozenModel):
    valid: bool
    ready: bool
    errors: tuple[ValidationIssue, ...] = ()
    missing_fields: tuple[str, ...] = ()


class CalculationPreview(FrozenModel):
    """Ephemeral calculation of a draft, with no claim of a persisted scene version."""

    schema_version: Literal["1.0"] = "1.0"
    model_version: Text
    input_snapshot: SceneSpec
    scenario_label: Text
    result: SimulationResult
    provenance: tuple[ResultProvenance, ...]
    calculated_at: AwareDatetime

    @model_validator(mode="after")
    def normalize_time_and_version(self) -> Self:
        if self.model_version != self.input_snapshot.simulation_model_version:
            raise ValueError("snapshot model version differs from scene")
        if self.result.business_type != self.input_snapshot.business_type:
            raise ValueError("snapshot result differs from scene business type")
        object.__setattr__(self, "calculated_at", self.calculated_at.astimezone(UTC))
        return self


class SimulationSnapshot(CalculationPreview):
    scene_version_id: Text
