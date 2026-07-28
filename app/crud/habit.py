from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, time, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.habit_schedule import (
    ALL_WEEKDAYS_MASK,
    calculate_scheduled_streak,
    expected_dates_between,
    format_schedule,
    get_schedule_mask_on,
    is_expected_on,
    mask_to_weekdays,
    weekdays_to_mask,
)
from app.models.habit import (
    Habit,
    HabitActivePeriod,
    HabitCompletion,
    HabitSchedulePeriod,
)

MAX_ACTIVE_HABITS = 20


class HabitScheduleConflictError(ValueError):
    """曜日設定の変更で既存達成記録との不整合が発生する場合。"""


def list_active_habits(db: Session) -> list[Habit]:
    return list(
        db.scalars(
            select(Habit)
            .where(Habit.is_active.is_(True))
            .order_by(Habit.created_at.asc(), Habit.id.asc())
        ).all()
    )


def list_archived_habits(db: Session) -> list[Habit]:
    return list(
        db.scalars(
            select(Habit)
            .where(Habit.is_active.is_(False))
            .order_by(Habit.archived_at.desc(), Habit.id.desc())
        ).all()
    )


def list_all_habits(db: Session) -> list[Habit]:
    return list(db.scalars(select(Habit).order_by(Habit.created_at.asc(), Habit.id.asc())).all())


def list_active_periods(db: Session) -> list[HabitActivePeriod]:
    return list(
        db.scalars(
            select(HabitActivePeriod).order_by(
                HabitActivePeriod.habit_id.asc(),
                HabitActivePeriod.started_on.asc(),
                HabitActivePeriod.id.asc(),
            )
        ).all()
    )


def list_schedule_periods(db: Session) -> list[HabitSchedulePeriod]:
    return list(
        db.scalars(
            select(HabitSchedulePeriod).order_by(
                HabitSchedulePeriod.habit_id.asc(),
                HabitSchedulePeriod.started_on.asc(),
                HabitSchedulePeriod.id.asc(),
            )
        ).all()
    )


def list_completions_between(
    db: Session,
    start_date: date,
    end_date: date,
) -> list[HabitCompletion]:
    if end_date < start_date:
        return []

    return list(
        db.scalars(
            select(HabitCompletion)
            .where(
                HabitCompletion.completed_on >= start_date,
                HabitCompletion.completed_on <= end_date,
            )
            .order_by(
                HabitCompletion.completed_on.asc(),
                HabitCompletion.habit_id.asc(),
                HabitCompletion.id.asc(),
            )
        ).all()
    )


def count_active_habits(db: Session) -> int:
    return int(
        db.scalar(select(func.count(Habit.id)).where(Habit.is_active.is_(True))) or 0
    )


def find_active_habit_by_name(
    db: Session,
    name: str,
    *,
    exclude_habit_id: int | None = None,
) -> Habit | None:
    normalized = name.casefold()
    for habit in list_active_habits(db):
        if exclude_habit_id is not None and habit.id == exclude_habit_id:
            continue
        if habit.name.casefold() == normalized:
            return habit
    return None


def create_habit(
    db: Session,
    name: str,
    *,
    started_on: date | None = None,
    weekdays: tuple[int, ...] = tuple(range(7)),
) -> Habit:
    start_date = started_on or date.today()
    weekdays_mask = weekdays_to_mask(weekdays)
    habit = Habit(name=name)
    db.add(habit)
    db.flush()
    db.add(HabitActivePeriod(habit_id=habit.id, started_on=start_date))
    db.add(
        HabitSchedulePeriod(
            habit_id=habit.id,
            schedule_type="weekdays",
            weekdays_mask=weekdays_mask,
            started_on=start_date,
        )
    )
    db.commit()
    db.refresh(habit)
    return habit


def get_habit(db: Session, habit_id: int) -> Habit | None:
    return db.get(Habit, habit_id)


def get_active_habit(db: Session, habit_id: int) -> Habit | None:
    return db.scalar(
        select(Habit).where(Habit.id == habit_id, Habit.is_active.is_(True))
    )


