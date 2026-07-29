import json
from datetime import date, datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.backup_export import (
    build_backup_payload,
    default_output_path,
    run_cli,
    write_backup_file,
)
from app.db import Base
from app.models.habit import (
    Habit,
    HabitActivePeriod,
    HabitCompletion,
    HabitSchedulePeriod,
)
from app.models.memo import DailyMemo
from app.models.task import Task
from app.models.time_entry import TimeEntry


@pytest.fixture()
def session(tmp_path: Path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'test.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    with session_factory() as db:
        yield db
    engine.dispose()


def test_build_backup_payload_contains_all_tables_and_counts(session):
    created_at = datetime(2026, 7, 24, 1, 2, 3)
    archived_at = datetime(2026, 7, 24, 3, 0, 0)
    session.add(
        Task(
            title="日本語タスク",
            is_done=True,
            created_at=created_at,
            updated_at=created_at,
        )
    )
    session.add(
        DailyMemo(
            memo_date=date(2026, 7, 23),
            content="メモ内容",
            updated_at=created_at,
        )
    )
    session.add(
        TimeEntry(
            entry_date=date(2026, 7, 23),
            category="個人開発",
            minutes=90,
            note="API実装",
            created_at=created_at,
        )
    )
    habit = Habit(
        name="平日読書",
        is_active=False,
        archived_at=archived_at,
        created_at=created_at,
        updated_at=archived_at,
    )
    session.add(habit)
    session.flush()
    session.add(
        HabitActivePeriod(
            habit_id=habit.id,
            started_on=date(2026, 7, 1),
            ended_on=date(2026, 7, 24),
            created_at=created_at,
        )
    )
    session.add(
        HabitSchedulePeriod(
            habit_id=habit.id,
            schedule_type="weekdays",
            weekdays_mask=31,
            started_on=date(2026, 7, 1),
            created_at=created_at,
        )
    )
    session.add(
        HabitCompletion(
            habit_id=habit.id,
            completed_on=date(2026, 7, 23),
            created_at=created_at,
        )
    )
    session.commit()

    payload = build_backup_payload(
        session,
        exported_at=datetime(2026, 7, 24, 4, 5, 6, tzinfo=timezone.utc),
    )

    assert payload["schema_version"] == 5
    assert payload["application"] == "home-panel-py"
    assert payload["exported_at"] == "2026-07-24T04:05:06Z"
    assert payload["record_counts"] == {
        "tasks": 1,
        "daily_memos": 1,
        "time_entries": 1,
        "habits": 1,
        "habit_active_periods": 1,
        "habit_schedule_periods": 1,
        "habit_completions": 1,
    }
    assert payload["data"]["tasks"][0]["title"] == "日本語タスク"
    assert payload["data"]["daily_memos"][0]["memo_date"] == "2026-07-23"
    assert payload["data"]["time_entries"][0]["category"] == "個人開発"
    assert payload["data"]["habits"][0]["name"] == "平日読書"
    assert payload["data"]["habits"][0]["is_active"] is False
    assert payload["data"]["habits"][0]["archived_at"] == "2026-07-24T03:00:00Z"
    assert payload["data"]["habit_active_periods"][0]["started_on"] == "2026-07-01"
    assert payload["data"]["habit_active_periods"][0]["ended_on"] == "2026-07-24"
    assert payload["data"]["habit_schedule_periods"][0]["schedule_type"] == "weekdays"
    assert payload["data"]["habit_schedule_periods"][0]["weekdays"] == [0, 1, 2, 3, 4]
    assert payload["data"]["habit_completions"][0]["habit_id"] == habit.id


def test_build_backup_payload_is_deterministically_ordered(session):
    stamp = datetime(2026, 7, 24, 0, 0, 0)
    session.add_all(
        [
            TimeEntry(
                entry_date=date(2026, 7, 24),
                category="作業",
                minutes=20,
                note="後",
                created_at=stamp,
            ),
            TimeEntry(
                entry_date=date(2026, 7, 23),
                category="学習",
                minutes=10,
                note="先",
                created_at=stamp,
            ),
        ]
    )
    habit = Habit(name="習慣", created_at=stamp, updated_at=stamp)
    session.add(habit)
    session.flush()
    session.add_all(
        [
            HabitActivePeriod(
                habit_id=habit.id,
                started_on=date(2026, 7, 20),
                created_at=stamp,
            ),
            HabitActivePeriod(
                habit_id=habit.id,
                started_on=date(2026, 7, 1),
                ended_on=date(2026, 7, 10),
                created_at=stamp,
            ),
            HabitSchedulePeriod(
                habit_id=habit.id,
                schedule_type="weekdays",
                weekdays_mask=31,
                started_on=date(2026, 7, 20),
                created_at=stamp,
            ),
            HabitSchedulePeriod(
                habit_id=habit.id,
                schedule_type="weekdays",
                weekdays_mask=127,
                started_on=date(2026, 7, 1),
                ended_on=date(2026, 7, 19),
                created_at=stamp,
            ),
            HabitCompletion(
                habit_id=habit.id,
                completed_on=date(2026, 7, 24),
                created_at=stamp,
            ),
            HabitCompletion(
                habit_id=habit.id,
                completed_on=date(2026, 7, 23),
                created_at=stamp,
            ),
        ]
    )
    session.commit()

    payload = build_backup_payload(session)

    assert [item["entry_date"] for item in payload["data"]["time_entries"]] == [
        "2026-07-23",
        "2026-07-24",
    ]
    assert [item["started_on"] for item in payload["data"]["habit_active_periods"]] == [
        "2026-07-01",
        "2026-07-20",
    ]
    assert [
        item["started_on"] for item in payload["data"]["habit_schedule_periods"]
    ] == ["2026-07-01", "2026-07-20"]
    assert [item["completed_on"] for item in payload["data"]["habit_completions"]] == [
        "2026-07-23",
        "2026-07-24",
    ]
    assert payload["data"]["habits"][0]["archived_at"] is None


def test_build_backup_payload_handles_empty_database(session):
    payload = build_backup_payload(session)

    assert payload["record_counts"] == {
        "tasks": 0,
        "daily_memos": 0,
        "time_entries": 0,
        "habits": 0,
        "habit_active_periods": 0,
        "habit_schedule_periods": 0,
        "habit_completions": 0,
    }
    assert payload["data"] == {
        "tasks": [],
        "daily_memos": [],
        "time_entries": [],
        "habits": [],
        "habit_active_periods": [],
        "habit_schedule_periods": [],
        "habit_completions": [],
    }


def test_write_backup_file_writes_utf8_json_atomically(session, tmp_path: Path):
    session.add(Task(title="バックアップ対象"))
    session.commit()
    output = tmp_path / "nested" / "backup.json"

    result = write_backup_file(
        session,
        output,
        exported_at=datetime(2026, 7, 24, 0, 0, tzinfo=timezone.utc),
    )

    assert result == output.resolve()
    content = output.read_text(encoding="utf-8")
    assert content.endswith("\n")
    parsed = json.loads(content)
    assert parsed["data"]["tasks"][0]["title"] == "バックアップ対象"
    assert not list(output.parent.glob("*.tmp"))


def test_write_backup_file_refuses_overwrite_without_force(session, tmp_path: Path):
    output = tmp_path / "backup.json"
    output.write_text("existing", encoding="utf-8")

    with pytest.raises(FileExistsError):
        write_backup_file(session, output)

    assert output.read_text(encoding="utf-8") == "existing"


def test_write_backup_file_overwrites_with_force(session, tmp_path: Path):
    output = tmp_path / "backup.json"
    output.write_text("existing", encoding="utf-8")

    write_backup_file(session, output, overwrite=True)

    assert json.loads(output.read_text(encoding="utf-8"))["schema_version"] == 5


def test_default_output_path_uses_utc_timestamp():
    output = default_output_path(
        datetime(2026, 7, 24, 12, 34, 56, tzinfo=timezone.utc)
    )

    assert (
        output
        == Path.home()
        / "HomePanelBackups"
        / "home-panel-backup-20260724T123456Z.json"
    )


def test_run_cli_rejects_missing_database(tmp_path: Path, capsys):
    result = run_cli(["--database", str(tmp_path / "missing.db")])

    assert result == 2
    assert "DBが見つかりません" in capsys.readouterr().err


def test_run_cli_rejects_database_with_missing_tables(tmp_path: Path, capsys):
    database = tmp_path / "invalid.db"
    engine = create_engine(f"sqlite:///{database}")
    with engine.connect():
        pass
    engine.dispose()

    result = run_cli(["--database", str(database)])

    assert result == 2
    assert "必要なテーブルが不足しています" in capsys.readouterr().err


def test_run_cli_handles_corrupted_database(tmp_path: Path, capsys):
    database = tmp_path / "corrupted.db"
    database.write_text("not a sqlite database", encoding="utf-8")

    result = run_cli(["--database", str(database)])

    assert result == 1
    assert "DBを確認できません" in capsys.readouterr().err


def test_run_cli_rejects_database_as_output_path(tmp_path: Path, capsys):
    database = tmp_path / "source.db"
    engine = create_engine(
        f"sqlite:///{database}", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(bind=engine)
    engine.dispose()

    result = run_cli(
        ["--database", str(database), "--output", str(database), "--force"]
    )

    assert result == 2
    assert "DB本体は指定できません" in capsys.readouterr().err
    assert database.exists()


def test_run_cli_creates_backup_from_specified_database(tmp_path: Path, capsys):
    database = tmp_path / "source.db"
    engine = create_engine(
        f"sqlite:///{database}", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    with session_factory() as db:
        db.add(Task(title="CLIタスク"))
        db.commit()
    engine.dispose()
    output = tmp_path / "exports" / "backup.json"

    result = run_cli(["--database", str(database), "--output", str(output)])

    assert result == 0
    assert output.exists()
    assert (
        json.loads(output.read_text(encoding="utf-8"))["data"]["tasks"][0]["title"]
        == "CLIタスク"
    )
    assert "バックアップを作成しました" in capsys.readouterr().out


def test_run_cli_migrates_legacy_habits_before_export(tmp_path: Path):
    database = tmp_path / "legacy.db"
    engine = create_engine(f"sqlite:///{database}")
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE tasks (id INTEGER PRIMARY KEY, title VARCHAR(255) NOT NULL, "
                "is_done BOOLEAN NOT NULL, created_at DATETIME NOT NULL, "
                "updated_at DATETIME NOT NULL)"
            )
        )
        connection.execute(
            text(
                "CREATE TABLE daily_memos (id INTEGER PRIMARY KEY, memo_date DATE NOT NULL, "
                "content TEXT NOT NULL, updated_at DATETIME NOT NULL)"
            )
        )
        connection.execute(
            text(
                "CREATE TABLE time_entries (id INTEGER PRIMARY KEY, entry_date DATE NOT NULL, "
                "category VARCHAR(20) NOT NULL, minutes INTEGER NOT NULL, "
                "note VARCHAR(255) NOT NULL, created_at DATETIME NOT NULL)"
            )
        )
        connection.execute(
            text(
                "CREATE TABLE habits (id INTEGER PRIMARY KEY, name VARCHAR(100) NOT NULL, "
                "is_active BOOLEAN NOT NULL, created_at DATETIME NOT NULL, "
                "updated_at DATETIME NOT NULL)"
            )
        )
        connection.execute(
            text(
                "CREATE TABLE habit_completions (id INTEGER PRIMARY KEY, "
                "habit_id INTEGER NOT NULL, completed_on DATE NOT NULL, "
                "created_at DATETIME NOT NULL)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO habits VALUES "
                "(1, '旧習慣', 0, '2026-07-01 00:00:00', '2026-07-10 00:00:00')"
            )
        )
    engine.dispose()
    output = tmp_path / "legacy-backup.json"

    assert run_cli(["--database", str(database), "--output", str(output)]) == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["schema_version"] == 5
    assert payload["data"]["habits"][0]["archived_at"] == "2026-07-10T00:00:00Z"
    assert payload["data"]["habit_active_periods"][0]["started_on"] == "2026-07-01"
    assert payload["data"]["habit_active_periods"][0]["ended_on"] == "2026-07-10"
    assert payload["data"]["habit_schedule_periods"][0]["weekdays"] == [
        0,
        1,
        2,
        3,
        4,
        5,
        6,
    ]
