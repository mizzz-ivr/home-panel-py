from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from app import habit_report_routes
from app.crud import habit as habit_crud
from app.db import Base, get_db
from app.habit_selected_completion import (
    SelectedCompletionUpdateStatus,
    set_selected_completions_on,
)
from app.main import app
from app.models.habit import HabitCompletion

FIXED_TODAY = date(2026, 7, 31)
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


def count_completion(client: TestClient, habit_id: int, target_date: date) -> int:
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


def post_selected(
    client: TestClient,
    habit_ids: list[str],
    *,
    target_date: str = "2026-07-28",
    completed: str = "true",
):
    return client.post(
        "/habits/completions/selected",
        data={
            "target_date": target_date,
            "completed": completed,
            "habit_ids": habit_ids,
        },
        follow_redirects=False,
    )


def test_selected_complete_updates_only_selected_expected_habits(client: TestClient):
    first_id = create_habit(client, "読書")
    second_id = create_habit(client, "運動")
    unselected_id = create_habit(client, "日記")

    response = post_selected(client, [str(first_id), str(second_id)])

    assert response.status_code == 303
    assert response.headers["location"] == (
        "/habits/history?target_date=2026-07-28"
    )
    assert count_completion(client, first_id, TARGET_DATE) == 1
    assert count_completion(client, second_id, TARGET_DATE) == 1
    assert count_completion(client, unselected_id, TARGET_DATE) == 0


def test_selected_clear_removes_only_selected_existing_records(client: TestClient):
    first_id = create_habit(client, "読書")
    second_id = create_habit(client, "運動")
    remaining_id = create_habit(client, "日記")
    for habit_id in (first_id, second_id, remaining_id):
        add_completion(client, habit_id, TARGET_DATE)

    response = post_selected(
        client,
        [str(first_id), str(second_id)],
        completed="false",
    )

    assert response.status_code == 303
    assert count_completion(client, first_id, TARGET_DATE) == 0
    assert count_completion(client, second_id, TARGET_DATE) == 0
    assert count_completion(client, remaining_id, TARGET_DATE) == 1


def test_selected_operations_are_idempotent(client: TestClient):
    habit_id = create_habit(client, "読書")

    assert post_selected(client, [str(habit_id)]).status_code == 303
    assert post_selected(client, [str(habit_id)]).status_code == 303
    assert count_completion(client, habit_id, TARGET_DATE) == 1

    assert post_selected(
        client,
        [str(habit_id)],
        completed="false",
    ).status_code == 303
    assert post_selected(
        client,
        [str(habit_id)],
        completed="false",
    ).status_code == 303
    assert count_completion(client, habit_id, TARGET_DATE) == 0


def test_mixed_not_expected_selection_rejects_all_without_partial_update(
    client: TestClient,
):
    expected_id = create_habit(client, "読書")
    monday_only_id = create_habit(client, "月曜だけ", weekdays=(0,))

    response = post_selected(client, [str(expected_id), str(monday_only_id)])

    assert response.status_code == 400
    assert "有効期間または対象曜日の範囲外" in response.text
    assert count_completion(client, expected_id, TARGET_DATE) == 0
    assert count_completion(client, monday_only_id, TARGET_DATE) == 0


def test_mixed_unknown_selection_rejects_all_without_partial_update(
    client: TestClient,
):
    expected_id = create_habit(client, "読書")

    response = post_selected(client, [str(expected_id), "9999"])

    assert response.status_code == 404
    assert "一部が存在しません" in response.text
    assert count_completion(client, expected_id, TARGET_DATE) == 0


@pytest.mark.parametrize(
    "habit_ids",
    [
        [],
        ["1", "1"],
        ["0"],
        ["-1"],
        ["abc"],
        ["1.0"],
    ],
)
def test_selected_edit_rejects_empty_duplicate_or_malformed_ids(
    client: TestClient,
    habit_ids: list[str],
):
    habit_id = create_habit(client, "読書")
    if habit_ids == ["1", "1"]:
        habit_ids = [str(habit_id), str(habit_id)]

    response = post_selected(client, habit_ids)

    assert response.status_code == 400
    assert count_completion(client, habit_id, TARGET_DATE) == 0


@pytest.mark.parametrize(
    ("target_date", "completed", "message"),
    [
        ("20260728", "true", "YYYY-MM-DD"),
        ("2026-02-30", "true", "YYYY-MM-DD"),
        ("2026-08-01", "true", "未来の日付"),
        ("2026-07-28", "yes", "達成状態が不正"),
    ],
)
def test_selected_edit_rejects_invalid_date_or_state(
    client: TestClient,
    target_date: str,
    completed: str,
    message: str,
):
    habit_id = create_habit(client, "読書")

    response = post_selected(
        client,
        [str(habit_id)],
        target_date=target_date,
        completed=completed,
    )

    assert response.status_code == 400
    assert message in response.text
    assert count_all_completions(client, TARGET_DATE) == 0


