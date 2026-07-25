import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.crud import app_setting as app_setting_crud
from app.dashboard_cards import DASHBOARD_PREFERENCES_KEY
from app.db import Base, get_db
from app.main import app
from app.models.app_setting import AppSetting


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
    app.state.testing_session_factory = testing_session_local

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()
    del app.state.testing_session_factory
    test_engine.dispose()


def test_dashboard_preferences_default_to_all_cards(client: TestClient):
    response = client.get("/api/dashboard/preferences")

    assert response.status_code == 200
    assert response.json() == {
        "order": ["todo", "memo", "time"],
        "hidden": [],
        "persisted": False,
    }
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"

    dashboard = client.get("/")
    assert dashboard.status_code == 200
    assert 'data-swapy-item="todo"' in dashboard.text
    assert 'data-swapy-item="memo"' in dashboard.text
    assert 'data-swapy-item="time"' in dashboard.text
    assert 'data-preferences-endpoint="/api/dashboard/preferences"' in dashboard.text
    assert 'href="/static/dashboard.css"' in dashboard.text


def test_dashboard_preferences_are_saved_and_applied_to_rendering(client: TestClient):
    response = client.put(
        "/api/dashboard/preferences",
        json={"order": ["time", "todo", "memo"], "hidden": ["memo"]},
    )

    assert response.status_code == 200
    assert response.json() == {
        "order": ["time", "todo", "memo"],
        "hidden": ["memo"],
        "persisted": True,
    }

    saved = client.get("/api/dashboard/preferences")
    assert saved.json() == response.json()

    dashboard = client.get("/")
    assert dashboard.status_code == 200
    assert dashboard.text.index('data-swapy-item="time"') < dashboard.text.index(
        'data-swapy-item="todo"'
    )
    assert 'data-swapy-item="memo"' not in dashboard.text
    assert 'value="memo"' in dashboard.text

    session_factory = client.app.state.testing_session_factory
    with session_factory() as db:
        stored = app_setting_crud.get_json_setting(db, DASHBOARD_PREFERENCES_KEY)
        assert stored == {"order": ["time", "todo", "memo"], "hidden": ["memo"]}


@pytest.mark.parametrize(
    "payload",
    [
        {"order": ["todo", "memo"], "hidden": []},
        {"order": ["todo", "memo", "memo"], "hidden": []},
        {"order": ["todo", "memo", "unknown"], "hidden": []},
        {"order": ["todo", "memo", "time"], "hidden": ["unknown"]},
        {"order": ["todo", "memo", "time"], "hidden": ["memo", "memo"]},
        {"order": ["todo", "memo", "time"], "hidden": ["todo", "memo", "time"]},
    ],
)
def test_dashboard_preferences_reject_invalid_card_sets(client: TestClient, payload):
    response = client.put("/api/dashboard/preferences", json=payload)

    assert response.status_code == 400
    assert "detail" in response.json()
    assert client.get("/api/dashboard/preferences").json()["persisted"] is False


def test_dashboard_preferences_reject_invalid_json_shape(client: TestClient):
    response = client.put(
        "/api/dashboard/preferences",
        json={"order": "todo,memo,time", "hidden": []},
    )

    assert response.status_code == 422
    assert client.get("/api/dashboard/preferences").json()["persisted"] is False


def test_dashboard_preferences_can_be_reset(client: TestClient):
    client.put(
        "/api/dashboard/preferences",
        json={"order": ["memo", "time", "todo"], "hidden": ["time"]},
    )

    response = client.delete("/api/dashboard/preferences")

    assert response.status_code == 200
    assert response.json() == {
        "order": ["todo", "memo", "time"],
        "hidden": [],
        "persisted": False,
    }
    dashboard = client.get("/")
    assert 'data-swapy-item="todo"' in dashboard.text
    assert 'data-swapy-item="memo"' in dashboard.text
    assert 'data-swapy-item="time"' in dashboard.text


def test_corrupted_dashboard_setting_falls_back_without_breaking_page(client: TestClient):
    session_factory = client.app.state.testing_session_factory
    with session_factory() as db:
        db.add(AppSetting(key=DASHBOARD_PREFERENCES_KEY, value="{broken-json"))
        db.commit()

    response = client.get("/api/dashboard/preferences")
    dashboard = client.get("/")

    assert response.status_code == 200
    assert response.json()["persisted"] is False
    assert dashboard.status_code == 200
    assert 'data-swapy-item="todo"' in dashboard.text
    assert 'data-swapy-item="memo"' in dashboard.text
    assert 'data-swapy-item="time"' in dashboard.text


def test_unknown_json_setting_can_be_stored_for_future_extensions(client: TestClient):
    session_factory = client.app.state.testing_session_factory
    with session_factory() as db:
        app_setting_crud.upsert_json_setting(
            db,
            "appearance.preferences.v1",
            {"density": "compact", "navigation": ["dashboard", "history"]},
        )
        setting = db.get(AppSetting, "appearance.preferences.v1")

        assert setting is not None
        assert json.loads(setting.value) == {
            "density": "compact",
            "navigation": ["dashboard", "history"],
        }
