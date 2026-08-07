from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.orm import sessionmaker

from app.backup_export import build_backup_payload
from app.backup_restore import normalize_backup_payload
from app.backup_validate import validate_backup_payload
from app.crud import task as task_crud
from app.db import Base, get_db
from app.main import app
from app.migrations import migrate_task_metadata
from app.models.task import Task


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


def get_tasks(client: TestClient) -> list[Task]:
    with client.app.state.testing_session_factory() as db:
        return list(db.scalars(select(Task).order_by(Task.id.asc())).all())


def test_legacy_task_creation_uses_backward_compatible_defaults(client: TestClient):
    response = client.post("/tasks", data={"title": "旧フォーム"})

    assert response.status_code == 303
    task = get_tasks(client)[0]
    assert task.due_date is None
    assert task.priority == "medium"


def test_advanced_task_creation_saves_due_date_and_priority(client: TestClient):
    response = client.post(
        "/tasks/advanced",
        data={
            "title": "リリース準備",
            "due_date": "2026-08-10",
            "priority": "high",
        },
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/#task-1"
    task = get_tasks(client)[0]
    assert task.title == "リリース準備"
    assert task.due_date == date(2026, 8, 10)
    assert task.priority == "high"

    dashboard = client.get("/")
    assert "リリース準備" in dashboard.text
    assert "優先度:" in dashboard.text
    assert "高" in dashboard.text
    assert "2026/08/10" in dashboard.text


def test_task_details_can_be_updated_and_due_date_cleared(client: TestClient):
    client.post(
        "/tasks/advanced",
        data={"title": "編集対象", "due_date": "2026-08-10", "priority": "low"},
    )

    updated = client.post(
        "/tasks/1/details",
        data={"due_date": "2026-08-12", "priority": "high"},
    )
    assert updated.status_code == 303
    task = get_tasks(client)[0]
    assert task.due_date == date(2026, 8, 12)
    assert task.priority == "high"

    cleared = client.post(
        "/tasks/1/details",
        data={"due_date": "", "priority": "medium"},
    )
    assert cleared.status_code == 303
    task = get_tasks(client)[0]
    assert task.due_date is None
    assert task.priority == "medium"


@pytest.mark.parametrize(
    ("due_date", "priority"),
    [
        ("2026-02-30", "medium"),
        ("20260810", "medium"),
        ("2026-08-10", "urgent"),
    ],
)
def test_advanced_task_creation_rejects_invalid_metadata(
    client: TestClient,
    due_date: str,
    priority: str,
):
    response = client.post(
        "/tasks/advanced",
        data={"title": "不正入力", "due_date": due_date, "priority": priority},
    )

    assert response.status_code == 400
    assert response.headers["cache-control"] == "no-store"
    assert get_tasks(client) == []


def test_task_details_returns_not_found_without_partial_update(client: TestClient):
    response = client.post(
        "/tasks/999/details",
        data={"due_date": "2026-08-10", "priority": "high"},
    )

    assert response.status_code == 404
    assert get_tasks(client) == []


def test_unfinished_tasks_are_ordered_by_due_state_priority_and_date(client: TestClient):
    today = date(2026, 8, 6)
    with client.app.state.testing_session_factory() as db:
        task_crud.create_task(db, "期限切れ低", due_date=today - timedelta(days=1), priority="low")
        task_crud.create_task(db, "期限切れ高", due_date=today - timedelta(days=2), priority="high")
        task_crud.create_task(db, "本日中", due_date=today, priority="medium")
        task_crud.create_task(db, "将来高", due_date=today + timedelta(days=5), priority="high")
        task_crud.create_task(db, "将来低早い", due_date=today + timedelta(days=2), priority="low")
        task_crud.create_task(db, "期限なし高", priority="high")
        completed = task_crud.create_task(
            db,
            "完了済み期限切れ",
            due_date=today - timedelta(days=10),
            priority="high",
        )
        task_crud.toggle_task(db, completed.id)
        ordered = task_crud.list_tasks(db, today=today)

    assert [task.title for task in ordered] == [
        "期限切れ高",
        "期限切れ低",
        "本日中",
        "将来高",
        "将来低早い",
        "期限なし高",
        "完了済み期限切れ",
    ]


def test_completed_past_due_task_is_not_rendered_as_overdue(client: TestClient):
    with client.app.state.testing_session_factory() as db:
        task = task_crud.create_task(
            db,
            "完了済み",
            due_date=date.today() - timedelta(days=1),
            priority="high",
        )
        task_crud.toggle_task(db, task.id)

    response = client.get("/")

    assert response.status_code == 200
    marker = 'id="task-1" class="todo-item done"'
    assert marker in response.text


def test_search_result_contains_task_due_date_and_priority(client: TestClient):
    client.post(
        "/tasks/advanced",
        data={"title": "検索対象ToDo", "due_date": "2026-08-20", "priority": "high"},
    )

    response = client.get("/search", params={"q": "検索対象"})

    assert response.status_code == 200
    assert "優先度 高" in response.text
    assert "2026/08/20" in response.text
    assert 'href="/?show_card=todo#task-1"' in response.text


def test_task_migration_adds_columns_defaults_indexes_and_is_idempotent(tmp_path: Path):
    engine = create_engine(f"sqlite:///{tmp_path / 'legacy.db'}")
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE tasks ("
                "id INTEGER PRIMARY KEY, title VARCHAR(255) NOT NULL, "
                "is_done BOOLEAN NOT NULL, created_at DATETIME NOT NULL, "
                "updated_at DATETIME NOT NULL)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO tasks VALUES "
                "(1, '既存', 0, '2026-08-01 00:00:00', '2026-08-01 00:00:00')"
            )
        )

    first = migrate_task_metadata(engine)
    second = migrate_task_metadata(engine)

    assert first == {"due_date_added": True, "priority_added": True}
    assert second == {"due_date_added": False, "priority_added": False}
    inspector = inspect(engine)
    columns = {column["name"] for column in inspector.get_columns("tasks")}
    indexes = {index["name"] for index in inspector.get_indexes("tasks")}
    assert {"due_date", "priority"}.issubset(columns)
    assert {"ix_tasks_due_date", "ix_tasks_priority"}.issubset(indexes)
    with engine.connect() as connection:
        row = connection.execute(
            text("SELECT due_date, priority FROM tasks WHERE id = 1")
        ).one()
    assert row == (None, "medium")
    engine.dispose()


