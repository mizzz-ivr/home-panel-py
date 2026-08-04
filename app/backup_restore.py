from __future__ import annotations

import argparse
import copy
import os
import shutil
import sys
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import Engine, create_engine, event, inspect, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from app.backup_export import BACKUP_SCHEMA_VERSION, build_backup_payload
from app.backup_validate import (
    BACKUP_APPLICATION,
    SHA256_PATTERN,
    BackupInputError,
    load_backup_file,
    validate_backup_payload,
)
from app.db import Base
from app.habit_schedule import weekdays_to_mask
from app.models.app_setting import AppSetting
from app.models.habit import (
    Habit,
    HabitActivePeriod,
    HabitCompletion,
    HabitSchedulePeriod,
)
from app.models.memo import DailyMemo
from app.models.task import Task
from app.models.time_entry import TimeEntry

CURRENT_BACKUP_SCHEMA_VERSION = BACKUP_SCHEMA_VERSION
RESTORED_TABLES = (
    "tasks",
    "daily_memos",
    "time_entries",
    "habits",
    "habit_active_periods",
    "habit_schedule_periods",
    "habit_completions",
)
DESTINATION_TABLES = {*RESTORED_TABLES, "app_settings"}
SQLITE_INTERNAL_TABLES = {"sqlite_sequence"}


class BackupRestoreInputError(ValueError):
    """復元入力または復元先が安全条件を満たさない場合。"""


class DestinationNotEmptyError(BackupRestoreInputError):
    """復元先に既存データがあり、安全に置換できない場合。"""


@dataclass(frozen=True)
class RestoreResult:
    database_path: Path
    source_sha256: str
    source_schema_version: int
    record_counts: dict[str, int]
    safety_copy_path: Path | None


def parse_utc_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.removesuffix("Z") + "+00:00")
    return parsed.astimezone(timezone.utc).replace(tzinfo=None)


def parse_optional_utc_datetime(value: str | None) -> datetime | None:
    return parse_utc_datetime(value) if value is not None else None


def normalize_backup_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """検証済みのv1〜v5バックアップを、現在のv5構造へ決定的に補完する。"""
    schema_version = payload["schema_version"]
    source_data = payload["data"]
    data: dict[str, list[dict[str, Any]]] = {
        "tasks": copy.deepcopy(source_data["tasks"]),
        "daily_memos": copy.deepcopy(source_data["daily_memos"]),
        "time_entries": copy.deepcopy(source_data["time_entries"]),
        "habits": [],
        "habit_active_periods": [],
        "habit_schedule_periods": [],
        "habit_completions": [],
    }

    if schema_version >= 2:
        for source_habit in source_data["habits"]:
            habit = copy.deepcopy(source_habit)
            if schema_version == 2:
                habit["archived_at"] = None if habit["is_active"] else habit["updated_at"]
            data["habits"].append(habit)
        data["habit_completions"] = copy.deepcopy(source_data["habit_completions"])

    ordered_habits = sorted(data["habits"], key=lambda item: item["id"])
    if schema_version >= 4:
        data["habit_active_periods"] = copy.deepcopy(source_data["habit_active_periods"])
    else:
        for index, habit in enumerate(ordered_habits, start=1):
            created_at = parse_utc_datetime(habit["created_at"])
            archived_at = parse_optional_utc_datetime(habit["archived_at"])
            data["habit_active_periods"].append(
                {
                    "id": index,
                    "habit_id": habit["id"],
                    "started_on": created_at.date().isoformat(),
                    "ended_on": archived_at.date().isoformat() if archived_at is not None else None,
                    "created_at": habit["created_at"],
                }
            )

    if schema_version >= 5:
        data["habit_schedule_periods"] = copy.deepcopy(source_data["habit_schedule_periods"])
    else:
        for index, habit in enumerate(ordered_habits, start=1):
            created_at = parse_utc_datetime(habit["created_at"])
            data["habit_schedule_periods"].append(
                {
                    "id": index,
                    "habit_id": habit["id"],
                    "schedule_type": "weekdays",
                    "weekdays": list(range(7)),
                    "started_on": created_at.date().isoformat(),
                    "ended_on": None,
                    "created_at": habit["created_at"],
                }
            )

    data["tasks"].sort(key=lambda item: item["id"])
    data["daily_memos"].sort(key=lambda item: (item["memo_date"], item["id"]))
    data["time_entries"].sort(
        key=lambda item: (item["entry_date"], item["created_at"], item["id"])
    )
    data["habits"].sort(key=lambda item: (item["created_at"], item["id"]))
    data["habit_active_periods"].sort(
        key=lambda item: (item["habit_id"], item["started_on"], item["id"])
    )
    data["habit_schedule_periods"].sort(
        key=lambda item: (item["habit_id"], item["started_on"], item["id"])
    )
    data["habit_completions"].sort(
        key=lambda item: (item["completed_on"], item["habit_id"], item["id"])
    )

    normalized = {
        "schema_version": CURRENT_BACKUP_SCHEMA_VERSION,
        "application": BACKUP_APPLICATION,
        "exported_at": payload["exported_at"],
        "record_counts": {
            table_name: len(data[table_name]) for table_name in RESTORED_TABLES
        },
        "data": data,
    }
    errors = validate_backup_payload(normalized)
    if errors:
        details = "\n".join(f"- {error}" for error in errors)
        raise BackupRestoreInputError(
            "旧バックアップを現在形式へ安全に変換できません。\n" + details
        )
    return normalized


