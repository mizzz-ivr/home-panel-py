from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.crud import app_setting as app_setting_crud
from app.db import Base, get_db
from app.main import app
from app.time_goal import (
    DAILY_TIME_GOAL_KEY,
    build_daily_time_goal_status,
    load_daily_time_goal,
    save_daily_time_goal,
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
    app.state.daily_time_goal_session_factory = session_factory
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
    del app.state.daily_time_goal_session_factory
    engine.dispose()


def time_card_html(response) -> str:
    return response.text.split('<section id="time-card"', 1)[1].split(
        'data-swapy-item="habits"', 1
    )[0]


def focus_card_html(response) -> str:
    return response.text.split('<section id="focus-card"', 1)[1].split(
        '<section id="todo-card"', 1
    )[0]


def test_daily_time_goal_is_unset_by_default(client: TestClient):
    response = client.get("/")

    assert response.status_code == 200
    card = time_card_html(response)
    assert "1日の時間目標" in card
    assert "目標を設定すると、今日の進捗と残り時間を確認できます。" in card
    assert "time-goal-percentage" not in card


def test_daily_time_goal_can_be_saved_and_persists(client: TestClient):
    response = client.post(
        "/settings/daily-time-goal",
        data={"minutes": "120"},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/#time-card"

    with client.app.state.daily_time_goal_session_factory() as db:
        assert load_daily_time_goal(db) == 120

    dashboard = client.get("/")
    card = time_card_html(dashboard)
    assert "目標 120分に対して 0%" in card
    assert 'value="0"' in card
    assert "目標まであと <strong>120分</strong>" in card
    assert 'value="120"' in card


def test_daily_time_goal_progress_updates_from_today_entries(client: TestClient):
    client.post("/settings/daily-time-goal", data={"minutes": "120"})
    client.post(
        "/time-entries",
        data={"category": "作業", "minutes": "95", "note": "集中作業"},
    )

    dashboard = client.get("/")
    card = time_card_html(dashboard)
    focus = focus_card_html(dashboard)

    assert dashboard.status_code == 200
    assert "目標 120分に対して 79%" in card
    assert 'value="79"' in card
    assert "目標まであと <strong>25分</strong>" in card
    assert "79%・残り25分" in focus
    assert 'href="/#time-card"' in focus


def test_daily_time_goal_keeps_actual_percentage_over_one_hundred(client: TestClient):
    client.post("/settings/daily-time-goal", data={"minutes": "120"})
    client.post(
        "/time-entries",
        data={"category": "作業", "minutes": "150", "note": "集中作業"},
    )

    dashboard = client.get("/")
    card = time_card_html(dashboard)
    focus = focus_card_html(dashboard)

    assert "目標 120分に対して 125%" in card
    assert 'value="100"' in card
    assert "目標達成・30分上回っています。" in card
    assert "125%・目標達成" in focus


def test_daily_time_goal_can_be_updated_and_cleared(client: TestClient):
    client.post("/settings/daily-time-goal", data={"minutes": "120"})
    updated = client.post(
        "/settings/daily-time-goal",
        data={"minutes": "60"},
        follow_redirects=False,
    )

    assert updated.status_code == 303
    with client.app.state.daily_time_goal_session_factory() as db:
        assert load_daily_time_goal(db) == 60

    cleared = client.post(
        "/settings/daily-time-goal",
        data={"minutes": "0"},
        follow_redirects=False,
    )

    assert cleared.status_code == 303
    assert cleared.headers["location"] == "/#time-card"
    with client.app.state.daily_time_goal_session_factory() as db:
        assert load_daily_time_goal(db) is None

    dashboard = client.get("/")
    assert "目標を設定すると、今日の進捗と残り時間を確認できます。" in time_card_html(
        dashboard
    )


@pytest.mark.parametrize("minutes", ["", "abc", "1.5", "-1", "1441"])
def test_daily_time_goal_rejects_invalid_values_without_overwriting_setting(
    client: TestClient,
    minutes: str,
):
    client.post("/settings/daily-time-goal", data={"minutes": "120"})

    response = client.post("/settings/daily-time-goal", data={"minutes": minutes})

    assert response.status_code == 400
    assert "1日の時間目標は1〜1440分の整数で入力してください。" in response.text
    with client.app.state.daily_time_goal_session_factory() as db:
        assert load_daily_time_goal(db) == 120


def test_daily_time_goal_accepts_boundary_values(client: TestClient):
    for minutes in (1, 1440):
        response = client.post(
            "/settings/daily-time-goal",
            data={"minutes": str(minutes)},
            follow_redirects=False,
        )
        assert response.status_code == 303
        with client.app.state.daily_time_goal_session_factory() as db:
            assert load_daily_time_goal(db) == minutes


def test_invalid_persisted_goal_falls_back_to_unset_without_crashing(client: TestClient):
    with client.app.state.daily_time_goal_session_factory() as db:
        app_setting_crud.upsert_json_setting(db, DAILY_TIME_GOAL_KEY, "120")

    response = client.get("/")

    assert response.status_code == 200
    assert "目標を設定すると、今日の進捗と残り時間を確認できます。" in time_card_html(
        response
    )


def test_daily_time_goal_service_rejects_bool_and_calculates_status(client: TestClient):
    with client.app.state.daily_time_goal_session_factory() as db:
        with pytest.raises(ValueError):
            save_daily_time_goal(db, True)

    status = build_daily_time_goal_status(120, 95)
    assert status.configured is True
    assert status.achieved is False
    assert status.percentage == 79
    assert status.progress_percentage == 79
    assert status.remaining_minutes == 25
    assert status.exceeded_minutes == 0