def test_backup_v6_preserves_task_metadata_and_validates(client: TestClient):
    client.post(
        "/tasks/advanced",
        data={"title": "バックアップ対象", "due_date": "2026-08-31", "priority": "low"},
    )
    exported_at = datetime(2026, 8, 6, 1, 0, tzinfo=timezone.utc)
    with client.app.state.testing_session_factory() as db:
        payload = build_backup_payload(db, exported_at=exported_at)

    assert payload["schema_version"] == 6
    assert payload["data"]["tasks"][0]["due_date"] == "2026-08-31"
    assert payload["data"]["tasks"][0]["priority"] == "low"
    assert validate_backup_payload(payload) == []

    invalid_priority = payload | {
        "data": payload["data"] | {
            "tasks": [payload["data"]["tasks"][0] | {"priority": "urgent"}]
        }
    }
    assert any("priority" in error for error in validate_backup_payload(invalid_priority))


def test_v5_backup_is_normalized_with_task_defaults():
    payload = {
        "schema_version": 5,
        "application": "home-panel-py",
        "exported_at": "2026-08-06T01:00:00Z",
        "record_counts": {
            "tasks": 1,
            "daily_memos": 0,
            "time_entries": 0,
            "habits": 0,
            "habit_active_periods": 0,
            "habit_schedule_periods": 0,
            "habit_completions": 0,
        },
        "data": {
            "tasks": [
                {
                    "id": 1,
                    "title": "旧バックアップ",
                    "is_done": False,
                    "created_at": "2026-08-01T00:00:00Z",
                    "updated_at": "2026-08-01T00:00:00Z",
                }
            ],
            "daily_memos": [],
            "time_entries": [],
            "habits": [],
            "habit_active_periods": [],
            "habit_schedule_periods": [],
            "habit_completions": [],
        },
    }

    assert validate_backup_payload(payload) == []
    normalized = normalize_backup_payload(payload)
    task = normalized["data"]["tasks"][0]
    assert normalized["schema_version"] == 6
    assert task["due_date"] is None
    assert task["priority"] == "medium"
    assert validate_backup_payload(normalized) == []
