from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import defaultdict
from collections.abc import Sequence
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable

from app.backup_export import BACKUP_SCHEMA_VERSION
from app.schemas.time_entry import TIME_ENTRY_CATEGORIES

BACKUP_APPLICATION = "home-panel-py"
SUPPORTED_BACKUP_SCHEMA_VERSIONS = tuple(range(1, BACKUP_SCHEMA_VERSION + 1))
BACKUP_TABLES_BY_VERSION = {
    1: ("tasks", "daily_memos", "time_entries"),
    2: ("tasks", "daily_memos", "time_entries", "habits", "habit_completions"),
    3: ("tasks", "daily_memos", "time_entries", "habits", "habit_completions"),
    4: (
        "tasks",
        "daily_memos",
        "time_entries",
        "habits",
        "habit_active_periods",
        "habit_completions",
    ),
    5: (
        "tasks",
        "daily_memos",
        "time_entries",
        "habits",
        "habit_active_periods",
        "habit_schedule_periods",
        "habit_completions",
    ),
}
MAX_BACKUP_FILE_SIZE = 50 * 1024 * 1024
MAX_VALIDATION_ERRORS = 100
DATE_PATTERN = re.compile(r"\d{4}-\d{2}-\d{2}\Z")
UTC_DATETIME_PATTERN = re.compile(
    r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z\Z"
)
SHA256_PATTERN = re.compile(r"[0-9a-fA-F]{64}\Z")


class BackupInputError(ValueError):
    """バックアップファイルまたはCLI入力が検証前提を満たさない場合。"""


class DuplicateJsonKeyError(ValueError):
    """JSONオブジェクト内で同じキーが複数回定義された場合。"""


class ErrorCollector:
    def __init__(self, limit: int = MAX_VALIDATION_ERRORS) -> None:
        self.limit = limit
        self.errors: list[str] = []
        self.truncated = False

    def add(self, message: str) -> None:
        if len(self.errors) < self.limit:
            self.errors.append(message)
        else:
            self.truncated = True

    def result(self) -> list[str]:
        if self.truncated:
            return [
                *self.errors,
                f"検証エラーが{self.limit}件を超えたため、以降を省略しました。",
            ]
        return self.errors


def reject_duplicate_json_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise DuplicateJsonKeyError(f"JSON内でキーが重複しています: {key}")
        result[key] = value
    return result


def load_backup_file(path: Path) -> tuple[Any, str]:
    source = path.expanduser().resolve()
    if not source.is_file():
        raise BackupInputError(f"バックアップファイルが見つかりません: {source}")

    file_size = source.stat().st_size
    if file_size > MAX_BACKUP_FILE_SIZE:
        raise BackupInputError(
            f"バックアップファイルが大きすぎます: {file_size} bytes "
            f"（上限: {MAX_BACKUP_FILE_SIZE} bytes）"
        )

    raw = source.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise BackupInputError("バックアップファイルはUTF-8として読み取れません。") from exc

    try:
        payload = json.loads(text, object_pairs_hook=reject_duplicate_json_keys)
    except DuplicateJsonKeyError as exc:
        raise BackupInputError(str(exc)) from exc
    except json.JSONDecodeError as exc:
        raise BackupInputError(
            f"JSONとして読み取れません: {exc.msg}（行{exc.lineno}、列{exc.colno}）"
        ) from exc

    return payload, digest


def validate_exact_keys(
    value: dict[str, Any],
    expected_keys: set[str],
    path: str,
    errors: ErrorCollector,
) -> None:
    actual_keys = set(value)
    for key in sorted(expected_keys - actual_keys):
        errors.add(f"{path}.{key}: 必須項目がありません。")
    for key in sorted(actual_keys - expected_keys):
        errors.add(f"{path}.{key}: 未知の項目です。")


def validate_positive_id(value: Any, path: str, errors: ErrorCollector) -> int | None:
    if type(value) is not int or value <= 0:
        errors.add(f"{path}: 1以上の整数である必要があります。")
        return None
    return value


