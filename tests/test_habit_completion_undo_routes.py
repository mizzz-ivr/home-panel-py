from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from app import habit_report_routes, main
from app.crud import habit as habit_crud
from app.db import Base, get_db
from app.habit_completion_undo import (
    HABIT_COMPLETION_UNDO_KEY,
    get_completion_habit_ids,
)
from app.main import app
from app.models.app_setting import AppSetting
from app.models.habit import HabitCompletion

FIXED_TODAY = date(2026, 7, 31)
PAST_DATE = date(2026, 7, 30)


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

    monkeypatch.setattr(main, "date", FixedDate)
    monkeypatch.setattr(habit_report_routes, "date", FixedDate)
    app.dependency_overrides[get_db] = override_get_db
    app.state.testing_session_factory = session_factory
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
    del app.state.testing_session_factory
    engine.dispose()


def create_habit(
    client: TestClient,
    name: str,
    *,
    weekdays: tuple[int, ...] = tuple(range(7)),
) -> int:
    session_factory = client.app.state.testing_session_factory
    with session_factory() as db:
        return habit_crud.create_habit(
            db,
            name,
            started_on=date(2026, 7, 1),
            weekdays=weekdays,
        ).id


def add_completion(client: TestClient, habit_id: int, target_date: date) -> None:
    session_factory = client.app.state.testing_session_factory
    with session_factory() as db:
        db.add(HabitCompletion(habit_id=habit_id, completed_on=target_date))
        db.commit()


def completion_ids(client: TestClient, target_date: date) -> tuple[int, ...]:
    session_factory = client.app.state.testing_session_factory
    with session_factory() as db:
        return get_completion_habit_ids(db, target_date)


def undo_setting_count(client: TestClient) -> int:
    session_factory = client.app.state.testing_session_factory
    with session_factory() as db:
        return int(
            db.scalar(
                select(func.count(AppSetting.key)).where(
                    AppSetting.key == HABIT_COMPLETION_UNDO_KEY
                )
            )
            or 0
        )


def get_undo_status(client: TestClient, target_date: date = PAST_DATE):
    return client.get(
        "/habits/completions/undo",
        params={"target_date": target_date.isoformat()},
    )


def test_single_completion_exposes_undo_and_restores_previous_state(client: TestClient):
    habit_id = create_habit(client, "読書")

    update = client.post(
        f"/habits/{habit_id}/completion",
        data={"target_date": PAST_DATE.isoformat(), "completed": "true"},
        follow_redirects=False,
    )
    status_response = get_undo_status(client)

    assert update.status_code == 303
    assert completion_ids(client, PAST_DATE) == (habit_id,)
    assert status_response.status_code == 200
    assert status_response.headers["cache-control"] == "no-store"
    assert status_response.headers["x-content-type-options"] == "nosniff"
    payload = status_response.json()
    assert payload["available"] is True
    assert payload["label"] == "習慣を達成に変更"
    assert payload["target_date"] == PAST_DATE.isoformat()
    assert payload["expires_in_seconds"] <= 600

    undo = client.post(
        "/habits/completions/undo",
        data={"token": payload["token"]},
        follow_redirects=False,
    )

    assert undo.status_code == 303
    assert undo.headers["location"] == (
        f"/habits/history?target_date={PAST_DATE.isoformat()}"
    )
    assert undo.headers["cache-control"] == "no-store"
    assert completion_ids(client, PAST_DATE) == ()
    assert undo_setting_count(client) == 0


def test_dashboard_toggle_undo_returns_to_dashboard(client: TestClient):
    habit_id = create_habit(client, "読書")

    toggle = client.post(
        f"/habits/{habit_id}/toggle-today",
        follow_redirects=False,
    )
    status_response = get_undo_status(client, FIXED_TODAY)

    assert toggle.status_code == 303
    assert completion_ids(client, FIXED_TODAY) == (habit_id,)
    payload = status_response.json()
    assert payload["available"] is True
    assert payload["label"] == "今日の習慣の達成状態変更"

    undo = client.post(
        "/habits/completions/undo",
        data={"token": payload["token"]},
        follow_redirects=False,
    )

    assert undo.status_code == 303
    assert undo.headers["location"] == "/"
    assert completion_ids(client, FIXED_TODAY) == ()


def test_bulk_clear_undo_restores_all_records(client: TestClient):
    first_id = create_habit(client, "読書")
    second_id = create_habit(client, "運動")
    add_completion(client, first_id, PAST_DATE)
    add_completion(client, second_id, PAST_DATE)

    clear = client.post(
        "/habits/completions/bulk",
        data={"target_date": PAST_DATE.isoformat(), "action": "clear_all"},
        follow_redirects=False,
    )
    payload = get_undo_status(client).json()

    assert clear.status_code == 303
    assert completion_ids(client, PAST_DATE) == ()
    assert payload["label"] == "この日の全達成取り消し"

    undo = client.post(
        "/habits/completions/undo",
        data={"token": payload["token"]},
        follow_redirects=False,
    )

    assert undo.status_code == 303
    assert completion_ids(client, PAST_DATE) == (first_id, second_id)


