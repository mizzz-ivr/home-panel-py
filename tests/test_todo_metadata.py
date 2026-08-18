from __future__ import annotations

import json
import re

from app.backup_restore import restore_backup_file

from .todo_metadata_legacy_tests import *  # noqa: F401,F403


def test_legacy_task_creation_uses_backward_compatible_defaults(client: TestClient):
    response = client.post(
        "/tasks",
        data={"title": "旧フォーム"},
        follow_redirects=False,
    )

    assert response.status_code == 303
    task = get_tasks(client)[0]
    assert task.due_date is None
    assert task.priority == "medium"


def test_advanced_task_creation_saves_due_date_and_priority(client: TestClient):
    target_due_date = date.today() + timedelta(days=1)
    response = client.post(
        "/tasks/advanced",
        data={
            "title": "リリース準備",
            "due_date": target_due_date.isoformat(),
            "priority": "high",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/#task-1"
    task = get_tasks(client)[0]
    assert task.title == "リリース準備"
    assert task.due_date == target_due_date
    assert task.priority == "high"

    dashboard = client.get("/")
    assert "リリース準備" in dashboard.text
    assert "優先度:" in dashboard.text
    assert "高" in dashboard.text
    assert target_due_date.strftime("%Y/%m/%d") in dashboard.text


def test_task_details_can_be_updated_and_due_date_cleared(client: TestClient):
    client.post(
        "/tasks/advanced",
        data={"title": "編集対象", "due_date": "2026-08-10", "priority": "low"},
        follow_redirects=False,
    )

    updated = client.post(
        "/tasks/1/details",
        data={"due_date": "2026-08-12", "priority": "high"},
        follow_redirects=False,
    )
    assert updated.status_code == 303
    task = get_tasks(client)[0]
    assert task.due_date == date(2026, 8, 12)
    assert task.priority == "high"

    cleared = client.post(
        "/tasks/1/details",
        data={"due_date": "", "priority": "medium"},
        follow_redirects=False,
    )
    assert cleared.status_code == 303
    task = get_tasks(client)[0]
    assert task.due_date is None
    assert task.priority == "medium"


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
    match = re.search(
        r'<li\s+id="task-1"\s+class="([^"]+)"',
        response.text,
        re.MULTILINE,
    )
    assert match is not None
    class_names = match.group(1).split()
    assert "done" in class_names
    assert "overdue" not in class_names
    assert "due-today" not in class_names


def test_backup_v6_preserves_task_metadata_and_validates(client: TestClient):
    client.post(
        "/tasks/advanced",
        data={"title": "バックアップ対象", "due_date": "2026-08-31", "priority": "low"},
    )
    exported_at = datetime(2026, 8, 6, 1, 0, tzinfo=timezone.utc)
    with client.app.state.testing_session_factory() as db:
        payload = build_backup_payload(db, exported_at=exported_at)

    payload["schema_version"] = 6
    payload["record_counts"].pop("daily_time_goal_periods")
    payload["data"].pop("daily_time_goal_periods")

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
    assert normalized["schema_version"] == 7
    assert normalized["data"]["daily_time_goal_periods"] == []
    assert task["due_date"] is None
    assert task["priority"] == "medium"
    assert validate_backup_payload(normalized) == []


def test_backup_v6_restore_preserves_task_due_date_and_priority(
    client: TestClient,
    tmp_path: Path,
):
    client.post(
        "/tasks/advanced",
        data={
            "title": "復元対象ToDo",
            "due_date": "2026-08-31",
            "priority": "high",
        },
        follow_redirects=False,
    )
    with client.app.state.testing_session_factory() as db:
        payload = build_backup_payload(
            db,
            exported_at=datetime(2026, 8, 6, 1, 0, tzinfo=timezone.utc),
        )

    payload["schema_version"] = 6
    payload["record_counts"].pop("daily_time_goal_periods")
    payload["data"].pop("daily_time_goal_periods")

    backup_path = tmp_path / "todo-v6.json"
    backup_path.write_text(
        json.dumps(payload, ensure_ascii=False),
        encoding="utf-8",
    )
    restored_path = tmp_path / "restored.db"

    result = restore_backup_file(backup_path, restored_path)

    assert result.source_schema_version == 6
    restored_engine = create_engine(f"sqlite:///{restored_path.as_posix()}")
    restored_session_factory = sessionmaker(bind=restored_engine)
    try:
        with restored_session_factory() as db:
            restored_task = db.get(Task, 1)
            assert restored_task is not None
            assert restored_task.title == "復元対象ToDo"
            assert restored_task.due_date == date(2026, 8, 31)
            assert restored_task.priority == "high"
    finally:
        restored_engine.dispose()
