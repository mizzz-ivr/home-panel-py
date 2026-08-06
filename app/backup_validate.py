from __future__ import annotations

from threading import Lock
from typing import Any

import app.backup_validate_legacy as _legacy
from app.backup_validate_legacy import *  # noqa: F401,F403
from app.task_priority import TASK_PRIORITIES

BACKUP_TABLES_BY_VERSION[6] = BACKUP_TABLES_BY_VERSION[5]

_legacy_validate_backup_payload = _legacy.validate_backup_payload
_legacy_validate_task = _legacy.validate_task
_validation_lock = Lock()


def validate_task_v6(record: Any, index: int, errors: ErrorCollector) -> int | None:
    path = f"data.tasks[{index}]"
    if type(record) is not dict:
        errors.add(f"{path}: オブジェクトである必要があります。")
        return None

    validate_exact_keys(
        record,
        {
            "id",
            "title",
            "is_done",
            "due_date",
            "priority",
            "created_at",
            "updated_at",
        },
        path,
        errors,
    )
    record_id = validate_positive_id(record.get("id"), f"{path}.id", errors)
    validate_string(
        record.get("title"),
        f"{path}.title",
        errors,
        min_length=1,
        max_length=255,
        disallow_blank=True,
    )
    if type(record.get("is_done")) is not bool:
        errors.add(f"{path}.is_done: 真偽値である必要があります。")
    validate_nullable_date_string(
        record.get("due_date"),
        f"{path}.due_date",
        errors,
    )
    priority = record.get("priority")
    if type(priority) is not str or priority not in TASK_PRIORITIES:
        errors.add(
            f"{path}.priority: low・medium・highのいずれかである必要があります。"
        )
    created_at = validate_utc_datetime_string(
        record.get("created_at"), f"{path}.created_at", errors
    )
    updated_at = validate_utc_datetime_string(
        record.get("updated_at"), f"{path}.updated_at", errors
    )
    if created_at is not None and updated_at is not None and updated_at < created_at:
        errors.add(f"{path}.updated_at: created_at以降である必要があります。")
    return record_id


def validate_backup_payload(payload: Any) -> list[str]:
    schema_version = payload.get("schema_version") if type(payload) is dict else None
    with _validation_lock:
        _legacy.validate_task = (
            validate_task_v6 if schema_version == 6 else _legacy_validate_task
        )
        try:
            return _legacy_validate_backup_payload(payload)
        finally:
            _legacy.validate_task = _legacy_validate_task


_legacy.BACKUP_TABLES_BY_VERSION[6] = _legacy.BACKUP_TABLES_BY_VERSION[5]
_legacy.validate_backup_payload = validate_backup_payload


def run_cli(args=None) -> int:
    return _legacy.run_cli(args)


if __name__ == "__main__":
    raise SystemExit(run_cli())
