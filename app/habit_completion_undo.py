from __future__ import annotations

import json
import secrets
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from enum import StrEnum
from typing import Any, Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.app_setting import AppSetting
from app.models.habit import Habit, HabitCompletion

HABIT_COMPLETION_UNDO_KEY = "habit.completion.undo.v1"
UNDO_TTL = timedelta(minutes=10)
UNDO_VERSION = 1

SOURCE_LABELS = {
    "dashboard_toggle": "今日の習慣の達成状態変更",
    "single_complete": "習慣を達成に変更",
    "single_clear": "習慣の達成取り消し",
    "bulk_complete": "対象習慣の一括達成",
    "bulk_clear": "この日の全達成取り消し",
    "selected_complete": "選択した習慣の一括達成",
    "selected_clear": "選択した達成の一括取り消し",
}
DASHBOARD_SOURCES = {"dashboard_toggle"}


@dataclass(frozen=True)
class HabitCompletionUndoAction:
    token: str
    target_date: date
    before_habit_ids: tuple[int, ...]
    after_habit_ids: tuple[int, ...]
    source: str
    created_at: datetime
    expires_at: datetime

    @property
    def label(self) -> str:
        return SOURCE_LABELS[self.source]

    @property
    def return_url(self) -> str:
        if self.source in DASHBOARD_SOURCES:
            return "/"
        return f"/habits/history?target_date={self.target_date.isoformat()}"

    def to_payload(self) -> dict[str, Any]:
        return {
            "version": UNDO_VERSION,
            "token": self.token,
            "target_date": self.target_date.isoformat(),
            "before_habit_ids": list(self.before_habit_ids),
            "after_habit_ids": list(self.after_habit_ids),
            "source": self.source,
            "created_at": self.created_at.isoformat(),
            "expires_at": self.expires_at.isoformat(),
        }


class UndoResultStatus(StrEnum):
    RESTORED = "restored"
    NOT_FOUND = "not_found"
    INVALID_TOKEN = "invalid_token"
    EXPIRED = "expired"
    STATE_CHANGED = "state_changed"
    MISSING_HABIT = "missing_habit"


@dataclass(frozen=True)
class UndoResult:
    status: UndoResultStatus
    action: HabitCompletionUndoAction | None = None


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def normalize_habit_ids(values: Iterable[int]) -> tuple[int, ...] | None:
    ids = tuple(values)
    if any(type(value) is not int or value <= 0 for value in ids):
        return None
    if len(set(ids)) != len(ids):
        return None
    return tuple(sorted(ids))