def get_schedule_periods_for_habit(db: Session, habit_id: int) -> list[HabitSchedulePeriod]:
    return list(
        db.scalars(
            select(HabitSchedulePeriod)
            .where(HabitSchedulePeriod.habit_id == habit_id)
            .order_by(HabitSchedulePeriod.started_on.asc(), HabitSchedulePeriod.id.asc())
        ).all()
    )


def get_current_schedule_mask(db: Session, habit_id: int, target_date: date | None = None) -> int:
    selected_date = target_date or date.today()
    mask = get_schedule_mask_on(get_schedule_periods_for_habit(db, habit_id), selected_date)
    return mask if mask is not None else ALL_WEEKDAYS_MASK


def get_schedule_display(db: Session, habit_id: int, target_date: date | None = None) -> str:
    return format_schedule(get_current_schedule_mask(db, habit_id, target_date))


def rename_habit(db: Session, habit_id: int, name: str) -> Habit | None:
    habit = get_habit(db, habit_id)
    if habit is None:
        return None

    habit.name = name
    db.commit()
    db.refresh(habit)
    return habit


def update_habit_schedule(
    db: Session,
    habit_id: int,
    weekdays: list[int],
    *,
    changed_on: date | None = None,
) -> Habit | None:
    habit = get_habit(db, habit_id)
    if habit is None:
        return None

    change_date = changed_on or date.today()
    if change_date < habit.created_at.date():
        raise ValueError("習慣の作成日より前へ曜日設定を適用できません。")
    new_mask = weekdays_to_mask(weekdays)
    current_period = db.scalar(
        select(HabitSchedulePeriod)
        .where(
            HabitSchedulePeriod.habit_id == habit_id,
            HabitSchedulePeriod.ended_on.is_(None),
        )
        .order_by(HabitSchedulePeriod.started_on.desc(), HabitSchedulePeriod.id.desc())
    )

    existing_completion = db.scalar(
        select(HabitCompletion).where(
            HabitCompletion.habit_id == habit_id,
            HabitCompletion.completed_on == change_date,
        )
    )
    if existing_completion is not None and not (new_mask & (1 << change_date.weekday())):
        raise HabitScheduleConflictError(
            "変更日の達成記録があるため、その曜日を対象外にできません。先に達成を取り消してください。"
        )

    if current_period is None:
        db.add(
            HabitSchedulePeriod(
                habit_id=habit_id,
                schedule_type="weekdays",
                weekdays_mask=new_mask,
                started_on=change_date,
            )
        )
    elif current_period.started_on == change_date:
        current_period.weekdays_mask = new_mask
    elif change_date < current_period.started_on:
        raise ValueError("現在の曜日設定より前の日付へ変更できません。")
    elif current_period.weekdays_mask != new_mask:
        current_period.ended_on = change_date - timedelta(days=1)
        db.add(
            HabitSchedulePeriod(
                habit_id=habit_id,
                schedule_type="weekdays",
                weekdays_mask=new_mask,
                started_on=change_date,
            )
        )

    db.commit()
    db.refresh(habit)
    return habit


def is_habit_expected_on(db: Session, habit_id: int, target_date: date) -> bool:
    active_periods = list(
        db.scalars(
            select(HabitActivePeriod).where(HabitActivePeriod.habit_id == habit_id)
        ).all()
    )
    schedule_periods = get_schedule_periods_for_habit(db, habit_id)
    return is_expected_on(target_date, active_periods, schedule_periods)


def toggle_today_completion(db: Session, habit_id: int, target_date: date) -> bool | None:
    habit = get_active_habit(db, habit_id)
    if habit is None:
        return None

    completion = db.scalar(
        select(HabitCompletion).where(
            HabitCompletion.habit_id == habit_id,
            HabitCompletion.completed_on == target_date,
        )
    )
    if completion is None and not is_habit_expected_on(db, habit_id, target_date):
        return False
    if completion is None:
        db.add(HabitCompletion(habit_id=habit_id, completed_on=target_date))
        completed = True
    else:
        db.delete(completion)
        completed = False

    db.commit()
    return completed


