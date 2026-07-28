from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterator, Sequence
from datetime import date, timedelta
from typing import Any

from sqlalchemy.orm import Session

from app.crud import habit as habit_crud
from app.models.habit import Habit, HabitActivePeriod


def daterange(start_date: date, end_date: date) -> Iterator[date]:
    current = start_date
    while current <= end_date:
        yield current
        current += timedelta(days=1)


def is_period_active_on(period: HabitActivePeriod, target_date: date) -> bool:
    return period.started_on <= target_date and (
        period.ended_on is None or target_date <= period.ended_on
    )


def is_habit_active_on(
    habit: Habit,
    target_date: date,
    periods: Sequence[HabitActivePeriod] | None = None,
) -> bool:
    if periods:
        return any(is_period_active_on(period, target_date) for period in periods)

    created_on = habit.created_at.date()
    if target_date < created_on:
        return False
    if habit.is_active:
        return True

    archived_at = habit.archived_at or habit.updated_at
    return target_date <= archived_at.date()


def calculate_longest_streak(
    completed_dates: set[date],
    start_date: date,
    end_date: date,
) -> int:
    longest = 0
    current = 0
    for target_date in daterange(start_date, end_date):
        if target_date in completed_dates:
            current += 1
            longest = max(longest, current)
        else:
            current = 0
    return longest


def group_periods_by_habit(
    periods: Sequence[HabitActivePeriod],
) -> dict[int, list[HabitActivePeriod]]:
    grouped: dict[int, list[HabitActivePeriod]] = defaultdict(list)
    for period in periods:
        grouped[period.habit_id].append(period)
    return grouped


def build_daily_report(db: Session, selected_date: date) -> dict[str, Any]:
    habits = habit_crud.list_all_habits(db)
    periods_by_habit = group_periods_by_habit(habit_crud.list_active_periods(db))
    completions = habit_crud.list_completions_between(db, selected_date, selected_date)
    completed_ids = {completion.habit_id for completion in completions}

    items: list[dict[str, Any]] = []
    for habit in habits:
        was_active = is_habit_active_on(
            habit,
            selected_date,
            periods_by_habit.get(habit.id),
        )
        was_completed = habit.id in completed_ids
        if not was_active and not was_completed:
            continue
        items.append(
            {
                "habit": habit,
                "completed": was_completed,
                "was_active": was_active,
                "is_archived": not habit.is_active,
            }
        )

    expected_count = sum(1 for item in items if item["was_active"])
    completed_count = sum(
        1 for item in items if item["was_active"] and item["completed"]
    )
    achievement_rate = round(completed_count / expected_count * 100) if expected_count else 0

    return {
        "items": items,
        "expected_count": expected_count,
        "completed_count": completed_count,
        "achievement_rate": achievement_rate,
    }


def build_period_report(
    db: Session,
    start_date: date,
    end_date: date,
    today: date,
) -> dict[str, Any]:
    effective_end = min(end_date, today)
    habits = habit_crud.list_all_habits(db)
    periods_by_habit = group_periods_by_habit(habit_crud.list_active_periods(db))
    completions = habit_crud.list_completions_between(db, start_date, effective_end)

    completion_dates_by_habit: dict[int, set[date]] = defaultdict(set)
    completion_ids_by_date: dict[date, set[int]] = defaultdict(set)
    for completion in completions:
        completion_dates_by_habit[completion.habit_id].add(completion.completed_on)
        completion_ids_by_date[completion.completed_on].add(completion.habit_id)

    daily_summaries: list[dict[str, Any]] = []
    total_expected = 0
    total_completed = 0
    perfect_days = 0

    for target_date in daterange(start_date, end_date):
        is_future = target_date > today
        if is_future:
            daily_summaries.append(
                {
                    "date": target_date,
                    "is_future": True,
                    "expected_count": 0,
                    "completed_count": 0,
                    "achievement_rate": 0,
                }
            )
            continue

        active_ids = {
            habit.id
            for habit in habits
            if is_habit_active_on(
                habit,
                target_date,
                periods_by_habit.get(habit.id),
            )
        }
        completed_count = len(completion_ids_by_date[target_date] & active_ids)
        expected_count = len(active_ids)
        achievement_rate = (
            round(completed_count / expected_count * 100) if expected_count else 0
        )
        total_expected += expected_count
        total_completed += completed_count
        if expected_count > 0 and completed_count == expected_count:
            perfect_days += 1

        daily_summaries.append(
            {
                "date": target_date,
                "is_future": False,
                "expected_count": expected_count,
                "completed_count": completed_count,
                "achievement_rate": achievement_rate,
            }
        )

    habit_summaries: list[dict[str, Any]] = []
    for habit in habits:
        habit_periods = periods_by_habit.get(habit.id)
        expected_dates = {
            target_date
            for target_date in daterange(start_date, effective_end)
            if is_habit_active_on(habit, target_date, habit_periods)
        }
        completed_dates = completion_dates_by_habit[habit.id] & expected_dates
        if not expected_dates and not completed_dates:
            continue

        expected_days = len(expected_dates)
        completed_days = len(completed_dates)
        achievement_rate = (
            round(completed_days / expected_days * 100) if expected_days else 0
        )
        habit_summaries.append(
            {
                "habit": habit,
                "expected_days": expected_days,
                "completed_days": completed_days,
                "achievement_rate": achievement_rate,
                "longest_streak": calculate_longest_streak(
                    completed_dates,
                    start_date,
                    effective_end,
                )
                if effective_end >= start_date
                else 0,
                "is_archived": not habit.is_active,
                "active_period_count": len(habit_periods or ()),
            }
        )

    habit_summaries.sort(
        key=lambda item: (
            -item["achievement_rate"],
            -item["completed_days"],
            item["habit"].created_at,
            item["habit"].id,
        )
    )

    return {
        "effective_end": effective_end,
        "total_expected": total_expected,
        "total_completed": total_completed,
        "achievement_rate": (
            round(total_completed / total_expected * 100) if total_expected else 0
        ),
        "perfect_days": perfect_days,
        "daily_summaries": daily_summaries,
        "habit_summaries": habit_summaries,
    }
