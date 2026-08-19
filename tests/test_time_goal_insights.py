from datetime import date, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.crud import time_entry as time_entry_crud
from app.db import Base, get_db
from app.main import app
from app.models.time_goal import DailyTimeGoalPeriod
from app.time_goal import save_daily_time_goal
from app.time_goal_insights import (
    achievement_query_start,
    build_time_goal_achievement_insights,
    calculate_goal_achievement_streak,
)


@pytest.fixture()
def client(tmp_path: Path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'test.db'}",
        connect_args={"check_same_thread": False},
    )
    session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    def override_get_db():
        with session_factory() as db:
            yield db

    app.dependency_overrides[get_db] = override_get_db
    app.state.time_goal_insights_session_factory = session_factory
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
    del app.state.time_goal_insights_session_factory
    engine.dispose()


def period(
    goal_minutes: int,
    started_on: date,
    ended_on: date | None = None,
    *,
    period_id: int = 1,
) -> DailyTimeGoalPeriod:
    return DailyTimeGoalPeriod(
        id=period_id,
        goal_minutes=goal_minutes,
        started_on=started_on,
        ended_on=ended_on,
    )


def test_achievement_insights_use_goal_value_for_each_date():
    today = date(2026, 8, 17)
    periods = (
        period(60, date(2026, 8, 11), date(2026, 8, 13), period_id=1),
        period(120, date(2026, 8, 14), None, period_id=2),
    )
    daily_totals = {
        date(2026, 8, 11): 60,
        date(2026, 8, 12): 30,
        date(2026, 8, 13): 80,
        date(2026, 8, 14): 120,
        date(2026, 8, 15): 150,
        date(2026, 8, 16): 120,
        today: 60,
    }

    insights = build_time_goal_achievement_insights(
        today=today,
        periods=periods,
        daily_totals=daily_totals,
    )

    assert insights.configured_days == 7
    assert insights.achieved_days == 5
    assert insights.achievement_rate == 71
    assert insights.streak_days == 4
    assert insights.days[0].goal_minutes == 60
    assert insights.days[0].achieved is True
    assert insights.days[1].percentage == 50
    assert insights.days[-1].goal_minutes == 120
    assert insights.days[-1].achieved is False


def test_unconfigured_days_are_excluded_from_achievement_rate():
    today = date(2026, 8, 17)
    periods = (period(60, date(2026, 8, 15), None),)

    insights = build_time_goal_achievement_insights(
        today=today,
        periods=periods,
        daily_totals={date(2026, 8, 15): 60, date(2026, 8, 16): 30, today: 60},
    )

    assert insights.configured_days == 3
    assert insights.achieved_days == 2
    assert insights.achievement_rate == 67
    assert insights.days[0].configured is False


def test_no_goal_history_has_no_achievement_rate_or_streak():
    today = date(2026, 8, 17)

    insights = build_time_goal_achievement_insights(
        today=today,
        periods=(),
        daily_totals={today: 120},
    )

    assert insights.has_goals is False
    assert insights.configured_days == 0
    assert insights.achieved_days == 0
    assert insights.achievement_rate is None
    assert insights.streak_days == 0


def test_streak_keeps_yesterday_achievement_until_today_is_achieved():
    today = date(2026, 8, 17)
    periods = (period(60, date(2026, 8, 10), None),)
    daily_totals = {
        today - timedelta(days=1): 60,
        today - timedelta(days=2): 90,
        today - timedelta(days=3): 60,
        today: 30,
    }

    assert calculate_goal_achievement_streak(periods, daily_totals, today) == 3


def test_streak_includes_today_after_goal_is_achieved():
    today = date(2026, 8, 17)
    periods = (period(60, date(2026, 8, 10), None),)
    daily_totals = {
        today - timedelta(days=1): 60,
        today - timedelta(days=2): 90,
        today: 60,
    }

    assert calculate_goal_achievement_streak(periods, daily_totals, today) == 3


def test_unconfigured_day_breaks_goal_achievement_streak():
    today = date(2026, 8, 17)
    periods = (
        period(60, date(2026, 8, 11), date(2026, 8, 13), period_id=1),
        period(60, date(2026, 8, 15), None, period_id=2),
    )
    daily_totals = {
        date(2026, 8, 13): 60,
        date(2026, 8, 15): 60,
        date(2026, 8, 16): 60,
        today: 60,
    }

    assert calculate_goal_achievement_streak(periods, daily_totals, today) == 3
    assert achievement_query_start(periods, today) == date(2026, 8, 15)


def test_query_start_reaches_before_seven_days_for_long_streak():
    today = date(2026, 8, 17)
    periods = (
        period(60, date(2026, 7, 1), date(2026, 7, 31), period_id=1),
        period(90, date(2026, 8, 1), None, period_id=2),
    )

    assert achievement_query_start(periods, today) == date(2026, 7, 1)


def test_overlapping_goal_periods_fail_closed_for_affected_dates():
    today = date(2026, 8, 17)
    periods = (
        period(60, date(2026, 8, 10), None, period_id=1),
        period(90, date(2026, 8, 15), None, period_id=2),
    )

    insights = build_time_goal_achievement_insights(
        today=today,
        periods=periods,
        daily_totals={today: 120},
    )

    assert insights.days[-1].configured is False
    assert insights.days[-1].achieved is False


def test_out_of_range_goal_value_fails_closed_without_division_error():
    today = date(2026, 8, 17)
    periods = (period(0, date(2026, 8, 11), None),)

    insights = build_time_goal_achievement_insights(
        today=today,
        periods=periods,
        daily_totals={today: 120},
    )

    assert insights.has_goals is False
    assert insights.achievement_rate is None
    assert insights.streak_days == 0
    assert insights.days[-1].configured is False


def test_dashboard_shows_goal_achievement_metrics_and_daily_results(client: TestClient):
    today = date.today()
    with client.app.state.time_goal_insights_session_factory() as db:
        save_daily_time_goal(db, 60, effective_on=today - timedelta(days=6))
        save_daily_time_goal(db, 120, effective_on=today - timedelta(days=3))
        records = (
            (today - timedelta(days=6), 60),
            (today - timedelta(days=5), 30),
            (today - timedelta(days=4), 80),
            (today - timedelta(days=3), 120),
            (today - timedelta(days=2), 150),
            (today - timedelta(days=1), 120),
            (today, 60),
        )
        for target_date, minutes in records:
            time_entry_crud.add_time_entry(
                db,
                target_date,
                minutes,
                "目標達成テスト",
                category="作業",
            )

    response = client.get("/")

    assert response.status_code == 200
    assert "目標達成" in response.text
    assert "目標設定日" in response.text
    assert "7/7日" in response.text
    assert "達成日" in response.text
    assert "5日" in response.text
    assert "達成率" in response.text
    assert "71%" in response.text
    assert "達成連続" in response.text
    assert "4日" in response.text
    assert "実績 60分 / 目標 120分・未達成" in response.text
    assert "当時の目標値で判定" in response.text


def test_dashboard_explains_when_recent_period_has_no_goals(client: TestClient):
    response = client.get("/")

    assert response.status_code == 200
    assert "直近7日は時間目標が設定されていません。" in response.text
