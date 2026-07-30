from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from app import habit_report_routes
from app.crud import habit as habit_crud
from app.db import Base, get_db
from app.habit_completion import (
    BulkCompletionUpdateStatus,
    complete_all_expected_on,
)
from app.main import app
from app.models.habit import HabitCompletion

FIXED_TODAY = date(2026, 7, 30)
TARGET_DATE = date(2026, 7, 28)


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
    name: str,
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


def add_completion(client: TestClient, habit_id: int, target_date: date) -> None:
    session_factory = client.app.state.testing_session_factory
    with session_factory() as db:
        db.add(HabitCompletion(habit_id=habit_id, completed_on=target_date))
        db.commit()


def count_completion(
    client: TestClient,
    habit_id: int,
    target_date: date,
) -> int:
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


def count_all_completions(client: TestClient, target_date: date) -> int:
    session_factory = client.app.state.testing_session_factory
    with session_factory() as db:
        return int(
            db.scalar(
                select(func.count(HabitCompletion.id)).where(
                    HabitCompletion.completed_on == target_date
                )
            )
            or 0
        )


def post_bulk(client: TestClient, target_date: str, action: str):
    return client.post(
        "/habits/completions/bulk",
        data={"target_date": target_date, "action": action},
        follow_redirects=False,
    )


def test_bulk_complete_adds_only_expected_habits(client: TestClient):
    daily_id = create_habit(client, "日記")
    monday_only_id = create_habit(client, "月曜だけ", weekdays=(0,))

    response = post_bulk(client, TARGET_DATE.isoformat(), "complete_expected")

    assert response.status_code == 303
    assert response.headers["location"] == (
        "/habits/history?target_date=2026-07-28"
    )
    assert count_completion(client, daily_id, TARGET_DATE) == 1
    assert count_completion(client, monday_only_id, TARGET_DATE) == 0


def test_bulk_complete_is_idempotent_and_keeps_inconsistent_records(
    client: TestClient,
):
    first_id = create_habit(client, "読書")
    second_id = create_habit(client, "運動")
    outside_schedule_id = create_habit(client, "月曜だけ", weekdays=(0,))
    add_completion(client, first_id, TARGET_DATE)
    add_completion(client, outside_schedule_id, TARGET_DATE)

    first = post_bulk(client, TARGET_DATE.isoformat(), "complete_expected")
    second = post_bulk(client, TARGET_DATE.isoformat(), "complete_expected")

    assert first.status_code == 303
    assert second.status_code == 303
    assert count_completion(client, first_id, TARGET_DATE) == 1
    assert count_completion(client, second_id, TARGET_DATE) == 1
    assert count_completion(client, outside_schedule_id, TARGET_DATE) == 1
    assert count_all_completions(client, TARGET_DATE) == 3


def test_bulk_clear_removes_all_records_including_inconsistent_records(
    client: TestClient,
):
    expected_id = create_habit(client, "読書")
    outside_schedule_id = create_habit(client, "月曜だけ", weekdays=(0,))
    add_completion(client, expected_id, TARGET_DATE)
    add_completion(client, outside_schedule_id, TARGET_DATE)

    first = post_bulk(client, TARGET_DATE.isoformat(), "clear_all")
    second = post_bulk(client, TARGET_DATE.isoformat(), "clear_all")

    assert first.status_code == 303
    assert second.status_code == 303
    assert count_all_completions(client, TARGET_DATE) == 0


def test_bulk_complete_includes_archived_habit_during_active_period(
    client: TestClient,
):
    archived_id = create_habit(client, "終了済み")
    session_factory = client.app.state.testing_session_factory
    with session_factory() as db:
        habit_crud.archive_habit(db, archived_id, archived_on=date(2026, 7, 22))

    response = post_bulk(client, "2026-07-21", "complete_expected")

    assert response.status_code == 303
    assert count_completion(client, archived_id, date(2026, 7, 21)) == 1


def test_bulk_complete_skips_stopped_period(client: TestClient):
    active_id = create_habit(client, "継続中")
    stopped_id = create_habit(client, "一時停止")
    session_factory = client.app.state.testing_session_factory
    with session_factory() as db:
        habit_crud.archive_habit(db, stopped_id, archived_on=date(2026, 7, 22))
        habit_crud.restore_habit(db, stopped_id, restored_on=date(2026, 7, 24))

    response = post_bulk(client, "2026-07-23", "complete_expected")

    assert response.status_code == 303
    assert count_completion(client, active_id, date(2026, 7, 23)) == 1
    assert count_completion(client, stopped_id, date(2026, 7, 23)) == 0


@pytest.mark.parametrize(
    ("target_date", "action", "message"),
    [
        ("20260728", "complete_expected", "YYYY-MM-DD"),
        ("2026-02-30", "complete_expected", "YYYY-MM-DD"),
        ("2026-07-31", "complete_expected", "未来の日付"),
        ("2026-07-28", "complete", "一括操作が不正"),
        ("2026-07-28", "delete", "一括操作が不正"),
    ],
)
def test_bulk_edit_rejects_invalid_input(
    client: TestClient,
    target_date: str,
    action: str,
    message: str,
):
    create_habit(client, "読書")

    response = post_bulk(client, target_date, action)

    assert response.status_code == 400
    assert message in response.text


def test_history_page_shows_available_bulk_actions(client: TestClient):
    first_id = create_habit(client, "読書")
    create_habit(client, "運動")
    add_completion(client, first_id, TARGET_DATE)

    response = client.get("/habits/history?target_date=2026-07-28")

    assert response.status_code == 200
    assert "この日の一括操作" in response.text
    assert "対象習慣をすべて達成" in response.text
    assert "この日の達成をすべて取り消す" in response.text
    assert 'action="/habits/completions/bulk"' in response.text
    assert 'name="action" value="complete_expected"' in response.text
    assert 'name="action" value="clear_all"' in response.text
    assert "data-confirm=" in response.text


def test_history_page_hides_complete_all_after_all_expected_are_completed(
    client: TestClient,
):
    habit_id = create_habit(client, "読書")
    add_completion(client, habit_id, TARGET_DATE)

    response = client.get("/habits/history?target_date=2026-07-28")

    assert response.status_code == 200
    assert "対象習慣をすべて達成" not in response.text
    assert "この日の達成をすべて取り消す" in response.text


def test_history_page_hides_bulk_section_without_targets_or_records(
    client: TestClient,
):
    create_habit(client, "月曜だけ", weekdays=(0,))

    response = client.get("/habits/history?target_date=2026-07-28")

    assert response.status_code == 200
    assert "この日の一括操作" not in response.text
    assert "対象習慣をすべて達成" not in response.text
    assert "この日の達成をすべて取り消す" not in response.text


def test_bulk_complete_commits_all_additions_once(client: TestClient, monkeypatch):
    create_habit(client, "読書")
    create_habit(client, "運動")
    session_factory = client.app.state.testing_session_factory

    with session_factory() as db:
        original_commit = db.commit
        commit_count = 0

        def counting_commit():
            nonlocal commit_count
            commit_count += 1
            original_commit()

        monkeypatch.setattr(db, "commit", counting_commit)
        result = complete_all_expected_on(
            db,
            TARGET_DATE,
            latest_editable_date=FIXED_TODAY,
        )

    assert result.status == BulkCompletionUpdateStatus.UPDATED
    assert result.created_count == 2
    assert result.target_count == 2
    assert commit_count == 1
    assert count_all_completions(client, TARGET_DATE) == 2
