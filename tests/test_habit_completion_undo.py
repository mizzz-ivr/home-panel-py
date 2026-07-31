import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from app.crud import habit as habit_crud
from app.db import Base
from app.habit_completion_undo import (
    HABIT_COMPLETION_UNDO_KEY,
    UNDO_TTL,
    UndoResultStatus,
    clear_completion_undo,
    get_available_completion_undo,
    get_completion_habit_ids,
    record_completion_undo,
    undo_completion_change,
)
from app.models.app_setting import AppSetting
from app.models.habit import HabitCompletion

TARGET_DATE = date(2026, 7, 30)
NOW = datetime(2026, 7, 31, 4, 0, tzinfo=timezone.utc)


@pytest.fixture()
def db(tmp_path: Path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'test.db'}",
        connect_args={"check_same_thread": False},
    )
    session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    with session_factory() as session:
        yield session
    engine.dispose()


def create_habit(db, name: str) -> int:
    return habit_crud.create_habit(
        db,
        name,
        started_on=date(2026, 7, 1),
        weekdays=tuple(range(7)),
    ).id


def add_completion(db, habit_id: int) -> None:
    db.add(HabitCompletion(habit_id=habit_id, completed_on=TARGET_DATE))
    db.commit()


def count_settings(db) -> int:
    return int(
        db.scalar(
            select(func.count(AppSetting.key)).where(
                AppSetting.key == HABIT_COMPLETION_UNDO_KEY
            )
        )
        or 0
    )


def test_record_and_load_available_undo(db):
    habit_id = create_habit(db, "読書")
    add_completion(db, habit_id)

    action = record_completion_undo(
        db,
        TARGET_DATE,
        (),
        (habit_id,),
        source="single_complete",
        now=NOW,
    )

    assert action is not None
    assert action.label == "習慣を達成に変更"
    assert action.return_url == "/habits/history?target_date=2026-07-30"
    assert get_available_completion_undo(db, target_date=TARGET_DATE, now=NOW) == action
    assert get_available_completion_undo(
        db,
        target_date=date(2026, 7, 29),
        now=NOW,
    ) is None


def test_dashboard_source_returns_dashboard(db):
    habit_id = create_habit(db, "読書")
    add_completion(db, habit_id)

    action = record_completion_undo(
        db,
        TARGET_DATE,
        (),
        (habit_id,),
        source="dashboard_toggle",
        now=NOW,
    )

    assert action is not None
    assert action.return_url == "/"


def test_no_change_does_not_replace_existing_undo(db):
    habit_id = create_habit(db, "読書")
    add_completion(db, habit_id)
    first = record_completion_undo(
        db,
        TARGET_DATE,
        (),
        (habit_id,),
        source="single_complete",
        now=NOW,
    )

    second = record_completion_undo(
        db,
        TARGET_DATE,
        (habit_id,),
        (habit_id,),
        source="single_complete",
        now=NOW + timedelta(minutes=1),
    )

    assert second is None
    assert get_available_completion_undo(db, now=NOW + timedelta(minutes=1)) == first


def test_latest_change_replaces_previous_undo(db):
    first_id = create_habit(db, "読書")
    second_id = create_habit(db, "運動")
    add_completion(db, first_id)
    first = record_completion_undo(
        db,
        TARGET_DATE,
        (),
        (first_id,),
        source="single_complete",
        now=NOW,
    )
    add_completion(db, second_id)

    second = record_completion_undo(
        db,
        TARGET_DATE,
        (first_id,),
        (first_id, second_id),
        source="selected_complete",
        now=NOW + timedelta(minutes=1),
    )

    assert first is not None and second is not None
    assert second.token != first.token
    assert get_available_completion_undo(db, now=NOW + timedelta(minutes=1)) == second


def test_undo_restores_exact_previous_state_and_is_consumed(db):
    first_id = create_habit(db, "読書")
    second_id = create_habit(db, "運動")
    add_completion(db, first_id)
    before = get_completion_habit_ids(db, TARGET_DATE)
    add_completion(db, second_id)
    after = get_completion_habit_ids(db, TARGET_DATE)
    action = record_completion_undo(
        db,
        TARGET_DATE,
        before,
        after,
        source="selected_complete",
        now=NOW,
    )
    assert action is not None

    result = undo_completion_change(db, action.token, now=NOW + timedelta(minutes=1))

    assert result.status == UndoResultStatus.RESTORED
    assert get_completion_habit_ids(db, TARGET_DATE) == (first_id,)
    assert count_settings(db) == 0
    assert undo_completion_change(
        db,
        action.token,
        now=NOW + timedelta(minutes=1),
    ).status == UndoResultStatus.NOT_FOUND


