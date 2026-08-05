from datetime import date, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from app.db import Base, get_db
from app.global_search import SEARCH_RESULT_LIMIT_PER_CATEGORY, search_all
from app.main import app
from app.models.habit import Habit
from app.models.memo import DailyMemo
from app.models.task import Task
from app.models.time_entry import TimeEntry


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


def seed_cross_category_results(client: TestClient) -> None:
    session_factory = client.app.state.testing_session_factory
    with session_factory() as db:
        db.add_all(
            [
                Task(title="設計レビュー", is_done=False),
                DailyMemo(
                    memo_date=date(2026, 8, 1),
                    content="検索機能の設計メモを整理する",
                ),
                TimeEntry(
                    entry_date=date(2026, 8, 2),
                    category="個人開発",
                    minutes=90,
                    note="横断検索の設計を進める",
                ),
                Habit(name="毎日設計", is_active=True),
            ]
        )
        db.commit()


def test_search_page_finds_all_supported_categories(client: TestClient):
    seed_cross_category_results(client)

    response = client.get("/search?q=設計")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert "設計レビュー" in response.text
    assert "検索機能の設計メモを整理する" in response.text
    assert "横断検索の設計を進める" in response.text
    assert "毎日設計" in response.text
    assert 'href="/#todo-card"' in response.text
    assert 'href="/history?target_date=2026-08-01"' in response.text
    assert 'href="/history?target_date=2026-08-02"' in response.text
    assert 'href="/habits/manage#habit-' in response.text
    assert "4件" in response.text


def test_search_landing_page_does_not_require_query(client: TestClient):
    response = client.get("/search")

    assert response.status_code == 200
    assert "探したい言葉を入力してください" in response.text
    assert 'class="card search-summary"' not in response.text


@pytest.mark.parametrize("query", ["", " ", "a", "あ"])
def test_search_rejects_query_shorter_than_two_characters(
    client: TestClient,
    query: str,
):
    response = client.get("/search", params={"q": query})

    assert response.status_code == 400
    assert "検索語は2〜100文字で入力してください" in response.text


def test_search_rejects_query_longer_than_one_hundred_characters(client: TestClient):
    response = client.get("/search", params={"q": "あ" * 101})

    assert response.status_code == 400
    assert "検索語は2〜100文字で入力してください" in response.text


def test_percent_and_underscore_are_searched_as_literal_characters(client: TestClient):
    session_factory = client.app.state.testing_session_factory
    with session_factory() as db:
        db.add_all(
            [
                Task(title="進捗100%確認"),
                Task(title="進捗100X確認"),
                Task(title="コードA_B確認"),
                Task(title="コードACB確認"),
            ]
        )
        db.commit()

    percent_response = client.get("/search", params={"q": "100%"})
    underscore_response = client.get("/search", params={"q": "A_"})

    assert percent_response.status_code == 200
    assert "進捗100%確認" in percent_response.text
    assert "進捗100X確認" not in percent_response.text
    assert underscore_response.status_code == 200
    assert "コードA_B確認" in underscore_response.text
    assert "コードACB確認" not in underscore_response.text


def test_search_limits_each_category_and_orders_newest_first(client: TestClient):
    session_factory = client.app.state.testing_session_factory
    base_time = datetime(2026, 8, 1, 12, 0, 0)
    with session_factory() as db:
        for index in range(25):
            db.add(
                Task(
                    title=f"共通検索 {index:02d}",
                    updated_at=base_time + timedelta(minutes=index),
                )
            )
        db.commit()

        results = search_all(db, "共通検索")

    assert len(results.tasks) == SEARCH_RESULT_LIMIT_PER_CATEGORY
    assert results.tasks[0].title == "共通検索 24"
    assert results.tasks[-1].title == "共通検索 05"


def test_search_is_case_insensitive_for_ascii(client: TestClient):
    session_factory = client.app.state.testing_session_factory
    with session_factory() as db:
        db.add(Task(title="Release CHECK"))
        db.commit()

    response = client.get("/search", params={"q": "release check"})

    assert response.status_code == 200
    assert "Release CHECK" in response.text


def test_search_escapes_saved_content_and_query(client: TestClient):
    session_factory = client.app.state.testing_session_factory
    with session_factory() as db:
        db.add(Task(title="<script>alert(1)</script>設計"))
        db.commit()

    response = client.get("/search", params={"q": "<script>"})

    assert response.status_code == 200
    assert "<script>alert(1)</script>" not in response.text
    assert "&lt;script&gt;alert(1)&lt;/script&gt;設計" in response.text
    assert 'value="&lt;script&gt;"' in response.text


def test_search_does_not_modify_database(client: TestClient):
    seed_cross_category_results(client)
    session_factory = client.app.state.testing_session_factory

    def counts() -> tuple[int, int, int, int]:
        with session_factory() as db:
            return (
                db.scalar(select(func.count(Task.id))) or 0,
                db.scalar(select(func.count(DailyMemo.id))) or 0,
                db.scalar(select(func.count(TimeEntry.id))) or 0,
                db.scalar(select(func.count(Habit.id))) or 0,
            )

    before = counts()
    response = client.get("/search?q=設計")
    after = counts()

    assert response.status_code == 200
    assert after == before


def test_dashboard_has_global_search_form_and_result_anchors(client: TestClient):
    session_factory = client.app.state.testing_session_factory
    with session_factory() as db:
        habit = Habit(name="読書", is_active=True)
        db.add(habit)
        db.commit()
        habit_id = habit.id

    dashboard = client.get("/")
    habit_management = client.get("/habits/manage")

    assert dashboard.status_code == 200
    assert 'action="/search"' in dashboard.text
    assert 'name="q"' in dashboard.text
    assert 'id="todo-card"' in dashboard.text
    assert habit_management.status_code == 200
    assert f'id="habit-{habit_id}"' in habit_management.text