def prepare_backup_for_restore(
    backup_path: Path,
    *,
    expected_sha256: str | None = None,
) -> tuple[dict[str, Any], str, int]:
    if expected_sha256 is not None and not SHA256_PATTERN.fullmatch(expected_sha256):
        raise BackupRestoreInputError(
            "--expected-sha256は64桁の16進数で指定してください。"
        )

    payload, digest = load_backup_file(backup_path)
    errors = validate_backup_payload(payload)
    if expected_sha256 is not None and digest != expected_sha256.lower():
        errors.append(
            "SHA-256が一致しません。"
            f"期待={expected_sha256.lower()}、実際={digest}"
        )
    if errors:
        details = "\n".join(f"- {error}" for error in errors)
        raise BackupRestoreInputError(
            "バックアップの検証に失敗しました。\n" + details
        )

    source_schema_version = payload["schema_version"]
    normalized = normalize_backup_payload(payload)
    return normalized, digest, source_schema_version


def create_sqlite_engine(database_path: Path) -> Engine:
    engine = create_engine(
        f"sqlite:///{database_path.as_posix()}",
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(engine, "connect")
    def enable_sqlite_foreign_keys(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA foreign_keys = ON")
        finally:
            cursor.close()

    return engine


def inspect_restore_destination(database_path: Path) -> bool:
    """復元先が未作成または完全に空かを確認し、既存ファイル有無を返す。"""
    if database_path.is_symlink():
        raise BackupRestoreInputError(
            f"復元先にシンボリックリンクは指定できません: {database_path}"
        )
    if not database_path.exists():
        return False
    if not database_path.is_file():
        raise BackupRestoreInputError(
            f"復元先は通常ファイルである必要があります: {database_path}"
        )
    if database_path.stat().st_size == 0:
        return True

    engine = create_sqlite_engine(database_path)
    try:
        table_names = set(inspect(engine).get_table_names())
        user_tables = table_names - SQLITE_INTERNAL_TABLES
        unknown_tables = user_tables - DESTINATION_TABLES
        if unknown_tables:
            raise BackupRestoreInputError(
                "復元先DBに未対応のテーブルがあります: "
                + ", ".join(sorted(unknown_tables))
            )

        non_empty_tables: list[str] = []
        with engine.connect() as connection:
            integrity = connection.scalar(text("PRAGMA integrity_check"))
            if integrity != "ok":
                raise BackupRestoreInputError(
                    f"復元先DBの整合性確認に失敗しました: {integrity}"
                )
            for table_name in sorted(user_tables):
                count = connection.scalar(text(f'SELECT COUNT(*) FROM "{table_name}"'))
                if count:
                    non_empty_tables.append(f"{table_name}={count}")
        if non_empty_tables:
            raise DestinationNotEmptyError(
                "復元先DBに既存データがあります。"
                "空のDBだけを復元先に指定してください: "
                + ", ".join(non_empty_tables)
            )
        return True
    except SQLAlchemyError as exc:
        raise BackupRestoreInputError(
            f"復元先DBを安全に確認できません: {exc}"
        ) from exc
    finally:
        engine.dispose()


def default_safety_copy_path(
    database_path: Path,
    *,
    created_at: datetime | None = None,
) -> Path:
    timestamp = (created_at or datetime.now(timezone.utc)).astimezone(
        timezone.utc
    ).strftime("%Y%m%dT%H%M%SZ")
    suffix = database_path.suffix or ".db"
    stem = (
        database_path.name[: -len(database_path.suffix)]
        if database_path.suffix
        else database_path.name
    )
    base_name = f"{stem}.pre-restore-{timestamp}"
    candidate = database_path.with_name(base_name + suffix)
    sequence = 2
    while candidate.exists():
        candidate = database_path.with_name(f"{base_name}-{sequence}{suffix}")
        sequence += 1
    return candidate


def fsync_file(path: Path) -> None:
    with path.open("rb") as file_handle:
        os.fsync(file_handle.fileno())


def fsync_directory(path: Path) -> None:
    try:
        descriptor = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    except OSError:
        pass
    finally:
        os.close(descriptor)


def insert_normalized_payload(db: Session, payload: dict[str, Any]) -> None:
    data = payload["data"]
    db.add_all(
        [
            Task(
                id=record["id"],
                title=record["title"],
                is_done=record["is_done"],
                created_at=parse_utc_datetime(record["created_at"]),
                updated_at=parse_utc_datetime(record["updated_at"]),
            )
            for record in data["tasks"]
        ]
    )
    db.add_all(
        [
            DailyMemo(
                id=record["id"],
                memo_date=date.fromisoformat(record["memo_date"]),
                content=record["content"],
                updated_at=parse_utc_datetime(record["updated_at"]),
            )
            for record in data["daily_memos"]
        ]
    )
    db.add_all(
        [
            TimeEntry(
                id=record["id"],
                entry_date=date.fromisoformat(record["entry_date"]),
                category=record["category"],
                minutes=record["minutes"],
                note=record["note"],
                created_at=parse_utc_datetime(record["created_at"]),
            )
            for record in data["time_entries"]
        ]
    )
    db.add_all(
        [
            Habit(
                id=record["id"],
                name=record["name"],
                is_active=record["is_active"],
                archived_at=parse_optional_utc_datetime(record["archived_at"]),
                created_at=parse_utc_datetime(record["created_at"]),
                updated_at=parse_utc_datetime(record["updated_at"]),
            )
            for record in data["habits"]
        ]
    )
    db.flush()
    db.add_all(
        [
            HabitActivePeriod(
                id=record["id"],
                habit_id=record["habit_id"],
                started_on=date.fromisoformat(record["started_on"]),
                ended_on=(
                    date.fromisoformat(record["ended_on"])
                    if record["ended_on"] is not None
                    else None
                ),
                created_at=parse_utc_datetime(record["created_at"]),
            )
            for record in data["habit_active_periods"]
        ]
    )
    db.add_all(
        [
            HabitSchedulePeriod(
                id=record["id"],
                habit_id=record["habit_id"],
                schedule_type=record["schedule_type"],
                weekdays_mask=weekdays_to_mask(record["weekdays"]),
                started_on=date.fromisoformat(record["started_on"]),
                ended_on=(
                    date.fromisoformat(record["ended_on"])
                    if record["ended_on"] is not None
                    else None
                ),
                created_at=parse_utc_datetime(record["created_at"]),
            )
            for record in data["habit_schedule_periods"]
        ]
    )
    db.add_all(
        [
            HabitCompletion(
                id=record["id"],
                habit_id=record["habit_id"],
                completed_on=date.fromisoformat(record["completed_on"]),
                created_at=parse_utc_datetime(record["created_at"]),
            )
            for record in data["habit_completions"]
        ]
    )


def verify_temporary_database(engine: Engine, expected_payload: dict[str, Any]) -> None:
    with engine.connect() as connection:
        foreign_key_errors = connection.execute(text("PRAGMA foreign_key_check")).all()
        if foreign_key_errors:
            raise RuntimeError(
                "復元後DBの外部キー整合性確認に失敗しました: "
                + repr(foreign_key_errors[:5])
            )
        integrity = connection.scalar(text("PRAGMA integrity_check"))
        if integrity != "ok":
            raise RuntimeError(f"復元後DBの整合性確認に失敗しました: {integrity}")

    session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    exported_at = parse_utc_datetime(expected_payload["exported_at"]).replace(
        tzinfo=timezone.utc
    )
    with session_factory() as db:
        restored_payload = build_backup_payload(db, exported_at=exported_at)
    errors = validate_backup_payload(restored_payload)
    if errors:
        raise RuntimeError(
            "復元後データの検証に失敗しました。\n"
            + "\n".join(f"- {error}" for error in errors)
        )
    if restored_payload["record_counts"] != expected_payload["record_counts"]:
        raise RuntimeError("復元後のレコード件数がバックアップと一致しません。")
    if restored_payload["data"] != expected_payload["data"]:
        raise RuntimeError("復元後のデータがバックアップと一致しません。")


def build_temporary_database(temporary_path: Path, payload: dict[str, Any]) -> None:
    engine = create_sqlite_engine(temporary_path)
    try:
        Base.metadata.create_all(bind=engine)
        session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
        with session_factory() as db:
            with db.begin():
                insert_normalized_payload(db, payload)
        verify_temporary_database(engine, payload)
    finally:
        engine.dispose()


def create_safety_copy(
    database_path: Path,
    *,
    created_at: datetime | None = None,
) -> Path:
    safety_copy = default_safety_copy_path(database_path, created_at=created_at)
    shutil.copy2(database_path, safety_copy)
    fsync_file(safety_copy)
    try:
        safety_copy.chmod(0o600)
    except OSError:
        pass
    return safety_copy


def restore_backup_file(
    backup_path: Path,
    database_path: Path,
    *,
    expected_sha256: str | None = None,
    restored_at: datetime | None = None,
) -> RestoreResult:
    source = backup_path.expanduser().resolve()
    destination_input = database_path.expanduser()
    if destination_input.is_symlink():
        raise BackupRestoreInputError(
            f"復元先にシンボリックリンクは指定できません: {destination_input}"
        )
    destination = destination_input.resolve()
    if source == destination:
        raise BackupRestoreInputError(
            "バックアップファイル自身を復元先DBには指定できません。"
        )

    normalized, digest, source_schema_version = prepare_backup_for_restore(
        source,
        expected_sha256=expected_sha256,
    )
    destination_existed = inspect_restore_destination(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)

    descriptor, temporary_name = tempfile.mkstemp(
        dir=destination.parent,
        prefix=f".{destination.name}.restore-",
        suffix=".tmp",
    )
    os.close(descriptor)
    temporary_path = Path(temporary_name)
    safety_copy_path: Path | None = None
    try:
        build_temporary_database(temporary_path, normalized)
        fsync_file(temporary_path)
        if destination_existed:
            safety_copy_path = create_safety_copy(destination, created_at=restored_at)
        os.replace(temporary_path, destination)
        try:
            destination.chmod(0o600)
        except OSError:
            pass
        fsync_file(destination)
        fsync_directory(destination.parent)
    finally:
        temporary_path.unlink(missing_ok=True)

    return RestoreResult(
        database_path=destination,
        source_sha256=digest,
        source_schema_version=source_schema_version,
        record_counts=normalized["record_counts"],
        safety_copy_path=safety_copy_path,
    )


def format_record_summary(record_counts: dict[str, int]) -> str:
    return (
        f"ToDo={record_counts['tasks']}、"
        f"メモ={record_counts['daily_memos']}、"
        f"時間記録={record_counts['time_entries']}、"
        f"習慣={record_counts['habits']}、"
        f"習慣有効期間={record_counts['habit_active_periods']}、"
        f"曜日設定期間={record_counts['habit_schedule_periods']}、"
        f"習慣達成={record_counts['habit_completions']}"
    )


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "検証済みのHome Panel JSONバックアップを、"
            "未作成または空のSQLite DBへ安全に復元します。"
        )
    )
    parser.add_argument("backup", type=Path, help="復元するJSONバックアップファイル")
    parser.add_argument(
        "--database",
        type=Path,
        default=Path("home_panel.db"),
        help="復元先SQLiteファイル（既定: home_panel.db）",
    )
    parser.add_argument(
        "--expected-sha256",
        help="既知のSHA-256（64桁の16進数）とファイル内容を照合する",
    )
    return parser


def run_cli(args: Sequence[str] | None = None) -> int:
    options = create_parser().parse_args(args)
    try:
        result = restore_backup_file(
            options.backup,
            options.database,
            expected_sha256=options.expected_sha256,
        )
    except (BackupInputError, BackupRestoreInputError) as exc:
        print(f"バックアップを復元できません: {exc}", file=sys.stderr)
        return 2
    except (OSError, SQLAlchemyError, RuntimeError) as exc:
        print(f"バックアップの復元に失敗しました: {exc}", file=sys.stderr)
        return 1

    print(f"バックアップを復元しました: {result.database_path}")
    print(f"入力スキーマ: v{result.source_schema_version}")
    print(f"レコード件数: {format_record_summary(result.record_counts)}")
    print(f"SHA-256: {result.source_sha256}")
    if result.safety_copy_path is not None:
        print(f"復元前DBの退避先: {result.safety_copy_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(run_cli())
