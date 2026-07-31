from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import StrEnum

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.crud import habit as habit_crud
from app.habit_completion import get_expected_habit_ids, list_completions_on
from app.models.habit import HabitCompletion


class SelectedCompletionUpdateStatus(StrEnum):
    UPDATED = "updated"
    UNCHANGED = "unchanged"
    FUTURE_DATE = "future_date"
    EMPTY_SELECTION = "empty_selection"
    INVALID_SELECTION = "invalid_selection"
    NOT_FOUND = "not_found"
    NOT_EXPECTED = "not_expected"


@dataclass(frozen=True)
class SelectedCompletionUpdate:
    status: SelectedCompletionUpdateStatus
    selected_count: int = 0
    updated_count: int = 0
    invalid_habit_ids: tuple[int, ...] = ()


def set_selected_completions_on(
    db: Session,
    habit_ids: list[int],
    target_date: date,
    *,
    completed: bool,
    latest_editable_date: date,
) -> SelectedCompletionUpdate:
    """選択した習慣の指定日達成状態を1トランザクションで設定する。"""

    if target_date > latest_editable_date:
        return SelectedCompletionUpdate(SelectedCompletionUpdateStatus.FUTURE_DATE)
    if not habit_ids:
        return SelectedCompletionUpdate(SelectedCompletionUpdateStatus.EMPTY_SELECTION)

    selected_ids = set(habit_ids)
    if len(selected_ids) != len(habit_ids) or any(habit_id <= 0 for habit_id in habit_ids):
        return SelectedCompletionUpdate(
            SelectedCompletionUpdateStatus.INVALID_SELECTION,
            selected_count=len(habit_ids),
        )

    known_ids = {habit.id for habit in habit_crud.list_all_habits(db)}
    unknown_ids = tuple(sorted(selected_ids - known_ids))
    if unknown_ids:
        return SelectedCompletionUpdate(
            SelectedCompletionUpdateStatus.NOT_FOUND,
            selected_count=len(selected_ids),
            invalid_habit_ids=unknown_ids,
        )

    completions_by_habit_id = {
        completion.habit_id: completion
        for completion in list_completions_on(db, target_date)
    }

    if completed:
        expected_ids = get_expected_habit_ids(db, target_date)
        not_expected_ids = tuple(sorted(selected_ids - expected_ids))
        if not_expected_ids:
            return SelectedCompletionUpdate(
                SelectedCompletionUpdateStatus.NOT_EXPECTED,
                selected_count=len(selected_ids),
                invalid_habit_ids=not_expected_ids,
            )

        missing_ids = selected_ids - completions_by_habit_id.keys()
        if not missing_ids:
            return SelectedCompletionUpdate(
                SelectedCompletionUpdateStatus.UNCHANGED,
                selected_count=len(selected_ids),
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
            missing_ids = selected_ids - existing_ids
            if not missing_ids:
                return SelectedCompletionUpdate(
                    SelectedCompletionUpdateStatus.UNCHANGED,
                    selected_count=len(selected_ids),
                )
            for habit_id in sorted(missing_ids):
                db.add(HabitCompletion(habit_id=habit_id, completed_on=target_date))
            db.commit()

        return SelectedCompletionUpdate(
            SelectedCompletionUpdateStatus.UPDATED,
            selected_count=len(selected_ids),
            updated_count=len(missing_ids),
        )

    existing = [
        completion
        for habit_id, completion in completions_by_habit_id.items()
        if habit_id in selected_ids
    ]
    if not existing:
        return SelectedCompletionUpdate(
            SelectedCompletionUpdateStatus.UNCHANGED,
            selected_count=len(selected_ids),
        )

    for completion in existing:
        db.delete(completion)
    db.commit()
    return SelectedCompletionUpdate(
        SelectedCompletionUpdateStatus.UPDATED,
        selected_count=len(selected_ids),
        updated_count=len(existing),
    )
