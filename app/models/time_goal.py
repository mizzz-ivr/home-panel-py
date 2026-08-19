from datetime import date, datetime

from sqlalchemy import CheckConstraint, Date, DateTime, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class DailyTimeGoalPeriod(Base):
    __tablename__ = "daily_time_goal_periods"
    __table_args__ = (
        UniqueConstraint("started_on", name="uq_daily_time_goal_period_start"),
        CheckConstraint(
            "goal_minutes BETWEEN 1 AND 1440",
            name="ck_daily_time_goal_period_minutes",
        ),
        CheckConstraint(
            "ended_on IS NULL OR ended_on >= started_on",
            name="ck_daily_time_goal_period_dates",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    goal_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    started_on: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    ended_on: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
