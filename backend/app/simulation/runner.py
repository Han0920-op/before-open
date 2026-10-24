"""Validate drafts, dispatch pure calculations and build reproducible input envelopes."""

from datetime import datetime
from typing import cast

from pydantic import ValidationError

from app.schemas.scene import (
    DemandScenario,
    RetailSceneBase,
    SceneBase,
    SceneSpec,
    ServiceScene,
    scene_adapter,
)
from app.schemas.simulation import (
    CalculationPreview,
    ResultProvenance,
    RetailInput,
    ServiceInput,
    SimulationResult,
    SimulationSnapshot,
    ValidationIssue,
    ValidationResult,
)
from app.simulation.retail import calculate_durable, calculate_perishable
from app.simulation.service import calculate_service


class SimulationError(ValueError):
    def __init__(self, code: str, validation: ValidationResult) -> None:
        super().__init__(code)
        self.code = code
        self.validation = validation


def parse_scene(raw: object) -> SceneSpec:
    # Revalidate even existing model objects: model_copy(update=...) bypasses validation.
    if isinstance(raw, SceneBase):
        raw = raw.model_dump(mode="python")
    return scene_adapter.validate_python(raw)


def validate_scene(raw: object, scenario_label: str | None = None) -> ValidationResult:
    try:
        scene = parse_scene(raw)
    except ValidationError as error:
        return ValidationResult(
            valid=False,
            ready=False,
            errors=tuple(
                ValidationIssue(
                    path=".".join(str(part) for part in item["loc"]),
                    code=item["type"],
                    message=item["msg"],
                )
                for item in error.errors(include_input=False, include_url=False)
            ),
        )
    missing = [path for path in scene.unknowns if path.startswith("fields.")]
    # Budget is optional for profit computation, not silently replaced by zero.
    missing = [path for path in missing if path != "fields.budget_cents"]
    if isinstance(scene, RetailSceneBase):
        selected = scene.demand_scenarios
        if scenario_label is not None:
            selected = tuple(s for s in selected if s.scenario_label == scenario_label)
            if not selected:
                return ValidationResult(
                    valid=False,
                    ready=False,
                    errors=(
                        ValidationIssue(
                            path="scenario_label",
                            code="SCENARIO_NOT_FOUND",
                            message="select an existing demand scenario",
                        ),
                    ),
                )
        if not selected:
            missing.append("demand_scenarios")
        for i, scenario in enumerate(scene.demand_scenarios):
            if scenario in selected and scenario.demand_qty.value is None:
                missing.append(f"demand_scenarios.{i}.demand_qty")
    return ValidationResult(valid=True, ready=not missing, missing_fields=tuple(missing))


def _required(raw: object, scenario_label: str | None) -> SceneSpec:
    validation = validate_scene(raw, scenario_label)
    if not validation.valid or not validation.ready:
        raise SimulationError(
            "INVALID_SCENE" if not validation.valid else "SIMULATION_NOT_READY", validation
        )
    return parse_scene(raw)


def _retail_input(scene: RetailSceneBase, scenario: DemandScenario) -> RetailInput:
    fields = scene.fields
    return RetailInput(
        unit_price_cents=cast(int, fields.unit_price_cents.value),
        unit_cost_cents=cast(int, fields.unit_cost_cents.value),
        stock_qty=cast(int, fields.stock_qty.value),
        fixed_cost_cents=cast(int, fields.fixed_cost_cents.value),
        budget_cents=fields.budget_cents.value,
        demand_qty=cast(int, scenario.demand_qty.value),
    )


def _service_input(scene: ServiceScene) -> ServiceInput:
    return ServiceInput.model_validate(
        {name: getattr(scene.fields, name).value for name in type(scene.fields).model_fields}
    )


