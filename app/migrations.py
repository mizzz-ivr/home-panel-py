from __future__ import annotations

from sqlalchemy import Engine, inspect, text

from app.habit_schedule import ALL_WEEKDAYS_MASK


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


def migrate_habit_target_weekdays(engine: Engine) -> bool:
    """既存習慣へ対象曜日マスクを追加し、毎日対象として補完する。"""
    inspector = inspect(engine)
    if "habits" not in inspector.get_table_names():
        return False

    column_names = {column["name"] for column in inspector.get_columns("habits")}
    added_column = "target_weekdays_mask" not in column_names

    with engine.begin() as connection:
        if added_column:
            connection.execute(
                text(
                    "ALTER TABLE habits ADD COLUMN target_weekdays_mask "
                    f"INTEGER NOT NULL DEFAULT {ALL_WEEKDAYS_MASK}"
                )
            )
        connection.execute(
            text(
                "UPDATE habits "
                f"SET target_weekdays_mask = {ALL_WEEKDAYS_MASK} "
                "WHERE target_weekdays_mask IS NULL "
                "OR target_weekdays_mask < 1 "
                f"OR target_weekdays_mask > {ALL_WEEKDAYS_MASK}"
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


def migrate_habit_schema(engine: Engine) -> dict[str, bool]:
    """習慣関連の互換移行を順序どおり実行する。"""
    return {
        "archived_at_added": migrate_habit_archived_at(engine),
        "target_weekdays_added": migrate_habit_target_weekdays(engine),
        "active_periods_created": migrate_habit_active_periods(engine),
    }
