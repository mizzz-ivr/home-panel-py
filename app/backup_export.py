from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, inspect, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from app.habit_schedule import mask_to_weekdays
from app.migrations import migrate_home_panel_schema
from app.models.habit import Habit, HabitActivePeriod, HabitCompletion, HabitSchedulePeriod
from app.models.memo import DailyMemo
from app.models.task import Task
from app.models.time_entry import TimeEntry
from app.models.time_goal import DailyTimeGoalPeriod
from app.time_goal_migration import migrate_daily_time_goal_periods

BACKUP_SCHEMA_VERSION = 7
BASE_REQUIRED_TABLES = {"tasks", "daily_memos", "time_entries", "habits", "habit_completions"}
REQUIRED_TABLES = {
    *BASE_REQUIRED_TABLES,
    "habit_active_periods",
    "habit_schedule_periods",
    "daily_time_goal_periods",
}


def format_datetime(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    else:
        value = value.astimezone(timezone.utc)
    return value.isoformat().replace("+00:00", "Z")


def format_optional_datetime(value: datetime | None) -> str | None:
    return format_datetime(value) if value is not None else None


def build_backup_payload(db: Session, exported_at: datetime | None = None) -> dict[str, Any]:
    export_time = exported_at or datetime.now(timezone.utc)
    tasks = list(db.scalars(select(Task).order_by(Task.id.asc())).all())
    memos = list(db.scalars(select(DailyMemo).order_by(DailyMemo.memo_date.asc(), DailyMemo.id.asc())).all())
    entries = list(db.scalars(select(TimeEntry).order_by(TimeEntry.entry_date.asc(), TimeEntry.created_at.asc(), TimeEntry.id.asc())).all())
    goal_periods = list(
        db.scalars(
            select(DailyTimeGoalPeriod).order_by(
                DailyTimeGoalPeriod.started_on.asc(),
                DailyTimeGoalPeriod.id.asc(),
            )
        ).all()
    )
    habits = list(db.scalars(select(Habit).order_by(Habit.created_at.asc(), Habit.id.asc())).all())
    active_periods = list(db.scalars(select(HabitActivePeriod).order_by(HabitActivePeriod.habit_id.asc(), HabitActivePeriod.started_on.asc(), HabitActivePeriod.id.asc())).all())
    schedule_periods = list(db.scalars(select(HabitSchedulePeriod).order_by(HabitSchedulePeriod.habit_id.asc(), HabitSchedulePeriod.started_on.asc(), HabitSchedulePeriod.id.asc())).all())
    completions = list(db.scalars(select(HabitCompletion).order_by(HabitCompletion.completed_on.asc(), HabitCompletion.habit_id.asc(), HabitCompletion.id.asc())).all())

    data = {
        "tasks": [{
            "id": task.id,
            "title": task.title,
            "is_done": task.is_done,
            "due_date": task.due_date.isoformat() if task.due_date else None,
            "priority": task.priority,
            "created_at": format_datetime(task.created_at),
            "updated_at": format_datetime(task.updated_at),
        } for task in tasks],
        "daily_memos": [{
            "id": memo.id,
            "memo_date": memo.memo_date.isoformat(),
            "content": memo.content,
            "updated_at": format_datetime(memo.updated_at),
        } for memo in memos],
        "time_entries": [{
            "id": entry.id,
            "entry_date": entry.entry_date.isoformat(),
            "category": entry.category,
            "minutes": entry.minutes,
            "note": entry.note,
            "created_at": format_datetime(entry.created_at),
        } for entry in entries],
        "daily_time_goal_periods": [{
            "id": period.id,
            "goal_minutes": period.goal_minutes,
            "started_on": period.started_on.isoformat(),
            "ended_on": period.ended_on.isoformat() if period.ended_on else None,
            "created_at": format_datetime(period.created_at),
        } for period in goal_periods],
        "habits": [{
            "id": habit.id,
            "name": habit.name,
            "is_active": habit.is_active,
            "archived_at": format_optional_datetime(habit.archived_at),
            "created_at": format_datetime(habit.created_at),
            "updated_at": format_datetime(habit.updated_at),
        } for habit in habits],
        "habit_active_periods": [{
            "id": period.id,
            "habit_id": period.habit_id,
            "started_on": period.started_on.isoformat(),
            "ended_on": period.ended_on.isoformat() if period.ended_on else None,
            "created_at": format_datetime(period.created_at),
        } for period in active_periods],
        "habit_schedule_periods": [{
            "id": period.id,
            "habit_id": period.habit_id,
            "schedule_type": period.schedule_type,
            "weekdays": list(mask_to_weekdays(period.weekdays_mask)),
            "started_on": period.started_on.isoformat(),
            "ended_on": period.ended_on.isoformat() if period.ended_on else None,
            "created_at": format_datetime(period.created_at),
        } for period in schedule_periods],
        "habit_completions": [{
            "id": completion.id,
            "habit_id": completion.habit_id,
            "completed_on": completion.completed_on.isoformat(),
            "created_at": format_datetime(completion.created_at),
        } for completion in completions],
    }
    return {
        "schema_version": BACKUP_SCHEMA_VERSION,
        "application": "home-panel-py",
        "exported_at": format_datetime(export_time),
        "record_counts": {name: len(records) for name, records in data.items()},
        "data": data,
    }


def default_output_path(exported_at: datetime | None = None) -> Path:
    export_time = exported_at or datetime.now(timezone.utc)
    timestamp = export_time.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return Path.home() / "HomePanelBackups" / f"home-panel-backup-{timestamp}.json"


def write_backup_file(db: Session, output_path: Path, *, exported_at: datetime | None = None, overwrite: bool = False) -> Path:
    destination = output_path.expanduser().resolve()
    if destination.exists() and not overwrite:
        raise FileExistsError(f"出力先が既に存在します: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(build_backup_payload(db, exported_at=exported_at), ensure_ascii=False, indent=2) + "\n"
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="\n", dir=destination.parent, prefix=f".{destination.name}.", suffix=".tmp", delete=False) as temporary_file:
            temporary_file.write(serialized)
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
            temporary_path = Path(temporary_file.name)
        os.replace(temporary_path, destination)
        temporary_path = None
        try:
            destination.chmod(0o600)
        except OSError:
            pass
        return destination
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Home Panelの全データをJSON形式でバックアップします。")
    parser.add_argument("--database", type=Path, default=Path("home_panel.db"), help="バックアップ対象のSQLiteファイル（既定: home_panel.db）")
    parser.add_argument("--output", type=Path, help="出力先JSONファイル（未指定時はホームディレクトリのHomePanelBackupsへ作成）")
    parser.add_argument("--force", action="store_true", help="出力先が存在する場合に上書きする")
    return parser


def run_cli(args: Sequence[str] | None = None) -> int:
    options = create_parser().parse_args(args)
    database_path = options.database.expanduser().resolve()
    if not database_path.is_file():
        print(f"バックアップ対象のDBが見つかりません: {database_path}", file=sys.stderr)
        return 2
    engine = create_engine(f"sqlite:///{database_path.as_posix()}", connect_args={"check_same_thread": False})
    try:
        table_names = set(inspect(engine).get_table_names())
        missing_base_tables = BASE_REQUIRED_TABLES - table_names
        if not missing_base_tables:
            migrate_home_panel_schema(engine)
            migrate_daily_time_goal_periods(engine)
        missing_tables = REQUIRED_TABLES - set(inspect(engine).get_table_names())
    except SQLAlchemyError as exc:
        print(f"バックアップ対象のDBを確認できません: {exc}", file=sys.stderr)
        engine.dispose()
        return 1
    if missing_base_tables or missing_tables:
        missing = missing_base_tables or missing_tables
        print("必要なテーブルが不足しています: " + ", ".join(sorted(missing)), file=sys.stderr)
        engine.dispose()
        return 2

    session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    exported_at = datetime.now(timezone.utc)
    output_path = options.output or default_output_path(exported_at)
    if output_path.expanduser().resolve() == database_path:
        print("出力先にバックアップ対象のDB本体は指定できません。", file=sys.stderr)
        engine.dispose()
        return 2
    try:
        with session_factory() as db:
            destination = write_backup_file(db, output_path, exported_at=exported_at, overwrite=options.force)
    except FileExistsError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except (OSError, SQLAlchemyError) as exc:
        print(f"バックアップの作成に失敗しました: {exc}", file=sys.stderr)
        return 1
    finally:
        engine.dispose()
    print(f"バックアップを作成しました: {destination}")
    return 0


if __name__ == "__main__":
    raise SystemExit(run_cli())
