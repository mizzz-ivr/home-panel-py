from datetime import date, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from app.crud import app_setting as app_setting_crud
from app.crud import habit as habit_crud
from app.dashboard_cards import DASHBOARD_PREFERENCES_KEY
from app.db import Base, get_db
from app.main import app
from app.models.habit import Habit, HabitCompletion


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
    app.state.testing_session_factory = session_factory
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
    del app.state.testing_session_factory
    engine.dispose()


def test_dashboard_displays_habit_card(client: TestClient):
    response = client.get("/")

    assert response.status_code == 200
    assert 'data-swapy-item="habits"' in response.text
    assert "習慣トラッカー" in response.text
    assert 'action="/habits"' in response.text


def test_create_toggle_and_cancel_habit_completion(client: TestClient):
    response = client.post("/habits", data={"name": "30分読書"}, follow_redirects=True)
    assert response.status_code == 200
    assert "30分読書" in response.text
    assert "今日の達成: 0/1件" in response.text

    response = client.post("/habits/1/toggle-today", follow_redirects=True)
    assert response.status_code == 200
    assert "今日の達成: 1/1件" in response.text
    assert "1日継続" in response.text
    assert "取り消す" in response.text

    response = client.post("/habits/1/toggle-today", follow_redirects=True)
    assert response.status_code == 200
    assert "今日の達成: 0/1件" in response.text


def test_rejects_blank_duplicate_and_too_long_habit_names(client: TestClient):
    assert client.post("/habits", data={"name": "   "}).status_code == 400
    client.post("/habits", data={"name": "運動"})

    duplicate = client.post("/habits", data={"name": "運動"})
    assert duplicate.status_code == 400
    assert "同じ名前" in duplicate.text

    too_long = client.post("/habits", data={"name": "x" * 101})
    assert too_long.status_code == 400
    assert "1〜100文字" in too_long.text


def test_rejects_more_than_twenty_active_habits(client: TestClient):
    for index in range(habit_crud.MAX_ACTIVE_HABITS):
        response = client.post(
            "/habits",
            data={"name": f"習慣{index}"},
            follow_redirects=False,
        )
        assert response.status_code == 303

    response = client.post("/habits", data={"name": "上限超過"})
    assert response.status_code == 400
    assert "最大20件" in response.text


def test_archive_habit_hides_it_without_deleting_history(client: TestClient):
    client.post("/habits", data={"name": "日記"})
    client.post("/habits/1/toggle-today")

    response = client.post("/habits/1/archive", follow_redirects=True)
    assert response.status_code == 200
    assert "日記" not in response.text

    session_factory = client.app.state.testing_session_factory
    with session_factory() as db:
        habit = db.get(Habit, 1)
        assert habit is not None
        assert habit.is_active is False
        assert db.scalar(select(func.count(HabitCompletion.id))) == 1


def test_missing_or_archived_habit_returns_404(client: TestClient):
    assert client.post("/habits/999/toggle-today").status_code == 404
    assert client.post("/habits/999/archive").status_code == 404

    client.post("/habits", data={"name": "終了対象"})
    client.post("/habits/1/archive")
    assert client.post("/habits/1/toggle-today").status_code == 404


def test_current_streak_allows_today_to_be_pending():
    today = date(2026, 7, 25)

    assert habit_crud.calculate_current_streak({today}, today) == 1
    assert habit_crud.calculate_current_streak({today, today - timedelta(days=1)}, today) == 2
    assert habit_crud.calculate_current_streak(
        {today - timedelta(days=1), today - timedelta(days=2)}, today
    ) == 2
    assert habit_crud.calculate_current_streak({today - timedelta(days=2)}, today) == 0


def test_legacy_three_card_preferences_append_habits_and_preserve_hidden(client: TestClient):
    session_factory = client.app.state.testing_session_factory
    with session_factory() as db:
        app_setting_crud.upsert_json_setting(
            db,
            DASHBOARD_PREFERENCES_KEY,
            {"order": ["time", "todo", "memo"], "hidden": ["memo"]},
        )

    response = client.get("/api/dashboard/preferences")

    assert response.status_code == 200
    assert response.json() == {
        "order": ["time", "todo", "memo", "habits"],
        "hidden": ["memo"],
        "persisted": True,
    }
