from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    String,
    Text,
    UniqueConstraint,
    event,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def new_id() -> str:
    return str(uuid4())


def now() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class Record(Base):
    __abstract__ = True
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class AnonymousSession(Record):
    __tablename__ = "anonymous_sessions"
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    csrf_hash: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Project(Record):
    __tablename__ = "projects"
    session_id: Mapped[str] = mapped_column(ForeignKey("anonymous_sessions.id"), index=True)
    original_idea: Mapped[str] = mapped_column(Text)
    title: Mapped[str] = mapped_column(String(200))


class SceneVersion(Record):
    __tablename__ = "scene_versions"
    __table_args__ = (
        UniqueConstraint("id", "project_id", name="uq_version_project"),
        ForeignKeyConstraint(
            ["parent_version_id", "project_id"],
            ["scene_versions.id", "scene_versions.project_id"],
            name="fk_parent_same_project",
        ),
    )
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    parent_version_id: Mapped[str | None] = mapped_column(String(36))
    schema_version: Mapped[str] = mapped_column(String(20))
    business_type: Mapped[str] = mapped_column(String(40))
    scene_spec_json: Mapped[dict[str, Any]] = mapped_column(JSON)


class SimulationRun(Record):
    __tablename__ = "simulation_runs"
    scene_version_id: Mapped[str] = mapped_column(ForeignKey("scene_versions.id"), index=True)
    model_version: Mapped[str] = mapped_column(String(60))
    input_snapshot_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    output_json: Mapped[dict[str, Any]] = mapped_column(JSON)


class IdempotencyRecord(Base):
    __tablename__ = "idempotency_records"
    # One key per session, across routes. Insert and business writes share a transaction.
    session_id: Mapped[str] = mapped_column(ForeignKey("anonymous_sessions.id"), primary_key=True)
    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    fingerprint: Mapped[str] = mapped_column(String(64))
    response_json: Mapped[dict[str, Any]] = mapped_column(JSON)


class AgentRun(Record):
    __tablename__ = "agent_runs"
    __table_args__ = (CheckConstraint("total_steps >= 0"),)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    thread_id: Mapped[str] = mapped_column(String(100))
    stage: Mapped[str] = mapped_column(String(60))
    status: Mapped[str] = mapped_column(String(30))
    total_steps: Mapped[int] = mapped_column(Integer)


class ToolInvocation(Record):
    __tablename__ = "tool_invocations"
    __table_args__ = (CheckConstraint("duration_ms >= 0"),)
    agent_run_id: Mapped[str] = mapped_column(ForeignKey("agent_runs.id"), index=True)
    tool_name: Mapped[str] = mapped_column(String(80))
    input_summary_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    output_summary_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(30))
    duration_ms: Mapped[int] = mapped_column(Integer)


class RiskCard(Record):
    __tablename__ = "risk_cards"
    scene_version_id: Mapped[str] = mapped_column(ForeignKey("scene_versions.id"), index=True)
    type: Mapped[str] = mapped_column(String(50))
    evidence_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    text: Mapped[str] = mapped_column(Text)
    severity: Mapped[str] = mapped_column(String(30))
    user_action: Mapped[str] = mapped_column(String(50))


class ExperimentTask(Record):
    __tablename__ = "experiment_tasks"
    __table_args__ = (
        ForeignKeyConstraint(
            ["scene_version_id", "project_id"],
            ["scene_versions.id", "scene_versions.project_id"],
            name="fk_task_same_project",
        ),
    )
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    scene_version_id: Mapped[str] = mapped_column(String(36))
    question: Mapped[str] = mapped_column(Text)
    method_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    warnings_json: Mapped[list[str]] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(30), default="open")


class Observation(Record):
    __tablename__ = "observations"
    __table_args__ = (
        CheckConstraint("sample_size >= 1 AND sample_size <= 1000000"),
        CheckConstraint("provenance = 'user_observation'"),
    )
    task_id: Mapped[str] = mapped_column(ForeignKey("experiment_tasks.id"), index=True)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    sample_size: Mapped[int] = mapped_column(Integer)
    notes: Mapped[str] = mapped_column(Text)
    limitations: Mapped[str] = mapped_column(Text)
    observed_values_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    provenance: Mapped[str] = mapped_column(String(30), default="user_observation")


def reject_mutation(mapper: object, connection: object, target: object) -> None:
    raise ValueError("immutable business record")


for _model in (SceneVersion, SimulationRun, Observation):
    event.listen(_model, "before_update", reject_mutation)
    event.listen(_model, "before_delete", reject_mutation)
