import hashlib
import json
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import DomainError
from app.models.entities import (
    AgentRun,
    ExperimentTask,
    IdempotencyRecord,
    Observation,
    Project,
    SceneVersion,
    SimulationRun,
    ToolInvocation,
)
from app.schemas.api import (
    AgentRunView,
    CompareRequest,
    ComparisonView,
    CreateExperiment,
    CreateObservation,
    ExperimentView,
    FieldChange,
    ObservationView,
    ProjectDetail,
    ProjectView,
    RunView,
    SummaryView,
    ToolView,
    VersionView,
)
from app.schemas.scene import SceneSpec, ServiceScene
from app.schemas.simulation import SimulationSnapshot
from app.simulation.runner import SimulationError, parse_scene, replay_snapshot, simulate


def utc(value: datetime) -> datetime:
    # SQLite does not preserve timezone offsets; persisted values are normalized to UTC.
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def project_for(db: Session, project_id: str, session_id: str) -> Project:
    project = db.scalar(
        select(Project).where(Project.id == project_id, Project.session_id == session_id)
    )
    if project is None:
        raise DomainError(404, "PROJECT_NOT_FOUND", "找不到这个想法或没有访问权限")
    return project


def version_for(db: Session, version_id: str, session_id: str) -> SceneVersion:
    version = db.scalar(
        select(SceneVersion)
        .join(Project)
        .where(SceneVersion.id == version_id, Project.session_id == session_id)
    )
    if version is None:
        raise DomainError(404, "VERSION_NOT_FOUND", "找不到这个方案或没有访问权限")
    return version


def project_view(project: Project) -> ProjectView:
    return ProjectView(
        id=project.id,
        original_idea=project.original_idea,
        title=project.title,
        created_at=utc(project.created_at),
    )


def version_view(version: SceneVersion) -> VersionView:
    return VersionView(
        id=version.id,
        project_id=version.project_id,
        parent_version_id=version.parent_version_id,
        scene=parse_scene(version.scene_spec_json),
        created_at=utc(version.created_at),
    )


def versions_for(db: Session, project_id: str) -> tuple[VersionView, ...]:
    return tuple(
        version_view(v)
        for v in db.scalars(
            select(SceneVersion)
            .where(SceneVersion.project_id == project_id)
            .order_by(SceneVersion.created_at, SceneVersion.id)
        )
    )


def project_detail(db: Session, project: Project) -> ProjectDetail:
    versions = versions_for(db, project.id)
    return ProjectDetail(
        project=project_view(project),
        versions=versions,
        latest_version_id=versions[-1].id if versions else None,
    )


def source_boundary(db: Session, project: Project, scene: SceneSpec) -> None:
    if scene.original_idea != project.original_idea:
        raise DomainError(422, "ORIGINAL_IDEA_IMMUTABLE", "方案必须保留项目的原始想法")
    raw = scene.model_dump(mode="json")

    def visit(value: Any, field_name: str) -> None:
        if isinstance(value, dict):
            source = value.get("source")
            if source in {"verified_external", "derived"}:
                raise DomainError(422, "SOURCE_FORBIDDEN", "手动输入不能声明外部核验或公式推导")
            if source == "user_observation":
                observation = db.scalar(
                    select(Observation)
                    .join(ExperimentTask)
                    .where(
                        Observation.id == value.get("observation_id"),
                        ExperimentTask.project_id == project.id,
                    )
                )
                observed = observation.observed_values_json.get(field_name) if observation else None
                unit = (
                    "cents"
                    if field_name.endswith("_cents")
                    else ("minutes" if "minutes" in field_name else "qty")
                )
                if (
                    not observed
                    or observed.get("value") != value.get("value")
                    or observed.get("unit") != unit
                ):
                    raise DomainError(
                        422, "OBSERVATION_MISMATCH", "观察必须属于本项目且数值与单位一致"
                    )
            for name, item in value.items():
                visit(item, name)
        elif isinstance(value, (list, tuple)):
            for item in value:
                visit(item, field_name)

    visit(raw, "scene")


def create_version(
    db: Session, project: Project, scene: SceneSpec, parent: SceneVersion | None = None
) -> VersionView:
    source_boundary(db, project, scene)
    if parent and parent.project_id != project.id:
        raise DomainError(422, "PROJECT_MISMATCH", "父方案不属于这个想法")
    version = SceneVersion(
        project_id=project.id,
        parent_version_id=parent.id if parent else None,
        schema_version=scene.schema_version,
        business_type=scene.business_type,
        scene_spec_json=scene.model_dump(mode="json"),
    )
    db.add(version)
    db.flush()
    return version_view(version)


