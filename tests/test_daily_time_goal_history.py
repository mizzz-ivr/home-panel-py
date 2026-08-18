from datetime import date, timedelta
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models.time_goal import DailyTimeGoalPeriod
from app.time_goal import (
    clear_daily_time_goal,
    list_daily_time_goal_periods,
    load_daily_time_goal,
    load_daily_time_goal_for_date,
    save_daily_time_goal,
)
from app.time_goal_constants import DAILY_TIME_GOAL_KEY
from app.time_goal_migration import migrate_daily_time_goal_periods


@pytest.fixture()
def session(tmp_path: Path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'goal-history.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    with session_factory() as db:
        yield db
    engine.dispose()


def test_same_day_goal_changes_update_one_period(session):
    target_date = date(2026, 8, 18)

    save_daily_time_goal(session, 120, effective_on=target_date)
    save_daily_time_goal(session, 90, effective_on=target_date)

    periods = list(session.scalars(select(DailyTimeGoalPeriod)).all())
    assert len(periods) == 1
    assert periods[0].goal_minutes == 90
    assert periods[0].started_on == target_date
    assert periods[0].ended_on is None
    assert load_daily_time_goal(session) == 90
    assert load_daily_time_goal_for_date(session, target_date) == 90


def test_same_goal_on_later_day_does_not_split_period(session):
    first_day = date(2026, 8, 10)

    save_daily_time_goal(session, 120, effective_on=first_day)
    save_daily_time_goal(session, 120, effective_on=first_day + timedelta(days=3))

    periods = list_daily_time_goal_periods(session)
    assert len(periods) == 1
    assert periods[0].started_on == first_day
    assert periods[0].ended_on is None


def test_goal_change_closes_previous_period_on_previous_day(session):
    first_day = date(2026, 8, 10)
    changed_on = date(2026, 8, 15)

    save_daily_time_goal(session, 60, effective_on=first_day)
    save_daily_time_goal(session, 120, effective_on=changed_on)

    periods = list(
        session.scalars(
            select(DailyTimeGoalPeriod).order_by(DailyTimeGoalPeriod.started_on.asc())
        ).all()
    )
    assert [(period.goal_minutes, period.started_on, period.ended_on) for period in periods] == [
        (60, first_day, changed_on - timedelta(days=1)),
        (120, changed_on, None),
    ]
    assert load_daily_time_goal_for_date(session, date(2026, 8, 14)) == 60
    assert load_daily_time_goal_for_date(session, changed_on) == 120


def test_clearing_goal_closes_period_and_creates_an_unconfigured_gap(session):
    first_day = date(2026, 8, 1)
    cleared_on = date(2026, 8, 5)

    save_daily_time_goal(session, 90, effective_on=first_day)
    clear_daily_time_goal(session, effective_on=cleared_on)

    period = session.scalar(select(DailyTimeGoalPeriod))
    assert period is not None
    assert period.ended_on == cleared_on - timedelta(days=1)
    assert load_daily_time_goal(session) is None
    assert load_daily_time_goal_for_date(session, date(2026, 8, 4)) == 90
    assert load_daily_time_goal_for_date(session, cleared_on) is None

    save_daily_time_goal(session, 120, effective_on=date(2026, 8, 8))
    assert load_daily_time_goal_for_date(session, date(2026, 8, 7)) is None
    assert load_daily_time_goal_for_date(session, date(2026, 8, 8)) == 120


def test_clearing_goal_on_its_start_day_removes_that_period(session):
    target_date = date(2026, 8, 18)

    save_daily_time_goal(session, 120, effective_on=target_date)
    clear_daily_time_goal(session, effective_on=target_date)

    assert session.scalar(select(DailyTimeGoalPeriod)) is None
    assert load_daily_time_goal(session) is None


def test_corrupt_multiple_open_periods_are_not_silently_used(session):
    session.add_all(
        [
            DailyTimeGoalPeriod(goal_minutes=60, started_on=date(2026, 8, 1)),
            DailyTimeGoalPeriod(goal_minutes=120, started_on=date(2026, 8, 10)),
        ]
    )
    session.commit()

    assert load_daily_time_goal_for_date(session, date(2026, 8, 18)) is None
    with pytest.raises(RuntimeError, match="開放中の期間が複数"):
        save_daily_time_goal(session, 90, effective_on=date(2026, 8, 18))


def test_migration_seeds_valid_existing_setting_from_migration_day(tmp_path: Path):
    database = tmp_path / "legacy-goal.db"
    engine = create_engine(f"sqlite:///{database.as_posix()}")
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE app_settings ("
                "key VARCHAR(100) PRIMARY KEY, "
                "value TEXT NOT NULL, "
                "updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP"
                ")"
            )
        )
        connection.execute(
            text("INSERT INTO app_settings (key, value) VALUES (:key, '120')"),
            {"key": DAILY_TIME_GOAL_KEY},
        )

    result = migrate_daily_time_goal_periods(engine)
    second_result = migrate_daily_time_goal_periods(engine)

    assert result == {"created_table": True, "seeded_current_goal": True}
    assert second_result == {"created_table": False, "seeded_current_goal": False}
    with engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT goal_minutes, started_on, ended_on "
                "FROM daily_time_goal_periods"
            )
        ).all()
    engine.dispose()

    assert len(rows) == 1
    assert rows[0][0] == 120
    assert str(rows[0][1]) == date.today().isoformat()
    assert rows[0][2] is None


def test_migration_does_not_invent_history_from_invalid_setting(tmp_path: Path):
    database = tmp_path / "invalid-goal.db"
    engine = create_engine(f"sqlite:///{database.as_posix()}")
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE app_settings ("
                "key VARCHAR(100) PRIMARY KEY, "
                "value TEXT NOT NULL, "
                "updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP"
                ")"
            )
        )
        connection.execute(
            text("INSERT INTO app_settings (key, value) VALUES (:key, '\"120\"')"),
            {"key": DAILY_TIME_GOAL_KEY},
        )

    result = migrate_daily_time_goal_periods(engine)

    assert result == {"created_table": True, "seeded_current_goal": False}
    with engine.connect() as connection:
        count = connection.scalar(text("SELECT COUNT(*) FROM daily_time_goal_periods"))
    engine.dispose()
    assert count == 0
