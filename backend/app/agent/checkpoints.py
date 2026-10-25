"""LangGraph checkpoint storage, separate from business facts but in the same transaction."""

import base64
from collections.abc import Iterator, Sequence
from threading import RLock
from typing import Any

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import (
    WRITES_IDX_MAP,
    BaseCheckpointSaver,
    ChannelVersions,
    Checkpoint,
    CheckpointMetadata,
    CheckpointTuple,
)
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import AgentCheckpoint, AgentCheckpointWrite


class TransactionSaver(BaseCheckpointSaver[int]):
    def __init__(self, db: Session, lock: RLock) -> None:
        super().__init__(serde=JsonPlusSerializer(pickle_fallback=False))
        self.db = db
        self.lock = lock

    def encode(self, value: Any) -> dict[str, str]:
        kind, data = self.serde.dumps_typed(value)
        return {"type": kind, "data": base64.b64encode(data).decode()}

    def decode(self, value: dict[str, Any]) -> Any:
        return self.serde.loads_typed((value["type"], base64.b64decode(value["data"])))

    def get_tuple(self, config: RunnableConfig) -> CheckpointTuple | None:
        with self.lock:
            c = config["configurable"]
            query = select(AgentCheckpoint).where(
                AgentCheckpoint.thread_id == c["thread_id"],
                AgentCheckpoint.namespace == c.get("checkpoint_ns", ""),
            )
            if c.get("checkpoint_id"):
                query = query.where(AgentCheckpoint.checkpoint_id == c["checkpoint_id"])
            row = self.db.scalar(query.order_by(AgentCheckpoint.checkpoint_id.desc()).limit(1))
            if row is None:
                return None
            selected: RunnableConfig = {
                "configurable": {
                    "thread_id": row.thread_id,
                    "checkpoint_ns": row.namespace,
                    "checkpoint_id": row.checkpoint_id,
                }
            }
            writes = self.db.scalars(
                select(AgentCheckpointWrite)
                .where(
                    AgentCheckpointWrite.thread_id == row.thread_id,
                    AgentCheckpointWrite.namespace == row.namespace,
                    AgentCheckpointWrite.checkpoint_id == row.checkpoint_id,
                )
                .order_by(AgentCheckpointWrite.task_id, AgentCheckpointWrite.index)
            )
            parent: RunnableConfig | None = (
                {
                    "configurable": {
                        "thread_id": row.thread_id,
                        "checkpoint_ns": row.namespace,
                        "checkpoint_id": row.parent_id,
                    }
                }
                if row.parent_id
                else None
            )
            return CheckpointTuple(
                config=selected,
                checkpoint=self.decode(row.payload_json["checkpoint"]),
                metadata=self.decode(row.payload_json["metadata"]),
                parent_config=parent,
                pending_writes=[
                    (w.task_id, w.channel, self.decode(w.payload_json)) for w in writes
                ],
            )

    def put(
        self,
        config: RunnableConfig,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: ChannelVersions,
    ) -> RunnableConfig:
        with self.lock:
            c = config["configurable"]
            self.db.merge(
                AgentCheckpoint(
                    thread_id=c["thread_id"],
                    namespace=c.get("checkpoint_ns", ""),
                    checkpoint_id=checkpoint["id"],
                    parent_id=c.get("checkpoint_id"),
                    payload_json={
                        "checkpoint": self.encode(checkpoint),
                        "metadata": self.encode(metadata),
                    },
                )
            )
            self.db.flush()
            return {
                "configurable": {
                    "thread_id": c["thread_id"],
                    "checkpoint_ns": c.get("checkpoint_ns", ""),
                    "checkpoint_id": checkpoint["id"],
                }
            }

    def put_writes(
        self,
        config: RunnableConfig,
        writes: Sequence[tuple[str, Any]],
        task_id: str,
        task_path: str = "",
    ) -> None:
        with self.lock:
            c = config["configurable"]
            for index, (channel, value) in enumerate(writes):
                idx = WRITES_IDX_MAP.get(channel, index)
                key = (c["thread_id"], c.get("checkpoint_ns", ""), c["checkpoint_id"], task_id, idx)
                previous = self.db.get(AgentCheckpointWrite, key)
                if previous is not None and idx >= 0:
                    continue
                self.db.merge(
                    AgentCheckpointWrite(
                        thread_id=key[0],
                        namespace=key[1],
                        checkpoint_id=key[2],
                        task_id=key[3],
                        index=idx,
                        channel=channel,
                        payload_json=self.encode(value),
                    )
                )
            self.db.flush()

    def list(
        self,
        config: RunnableConfig | None,
        *,
        filter: dict[str, Any] | None = None,
        before: RunnableConfig | None = None,
        limit: int | None = None,
    ) -> Iterator[CheckpointTuple]:
        with self.lock:
            query = select(AgentCheckpoint).order_by(AgentCheckpoint.checkpoint_id.desc())
            if config:
                query = query.where(
                    AgentCheckpoint.thread_id == config["configurable"]["thread_id"],
                    AgentCheckpoint.namespace == config["configurable"].get("checkpoint_ns", ""),
                )
            if before:
                query = query.where(
                    AgentCheckpoint.checkpoint_id < before["configurable"]["checkpoint_id"]
                )
            rows = list(self.db.scalars(query))
            values = []
            for row in rows:
                item = self.get_tuple(
                    {
                        "configurable": {
                            "thread_id": row.thread_id,
                            "checkpoint_ns": row.namespace,
                            "checkpoint_id": row.checkpoint_id,
                        }
                    }
                )
                if item and (
                    not filter or all(item.metadata.get(k) == v for k, v in filter.items())
                ):
                    values.append(item)
            yield from values[:limit] if limit is not None else values
