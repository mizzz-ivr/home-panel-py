import copy
from datetime import date, datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import sessionmaker

from app.backup_validate import validate_backup_payload
from app.crud import habit as habit_crud
from app.db import Base
from app.habit_report import build_period_report
from app.migrations import migrate_habit_schema
from app.models.habit import HabitActivePeriod, HabitCompletion


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


def test_create_archive_and_restore_manage_active_periods(session):
    habit = habit_crud.create_habit(session, "読書", started_on=date(2026, 7, 1))

    assert habit_crud.archive_habit(session, habit.id, archived_on=date(2026, 7, 3)) is True
    assert habit_crud.restore_habit(session, habit.id, restored_on=date(2026, 7, 6)) is True
    assert habit_crud.archive_habit(session, habit.id, archived_on=date(2026, 7, 7)) is True

    periods = list(
        session.scalars(
            select(HabitActivePeriod).order_by(HabitActivePeriod.started_on.asc())
        ).all()
    )
    assert [(period.started_on, period.ended_on) for period in periods] == [
        (date(2026, 7, 1), date(2026, 7, 3)),
        (date(2026, 7, 6), date(2026, 7, 7)),
    ]


def test_same_day_archive_and_restore_reopens_existing_period(session):
    habit = habit_crud.create_habit(session, "運動", started_on=date(2026, 7, 10))

    assert habit_crud.archive_habit(session, habit.id, archived_on=date(2026, 7, 10)) is True
    assert habit_crud.restore_habit(session, habit.id, restored_on=date(2026, 7, 10)) is True

    periods = habit_crud.list_active_periods(session)
    assert len(periods) == 1
    assert periods[0].started_on == date(2026, 7, 10)
    assert periods[0].ended_on is None


def test_period_report_excludes_paused_days_from_denominator(session):
    habit = habit_crud.create_habit(session, "学習", started_on=date(2026, 7, 1))
    habit_crud.archive_habit(session, habit.id, archived_on=date(2026, 7, 3))
    habit_crud.restore_habit(session, habit.id, restored_on=date(2026, 7, 6))
    habit_crud.archive_habit(session, habit.id, archived_on=date(2026, 7, 7))
    session.add_all(
        [
            HabitCompletion(habit_id=habit.id, completed_on=date(2026, 7, 1)),
            HabitCompletion(habit_id=habit.id, completed_on=date(2026, 7, 2)),
            HabitCompletion(habit_id=habit.id, completed_on=date(2026, 7, 6)),
            HabitCompletion(habit_id=habit.id, completed_on=date(2026, 7, 7)),
        ]
    )
    session.commit()

    report = build_period_report(
        session,
        date(2026, 7, 1),
        date(2026, 7, 7),
        date(2026, 7, 7),
    )

    assert report["total_expected"] == 5
    assert report["total_completed"] == 4
    assert report["achievement_rate"] == 80
    assert report["habit_summaries"][0]["expected_days"] == 5
    assert report["habit_summaries"][0]["active_period_count"] == 2
    by_date = {item["date"]: item for item in report["daily_summaries"]}
    assert by_date[date(2026, 7, 4)]["expected_count"] == 0
    assert by_date[date(2026, 7, 5)]["expected_count"] == 0


def test_migration_backfills_periods_and_is_idempotent(tmp_path: Path):
    engine = create_engine(f"sqlite:///{tmp_path / 'legacy.db'}")
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE habits ("
                "id INTEGER PRIMARY KEY, name VARCHAR(100) NOT NULL, "
                "is_active BOOLEAN NOT NULL, created_at DATETIME NOT NULL, "
                "updated_at DATETIME NOT NULL)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO habits VALUES "
                "(1, '利用中', 1, '2026-07-01 00:00:00', '2026-07-01 00:00:00'),"
                "(2, '終了済み', 0, '2026-07-02 00:00:00', '2026-07-09 00:00:00')"
            )
        )

    first = migrate_habit_schema(engine)
    second = migrate_habit_schema(engine)

    assert first == {"archived_at_added": True, "active_periods_created": True}
    assert second == {"archived_at_added": False, "active_periods_created": False}
    with engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT habit_id, started_on, ended_on "
                "FROM habit_active_periods ORDER BY habit_id"
            )
        ).all()
    engine.dispose()

    assert [(row[0], str(row[1]), str(row[2]) if row[2] is not None else None) for row in rows] == [
        (1, "2026-07-01", None),
        (2, "2026-07-02", "2026-07-09"),
    ]


def valid_v4_payload() -> dict:
    return {
        "schema_version": 4,
        "application": "home-panel-py",
        "exported_at": "2026-07-28T00:00:00Z",
        "record_counts": {
            "tasks": 0,
            "daily_memos": 0,
            "time_entries": 0,
            "habits": 1,
            "habit_active_periods": 1,
            "habit_completions": 1,
        },
        "data": {
            "tasks": [],
            "daily_memos": [],
            "time_entries": [],
            "habits": [
                {
                    "id": 1,
                    "name": "毎日読書",
                    "is_active": True,
                    "archived_at": None,
                    "created_at": "2026-07-01T00:00:00Z",
                    "updated_at": "2026-07-01T00:00:00Z",
                }
            ],
            "habit_active_periods": [
                {
                    "id": 1,
                    "habit_id": 1,
                    "started_on": "2026-07-01",
                    "ended_on": None,
                    "created_at": "2026-07-01T00:00:00Z",
                }
            ],
            "habit_completions": [
                {
                    "id": 1,
                    "habit_id": 1,
                    "completed_on": "2026-07-02",
                    "created_at": "2026-07-02T00:00:00Z",
                }
            ],
        },
    }


def test_backup_v4_accepts_consistent_active_periods():
    assert validate_backup_payload(valid_v4_payload()) == []


def test_backup_v4_rejects_overlapping_periods():
    payload = valid_v4_payload()
    payload["data"]["habit_active_periods"][0]["ended_on"] = "2026-07-05"
    payload["data"]["habit_active_periods"].append(
        {
            "id": 2,
            "habit_id": 1,
            "started_on": "2026-07-05",
            "ended_on": None,
            "created_at": "2026-07-05T00:00:00Z",
        }
    )
    payload["record_counts"]["habit_active_periods"] = 2

    errors = validate_backup_payload(payload)

    assert any("有効期間が重複" in error for error in errors)


def test_backup_v4_rejects_completion_outside_active_period():
    payload = copy.deepcopy(valid_v4_payload())
    payload["data"]["habit_active_periods"][0]["started_on"] = "2026-07-03"

    errors = validate_backup_payload(payload)

    assert any("有効期間外の達成記録" in error for error in errors)


def test_backup_v4_rejects_active_habit_without_open_period():
    payload = valid_v4_payload()
    payload["data"]["habit_active_periods"][0]["ended_on"] = "2026-07-10"

    errors = validate_backup_payload(payload)

    assert any("開放中の有効期間が1件必要" in error for error in errors)
