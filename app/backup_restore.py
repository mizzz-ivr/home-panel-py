from __future__ import annotations

import copy
import json
from datetime import date, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import update

import app.backup_restore_legacy as _legacy
from app.backup_restore_legacy import *  # noqa: F401,F403
from app.models.app_setting import AppSetting
from app.models.task import Task
from app.models.time_goal import DailyTimeGoalPeriod
from app.task_priority import DEFAULT_TASK_PRIORITY
from app.time_goal_constants import DAILY_TIME_GOAL_KEY

_legacy_normalize_backup_payload = _legacy.normalize_backup_payload
_legacy_insert_normalized_payload = _legacy.insert_normalized_payload
_legacy_restore_backup_file = _legacy.restore_backup_file
_legacy_format_record_summary = _legacy.format_record_summary


def normalize_backup_payload(payload: dict[str, Any]) -> dict[str, Any]:
    source = copy.deepcopy(payload)
    source_schema_version = source["schema_version"]
    goal_periods = (
        copy.deepcopy(source["data"].get("daily_time_goal_periods", []))
        if source_schema_version >= 7
        else []
    )

    if source_schema_version < 6:
        for task in source["data"]["tasks"]:
            task["due_date"] = None
            task["priority"] = DEFAULT_TASK_PRIORITY

    previous_current_version = _legacy.CURRENT_BACKUP_SCHEMA_VERSION
    _legacy.CURRENT_BACKUP_SCHEMA_VERSION = 6
    try:
        normalized = _legacy_normalize_backup_payload(source)
    finally:
        _legacy.CURRENT_BACKUP_SCHEMA_VERSION = previous_current_version

    normalized["schema_version"] = 7
    normalized["data"]["daily_time_goal_periods"] = goal_periods
    normalized["record_counts"]["daily_time_goal_periods"] = len(goal_periods)

    errors = validate_backup_payload(normalized)
    if errors:
        details = "\n".join(f"- {error}" for error in errors)
        raise BackupRestoreInputError(
            "旧バックアップを現在形式へ安全に変換できません。\n" + details
        )
    return normalized


def insert_normalized_payload(db, payload: dict[str, Any]) -> None:
    _legacy_insert_normalized_payload(db, payload)
    for record in payload["data"]["tasks"]:
        result = db.execute(
            update(Task)
            .where(Task.id == record["id"])
            .values(
                due_date=(
                    date.fromisoformat(record["due_date"])
                    if record["due_date"] is not None
                    else None
                ),
                priority=record["priority"],
                updated_at=parse_utc_datetime(record["updated_at"]),
            )
        )
        if result.rowcount != 1:
            raise RuntimeError(
                f"復元対象のToDoが見つかりません: {record['id']}"
            )

    goal_periods = payload["data"].get("daily_time_goal_periods", [])
    db.add_all(
        [
            DailyTimeGoalPeriod(
                id=record["id"],
                goal_minutes=record["goal_minutes"],
                started_on=date.fromisoformat(record["started_on"]),
                ended_on=(
                    date.fromisoformat(record["ended_on"])
                    if record["ended_on"] is not None
                    else None
                ),
                created_at=parse_utc_datetime(record["created_at"]),
            )
            for record in goal_periods
        ]
    )

    open_periods = [record for record in goal_periods if record["ended_on"] is None]
    if len(open_periods) > 1:
        raise RuntimeError("復元対象の時間目標履歴に開放中期間が複数あります。")
    if open_periods:
        current_goal = open_periods[0]["goal_minutes"]
        db.add(
            AppSetting(
                key=DAILY_TIME_GOAL_KEY,
                value=json.dumps(
                    current_goal,
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
            )
        )

    db.expire_all()


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


def format_record_summary(record_counts: dict[str, int]) -> str:
    summary = _legacy_format_record_summary(record_counts)
    if "daily_time_goal_periods" in record_counts:
        summary += f"、時間目標履歴={record_counts['daily_time_goal_periods']}"
    return summary


_legacy.DESTINATION_TABLES.add("daily_time_goal_periods")
_legacy.normalize_backup_payload = normalize_backup_payload
_legacy.insert_normalized_payload = insert_normalized_payload
_legacy.restore_backup_file = restore_backup_file
_legacy.format_record_summary = format_record_summary


def run_cli(args=None) -> int:
    return _legacy.run_cli(args)


if __name__ == "__main__":
    raise SystemExit(run_cli())