def validate_string(
    value: Any,
    path: str,
    errors: ErrorCollector,
    *,
    min_length: int = 0,
    max_length: int,
    disallow_blank: bool = False,
) -> str | None:
    if type(value) is not str:
        errors.add(f"{path}: 文字列である必要があります。")
        return None
    if len(value) < min_length or len(value) > max_length:
        errors.add(f"{path}: {min_length}〜{max_length}文字である必要があります。")
    if disallow_blank and not value.strip():
        errors.add(f"{path}: 空白だけの文字列は指定できません。")
    return value


def validate_date_string(value: Any, path: str, errors: ErrorCollector) -> date | None:
    if type(value) is not str or not DATE_PATTERN.fullmatch(value):
        errors.add(f"{path}: YYYY-MM-DD形式の文字列である必要があります。")
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        errors.add(f"{path}: 実在する日付ではありません。")
        return None


def validate_nullable_date_string(
    value: Any,
    path: str,
    errors: ErrorCollector,
) -> date | None:
    if value is None:
        return None
    return validate_date_string(value, path, errors)


def validate_utc_datetime_string(
    value: Any,
    path: str,
    errors: ErrorCollector,
) -> datetime | None:
    if type(value) is not str or not UTC_DATETIME_PATTERN.fullmatch(value):
        errors.add(f"{path}: UTCのISO 8601形式（末尾Z）である必要があります。")
        return None
    try:
        parsed = datetime.fromisoformat(value.removesuffix("Z") + "+00:00")
    except ValueError:
        errors.add(f"{path}: 実在する日時ではありません。")
        return None
    if parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        errors.add(f"{path}: UTC日時である必要があります。")
        return None
    return parsed


def validate_nullable_utc_datetime_string(
    value: Any,
    path: str,
    errors: ErrorCollector,
) -> datetime | None:
    if value is None:
        return None
    return validate_utc_datetime_string(value, path, errors)


