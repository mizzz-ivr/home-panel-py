from __future__ import annotations

import copy
from datetime import date
from threading import Lock
from typing import Any

import app.backup_validate_legacy as _legacy
from app.backup_validate_legacy import *  # noqa: F401,F403
from app.task_priority import TASK_PRIORITIES
from app.time_goal_constants import (
    MAX_DAILY_TIME_GOAL_MINUTES,
    MIN_DAILY_TIME_GOAL_MINUTES,
)

BACKUP_TABLES_BY_VERSION[6] = BACKUP_TABLES_BY_VERSION[5]
BACKUP_TABLES_BY_VERSION[7] = (
    *BACKUP_TABLES_BY_VERSION[6],
    "daily_time_goal_periods",
)

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


def validate_daily_time_goal_period_v7(
    record: Any,
    index: int,
    errors: ErrorCollector,
) -> int | None:
    path = f"data.daily_time_goal_periods[{index}]"
    if type(record) is not dict:
        errors.add(f"{path}: オブジェクトである必要があります。")
        return None

    validate_exact_keys(
        record,
        {"id", "goal_minutes", "started_on", "ended_on", "created_at"},
        path,
        errors,
    )
    record_id = validate_positive_id(record.get("id"), f"{path}.id", errors)
    goal_minutes = record.get("goal_minutes")
    if (
        type(goal_minutes) is not int
        or not MIN_DAILY_TIME_GOAL_MINUTES
        <= goal_minutes
        <= MAX_DAILY_TIME_GOAL_MINUTES
    ):
        errors.add(
            f"{path}.goal_minutes: "
            f"{MIN_DAILY_TIME_GOAL_MINUTES}〜{MAX_DAILY_TIME_GOAL_MINUTES}の整数である必要があります。"
        )
    started_on = validate_date_string(
        record.get("started_on"), f"{path}.started_on", errors
    )
    ended_on = validate_nullable_date_string(
        record.get("ended_on"), f"{path}.ended_on", errors
    )
    validate_utc_datetime_string(
        record.get("created_at"), f"{path}.created_at", errors
    )
    if started_on is not None and ended_on is not None and ended_on < started_on:
        errors.add(f"{path}.ended_on: started_on以降である必要があります。")
    return record_id


def _validate_daily_time_goal_periods_v7(payload: dict[str, Any]) -> list[str]:
    errors = ErrorCollector()
    data = payload.get("data")
    record_counts = payload.get("record_counts")
    if type(data) is not dict or type(record_counts) is not dict:
        return errors.result()

    records = data.get("daily_time_goal_periods")
    actual_count, _ = validate_records(
        records,
        "daily_time_goal_periods",
        validate_daily_time_goal_period_v7,
        errors,
    )
    expected_count = record_counts.get("daily_time_goal_periods")
    if type(expected_count) is not int or expected_count < 0:
        errors.add(
            "record_counts.daily_time_goal_periods: 0以上の整数である必要があります。"
        )
    elif actual_count is not None and expected_count != actual_count:
        errors.add(
            "record_counts.daily_time_goal_periods: 配列件数と一致しません。"
            f"記録={expected_count}、実際={actual_count}"
        )

    if type(records) is not list:
        return errors.result()

    parsed_periods: list[tuple[date, date | None, int]] = []
    seen_starts: set[date] = set()
    for index, record in enumerate(records):
        if type(record) is not dict:
            continue
        try:
            started_on = date.fromisoformat(record["started_on"])
            ended_on = (
                date.fromisoformat(record["ended_on"])
                if record.get("ended_on") is not None
                else None
            )
        except (KeyError, TypeError, ValueError):
            continue
        if started_on in seen_starts:
            errors.add(
                f"data.daily_time_goal_periods[{index}].started_on: 開始日が重複しています。"
            )
        seen_starts.add(started_on)
        parsed_periods.append((started_on, ended_on, index))

    previous_end: date | None = None
    for position, (started_on, ended_on, index) in enumerate(
        sorted(parsed_periods, key=lambda item: (item[0], item[2]))
    ):
        if position > 0 and (previous_end is None or started_on <= previous_end):
            errors.add(
                f"data.daily_time_goal_periods[{index}]: 時間目標の適用期間が重複しています。"
            )
        previous_end = ended_on

    return errors.result()


def validate_backup_payload(payload: Any) -> list[str]:
    schema_version = payload.get("schema_version") if type(payload) is dict else None
    with _validation_lock:
        if schema_version == 7:
            compatible = copy.deepcopy(payload)
            compatible["schema_version"] = 6
            if type(compatible.get("data")) is dict:
                compatible["data"].pop("daily_time_goal_periods", None)
            if type(compatible.get("record_counts")) is dict:
                compatible["record_counts"].pop("daily_time_goal_periods", None)
            _legacy.validate_task = validate_task_v6
            try:
                errors = _legacy_validate_backup_payload(compatible)
            finally:
                _legacy.validate_task = _legacy_validate_task
            errors.extend(_validate_daily_time_goal_periods_v7(payload))
            return errors

        _legacy.validate_task = (
            validate_task_v6 if schema_version == 6 else _legacy_validate_task
        )
        try:
            return _legacy_validate_backup_payload(payload)
        finally:
            _legacy.validate_task = _legacy_validate_task


_legacy.BACKUP_TABLES_BY_VERSION[6] = _legacy.BACKUP_TABLES_BY_VERSION[5]
_legacy.BACKUP_TABLES_BY_VERSION[7] = (
    *_legacy.BACKUP_TABLES_BY_VERSION[6],
    "daily_time_goal_periods",
)
_legacy.validate_backup_payload = validate_backup_payload


def run_cli(args=None) -> int:
    return _legacy.run_cli(args)


if __name__ == "__main__":
    raise SystemExit(run_cli())
