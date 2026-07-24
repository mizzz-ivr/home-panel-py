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

from app.models.memo import DailyMemo
from app.models.task import Task
from app.models.time_entry import TimeEntry

BACKUP_SCHEMA_VERSION = 1
REQUIRED_TABLES = {"tasks", "daily_memos", "time_entries"}


def format_datetime(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    else:
        value = value.astimezone(timezone.utc)
    return value.isoformat().replace("+00:00", "Z")


def build_backup_payload(db: Session, exported_at: datetime | None = None) -> dict[str, Any]:
    export_time = exported_at or datetime.now(timezone.utc)
    tasks = list(db.scalars(select(Task).order_by(Task.id.asc())).all())
    memos = list(db.scalars(select(DailyMemo).order_by(DailyMemo.memo_date.asc(), DailyMemo.id.asc())).all())
    entries = list(
        db.scalars(
            select(TimeEntry).order_by(
                TimeEntry.entry_date.asc(),
                TimeEntry.created_at.asc(),
                TimeEntry.id.asc(),
            )
        ).all()
    )

    return {
        "schema_version": BACKUP_SCHEMA_VERSION,
        "application": "home-panel-py",
        "exported_at": format_datetime(export_time),
        "record_counts": {
            "tasks": len(tasks),
            "daily_memos": len(memos),
            "time_entries": len(entries),
        },
        "data": {
            "tasks": [
                {
                    "id": task.id,
                    "title": task.title,
                    "is_done": task.is_done,
                    "created_at": format_datetime(task.created_at),
                    "updated_at": format_datetime(task.updated_at),
                }
                for task in tasks
            ],
            "daily_memos": [
                {
                    "id": memo.id,
                    "memo_date": memo.memo_date.isoformat(),
                    "content": memo.content,
                    "updated_at": format_datetime(memo.updated_at),
                }
                for memo in memos
            ],
            "time_entries": [
                {
                    "id": entry.id,
                    "entry_date": entry.entry_date.isoformat(),
                    "category": entry.category,
                    "minutes": entry.minutes,
                    "note": entry.note,
                    "created_at": format_datetime(entry.created_at),
                }
                for entry in entries
            ],
        },
    }


def default_output_path(exported_at: datetime | None = None) -> Path:
    export_time = exported_at or datetime.now(timezone.utc)
    timestamp = export_time.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return Path.home() / "HomePanelBackups" / f"home-panel-backup-{timestamp}.json"


def write_backup_file(
    db: Session,
    output_path: Path,
    *,
    exported_at: datetime | None = None,
    overwrite: bool = False,
) -> Path:
    destination = output_path.expanduser().resolve()
    if destination.exists() and not overwrite:
        raise FileExistsError(f"出力先が既に存在します: {destination}")

    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = build_backup_payload(db, exported_at=exported_at)
    serialized = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"

    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            dir=destination.parent,
            prefix=f".{destination.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary_file:
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
    parser.add_argument(
        "--database",
        type=Path,
        default=Path("home_panel.db"),
        help="バックアップ対象のSQLiteファイル（既定: home_panel.db）",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="出力先JSONファイル（未指定時はホームディレクトリのHomePanelBackupsへ作成）",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="出力先が存在する場合に上書きする",
    )
    return parser


def run_cli(args: Sequence[str] | None = None) -> int:
    options = create_parser().parse_args(args)
    database_path = options.database.expanduser().resolve()
    if not database_path.is_file():
        print(f"バックアップ対象のDBが見つかりません: {database_path}", file=sys.stderr)
        return 2

    engine = create_engine(
        f"sqlite:///{database_path.as_posix()}",
        connect_args={"check_same_thread": False},
    )
    try:
        missing_tables = REQUIRED_TABLES - set(inspect(engine).get_table_names())
    except SQLAlchemyError as exc:
        print(f"バックアップ対象のDBを確認できません: {exc}", file=sys.stderr)
        engine.dispose()
        return 1

    if missing_tables:
        print(
            "必要なテーブルが不足しています: " + ", ".join(sorted(missing_tables)),
            file=sys.stderr,
        )
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
            destination = write_backup_file(
                db,
                output_path,
                exported_at=exported_at,
                overwrite=options.force,
            )
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
