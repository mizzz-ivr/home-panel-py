from __future__ import annotations

import json
from datetime import date

from .backup_restore_legacy_tests import *  # noqa: F401,F403
from app.models.time_goal import DailyTimeGoalPeriod
from app.time_goal_constants import DAILY_TIME_GOAL_KEY


def test_restore_v5_to_new_database_preserves_all_data(tmp_path: Path):
    payload = make_v5_payload()
    backup = write_payload(tmp_path / "backup.json", payload)
    database = tmp_path / "restored.db"

    result = restore_backup_file(backup, database)
    normalized = normalize_backup_payload(payload)

    assert result.database_path == database.resolve()
    assert result.source_schema_version == 5
    assert result.record_counts == normalized["record_counts"]
    assert result.safety_copy_path is None
    restored = export_database(database)
    assert restored["data"] == normalized["data"]
    assert restored["data"]["daily_time_goal_periods"] == []

    engine = create_engine(f"sqlite:///{database.as_posix()}")
    session_factory = sessionmaker(bind=engine)
    with session_factory() as db:
        assert db.scalar(select(AppSetting)) is None
    engine.dispose()


def test_restore_v7_preserves_goal_history_and_rebuilds_current_setting(tmp_path: Path):
    payload = normalize_backup_payload(make_v5_payload())
    payload["data"]["daily_time_goal_periods"] = [
        {
            "id": 1,
            "goal_minutes": 60,
            "started_on": "2026-07-01",
            "ended_on": "2026-07-09",
            "created_at": STAMP,
        },
        {
            "id": 2,
            "goal_minutes": 120,
            "started_on": "2026-07-10",
            "ended_on": None,
            "created_at": "2026-07-10T00:00:00Z",
        },
    ]
    payload["record_counts"]["daily_time_goal_periods"] = 2
    backup = write_payload(tmp_path / "backup-v7.json", payload)
    database = tmp_path / "restored-v7.db"

    result = restore_backup_file(backup, database)

    assert result.source_schema_version == 7
    assert result.record_counts["daily_time_goal_periods"] == 2
    assert export_database(database)["data"] == payload["data"]

    engine = create_engine(f"sqlite:///{database.as_posix()}")
    session_factory = sessionmaker(bind=engine)
    with session_factory() as db:
        periods = list(
            db.scalars(
                select(DailyTimeGoalPeriod).order_by(DailyTimeGoalPeriod.started_on.asc())
            ).all()
        )
        setting = db.get(AppSetting, DAILY_TIME_GOAL_KEY)
        assert [(period.goal_minutes, period.started_on, period.ended_on) for period in periods] == [
            (60, date(2026, 7, 1), date(2026, 7, 9)),
            (120, date(2026, 7, 10), None),
        ]
        assert setting is not None
        assert json.loads(setting.value) == 120
    engine.dispose()


def test_restore_v7_with_closed_goal_history_keeps_current_goal_unset(tmp_path: Path):
    payload = normalize_backup_payload(make_v5_payload())
    payload["data"]["daily_time_goal_periods"] = [
        {
            "id": 1,
            "goal_minutes": 90,
            "started_on": "2026-07-01",
            "ended_on": "2026-07-31",
            "created_at": STAMP,
        }
    ]
    payload["record_counts"]["daily_time_goal_periods"] = 1
    backup = write_payload(tmp_path / "backup-v7-closed.json", payload)
    database = tmp_path / "restored-v7-closed.db"

    restore_backup_file(backup, database)

    engine = create_engine(f"sqlite:///{database.as_posix()}")
    session_factory = sessionmaker(bind=engine)
    with session_factory() as db:
        assert db.get(AppSetting, DAILY_TIME_GOAL_KEY) is None
    engine.dispose()


def test_existing_empty_database_is_copied_before_replace(tmp_path: Path):
    payload = make_v5_payload()
    backup = write_payload(tmp_path / "backup.json", payload)
    database = tmp_path / "home_panel.db"
    engine = create_engine(f"sqlite:///{database.as_posix()}")
    Base.metadata.create_all(bind=engine)
    engine.dispose()
    previous_bytes = database.read_bytes()

    result = restore_backup_file(
        backup,
        database,
        restored_at=datetime(2026, 8, 4, 0, 0, tzinfo=timezone.utc),
    )

    assert result.safety_copy_path == tmp_path / "home_panel.pre-restore-20260804T000000Z.db"
    assert result.safety_copy_path.read_bytes() == previous_bytes
    assert export_database(database)["data"] == normalize_backup_payload(payload)["data"]