def calculate(version: SceneVersion, label: str) -> SimulationSnapshot:
    try:
        return simulate(
            version.scene_spec_json,
            scene_version_id=version.id,
            scenario_label=label,
            calculated_at=datetime.now(UTC),
        )
    except SimulationError as error:
        raise DomainError(422, error.code, "场景条件不完整或情景标签无效，请检查后再试") from None


def create_run(db: Session, version: SceneVersion, label: str) -> RunView:
    snapshot = calculate(version, label)
    run = SimulationRun(
        scene_version_id=version.id,
        model_version=snapshot.model_version,
        input_snapshot_json=snapshot.input_snapshot.model_dump(mode="json"),
        output_json=snapshot.model_dump(mode="json"),
    )
    db.add(run)
    db.flush()
    return RunView(id=run.id, snapshot=snapshot)


def run_view(run: SimulationRun) -> RunView:
    snapshot = replay_snapshot(SimulationSnapshot.model_validate(run.output_json))
    if (
        run.scene_version_id != snapshot.scene_version_id
        or run.model_version != snapshot.model_version
        or run.input_snapshot_json != snapshot.input_snapshot.model_dump(mode="json")
    ):
        raise DomainError(500, "STORED_RUN_INVALID", "保存的模拟记录校验失败")
    return RunView(id=run.id, snapshot=snapshot)


