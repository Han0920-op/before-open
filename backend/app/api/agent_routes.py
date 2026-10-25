from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel

from app.agent import service
from app.agent.contracts import (
    ActionInput,
    AgentConfirmation,
    AgentResult,
    AnalyzeInput,
    ClarificationInput,
    ConnectionInput,
    ModelStatus,
    RetryInput,
    StartInput,
)
from app.agent.model import PROVIDERS, AgentFailure
from app.api.routes import Key, envelope, write
from app.core.errors import DomainError
from app.core.security import Actor, Db
from app.schemas.api import Envelope
from app.services import business

router = APIRouter(prefix="/api/v1")


def model_status(request: Request, actor: Actor) -> ModelStatus:
    connection = request.app.state.model_connections.get(actor.id)
    return ModelStatus(
        connected=connection is not None,
        provider=connection.provider if connection else None,
        model=connection.model if connection else None,
        available_models={key: tuple(value["models"]) for key, value in PROVIDERS.items()},
        verified=connection.verified if connection else False,
    )


@router.get("/models", response_model=Envelope[ModelStatus])
def models(request: Request, actor: Actor) -> Envelope[ModelStatus]:
    return envelope(request, model_status(request, actor))


@router.post("/model-connection", response_model=Envelope[ModelStatus])
def connect_model(request: Request, body: ConnectionInput, actor: Actor) -> Envelope[ModelStatus]:
    local = bool(
        request.client and request.client.host in {"127.0.0.1", "::1", "testclient"}
    ) and request.url.hostname in {"127.0.0.1", "localhost", "testserver"}
    if request.url.scheme != "https" and not local:
        raise DomainError(400, "HTTPS_REQUIRED", "模型密钥只能通过HTTPS提交，本机开发除外")
    if not body.authorize_paid_calls:
        raise DomainError(422, "MODEL_AUTHORIZATION_REQUIRED", "请确认模型调用可能产生费用")
    try:
        request.app.state.model_connections.connect(
            actor.id, body.provider, body.model, body.api_key.get_secret_value()
        )
    except AgentFailure as error:
        raise DomainError(422, error.code, "模型不在当前支持列表或连接已达上限") from None
    return envelope(request, model_status(request, actor))


@router.post("/model-connection/disconnect", response_model=Envelope[ModelStatus])
def disconnect_model(request: Request, actor: Actor) -> Envelope[ModelStatus]:
    request.app.state.model_connections.disconnect(actor.id)
    return envelope(request, model_status(request, actor))


def execute(
    request: Request,
    db: Db,
    actor: Actor,
    project_id: str,
    key: str,
    body: BaseModel,
    command: str,
    run_id: str | None = None,
    payload: dict[str, Any] | None = None,
) -> Envelope[AgentResult]:
    project = business.project_for(db, project_id, actor.id)
    if command in {"analyze", "experiment"} and payload:
        version = business.version_for(db, payload["scene_version_id"], actor.id)
        if version.project_id != project.id:
            raise DomainError(422, "PROJECT_MISMATCH", "方案不属于当前想法")

    def operation() -> AgentResult:
        run = (
            service.run_for(db, project_id, run_id, actor.id)
            if run_id
            else service.create(db, project, command)
        )
        if command == "confirm" and run.status != "needs_confirmation":
            raise DomainError(
                409, "INVALID_AGENT_STATE", "草稿尚未就绪或已确认，请读取当前执行结果"
            )
        if command == "action":
            action_id = (payload or {}).get("action_id")
            if run.status == "completed" and run.result_json.get("chosen_action") == action_id:
                return service.view(db, run)
            allowed = {
                c["action"]["id"] for c in run.result_json.get("risk_cards", []) if c.get("action")
            }
            if run.status != "needs_choice" or action_id not in allowed:
                raise DomainError(409, "ACTION_NOT_ALLOWED", "请从本次分析的待确认建议中选择")
        actual_command, actual_payload = command, payload
        if command == "retry":
            if run.status != "failed":
                raise DomainError(409, "INVALID_AGENT_STATE", "这次执行不需要重试")
            actual_command = run.result_json.get("last_command", "start")
            actual_payload = run.result_json.get("last_payload", {})
        return service.advance(
            db,
            project,
            run,
            actor.id,
            request.app.state.settings,
            lambda: request.app.state.agent_model_factory(actor.id),
            request.state.request_id,
            key,
            command=actual_command,
            payload=actual_payload,
        )

    return write(request, db, actor, key, body, operation, AgentResult)


@router.post("/projects/{project_id}/scene-draft", response_model=Envelope[AgentResult])
def scene_draft(
    project_id: str, request: Request, body: StartInput, db: Db, actor: Actor, key: Key
) -> Envelope[AgentResult]:
    return execute(request, db, actor, project_id, key, body, "start")


@router.post("/projects/{project_id}/clarifications", response_model=Envelope[AgentResult])
def clarify(
    project_id: str, request: Request, body: ClarificationInput, db: Db, actor: Actor, key: Key
) -> Envelope[AgentResult]:
    return execute(
        request, db, actor, project_id, key, body, "clarify", body.run_id, body.model_dump()
    )


@router.post("/projects/{project_id}/agent-confirm", response_model=Envelope[AgentResult])
def confirm(
    project_id: str, request: Request, body: AgentConfirmation, db: Db, actor: Actor, key: Key
) -> Envelope[AgentResult]:
    return execute(request, db, actor, project_id, key, body, "confirm", body.run_id)


@router.post("/projects/{project_id}/agent-runs", response_model=Envelope[AgentResult])
def analyze(
    project_id: str, request: Request, body: AnalyzeInput, db: Db, actor: Actor, key: Key
) -> Envelope[AgentResult]:
    return execute(request, db, actor, project_id, key, body, "analyze", payload=body.model_dump())


@router.post(
    "/projects/{project_id}/agent-runs/{run_id}/actions", response_model=Envelope[AgentResult]
)
def apply_action(
    project_id: str,
    run_id: str,
    request: Request,
    body: ActionInput,
    db: Db,
    actor: Actor,
    key: Key,
) -> Envelope[AgentResult]:
    return execute(request, db, actor, project_id, key, body, "action", run_id, body.model_dump())


@router.post("/projects/{project_id}/agent-retry", response_model=Envelope[AgentResult])
def retry(
    project_id: str, request: Request, body: RetryInput, db: Db, actor: Actor, key: Key
) -> Envelope[AgentResult]:
    return execute(request, db, actor, project_id, key, body, "retry", body.run_id)


@router.post("/projects/{project_id}/experiment-draft", response_model=Envelope[AgentResult])
def experiment(
    project_id: str, request: Request, body: AnalyzeInput, db: Db, actor: Actor, key: Key
) -> Envelope[AgentResult]:
    return execute(
        request, db, actor, project_id, key, body, "experiment", payload=body.model_dump()
    )
