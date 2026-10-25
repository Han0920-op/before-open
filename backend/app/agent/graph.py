from collections.abc import Callable
from typing import Any, TypedDict

from langchain_core.runnables import RunnableLambda
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt
from sqlalchemy import select

from app.agent.checkpoints import TransactionSaver
from app.agent.contracts import Extraction, RiskCardView
from app.agent.model import AgentFailure
from app.agent.runtime import Runtime
from app.agent.scenes import build_scene, grounded, questions
from app.agent.tools import execute, risks
from app.models.entities import Project, RiskCard, SceneVersion
from app.services import business
from app.simulation.runner import parse_scene, validate_scene


class AgentState(TypedDict):
    data: dict[str, Any]


def typed_node(
    function: Callable[[dict[str, Any]], dict[str, Any]],
) -> Callable[[AgentState], AgentState]:
    def wrapped(state: AgentState) -> AgentState:
        return {"data": function(state["data"])}

    return wrapped


def build_graph(runtime: Runtime, project: Project, session_id: str) -> Any:
    def extract(state: dict[str, Any]) -> dict[str, Any]:
        extraction = runtime.call_model(
            "parse_intent",
            lambda: grounded(runtime.model.extract(project.original_idea), project.original_idea),
        )
        if extraction.business_type in {"unsupported", "uncertain"}:
            return {
                **state,
                "status": "unsupported",
                "message": "这个想法暂时不能完整模拟，请选择受支持的简化方式或手动准备。",
            }
        return {**state, "extraction": extraction.model_dump(mode="json")}

    def prepare(state: dict[str, Any]) -> dict[str, Any]:
        scene = (
            parse_scene(state["scene"])
            if state.get("scene")
            else build_scene(project, Extraction.model_validate(state["extraction"]))
        )
        seed = runtime.db.scalar(
            select(SceneVersion)
            .where(SceneVersion.project_id == project.id)
            .order_by(SceneVersion.created_at.desc(), SceneVersion.id.desc())
            .limit(1)
        )
        seed_id = state.get("seed_version_id")
        if seed is not None and not state.get("scene"):
            existing = parse_scene(seed.scene_spec_json)
            if existing.business_type != scene.business_type:
                raise AgentFailure("BUSINESS_TYPE_CHANGE_REQUIRES_MANUAL")
            raw = existing.model_dump(mode="json")
            extracted = scene.model_dump(mode="json")
            for key, field in raw["fields"].items():
                if field["value"] is None and extracted["fields"][key]["value"] is not None:
                    raw["fields"][key] = extracted["fields"][key]
            scene = parse_scene(raw)
            seed_id = seed.id
        label = (
            "base"
            if scene.business_type == "appointment_service"
            else scene.demand_scenarios[0].scenario_label
        )
        qs = questions(scene)
        runtime.tool(
            "validate_scene",
            lambda: validate_scene(scene, label).model_dump(mode="json"),
            {"business_type": scene.business_type, "draft": True},
            None,
        )
        return {
            **state,
            "scene": scene.model_dump(mode="json"),
            "questions": [q.model_dump() for q in qs],
            "seed_version_id": seed_id,
            "scenario_label": label,
            "status": "needs_input" if qs else "needs_confirmation",
        }

    def human_confirm(state: dict[str, Any]) -> dict[str, Any]:
        decision = interrupt({"status": state["status"], "questions": state["questions"]})
        if not isinstance(decision, dict) or decision.get("confirmed") is not True:
            raise AgentFailure("CONFIRMATION_REQUIRED")
        return {**state, "status": "running"}

    def save(state: dict[str, Any]) -> dict[str, Any]:
        scene = parse_scene(state["scene"])
        if not validate_scene(scene, state.get("scenario_label", "base")).ready:
            raise AgentFailure("SIMULATION_NOT_READY")
        parent = (
            business.version_for(runtime.db, state["seed_version_id"], session_id)
            if state.get("seed_version_id")
            else None
        )
        version = business.create_version(runtime.db, project, scene, parent)
        return {**state, "scene_version_id": version.id}

    def plan(state: dict[str, Any]) -> dict[str, Any]:
        version = business.version_for(runtime.db, state["scene_version_id"], session_id)
        plan = runtime.call_model(
            "choose_tools",
            lambda: runtime.model.plan(
                {"scene": version.scene_spec_json, "parent_version_id": version.parent_version_id}
            ),
        )
        names = plan.tools
        expected = (
            "calculate_service"
            if version.business_type == "appointment_service"
            else "calculate_retail"
        )
        if expected not in names or len(names) != len(set(names)):
            raise AgentFailure("INVALID_TOOL_PLAN")
        return {**state, "tool_plan": list(names)}

    def run_tools(state: dict[str, Any]) -> dict[str, Any]:
        version = business.version_for(runtime.db, state["scene_version_id"], session_id)
        outputs = {
            name: execute(runtime, name, version, state.get("scenario_label", "base"), session_id)
            for name in state["tool_plan"]
        }
        return {**state, "tool_results": outputs}

    def risk_review(state: dict[str, Any]) -> dict[str, Any]:
        output = (
            state["tool_results"].get("calculate_retail")
            or state["tool_results"]["calculate_service"]
        )
        result = runtime.tool(
            "generate_risk_cards",
            lambda: {"cards": [c.model_dump(mode="json") for c in risks(output)]},
            {"scene_version_id": state["scene_version_id"], "tools": state["tool_plan"]},
            state["scene_version_id"],
        )
        for raw in result["cards"]:
            card = RiskCardView.model_validate(raw)
            runtime.db.add(
                RiskCard(
                    scene_version_id=state["scene_version_id"],
                    type=card.type,
                    text=card.text,
                    evidence_json=card.evidence,
                    severity=card.severity,
                    user_action=card.action.id if card.action else "view_evidence",
                )
            )
        return {
            **state,
            "risk_cards": result["cards"],
            "status": "needs_choice",
            "message": "已按确认的条件运行工具，可以查看依据或尝试独立方案。",
        }

    def wait_choice(state: dict[str, Any]) -> dict[str, Any]:
        decision = interrupt({"status": "needs_choice"})
        if not isinstance(decision, dict) or decision.get("confirmed") is not True:
            raise AgentFailure("CONFIRMATION_REQUIRED")
        return {**state, "chosen_action": decision.get("action_id")}

    def apply(state: dict[str, Any]) -> dict[str, Any]:
        selected = next(
            (
                card["action"]
                for card in state["risk_cards"]
                if card.get("action") and card["action"]["id"] == state["chosen_action"]
            ),
            None,
        )
        if selected is None:
            raise AgentFailure("ACTION_NOT_ALLOWED")
        parent = business.version_for(runtime.db, state["scene_version_id"], session_id)
        raw = parse_scene(parent.scene_spec_json).model_dump(mode="json")
        for change in selected["changes"]:
            raw["fields"][change["field"]] = {
                "value": change["value"],
                "source": "user_input",
                "note": "用户明确接受的备选方案，不覆盖父版本",
            }
        child = business.create_version(runtime.db, project, parse_scene(raw), parent)
        row = business.version_for(runtime.db, child.id, session_id)
        calculate = (
            "calculate_service"
            if row.business_type == "appointment_service"
            else "calculate_retail"
        )
        execute(runtime, calculate, row, state.get("scenario_label", "base"), session_id)
        execute(runtime, "compare_versions", row, state.get("scenario_label", "base"), session_id)
        return {
            **state,
            "branch_version_id": child.id,
            "status": "completed",
            "message": "已创建独立方案并完成比较，原版本保留。",
        }

    graph = StateGraph(AgentState)
    for name, function in {
        "extract": extract,
        "prepare": prepare,
        "human_confirm": human_confirm,
        "save": save,
        "plan": plan,
        "run_tools": run_tools,
        "risk_review": risk_review,
        "wait_choice": wait_choice,
        "apply": apply,
    }.items():
        graph.add_node(name, RunnableLambda(typed_node(runtime.node(function))))
    graph.add_conditional_edges(
        START, lambda state: "plan" if state["data"].get("scene_version_id") else "extract"
    )
    graph.add_conditional_edges(
        "extract", lambda state: END if state["data"].get("status") == "unsupported" else "prepare"
    )
    for a, b in [
        ("prepare", "human_confirm"),
        ("human_confirm", "save"),
        ("save", "plan"),
        ("plan", "run_tools"),
        ("run_tools", "risk_review"),
        ("risk_review", "wait_choice"),
        ("wait_choice", "apply"),
        ("apply", END),
    ]:
        graph.add_edge(a, b)
    return graph.compile(checkpointer=TransactionSaver(runtime.db, runtime.lock))