def parse_aware_datetime(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(timezone.utc)


def parse_undo_action(raw: object) -> HabitCompletionUndoAction | None:
    if not isinstance(raw, dict) or raw.get("version") != UNDO_VERSION:
        return None

    token = raw.get("token")
    source = raw.get("source")
    if (
        not isinstance(token, str)
        or not 16 <= len(token) <= 128
        or source not in SOURCE_LABELS
    ):
        return None

    target_date_raw = raw.get("target_date")
    if not isinstance(target_date_raw, str):
        return None
    try:
        target_date = date.fromisoformat(target_date_raw)
    except ValueError:
        return None

    before_raw = raw.get("before_habit_ids")
    after_raw = raw.get("after_habit_ids")
    if not isinstance(before_raw, list) or not isinstance(after_raw, list):
        return None
    before_habit_ids = normalize_habit_ids(before_raw)
    after_habit_ids = normalize_habit_ids(after_raw)
    if before_habit_ids is None or after_habit_ids is None:
        return None
    if before_habit_ids == after_habit_ids:
        return None

    created_at = parse_aware_datetime(raw.get("created_at"))
    expires_at = parse_aware_datetime(raw.get("expires_at"))
    if created_at is None or expires_at is None:
        return None
    if expires_at <= created_at or expires_at - created_at > UNDO_TTL:
        return None

    return HabitCompletionUndoAction(
        token=token,
        target_date=target_date,
        before_habit_ids=before_habit_ids,
        after_habit_ids=after_habit_ids,
        source=source,
        created_at=created_at,
        expires_at=expires_at,
    )


def get_completion_habit_ids(db: Session, target_date: date) -> tuple[int, ...]:
    return tuple(
        db.scalars(
            select(HabitCompletion.habit_id)
            .where(HabitCompletion.completed_on == target_date)
            .order_by(HabitCompletion.habit_id.asc())
        ).all()
    )


def get_stored_undo_action(db: Session) -> HabitCompletionUndoAction | None:
    setting = db.get(AppSetting, HABIT_COMPLETION_UNDO_KEY)
    if setting is None:
        return None
    try:
        raw = json.loads(setting.value)
    except (TypeError, json.JSONDecodeError):
        return None
    return parse_undo_action(raw)


def set_undo_setting(db: Session, action: HabitCompletionUndoAction) -> None:
    serialized = json.dumps(
        action.to_payload(),
        ensure_ascii=False,
        separators=(",", ":"),
    )
    setting = db.get(AppSetting, HABIT_COMPLETION_UNDO_KEY)
    if setting is None:
        db.add(AppSetting(key=HABIT_COMPLETION_UNDO_KEY, value=serialized))
    else:
        setting.value = serialized


def delete_undo_setting(db: Session) -> bool:
    setting = db.get(AppSetting, HABIT_COMPLETION_UNDO_KEY)
    if setting is None:
        return False
    db.delete(setting)
    return True


def record_completion_undo(
    db: Session,
    target_date: date,
    before_habit_ids: Iterable[int],
    after_habit_ids: Iterable[int],
    *,
    source: str,
    now: datetime | None = None,
) -> HabitCompletionUndoAction | None:
    if source not in SOURCE_LABELS:
        raise ValueError("未対応のUndo操作種別です。")

    before = normalize_habit_ids(before_habit_ids)
    after = normalize_habit_ids(after_habit_ids)
    if before is None or after is None:
        raise ValueError("Undoへ保存する習慣IDが不正です。")
    if before == after:
        return None

    current_time = (now or utc_now()).astimezone(timezone.utc)
    action = HabitCompletionUndoAction(
        token=secrets.token_urlsafe(24),
        target_date=target_date,
        before_habit_ids=before,
        after_habit_ids=after,
        source=source,
        created_at=current_time,
        expires_at=current_time + UNDO_TTL,
    )
    set_undo_setting(db, action)
    db.commit()
    return action


def clear_completion_undo(db: Session) -> bool:
    if not delete_undo_setting(db):
        return False
    db.commit()
    return True


def get_available_completion_undo(
    db: Session,
    *,
    target_date: date | None = None,
    now: datetime | None = None,
) -> HabitCompletionUndoAction | None:
    action = get_stored_undo_action(db)
    if action is None:
        return None

    current_time = (now or utc_now()).astimezone(timezone.utc)
    if action.expires_at <= current_time:
        return None
    if target_date is not None and action.target_date != target_date:
        return None
    if get_completion_habit_ids(db, action.target_date) != action.after_habit_ids:
        return None
    return action


def undo_completion_change(
    db: Session,
    token: str,
    *,
    now: datetime | None = None,
) -> UndoResult:
    action = get_stored_undo_action(db)
    if action is None:
        return UndoResult(UndoResultStatus.NOT_FOUND)
    if not secrets.compare_digest(action.token, token):
        return UndoResult(UndoResultStatus.INVALID_TOKEN, action)

    current_time = (now or utc_now()).astimezone(timezone.utc)
    if action.expires_at <= current_time:
        delete_undo_setting(db)
        db.commit()
        return UndoResult(UndoResultStatus.EXPIRED, action)

    current_ids = get_completion_habit_ids(db, action.target_date)
    if current_ids != action.after_habit_ids:
        delete_undo_setting(db)
        db.commit()
        return UndoResult(UndoResultStatus.STATE_CHANGED, action)

    existing_habit_ids = set(
        db.scalars(
            select(Habit.id).where(Habit.id.in_(action.before_habit_ids))
        ).all()
    )
    if existing_habit_ids != set(action.before_habit_ids):
        delete_undo_setting(db)
        db.commit()
        return UndoResult(UndoResultStatus.MISSING_HABIT, action)

    completions = list(
        db.scalars(
            select(HabitCompletion).where(
                HabitCompletion.completed_on == action.target_date
            )
        ).all()
    )
    for completion in completions:
        db.delete(completion)
    for habit_id in action.before_habit_ids:
        db.add(
            HabitCompletion(
                habit_id=habit_id,
                completed_on=action.target_date,
            )
        )

    delete_undo_setting(db)
    db.commit()
    return UndoResult(UndoResultStatus.RESTORED, action)
