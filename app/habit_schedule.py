from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import date, timedelta
from typing import Any

WEEKDAY_LABELS = ("月", "火", "水", "木", "金", "土", "日")
ALL_WEEKDAYS = tuple(range(7))
ALL_WEEKDAYS_MASK = sum(1 << weekday for weekday in ALL_WEEKDAYS)
WEEKDAYS_MASK = sum(1 << weekday for weekday in range(5))
WEEKEND_MASK = (1 << 5) | (1 << 6)


def weekdays_to_mask(weekdays: Iterable[int]) -> int:
    normalized = set(weekdays)
    if not normalized or any(type(weekday) is not int or not 0 <= weekday <= 6 for weekday in normalized):
        raise ValueError("対象曜日は月曜日0〜日曜日6から1つ以上指定してください。")
    return sum(1 << weekday for weekday in normalized)


def mask_to_weekdays(mask: int) -> tuple[int, ...]:
    if type(mask) is not int or not 1 <= mask <= ALL_WEEKDAYS_MASK:
        raise ValueError("曜日マスクは1〜127の整数である必要があります。")
    return tuple(weekday for weekday in ALL_WEEKDAYS if mask & (1 << weekday))


def is_scheduled_on(mask: int, target_date: date) -> bool:
    return bool(mask & (1 << target_date.weekday()))


def format_schedule(mask: int) -> str:
    if mask == ALL_WEEKDAYS_MASK:
        return "毎日"
    if mask == WEEKDAYS_MASK:
        return "平日"
    if mask == WEEKEND_MASK:
        return "土日"
    return "・".join(WEEKDAY_LABELS[weekday] for weekday in mask_to_weekdays(mask))


def is_date_in_period(target_date: date, period: Any) -> bool:
    return period.started_on <= target_date and (
        period.ended_on is None or target_date <= period.ended_on
    )


def get_schedule_mask_on(schedule_periods: Sequence[Any], target_date: date) -> int | None:
    matching = [
        period
        for period in schedule_periods
        if period.schedule_type == "weekdays" and is_date_in_period(target_date, period)
    ]
    if not matching:
        return None
    latest = max(matching, key=lambda period: (period.started_on, period.id))
    return latest.weekdays_mask


def is_expected_on(
    target_date: date,
    active_periods: Sequence[Any],
    schedule_periods: Sequence[Any],
) -> bool:
    if not any(is_date_in_period(target_date, period) for period in active_periods):
        return False
    mask = get_schedule_mask_on(schedule_periods, target_date)
    return mask is not None and is_scheduled_on(mask, target_date)


def expected_dates_between(
    start_date: date,
    end_date: date,
    active_periods: Sequence[Any],
    schedule_periods: Sequence[Any],
) -> list[date]:
    if end_date < start_date:
        return []
    result: list[date] = []
    cursor = start_date
    while cursor <= end_date:
        if is_expected_on(cursor, active_periods, schedule_periods):
            result.append(cursor)
        cursor += timedelta(days=1)
    return result


def calculate_scheduled_streak(
    completed_dates: set[date],
    expected_dates: Sequence[date],
    today: date,
) -> int:
    candidates = sorted(target_date for target_date in expected_dates if target_date <= today)
    if not candidates:
        return 0

    if candidates[-1] == today and today not in completed_dates:
        candidates.pop()
    streak = 0
    for target_date in reversed(candidates):
        if target_date not in completed_dates:
            break
        streak += 1
    return streak
