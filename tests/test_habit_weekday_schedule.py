import copy
from datetime import date, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import sessionmaker

from app.backup_validate import validate_backup_payload
from app.crud import habit as habit_crud
from app.db import Base, get_db
from app.habit_report import build_period_report
from app.habit_schedule import (
    ALL_WEEKDAYS_MASK,
    calculate_scheduled_streak,
    format_schedule,
    mask_to_weekdays,
    weekdays_to_mask,
)
from app.main import app
from app.migrations import migrate_habit_schedule_periods
from app.models.habit import HabitCompletion, HabitSchedulePeriod


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


@pytest.fixture()
def client(tmp_path: Path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'client.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    def override_get_db():
        with session_factory() as db:
            yield db

    app.dependency_overrides[get_db] = override_get_db
    app.state.testing_session_factory = session_factory
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
    del app.state.testing_session_factory
    engine.dispose()


def test_weekday_mask_conversion_and_labels():
    assert weekdays_to_mask([0, 2, 4]) == 21
    assert mask_to_weekdays(21) == (0, 2, 4)
    assert format_schedule(127) == "毎日"
    assert format_schedule(31) == "平日"
    assert format_schedule(96) == "土日"
    assert format_schedule(21) == "月・水・金"

    with pytest.raises(ValueError):
        weekdays_to_mask([])
    with pytest.raises(ValueError):
        weekdays_to_mask([7])
    with pytest.raises(ValueError):
        mask_to_weekdays(0)


def test_create_habit_creates_everyday_schedule_period(session):
    habit = habit_crud.create_habit(session, "読書", started_on=date(2026, 7, 6))

    periods = habit_crud.get_schedule_periods_for_habit(session, habit.id)
    assert len(periods) == 1
    assert periods[0].started_on == date(2026, 7, 6)
    assert periods[0].ended_on is None
    assert periods[0].weekdays_mask == ALL_WEEKDAYS_MASK


def test_schedule_change_preserves_past_period_and_same_day_update(session):
    habit = habit_crud.create_habit(session, "運動", started_on=date(2026, 7, 6))

    habit_crud.update_habit_schedule(
        session,
        habit.id,
        [0, 2, 4],
        changed_on=date(2026, 7, 9),
    )
    habit_crud.update_habit_schedule(
        session,
        habit.id,
        [1, 3],
        changed_on=date(2026, 7, 9),
    )

    periods = habit_crud.get_schedule_periods_for_habit(session, habit.id)
    assert [(period.started_on, period.ended_on, period.weekdays_mask) for period in periods] == [
        (date(2026, 7, 6), date(2026, 7, 8), 127),
        (date(2026, 7, 9), None, 10),
    ]


def test_report_excludes_non_target_weekdays_and_preserves_schedule_history(session):
    habit = habit_crud.create_habit(session, "学習", started_on=date(2026, 7, 6))
    habit_crud.update_habit_schedule(
        session,
        habit.id,
        [3],
        changed_on=date(2026, 7, 9),
    )
    session.add_all(
        [
            HabitCompletion(habit_id=habit.id, completed_on=date(2026, 7, 6)),
            HabitCompletion(habit_id=habit.id, completed_on=date(2026, 7, 7)),
            HabitCompletion(habit_id=habit.id, completed_on=date(2026, 7, 8)),
            HabitCompletion(habit_id=habit.id, completed_on=date(2026, 7, 9)),
        ]
    )
    session.commit()

    report = build_period_report(
        session,
        date(2026, 7, 6),
        date(2026, 7, 12),
        date(2026, 7, 12),
    )

    assert report["total_expected"] == 4
    assert report["total_completed"] == 4
    assert report["achievement_rate"] == 100
    summary = report["habit_summaries"][0]
    assert summary["expected_days"] == 4
    assert summary["completed_days"] == 4
    assert summary["schedule_period_count"] == 2
    by_date = {item["date"]: item for item in report["daily_summaries"]}
    assert by_date[date(2026, 7, 10)]["expected_count"] == 0
    assert by_date[date(2026, 7, 11)]["expected_count"] == 0
    assert by_date[date(2026, 7, 12)]["expected_count"] == 0


def test_scheduled_streak_ignores_non_target_calendar_days():
    expected_dates = [
        date(2026, 7, 6),
        date(2026, 7, 8),
        date(2026, 7, 10),
    ]
    completed = set(expected_dates)

    assert calculate_scheduled_streak(completed, expected_dates, date(2026, 7, 10)) == 3
    assert calculate_scheduled_streak(completed, expected_dates, date(2026, 7, 11)) == 3


def test_off_schedule_completion_is_rejected_without_mutation(session):
    habit = habit_crud.create_habit(
        session,
        "月曜のみ",
        started_on=date(2026, 7, 6),
        weekdays=(0,),
    )

    assert habit_crud.toggle_today_completion(session, habit.id, date(2026, 7, 7)) is False
    assert session.scalar(
        select(HabitCompletion).where(HabitCompletion.habit_id == habit.id)
    ) is None
    assert habit_crud.toggle_today_completion(session, habit.id, date(2026, 7, 6)) is True


def test_schedule_change_rejects_excluding_existing_completion(session):
    habit = habit_crud.create_habit(session, "読書", started_on=date(2026, 7, 6))
    session.add(HabitCompletion(habit_id=habit.id, completed_on=date(2026, 7, 9)))
    session.commit()

    with pytest.raises(habit_crud.HabitScheduleConflictError):
        habit_crud.update_habit_schedule(
            session,
            habit.id,
            [0, 1, 2, 4],
            changed_on=date(2026, 7, 9),
        )

    assert habit_crud.get_current_schedule_mask(session, habit.id, date(2026, 7, 9)) == 127


def test_management_route_updates_weekdays_and_rejects_empty_selection(client: TestClient):
    client.post("/habits", data={"name": "読書"})

    response = client.post(
        "/habits/1/schedule",
        data={"weekdays": ["0", "2", "4"]},
        follow_redirects=False,
    )
    assert response.status_code == 303

    management = client.get("/habits/manage")
    assert management.status_code == 200
    assert "現在: 月・水・金" in management.text
    assert 'value="0"' in management.text

    invalid = client.post("/habits/1/schedule", data={})
    assert invalid.status_code == 400
    assert "1つ以上選択" in invalid.text


def test_migration_backfills_everyday_schedule_and_is_idempotent(tmp_path: Path):
    engine = create_engine(f"sqlite:///{tmp_path / 'legacy.db'}")
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE habits ("
                "id INTEGER PRIMARY KEY, name VARCHAR(100) NOT NULL, "
                "is_active BOOLEAN NOT NULL, archived_at DATETIME NULL, "
                "created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO habits VALUES "
                "(1, '旧習慣', 1, NULL, '2026-07-01 00:00:00', '2026-07-01 00:00:00')"
            )
        )

    assert migrate_habit_schedule_periods(engine) is True
    assert migrate_habit_schedule_periods(engine) is False

    with engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT habit_id, schedule_type, weekdays_mask, started_on, ended_on "
                "FROM habit_schedule_periods"
            )
        ).all()
    engine.dispose()

    assert [(row[0], row[1], row[2], str(row[3]), row[4]) for row in rows] == [
        (1, "weekdays", 127, "2026-07-01", None)
    ]