def test_selected_clear_undo_restores_selected_and_preserves_unselected(client: TestClient):
    first_id = create_habit(client, "読書")
    second_id = create_habit(client, "運動")
    remaining_id = create_habit(client, "日記")
    for habit_id in (first_id, second_id, remaining_id):
        add_completion(client, habit_id, PAST_DATE)

    clear = client.post(
        "/habits/completions/selected",
        data={
            "target_date": PAST_DATE.isoformat(),
            "completed": "false",
            "habit_ids": [str(first_id), str(second_id)],
        },
        follow_redirects=False,
    )
    payload = get_undo_status(client).json()

    assert clear.status_code == 303
    assert completion_ids(client, PAST_DATE) == (remaining_id,)
    assert payload["label"] == "選択した達成の一括取り消し"

    undo = client.post(
        "/habits/completions/undo",
        data={"token": payload["token"]},
        follow_redirects=False,
    )

    assert undo.status_code == 303
    assert completion_ids(client, PAST_DATE) == (
        first_id,
        second_id,
        remaining_id,
    )


def test_latest_change_replaces_previous_token(client: TestClient):
    first_id = create_habit(client, "読書")
    second_id = create_habit(client, "運動")

    client.post(
        f"/habits/{first_id}/completion",
        data={"target_date": PAST_DATE.isoformat(), "completed": "true"},
    )
    first_token = get_undo_status(client).json()["token"]
    client.post(
        f"/habits/{second_id}/completion",
        data={"target_date": PAST_DATE.isoformat(), "completed": "true"},
    )
    second_token = get_undo_status(client).json()["token"]

    assert second_token != first_token
    rejected = client.post(
        "/habits/completions/undo",
        data={"token": first_token},
        follow_redirects=False,
    )
    assert rejected.status_code == 400
    assert completion_ids(client, PAST_DATE) == (first_id, second_id)

    restored = client.post(
        "/habits/completions/undo",
        data={"token": second_token},
        follow_redirects=False,
    )
    assert restored.status_code == 303
    assert completion_ids(client, PAST_DATE) == (first_id,)


def test_external_state_change_hides_and_rejects_stale_undo(client: TestClient):
    first_id = create_habit(client, "読書")
    second_id = create_habit(client, "運動")
    client.post(
        f"/habits/{first_id}/completion",
        data={"target_date": PAST_DATE.isoformat(), "completed": "true"},
    )
    token = get_undo_status(client).json()["token"]
    add_completion(client, second_id, PAST_DATE)

    hidden = get_undo_status(client)
    rejected = client.post(
        "/habits/completions/undo",
        data={"token": token},
        follow_redirects=False,
    )

    assert hidden.json() == {"available": False}
    assert rejected.status_code == 409
    assert "後続の変更" in rejected.text
    assert completion_ids(client, PAST_DATE) == (first_id, second_id)
    assert undo_setting_count(client) == 0


def test_schedule_change_invalidates_existing_undo(client: TestClient):
    habit_id = create_habit(client, "読書")
    client.post(
        f"/habits/{habit_id}/completion",
        data={"target_date": PAST_DATE.isoformat(), "completed": "true"},
    )
    assert undo_setting_count(client) == 1

    session_factory = client.app.state.testing_session_factory
    with session_factory() as db:
        habit_crud.update_habit_schedule(
            db,
            habit_id,
            [0, 1, 2, 3, 4],
            changed_on=FIXED_TODAY,
        )

    assert undo_setting_count(client) == 0
    assert get_undo_status(client).json() == {"available": False}


def test_archive_invalidates_existing_undo(client: TestClient):
    habit_id = create_habit(client, "読書")
    client.post(
        f"/habits/{habit_id}/completion",
        data={"target_date": PAST_DATE.isoformat(), "completed": "true"},
    )
    assert undo_setting_count(client) == 1

    archive = client.post(
        f"/habits/{habit_id}/archive",
        follow_redirects=False,
    )

    assert archive.status_code == 303
    assert undo_setting_count(client) == 0


@pytest.mark.parametrize(
    "target_date",
    ["20260731", "2026-02-30", "2026-7-31"],
)
def test_undo_status_rejects_invalid_date(client: TestClient, target_date: str):
    response = client.get(
        "/habits/completions/undo",
        params={"target_date": target_date},
    )

    assert response.status_code == 400
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"


def test_undo_rejects_invalid_or_missing_token(client: TestClient):
    invalid = client.post(
        "/habits/completions/undo",
        data={"token": "short"},
        follow_redirects=False,
    )
    missing = client.post(
        "/habits/completions/undo",
        data={"token": "x" * 24},
        follow_redirects=False,
    )

    assert invalid.status_code == 400
    assert missing.status_code == 404
    assert invalid.headers["cache-control"] == "no-store"
    assert missing.headers["x-content-type-options"] == "nosniff"


def test_dashboard_and_history_load_undo_assets(client: TestClient):
    dashboard = client.get("/")
    history = client.get(
        "/habits/history",
        params={"target_date": PAST_DATE.isoformat()},
    )

    for response, target_date in (
        (dashboard, FIXED_TODAY),
        (history, PAST_DATE),
    ):
        assert response.status_code == 200
        assert "/static/habit_undo.css" in response.text
        assert "/static/habit_undo.js" in response.text
        assert "data-habit-undo" in response.text
        assert f'data-target-date="{target_date.isoformat()}"' in response.text