def validate_task(record: Any, index: int, errors: ErrorCollector) -> int | None:
    path = f"data.tasks[{index}]"
    if type(record) is not dict:
        errors.add(f"{path}: オブジェクトである必要があります。")
        return None
    validate_exact_keys(
        record,
        {"id", "title", "is_done", "created_at", "updated_at"},
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
    created_at = validate_utc_datetime_string(
        record.get("created_at"), f"{path}.created_at", errors
    )
    updated_at = validate_utc_datetime_string(
        record.get("updated_at"), f"{path}.updated_at", errors
    )
    if created_at is not None and updated_at is not None and updated_at < created_at:
        errors.add(f"{path}.updated_at: created_at以降である必要があります。")
    return record_id


def validate_daily_memo(record: Any, index: int, errors: ErrorCollector) -> int | None:
    path = f"data.daily_memos[{index}]"
    if type(record) is not dict:
        errors.add(f"{path}: オブジェクトである必要があります。")
        return None
    validate_exact_keys(
        record, {"id", "memo_date", "content", "updated_at"}, path, errors
    )
    record_id = validate_positive_id(record.get("id"), f"{path}.id", errors)
    validate_date_string(record.get("memo_date"), f"{path}.memo_date", errors)
    validate_string(record.get("content"), f"{path}.content", errors, max_length=5000)
    validate_utc_datetime_string(
        record.get("updated_at"), f"{path}.updated_at", errors
    )
    return record_id


def validate_time_entry(record: Any, index: int, errors: ErrorCollector) -> int | None:
    path = f"data.time_entries[{index}]"
    if type(record) is not dict:
        errors.add(f"{path}: オブジェクトである必要があります。")
        return None
    validate_exact_keys(
        record,
        {"id", "entry_date", "category", "minutes", "note", "created_at"},
        path,
        errors,
    )
    record_id = validate_positive_id(record.get("id"), f"{path}.id", errors)
    validate_date_string(record.get("entry_date"), f"{path}.entry_date", errors)
    category = record.get("category")
    if type(category) is not str or category not in TIME_ENTRY_CATEGORIES:
        errors.add(
            f"{path}.category: "
            + "・".join(TIME_ENTRY_CATEGORIES)
            + "のいずれかである必要があります。"
        )
    minutes = record.get("minutes")
    if type(minutes) is not int or not 1 <= minutes <= 1440:
        errors.add(f"{path}.minutes: 1〜1440の整数である必要があります。")
    validate_string(record.get("note"), f"{path}.note", errors, max_length=255)
    validate_utc_datetime_string(
        record.get("created_at"), f"{path}.created_at", errors
    )
    return record_id


def validate_habit_v2(record: Any, index: int, errors: ErrorCollector) -> int | None:
    path = f"data.habits[{index}]"
    if type(record) is not dict:
        errors.add(f"{path}: オブジェクトである必要があります。")
        return None
    validate_exact_keys(
        record,
        {"id", "name", "is_active", "created_at", "updated_at"},
        path,
        errors,
    )
    record_id = validate_positive_id(record.get("id"), f"{path}.id", errors)
    validate_string(
        record.get("name"),
        f"{path}.name",
        errors,
        min_length=1,
        max_length=100,
        disallow_blank=True,
    )
    if type(record.get("is_active")) is not bool:
        errors.add(f"{path}.is_active: 真偽値である必要があります。")
    created_at = validate_utc_datetime_string(
        record.get("created_at"), f"{path}.created_at", errors
    )
    updated_at = validate_utc_datetime_string(
        record.get("updated_at"), f"{path}.updated_at", errors
    )
    if created_at is not None and updated_at is not None and updated_at < created_at:
        errors.add(f"{path}.updated_at: created_at以降である必要があります。")
    return record_id


def validate_habit_v3(record: Any, index: int, errors: ErrorCollector) -> int | None:
    path = f"data.habits[{index}]"
    if type(record) is not dict:
        errors.add(f"{path}: オブジェクトである必要があります。")
        return None
    validate_exact_keys(
        record,
        {"id", "name", "is_active", "archived_at", "created_at", "updated_at"},
        path,
        errors,
    )
    record_id = validate_positive_id(record.get("id"), f"{path}.id", errors)
    validate_string(
        record.get("name"),
        f"{path}.name",
        errors,
        min_length=1,
        max_length=100,
        disallow_blank=True,
    )
    is_active = record.get("is_active")
    if type(is_active) is not bool:
        errors.add(f"{path}.is_active: 真偽値である必要があります。")
    created_at = validate_utc_datetime_string(
        record.get("created_at"), f"{path}.created_at", errors
    )
    updated_at = validate_utc_datetime_string(
        record.get("updated_at"), f"{path}.updated_at", errors
    )
    archived_at = validate_nullable_utc_datetime_string(
        record.get("archived_at"), f"{path}.archived_at", errors
    )
    if created_at is not None and updated_at is not None and updated_at < created_at:
        errors.add(f"{path}.updated_at: created_at以降である必要があります。")
    if is_active is True and record.get("archived_at") is not None:
        errors.add(f"{path}.archived_at: アクティブな習慣ではnullである必要があります。")
    if is_active is False and record.get("archived_at") is None:
        errors.add(f"{path}.archived_at: 終了済み習慣では必須です。")
    if created_at is not None and archived_at is not None and archived_at < created_at:
        errors.add(f"{path}.archived_at: created_at以降である必要があります。")
    if updated_at is not None and archived_at is not None and updated_at < archived_at:
        errors.add(f"{path}.updated_at: archived_at以降である必要があります。")
    return record_id


def validate_habit_active_period(
    record: Any, index: int, errors: ErrorCollector
) -> int | None:
    path = f"data.habit_active_periods[{index}]"
    if type(record) is not dict:
        errors.add(f"{path}: オブジェクトである必要があります。")
        return None
    validate_exact_keys(
        record,
        {"id", "habit_id", "started_on", "ended_on", "created_at"},
        path,
        errors,
    )
    record_id = validate_positive_id(record.get("id"), f"{path}.id", errors)
    validate_positive_id(record.get("habit_id"), f"{path}.habit_id", errors)
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


def validate_weekdays(value: Any, path: str, errors: ErrorCollector) -> tuple[int, ...] | None:
    if type(value) is not list:
        errors.add(f"{path}: 配列である必要があります。")
        return None
    if not value:
        errors.add(f"{path}: 月曜日0〜日曜日6から1つ以上必要です。")
        return None
    valid: list[int] = []
    seen: set[int] = set()
    for index, weekday in enumerate(value):
        if type(weekday) is not int or not 0 <= weekday <= 6:
            errors.add(f"{path}[{index}]: 0〜6の整数である必要があります。")
            continue
        if weekday in seen:
            errors.add(f"{path}[{index}]: 曜日 {weekday} が重複しています。")
            continue
        seen.add(weekday)
        valid.append(weekday)
    return tuple(valid)


def validate_habit_schedule_period(
    record: Any, index: int, errors: ErrorCollector
) -> int | None:
    path = f"data.habit_schedule_periods[{index}]"
    if type(record) is not dict:
        errors.add(f"{path}: オブジェクトである必要があります。")
        return None
    validate_exact_keys(
        record,
        {
            "id",
            "habit_id",
            "schedule_type",
            "weekdays",
            "started_on",
            "ended_on",
            "created_at",
        },
        path,
        errors,
    )
    record_id = validate_positive_id(record.get("id"), f"{path}.id", errors)
    validate_positive_id(record.get("habit_id"), f"{path}.habit_id", errors)
    if record.get("schedule_type") != "weekdays":
        errors.add(f"{path}.schedule_type: weekdaysである必要があります。")
    validate_weekdays(record.get("weekdays"), f"{path}.weekdays", errors)
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


def validate_habit_completion(
    record: Any, index: int, errors: ErrorCollector
) -> int | None:
    path = f"data.habit_completions[{index}]"
    if type(record) is not dict:
        errors.add(f"{path}: オブジェクトである必要があります。")
        return None
    validate_exact_keys(
        record, {"id", "habit_id", "completed_on", "created_at"}, path, errors
    )
    record_id = validate_positive_id(record.get("id"), f"{path}.id", errors)
    validate_positive_id(record.get("habit_id"), f"{path}.habit_id", errors)
    validate_date_string(record.get("completed_on"), f"{path}.completed_on", errors)
    validate_utc_datetime_string(
        record.get("created_at"), f"{path}.created_at", errors
    )
    return record_id


Validator = Callable[[Any, int, ErrorCollector], int | None]


def validate_records(
    records: Any,
    table_name: str,
    validator: Validator,
    errors: ErrorCollector,
) -> tuple[int | None, set[int]]:
    path = f"data.{table_name}"
    if type(records) is not list:
        errors.add(f"{path}: 配列である必要があります。")
        return None, set()
    seen_ids: set[int] = set()
    for index, record in enumerate(records):
        record_id = validator(record, index, errors)
        if record_id is not None:
            if record_id in seen_ids:
                errors.add(f"{path}[{index}].id: ID {record_id} が重複しています。")
            seen_ids.add(record_id)
    return len(records), seen_ids


def validate_habit_references(
    data: dict[str, Any], habit_ids: set[int], errors: ErrorCollector
) -> None:
    records = data.get("habit_completions")
    if type(records) is not list:
        return
    seen_pairs: set[tuple[int, str]] = set()
    for index, record in enumerate(records):
        if type(record) is not dict:
            continue
        habit_id = record.get("habit_id")
        completed_on = record.get("completed_on")
        if type(habit_id) is int and habit_id not in habit_ids:
            errors.add(
                f"data.habit_completions[{index}].habit_id: habitsに存在しないIDです。"
            )
        if type(habit_id) is int and type(completed_on) is str:
            pair = (habit_id, completed_on)
            if pair in seen_pairs:
                errors.add(
                    f"data.habit_completions[{index}]: "
                    "同じ習慣・日付の達成記録が重複しています。"
                )
            seen_pairs.add(pair)


def parse_period_records(
    records: Any,
    table_name: str,
    habit_ids: set[int],
    errors: ErrorCollector,
) -> dict[int, list[tuple[date, date | None, int, dict[str, Any]]]]:
    grouped: dict[int, list[tuple[date, date | None, int, dict[str, Any]]]] = defaultdict(list)
    seen_starts: set[tuple[int, date]] = set()
    if type(records) is not list:
        return grouped
    for index, record in enumerate(records):
        if type(record) is not dict:
            continue
        habit_id = record.get("habit_id")
        if type(habit_id) is not int:
            continue
        if habit_id not in habit_ids:
            errors.add(f"data.{table_name}[{index}].habit_id: habitsに存在しないIDです。")
            continue
        try:
            started_on = (
                date.fromisoformat(record["started_on"])
                if type(record.get("started_on")) is str
                else None
            )
            ended_on = (
                date.fromisoformat(record["ended_on"])
                if type(record.get("ended_on")) is str
                else None
            )
        except ValueError:
            continue
        if started_on is None:
            continue
        pair = (habit_id, started_on)
        if pair in seen_starts:
            label = "有効期間" if table_name == "habit_active_periods" else "曜日設定期間"
            errors.add(
                f"data.{table_name}[{index}]: 同じ習慣・開始日の{label}が重複しています。"
            )
        seen_starts.add(pair)
        grouped[habit_id].append((started_on, ended_on, index, record))
    return grouped


def validate_non_overlapping_periods(
    grouped: dict[int, list[tuple[date, date | None, int, dict[str, Any]]]],
    table_name: str,
    label: str,
    errors: ErrorCollector,
) -> None:
    for periods in grouped.values():
        ordered = sorted(periods, key=lambda item: (item[0], item[2]))
        previous_end: date | None = None
        for position, (started_on, ended_on, index, _) in enumerate(ordered):
            if position > 0 and (previous_end is None or started_on <= previous_end):
                errors.add(
                    f"data.{table_name}[{index}]: 同じ習慣の{label}が重複しています。"
                )
            previous_end = ended_on


def build_habits_by_id(data: dict[str, Any]) -> dict[int, dict[str, Any]]:
    records = data.get("habits")
    if type(records) is not list:
        return {}
    return {
        record["id"]: record
        for record in records
        if type(record) is dict and type(record.get("id")) is int
    }


def validate_active_period_consistency(
    data: dict[str, Any],
    habit_ids: set[int],
    errors: ErrorCollector,
) -> dict[int, list[tuple[date, date | None, int, dict[str, Any]]]]:
    periods = parse_period_records(
        data.get("habit_active_periods"),
        "habit_active_periods",
        habit_ids,
        errors,
    )
    validate_non_overlapping_periods(
        periods, "habit_active_periods", "有効期間", errors
    )
    habits_by_id = build_habits_by_id(data)
    for habit_id in habit_ids:
        habit_periods = sorted(periods.get(habit_id, []), key=lambda item: item[0])
        if not habit_periods:
            errors.add(f"data.habits: 習慣ID {habit_id} の有効期間がありません。")
            continue
        open_count = sum(1 for _, ended_on, _, _ in habit_periods if ended_on is None)
        is_active = habits_by_id.get(habit_id, {}).get("is_active")
        if is_active is True and open_count != 1:
            errors.add(
                f"data.habit_active_periods: アクティブな習慣ID {habit_id} は"
                "開放中の有効期間が1件必要です。"
            )
        if is_active is False and open_count != 0:
            errors.add(
                f"data.habit_active_periods: 終了済み習慣ID {habit_id} に"
                "開放中の有効期間があります。"
            )
        created_at_raw = habits_by_id.get(habit_id, {}).get("created_at")
        if type(created_at_raw) is str:
            try:
                created_on = datetime.fromisoformat(
                    created_at_raw.removesuffix("Z") + "+00:00"
                ).date()
                if habit_periods[0][0] < created_on:
                    errors.add(
                        f"data.habit_active_periods: 習慣ID {habit_id} の開始日が"
                        "習慣作成日より前です。"
                    )
            except ValueError:
                pass

    completion_records = data.get("habit_completions")
    if type(completion_records) is list:
        for index, record in enumerate(completion_records):
            if type(record) is not dict:
                continue
            habit_id = record.get("habit_id")
            completed_raw = record.get("completed_on")
            if type(habit_id) is not int or type(completed_raw) is not str:
                continue
            try:
                completed_on = date.fromisoformat(completed_raw)
            except ValueError:
                continue
            habit_periods = periods.get(habit_id, [])
            if habit_periods and not any(
                started <= completed_on and (ended is None or completed_on <= ended)
                for started, ended, _, _ in habit_periods
            ):
                errors.add(
                    f"data.habit_completions[{index}].completed_on: "
                    "習慣の有効期間外の達成記録です。"
                )
    return periods


def validate_schedule_period_consistency(
    data: dict[str, Any],
    habit_ids: set[int],
    active_periods: dict[
        int, list[tuple[date, date | None, int, dict[str, Any]]]
    ],
    errors: ErrorCollector,
) -> None:
    schedules = parse_period_records(
        data.get("habit_schedule_periods"),
        "habit_schedule_periods",
        habit_ids,
        errors,
    )
    validate_non_overlapping_periods(
        schedules, "habit_schedule_periods", "曜日設定期間", errors
    )
    habits_by_id = build_habits_by_id(data)

    for habit_id in habit_ids:
        periods = sorted(schedules.get(habit_id, []), key=lambda item: item[0])
        if not periods:
            errors.add(f"data.habits: 習慣ID {habit_id} の曜日設定期間がありません。")
            continue
        open_count = sum(1 for _, ended_on, _, _ in periods if ended_on is None)
        if open_count != 1:
            errors.add(
                f"data.habit_schedule_periods: 習慣ID {habit_id} は"
                "開放中の曜日設定期間が1件必要です。"
            )
        created_at_raw = habits_by_id.get(habit_id, {}).get("created_at")
        if type(created_at_raw) is str:
            try:
                created_on = datetime.fromisoformat(
                    created_at_raw.removesuffix("Z") + "+00:00"
                ).date()
                if periods[0][0] < created_on:
                    errors.add(
                        f"data.habit_schedule_periods: 習慣ID {habit_id} の開始日が"
                        "習慣作成日より前です。"
                    )
            except ValueError:
                pass

    completion_records = data.get("habit_completions")
    if type(completion_records) is not list:
        return
    for index, record in enumerate(completion_records):
        if type(record) is not dict:
            continue
        habit_id = record.get("habit_id")
        completed_raw = record.get("completed_on")
        if type(habit_id) is not int or type(completed_raw) is not str:
            continue
        try:
            completed_on = date.fromisoformat(completed_raw)
        except ValueError:
            continue
        if active_periods.get(habit_id) and not any(
            started <= completed_on and (ended is None or completed_on <= ended)
            for started, ended, _, _ in active_periods[habit_id]
        ):
            continue
        matching = [
            record_data
            for started, ended, _, record_data in schedules.get(habit_id, [])
            if started <= completed_on and (ended is None or completed_on <= ended)
        ]
        if not matching:
            errors.add(
                f"data.habit_completions[{index}].completed_on: "
                "曜日設定期間外の達成記録です。"
            )
            continue
        weekdays = matching[-1].get("weekdays")
        if type(weekdays) is list and completed_on.weekday() not in weekdays:
            errors.add(
                f"data.habit_completions[{index}].completed_on: "
                "対象曜日外の達成記録です。"
            )


def validate_backup_payload(payload: Any) -> list[str]:
    errors = ErrorCollector()
    if type(payload) is not dict:
        errors.add("$: JSONのルートはオブジェクトである必要があります。")
        return errors.result()

    validate_exact_keys(
        payload,
        {"schema_version", "application", "exported_at", "record_counts", "data"},
        "$",
        errors,
    )
    schema_version = payload.get("schema_version")
    if type(schema_version) is not int:
        errors.add("$.schema_version: 整数である必要があります。")
        return errors.result()
    if schema_version not in SUPPORTED_BACKUP_SCHEMA_VERSIONS:
        errors.add(
            "$.schema_version: 未対応のバージョンです。"
            f"対応={SUPPORTED_BACKUP_SCHEMA_VERSIONS}、指定={schema_version}"
        )
        return errors.result()

    if payload.get("application") != BACKUP_APPLICATION:
        errors.add(f"$.application: {BACKUP_APPLICATION}である必要があります。")
    validate_utc_datetime_string(payload.get("exported_at"), "$.exported_at", errors)

    table_names = BACKUP_TABLES_BY_VERSION[schema_version]
    record_counts = payload.get("record_counts")
    data = payload.get("data")
    if type(record_counts) is not dict:
        errors.add("$.record_counts: オブジェクトである必要があります。")
        record_counts = {}
    else:
        validate_exact_keys(record_counts, set(table_names), "record_counts", errors)
    if type(data) is not dict:
        errors.add("$.data: オブジェクトである必要があります。")
        return errors.result()
    validate_exact_keys(data, set(table_names), "data", errors)

    validators: dict[str, Validator] = {
        "tasks": validate_task,
        "daily_memos": validate_daily_memo,
        "time_entries": validate_time_entry,
        "habits": validate_habit_v3 if schema_version >= 3 else validate_habit_v2,
        "habit_active_periods": validate_habit_active_period,
        "habit_schedule_periods": validate_habit_schedule_period,
        "habit_completions": validate_habit_completion,
    }
    ids_by_table: dict[str, set[int]] = {}
    for table_name in table_names:
        actual_count, record_ids = validate_records(
            data.get(table_name), table_name, validators[table_name], errors
        )
        ids_by_table[table_name] = record_ids
        expected_count = record_counts.get(table_name)
        if type(expected_count) is not int or expected_count < 0:
            errors.add(f"record_counts.{table_name}: 0以上の整数である必要があります。")
        elif actual_count is not None and expected_count != actual_count:
            errors.add(
                f"record_counts.{table_name}: 配列件数と一致しません。"
                f"記録={expected_count}、実際={actual_count}"
            )

    if schema_version >= 2:
        validate_habit_references(data, ids_by_table.get("habits", set()), errors)
    active_periods: dict[
        int, list[tuple[date, date | None, int, dict[str, Any]]]
    ] = {}
    if schema_version >= 4:
        active_periods = validate_active_period_consistency(
            data, ids_by_table.get("habits", set()), errors
        )
    if schema_version >= 5:
        validate_schedule_period_consistency(
            data,
            ids_by_table.get("habits", set()),
            active_periods,
            errors,
        )
    return errors.result()


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Home PanelのJSONバックアップが復元前提を満たすか検証します。"
    )
    parser.add_argument("backup", type=Path, help="検証対象のJSONバックアップファイル")
    parser.add_argument(
        "--expected-sha256",
        help="既知のSHA-256（64桁の16進数）とファイル内容を照合する",
    )
    return parser


