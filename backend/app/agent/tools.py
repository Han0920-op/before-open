from typing import Any

from app.agent.contracts import Change, ProposedAction, RiskCardView
from app.agent.model import AgentFailure
from app.agent.runtime import Runtime
from app.models.entities import SceneVersion
from app.schemas.api import CompareRequest
from app.schemas.scene import ServiceScene
from app.services import business
from app.simulation.common import check_budget
from app.simulation.runner import parse_scene, run_demand_scenarios, validate_scene


def execute(
    runtime: Runtime, name: str, version: SceneVersion, label: str, session_id: str
) -> dict[str, Any]:
    scene = parse_scene(version.scene_spec_json)
    summary = {"scene_version_id": version.id, "scenario_label": label}

    def call() -> dict[str, Any]:
        if name == "validate_scene":
            return validate_scene(scene, label).model_dump(mode="json")
        if name == "calculate_service" and isinstance(scene, ServiceScene):
            return business.create_run(runtime.db, version, label).snapshot.model_dump(mode="json")
        if name == "calculate_retail" and not isinstance(scene, ServiceScene):
            return business.create_run(runtime.db, version, label).snapshot.model_dump(mode="json")
        if name == "check_budget" and not isinstance(scene, ServiceScene):
            c, q, f, b = (
                scene.fields.unit_cost_cents.value,
                scene.fields.stock_qty.value,
                scene.fields.fixed_cost_cents.value,
                scene.fields.budget_cents.value,
            )
            if c is None or q is None or f is None:
                raise AgentFailure("SIMULATION_NOT_READY")
            cash_out = q * c + f
            return {
                "cash_out_cents": cash_out,
                "budget_cents": b,
                "budget_gap_cents": check_budget(b, cash_out),
            }
        if name == "run_demand_scenarios" and not isinstance(scene, ServiceScene):
            from datetime import UTC, datetime

            runs = run_demand_scenarios(
                scene, scene_version_id=version.id, calculated_at=datetime.now(UTC)
            )
            return {"results": [r.model_dump(mode="json") for r in runs]}
        if name == "compare_versions" and version.parent_version_id:
            project = business.project_for(runtime.db, version.project_id, session_id)
            parent = business.version_for(runtime.db, version.parent_version_id, session_id)
            parent_scene = parse_scene(parent.scene_spec_json)
            parent_label = (
                "base"
                if isinstance(parent_scene, ServiceScene)
                else parent_scene.demand_scenarios[0].scenario_label
            )
            return business.compare(
                runtime.db,
                project,
                CompareRequest(
                    left_version_id=parent.id,
                    right_version_id=version.id,
                    left_scenario_label=parent_label,
                    right_scenario_label=label,
                ),
                session_id,
            ).model_dump(mode="json")
        raise AgentFailure("TOOL_NOT_ALLOWED")

    return runtime.tool(name, call, summary, version.id)


def risks(calculation: dict[str, Any]) -> tuple[RiskCardView, ...]:
    scene = parse_scene(calculation["input_snapshot"])
    result = calculation["result"]
    evidence = {
        "model_version": calculation["model_version"],
        "scenario_label": calculation["scenario_label"],
    }
    cards: list[RiskCardView] = []
    if not isinstance(scene, ServiceScene):
        gap = result["budget_gap_cents"]
        if gap is None:
            cards.append(
                RiskCardView(
                    type="unknown_budget",
                    text="预算还没填，暂时不能判断钱够不够。",
                    severity="info",
                    evidence={**evidence, "budget_gap_cents": None},
                )
            )
        elif gap > 0:
            b, f, c, q = (
                scene.fields.budget_cents.value,
                scene.fields.fixed_cost_cents.value,
                scene.fields.unit_cost_cents.value,
                scene.fields.stock_qty.value,
            )
            action = None
            if b is not None and f is not None and c and q and b >= f:
                qty = min(q, (b - f) // c)
                action = ProposedAction(
                    id="reduce_stock",
                    label=f"试试备货{qty}份的方案",
                    changes=(Change(field="stock_qty", value=qty),),
                )
            cards.append(
                RiskCardView(
                    type="budget_gap",
                    text=(
                        f"按目前投入，预算还差{gap // 100}.{gap % 100:02d}元。"
                        "可以比较更小的备货方案。"
                    ),
                    severity="warning",
                    evidence={**evidence, "budget_gap_cents": gap},
                    action=action,
                )
            )
        if result["unsold"] > 0:
            action = None
            if scene.business_type == "retail_perishable":
                action = ProposedAction(
                    id="match_assumed_demand",
                    label="试试按这组假设备货",
                    changes=(Change(field="stock_qty", value=result["sold"]),),
                )
            cards.append(
                RiskCardView(
                    type="unsold",
                    severity="warning" if action else "info",
                    text="这组需求假设下会有剩余。易损耗商品整批成本已发生，可保留库存则应分开看现金与期间结果。",
                    evidence={**evidence, "unsold": result["unsold"]},
                    action=action,
                )
            )
    elif result["valid_bookings"] > result["capacity"]:
        cards.append(
            RiskCardView(
                type="capacity",
                severity="warning",
                text="这组有效预约超过了可用时间的服务容量，未完成预约没有计入收入。",
                evidence={
                    **evidence,
                    "capacity": result["capacity"],
                    "valid_bookings": result["valid_bookings"],
                },
            )
        )
    if len(cards) < 3:
        cards.append(
            RiskCardView(
                type="assumption_boundary",
                severity="info",
                text="需求、预约和成本仍取决于输入条件。这不是现实销量或经营许可证明，可先做小样本观察。",
                evidence=evidence,
            )
        )
    return tuple(cards[:3])
