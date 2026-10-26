from fastapi import APIRouter, Request
from sqlalchemy import select

from app.api.routes import Key, envelope, write
from app.core.security import Actor, Db
from app.models.entities import ProcessRun, SimulationRun
from app.schemas.api import Envelope
from app.schemas.process import AdvanceProcess, CreateProcess, ProcessView
from app.services import business
from app.services import process as service

router = APIRouter(prefix="/api/v1")


@router.post(
    "/scene-versions/{version_id}/process-runs",
    response_model=Envelope[ProcessView],
    status_code=201,
)
def create_process(
    version_id: str, body: CreateProcess, request: Request, db: Db, actor: Actor, key: Key
) -> Envelope[ProcessView]:
    version = business.version_for(db, version_id, actor.id)
    return write(
        request,
        db,
        actor,
        key,
        body,
        lambda: service.create(db, version, body.scenario_label),
        ProcessView,
    )


@router.get("/scene-versions/{version_id}/process-runs", response_model=Envelope[list[ProcessView]])
def latest_process(
    version_id: str, request: Request, db: Db, actor: Actor
) -> Envelope[list[ProcessView]]:
    business.version_for(db, version_id, actor.id)
    rows = db.scalars(
        select(ProcessRun)
        .join(SimulationRun)
        .where(SimulationRun.scene_version_id == version_id)
        .order_by(ProcessRun.created_at.desc(), ProcessRun.id.desc())
        .limit(1)
    )
    return envelope(request, [service.view(db, row) for row in rows])


@router.get("/process-runs/{process_id}", response_model=Envelope[ProcessView])
def get_process(process_id: str, request: Request, db: Db, actor: Actor) -> Envelope[ProcessView]:
    return envelope(request, service.view(db, service.owned(db, process_id, actor.id)))


@router.post("/process-runs/{process_id}/advance", response_model=Envelope[ProcessView])
def advance_process(
    process_id: str, body: AdvanceProcess, request: Request, db: Db, actor: Actor, key: Key
) -> Envelope[ProcessView]:
    row = service.owned(db, process_id, actor.id)
    return write(
        request,
        db,
        actor,
        key,
        body,
        lambda: service.advance(db, row, body.expected_revision, body.action == "finish"),
        ProcessView,
    )
