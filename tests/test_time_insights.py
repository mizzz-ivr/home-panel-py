from datetime import date, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.crud import time_entry as time_entry_crud
from app.db import Base, get_db
from app.main import app
from app.time_insights import build_time_insights, calculate_recording_streak


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
    app.state.time_insights_session_factory = session_factory
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
    del app.state.time_insights_session_factory
    engine.dispose()


def time_card_html(response) -> str:
    return response.text.split('<section id="time-card"', 1)[1].split(
        'data-swapy-item="habits"', 1
    )[0]


def add_entry(
    client: TestClient,
    target_date: date,
    minutes: int,
    category: str = "作業",
) -> None:
    with client.app.state.time_insights_session_factory() as db:
        time_entry_crud.add_time_entry(
            db,
            target_date,
            minutes,
            "インサイトテスト",
            category=category,
        )


def hide_time_card(client: TestClient) -> None:
    response = client.put(
        "/api/dashboard/preferences",
        json={
            "order": ["focus", "todo", "memo", "time", "habits"],
            "hidden": ["time"],
        },
    )
    assert response.status_code == 200


def test_build_time_insights_summarizes_current_and_previous_periods():
    today = date(2026, 8, 17)
    daily_totals = {
        today: 120,
        today - timedelta(days=1): 60,
        today - timedelta(days=2): 30,
        today - timedelta(days=7): 80,
        today - timedelta(days=8): 60,
    }

    insights = build_time_insights(
        today=today,
        daily_totals=daily_totals,
        recorded_dates=(
            today,
            today - timedelta(days=1),
            today - timedelta(days=2),
            today - timedelta(days=4),
        ),
        category_totals=(("学習", 150), ("作業", 60)),
    )

    assert insights.period_start == date(2026, 8, 11)
    assert insights.period_end == today
    assert insights.total_minutes == 210
    assert insights.active_days == 3
    assert insights.average_minutes == 70
    assert insights.previous_total_minutes == 140
    assert insights.change_percentage == 50
    assert insights.trend == "up"
    assert insights.streak_days == 3
    assert insights.today_recorded is True
    assert insights.top_category == "学習"
    assert insights.top_category_minutes == 150
    assert len(insights.days) == 7
    assert insights.days[-1].minutes == 120
    assert insights.days[-1].percentage == 100
    assert insights.days[-2].percentage == 50


def test_build_time_insights_handles_zero_previous_period_without_division():
    today = date(2026, 8, 17)

    insights = build_time_insights(
        today=today,
        daily_totals={today: 25},
        recorded_dates=(today,),
        category_totals=(("作業", 25),),
    )

    assert insights.previous_total_minutes == 0
    assert insights.change_percentage is None
    assert insights.trend == "up"


def test_recording_streak_keeps_yesterday_streak_until_today_is_recorded():
    today = date(2026, 8, 17)

    assert calculate_recording_streak(
        (
            today - timedelta(days=1),
            today - timedelta(days=2),
            today - timedelta(days=3),
        ),
        today,
    ) == 3


def test_recording_streak_is_zero_when_yesterday_was_missed():
    today = date(2026, 8, 17)

    assert calculate_recording_streak(
        (today - timedelta(days=2), today - timedelta(days=3)),
        today,
    ) == 0


def test_dashboard_shows_empty_time_insights(client: TestClient):
    response = client.get("/")

    assert response.status_code == 200
    card = time_card_html(response)
    assert "直近7日の時間インサイト" in card
    assert "7日合計" in card
    assert "0/7日" in card
    assert "直近7日にはまだ時間記録がありません。" in card
    assert 'href="/static/time_insights.css"' in response.text


def test_dashboard_shows_time_insights_from_existing_entries(client: TestClient):
    today = date.today()
    add_entry(client, today, 120, "学習")
    add_entry(client, today - timedelta(days=1), 60, "作業")
    add_entry(client, today - timedelta(days=2), 30, "学習")
    add_entry(client, today - timedelta(days=7), 80, "作業")
    add_entry(client, today - timedelta(days=8), 60, "作業")

    response = client.get("/")

    assert response.status_code == 200
    card = time_card_html(response)
    assert "3時間30分" in card
    assert "3/7日" in card
    assert "活動日平均" in card
    assert "1時間10分" in card
    assert "連続記録" in card
    assert "3日" in card
    assert "今日も記録済み" in card
    assert "前7日比 <strong>+50%</strong>" in card
    assert "最多カテゴリ <strong>学習 150分</strong>" in card
    assert f'aria-label="{today.isoformat()}の記録時間 120分"' in card


def test_recorded_dates_are_distinct_and_ignore_future_entries(client: TestClient):
    today = date.today()
    add_entry(client, today, 20)
    add_entry(client, today, 30)
    add_entry(client, today - timedelta(days=1), 40)
    add_entry(client, today + timedelta(days=1), 50)

    with client.app.state.time_insights_session_factory() as db:
        recorded_dates = time_entry_crud.list_recorded_dates_up_to(db, today)

    assert recorded_dates == [today, today - timedelta(days=1)]


def test_hidden_time_card_only_builds_insights_when_temporarily_shown(client: TestClient):
    hide_time_card(client)

    hidden_response = client.get("/")
    forced_response = client.get("/?show_card=time")

    assert hidden_response.status_code == 200
    assert "直近7日の時間インサイト" not in hidden_response.text
    assert forced_response.status_code == 200
    assert forced_response.text.count("直近7日の時間インサイト") == 1
    assert forced_response.text.count('id="time-card"') == 1