def archive_habit(
    db: Session,
    habit_id: int,
    *,
    archived_on: date | None = None,
) -> bool:
    habit = get_active_habit(db, habit_id)
    if habit is None:
        return False

    changed_on = archived_on or date.today()
    changed_at = (
        datetime.combine(changed_on, time.min)
        if archived_on is not None
        else datetime.utcnow()
    )
    open_periods = list(
        db.scalars(
            select(HabitActivePeriod).where(
                HabitActivePeriod.habit_id == habit_id,
                HabitActivePeriod.ended_on.is_(None),
            )
        ).all()
    )
    if not open_periods:
        db.add(
            HabitActivePeriod(
                habit_id=habit_id,
                started_on=habit.created_at.date(),
                ended_on=changed_on,
            )
        )
    else:
        for period in open_periods:
            period.ended_on = max(changed_on, period.started_on)

    habit.is_active = False
    habit.archived_at = changed_at
    db.commit()
    return True


def restore_habit(
    db: Session,
    habit_id: int,
    *,
    restored_on: date | None = None,
) -> bool:
    habit = get_habit(db, habit_id)
    if habit is None or habit.is_active:
        return False

    changed_on = restored_on or date.today()
    latest_period = db.scalar(
        select(HabitActivePeriod)
        .where(HabitActivePeriod.habit_id == habit_id)
        .order_by(HabitActivePeriod.started_on.desc(), HabitActivePeriod.id.desc())
    )
    if latest_period is not None and latest_period.ended_on == changed_on:
        latest_period.ended_on = None
    else:
        db.add(HabitActivePeriod(habit_id=habit_id, started_on=changed_on))

    habit.is_active = True
    habit.archived_at = None
    db.commit()
    return True


def get_dashboard_summary(db: Session, today: date) -> tuple[list[dict[str, Any]], int, int]:
    habits = list_active_habits(db)
    if not habits:
        return [], 0, 0

    habit_ids = [habit.id for habit in habits]
    completions = list(
        db.scalars(
            select(HabitCompletion)
            .where(HabitCompletion.habit_id.in_(habit_ids))
            .order_by(HabitCompletion.completed_on.asc(), HabitCompletion.id.asc())
        ).all()
    )
    active_periods = list(
        db.scalars(
            select(HabitActivePeriod).where(HabitActivePeriod.habit_id.in_(habit_ids))
        ).all()
    )
    schedule_periods = list(
        db.scalars(
            select(HabitSchedulePeriod).where(HabitSchedulePeriod.habit_id.in_(habit_ids))
        ).all()
    )

    completion_dates: dict[int, set[date]] = defaultdict(set)
    active_periods_by_habit: dict[int, list[HabitActivePeriod]] = defaultdict(list)
    schedule_periods_by_habit: dict[int, list[HabitSchedulePeriod]] = defaultdict(list)
    for completion in completions:
        completion_dates[completion.habit_id].add(completion.completed_on)
    for period in active_periods:
        active_periods_by_habit[period.habit_id].append(period)
    for period in schedule_periods:
        schedule_periods_by_habit[period.habit_id].append(period)

    items: list[dict[str, Any]] = []
    completed_today = 0
    scheduled_today_count = 0
    for habit in habits:
        dates = completion_dates[habit.id]
        habit_active_periods = active_periods_by_habit[habit.id]
        habit_schedule_periods = schedule_periods_by_habit[habit.id]
        earliest_date = min(
            (period.started_on for period in habit_active_periods),
            default=habit.created_at.date(),
        )
        expected_dates = expected_dates_between(
            earliest_date,
            today,
            habit_active_periods,
            habit_schedule_periods,
        )
        scheduled_today = today in expected_dates
        is_completed_today = scheduled_today and today in dates
        if scheduled_today:
            scheduled_today_count += 1
        if is_completed_today:
            completed_today += 1
        current_mask = get_schedule_mask_on(habit_schedule_periods, today) or ALL_WEEKDAYS_MASK
        items.append(
            {
                "habit": habit,
                "completed_today": is_completed_today,
                "scheduled_today": scheduled_today,
                "schedule_label": format_schedule(current_mask),
                "schedule_weekdays": mask_to_weekdays(current_mask),
                "current_streak": calculate_scheduled_streak(dates, expected_dates, today),
            }
        )

    return items, completed_today, scheduled_today_count
