from __future__ import annotations

from collections.abc import Iterable
from datetime import date

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
