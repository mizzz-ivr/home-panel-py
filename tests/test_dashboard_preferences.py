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

ALL_CARD_IDS = ["focus", "todo", "memo", "time", "habits"]


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
        "order": ALL_CARD_IDS,
        "hidden": [],
        "persisted": False,
    }
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"

    dashboard = client.get("/")
    assert dashboard.status_code == 200
    for card_id in ALL_CARD_IDS:
        assert f'data-swapy-item="{card_id}"' in dashboard.text
    assert dashboard.text.index('data-swapy-item="focus"') < dashboard.text.index(
        'data-swapy-item="todo"'
    )
    assert 'data-preferences-endpoint="/api/dashboard/preferences"' in dashboard.text
    assert 'href="/static/dashboard.css"' in dashboard.text
    assert 'href="/static/focus.css"' in dashboard.text


def test_dashboard_preferences_are_saved_and_applied_to_rendering(client: TestClient):
    payload = {
        "order": ["time", "habits", "todo", "memo", "focus"],
        "hidden": ["memo"],
    }
    response = client.put("/api/dashboard/preferences", json=payload)

    assert response.status_code == 200
    assert response.json() == {**payload, "persisted": True}
    assert client.get("/api/dashboard/preferences").json() == response.json()

    dashboard = client.get("/")
    assert dashboard.status_code == 200
    assert dashboard.text.index('data-swapy-item="time"') < dashboard.text.index(
        'data-swapy-item="habits"'
    )
    assert dashboard.text.index('data-swapy-item="habits"') < dashboard.text.index(
        'data-swapy-item="todo"'
    )
    assert dashboard.text.index('data-swapy-item="todo"') < dashboard.text.index(
        'data-swapy-item="focus"'
    )
    assert 'data-swapy-item="memo"' not in dashboard.text
    assert 'value="memo"' in dashboard.text

    session_factory = client.app.state.testing_session_factory
    with session_factory() as db:
        assert app_setting_crud.get_json_setting(db, DASHBOARD_PREFERENCES_KEY) == payload


def test_existing_four_card_preferences_append_focus_without_reordering(client: TestClient):
    legacy_payload = {
        "order": ["time", "habits", "todo", "memo"],
        "hidden": ["memo"],
    }
    session_factory = client.app.state.testing_session_factory
    with session_factory() as db:
        app_setting_crud.upsert_json_setting(db, DASHBOARD_PREFERENCES_KEY, legacy_payload)

    response = client.get("/api/dashboard/preferences")

    assert response.status_code == 200
    assert response.json() == {
        "order": ["time", "habits", "todo", "memo", "focus"],
        "hidden": ["memo"],
        "persisted": True,
    }
    dashboard = client.get("/")
    assert dashboard.text.index('data-swapy-item="time"') < dashboard.text.index(
        'data-swapy-item="habits"'
    )
    assert dashboard.text.index('data-swapy-item="habits"') < dashboard.text.index(
        'data-swapy-item="todo"'
    )
    assert dashboard.text.index('data-swapy-item="todo"') < dashboard.text.index(
        'data-swapy-item="focus"'
    )
    assert 'data-swapy-item="memo"' not in dashboard.text


@pytest.mark.parametrize(
    "payload",
    [
        {"order": ["todo", "memo", "time", "habits"], "hidden": []},
        {"order": ["focus", "todo", "memo", "time", "time"], "hidden": []},
        {"order": ["focus", "todo", "memo", "time", "unknown"], "hidden": []},
        {"order": ALL_CARD_IDS, "hidden": ["unknown"]},
        {"order": ALL_CARD_IDS, "hidden": ["memo", "memo"]},
        {"order": ALL_CARD_IDS, "hidden": ALL_CARD_IDS},
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
        json={"order": "focus,todo,memo,time,habits", "hidden": []},
    )

    assert response.status_code == 422
    assert client.get("/api/dashboard/preferences").json()["persisted"] is False


def test_dashboard_preferences_can_be_reset(client: TestClient):
    client.put(
        "/api/dashboard/preferences",
        json={
            "order": ["memo", "habits", "time", "todo", "focus"],
            "hidden": ["time"],
        },
    )

    response = client.delete("/api/dashboard/preferences")

    assert response.status_code == 200
    assert response.json() == {
        "order": ALL_CARD_IDS,
        "hidden": [],
        "persisted": False,
    }
    dashboard = client.get("/")
    for card_id in ALL_CARD_IDS:
        assert f'data-swapy-item="{card_id}"' in dashboard.text


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
    for card_id in ALL_CARD_IDS:
        assert f'data-swapy-item="{card_id}"' in dashboard.text


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