def idempotent(
    db: Session,
    session_id: str,
    key: str,
    route: str,
    payload: BaseModel,
    operation: Callable[[], BaseModel],
) -> dict[str, Any]:
    fingerprint = hashlib.sha256(
        json.dumps(
            {"route": route, "payload": payload.model_dump(mode="json")},
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode()
    ).hexdigest()
    record = IdempotencyRecord(
        session_id=session_id, key=key, fingerprint=fingerprint, response_json={}
    )
    try:
        with db.begin_nested():
            db.add(record)
            db.flush()
    except IntegrityError:
        existing = db.get(IdempotencyRecord, (session_id, key), populate_existing=True)
        if existing is None:
            raise DomainError(409, "RETRY_REQUEST", "请求正在处理，请稍后使用同一键重试") from None
        if existing.fingerprint != fingerprint:
            raise DomainError(409, "IDEMPOTENCY_CONFLICT", "这个请求键已用于其他内容") from None
        return existing.response_json
    result = operation().model_dump(mode="json")
    record.response_json = result
    db.flush()
    return result


def flatten(value: Any, path: str = "") -> dict[str, Any]:
    if isinstance(value, dict) and value:
        return {
            p: v
            for name, item in value.items()
            for p, v in flatten(item, f"{path}.{name}" if path else name).items()
        }
    if isinstance(value, list) and value:
        return {
            p: v for i, item in enumerate(value) for p, v in flatten(item, f"{path}.{i}").items()
        }
    return {path: value}


def compare(
    db: Session, project: Project, request: CompareRequest, session_id: str
) -> ComparisonView:
    left = version_for(db, request.left_version_id, session_id)
    right = version_for(db, request.right_version_id, session_id)
    if left.project_id != project.id or right.project_id != project.id:
        raise DomainError(422, "PROJECT_MISMATCH", "只能比较同一想法的方案")
    if left.business_type != right.business_type:
        raise DomainError(422, "INCOMPATIBLE_MODELS", "不同经营模型不能直接比较经营结果")
    a, b = (
        calculate(left, request.left_scenario_label),
        calculate(right, request.right_scenario_label),
    )
    first, second = (
        flatten(a.input_snapshot.model_dump(mode="json")),
        flatten(b.input_snapshot.model_dump(mode="json")),
    )
    paths = sorted(first.keys() | second.keys())
    changed = tuple(
        FieldChange(path=p, left=first.get(p), right=second.get(p))
        for p in paths
        if p not in first or p not in second or first[p] != second[p]
    )
    unchanged = tuple(p for p in paths if p in first and p in second and first[p] == second[p])
    result_a, result_b = a.result.model_dump(), b.result.model_dump()
    deltas = {
        name: result_b[name] - value if value is not None and result_b[name] is not None else None
        for name, value in result_a.items()
        if name != "business_type"
    }
    same_demand = None
    if not isinstance(a.input_snapshot, ServiceScene) and not isinstance(
        b.input_snapshot, ServiceScene
    ):
        da = next(
            s.demand_qty
            for s in a.input_snapshot.demand_scenarios
            if s.scenario_label == a.scenario_label
        )
        db_demand = next(
            s.demand_qty
            for s in b.input_snapshot.demand_scenarios
            if s.scenario_label == b.scenario_label
        )
        same_demand = da == db_demand
    return ComparisonView(
        left=a,
        right=b,
        changed_fields=changed,
        unchanged_fields=unchanged,
        same_calculation_inputs=(
            a.input_snapshot.fields == b.input_snapshot.fields and same_demand is not False
        ),
        same_demand_assumption=same_demand,
        same_period=a.input_snapshot.period_note == b.input_snapshot.period_note,
        result_deltas=deltas,
        warning="仅比较上述输入假设；不同需求或期间不代表同条件优劣，不是现实预测。",
    )


def experiment_view(task: ExperimentTask) -> ExperimentView:
    return ExperimentView(
        id=task.id,
        project_id=task.project_id,
        scene_version_id=task.scene_version_id,
        question=task.question,
        method=task.method_json["description"],
        warnings=tuple(task.warnings_json),
        status=task.status,
    )


def create_experiment(
    db: Session, project: Project, body: CreateExperiment, session_id: str
) -> ExperimentView:
    version = version_for(db, body.scene_version_id, session_id)
    if version.project_id != project.id:
        raise DomainError(422, "PROJECT_MISMATCH", "任务方案不属于这个想法")
    task = ExperimentTask(
        project_id=project.id,
        scene_version_id=version.id,
        question=body.question,
        method_json={"description": body.method},
        warnings_json=list(body.warnings)
        + ["须征得参与者同意；不记录姓名或联系方式；样本不代表市场。"],
    )
    db.add(task)
    db.flush()
    return experiment_view(task)


def task_for(db: Session, task_id: str, session_id: str) -> ExperimentTask:
    task = db.scalar(
        select(ExperimentTask)
        .join(Project)
        .where(ExperimentTask.id == task_id, Project.session_id == session_id)
    )
    if task is None:
        raise DomainError(404, "EXPERIMENT_NOT_FOUND", "找不到任务或没有访问权限")
    return task


def observation_view(observation: Observation) -> ObservationView:
    return ObservationView(
        id=observation.id,
        task_id=observation.task_id,
        recorded_at=utc(observation.recorded_at),
        sample_size=observation.sample_size,
        notes=observation.notes,
        limitations=observation.limitations,
        observed_values=observation.observed_values_json,
    )


def create_observation(
    db: Session, task: ExperimentTask, body: CreateObservation
) -> ObservationView:
    observation = Observation(
        task_id=task.id,
        recorded_at=body.recorded_at.astimezone(UTC),
        sample_size=body.sample_size,
        notes=body.notes,
        limitations=body.limitations,
        observed_values_json={
            k: v.model_dump(mode="json") for k, v in body.observed_values.items()
        },
    )
    db.add(observation)
    db.flush()
    return observation_view(observation)


def agent_view(db: Session, project: Project, run_id: str) -> AgentRunView:
    run = db.scalar(
        select(AgentRun).where(AgentRun.id == run_id, AgentRun.project_id == project.id)
    )
    if run is None:
        raise DomainError(404, "AGENT_RUN_NOT_FOUND", "还没有这条 Agent 执行记录")
    tools = db.scalars(
        select(ToolInvocation)
        .where(ToolInvocation.agent_run_id == run.id)
        .order_by(ToolInvocation.created_at, ToolInvocation.id)
    )
    return AgentRunView(
        id=run.id,
        thread_id=run.thread_id,
        stage=run.stage,
        status=run.status,
        total_steps=run.total_steps,
        tools=tuple(
            ToolView(
                id=t.id,
                tool_name=t.tool_name,
                input_summary=t.input_summary_json,
                output_summary=t.output_summary_json,
                status=t.status,
                duration_ms=t.duration_ms,
            )
            for t in tools
        ),
    )


def summary(db: Session, project: Project) -> SummaryView:
    runs = db.scalars(
        select(SimulationRun)
        .join(SceneVersion)
        .where(SceneVersion.project_id == project.id)
        .order_by(SimulationRun.created_at, SimulationRun.id)
    )
    tasks = db.scalars(
        select(ExperimentTask)
        .where(ExperimentTask.project_id == project.id)
        .order_by(ExperimentTask.created_at, ExperimentTask.id)
    )
    observations = db.scalars(
        select(Observation)
        .join(ExperimentTask)
        .where(ExperimentTask.project_id == project.id)
        .order_by(Observation.created_at, Observation.id)
    )
    return SummaryView(
        project=project_view(project),
        versions=versions_for(db, project.id),
        simulations=tuple(run_view(r) for r in runs),
        experiments=tuple(experiment_view(t) for t in tasks),
        observations=tuple(observation_view(o) for o in observations),
    )