def test_undo_restores_existing_inconsistent_records(db):
    habit_id = create_habit(db, "月曜だけ")
    add_completion(db, habit_id)
    action = record_completion_undo(
        db,
        TARGET_DATE,
        (habit_id,),
        (),
        source="bulk_clear",
        now=NOW,
    )
    db.query(HabitCompletion).delete()
    db.commit()

    result = undo_completion_change(db, action.token, now=NOW + timedelta(minutes=1))

    assert result.status == UndoResultStatus.RESTORED
    assert get_completion_habit_ids(db, TARGET_DATE) == (habit_id,)


def test_invalid_token_does_not_modify_or_consume_undo(db):
    habit_id = create_habit(db, "読書")
    add_completion(db, habit_id)
    action = record_completion_undo(
        db,
        TARGET_DATE,
        (),
        (habit_id,),
        source="single_complete",
        now=NOW,
    )

    result = undo_completion_change(db, "x" * 24, now=NOW + timedelta(minutes=1))

    assert result.status == UndoResultStatus.INVALID_TOKEN
    assert get_completion_habit_ids(db, TARGET_DATE) == (habit_id,)
    assert count_settings(db) == 1
    assert get_available_completion_undo(db, now=NOW + timedelta(minutes=1)) == action


def test_expired_undo_is_not_available_and_is_consumed_on_post(db):
    habit_id = create_habit(db, "読書")
    add_completion(db, habit_id)
    action = record_completion_undo(
        db,
        TARGET_DATE,
        (),
        (habit_id,),
        source="single_complete",
        now=NOW,
    )

    assert get_available_completion_undo(
        db,
        now=NOW + UNDO_TTL,
    ) is None
    result = undo_completion_change(db, action.token, now=NOW + UNDO_TTL)

    assert result.status == UndoResultStatus.EXPIRED
    assert get_completion_habit_ids(db, TARGET_DATE) == (habit_id,)
    assert count_settings(db) == 0


def test_state_change_rejects_and_consumes_stale_undo(db):
    first_id = create_habit(db, "読書")
    second_id = create_habit(db, "運動")
    add_completion(db, first_id)
    action = record_completion_undo(
        db,
        TARGET_DATE,
        (),
        (first_id,),
        source="single_complete",
        now=NOW,
    )
    add_completion(db, second_id)

    result = undo_completion_change(db, action.token, now=NOW + timedelta(minutes=1))

    assert result.status == UndoResultStatus.STATE_CHANGED
    assert get_completion_habit_ids(db, TARGET_DATE) == (first_id, second_id)
    assert count_settings(db) == 0


def test_missing_habit_rejects_restore(db):
    habit_id = create_habit(db, "読書")
    action = record_completion_undo(
        db,
        TARGET_DATE,
        (habit_id,),
        (),
        source="bulk_clear",
        now=NOW,
    )
    habit = habit_crud.get_habit(db, habit_id)
    db.delete(habit)
    db.commit()

    result = undo_completion_change(db, action.token, now=NOW + timedelta(minutes=1))

    assert result.status == UndoResultStatus.MISSING_HABIT
    assert count_settings(db) == 0


def test_corrupt_or_invalid_setting_is_ignored(db):
    db.add(AppSetting(key=HABIT_COMPLETION_UNDO_KEY, value="not-json"))
    db.commit()
    assert get_available_completion_undo(db, now=NOW) is None

    setting = db.get(AppSetting, HABIT_COMPLETION_UNDO_KEY)
    setting.value = json.dumps(
        {
            "version": 1,
            "token": "a" * 24,
            "target_date": TARGET_DATE.isoformat(),
            "before_habit_ids": [1, 1],
            "after_habit_ids": [],
            "source": "bulk_clear",
            "created_at": NOW.isoformat(),
            "expires_at": (NOW + timedelta(minutes=1)).isoformat(),
        }
    )
    db.commit()
    assert get_available_completion_undo(db, now=NOW) is None


def test_clear_completion_undo_is_idempotent(db):
    assert clear_completion_undo(db) is False
    habit_id = create_habit(db, "読書")
    add_completion(db, habit_id)
    record_completion_undo(
        db,
        TARGET_DATE,
        (),
        (habit_id,),
        source="single_complete",
        now=NOW,
    )

    assert clear_completion_undo(db) is True
    assert clear_completion_undo(db) is False
