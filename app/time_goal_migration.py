from __future__ import annotations

import json
from datetime import date, datetime

from sqlalchemy import Engine, inspect, text

from app.time_goal_constants import (
    DAILY_TIME_GOAL_KEY,
    MAX_DAILY_TIME_GOAL_MINUTES,
    MIN_DAILY_TIME_GOAL_MINUTES,
)


def _parse_existing_goal(raw_value: object) -> int | None:
    if not isinstance(raw_value, str):
        return None
    try:
        value = json.loads(raw_value)
    except (TypeError, json.JSONDecodeError):
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    if not MIN_DAILY_TIME_GOAL_MINUTES <= value <= MAX_DAILY_TIME_GOAL_MINUTES:
        return None
    return value


def migrate_daily_time_goal_periods(engine: Engine) -> dict[str, bool]:
    """時間目標の期間履歴テーブルを作成し、現在値だけを移行日から引き継ぐ。"""
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    created_table = "daily_time_goal_periods" not in existing_tables
    seeded_current_goal = False

    with engine.begin() as connection:
        if created_table:
            connection.execute(
                text(
                    "CREATE TABLE daily_time_goal_periods ("
                    "id INTEGER NOT NULL PRIMARY KEY, "
                    "goal_minutes INTEGER NOT NULL, "
                    "started_on DATE NOT NULL, "
                    "ended_on DATE NULL, "
                    "created_at DATETIME NOT NULL, "
                    "CONSTRAINT uq_daily_time_goal_period_start UNIQUE (started_on), "
                    "CONSTRAINT ck_daily_time_goal_period_minutes "
                    "CHECK (goal_minutes BETWEEN 1 AND 1440), "
                    "CONSTRAINT ck_daily_time_goal_period_dates "
                    "CHECK (ended_on IS NULL OR ended_on >= started_on)"
                    ")"
                )
            )
            connection.execute(
                text(
                    "CREATE INDEX ix_daily_time_goal_periods_started_on "
                    "ON daily_time_goal_periods (started_on)"
                )
            )
            connection.execute(
                text(
                    "CREATE INDEX ix_daily_time_goal_periods_ended_on "
                    "ON daily_time_goal_periods (ended_on)"
                )
            )

            if "app_settings" in existing_tables:
                raw_value = connection.scalar(
                    text("SELECT value FROM app_settings WHERE key = :key"),
                    {"key": DAILY_TIME_GOAL_KEY},
                )
                current_goal = _parse_existing_goal(raw_value)
                if current_goal is not None:
                    connection.execute(
                        text(
                            "INSERT INTO daily_time_goal_periods "
                            "(goal_minutes, started_on, ended_on, created_at) "
                            "VALUES (:goal_minutes, :started_on, NULL, :created_at)"
                        ),
                        {
                            "goal_minutes": current_goal,
                            "started_on": date.today(),
                            "created_at": datetime.utcnow(),
                        },
                    )
                    seeded_current_goal = True

    return {
        "created_table": created_table,
        "seeded_current_goal": seeded_current_goal,
    }
