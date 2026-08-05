import os
import subprocess
import sys
from pathlib import Path

from sqlalchemy import create_engine, inspect, text

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def run_python(code: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(PROJECT_ROOT)
    return subprocess.run(
        [sys.executable, "-c", code],
        cwd=cwd,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )


def test_importing_database_module_does_not_create_default_database(tmp_path: Path):
    result = run_python("import app.db", tmp_path)

    assert result.returncode == 0, result.stderr
    assert not (tmp_path / "home_panel.db").exists()


def test_create_all_migrates_legacy_schema_before_creating_tables(tmp_path: Path):
    database = tmp_path / "legacy.db"
    engine = create_engine(f"sqlite:///{database.as_posix()}")
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE habits ("
                "id INTEGER PRIMARY KEY, "
                "name VARCHAR(100) NOT NULL, "
                "is_active BOOLEAN NOT NULL, "
                "created_at DATETIME NOT NULL, "
                "updated_at DATETIME NOT NULL"
                ")"
            )
        )
        connection.execute(
            text(
                "INSERT INTO habits VALUES "
                "(1, '旧習慣', 0, '2026-07-01 00:00:00', '2026-07-10 00:00:00')"
            )
        )
    engine.dispose()

    code = (
        "from sqlalchemy import create_engine; "
        "from app import models; "
        "from app.db import Base; "
        f"engine = create_engine('sqlite:///{database.as_posix()}'); "
        "Base.metadata.create_all(bind=engine); "
        "engine.dispose()"
    )
    result = run_python(code, tmp_path)

    assert result.returncode == 0, result.stderr
    engine = create_engine(f"sqlite:///{database.as_posix()}")
    inspector = inspect(engine)
    columns = {column["name"] for column in inspector.get_columns("habits")}
    assert "archived_at" in columns
    assert "habit_active_periods" in inspector.get_table_names()
    assert "habit_schedule_periods" in inspector.get_table_names()
    with engine.connect() as connection:
        archived_at = connection.scalar(
            text("SELECT archived_at FROM habits WHERE id = 1")
        )
        active_period = connection.execute(
            text(
                "SELECT started_on, ended_on "
                "FROM habit_active_periods WHERE habit_id = 1"
            )
        ).one()
        schedule_count = connection.scalar(
            text(
                "SELECT COUNT(*) FROM habit_schedule_periods WHERE habit_id = 1"
            )
        )
    engine.dispose()

    assert str(archived_at).startswith("2026-07-10")
    assert tuple(str(value) for value in active_period) == (
        "2026-07-01",
        "2026-07-10",
    )
    assert schedule_count == 1
