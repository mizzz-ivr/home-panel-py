from datetime import date, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.orm import sessionmaker

from app.crud import habit as habit_crud
from app.db import Base, get_db
from app.habit_report import build_daily_report
from app.main import app
from app.migrations import migrate_habit_archived_at
from app.models.habit import Habit, HabitCompletion


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


def test_dashboard_links_to_habit_management(client: TestClient):
    response = client.get("/")

    assert response.status_code == 200
    assert 'href="/habits/manage"' in response.text
    assert "習慣を管理" in response.text


def test_management_page_lists_active_and_archived_habits(client: TestClient):
    client.post("/habits", data={"name": "読書"})
    client.post("/habits", data={"name": "運動"})
    client.post("/habits/2/archive")

    response = client.get("/habits/manage")

    assert response.status_code == 200
    assert "アクティブな習慣" in response.text
    assert "終了済みの習慣" in response.text
    assert "読書" in response.text
    assert "運動" in response.text
    assert "再開する" in response.text


def test_rename_active_habit_preserves_history(client: TestClient):
    client.post("/habits", data={"name": "読書"})
    client.post("/habits/1/toggle-today")

    response = client.post(
        "/habits/1/rename",
        data={"name": "30分読書"},
        follow_redirects=False,
    )

    assert response.status_code == 303
    session_factory = client.app.state.testing_session_factory
    with session_factory() as db:
        habit = db.get(Habit, 1)
        assert habit is not None
        assert habit.name == "30分読書"
        assert db.scalar(select(HabitCompletion).where(HabitCompletion.habit_id == 1)) is not None


def test_rename_rejects_blank_duplicate_and_missing_habit(client: TestClient):
    client.post("/habits", data={"name": "読書"})
    client.post("/habits", data={"name": "運動"})

    assert client.post("/habits/1/rename", data={"name": "   "}).status_code == 400
    duplicate = client.post("/habits/2/rename", data={"name": "読書"})
    assert duplicate.status_code == 400
    assert "同じ名前" in duplicate.text
    assert client.post("/habits/999/rename", data={"name": "不存在"}).status_code == 404


def test_archive_sets_fixed_archived_at_and_rename_does_not_change_it(client: TestClient):
    client.post("/habits", data={"name": "日記"})
    client.post("/habits/1/archive")

    session_factory = client.app.state.testing_session_factory
    with session_factory() as db:
        habit = db.get(Habit, 1)
        assert habit is not None
        assert habit.archived_at is not None
        archived_at = habit.archived_at

    client.post("/habits/1/rename", data={"name": "夜の日記"})

    with session_factory() as db:
        habit = db.get(Habit, 1)
        assert habit is not None
        assert habit.name == "夜の日記"
        assert habit.archived_at == archived_at


def test_restore_habit_keeps_history_and_clears_archived_at(client: TestClient):
    client.post("/habits", data={"name": "ストレッチ"})
    client.post("/habits/1/toggle-today")
    client.post("/habits/1/archive")

    response = client.post("/habits/1/restore", follow_redirects=False)

    assert response.status_code == 303
    session_factory = client.app.state.testing_session_factory
    with session_factory() as db:
        habit = db.get(Habit, 1)
        assert habit is not None
        assert habit.is_active is True
        assert habit.archived_at is None
        assert db.scalar(select(HabitCompletion).where(HabitCompletion.habit_id == 1)) is not None


def test_restore_rejects_duplicate_name_active_limit_and_invalid_state(client: TestClient):
    client.post("/habits", data={"name": "読書"})
    client.post("/habits/1/archive")
    client.post("/habits", data={"name": "読書"})

    duplicate = client.post("/habits/1/restore")
    assert duplicate.status_code == 400
    assert "同じ名前" in duplicate.text
    assert client.post("/habits/2/restore").status_code == 404
    assert client.post("/habits/999/restore").status_code == 404

    session_factory = client.app.state.testing_session_factory
    with session_factory() as db:
        archived = db.get(Habit, 1)
        assert archived is not None
        archived.name = "再開対象"
        for index in range(habit_crud.MAX_ACTIVE_HABITS - 1):
            db.add(Habit(name=f"上限{index}"))
        db.commit()

    limited = client.post("/habits/1/restore")
    assert limited.status_code == 400
    assert "最大20件" in limited.text


def test_report_uses_archived_at_even_after_archived_habit_is_renamed(client: TestClient):
    session_factory = client.app.state.testing_session_factory
    archived_at = datetime(2026, 7, 10, 12, 0, 0)
    with session_factory() as db:
        habit = Habit(
            name="旧習慣",
            is_active=False,
            archived_at=archived_at,
            created_at=datetime(2026, 7, 1, 9, 0, 0),
            updated_at=datetime(2026, 7, 20, 9, 0, 0),
        )
        db.add(habit)
        db.commit()

        on_end_date = build_daily_report(db, date(2026, 7, 10))
        after_end_date = build_daily_report(db, date(2026, 7, 11))

    assert on_end_date["expected_count"] == 1
    assert after_end_date["expected_count"] == 0


def test_migration_adds_archived_at_and_backfills_existing_archived_habits(tmp_path: Path):
    engine = create_engine(f"sqlite:///{tmp_path / 'legacy.db'}")
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE habits ("
                "id INTEGER PRIMARY KEY, name VARCHAR(100) NOT NULL, "
                "is_active BOOLEAN NOT NULL, created_at DATETIME NOT NULL, "
                "updated_at DATETIME NOT NULL)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO habits "
                "(id, name, is_active, created_at, updated_at) VALUES "
                "(1, '終了済み', 0, '2026-07-01 00:00:00', '2026-07-10 00:00:00'), "
                "(2, '利用中', 1, '2026-07-01 00:00:00', '2026-07-11 00:00:00')"
            )
        )

    assert migrate_habit_archived_at(engine) is True
    assert migrate_habit_archived_at(engine) is False
    assert "archived_at" in {column["name"] for column in inspect(engine).get_columns("habits")}

    with engine.connect() as connection:
        rows = connection.execute(
            text("SELECT id, archived_at FROM habits ORDER BY id")
        ).all()
    assert rows[0].archived_at == "2026-07-10 00:00:00"
    assert rows[1].archived_at is None
    engine.dispose()