def valid_v5_payload() -> dict:
    return {
        "schema_version": 5,
        "application": "home-panel-py",
        "exported_at": "2026-07-28T00:00:00Z",
        "record_counts": {
            "tasks": 0,
            "daily_memos": 0,
            "time_entries": 0,
            "habits": 1,
            "habit_active_periods": 1,
            "habit_schedule_periods": 1,
            "habit_completions": 1,
        },
        "data": {
            "tasks": [],
            "daily_memos": [],
            "time_entries": [],
            "habits": [
                {
                    "id": 1,
                    "name": "平日読書",
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
            "habit_schedule_periods": [
                {
                    "id": 1,
                    "habit_id": 1,
                    "schedule_type": "weekdays",
                    "weekdays": [0, 1, 2, 3, 4],
                    "started_on": "2026-07-01",
                    "ended_on": None,
                    "created_at": "2026-07-01T00:00:00Z",
                }
            ],
            "habit_completions": [
                {
                    "id": 1,
                    "habit_id": 1,
                    "completed_on": "2026-07-06",
                    "created_at": "2026-07-06T00:00:00Z",
                }
            ],
        },
    }


def test_backup_v5_accepts_consistent_schedule_periods():
    assert validate_backup_payload(valid_v5_payload()) == []


@pytest.mark.parametrize(
    ("weekdays", "expected"),
    [
        ([], "1つ以上"),
        ([0, 0], "重複"),
        ([7], "0〜6"),
        ([True], "0〜6"),
    ],
)
def test_backup_v5_rejects_invalid_weekdays(weekdays, expected):
    payload = valid_v5_payload()
    payload["data"]["habit_schedule_periods"][0]["weekdays"] = weekdays

    assert any(expected in error for error in validate_backup_payload(payload))


def test_backup_v5_rejects_overlapping_schedule_periods():
    payload = valid_v5_payload()
    payload["data"]["habit_schedule_periods"][0]["ended_on"] = "2026-07-10"
    payload["data"]["habit_schedule_periods"].append(
        {
            "id": 2,
            "habit_id": 1,
            "schedule_type": "weekdays",
            "weekdays": [5, 6],
            "started_on": "2026-07-10",
            "ended_on": None,
            "created_at": "2026-07-10T00:00:00Z",
        }
    )
    payload["record_counts"]["habit_schedule_periods"] = 2

    assert any("曜日設定期間が重複" in error for error in validate_backup_payload(payload))


def test_backup_v5_rejects_completion_on_non_target_weekday():
    payload = copy.deepcopy(valid_v5_payload())
    payload["data"]["habit_completions"][0]["completed_on"] = "2026-07-05"

    assert any("対象曜日外の達成記録" in error for error in validate_backup_payload(payload))