def test_archived_habit_can_be_selected_during_its_active_period(
    client: TestClient,
):
    habit_id = create_habit(client, "終了済み")
    session_factory = client.app.state.testing_session_factory
    with session_factory() as db:
        habit_crud.archive_habit(db, habit_id, archived_on=date(2026, 7, 29))

    response = post_selected(
        client,
        [str(habit_id)],
        target_date="2026-07-28",
    )

    assert response.status_code == 303
    assert count_completion(client, habit_id, TARGET_DATE) == 1


def test_stopped_period_in_mixed_selection_rejects_all(client: TestClient):
    expected_id = create_habit(client, "継続中")
    stopped_id = create_habit(client, "一時停止")
    session_factory = client.app.state.testing_session_factory
    with session_factory() as db:
        habit_crud.archive_habit(db, stopped_id, archived_on=date(2026, 7, 27))
        habit_crud.restore_habit(db, stopped_id, restored_on=date(2026, 7, 29))

    response = post_selected(client, [str(expected_id), str(stopped_id)])

    assert response.status_code == 400
    assert count_completion(client, expected_id, TARGET_DATE) == 0
    assert count_completion(client, stopped_id, TARGET_DATE) == 0


def test_selected_clear_can_remove_inconsistent_record(client: TestClient):
    habit_id = create_habit(client, "月曜だけ", weekdays=(0,))
    add_completion(client, habit_id, TARGET_DATE)

    response = post_selected(client, [str(habit_id)], completed="false")

    assert response.status_code == 303
    assert count_completion(client, habit_id, TARGET_DATE) == 0


def test_selected_complete_commits_multiple_additions_once(
    client: TestClient,
    monkeypatch,
):
    first_id = create_habit(client, "読書")
    second_id = create_habit(client, "運動")
    session_factory = client.app.state.testing_session_factory

    with session_factory() as db:
        original_commit = db.commit
        commit_count = 0

        def counting_commit():
            nonlocal commit_count
            commit_count += 1
            original_commit()

        monkeypatch.setattr(db, "commit", counting_commit)
        result = set_selected_completions_on(
            db,
            [first_id, second_id],
            TARGET_DATE,
            completed=True,
            latest_editable_date=FIXED_TODAY,
        )

    assert result.status == SelectedCompletionUpdateStatus.UPDATED
    assert result.updated_count == 2
    assert commit_count == 1
    assert count_all_completions(client, TARGET_DATE) == 2


def test_selected_clear_commits_multiple_deletions_once(
    client: TestClient,
    monkeypatch,
):
    first_id = create_habit(client, "読書")
    second_id = create_habit(client, "運動")
    add_completion(client, first_id, TARGET_DATE)
    add_completion(client, second_id, TARGET_DATE)
    session_factory = client.app.state.testing_session_factory

    with session_factory() as db:
        original_commit = db.commit
        commit_count = 0

        def counting_commit():
            nonlocal commit_count
            commit_count += 1
            original_commit()

        monkeypatch.setattr(db, "commit", counting_commit)
        result = set_selected_completions_on(
            db,
            [first_id, second_id],
            TARGET_DATE,
            completed=False,
            latest_editable_date=FIXED_TODAY,
        )

    assert result.status == SelectedCompletionUpdateStatus.UPDATED
    assert result.updated_count == 2
    assert commit_count == 1
    assert count_all_completions(client, TARGET_DATE) == 0


def test_history_page_wires_checkboxes_to_external_selected_form(
    client: TestClient,
):
    first_id = create_habit(client, "読書")
    second_id = create_habit(client, "運動")

    response = client.get("/habits/history?target_date=2026-07-28")
    normalized_html = " ".join(response.text.split())

    assert response.status_code == 200
    assert 'id="selected-habit-completion-form"' in normalized_html
    assert 'action="/habits/completions/selected"' in normalized_html
    assert 'name="completed" value="true"' in normalized_html
    assert 'name="completed" value="false"' in normalized_html
    assert normalized_html.count('name="habit_ids"') == 2
    assert f'value="{first_id}"' in normalized_html
    assert f'value="{second_id}"' in normalized_html
    assert normalized_html.count('form="selected-habit-completion-form"') == 2
    assert "選択した習慣を達成" in normalized_html
    assert "選択した達成を取り消す" in normalized_html
    assert "data-confirm=" in normalized_html
