from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.errors import DomainError
from app.models.entities import ProcessRun, ProcessStep, Project, SceneVersion, SimulationRun
from app.schemas.process import ProcessProfile, ProcessStepView, ProcessView
from app.schemas.simulation import SimulationSnapshot
from app.services import business
from app.simulation.process import ledger, profile_for
from app.simulation.runner import replay_snapshot


def owned(db: Session, process_id: str, owner: str) -> ProcessRun:
    row = db.scalar(
        select(ProcessRun)
        .join(SimulationRun)
        .join(SceneVersion)
        .join(Project)
        .where(ProcessRun.id == process_id, Project.session_id == owner)
        .with_for_update(of=ProcessRun)
    )
    if row is None:
        raise DomainError(404, "PROCESS_NOT_FOUND", "找不到这次营业或没有访问权限")
    return row


def view(db: Session, row: ProcessRun) -> ProcessView:
    simulation = db.get(SimulationRun, row.simulation_run_id)
    assert simulation is not None
    snapshot = replay_snapshot(SimulationSnapshot.model_validate(simulation.output_json))
    profile = ProcessProfile.model_validate(row.profile_json)
    expected = ledger(snapshot, row.revision)
    stored = tuple(
        ProcessStepView.model_validate(s.ledger_json)
        for s in db.scalars(
            select(ProcessStep)
            .where(ProcessStep.process_run_id == row.id)
            .order_by(ProcessStep.sequence)
        )
    )
    if stored != expected or profile != profile_for(snapshot):
        raise DomainError(503, "PROCESS_INCONSISTENT", "营业记录校验未通过，请保留记录并反馈")
    return ProcessView(
        id=row.id,
        scene_version_id=simulation.scene_version_id,
        simulation_run_id=simulation.id,
        scenario_label=snapshot.scenario_label,
        status="completed" if row.revision == 3 else "open",
        profile=profile,
        state=stored[-1].after,
        steps=stored,
        calculation=snapshot if row.revision == 3 else None,
    )


def create(db: Session, version: SceneVersion, label: str) -> ProcessView:
    if version.business_type != "retail_perishable":
        raise DomainError(422, "PROCESS_TYPE_UNSUPPORTED", "此批次逐段营业先支持易损耗零售")
    simulation = business.create_run(db, version, label)
    profile = profile_for(simulation.snapshot)
    row = ProcessRun(
        simulation_run_id=simulation.id, profile_json=profile.model_dump(mode="json"), revision=0
    )
    db.add(row)
    db.flush()
    db.add(
        ProcessStep(
            process_run_id=row.id,
            sequence=0,
            ledger_json=ledger(simulation.snapshot, 0)[0].model_dump(mode="json"),
        )
    )
    db.flush()
    return view(db, row)


def advance(db: Session, row: ProcessRun, expected_revision: int, finish: bool) -> ProcessView:
    if row.revision != expected_revision:
        raise DomainError(409, "PROCESS_REVISION_CONFLICT", "营业已推进，请读取最新状态再继续")
    if row.revision == 3:
        return view(db, row)
    target = 3 if finish else row.revision + 1
    previous = row.revision
    # Also compare at the write boundary, not just in the request handler.
    changed = db.execute(
        update(ProcessRun)
        .where(ProcessRun.id == row.id, ProcessRun.revision == previous)
        .values(revision=target)
        .returning(ProcessRun.id)
        .execution_options(synchronize_session=False)
    )
    if changed.scalar_one_or_none() != row.id:
        raise DomainError(409, "PROCESS_REVISION_CONFLICT", "营业已推进，请读取最新状态再继续")
    db.expire(row)
    simulation = db.get(SimulationRun, row.simulation_run_id)
    assert simulation is not None
    snapshot = replay_snapshot(SimulationSnapshot.model_validate(simulation.output_json))
    for step in ledger(snapshot, target)[previous + 1 :]:
        db.add(
            ProcessStep(
                process_run_id=row.id,
                sequence=step.sequence,
                ledger_json=step.model_dump(mode="json"),
            )
        )
    db.flush()
    return view(db, row)
