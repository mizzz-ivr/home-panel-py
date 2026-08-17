from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Iterable, Mapping, Sequence

WEEKDAY_LABELS = ("月", "火", "水", "木", "金", "土", "日")
CURRENT_PERIOD_DAYS = 7
COMPARISON_PERIOD_DAYS = 7


@dataclass(frozen=True)
class TimeInsightDay:
    target_date: date
    weekday: str
    minutes: int
    percentage: int
    is_today: bool


@dataclass(frozen=True)
class TimeInsights:
    period_start: date
    period_end: date
    total_minutes: int
    active_days: int
    average_minutes: int
    streak_days: int
    today_recorded: bool
    previous_total_minutes: int
    change_percentage: int | None
    trend: str
    top_category: str | None
    top_category_minutes: int
    days: tuple[TimeInsightDay, ...]

    @property
    def has_activity(self) -> bool:
        return self.total_minutes > 0


def calculate_recording_streak(recorded_dates: Iterable[date], today: date) -> int:
    active_dates = {target_date for target_date in recorded_dates if target_date <= today}
    if today in active_dates:
        cursor = today
    elif today > date.min:
        cursor = today - timedelta(days=1)
    else:
        return 0

    streak = 0
    while cursor in active_dates:
        streak += 1
        if cursor == date.min:
            break
        cursor -= timedelta(days=1)
    return streak


def build_time_insights(
    *,
    today: date,
    daily_totals: Mapping[date, int],
    recorded_dates: Iterable[date],
    category_totals: Sequence[tuple[str, int]],
) -> TimeInsights:
    period_start = today - timedelta(days=CURRENT_PERIOD_DAYS - 1)
    comparison_start = period_start - timedelta(days=COMPARISON_PERIOD_DAYS)
    comparison_end = period_start - timedelta(days=1)

    current_dates = [period_start + timedelta(days=offset) for offset in range(CURRENT_PERIOD_DAYS)]
    current_minutes = [max(int(daily_totals.get(target_date, 0)), 0) for target_date in current_dates]
    total_minutes = sum(current_minutes)
    active_days = sum(1 for minutes in current_minutes if minutes > 0)
    average_minutes = round(total_minutes / active_days) if active_days else 0
    max_daily_minutes = max(current_minutes, default=0)

    days = tuple(
        TimeInsightDay(
            target_date=target_date,
            weekday=WEEKDAY_LABELS[target_date.weekday()],
            minutes=minutes,
            percentage=round(minutes / max_daily_minutes * 100) if max_daily_minutes else 0,
            is_today=target_date == today,
        )
        for target_date, minutes in zip(current_dates, current_minutes, strict=True)
    )

    previous_total_minutes = sum(
        max(int(daily_totals.get(comparison_start + timedelta(days=offset), 0)), 0)
        for offset in range(COMPARISON_PERIOD_DAYS)
    )
    if previous_total_minutes == 0:
        change_percentage = None
        trend = "up" if total_minutes > 0 else "same"
    else:
        change_percentage = round(
            (total_minutes - previous_total_minutes) * 100 / previous_total_minutes
        )
        if total_minutes > previous_total_minutes:
            trend = "up"
        elif total_minutes < previous_total_minutes:
            trend = "down"
        else:
            trend = "same"

    top_category = None
    top_category_minutes = 0
    if category_totals:
        category, minutes = category_totals[0]
        normalized_minutes = max(int(minutes), 0)
        if normalized_minutes > 0:
            top_category = str(category)
            top_category_minutes = normalized_minutes

    return TimeInsights(
        period_start=period_start,
        period_end=today,
        total_minutes=total_minutes,
        active_days=active_days,
        average_minutes=average_minutes,
        streak_days=calculate_recording_streak(recorded_dates, today),
        today_recorded=today in set(recorded_dates),
        previous_total_minutes=previous_total_minutes,
        change_percentage=change_percentage,
        trend=trend,
        top_category=top_category,
        top_category_minutes=top_category_minutes,
        days=days,
    )
