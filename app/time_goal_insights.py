from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Mapping, Sequence

from app.models.time_goal import DailyTimeGoalPeriod
from app.time_goal_constants import (
    MAX_DAILY_TIME_GOAL_MINUTES,
    MIN_DAILY_TIME_GOAL_MINUTES,
)

CURRENT_PERIOD_DAYS = 7


@dataclass(frozen=True)
class TimeGoalAchievementDay:
    target_date: date
    minutes: int
    goal_minutes: int | None
    percentage: int
    achieved: bool
    is_today: bool

    @property
    def configured(self) -> bool:
        return self.goal_minutes is not None


@dataclass(frozen=True)
class TimeGoalAchievementInsights:
    period_start: date
    period_end: date
    configured_days: int
    achieved_days: int
    achievement_rate: int | None
    streak_days: int
    days: tuple[TimeGoalAchievementDay, ...]

    @property
    def has_goals(self) -> bool:
        return self.configured_days > 0


def _goal_minutes_for_date(
    periods: Sequence[DailyTimeGoalPeriod],
    target_date: date,
) -> int | None:
    matches = [
        period
        for period in periods
        if period.started_on <= target_date
        and (period.ended_on is None or period.ended_on >= target_date)
    ]
    if len(matches) != 1:
        return None

    goal_minutes = matches[0].goal_minutes
    if (
        isinstance(goal_minutes, bool)
        or not isinstance(goal_minutes, int)
        or not MIN_DAILY_TIME_GOAL_MINUTES
        <= goal_minutes
        <= MAX_DAILY_TIME_GOAL_MINUTES
    ):
        return None
    return goal_minutes


def _continuous_goal_coverage_start(
    periods: Sequence[DailyTimeGoalPeriod],
    anchor_date: date,
) -> date | None:
    covering = [
        period
        for period in periods
        if period.started_on <= anchor_date
        and (period.ended_on is None or period.ended_on >= anchor_date)
    ]
    if len(covering) != 1:
        return None

    current = covering[0]
    start = current.started_on
    ordered = sorted(periods, key=lambda period: (period.started_on, period.id or 0))
    try:
        index = ordered.index(current)
    except ValueError:
        return start

    while index > 0 and start > date.min:
        previous = ordered[index - 1]
        expected_end = start - timedelta(days=1)
        if previous.ended_on != expected_end:
            break
        start = previous.started_on
        index -= 1
    return start


def achievement_query_start(
    periods: Sequence[DailyTimeGoalPeriod],
    today: date,
) -> date | None:
    """現在ストリーク候補を正確に判定するために必要な最古日を返す。"""
    candidates: list[date] = []
    today_start = _continuous_goal_coverage_start(periods, today)
    if today_start is not None:
        candidates.append(today_start)
    if today > date.min:
        yesterday_start = _continuous_goal_coverage_start(
            periods,
            today - timedelta(days=1),
        )
        if yesterday_start is not None:
            candidates.append(yesterday_start)
    return min(candidates) if candidates else None


def calculate_goal_achievement_streak(
    periods: Sequence[DailyTimeGoalPeriod],
    daily_totals: Mapping[date, int],
    today: date,
) -> int:
    today_goal = _goal_minutes_for_date(periods, today)
    today_minutes = max(int(daily_totals.get(today, 0)), 0)
    if today_goal is not None and today_minutes >= today_goal:
        cursor = today
    elif today > date.min:
        cursor = today - timedelta(days=1)
    else:
        return 0

    streak = 0
    while True:
        goal_minutes = _goal_minutes_for_date(periods, cursor)
        if goal_minutes is None:
            break
        minutes = max(int(daily_totals.get(cursor, 0)), 0)
        if minutes < goal_minutes:
            break
        streak += 1
        if cursor == date.min:
            break
        cursor -= timedelta(days=1)
    return streak


def build_time_goal_achievement_insights(
    *,
    today: date,
    periods: Sequence[DailyTimeGoalPeriod],
    daily_totals: Mapping[date, int],
) -> TimeGoalAchievementInsights:
    period_start = today - timedelta(days=CURRENT_PERIOD_DAYS - 1)
    days: list[TimeGoalAchievementDay] = []

    for offset in range(CURRENT_PERIOD_DAYS):
        target_date = period_start + timedelta(days=offset)
        minutes = max(int(daily_totals.get(target_date, 0)), 0)
        goal_minutes = _goal_minutes_for_date(periods, target_date)
        achieved = goal_minutes is not None and minutes >= goal_minutes
        percentage = (
            min(minutes * 100 // goal_minutes, 100)
            if goal_minutes is not None
            else 0
        )
        days.append(
            TimeGoalAchievementDay(
                target_date=target_date,
                minutes=minutes,
                goal_minutes=goal_minutes,
                percentage=percentage,
                achieved=achieved,
                is_today=target_date == today,
            )
        )

    configured_days = sum(1 for day in days if day.configured)
    achieved_days = sum(1 for day in days if day.achieved)
    achievement_rate = (
        round(achieved_days * 100 / configured_days) if configured_days else None
    )

    return TimeGoalAchievementInsights(
        period_start=period_start,
        period_end=today,
        configured_days=configured_days,
        achieved_days=achieved_days,
        achievement_rate=achievement_rate,
        streak_days=calculate_goal_achievement_streak(periods, daily_totals, today),
        days=tuple(days),
    )