def _provenance(
    scene: SceneSpec, result: SimulationResult, label: str
) -> tuple[ResultProvenance, ...]:
    # Paths refer to input_snapshot. Each result has an explicit dependency set.
    if isinstance(scene, RetailSceneBase):
        i = next(i for i, item in enumerate(scene.demand_scenarios) if item.scenario_label == label)
        stock, demand = "fields.stock_qty", f"demand_scenarios.{i}.demand_qty"
        sales = (stock, demand)
        revenue = (*sales, "fields.unit_price_cents")
        cash_out = (stock, "fields.unit_cost_cents", "fields.fixed_cost_cents")
        deps = {
            "sold": sales,
            "unsold": sales,
            "revenue_cents": revenue,
            "cash_out_cents": cash_out,
            "result_cents": tuple(dict.fromkeys((*revenue, *cash_out))),
            "cash_change_cents": tuple(dict.fromkeys((*revenue, *cash_out))),
            "simplified_period_profit_cents": (
                *revenue,
                "fields.unit_cost_cents",
                "fields.fixed_cost_cents",
            ),
            "remaining_inventory_cost_cents": (*sales, "fields.unit_cost_cents"),
            "budget_gap_cents": (*cash_out, "fields.budget_cents"),
        }
    else:
        capacity = ("fields.available_minutes", "fields.minutes_per_job")
        valid = ("fields.booked", "fields.cancelled")
        completed = (*capacity, *valid)
        deps = {
            "capacity": capacity,
            "valid_bookings": valid,
            "completed": completed,
            "revenue_cents": (*completed, "fields.unit_price_cents"),
            "cost_cents": (*completed, "fields.unit_cost_cents", "fields.fixed_cost_cents"),
            "simplified_result_cents": (
                *completed,
                "fields.unit_price_cents",
                "fields.unit_cost_cents",
                "fields.fixed_cost_cents",
            ),
            "idle_minutes": completed,
        }
    return tuple(
        ResultProvenance(
            field=name,
            source="unknown" if value is None else "derived",
            derived_from=deps[name],
        )
        for name, value in result.model_dump().items()
        if name != "business_type"
    )


def preview(
    raw: object,
    *,
    scenario_label: str,
    calculated_at: datetime,
) -> CalculationPreview:
    """Calculate an unsaved draft without creating or claiming a business version."""
    scene = _required(raw, scenario_label)
    result: SimulationResult
    if isinstance(scene, ServiceScene):
        result = calculate_service(_service_input(scene))
    else:
        scenario = next(s for s in scene.demand_scenarios if s.scenario_label == scenario_label)
        data = _retail_input(scene, scenario)
        if scene.business_type == "retail_perishable":
            result = calculate_perishable(data)
        else:
            result = calculate_durable(data)
    return CalculationPreview(
        model_version=scene.simulation_model_version,
        input_snapshot=scene,
        scenario_label=scenario_label,
        result=result,
        provenance=_provenance(scene, result, scenario_label),
        calculated_at=calculated_at,
    )


def simulate(
    raw: object,
    *,
    scene_version_id: str,
    scenario_label: str,
    calculated_at: datetime,
) -> SimulationSnapshot:
    """Only callers persisting a version should attach its business version ID."""
    calculation = preview(raw, scenario_label=scenario_label, calculated_at=calculated_at)
    return SimulationSnapshot(scene_version_id=scene_version_id, **calculation.model_dump())


def run_demand_scenarios(
    raw: object,
    *,
    scene_version_id: str,
    calculated_at: datetime,
) -> tuple[SimulationSnapshot, ...]:
    """Run all supplied retail assumptions or reject the entire incomplete batch."""
    scene = _required(raw, None)
    if isinstance(scene, ServiceScene):
        raise SimulationError(
            "UNSUPPORTED_BUSINESS_TYPE",
            ValidationResult(
                valid=False,
                ready=False,
                errors=(
                    ValidationIssue(
                        path="business_type",
                        code="UNSUPPORTED_BUSINESS_TYPE",
                        message="demand scenarios apply only to retail",
                    ),
                ),
            ),
        )
    return tuple(
        simulate(
            scene,
            scene_version_id=scene_version_id,
            scenario_label=scenario.scenario_label,
            calculated_at=calculated_at,
        )
        for scenario in scene.demand_scenarios
    )


def replay_snapshot(snapshot: SimulationSnapshot) -> SimulationSnapshot:
    """Recompute from the saved input, and reject results/provenance that were altered."""
    replayed = simulate(
        snapshot.input_snapshot,
        scene_version_id=snapshot.scene_version_id,
        scenario_label=snapshot.scenario_label,
        calculated_at=snapshot.calculated_at,
    )
    if replayed != snapshot:
        raise ValueError("snapshot does not match recomputed result and provenance")
    return replayed
