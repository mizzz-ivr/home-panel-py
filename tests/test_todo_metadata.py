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
    response = client.post(
        "/tasks/advanced",
        data={
            "title": "リリース準備",
            "due_date": "2026-08-10",
            "priority": "high",
        },
        follow_redirects=False,
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
