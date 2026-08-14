from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base, get_db
from app.main import app


@pytest.fixture()
def client(tmp_path: Path):
    db_path = tmp_path / "test.db"
    test_engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
    )
    testing_session_local = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)
    Base.metadata.create_all(bind=test_engine)

    def override_get_db():
        db = testing_session_local()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()
    test_engine.dispose()


def test_dashboard_renders_focus_timer_controls(client: TestClient):
    response = client.get("/")

    assert response.status_code == 200
    assert 'href="/static/time_timer.css"' in response.text
    assert 'src="/static/time_timer.js"' in response.text
    assert 'data-focus-timer' in response.text
    assert 'data-timer-display' in response.text
    assert 'data-timer-start' in response.text
    assert 'data-timer-pause' in response.text
    assert 'data-timer-resume' in response.text
    assert 'data-timer-reset' in response.text
    assert 'aria-live="polite"' in response.text
    assert "完了しても自動登録せず" in response.text

    for minutes in (15, 25, 50, 90):
        assert f'data-timer-preset="{minutes}"' in response.text
        assert f">{minutes}分</button>" in response.text


def test_focus_timer_assets_are_served_and_do_not_post_time_entries(client: TestClient):
    script = client.get("/static/time_timer.js")
    stylesheet = client.get("/static/time_timer.css")

    assert script.status_code == 200
    assert stylesheet.status_code == 200
    assert "home-panel.focus-timer.v1" in script.text
    assert "Date.now()" in script.text
    assert "localStorage" in script.text
    assert "/time-entries" not in script.text
    assert "fetch(" not in script.text
    assert ".submit(" not in script.text
    assert ".focus-timer-panel" in stylesheet.text


def test_focus_timer_is_available_when_hidden_time_card_is_temporarily_shown(
    client: TestClient,
):
    preferences = client.get("/api/dashboard/preferences").json()
    response = client.put(
        "/api/dashboard/preferences",
        json={
            "order": preferences["order"],
            "hidden": ["time"],
        },
    )
    assert response.status_code == 200

    dashboard = client.get("/?show_card=time")

    assert dashboard.status_code == 200
    assert "この画面だけ非表示設定のカードを表示しています。" in dashboard.text
    assert 'id="time-card"' in dashboard.text
    assert 'data-focus-timer' in dashboard.text
    assert dashboard.text.count('data-focus-timer') == 1


def test_focus_timer_buttons_are_non_submit_controls(client: TestClient):
    response = client.get("/")

    assert response.status_code == 200
    assert 'type="button" data-timer-start' in response.text
    assert 'type="button" data-timer-pause' in response.text
    assert 'type="button" data-timer-resume' in response.text
    assert 'type="button" class="secondary-button" data-timer-reset' in response.text
