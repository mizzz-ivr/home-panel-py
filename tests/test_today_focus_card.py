from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base, get_db
from app.main import app


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
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
    engine.dispose()


def create_task(
    client: TestClient,
    title: str,
    *,
    due_date: date | None,
    priority: str = "medium",
) -> int:
    response = client.post(
        "/tasks/advanced",
        data={
            "title": title,
            "due_date": due_date.isoformat() if due_date else "",
            "priority": priority,
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    return int(response.headers["location"].rsplit("task-", 1)[1])


def focus_html(response) -> str:
    return response.text.split('<section id="focus-card"', 1)[1].split(
        '<section id="todo-card"', 1
    )[0]


def test_today_focus_summarizes_urgent_tasks_habits_and_time(client: TestClient):
    today = date.today()
    create_task(
        client,
        "期限切れ重要",
        due_date=today - timedelta(days=1),
        priority="high",
    )
    create_task(client, "今日やる", due_date=today, priority="low")
    create_task(
        client,
        "未来の高優先度",
        due_date=today + timedelta(days=1),
        priority="high",
    )
    completed_id = create_task(
        client,
        "完了済み期限切れ",
        due_date=today - timedelta(days=2),
        priority="high",
    )
    completed = client.post(
        f"/tasks/{completed_id}/toggle-view",
        data={"todo_view": "all"},
        follow_redirects=False,
    )
    assert completed.status_code == 303

    assert client.post("/habits", data={"name": "読書"}, follow_redirects=False).status_code == 303
    assert client.post("/habits", data={"name": "筋トレ"}, follow_redirects=False).status_code == 303
    assert (
        client.post("/habits/2/toggle-today", follow_redirects=False).status_code
        == 303
    )

    time_response = client.post(
        "/time-entries",
        data={"category": "作業", "minutes": "95", "note": "集中作業"},
        follow_redirects=False,
    )
    assert time_response.status_code == 303

    response = client.get("/")
    focus = focus_html(response)

    assert response.status_code == 200
    assert "今日確認したい項目が <strong>3件</strong>" in focus
    assert "期限切れToDo" in focus
    assert "本日期限ToDo" in focus
    assert "未達成の習慣" in focus
    assert "1時間35分" in focus
    assert "1件の記録" in focus
    assert "期限切れ重要" in focus
    assert "今日やる" in focus
    assert "未来の高優先度" not in focus
    assert "完了済み期限切れ" not in focus
    assert "読書" in focus
    assert "筋トレ" not in focus
    assert '/?todo_view=overdue&amp;show_card=todo#todo-card' in focus
    assert '/?todo_view=today&amp;show_card=todo#todo-card' in focus
    assert '/habits/manage#habit-1' in focus
    assert f'/history?target_date={today.isoformat()}' in focus
    assert "<form" not in focus


def test_today_focus_todo_section_uses_today_view_when_only_today_is_due(client: TestClient):
    create_task(client, "今日だけ", due_date=date.today(), priority="medium")

    response = client.get("/")
    focus = focus_html(response)

    assert response.status_code == 200
    assert (
        '<a href="/?todo_view=today&amp;show_card=todo#todo-card">ToDoを開く</a>'
        in focus
    )


def test_today_focus_shows_clear_state_when_no_required_action_exists(client: TestClient):
    response = client.get("/")
    focus = focus_html(response)

    assert response.status_code == 200
    assert "今日の必須アクションは片付いています。" in focus
    assert "期限到来ToDoと今日対象の未達成習慣はありません。" in focus
    assert "0分" in focus
    assert "0件の記録" in focus


def test_today_focus_preview_is_limited_to_five_tasks(client: TestClient):
    today = date.today()
    for index in range(6):
        create_task(
            client,
            f"期限切れ{index}",
            due_date=today - timedelta(days=index + 1),
            priority="high",
        )

    response = client.get("/")
    focus = focus_html(response)

    assert response.status_code == 200
    assert "ほか 1件あります。" in focus
    assert focus.count("優先度高") == 5


def test_today_focus_can_be_hidden_with_dashboard_preferences(client: TestClient):
    payload = {
        "order": ["focus", "todo", "memo", "time", "habits"],
        "hidden": ["focus"],
    }
    saved = client.put("/api/dashboard/preferences", json=payload)

    assert saved.status_code == 200
    dashboard = client.get("/")
    assert 'data-swapy-item="focus"' not in dashboard.text
    assert 'value="focus"' in dashboard.text
