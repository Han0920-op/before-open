"""Scene drafts preserve unknown values; execution readiness is a separate check."""

from typing import Annotated, Literal, Self

from pydantic import Field, StrictBool, TypeAdapter, model_validator

from app.schemas.provenance import ExternalEvidence, FrozenModel, Source, SourceField, Text

Money = Annotated[int, Field(strict=True, ge=0, le=10**9)]
Quantity = Annotated[int, Field(strict=True, ge=0, le=10**6)]
JobMinutes = Annotated[int, Field(strict=True, ge=1, le=10**6)]


class LocationSpec(FrozenModel):
    location_type: Text
    description: Text
    source: Source = "unknown"
    verified: StrictBool = False
    evidence: ExternalEvidence | None = None
    observation_id: Text | None = None
    derived_from: tuple[Text, ...] = ()

    @model_validator(mode="after")
    def check_verification(self) -> Self:
        SourceField[Text](
            value=None if self.source == "unknown" else self.description,
            source=self.source,
            evidence=self.evidence,
            observation_id=self.observation_id,
            derived_from=self.derived_from,
        )
        if self.verified != (self.source == "verified_external"):
            raise ValueError("verified must agree with source")
        if self.verified != (self.evidence is not None):
            raise ValueError("verified location requires external evidence")
        return self


class RetailFields(FrozenModel):
    budget_cents: SourceField[Money]
    unit_price_cents: SourceField[Money]
    unit_cost_cents: SourceField[Money]
    stock_qty: SourceField[Quantity]
    fixed_cost_cents: SourceField[Money]


class ServiceFields(FrozenModel):
    unit_price_cents: SourceField[Money]
    unit_cost_cents: SourceField[Money]
    minutes_per_job: SourceField[JobMinutes]
    available_minutes: SourceField[Quantity]
    booked: SourceField[Quantity]
    cancelled: SourceField[Quantity]
    fixed_cost_cents: SourceField[Money]

    @model_validator(mode="after")
    def check_cancellations(self) -> Self:
        booked, cancelled = self.booked.value, self.cancelled.value
        if booked is not None and cancelled is not None and cancelled > booked:
            raise ValueError("cancelled must not exceed booked")
        return self


class DemandScenario(FrozenModel):
    scenario_label: Text
    demand_qty: SourceField[Quantity]


class SceneBase(FrozenModel):
    schema_version: Literal["1.0"] = "1.0"
    currency: Literal["CNY"] = "CNY"
    title: Text
    original_idea: Text
    location: LocationSpec
    period_note: Text  # Explicit single simulation period and fixed-cost scope.
    unknowns: tuple[str, ...] = ()


class RetailSceneBase(SceneBase):
    fields: RetailFields
    demand_scenarios: tuple[DemandScenario, ...] = ()

    @model_validator(mode="after")
    def normalize_unknowns(self) -> Self:
        labels = [s.scenario_label for s in self.demand_scenarios]
        if len(labels) != len(set(labels)):
            raise ValueError("scenario labels must be unique")
        paths = [
            f"fields.{name}"
            for name in type(self.fields).model_fields
            if getattr(self.fields, name).value is None
        ]
        paths.extend(
            f"demand_scenarios.{i}.demand_qty"
            for i, scenario in enumerate(self.demand_scenarios)
            if scenario.demand_qty.value is None
        )
        object.__setattr__(self, "unknowns", tuple(paths))
        return self


class PerishableScene(RetailSceneBase):
    business_type: Literal["retail_perishable"]
    simulation_model_version: Literal["retail-perishable-v1"]


class DurableScene(RetailSceneBase):
    business_type: Literal["retail_durable"]
    simulation_model_version: Literal["retail-durable-v1"]


class ServiceScene(SceneBase):
    business_type: Literal["appointment_service"]
    simulation_model_version: Literal["service-v1"]
    fields: ServiceFields
    demand_scenarios: tuple[DemandScenario, ...] = Field(default=(), max_length=0)

    @model_validator(mode="after")
    def normalize_unknowns(self) -> Self:
        object.__setattr__(
            self,
            "unknowns",
            tuple(
                f"fields.{name}"
                for name in type(self.fields).model_fields
                if getattr(self.fields, name).value is None
            ),
        )
        return self


SceneSpec = Annotated[
    PerishableScene | DurableScene | ServiceScene, Field(discriminator="business_type")
]
# Pydantic supports Annotated unions at runtime; its constructor overload is narrower.
scene_adapter: TypeAdapter[SceneSpec] = TypeAdapter(SceneSpec)  # type: ignore[arg-type]
