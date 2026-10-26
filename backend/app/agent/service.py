from typing import Any
from uuid import uuid4

from langchain_core.runnables import RunnableConfig
from langgraph.types import Command
from langsmith import tracing_context
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agent.contracts import (
    AgentResult,
    ExperimentDraft,
    Extraction,
    ProposedAction,
    Question,
    RiskCardView,
)
from app.agent.graph import build_graph
from app.agent.model import AgentFailure, ScenarioModel
from app.agent.runtime import Runtime
from app.agent.scenes import clarify, questions
from app.core.config import Settings
from app.core.errors import DomainError
from app.models.entities import AgentRun, Project, ToolInvocation
from app.schemas.api import ToolView
from app.services import business
from app.simulation.runner import parse_scene


def run_for(db: Session, project_id: str, run_id: str, owner: str) -> AgentRun:
    business.project_for(db, project_id, owner)
    run = db.scalar(
        select(AgentRun)
        .where(AgentRun.id == run_id, AgentRun.project_id == project_id)
        .with_for_update()
    )
    if run is None:
        raise DomainError(404, "AGENT_RUN_NOT_FOUND", "找不到这次分析或没有访问权限")
    return run


def view(db: Session, run: AgentRun) -> AgentResult:
    data = run.result_json
    tools = db.scalars(
        select(ToolInvocation)
        .where(ToolInvocation.agent_run_id == run.id)
        .order_by(ToolInvocation.created_at, ToolInvocation.id)
    )
    return AgentResult(
        id=run.id,
        thread_id=run.thread_id,
        status=run.status,
        stage=run.stage,
        total_steps=run.total_steps,
        total_calls=run.total_calls,
        request_id=run.request_id,
        error_code=run.error_code,
        scene=parse_scene(data["scene"]) if data.get("scene") else None,
        questions=tuple(Question.model_validate(q) for q in data.get("questions", [])),
        facts=Extraction.model_validate(data["extraction"]).texts if data.get("extraction") else (),
        risk_cards=tuple(RiskCardView.model_validate(c) for c in data.get("risk_cards", [])),
        proposed_actions=tuple(
            ProposedAction.model_validate(c["action"])
            for c in data.get("risk_cards", [])
            if c.get("action")
        ),
        scene_version_id=data.get("scene_version_id"),
        branch_version_id=data.get("branch_version_id"),
        experiment_draft=ExperimentDraft.model_validate(data["experiment_draft"])
        if data.get("experiment_draft")
        else None,
        tools=tuple(
            ToolView(
                id=t.id,
                tool_name=t.tool_name,
                input_summary=t.input_summary_json,
                output_summary=t.output_summary_json,
                status=t.status,
                duration_ms=t.duration_ms,
                request_id=t.request_id,
                scene_version_id=t.scene_version_id,
            )
            for t in tools
        ),
        model_calls=data.get("model_calls", []),
        model=data.get("model"),
        message=data.get("message", ""),
    )


def create(db: Session, project: Project, stage: str) -> AgentRun:
    run = AgentRun(
        project_id=project.id,
        thread_id=str(uuid4()),
        stage=stage,
        status="queued",
        total_steps=0,
        total_calls=0,
        result_json={},
    )
    db.add(run)
    db.flush()
    return run


