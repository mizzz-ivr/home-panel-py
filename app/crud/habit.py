from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.habit import Habit, HabitCompletion

MAX_ACTIVE_HABITS = 20


def list_active_habits(db: Session) -> list[Habit]:
    return list(
        db.scalars(
            select(Habit)
            .where(Habit.is_active.is_(True))
            .order_by(Habit.created_at.asc(), Habit.id.asc())
        ).all()
    )


def list_archived_habits(db: Session) -> list[Habit]:
    return list(
        db.scalars(
            select(Habit)
            .where(Habit.is_active.is_(False))
            .order_by(Habit.archived_at.desc(), Habit.id.desc())
        ).all()
    )


def list_all_habits(db: Session) -> list[Habit]:
    return list(db.scalars(select(Habit).order_by(Habit.created_at.asc(), Habit.id.asc())).all())


def list_completions_between(
    db: Session,
    start_date: date,
    end_date: date,
) -> list[HabitCompletion]:
    if end_date < start_date:
        return []

    return list(
        db.scalars(
            select(HabitCompletion)
            .where(
                HabitCompletion.completed_on >= start_date,
                HabitCompletion.completed_on <= end_date,
            )
            .order_by(
                HabitCompletion.completed_on.asc(),
                HabitCompletion.habit_id.asc(),
                HabitCompletion.id.asc(),
            )
        ).all()
    )


def count_active_habits(db: Session) -> int:
    return int(
        db.scalar(select(func.count(Habit.id)).where(Habit.is_active.is_(True))) or 0
    )


def find_active_habit_by_name(
    db: Session,
    name: str,
    *,
    exclude_habit_id: int | None = None,
) -> Habit | None:
    normalized = name.casefold()
    for habit in list_active_habits(db):
        if exclude_habit_id is not None and habit.id == exclude_habit_id:
            continue
        if habit.name.casefold() == normalized:
            return habit
    return None


def create_habit(db: Session, name: str) -> Habit:
    habit = Habit(name=name)
    db.add(habit)
    db.commit()
    db.refresh(habit)
    return habit


def get_habit(db: Session, habit_id: int) -> Habit | None:
    return db.get(Habit, habit_id)


def get_active_habit(db: Session, habit_id: int) -> Habit | None:
    return db.scalar(
        select(Habit).where(Habit.id == habit_id, Habit.is_active.is_(True))
    )


def rename_habit(db: Session, habit_id: int, name: str) -> Habit | None:
    habit = get_habit(db, habit_id)
    if habit is None:
        return None

    habit.name = name
    db.commit()
    db.refresh(habit)
    return habit


def toggle_today_completion(db: Session, habit_id: int, target_date: date) -> bool | None:
    habit = get_active_habit(db, habit_id)
    if habit is None:
        return None

    completion = db.scalar(
        select(HabitCompletion).where(
            HabitCompletion.habit_id == habit_id,
            HabitCompletion.completed_on == target_date,
        )
    )
    if completion is None:
        db.add(HabitCompletion(habit_id=habit_id, completed_on=target_date))
        completed = True
    else:
        db.delete(completion)
        completed = False

    db.commit()
    return completed


def archive_habit(db: Session, habit_id: int) -> bool:
    habit = get_active_habit(db, habit_id)
    if habit is None:
        return False

    habit.is_active = False
    habit.archived_at = datetime.utcnow()
    db.commit()
    return True


def restore_habit(db: Session, habit_id: int) -> bool:
    habit = get_habit(db, habit_id)
    if habit is None or habit.is_active:
        return False

    habit.is_active = True
    habit.archived_at = None
    db.commit()
    return True


def calculate_current_streak(completed_dates: set[date], today: date) -> int:
    if not completed_dates:
        return 0

    cursor = today if today in completed_dates else today - timedelta(days=1)
    streak = 0
    while cursor in completed_dates:
        streak += 1
        cursor -= timedelta(days=1)
    return streak


def get_dashboard_summary(db: Session, today: date) -> tuple[list[dict[str, Any]], int, int]:
    habits = list_active_habits(db)
    if not habits:
        return [], 0, 0

    habit_ids = [habit.id for habit in habits]
    completions = list(
        db.scalars(
            select(HabitCompletion)
            .where(HabitCompletion.habit_id.in_(habit_ids))
            .order_by(HabitCompletion.completed_on.asc(), HabitCompletion.id.asc())
        ).all()
    )

    completion_dates: dict[int, set[date]] = defaultdict(set)
    for completion in completions:
        completion_dates[completion.habit_id].add(completion.completed_on)

    items: list[dict[str, Any]] = []
    completed_today = 0
    for habit in habits:
        dates = completion_dates[habit.id]
        is_completed_today = today in dates
        if is_completed_today:
            completed_today += 1
        items.append(
            {
                "habit": habit,
                "completed_today": is_completed_today,
                "current_streak": calculate_current_streak(dates, today),
            }
        )

    return items, completed_today, len(habits)
