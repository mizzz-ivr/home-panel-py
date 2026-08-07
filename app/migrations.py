from __future__ import annotations

from sqlalchemy import Engine, inspect, text

from app.habit_schedule import ALL_WEEKDAYS_MASK
from app.task_priority import DEFAULT_TASK_PRIORITY


def migrate_task_metadata(engine: Engine) -> dict[str, bool]:
    """既存のtasksテーブルへ期限・優先度を追加し、既定値を補完する。"""
    inspector = inspect(engine)
    if "tasks" not in inspector.get_table_names():
        return {"due_date_added": False, "priority_added": False}

    column_names = {column["name"] for column in inspector.get_columns("tasks")}
    due_date_added = "due_date" not in column_names
    priority_added = "priority" not in column_names

    with engine.begin() as connection:
        if due_date_added:
            connection.execute(text("ALTER TABLE tasks ADD COLUMN due_date DATE"))
        if priority_added:
            connection.execute(
                text(
                    "ALTER TABLE tasks ADD COLUMN priority VARCHAR(10) "
                    f"NOT NULL DEFAULT '{DEFAULT_TASK_PRIORITY}'"
                )
            )

        connection.execute(
            text(
                "UPDATE tasks "
                f"SET priority = '{DEFAULT_TASK_PRIORITY}' "
                "WHERE priority IS NULL "
                "OR priority NOT IN ('low', 'medium', 'high')"
            )
        )
        connection.execute(
            text("CREATE INDEX IF NOT EXISTS ix_tasks_due_date ON tasks (due_date)")
        )
        connection.execute(
            text("CREATE INDEX IF NOT EXISTS ix_tasks_priority ON tasks (priority)")
        )

    return {
        "due_date_added": due_date_added,
        "priority_added": priority_added,
    }


def migrate_habit_archived_at(engine: Engine) -> bool:
    """既存のhabitsテーブルへarchived_at列を追加し、終了済みデータを補完する。"""
    inspector = inspect(engine)
    if "habits" not in inspector.get_table_names():
        return False

    column_names = {column["name"] for column in inspector.get_columns("habits")}
    added_column = "archived_at" not in column_names

    with engine.begin() as connection:
        if added_column:
            connection.execute(text("ALTER TABLE habits ADD COLUMN archived_at DATETIME"))

        connection.execute(
            text(
                "UPDATE habits "
                "SET archived_at = updated_at "
                "WHERE is_active = 0 AND archived_at IS NULL"
            )
        )
        connection.execute(
            text(
                "UPDATE habits "
                "SET archived_at = NULL "
                "WHERE is_active = 1 AND archived_at IS NOT NULL"
            )
        )

    return added_column


def migrate_habit_active_periods(engine: Engine) -> bool:
    """習慣の開始・終了区間テーブルを作成し、既存習慣から初期区間を生成する。"""
    inspector = inspect(engine)
    if "habits" not in inspector.get_table_names():
        return False

    created_table = "habit_active_periods" not in inspector.get_table_names()
    with engine.begin() as connection:
        if created_table:
            connection.execute(
                text(
                    "CREATE TABLE habit_active_periods ("
                    "id INTEGER NOT NULL PRIMARY KEY, "
                    "habit_id INTEGER NOT NULL, "
                    "started_on DATE NOT NULL, "
                    "ended_on DATE NULL, "
                    "created_at DATETIME NOT NULL, "
                    "CONSTRAINT uq_habit_active_period_start UNIQUE (habit_id, started_on), "
                    "CONSTRAINT ck_habit_active_period_dates "
                    "CHECK (ended_on IS NULL OR ended_on >= started_on), "
                    "FOREIGN KEY(habit_id) REFERENCES habits (id) ON DELETE CASCADE"
                    ")"
                )
            )
            connection.execute(
                text(
                    "CREATE INDEX ix_habit_active_periods_habit_id "
                    "ON habit_active_periods (habit_id)"
                )
            )
            connection.execute(
                text(
                    "CREATE INDEX ix_habit_active_periods_started_on "
                    "ON habit_active_periods (started_on)"
                )
            )
            connection.execute(
                text(
                    "CREATE INDEX ix_habit_active_periods_ended_on "
                    "ON habit_active_periods (ended_on)"
                )
            )

        connection.execute(
            text(
                "INSERT INTO habit_active_periods "
                "(habit_id, started_on, ended_on, created_at) "
                "SELECT h.id, date(h.created_at), "
                "CASE WHEN h.is_active = 0 "
                "THEN date(COALESCE(h.archived_at, h.updated_at)) ELSE NULL END, "
                "CURRENT_TIMESTAMP "
                "FROM habits h "
                "WHERE NOT EXISTS ("
                "SELECT 1 FROM habit_active_periods p WHERE p.habit_id = h.id"
                ")"
            )
        )
        connection.execute(
            text(
                "UPDATE habit_active_periods "
                "SET ended_on = ("
                "SELECT date(COALESCE(h.archived_at, h.updated_at)) "
                "FROM habits h WHERE h.id = habit_active_periods.habit_id"
                ") "
                "WHERE ended_on IS NULL AND habit_id IN ("
                "SELECT id FROM habits WHERE is_active = 0"
                ")"
            )
        )
        connection.execute(
            text(
                "INSERT INTO habit_active_periods "
                "(habit_id, started_on, ended_on, created_at) "
                "SELECT h.id, date(h.updated_at), NULL, CURRENT_TIMESTAMP "
                "FROM habits h "
                "WHERE h.is_active = 1 "
                "AND NOT EXISTS ("
                "SELECT 1 FROM habit_active_periods p "
                "WHERE p.habit_id = h.id AND p.ended_on IS NULL"
                ") "
                "AND NOT EXISTS ("
                "SELECT 1 FROM habit_active_periods p "
                "WHERE p.habit_id = h.id AND p.started_on = date(h.updated_at)"
                ")"
            )
        )

    return created_table


