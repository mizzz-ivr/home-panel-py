from __future__ import annotations

from datetime import date
from enum import StrEnum

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.crud import habit as habit_crud
from app.models.habit import HabitCompletion


class CompletionUpdateResult(StrEnum):
    CREATED = "created"
    DELETED = "deleted"
    UNCHANGED = "unchanged"
    NOT_FOUND = "not_found"
    NOT_EXPECTED = "not_expected"
    FUTURE_DATE = "future_date"


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
        if not habit_crud.is_habit_expected_on(db, habit_id, target_date):
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
