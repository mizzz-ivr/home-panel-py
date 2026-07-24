from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections.abc import Sequence
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from app.backup_export import BACKUP_SCHEMA_VERSION
from app.schemas.time_entry import TIME_ENTRY_CATEGORIES

BACKUP_APPLICATION = "home-panel-py"
BACKUP_TABLES = ("tasks", "daily_memos", "time_entries")
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
            return [*self.errors, f"検証エラーが{self.limit}件を超えたため、以降を省略しました。"]
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
    task_id = validate_positive_id(record.get("id"), f"{path}.id", errors)
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
    created_at = validate_utc_datetime_string(record.get("created_at"), f"{path}.created_at", errors)
    updated_at = validate_utc_datetime_string(record.get("updated_at"), f"{path}.updated_at", errors)
    if created_at is not None and updated_at is not None and updated_at < created_at:
        errors.add(f"{path}.updated_at: created_at以降である必要があります。")
    return task_id


def validate_daily_memo(record: Any, index: int, errors: ErrorCollector) -> int | None:
    path = f"data.daily_memos[{index}]"
    if type(record) is not dict:
        errors.add(f"{path}: オブジェクトである必要があります。")
        return None

    validate_exact_keys(record, {"id", "memo_date", "content", "updated_at"}, path, errors)
    memo_id = validate_positive_id(record.get("id"), f"{path}.id", errors)
    validate_date_string(record.get("memo_date"), f"{path}.memo_date", errors)
    validate_string(record.get("content"), f"{path}.content", errors, max_length=5000)
    validate_utc_datetime_string(record.get("updated_at"), f"{path}.updated_at", errors)
    return memo_id


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
    entry_id = validate_positive_id(record.get("id"), f"{path}.id", errors)
    validate_date_string(record.get("entry_date"), f"{path}.entry_date", errors)

    category = record.get("category")
    if type(category) is not str or category not in TIME_ENTRY_CATEGORIES:
        errors.add(
            f"{path}.category: " + "・".join(TIME_ENTRY_CATEGORIES) + "のいずれかである必要があります。"
        )

    minutes = record.get("minutes")
    if type(minutes) is not int or not 1 <= minutes <= 1440:
        errors.add(f"{path}.minutes: 1〜1440の整数である必要があります。")

    validate_string(record.get("note"), f"{path}.note", errors, max_length=255)
    validate_utc_datetime_string(record.get("created_at"), f"{path}.created_at", errors)
    return entry_id


def validate_records(
    records: Any,
    table_name: str,
    validator: Any,
    errors: ErrorCollector,
) -> int | None:
    path = f"data.{table_name}"
    if type(records) is not list:
        errors.add(f"{path}: 配列である必要があります。")
        return None

    seen_ids: set[int] = set()
    for index, record in enumerate(records):
        record_id = validator(record, index, errors)
        if record_id is not None:
            if record_id in seen_ids:
                errors.add(f"{path}[{index}].id: ID {record_id} が重複しています。")
            seen_ids.add(record_id)
    return len(records)


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
    if schema_version != BACKUP_SCHEMA_VERSION:
        errors.add(
            f"$.schema_version: 未対応のバージョンです。"
            f"対応={BACKUP_SCHEMA_VERSION}、指定={schema_version}"
        )
        return errors.result()

    if payload.get("application") != BACKUP_APPLICATION:
        errors.add(f"$.application: {BACKUP_APPLICATION}である必要があります。")
    validate_utc_datetime_string(payload.get("exported_at"), "$.exported_at", errors)

    record_counts = payload.get("record_counts")
    data = payload.get("data")
    if type(record_counts) is not dict:
        errors.add("$.record_counts: オブジェクトである必要があります。")
        record_counts = {}
    else:
        validate_exact_keys(record_counts, set(BACKUP_TABLES), "record_counts", errors)

    if type(data) is not dict:
        errors.add("$.data: オブジェクトである必要があります。")
        return errors.result()
    validate_exact_keys(data, set(BACKUP_TABLES), "data", errors)

    validators = {
        "tasks": validate_task,
        "daily_memos": validate_daily_memo,
        "time_entries": validate_time_entry,
    }
    for table_name in BACKUP_TABLES:
        actual_count = validate_records(data.get(table_name), table_name, validators[table_name], errors)
        expected_count = record_counts.get(table_name)
        if type(expected_count) is not int or expected_count < 0:
            errors.add(f"record_counts.{table_name}: 0以上の整数である必要があります。")
        elif actual_count is not None and expected_count != actual_count:
            errors.add(
                f"record_counts.{table_name}: 配列件数と一致しません。"
                f"記録={expected_count}、実際={actual_count}"
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
    print("バックアップは有効です。")
    print(
        "レコード件数: "
        f"ToDo={counts['tasks']}、メモ={counts['daily_memos']}、時間記録={counts['time_entries']}"
    )
    print(f"SHA-256: {digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(run_cli())
