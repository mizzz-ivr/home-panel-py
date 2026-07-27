from datetime import date, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import habit_report_routes
from app.db import Base, get_db
from app.habit_report import build_daily_report, build_period_report, calculate_longest_streak
from app.main import app
from app.models.habit import Habit, HabitCompletion

FIXED_TODAY = date(2026, 7, 26)


class FixedDate(date):
    @classmethod
    def today(cls):
        return cls(FIXED_TODAY.year, FIXED_TODAY.month, FIXED_TODAY.day)


@pytest.fixture()
def client(tmp_path: Path, monkeypatch):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'test.db'}",
        connect_args={"check_same_thread": False},
    )
    session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    def override_get_db():
        with session_factory() as db:
            yield db

    monkeypatch.setattr(habit_report_routes, "date", FixedDate)
    app.dependency_overrides[get_db] = override_get_db
    app.state.testing_session_factory = session_factory
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
    del app.state.testing_session_factory
    engine.dispose()


def add_habit(
    client: TestClient,
    name: str,
    created_on: date,
    *,
    is_active: bool = True,
    updated_on: date | None = None,
) -> int:
    session_factory = client.app.state.testing_session_factory
    created_at = datetime.combine(created_on, datetime.min.time())
    updated_at = datetime.combine(updated_on or created_on, datetime.min.time())
    with session_factory() as db:
        habit = Habit(
            name=name,
            is_active=is_active,
            created_at=created_at,
            updated_at=updated_at,
        )
        db.add(habit)
        db.commit()
        db.refresh(habit)
        return habit.id


def add_completion(client: TestClient, habit_id: int, completed_on: date) -> None:
    session_factory = client.app.state.testing_session_factory
    with session_factory() as db:
        db.add(HabitCompletion(habit_id=habit_id, completed_on=completed_on))
        db.commit()


def test_daily_report_displays_completed_and_archived_habits(client: TestClient):
    active_id = add_habit(client, "読書", date(2026, 7, 20))
    archived_id = add_habit(
        client,
        "運動",
        date(2026, 7, 18),
        is_active=False,
        updated_on=date(2026, 7, 23),
    )
    add_completion(client, active_id, date(2026, 7, 22))
    add_completion(client, archived_id, date(2026, 7, 22))

    response = client.get("/habits/history?target_date=2026-07-22")

    assert response.status_code == 200
    assert "習慣の日別履歴" in response.text
    assert "2/2件" in response.text
    assert "100%" in response.text
    assert "読書" in response.text
    assert "運動" in response.text
    assert "終了済み" in response.text


def test_daily_report_excludes_habit_before_creation_and_after_archive(client: TestClient):
    add_habit(client, "後から開始", date(2026, 7, 23))
    add_habit(
        client,
        "終了済み",
        date(2026, 7, 18),
        is_active=False,
        updated_on=date(2026, 7, 20),
    )

    response = client.get("/habits/history?target_date=2026-07-22")

    assert response.status_code == 200
    assert "0/0件" in response.text
    assert "この日に対象となる習慣はありません" in response.text


def test_weekly_report_calculates_opportunities_rate_and_perfect_days(client: TestClient):
    reading_id = add_habit(client, "読書", date(2026, 7, 20))
    exercise_id = add_habit(client, "運動", date(2026, 7, 22))
    for completed_on in (date(2026, 7, 20), date(2026, 7, 21), date(2026, 7, 22)):
        add_completion(client, reading_id, completed_on)
    add_completion(client, exercise_id, date(2026, 7, 22))

    response = client.get("/habits/weekly?target_date=2026-07-23")

    assert response.status_code == 200
    assert "習慣の週次集計" in response.text
    assert "4/12件" in response.text
    assert "33%" in response.text
    assert "3日" in response.text
    assert "3/7日達成" in response.text
    assert "1/5日達成" in response.text
    assert "最長3日連続" in response.text


def test_period_report_stops_counting_after_archive(client: TestClient):
    habit_id = add_habit(
        client,
        "朝活",
        date(2026, 7, 20),
        is_active=False,
        updated_on=date(2026, 7, 22),
    )
    add_completion(client, habit_id, date(2026, 7, 20))
    add_completion(client, habit_id, date(2026, 7, 21))

    session_factory = client.app.state.testing_session_factory
    with session_factory() as db:
        report = build_period_report(
            db,
            date(2026, 7, 20),
            date(2026, 7, 26),
            FIXED_TODAY,
        )

    assert report["total_expected"] == 3
    assert report["total_completed"] == 2
    assert report["achievement_rate"] == 67
    assert report["habit_summaries"][0]["is_archived"] is True


def test_monthly_report_displays_calendar_and_excludes_future_days(client: TestClient):
    habit_id = add_habit(client, "日記", date(2026, 7, 25))
    add_completion(client, habit_id, date(2026, 7, 25))

    response = client.get("/habits/monthly?target_month=2026-07")

    assert response.status_code == 200
    assert "習慣の月次集計" in response.text
    assert "1/2件" in response.text
    assert "50%" in response.text
    assert "集計は07月26日まで" in response.text
    assert "未到来" in response.text
    assert 'href="/habits/history?target_date=2026-07-25"' in response.text


def test_empty_reports_render_without_division_error(client: TestClient):
    daily = client.get("/habits/history?target_date=2026-07-20")
    weekly = client.get("/habits/weekly?target_date=2026-07-20")
    monthly = client.get("/habits/monthly?target_month=2026-07")

    assert daily.status_code == 200
    assert weekly.status_code == 200
    assert monthly.status_code == 200
    assert "0/0件" in daily.text
    assert "0/0件" in weekly.text
    assert "0/0件" in monthly.text


@pytest.mark.parametrize(
    ("url", "message"),
    [
        ("/habits/history?target_date=20260720", "YYYY-MM-DD"),
        ("/habits/history?target_date=2026-02-30", "YYYY-MM-DD"),
        ("/habits/history?target_date=2026-07-27", "未来の日付"),
        ("/habits/weekly?target_date=2026-W30", "YYYY-MM-DD"),
        ("/habits/weekly?target_date=2026-07-27", "未来の日付"),
        ("/habits/monthly?target_month=202607", "YYYY-MM"),
        ("/habits/monthly?target_month=2026-13", "YYYY-MM"),
        ("/habits/monthly?target_month=2026-08", "未来の月"),
    ],
)
def test_habit_reports_reject_invalid_or_future_periods(
    client: TestClient,
    url: str,
    message: str,
):
    response = client.get(url)

    assert response.status_code == 400
    assert message in response.text


def test_longest_streak_is_limited_to_selected_period():
    completed_dates = {
        date(2026, 6, 30),
        date(2026, 7, 1),
        date(2026, 7, 2),
        date(2026, 7, 4),
    }

    assert calculate_longest_streak(
        completed_dates,
        date(2026, 7, 1),
        date(2026, 7, 5),
    ) == 2


def test_daily_report_service_uses_active_period_as_denominator(client: TestClient):
    add_habit(client, "対象", date(2026, 7, 20))
    add_habit(client, "未開始", date(2026, 7, 23))

    session_factory = client.app.state.testing_session_factory
    with session_factory() as db:
        report = build_daily_report(db, date(2026, 7, 22))

    assert report["expected_count"] == 1
    assert report["completed_count"] == 0
    assert report["achievement_rate"] == 0
