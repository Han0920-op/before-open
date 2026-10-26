"""Persist bounded retail processes without changing existing simulations.

Revision ID: 0003
Revises: 0002
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "process_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "simulation_run_id", sa.String(36), sa.ForeignKey("simulation_runs.id"), nullable=False
        ),
        sa.Column("profile_json", sa.JSON(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.CheckConstraint("revision >= 0 AND revision <= 3"),
    )
    op.create_index("ix_process_runs_simulation_run_id", "process_runs", ["simulation_run_id"])
    op.create_table(
        "process_steps",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "process_run_id", sa.String(36), sa.ForeignKey("process_runs.id"), nullable=False
        ),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("ledger_json", sa.JSON(), nullable=False),
        sa.UniqueConstraint("process_run_id", "sequence", name="uq_process_step"),
        sa.CheckConstraint("sequence >= 0 AND sequence <= 3"),
    )
    op.create_index("ix_process_steps_process_run_id", "process_steps", ["process_run_id"])
    dialect = op.get_bind().dialect.name
    if dialect == "postgresql":
        op.execute(
            "CREATE TRIGGER frozen_record BEFORE UPDATE OR DELETE ON process_steps "
            "FOR EACH ROW EXECUTE FUNCTION before_open_reject_mutation()"
        )
    elif dialect == "sqlite":
        for operation in ("UPDATE", "DELETE"):
            op.execute(
                f"CREATE TRIGGER frozen_process_steps_{operation} BEFORE {operation} "
                "ON process_steps BEGIN SELECT RAISE(ABORT, 'immutable business record'); END"
            )


def downgrade() -> None:
    op.drop_table("process_steps")
    op.drop_table("process_runs")
