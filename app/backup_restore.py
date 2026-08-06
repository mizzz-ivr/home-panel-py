from __future__ import annotations

import copy
from datetime import date
from typing import Any

import app.backup_restore_legacy as _legacy
from app.backup_restore_legacy import *  # noqa: F401,F403
from app.models.task import Task
from app.task_priority import DEFAULT_TASK_PRIORITY

_legacy_normalize_backup_payload = _legacy.normalize_backup_payload
_legacy_insert_normalized_payload = _legacy.insert_normalized_payload


def normalize_backup_payload(payload: dict[str, Any]) -> dict[str, Any]:
    source = payload
    if payload["schema_version"] < 6:
        source = copy.deepcopy(payload)
        for task in source["data"]["tasks"]:
            task["due_date"] = None
            task["priority"] = DEFAULT_TASK_PRIORITY
    return _legacy_normalize_backup_payload(source)


def insert_normalized_payload(db, payload: dict[str, Any]) -> None:
    _legacy_insert_normalized_payload(db, payload)
    for record in payload["data"]["tasks"]:
        task = db.get(Task, record["id"])
        if task is None:
            raise RuntimeError(f"復元対象のToDoが見つかりません: {record['id']}")
        task.due_date = (
            date.fromisoformat(record["due_date"])
            if record["due_date"] is not None
            else None
        )
        task.priority = record["priority"]


_legacy.normalize_backup_payload = normalize_backup_payload
_legacy.insert_normalized_payload = insert_normalized_payload


def run_cli(args=None) -> int:
    return _legacy.run_cli(args)


if __name__ == "__main__":
    raise SystemExit(run_cli())
