from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from app.db import Base, get_db
from app.main import app
from app.models.task import Task
from app.task_views import normalize_todo_view, todo_dashboard_url


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
    app.state.todo_filter_session_factory = session_factory
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
    del app.state.todo_filter_session_factory
    engine.dispose()


def seed_tasks(client: TestClient) -> None:
    today = date.today()
    with client.app.state.todo_filter_session_factory() as db:
        db.add_all(
            [
                Task(
                    title="期限切れ高",
                    due_date=today - timedelta(days=1),
                    priority="high",
                ),
                Task(
                    title="本日期限中",
                    due_date=today,
                    priority="medium",
                ),
                Task(
                    title="今後低",
                    due_date=today + timedelta(days=2),
                    priority="low",
                ),
                Task(
                    title="期限なし高",
                    due_date=None,
                    priority="high",
                ),
                Task(
                    title="完了済み高",
                    due_date=today - timedelta(days=3),
                    priority="high",
                    is_done=True,
                ),
                Task(
                    title="完了済み中",
                    due_date=None,
                    priority="medium",
                    is_done=True,
                ),
            ]
        )
        db.commit()


def task_count(client: TestClient) -> int:
    with client.app.state.todo_filter_session_factory() as db:
        return db.scalar(select(func.count(Task.id))) or 0


def test_todo_view_normalization_and_redirect_are_whitelisted():
    assert normalize_todo_view("overdue") == "overdue"
    assert normalize_todo_view("unknown") == "all"
    assert normalize_todo_view(None) == "all"

    assert (
        todo_dashboard_url("overdue", show_card="todo", task_id=7)
        == "/?todo_view=overdue&show_card=todo#task-7"
    )
    assert (
        todo_dashboard_url("javascript:alert(1)", show_card="https://example.com", task_id=7)
        == "/#task-7"
    )


@pytest.mark.parametrize(
    ("view", "expected_title"),
    [
        ("today", "本日期限中"),
        ("overdue", "期限切れ高"),
        ("upcoming", "今後低"),
        ("no_due", "期限なし高"),
    ],
)
def test_due_date_views_only_render_matching_open_tasks(
    client: TestClient,
    view: str,
    expected_title: str,
):
    seed_tasks(client)

    response = client.get("/", params={"todo_view": view})

    assert response.status_code == 200
    assert expected_title in response.text
    for title in {
        "期限切れ高",
        "本日期限中",
        "今後低",
        "期限なし高",
        "完了済み高",
        "完了済み中",
    } - {expected_title}:
        assert title not in response.text
    assert 'data-todo-view="' + view + '"' in response.text
    assert "6件中 1件を表示" in response.text


def test_high_priority_view_excludes_completed_high_priority_tasks(client: TestClient):
    seed_tasks(client)

    response = client.get("/", params={"todo_view": "high"})

    assert response.status_code == 200
    assert "期限切れ高" in response.text
    assert "期限なし高" in response.text
    assert "完了済み高" not in response.text
    assert "6件中 2件を表示" in response.text


def test_completed_view_only_renders_completed_tasks(client: TestClient):
    seed_tasks(client)

    response = client.get("/", params={"todo_view": "completed"})

    assert response.status_code == 200
    assert "完了済み高" in response.text
    assert "完了済み中" in response.text
    assert "期限切れ高" not in response.text
    assert "6件中 2件を表示" in response.text


def test_invalid_view_falls_back_to_all_without_mutating_tasks(client: TestClient):
    seed_tasks(client)
    before = task_count(client)

    response = client.get("/", params={"todo_view": "not-a-view"})

    assert response.status_code == 200
    assert 'data-todo-view="all"' in response.text
    assert "6件中 6件を表示" in response.text
    assert "期限切れ高" in response.text
    assert "完了済み中" in response.text
    assert task_count(client) == before


def test_filter_links_and_forms_preserve_forced_todo_card_context(client: TestClient):
    seed_tasks(client)

    response = client.get(
        "/",
        params={"todo_view": "high", "show_card": "todo"},
    )

    assert response.status_code == 200
    assert 'name="todo_view" value="high"' in response.text
    assert 'name="show_card" value="todo"' in response.text
    assert (
        'href="/?todo_view=overdue&amp;show_card=todo#todo-card"'
        in response.text
    )


def test_create_task_preserves_view_and_rejects_untrusted_return_context(client: TestClient):
    response = client.post(
        "/tasks/advanced",
        data={
            "title": "高優先度追加",
            "priority": "high",
            "due_date": "",
            "todo_view": "high",
            "show_card": "todo",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/?todo_view=high&show_card=todo#task-1"

    unsafe = client.post(
        "/tasks/advanced",
        data={
            "title": "安全な戻り先",
            "priority": "medium",
            "due_date": "",
            "todo_view": "https://example.com",
            "show_card": "javascript:alert(1)",
        },
        follow_redirects=False,
    )

    assert unsafe.status_code == 303
    assert unsafe.headers["location"] == "/#task-2"


def test_details_edit_preserves_view_and_can_move_task_out_of_filter(client: TestClient):
    with client.app.state.todo_filter_session_factory() as db:
        task = Task(title="編集対象", priority="high")
        db.add(task)
        db.commit()
        db.refresh(task)
        task_id = task.id

    response = client.post(
        f"/tasks/{task_id}/details",
        data={
            "due_date": "",
            "priority": "low",
            "todo_view": "high",
            "show_card": "todo",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == f"/?todo_view=high&show_card=todo#task-{task_id}"
    filtered = client.get("/", params={"todo_view": "high"})
    assert "編集対象" not in filtered.text
    assert "この条件に一致するタスクはありません。" in filtered.text


def test_toggle_in_high_view_keeps_view_and_removes_completed_task(client: TestClient):
    with client.app.state.todo_filter_session_factory() as db:
        task = Task(title="切替対象", priority="high")
        db.add(task)
        db.commit()
        db.refresh(task)
        task_id = task.id

    response = client.post(
        f"/tasks/{task_id}/toggle-view",
        data={"todo_view": "high"},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/?todo_view=high#todo-card"

    filtered = client.get("/", params={"todo_view": "high"})
    assert "切替対象" not in filtered.text
    assert "この条件に一致するタスクはありません。" in filtered.text


def test_delete_in_view_preserves_context_and_deletes_only_target(client: TestClient):
    with client.app.state.todo_filter_session_factory() as db:
        first = Task(title="削除対象", priority="high")
        second = Task(title="残す対象", priority="high")
        db.add_all([first, second])
        db.commit()
        db.refresh(first)
        first_id = first.id

    response = client.post(
        f"/tasks/{first_id}/delete-view",
        data={"todo_view": "high", "show_card": "todo"},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/?todo_view=high&show_card=todo#todo-card"
    with client.app.state.todo_filter_session_factory() as db:
        titles = set(db.scalars(select(Task.title)).all())
    assert titles == {"残す対象"}
