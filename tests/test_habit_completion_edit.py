from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from app import habit_report_routes
from app.crud import habit as habit_crud
from app.db import Base, get_db
from app.main import app
from app.models.habit import HabitCompletion

FIXED_TODAY = date(2026, 7, 30)


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
    name: str = "読書",
    *,
    started_on: date = date(2026, 7, 20),
    weekdays: tuple[int, ...] = tuple(range(7)),
) -> int:
    session_factory = client.app.state.testing_session_factory
    with session_factory() as db:
        habit = habit_crud.create_habit(
            db,
            name,
            started_on=started_on,
            weekdays=weekdays,
        )
        return habit.id


def count_completions(client: TestClient, habit_id: int, target_date: date) -> int:
    session_factory = client.app.state.testing_session_factory
    with session_factory() as db:
        return int(
            db.scalar(
                select(func.count(HabitCompletion.id)).where(
                    HabitCompletion.habit_id == habit_id,
                    HabitCompletion.completed_on == target_date,
                )
            )
            or 0
        )


def post_completion(
    client: TestClient,
    habit_id: int,
    target_date: str,
    completed: str,
):
    return client.post(
        f"/habits/{habit_id}/completion",
        data={"target_date": target_date, "completed": completed},
        follow_redirects=False,
    )


def test_past_completion_can_be_added_and_removed(client: TestClient):
    habit_id = create_habit(client)
    target_date = date(2026, 7, 28)

    created = post_completion(client, habit_id, target_date.isoformat(), "true")

    assert created.status_code == 303
    assert created.headers["location"] == (
        "/habits/history?target_date=2026-07-28"
    )
    assert count_completions(client, habit_id, target_date) == 1

    deleted = post_completion(client, habit_id, target_date.isoformat(), "false")

    assert deleted.status_code == 303
    assert count_completions(client, habit_id, target_date) == 0


def test_completion_update_is_idempotent(client: TestClient):
    habit_id = create_habit(client)
    target_date = date(2026, 7, 28)

    assert post_completion(client, habit_id, target_date.isoformat(), "true").status_code == 303
    assert post_completion(client, habit_id, target_date.isoformat(), "true").status_code == 303
    assert count_completions(client, habit_id, target_date) == 1

    assert post_completion(client, habit_id, target_date.isoformat(), "false").status_code == 303
    assert post_completion(client, habit_id, target_date.isoformat(), "false").status_code == 303
    assert count_completions(client, habit_id, target_date) == 0


def test_archived_habit_can_be_edited_only_during_active_period(client: TestClient):
    habit_id = create_habit(client, "運動")
    session_factory = client.app.state.testing_session_factory
    with session_factory() as db:
        habit_crud.archive_habit(db, habit_id, archived_on=date(2026, 7, 22))

    active_day = post_completion(client, habit_id, "2026-07-21", "true")
    after_archive = post_completion(client, habit_id, "2026-07-23", "true")

    assert active_day.status_code == 303
    assert after_archive.status_code == 400
    assert "有効期間または対象曜日の範囲外" in after_archive.text
    assert count_completions(client, habit_id, date(2026, 7, 21)) == 1
    assert count_completions(client, habit_id, date(2026, 7, 23)) == 0


def test_stopped_period_rejects_new_completion(client: TestClient):
    habit_id = create_habit(client, "朝活")
    session_factory = client.app.state.testing_session_factory
    with session_factory() as db:
        habit_crud.archive_habit(db, habit_id, archived_on=date(2026, 7, 22))
        habit_crud.restore_habit(db, habit_id, restored_on=date(2026, 7, 24))

    response = post_completion(client, habit_id, "2026-07-23", "true")

    assert response.status_code == 400
    assert count_completions(client, habit_id, date(2026, 7, 23)) == 0


def test_non_scheduled_weekday_rejects_new_completion(client: TestClient):
    habit_id = create_habit(client, weekdays=(0,))

    response = post_completion(client, habit_id, "2026-07-21", "true")

    assert response.status_code == 400
    assert "有効期間または対象曜日の範囲外" in response.text
    assert count_completions(client, habit_id, date(2026, 7, 21)) == 0


def test_inconsistent_completion_can_be_removed(client: TestClient):
    habit_id = create_habit(client, weekdays=(0,))
    target_date = date(2026, 7, 21)
    session_factory = client.app.state.testing_session_factory
    with session_factory() as db:
        db.add(HabitCompletion(habit_id=habit_id, completed_on=target_date))
        db.commit()

    response = post_completion(client, habit_id, target_date.isoformat(), "false")

    assert response.status_code == 303
    assert count_completions(client, habit_id, target_date) == 0


@pytest.mark.parametrize(
    ("target_date", "completed", "message"),
    [
        ("20260728", "true", "YYYY-MM-DD"),
        ("2026-02-30", "true", "YYYY-MM-DD"),
        ("2026-07-31", "true", "未来の日付"),
        ("2026-07-28", "1", "達成状態が不正"),
        ("2026-07-28", "yes", "達成状態が不正"),
    ],
)
def test_completion_edit_rejects_invalid_input(
    client: TestClient,
    target_date: str,
    completed: str,
    message: str,
):
    habit_id = create_habit(client)

    response = post_completion(client, habit_id, target_date, completed)

    assert response.status_code == 400
    assert message in response.text


def test_completion_edit_returns_404_for_unknown_habit(client: TestClient):
    response = post_completion(client, 9999, "2026-07-28", "true")

    assert response.status_code == 404
    assert "指定された習慣が存在しません" in response.text


def test_history_page_shows_explicit_completion_actions(client: TestClient):
    habit_id = create_habit(client)

    before = client.get("/habits/history?target_date=2026-07-28")
    assert before.status_code == 200
    assert "達成にする" in before.text
    assert f'action="/habits/{habit_id}/completion"' in before.text
    assert 'name="completed" value="true"' in before.text

    post_completion(client, habit_id, "2026-07-28", "true")
    after = client.get("/habits/history?target_date=2026-07-28")

    assert after.status_code == 200
    assert "達成を取り消す" in after.text
    assert 'name="completed" value="false"' in after.text


def test_target_outside_schedule_has_no_add_action(client: TestClient):
    create_habit(client, weekdays=(0,))

    response = client.get("/habits/history?target_date=2026-07-21")

    assert response.status_code == 200
    assert "対象外" in response.text
    assert "達成にする" not in response.text