def advance(
    db: Session,
    project: Project,
    run: AgentRun,
    owner: str,
    settings: Settings,
    model_factory: Any,
    request_id: str,
    key: str,
    *,
    command: str,
    payload: dict[str, Any] | None = None,
) -> AgentResult:
    payload = payload or {}
    previous = dict(run.result_json)
    run.request_id = request_id
    run.error_code = None
    runtime: Runtime | None = None
    try:
        model: ScenarioModel = model_factory()
        if previous.get("model") and previous["model"] != model.identity:
            raise AgentFailure("MODEL_CHANGED")
        runtime = Runtime(db, run, model, settings, request_id, key)
        config: RunnableConfig = {
            "configurable": {"thread_id": run.thread_id},
            "recursion_limit": 16,
            "callbacks": [],
        }
        with db.begin_nested(), tracing_context(enabled=False):
            graph = build_graph(runtime, project, owner)
            checkpoint = graph.get_state(config)
            state: dict[str, Any] = checkpoint.values.get("data", {}) or previous
            if command == "experiment":
                version = business.version_for(db, payload["scene_version_id"], owner)
                if version.project_id != project.id:
                    raise AgentFailure("PROJECT_MISMATCH")

                def draft_call() -> dict[str, Any]:
                    draft = runtime.call_model(
                        "draft_experiment",
                        lambda: model.experiment(
                            {
                                "scene": version.scene_spec_json,
                                "known_limits": "演示/用户自报并非外部核验",
                            }
                        ),
                    )
                    return draft.model_dump(mode="json")

                output = runtime.tool(
                    "draft_experiment",
                    draft_call,
                    {"scene_version_id": version.id, "draft_only": True},
                    version.id,
                )
                state = {
                    "experiment_draft": output,
                    "scene_version_id": version.id,
                    "status": "completed",
                    "message": "这是一张待你确认的任务草稿，尚未开展调查或保存任务。",
                }
            elif command == "clarify":
                if not state.get("scene") or state.get("status") not in {
                    "needs_input",
                    "needs_confirmation",
                }:
                    raise AgentFailure("INVALID_AGENT_STATE")
                scene = clarify(
                    parse_scene(state["scene"]),
                    payload.get("answers", {}),
                    payload.get("use_demo_assumptions", False),
                )
                from app.simulation.runner import validate_scene

                runtime.tool(
                    "validate_scene",
                    lambda: validate_scene(scene, "base").model_dump(mode="json"),
                    {"draft": True, "clarification": True},
                    None,
                )
                qs = questions(scene)
                state.update(
                    scene=scene.model_dump(mode="json"),
                    questions=[q.model_dump() for q in qs],
                    status="needs_input" if qs else "needs_confirmation",
                )
                graph.update_state(config, {"data": state}, as_node="prepare")
                graph.invoke(None, config=config, durability="sync")
                state = graph.get_state(config).values["data"]
            else:
                if command == "start":
                    initial = {"status": "running", "scenario_label": "base"}
                    graph.invoke({"data": initial}, config=config, durability="sync")
                elif command == "analyze":
                    version = business.version_for(db, payload["scene_version_id"], owner)
                    if version.project_id != project.id:
                        raise AgentFailure("PROJECT_MISMATCH")
                    graph.invoke(
                        {
                            "data": {
                                "scene_version_id": version.id,
                                "scene": version.scene_spec_json,
                                "scenario_label": payload["scenario_label"],
                                "status": "running",
                            }
                        },
                        config=config,
                        durability="sync",
                    )
                elif command == "confirm":
                    if run.status not in {"needs_confirmation", "failed"}:
                        raise AgentFailure("INVALID_AGENT_STATE")
                    graph.invoke(
                        Command(resume={"confirmed": True}), config=config, durability="sync"
                    )
                elif command == "action":
                    if run.status == "completed" and state.get("chosen_action") == payload.get(
                        "action_id"
                    ):
                        return view(db, run)
                    if state.get("status") != "needs_choice":
                        raise AgentFailure("INVALID_AGENT_STATE")
                    graph.invoke(
                        Command(resume={"confirmed": True, "action_id": payload["action_id"]}),
                        config=config,
                        durability="sync",
                    )
                else:
                    raise AgentFailure("INVALID_AGENT_STATE")
                state = graph.get_state(config).values["data"]
            run.result_json = {
                **state,
                "model": model.identity,
                "model_calls": previous.get("model_calls", []) + runtime.model_calls,
                "last_command": command,
                "last_payload": payload or {},
            }
            run.status = state.get("status", "completed")
            run.stage = "wait_choice" if run.status == "needs_choice" else command
    except Exception as error:
        code = error.code if isinstance(error, AgentFailure) else "AGENT_EXECUTION_FAILED"
        # Keep the prior checkpoint, safe draft and failure summaries; never exception text/keys.
        run.status = "failed"
        run.error_code = code
        run.result_json = {
            **previous,
            "last_command": command,
            "last_payload": payload or {},
            "model_calls": previous.get("model_calls", [])
            + (runtime.model_calls if runtime else []),
            "message": {
                "LLM_AUTHENTICATION_FAILED": "智能整理服务连接失败，请稍后再试。手动预演仍可用。",
                "LLM_ACCESS_DENIED": "访问被拒绝，请检查模型权限和环境域名。手动预演仍可用。",
                "LLM_RATE_LIMITED": "服务限流或额度不足，请稍后重试。手动预演仍可用。",
                "LLM_TIMEOUT": "模型服务超时，请稍后重试。已保存方案不会被覆盖。",
                "SHARED_MODEL_LIMIT": "智能整理本期体验额度已用完，手动场景和经营过程仍可使用。",
                "MODEL_INPUT_LIMIT": "这次内容过长，请简化想法后再试。手动预演仍可用。",
                "MODEL_CHANGED": "模型已切换，请重新准备草稿；原方案和用户事实不会被覆盖。",
            }.get(code, "智能整理这次未完成。已保存的方案仍可手动预演，也可稍后重试。"),
        }
    if runtime:
        run.total_steps += runtime.nodes
        run.total_calls += runtime.calls
        for log in runtime.logs:
            rolled_back = run.status == "failed"
            db.add(
                ToolInvocation(
                    agent_run_id=run.id,
                    tool_name=log["tool_name"],
                    input_summary_json={
                        **log["input_summary"],
                        "scene_version_id": None,
                        "rolled_back": True,
                    }
                    if rolled_back
                    else log["input_summary"],
                    output_summary_json={} if rolled_back else log["output_summary"],
                    status="rolled_back"
                    if rolled_back and log["status"] == "completed"
                    else log["status"],
                    duration_ms=log["duration_ms"],
                    request_id=request_id,
                    idempotency_key=key,
                    scene_version_id=None if rolled_back else log["scene_version_id"],
                )
            )
    db.flush()
    return view(db, run)
