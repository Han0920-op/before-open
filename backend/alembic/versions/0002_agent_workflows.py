"""agent_workflows

Revision ID: 0002
Revises: 0001
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index("ix_agent_runs_thread_id", "agent_runs", ["thread_id"], unique=True)
    op.create_table(
        "agent_checkpoint_writes",
        sa.Column("thread_id", sa.String(length=100), nullable=False),
        sa.Column("namespace", sa.String(length=200), nullable=False),
        sa.Column("checkpoint_id", sa.String(length=100), nullable=False),
        sa.Column("task_id", sa.String(length=100), nullable=False),
        sa.Column("index", sa.Integer(), nullable=False),
        sa.Column("channel", sa.String(length=100), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(
            ["thread_id"],
            ["agent_runs.thread_id"],
        ),
        sa.PrimaryKeyConstraint("thread_id", "namespace", "checkpoint_id", "task_id", "index"),
    )
    op.create_table(
        "agent_checkpoints",
        sa.Column("thread_id", sa.String(length=100), nullable=False),
        sa.Column("namespace", sa.String(length=200), nullable=False),
        sa.Column("checkpoint_id", sa.String(length=100), nullable=False),
        sa.Column("parent_id", sa.String(length=100), nullable=True),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(
            ["thread_id"],
            ["agent_runs.thread_id"],
        ),
        sa.PrimaryKeyConstraint("thread_id", "namespace", "checkpoint_id"),
    )
    op.add_column(
        "agent_runs", sa.Column("total_calls", sa.Integer(), server_default="0", nullable=False)
    )
    op.add_column("agent_runs", sa.Column("request_id", sa.String(length=36), nullable=True))
    op.add_column("agent_runs", sa.Column("error_code", sa.String(length=60), nullable=True))
    op.add_column(
        "agent_runs", sa.Column("result_json", sa.JSON(), server_default="{}", nullable=False)
    )

    with op.batch_alter_table(
        "tool_invocations", schema=None, table_args=(sa.CheckConstraint("duration_ms >= 0"),)
    ) as batch_op:
        batch_op.add_column(sa.Column("request_id", sa.String(length=36), nullable=True))
        batch_op.add_column(sa.Column("idempotency_key", sa.String(length=128), nullable=True))
        batch_op.add_column(sa.Column("scene_version_id", sa.String(length=36), nullable=True))
        batch_op.create_foreign_key(
            "fk_tool_scene_version", "scene_versions", ["scene_version_id"], ["id"]
        )

    # ### end Alembic commands ###


def downgrade() -> None:
    op.drop_table("agent_checkpoint_writes")
    op.drop_table("agent_checkpoints")
    with op.batch_alter_table(
        "tool_invocations", table_args=(sa.CheckConstraint("duration_ms >= 0"),)
    ) as batch_op:
        batch_op.drop_constraint("fk_tool_scene_version", type_="foreignkey")
        batch_op.drop_column("scene_version_id")
        batch_op.drop_column("idempotency_key")
        batch_op.drop_column("request_id")
    op.drop_index("ix_agent_runs_thread_id", table_name="agent_runs")
    for name in ("result_json", "error_code", "request_id", "total_calls"):
        op.drop_column("agent_runs", name)
