from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from urllib.parse import urlencode

from app.models.task import Task

TODO_VIEW_ALL = "all"
TODO_VIEW_DEFINITIONS = (
    ("all", "すべて"),
    ("today", "今日"),
    ("overdue", "期限切れ"),
    ("upcoming", "今後"),
    ("no_due", "期限なし"),
    ("high", "高優先度"),
    ("completed", "完了済み"),
)
VALID_TODO_VIEWS = frozenset(key for key, _label in TODO_VIEW_DEFINITIONS)


@dataclass(frozen=True)
class TodoViewOption:
    key: str
    label: str
    count: int


def normalize_todo_view(value: str | None) -> str:
    if value in VALID_TODO_VIEWS:
        return value
    return TODO_VIEW_ALL


def task_matches_view(task: Task, view: str, today: date) -> bool:
    normalized_view = normalize_todo_view(view)
    if normalized_view == "all":
        return True
    if normalized_view == "completed":
        return task.is_done
    if task.is_done:
        return False
    if normalized_view == "today":
        return task.due_date == today
    if normalized_view == "overdue":
        return task.due_date is not None and task.due_date < today
    if normalized_view == "upcoming":
        return task.due_date is not None and task.due_date > today
    if normalized_view == "no_due":
        return task.due_date is None
    if normalized_view == "high":
        return task.priority == "high"
    return True


def filter_tasks(tasks: list[Task], view: str, today: date) -> list[Task]:
    normalized_view = normalize_todo_view(view)
    return [
        task
        for task in tasks
        if task_matches_view(task, normalized_view, today)
    ]


def build_todo_view_options(
    tasks: list[Task],
    today: date,
) -> tuple[TodoViewOption, ...]:
    return tuple(
        TodoViewOption(
            key=key,
            label=label,
            count=sum(1 for task in tasks if task_matches_view(task, key, today)),
        )
        for key, label in TODO_VIEW_DEFINITIONS
    )


def todo_dashboard_url(
    view: str | None,
    *,
    show_card: str | None = None,
    task_id: int | None = None,
) -> str:
    normalized_view = normalize_todo_view(view)
    params: list[tuple[str, str]] = []
    if normalized_view != TODO_VIEW_ALL:
        params.append(("todo_view", normalized_view))
    if show_card == "todo":
        params.append(("show_card", "todo"))

    url = "/"
    if params:
        url += "?" + urlencode(params)
    anchor = f"task-{task_id}" if task_id is not None else "todo-card"
    return f"{url}#{anchor}"
