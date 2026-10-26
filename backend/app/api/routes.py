from collections.abc import Callable
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Header, Query, Request, Response
from pydantic import BaseModel
from sqlalchemy import select, text

from app.agent.contracts import AgentResult
from app.core.errors import DomainError
from app.core.security import Actor, Db, open_session
from app.models.entities import Project, SceneVersion, SimulationRun
from app.schemas.api import (
    CompareRequest,
    ComparisonView,
    ConfirmScene,
    CreateExperiment,
    CreateObservation,
    CreateProject,
    Envelope,
    ExperimentView,
    ObservationView,
    PreviewRequest,
    ProjectDetail,
    ProjectView,
    RunView,
    SessionView,
    SimulateRequest,
    SummaryView,
    VersionView,
)
from app.schemas.simulation import CalculationPreview
from app.services import business as service
from app.simulation.runner import SimulationError, preview

router = APIRouter(prefix="/api/v1")
Key = Annotated[str, Header(alias="Idempotency-Key", pattern=r"^[A-Za-z0-9._:-]{1,128}$")]


def envelope[T](request: Request, value: T) -> Envelope[T]:
    return Envelope(request_id=request.state.request_id, data=value)


def write[T: BaseModel](
    request: Request,
    db: Db,
    actor: Actor,
    key: str,
    body: BaseModel,
    operation: Callable[[], T],
    view: type[T],
) -> Envelope[T]:
    data = service.idempotent(db, actor.id, key, request.url.path, body, operation)
    return envelope(request, view.model_validate(data))


@router.get("/session", response_model=Envelope[SessionView])
def session(request: Request, response: Response, db: Db) -> Envelope[SessionView]:
    return envelope(request, open_session(request, response, db))


@router.get("/ready", response_model=Envelope[dict[str, str]])
def ready(request: Request, db: Db) -> Envelope[dict[str, str]]:
    revision = db.scalar(text("SELECT version_num FROM alembic_version"))
    if revision != "0003":
        raise DomainError(503, "DATABASE_NOT_READY", "数据库迁移尚未就绪")
    return envelope(request, {"database": "ok", "revision": revision})


@router.post("/projects", response_model=Envelope[ProjectView], status_code=201)
def create_project(
    request: Request, body: CreateProject, db: Db, actor: Actor, key: Key
) -> Envelope[ProjectView]:
    def operation() -> ProjectView:
        project = Project(session_id=actor.id, original_idea=body.original_idea, title=body.title)
        db.add(project)
        db.flush()
        return service.project_view(project)

    return write(request, db, actor, key, body, operation, ProjectView)


