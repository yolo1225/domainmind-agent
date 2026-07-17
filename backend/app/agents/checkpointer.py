from __future__ import annotations

import base64
from collections.abc import Callable
from contextlib import contextmanager
from threading import RLock
from typing import Any

from langgraph.checkpoint.base import (
    BaseCheckpointSaver,
    Checkpoint,
    CheckpointMetadata,
    CheckpointTuple,
)
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import GraphCheckpoint


def _dump(serde, value: Any) -> dict[str, str]:
    kind, data = serde.dumps_typed(value)
    return {"kind": kind, "data": base64.b64encode(data).decode("ascii")}


def _load(serde, value: dict[str, str]) -> Any:
    return serde.loads_typed((value["kind"], base64.b64decode(value["data"])))


class MySQLLangGraphCheckpointer(BaseCheckpointSaver):
    """Latest-checkpoint MySQL saver for the MVP's resumable task thread."""

    def __init__(self, session_factory: Callable[[], Session]) -> None:
        super().__init__()
        self.session_factory = session_factory
        self._lock = RLock()

    @contextmanager
    def _session(self):
        with self._lock:
            with self.session_factory() as db:
                yield db

    def get_tuple(self, config: dict) -> CheckpointTuple | None:
        configurable = config.get("configurable", {})
        thread_id = configurable.get("thread_id")
        if not thread_id:
            return None
        with self._session() as db:
            row = db.scalar(select(GraphCheckpoint).where(GraphCheckpoint.task_id == thread_id))
            payload = dict(row.state_json or {}) if row else {}
            checkpoint_id = row.checkpoint_id if row else None
        if not row or not payload.get("native_checkpoint"):
            return None
        checkpoint = _load(self.serde, payload["checkpoint"])
        metadata = _load(self.serde, payload["metadata"])
        stored_config = {
            "configurable": {
                "thread_id": thread_id,
                "checkpoint_ns": payload.get("checkpoint_ns", ""),
                "checkpoint_id": checkpoint_id,
            }
        }
        parent_id = payload.get("parent_checkpoint_id")
        parent_config = (
            {
                "configurable": {
                    "thread_id": thread_id,
                    "checkpoint_ns": payload.get("checkpoint_ns", ""),
                    "checkpoint_id": parent_id,
                }
            }
            if parent_id
            else None
        )
        pending_writes = [
            (item["task_id"], item["channel"], _load(self.serde, item["value"]))
            for item in payload.get("pending_writes", [])
        ]
        return CheckpointTuple(
            stored_config, checkpoint, metadata, parent_config, pending_writes
        )

    def list(self, config: dict | None, **kwargs):
        if config and (item := self.get_tuple(config)):
            yield item

    def put(
        self,
        config: dict,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: dict,
    ) -> dict:
        configurable = config["configurable"]
        thread_id = configurable["thread_id"]
        checkpoint_id = checkpoint["id"]
        payload = {
            "native_checkpoint": True,
            "checkpoint": _dump(self.serde, checkpoint),
            "metadata": _dump(self.serde, metadata),
            "new_versions": new_versions,
            "checkpoint_ns": configurable.get("checkpoint_ns", ""),
            "parent_checkpoint_id": configurable.get("checkpoint_id"),
            "pending_writes": [],
        }
        with self._session() as db:
            row = db.scalar(select(GraphCheckpoint).where(GraphCheckpoint.task_id == thread_id))
            if row is None:
                row = GraphCheckpoint(
                    task_id=thread_id,
                    checkpoint_id=checkpoint_id,
                    state_json=payload,
                    status="saved",
                )
                db.add(row)
            else:
                row.checkpoint_id = checkpoint_id
                row.state_json = payload
                row.status = "saved"
            db.commit()
        return {
            "configurable": {
                "thread_id": thread_id,
                "checkpoint_ns": configurable.get("checkpoint_ns", ""),
                "checkpoint_id": checkpoint_id,
            }
        }

    def put_writes(
        self,
        config: dict,
        writes: list[tuple[str, Any]],
        task_id: str,
        task_path: str = "",
    ) -> None:
        configurable = config["configurable"]
        with self._session() as db:
            row = db.scalar(
                select(GraphCheckpoint).where(
                    GraphCheckpoint.task_id == configurable["thread_id"]
                )
            )
            if row is None or row.checkpoint_id != configurable.get("checkpoint_id"):
                return
            payload = dict(row.state_json or {})
            pending = list(payload.get("pending_writes", []))
            for channel, value in writes:
                pending.append(
                    {
                        "task_id": task_id,
                        "task_path": task_path,
                        "channel": channel,
                        "value": _dump(self.serde, value),
                    }
                )
            payload["pending_writes"] = pending
            row.state_json = payload
            db.commit()

    def delete_thread(self, thread_id: str) -> None:
        with self._session() as db:
            row = db.scalar(select(GraphCheckpoint).where(GraphCheckpoint.task_id == thread_id))
            if row:
                db.delete(row)
                db.commit()

    def mark_status(self, thread_id: str, status: str) -> None:
        with self._session() as db:
            row = db.scalar(select(GraphCheckpoint).where(GraphCheckpoint.task_id == thread_id))
            if row:
                row.status = status
                db.commit()
