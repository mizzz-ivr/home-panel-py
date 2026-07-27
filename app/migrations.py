from __future__ import annotations

from sqlalchemy import Engine, inspect, text


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