@router.get("/projects", response_model=Envelope[list[ProjectView]])
def list_projects(
    request: Request,
    db: Db,
    actor: Actor,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Envelope[list[ProjectView]]:
    projects = db.scalars(
        select(Project)
        .where(Project.session_id == actor.id)
        .order_by(Project.created_at, Project.id)
        .offset(offset)
        .limit(limit)
    )
    return envelope(request, [service.project_view(p) for p in projects])


@router.get("/projects/{project_id}", response_model=Envelope[ProjectDetail])
def get_project(project_id: str, request: Request, db: Db, actor: Actor) -> Envelope[ProjectDetail]:
    return envelope(
        request, service.project_detail(db, service.project_for(db, project_id, actor.id))
    )


@router.post(
    "/projects/{project_id}/scene-confirm", response_model=Envelope[VersionView], status_code=201
)
def confirm_scene(
    project_id: str, request: Request, body: ConfirmScene, db: Db, actor: Actor, key: Key
) -> Envelope[VersionView]:
    project = service.project_for(db, project_id, actor.id)
    return write(
        request,
        db,
        actor,
        key,
        body,
        lambda: service.create_version(db, project, body.scene),
        VersionView,
    )


@router.get("/scene-versions/{version_id}", response_model=Envelope[VersionView])
def get_version(version_id: str, request: Request, db: Db, actor: Actor) -> Envelope[VersionView]:
    return envelope(request, service.version_view(service.version_for(db, version_id, actor.id)))


@router.post("/projects/{project_id}/preview", response_model=Envelope[CalculationPreview])
def preview_scene(
    project_id: str,
    request: Request,
    body: PreviewRequest,
    db: Db,
    actor: Actor,
) -> Envelope[CalculationPreview]:
    project = service.project_for(db, project_id, actor.id)
    service.source_boundary(db, project, body.scene)
    try:
        result = preview(
            body.scene, scenario_label=body.scenario_label, calculated_at=datetime.now(UTC)
        )
    except SimulationError as error:
        raise DomainError(422, error.code, "还缺少计算条件或情景无效，请检查填写内容") from None
    return envelope(request, result)


@router.post(
    "/scene-versions/{version_id}/branches", response_model=Envelope[VersionView], status_code=201
)
def branch(
    version_id: str, request: Request, body: ConfirmScene, db: Db, actor: Actor, key: Key
) -> Envelope[VersionView]:
    parent = service.version_for(db, version_id, actor.id)
    project = service.project_for(db, parent.project_id, actor.id)
    return write(
        request,
        db,
        actor,
        key,
        body,
        lambda: service.create_version(db, project, body.scene, parent),
        VersionView,
    )


@router.post(
    "/scene-versions/{version_id}/simulate", response_model=Envelope[RunView], status_code=201
)
def simulate(
    version_id: str, request: Request, body: SimulateRequest, db: Db, actor: Actor, key: Key
) -> Envelope[RunView]:
    version = service.version_for(db, version_id, actor.id)
    return write(
        request,
        db,
        actor,
        key,
        body,
        lambda: service.create_run(db, version, body.scenario_label),
        RunView,
    )


@router.get("/scene-versions/{version_id}/simulations", response_model=Envelope[list[RunView]])
def list_runs(version_id: str, request: Request, db: Db, actor: Actor) -> Envelope[list[RunView]]:
    service.version_for(db, version_id, actor.id)
    rows = db.scalars(
        select(SimulationRun)
        .where(SimulationRun.scene_version_id == version_id)
        .order_by(SimulationRun.created_at, SimulationRun.id)
    )
    return envelope(request, [service.run_view(r) for r in rows])


@router.get("/simulation-runs/{run_id}", response_model=Envelope[RunView])
def get_run(run_id: str, request: Request, db: Db, actor: Actor) -> Envelope[RunView]:
    run = db.scalar(
        select(SimulationRun)
        .join(SceneVersion)
        .join(Project)
        .where(SimulationRun.id == run_id, Project.session_id == actor.id)
    )
    if run is None:
        raise DomainError(404, "SIMULATION_NOT_FOUND", "找不到模拟记录或没有访问权限")
    return envelope(request, service.run_view(run))


@router.post("/projects/{project_id}/compare", response_model=Envelope[ComparisonView])
def compare(
    project_id: str, request: Request, body: CompareRequest, db: Db, actor: Actor
) -> Envelope[ComparisonView]:
    return envelope(
        request, service.compare(db, service.project_for(db, project_id, actor.id), body, actor.id)
    )


@router.post(
    "/projects/{project_id}/experiments", response_model=Envelope[ExperimentView], status_code=201
)
def create_experiment(
    project_id: str, request: Request, body: CreateExperiment, db: Db, actor: Actor, key: Key
) -> Envelope[ExperimentView]:
    project = service.project_for(db, project_id, actor.id)
    return write(
        request,
        db,
        actor,
        key,
        body,
        lambda: service.create_experiment(db, project, body, actor.id),
        ExperimentView,
    )


@router.get("/experiments/{task_id}", response_model=Envelope[ExperimentView])
def get_experiment(
    task_id: str, request: Request, db: Db, actor: Actor
) -> Envelope[ExperimentView]:
    return envelope(request, service.experiment_view(service.task_for(db, task_id, actor.id)))


@router.post(
    "/experiments/{task_id}/observations", response_model=Envelope[ObservationView], status_code=201
)
def create_observation(
    task_id: str, request: Request, body: CreateObservation, db: Db, actor: Actor, key: Key
) -> Envelope[ObservationView]:
    task = service.task_for(db, task_id, actor.id)
    return write(
        request,
        db,
        actor,
        key,
        body,
        lambda: service.create_observation(db, task, body),
        ObservationView,
    )


@router.get("/projects/{project_id}/agent-runs/{run_id}", response_model=Envelope[AgentResult])
def get_agent_run(
    project_id: str, run_id: str, request: Request, db: Db, actor: Actor
) -> Envelope[AgentResult]:
    from app.agent import service as agents

    return envelope(request, agents.view(db, agents.run_for(db, project_id, run_id, actor.id)))


@router.get("/projects/{project_id}/summary", response_model=Envelope[SummaryView])
def get_summary(project_id: str, request: Request, db: Db, actor: Actor) -> Envelope[SummaryView]:
    return envelope(request, service.summary(db, service.project_for(db, project_id, actor.id)))