def migrate_habit_schedule_periods(engine: Engine) -> bool:
    """対象曜日の適用期間テーブルを作成し、既存習慣を毎日対象で補完する。"""
    inspector = inspect(engine)
    if "habits" not in inspector.get_table_names():
        return False

    created_table = "habit_schedule_periods" not in inspector.get_table_names()
    with engine.begin() as connection:
        if created_table:
            connection.execute(
                text(
                    "CREATE TABLE habit_schedule_periods ("
                    "id INTEGER NOT NULL PRIMARY KEY, "
                    "habit_id INTEGER NOT NULL, "
                    "schedule_type VARCHAR(20) NOT NULL, "
                    "weekdays_mask INTEGER NOT NULL, "
                    "started_on DATE NOT NULL, "
                    "ended_on DATE NULL, "
                    "created_at DATETIME NOT NULL, "
                    "CONSTRAINT uq_habit_schedule_period_start UNIQUE (habit_id, started_on), "
                    "CONSTRAINT ck_habit_schedule_period_dates "
                    "CHECK (ended_on IS NULL OR ended_on >= started_on), "
                    "CONSTRAINT ck_habit_schedule_weekdays_mask "
                    "CHECK (weekdays_mask BETWEEN 1 AND 127), "
                    "CONSTRAINT ck_habit_schedule_type "
                    "CHECK (schedule_type = 'weekdays'), "
                    "FOREIGN KEY(habit_id) REFERENCES habits (id) ON DELETE CASCADE"
                    ")"
                )
            )
            connection.execute(
                text(
                    "CREATE INDEX ix_habit_schedule_periods_habit_id "
                    "ON habit_schedule_periods (habit_id)"
                )
            )
            connection.execute(
                text(
                    "CREATE INDEX ix_habit_schedule_periods_started_on "
                    "ON habit_schedule_periods (started_on)"
                )
            )
            connection.execute(
                text(
                    "CREATE INDEX ix_habit_schedule_periods_ended_on "
                    "ON habit_schedule_periods (ended_on)"
                )
            )

        connection.execute(
            text(
                "INSERT INTO habit_schedule_periods "
                "(habit_id, schedule_type, weekdays_mask, started_on, ended_on, created_at) "
                f"SELECT h.id, 'weekdays', {ALL_WEEKDAYS_MASK}, date(h.created_at), NULL, "
                "CURRENT_TIMESTAMP FROM habits h "
                "WHERE NOT EXISTS ("
                "SELECT 1 FROM habit_schedule_periods s WHERE s.habit_id = h.id"
                ")"
            )
        )
        connection.execute(
            text(
                "UPDATE habit_schedule_periods SET ended_on = NULL "
                "WHERE id IN ("
                "SELECT latest.id FROM habit_schedule_periods latest "
                "WHERE NOT EXISTS ("
                "SELECT 1 FROM habit_schedule_periods opened "
                "WHERE opened.habit_id = latest.habit_id AND opened.ended_on IS NULL"
                ") "
                "AND latest.started_on = ("
                "SELECT MAX(candidate.started_on) FROM habit_schedule_periods candidate "
                "WHERE candidate.habit_id = latest.habit_id"
                ")"
                ")"
            )
        )

    return created_table


def migrate_habit_schema(engine: Engine) -> dict[str, bool]:
    """習慣関連の互換移行を順序どおり実行する。"""
    archived_at_added = migrate_habit_archived_at(engine)
    active_periods_created = migrate_habit_active_periods(engine)
    migrate_habit_schedule_periods(engine)
    return {
        "archived_at_added": archived_at_added,
        "active_periods_created": active_periods_created,
    }


def migrate_home_panel_schema(engine: Engine) -> dict[str, dict[str, bool]]:
    """Home Panel全体の軽量互換移行を順序どおり実行する。"""
    return {
        "tasks": migrate_task_metadata(engine),
        "habits": migrate_habit_schema(engine),
    }
