from datetime import date, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.crud import memo as memo_crud
from app.crud import time_entry as time_entry_crud
from app.db import Base, get_db
from app.main import app


@pytest.fixture()
def client(tmp_path: Path):
    db_path = tmp_path / "test.db"
    test_engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
    )
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)
    Base.metadata.create_all(bind=test_engine)

    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    app.state.testing_session_factory = TestingSessionLocal

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()
    del app.state.testing_session_factory


def test_top_page(client: TestClient):
    response = client.get("/")
    assert response.status_code == 200
    assert "Home Panel" in response.text
    assert 'href="/history"' in response.text


def test_dashboard_contains_swapy_layout(client: TestClient):
    response = client.get("/")

    assert response.status_code == 200
    assert 'data-swapy-container' in response.text
    assert 'data-swapy-slot="slot-1"' in response.text
    assert 'data-swapy-slot="slot-2"' in response.text
    assert 'data-swapy-slot="slot-3"' in response.text
    assert 'data-swapy-item="todo"' in response.text
    assert 'data-swapy-item="memo"' in response.text
    assert 'data-swapy-item="time"' in response.text
    assert 'swapy@1.0.5/dist/swapy.min.js' in response.text


def test_dashboard_javascript_is_served(client: TestClient):
    response = client.get("/static/app.js")

    assert response.status_code == 200
    assert "home-panel:dashboard-layout:v1" in response.text
    assert "onSwapEnd" in response.text


def test_add_task(client: TestClient):
    response = client.post("/tasks", data={"title": "買い物"}, follow_redirects=True)
    assert response.status_code == 200
    assert "買い物" in response.text


def test_toggle_task(client: TestClient):
    client.post("/tasks", data={"title": "読書"})
    response = client.post("/tasks/1/toggle", follow_redirects=True)
    assert response.status_code == 200
    assert "未完了に戻す" in response.text


def test_delete_task(client: TestClient):
    client.post("/tasks", data={"title": "削除対象"})
    response = client.post("/tasks/1/delete", follow_redirects=True)
    assert response.status_code == 200
    assert "削除対象" not in response.text


def test_save_today_memo(client: TestClient):
    client.post("/memo/today", data={"content": "今日は設計を進めた"})
    response = client.get("/memo/today")
    assert response.status_code == 200
    assert response.json()["memo_date"] == str(date.today())
    assert response.json()["content"] == "今日は設計を進めた"


def test_add_time_entry_reflects_total(client: TestClient):
    response = client.post(
        "/time-entries",
        data={"minutes": 30, "note": "Python学習"},
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert "当日合計: <strong>30</strong> 分" in response.text


def test_history_displays_selected_date(client: TestClient):
    target_date = date.today() - timedelta(days=1)
    session_factory = client.app.state.testing_session_factory

    with session_factory() as db:
        memo_crud.upsert_memo_by_date(db, target_date, "昨日はテストを追加した")
        time_entry_crud.add_time_entry(db, target_date, 45, "履歴画面の確認")
        time_entry_crud.add_time_entry(db, target_date, 15, "README更新")

    response = client.get("/history", params={"target_date": target_date.isoformat()})

    assert response.status_code == 200
    assert target_date.strftime("%Y年%m月%d日") in response.text
    assert "昨日はテストを追加した" in response.text
    assert "履歴画面の確認" in response.text
    assert "README更新" in response.text
    assert "60分" in response.text
    assert "2件" in response.text


def test_history_defaults_to_today(client: TestClient):
    client.post("/memo/today", data={"content": "今日の履歴"})
    client.post("/time-entries", data={"minutes": 25, "note": "確認"})

    response = client.get("/history")

    assert response.status_code == 200
    assert date.today().strftime("%Y年%m月%d日") in response.text
    assert "今日の履歴" in response.text
    assert "25分" in response.text


def test_history_rejects_invalid_date(client: TestClient):
    response = client.get("/history", params={"target_date": "not-a-date"})

    assert response.status_code == 400
    assert "日付はYYYY-MM-DD形式で指定してください。" in response.text


def test_history_rejects_future_date(client: TestClient):
    future_date = date.today() + timedelta(days=1)
    response = client.get("/history", params={"target_date": future_date.isoformat()})

    assert response.status_code == 400
    assert "未来の日付は履歴として表示できません。" in response.text


def test_history_handles_minimum_date(client: TestClient):
    response = client.get("/history", params={"target_date": date.min.isoformat()})

    assert response.status_code == 200
    assert "前の日" in response.text
    assert 'aria-disabled="true"' in response.text


def test_history_empty_state(client: TestClient):
    target_date = date.today() - timedelta(days=30)
    response = client.get("/history", params={"target_date": target_date.isoformat()})

    assert response.status_code == 200
    assert "この日のメモはありません。" in response.text
    assert "この日の時間記録はありません。" in response.text


def test_reject_empty_task(client: TestClient):
    response = client.post("/tasks", data={"title": "   "})
    assert response.status_code == 200
    assert "タスク名を入力してください。" in response.text


def test_reject_invalid_minutes(client: TestClient):
    response = client.post("/time-entries", data={"minutes": 0, "note": ""})
    assert response.status_code == 200
    assert "時間は1〜1440分の整数で入力してください。" in response.text

    response = client.post("/time-entries", data={"minutes": -3, "note": ""})
    assert response.status_code == 200
    assert "時間は1〜1440分の整数で入力してください。" in response.text

    response = client.post("/time-entries", data={"minutes": "abc", "note": ""})
    assert response.status_code == 200
    assert "時間は1〜1440分の整数で入力してください。" in response.text

    response = client.post("/time-entries", data={"minutes": 10, "note": "a" * 256})
    assert response.status_code == 200
    assert "時間は1〜1440分の整数で入力してください。" in response.text


def test_non_existing_task_operations(client: TestClient):
    toggle_response = client.post("/tasks/999/toggle")
    delete_response = client.post("/tasks/999/delete")

    assert toggle_response.status_code == 404
    assert delete_response.status_code == 404
    assert "指定されたタスクが存在しません。" in toggle_response.text
    assert "指定されたタスクが存在しません。" in delete_response.text


def test_reject_too_long_memo(client: TestClient):
    response = client.post("/memo/today", data={"content": "x" * 5001})
    assert response.status_code == 400
    assert "メモ内容は5000文字以内で入力してください。" in response.text
