from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from datetime import date
from typing import Any

from app.habit_schedule import get_schedule_mask_on, is_expected_on
from app.models.habit import Habit, HabitActivePeriod, HabitSchedulePeriod


def is_period_active_on(period: Any, target_date: date) -> bool:
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


def is_habit_expected_on(
    habit: Habit,
    target_date: date,
    active_periods: Sequence[HabitActivePeriod] | None,
    schedule_periods: Sequence[HabitSchedulePeriod] | None,
) -> bool:
    if active_periods:
        return is_expected_on(target_date, active_periods, schedule_periods or ())
    if not is_habit_active_on(habit, target_date):
        return False
    if not schedule_periods:
        return True
    mask = get_schedule_mask_on(schedule_periods, target_date)
    return mask is not None and bool(mask & (1 << target_date.weekday()))


def group_periods_by_habit(periods: Sequence[Any]) -> dict[int, list[Any]]:
    grouped: dict[int, list[Any]] = defaultdict(list)
    for period in periods:
        grouped[period.habit_id].append(period)
    return grouped
