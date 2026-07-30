from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterator, Sequence
from datetime import date, timedelta
from typing import Any

from sqlalchemy.orm import Session

from app.crud import habit as habit_crud
from app.habit_eligibility import (
    group_periods_by_habit,
    is_habit_active_on,
    is_habit_expected_on,
    is_period_active_on,
)
from app.habit_schedule import (
    ALL_WEEKDAYS_MASK,
    expected_dates_between,
    format_schedule,
    get_schedule_mask_on,
)


def daterange(start_date: date, end_date: date) -> Iterator[date]:
    current = start_date
    while current <= end_date:
        yield current
        current += timedelta(days=1)


def calculate_longest_streak(
    completed_dates: set[date],
    start_date: date,
    end_date: date,
    expected_dates: Sequence[date] | None = None,
) -> int:
    targets = list(expected_dates) if expected_dates is not None else list(daterange(start_date, end_date))
    longest = 0
    current = 0
    for target_date in targets:
        if target_date in completed_dates:
            current += 1
            longest = max(longest, current)
        else:
            current = 0
    return longest


def build_daily_report(db: Session, selected_date: date) -> dict[str, Any]:
    habits = habit_crud.list_all_habits(db)
    active_periods_by_habit = group_periods_by_habit(habit_crud.list_active_periods(db))
    schedule_periods_by_habit = group_periods_by_habit(habit_crud.list_schedule_periods(db))
    completions = habit_crud.list_completions_between(db, selected_date, selected_date)
    completed_ids = {completion.habit_id for completion in completions}

    items: list[dict[str, Any]] = []
    for habit in habits:
        active_periods = active_periods_by_habit.get(habit.id)
        schedule_periods = schedule_periods_by_habit.get(habit.id)
        was_active = is_habit_active_on(habit, selected_date, active_periods)
        was_scheduled = is_habit_expected_on(
            habit,
            selected_date,
            active_periods,
            schedule_periods,
        )
        was_completed = habit.id in completed_ids
        if not was_active and not was_completed:
            continue
        schedule_mask = get_schedule_mask_on(schedule_periods or (), selected_date) or ALL_WEEKDAYS_MASK
        items.append(
            {
                "habit": habit,
                "completed": was_completed,
                "was_active": was_active,
                "was_scheduled": was_scheduled,
                "schedule_label": format_schedule(schedule_mask),
                "is_archived": not habit.is_active,
            }
        )

    expected_count = sum(1 for item in items if item["was_scheduled"])
    completed_count = sum(
        1 for item in items if item["was_scheduled"] and item["completed"]
    )
    achievement_rate = round(completed_count / expected_count * 100) if expected_count else 0

    return {
        "items": items,
        "expected_count": expected_count,
        "completed_count": completed_count,
        "recorded_count": len(completions),
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
    active_periods_by_habit = group_periods_by_habit(habit_crud.list_active_periods(db))
    schedule_periods_by_habit = group_periods_by_habit(habit_crud.list_schedule_periods(db))
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

        expected_ids = {
            habit.id
            for habit in habits
            if is_habit_expected_on(
                habit,
                target_date,
                active_periods_by_habit.get(habit.id),
                schedule_periods_by_habit.get(habit.id),
            )
        }
        completed_count = len(completion_ids_by_date[target_date] & expected_ids)
        expected_count = len(expected_ids)
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
        active_periods = active_periods_by_habit.get(habit.id) or ()
        schedule_periods = schedule_periods_by_habit.get(habit.id) or ()
        if active_periods:
            expected_dates = expected_dates_between(
                start_date,
                effective_end,
                active_periods,
                schedule_periods,
            )
        else:
            expected_dates = [
                target_date
                for target_date in daterange(start_date, effective_end)
                if is_habit_expected_on(habit, target_date, None, schedule_periods)
            ]
        expected_date_set = set(expected_dates)
        completed_dates = completion_dates_by_habit[habit.id] & expected_date_set
        if not expected_dates and not completed_dates:
            continue

        expected_days = len(expected_dates)
        completed_days = len(completed_dates)
        achievement_rate = (
            round(completed_days / expected_days * 100) if expected_days else 0
        )
        current_mask = (
            get_schedule_mask_on(schedule_periods, effective_end)
            if effective_end >= start_date
            else None
        ) or ALL_WEEKDAYS_MASK
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
                    expected_dates,
                )
                if effective_end >= start_date
                else 0,
                "schedule_label": format_schedule(current_mask),
                "is_archived": not habit.is_active,
                "active_period_count": len(active_periods),
                "schedule_period_count": len(schedule_periods),
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
