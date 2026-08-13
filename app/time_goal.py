from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.crud import app_setting as app_setting_crud

DAILY_TIME_GOAL_KEY = "daily_time_goal_minutes"
MIN_DAILY_TIME_GOAL_MINUTES = 1
MAX_DAILY_TIME_GOAL_MINUTES = 1440


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


def save_daily_time_goal(db: Session, minutes: int) -> None:
    if not MIN_DAILY_TIME_GOAL_MINUTES <= minutes <= MAX_DAILY_TIME_GOAL_MINUTES:
        raise ValueError(
            f"1日の時間目標は{MIN_DAILY_TIME_GOAL_MINUTES}〜{MAX_DAILY_TIME_GOAL_MINUTES}分で指定してください。"
        )
    app_setting_crud.upsert_json_setting(db, DAILY_TIME_GOAL_KEY, minutes)


def clear_daily_time_goal(db: Session) -> None:
    app_setting_crud.delete_setting(db, DAILY_TIME_GOAL_KEY)


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
