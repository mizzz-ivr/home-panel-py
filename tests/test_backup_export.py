from __future__ import annotations

from .backup_export_legacy_tests import *  # noqa: F401,F403


def test_build_backup_payload_contains_all_tables_and_counts(session):
    created_at = datetime(2026, 7, 24, 1, 2, 3)
    archived_at = datetime(2026, 7, 24, 3, 0, 0)
    task = Task(
        title="日本語タスク",
        is_done=True,
        due_date=date(2026, 7, 25),
        priority="high",
        created_at=created_at,
        updated_at=created_at,
    )
    session.add(task)
    session.add(
        DailyMemo(
            memo_date=date(2026, 7, 23),
            content="メモ内容",
            updated_at=created_at,
        )
    )
    session.add(
        TimeEntry(
            entry_date=date(2026, 7, 23),
            category="個人開発",
            minutes=90,
            note="API実装",
            created_at=created_at,
        )
    )
    habit = Habit(
        name="平日読書",
        is_active=False,
        archived_at=archived_at,
        created_at=created_at,
        updated_at=archived_at,
    )
    session.add(habit)
    session.flush()
    session.add_all(
        [
            HabitActivePeriod(
                habit_id=habit.id,
                started_on=date(2026, 7, 1),
                ended_on=date(2026, 7, 24),
                created_at=created_at,
            ),
            HabitSchedulePeriod(
                habit_id=habit.id,
                schedule_type="weekdays",
                weekdays_mask=31,
                started_on=date(2026, 7, 1),
                created_at=created_at,
            ),
            HabitCompletion(
                habit_id=habit.id,
                completed_on=date(2026, 7, 23),
                created_at=created_at,
            ),
        ]
    )
    session.commit()

    payload = build_backup_payload(
        session,
        exported_at=datetime(2026, 7, 24, 4, 5, 6, tzinfo=timezone.utc),
    )

    assert payload["schema_version"] == 6
    assert payload["application"] == "home-panel-py"
    assert payload["record_counts"] == {
        "tasks": 1,
        "daily_memos": 1,
        "time_entries": 1,
        "habits": 1,
        "habit_active_periods": 1,
        "habit_schedule_periods": 1,
        "habit_completions": 1,
    }
    task_record = payload["data"]["tasks"][0]
    assert task_record["due_date"] == "2026-07-25"
    assert task_record["priority"] == "high"
    assert payload["data"]["habit_schedule_periods"][0]["weekdays"] == [0, 1, 2, 3, 4]


def test_write_backup_file_overwrites_with_force(session, tmp_path: Path):
    output = tmp_path / "backup.json"
    output.write_text("existing", encoding="utf-8")

    write_backup_file(session, output, overwrite=True)

    assert json.loads(output.read_text(encoding="utf-8"))["schema_version"] == 6


def test_run_cli_migrates_legacy_habits_before_export(tmp_path: Path):
    database = tmp_path / "legacy.db"
    engine = create_engine(f"sqlite:///{database}")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE tasks (id INTEGER PRIMARY KEY, title VARCHAR(255) NOT NULL, is_done BOOLEAN NOT NULL, created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL)"))
        connection.execute(text("CREATE TABLE daily_memos (id INTEGER PRIMARY KEY, memo_date DATE NOT NULL, content TEXT NOT NULL, updated_at DATETIME NOT NULL)"))
        connection.execute(text("CREATE TABLE time_entries (id INTEGER PRIMARY KEY, entry_date DATE NOT NULL, category VARCHAR(20) NOT NULL, minutes INTEGER NOT NULL, note VARCHAR(255) NOT NULL, created_at DATETIME NOT NULL)"))
        connection.execute(text("CREATE TABLE habits (id INTEGER PRIMARY KEY, name VARCHAR(100) NOT NULL, is_active BOOLEAN NOT NULL, created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL)"))
        connection.execute(text("CREATE TABLE habit_completions (id INTEGER PRIMARY KEY, habit_id INTEGER NOT NULL, completed_on DATE NOT NULL, created_at DATETIME NOT NULL)"))
        connection.execute(text("INSERT INTO habits VALUES (1, '旧習慣', 0, '2026-07-01 00:00:00', '2026-07-10 00:00:00')"))
        connection.execute(text("INSERT INTO tasks VALUES (1, '旧タスク', 0, '2026-07-01 00:00:00', '2026-07-01 00:00:00')"))
    engine.dispose()
    output = tmp_path / "legacy-backup.json"

    assert run_cli(["--database", str(database), "--output", str(output)]) == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["schema_version"] == 6
    assert payload["data"]["tasks"][0]["due_date"] is None
    assert payload["data"]["tasks"][0]["priority"] == "medium"
    assert payload["data"]["habits"][0]["archived_at"] == "2026-07-10T00:00:00Z"
    assert payload["data"]["habit_active_periods"][0]["ended_on"] == "2026-07-10"
    assert payload["data"]["habit_schedule_periods"][0]["weekdays"] == list(range(7))
