import json
from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.crud import app_setting as app_setting_crud
from app.models.app_setting import AppSetting
from app.models.time_goal import DailyTimeGoalPeriod
from app.time_goal_constants import (
    DAILY_TIME_GOAL_KEY,
    MAX_DAILY_TIME_GOAL_MINUTES,
    MIN_DAILY_TIME_GOAL_MINUTES,
)


@dataclass(frozen=True)
class DailyTimeGoalStatus:
    goal_minutes: int | None
    total_minutes: int
    percentage: int
    progress_percentage: int
    remaining_minutes: int
    exceeded_minutes: int

    @property
    def configured(self) -> bool:
        return self.goal_minutes is not None

    @property
    def achieved(self) -> bool:
        return self.goal_minutes is not None and self.total_minutes >= self.goal_minutes


def load_daily_time_goal(db: Session) -> int | None:
    raw_value = app_setting_crud.get_json_setting(db, DAILY_TIME_GOAL_KEY)
    if isinstance(raw_value, bool) or not isinstance(raw_value, int):
        return None
    if not MIN_DAILY_TIME_GOAL_MINUTES <= raw_value <= MAX_DAILY_TIME_GOAL_MINUTES:
        return None
    return raw_value


def _validate_goal_minutes(minutes: int) -> None:
    if (
        isinstance(minutes, bool)
        or not isinstance(minutes, int)
        or not MIN_DAILY_TIME_GOAL_MINUTES <= minutes <= MAX_DAILY_TIME_GOAL_MINUTES
    ):
        raise ValueError(
            f"1日の時間目標は{MIN_DAILY_TIME_GOAL_MINUTES}〜{MAX_DAILY_TIME_GOAL_MINUTES}分で指定してください。"
        )


def _get_open_period(db: Session) -> DailyTimeGoalPeriod | None:
    periods = list(
        db.scalars(
            select(DailyTimeGoalPeriod)
            .where(DailyTimeGoalPeriod.ended_on.is_(None))
            .order_by(DailyTimeGoalPeriod.started_on.desc(), DailyTimeGoalPeriod.id.desc())
        ).all()
    )
    if len(periods) > 1:
        raise RuntimeError("時間目標履歴に開放中の期間が複数あります。")
    return periods[0] if periods else None


def _upsert_current_setting(db: Session, minutes: int) -> None:
    serialized = json.dumps(minutes, ensure_ascii=False, separators=(",", ":"))
    setting = db.get(AppSetting, DAILY_TIME_GOAL_KEY)
    if setting is None:
        db.add(AppSetting(key=DAILY_TIME_GOAL_KEY, value=serialized))
    else:
        setting.value = serialized


def save_daily_time_goal(
    db: Session,
    minutes: int,
    *,
    effective_on: date | None = None,
) -> None:
    _validate_goal_minutes(minutes)
    target_date = effective_on or date.today()
    open_period = _get_open_period(db)

    if open_period is not None and open_period.started_on > target_date:
        raise RuntimeError("時間目標履歴の開始日が変更日より未来です。")

    _upsert_current_setting(db, minutes)

    if open_period is None:
        db.add(
            DailyTimeGoalPeriod(
                goal_minutes=minutes,
                started_on=target_date,
            )
        )
    elif open_period.started_on == target_date:
        open_period.goal_minutes = minutes
    elif open_period.goal_minutes != minutes:
        open_period.ended_on = target_date - timedelta(days=1)
        db.add(
            DailyTimeGoalPeriod(
                goal_minutes=minutes,
                started_on=target_date,
            )
        )

    db.commit()


def clear_daily_time_goal(
    db: Session,
    *,
    effective_on: date | None = None,
) -> None:
    target_date = effective_on or date.today()
    open_period = _get_open_period(db)
    if open_period is not None and open_period.started_on > target_date:
        raise RuntimeError("時間目標履歴の開始日が解除日より未来です。")

    setting = db.get(AppSetting, DAILY_TIME_GOAL_KEY)
    if setting is not None:
        db.delete(setting)

    if open_period is not None:
        if open_period.started_on == target_date:
            db.delete(open_period)
        else:
            open_period.ended_on = target_date - timedelta(days=1)

    db.commit()


def load_daily_time_goal_for_date(db: Session, target_date: date) -> int | None:
    periods = list(
        db.scalars(
            select(DailyTimeGoalPeriod)
            .where(
                DailyTimeGoalPeriod.started_on <= target_date,
                or_(
                    DailyTimeGoalPeriod.ended_on.is_(None),
                    DailyTimeGoalPeriod.ended_on >= target_date,
                ),
            )
            .order_by(DailyTimeGoalPeriod.started_on.desc(), DailyTimeGoalPeriod.id.desc())
            .limit(2)
        ).all()
    )
    if len(periods) != 1:
        return None
    return periods[0].goal_minutes


def list_daily_time_goal_periods(
    db: Session,
    *,
    limit: int = 5,
) -> list[DailyTimeGoalPeriod]:
    if limit < 1:
        return []
    return list(
        db.scalars(
            select(DailyTimeGoalPeriod)
            .order_by(DailyTimeGoalPeriod.started_on.desc(), DailyTimeGoalPeriod.id.desc())
            .limit(limit)
        ).all()
    )


def build_daily_time_goal_status(
    goal_minutes: int | None,
    total_minutes: int,
) -> DailyTimeGoalStatus:
    if goal_minutes is None:
        return DailyTimeGoalStatus(
            goal_minutes=None,
            total_minutes=total_minutes,
            percentage=0,
            progress_percentage=0,
            remaining_minutes=0,
            exceeded_minutes=0,
        )

    percentage = total_minutes * 100 // goal_minutes
    return DailyTimeGoalStatus(
        goal_minutes=goal_minutes,
        total_minutes=total_minutes,
        percentage=percentage,
        progress_percentage=min(percentage, 100),
        remaining_minutes=max(goal_minutes - total_minutes, 0),
        exceeded_minutes=max(total_minutes - goal_minutes, 0),
    )
