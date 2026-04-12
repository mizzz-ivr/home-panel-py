from datetime import date
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
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)
    Base.metadata.create_all(bind=test_engine)

    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()


def test_top_page(client: TestClient):
    response = client.get("/")
    assert response.status_code == 200
    assert "Home Panel" in response.text


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


def test_non_existing_task_operations(client: TestClient):
    toggle_response = client.post("/tasks/999/toggle")
    delete_response = client.post("/tasks/999/delete")

    assert toggle_response.status_code == 404
    assert delete_response.status_code == 404
    assert toggle_response.json()["detail"] == "指定されたタスクが存在しません。"
    assert delete_response.json()["detail"] == "指定されたタスクが存在しません。"
