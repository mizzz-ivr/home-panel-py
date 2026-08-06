from __future__ import annotations

import copy
from datetime import date, datetime
from pathlib import Path
from typing import Any

import app.backup_restore_legacy as _legacy
from app.backup_restore_legacy import *  # noqa: F401,F403
from app.models.task import Task
from app.task_priority import DEFAULT_TASK_PRIORITY

_legacy_normalize_backup_payload = _legacy.normalize_backup_payload
_legacy_insert_normalized_payload = _legacy.insert_normalized_payload
_legacy_restore_backup_file = _legacy.restore_backup_file


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


def restore_backup_file(
    backup_path: Path,
    database_path: Path,
    *,
    expected_sha256: str | None = None,
    restored_at: datetime | None = None,
) -> RestoreResult:
    previous_builder = _legacy.build_temporary_database
    _legacy.build_temporary_database = build_temporary_database
    try:
        return _legacy_restore_backup_file(
            backup_path,
            database_path,
            expected_sha256=expected_sha256,
            restored_at=restored_at,
        )
    finally:
        _legacy.build_temporary_database = previous_builder


_legacy.normalize_backup_payload = normalize_backup_payload
_legacy.insert_normalized_payload = insert_normalized_payload
_legacy.restore_backup_file = restore_backup_file


def run_cli(args=None) -> int:
    return _legacy.run_cli(args)


if __name__ == "__main__":
    raise SystemExit(run_cli())
