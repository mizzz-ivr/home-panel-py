from __future__ import annotations

from datetime import date
from typing import Literal

TaskPriority = Literal["low", "medium", "high"]

TASK_PRIORITIES: tuple[TaskPriority, ...] = ("low", "medium", "high")
TASK_PRIORITY_LABELS: dict[TaskPriority, str] = {
    "low": "低",
    "medium": "中",
    "high": "高",
}
TASK_PRIORITY_SORT_ORDER: dict[TaskPriority, int] = {
    "high": 0,
    "medium": 1,
    "low": 2,
}
DEFAULT_TASK_PRIORITY: TaskPriority = "medium"


def is_valid_task_priority(value: object) -> bool:
    return type(value) is str and value in TASK_PRIORITIES


def format_task_priority(value: str) -> str:
    return TASK_PRIORITY_LABELS.get(value, value)


def format_task_due_date(due_date: date | None) -> str:
    return due_date.strftime("%Y/%m/%d") if due_date is not None else "期限なし"


def get_task_due_state(
    due_date: date | None,
    *,
    today: date,
    is_done: bool,
) -> str:
    if due_date is None:
        return "none"
    if is_done:
        return "completed"
    if due_date < today:
        return "overdue"
    if due_date == today:
        return "today"
    return "upcoming"
