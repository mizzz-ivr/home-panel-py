from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models.habit import Habit
from app.models.memo import DailyMemo
from app.models.task import Task
from app.models.time_entry import TimeEntry

SEARCH_RESULT_LIMIT_PER_CATEGORY = 20
SEARCH_SNIPPET_LENGTH = 120


@dataclass(frozen=True)
class SearchResultItem:
    item_id: int
    title: str
    description: str
    metadata: str
    url: str


@dataclass(frozen=True)
class GlobalSearchResults:
    tasks: tuple[SearchResultItem, ...]
    memos: tuple[SearchResultItem, ...]
    time_entries: tuple[SearchResultItem, ...]
    habits: tuple[SearchResultItem, ...]

    @property
    def total_count(self) -> int:
        return sum(
            len(items)
            for items in (
                self.tasks,
                self.memos,
                self.time_entries,
                self.habits,
            )
        )


def escape_like_literal(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def build_contains_pattern(query: str) -> str:
    return f"%{escape_like_literal(query)}%"


def normalize_snippet(value: str, *, max_length: int = SEARCH_SNIPPET_LENGTH) -> str:
    normalized = " ".join(value.split())
    if len(normalized) <= max_length:
        return normalized
    return normalized[: max_length - 1] + "…"


def format_datetime(value: datetime) -> str:
    return value.strftime("%Y/%m/%d %H:%M")


def format_date(value: date) -> str:
    return value.strftime("%Y/%m/%d")


def search_tasks(
    db: Session,
    pattern: str,
    *,
    limit: int = SEARCH_RESULT_LIMIT_PER_CATEGORY,
) -> tuple[SearchResultItem, ...]:
    tasks = db.scalars(
        select(Task)
        .where(Task.title.ilike(pattern, escape="\\"))
        .order_by(Task.updated_at.desc(), Task.id.desc())
        .limit(limit)
    ).all()
    return tuple(
        SearchResultItem(
            item_id=task.id,
            title=task.title,
            description="完了済み" if task.is_done else "未完了",
            metadata=f"更新: {format_datetime(task.updated_at)}",
            url=f"/?show_card=todo#task-{task.id}",
        )
        for task in tasks
    )


def search_memos(
    db: Session,
    pattern: str,
    *,
    limit: int = SEARCH_RESULT_LIMIT_PER_CATEGORY,
) -> tuple[SearchResultItem, ...]:
    memos = db.scalars(
        select(DailyMemo)
        .where(DailyMemo.content.ilike(pattern, escape="\\"))
        .order_by(DailyMemo.memo_date.desc(), DailyMemo.id.desc())
        .limit(limit)
    ).all()
    return tuple(
        SearchResultItem(
            item_id=memo.id,
            title=f"{format_date(memo.memo_date)}のメモ",
            description=normalize_snippet(memo.content),
            metadata=f"更新: {format_datetime(memo.updated_at)}",
            url=f"/history?target_date={memo.memo_date.isoformat()}",
        )
        for memo in memos
    )


def search_time_entries(
    db: Session,
    pattern: str,
    *,
    limit: int = SEARCH_RESULT_LIMIT_PER_CATEGORY,
) -> tuple[SearchResultItem, ...]:
    entries = db.scalars(
        select(TimeEntry)
        .where(
            or_(
                TimeEntry.category.ilike(pattern, escape="\\"),
                TimeEntry.note.ilike(pattern, escape="\\"),
            )
        )
        .order_by(
            TimeEntry.entry_date.desc(),
            TimeEntry.created_at.desc(),
            TimeEntry.id.desc(),
        )
        .limit(limit)
    ).all()
    return tuple(
        SearchResultItem(
            item_id=entry.id,
            title=f"{entry.category}・{entry.minutes}分",
            description=normalize_snippet(entry.note) if entry.note.strip() else "メモなし",
            metadata=f"記録日: {format_date(entry.entry_date)}",
            url=f"/history?target_date={entry.entry_date.isoformat()}",
        )
        for entry in entries
    )


def search_habits(
    db: Session,
    pattern: str,
    *,
    limit: int = SEARCH_RESULT_LIMIT_PER_CATEGORY,
) -> tuple[SearchResultItem, ...]:
    habits = db.scalars(
        select(Habit)
        .where(Habit.name.ilike(pattern, escape="\\"))
        .order_by(Habit.updated_at.desc(), Habit.id.desc())
        .limit(limit)
    ).all()
    return tuple(
        SearchResultItem(
            item_id=habit.id,
            title=habit.name,
            description="利用中" if habit.is_active else "終了済み",
            metadata=f"更新: {format_datetime(habit.updated_at)}",
            url=f"/habits/manage#habit-{habit.id}",
        )
        for habit in habits
    )


def search_all(
    db: Session,
    query: str,
    *,
    limit_per_category: int = SEARCH_RESULT_LIMIT_PER_CATEGORY,
) -> GlobalSearchResults:
    if limit_per_category < 1:
        raise ValueError("カテゴリごとの上限は1以上で指定してください。")

    pattern = build_contains_pattern(query)
    return GlobalSearchResults(
        tasks=search_tasks(db, pattern, limit=limit_per_category),
        memos=search_memos(db, pattern, limit=limit_per_category),
        time_entries=search_time_entries(db, pattern, limit=limit_per_category),
        habits=search_habits(db, pattern, limit=limit_per_category),
    )
