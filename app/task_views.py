from __future__ import annotations

from urllib.parse import urlencode

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


def normalize_todo_view(value: str | None) -> str:
    if value in VALID_TODO_VIEWS:
        return value
    return TODO_VIEW_ALL


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