def run_cli(args: Sequence[str] | None = None) -> int:
    options = create_parser().parse_args(args)
    expected_sha256 = options.expected_sha256
    if expected_sha256 is not None and not SHA256_PATTERN.fullmatch(expected_sha256):
        print("--expected-sha256は64桁の16進数で指定してください。", file=sys.stderr)
        return 2

    try:
        payload, digest = load_backup_file(options.backup)
    except BackupInputError as exc:
        print(f"バックアップを検証できません: {exc}", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"バックアップファイルの読み取りに失敗しました: {exc}", file=sys.stderr)
        return 1

    errors = validate_backup_payload(payload)
    if expected_sha256 is not None and digest != expected_sha256.lower():
        errors.append(
            "SHA-256が一致しません。"
            f"期待={expected_sha256.lower()}、実際={digest}"
        )

    if errors:
        print("バックアップの検証に失敗しました。", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 2

    counts = payload["record_counts"]
    summary = (
        f"ToDo={counts['tasks']}、メモ={counts['daily_memos']}、"
        f"時間記録={counts['time_entries']}"
    )
    if payload["schema_version"] >= 2:
        summary += (
            f"、習慣={counts['habits']}、習慣達成={counts['habit_completions']}"
        )
    if payload["schema_version"] >= 4:
        summary += f"、習慣有効期間={counts['habit_active_periods']}"
    if payload["schema_version"] >= 5:
        summary += f"、曜日設定期間={counts['habit_schedule_periods']}"
    print("バックアップは有効です。")
    print(f"レコード件数: {summary}")
    print(f"SHA-256: {digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(run_cli())
