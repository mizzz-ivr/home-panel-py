from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import StrEnum

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.crud import habit as habit_crud
from app.habit_report import (
    group_periods_by_habit,
    is_habit_expected_on as is_report_habit_expected_on,
)
from app.models.habit import HabitCompletion


class CompletionUpdateResult(StrEnum):
    CREATED = "created"
    DELETED = "deleted"
    UNCHANGED = "unchanged"
    NOT_FOUND = "not_found"
    NOT_EXPECTED = "not_expected"
    FUTURE_DATE = "future_date"


class BulkCompletionUpdateStatus(StrEnum):
    UPDATED = "updated"
    UNCHANGED = "unchanged"
    FUTURE_DATE = "future_date"


@dataclass(frozen=True)
class BulkCompletionUpdate:
    status: BulkCompletionUpdateStatus
    target_count: int = 0
    created_count: int = 0
    deleted_count: int = 0


def get_completion(
    db: Session,
    habit_id: int,
    target_date: date,
) -> HabitCompletion | None:
    return db.scalar(
        select(HabitCompletion).where(
            HabitCompletion.habit_id == habit_id,
            HabitCompletion.completed_on == target_date,
        )
    )


def list_completions_on(db: Session, target_date: date) -> list[HabitCompletion]:
    return list(
        db.scalars(
            select(HabitCompletion)
            .where(HabitCompletion.completed_on == target_date)
            .order_by(HabitCompletion.habit_id.asc(), HabitCompletion.id.asc())
        ).all()
    )


def get_expected_habit_ids(db: Session, target_date: date) -> set[int]:
    habits = habit_crud.list_all_habits(db)
    active_periods_by_habit = group_periods_by_habit(
        habit_crud.list_active_periods(db)
    )
    schedule_periods_by_habit = group_periods_by_habit(
        habit_crud.list_schedule_periods(db)
    )
    return {
        habit.id
        for habit in habits
        if is_report_habit_expected_on(
            habit,
            target_date,
            active_periods_by_habit.get(habit.id),
            schedule_periods_by_habit.get(habit.id),
        )
    }


def set_completion_on(
    db: Session,
    habit_id: int,
    target_date: date,
    *,
    completed: bool,
    latest_editable_date: date,
) -> CompletionUpdateResult:
    """指定日の達成状態を明示的に設定する。

    追加時は有効期間と曜日設定を検証する。取り消し時は、対象外曜日などに
    残っている不整合記録も修復できるよう、既存記録があれば削除する。
    """

    if target_date > latest_editable_date:
        return CompletionUpdateResult.FUTURE_DATE

    if habit_crud.get_habit(db, habit_id) is None:
        return CompletionUpdateResult.NOT_FOUND

    existing = get_completion(db, habit_id, target_date)

    if completed:
        if existing is not None:
            return CompletionUpdateResult.UNCHANGED
        if habit_id not in get_expected_habit_ids(db, target_date):
            return CompletionUpdateResult.NOT_EXPECTED

        db.add(HabitCompletion(habit_id=habit_id, completed_on=target_date))
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            if get_completion(db, habit_id, target_date) is not None:
                return CompletionUpdateResult.UNCHANGED
            raise
        return CompletionUpdateResult.CREATED

    if existing is None:
        return CompletionUpdateResult.UNCHANGED

    db.delete(existing)
    db.commit()
    return CompletionUpdateResult.DELETED


def complete_all_expected_on(
    db: Session,
    target_date: date,
    *,
    latest_editable_date: date,
) -> BulkCompletionUpdate:
    """対象日の達成対象を1トランザクションですべて達成済みにする。"""

    if target_date > latest_editable_date:
        return BulkCompletionUpdate(BulkCompletionUpdateStatus.FUTURE_DATE)

    expected_ids = get_expected_habit_ids(db, target_date)
    existing_ids = {
        completion.habit_id for completion in list_completions_on(db, target_date)
    }
    missing_ids = expected_ids - existing_ids
    if not missing_ids:
        return BulkCompletionUpdate(
            BulkCompletionUpdateStatus.UNCHANGED,
            target_count=len(expected_ids),
        )

    for habit_id in sorted(missing_ids):
        db.add(HabitCompletion(habit_id=habit_id, completed_on=target_date))

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing_ids = {
            completion.habit_id for completion in list_completions_on(db, target_date)
        }
        missing_ids = expected_ids - existing_ids
        if not missing_ids:
            return BulkCompletionUpdate(
                BulkCompletionUpdateStatus.UNCHANGED,
                target_count=len(expected_ids),
            )
        for habit_id in sorted(missing_ids):
            db.add(HabitCompletion(habit_id=habit_id, completed_on=target_date))
        db.commit()

    return BulkCompletionUpdate(
        BulkCompletionUpdateStatus.UPDATED,
        target_count=len(expected_ids),
        created_count=len(missing_ids),
    )


def clear_all_completions_on(
    db: Session,
    target_date: date,
    *,
    latest_editable_date: date,
) -> BulkCompletionUpdate:
    """対象日の達成記録を不整合記録も含めて1トランザクションで削除する。"""

    if target_date > latest_editable_date:
        return BulkCompletionUpdate(BulkCompletionUpdateStatus.FUTURE_DATE)

    completions = list_completions_on(db, target_date)
    if not completions:
        return BulkCompletionUpdate(BulkCompletionUpdateStatus.UNCHANGED)

    for completion in completions:
        db.delete(completion)
    db.commit()
    return BulkCompletionUpdate(
        BulkCompletionUpdateStatus.UPDATED,
        target_count=len(completions),
        deleted_count=len(completions),
    )
