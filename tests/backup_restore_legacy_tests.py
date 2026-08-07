import copy
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import sessionmaker

from app import backup_restore
from app.backup_export import build_backup_payload
from app.backup_restore import (
    BackupRestoreInputError,
    DestinationNotEmptyError,
    normalize_backup_payload,
    prepare_backup_for_restore,
    restore_backup_file,
    run_cli,
)
from app.db import Base
from app.models.app_setting import AppSetting
from app.models.task import Task

EXPORTED_AT = "2026-07-31T00:00:00Z"
STAMP = "2026-07-01T00:00:00Z"


def make_v5_payload() -> dict:
    return {
        "schema_version": 5,
        "application": "home-panel-py",
        "exported_at": EXPORTED_AT,
        "record_counts": {
            "tasks": 1,
            "daily_memos": 1,
            "time_entries": 1,
            "habits": 1,
            "habit_active_periods": 1,
            "habit_schedule_periods": 1,
            "habit_completions": 1,
        },
        "data": {
            "tasks": [
                {
                    "id": 4,
                    "title": "復元対象",
                    "is_done": True,
                    "created_at": STAMP,
                    "updated_at": STAMP,
                }
            ],
            "daily_memos": [
                {
                    "id": 3,
                    "memo_date": "2026-07-01",
                    "content": "復元メモ",
                    "updated_at": STAMP,
                }
            ],
            "time_entries": [
                {
                    "id": 2,
                    "entry_date": "2026-07-01",
                    "category": "学習",
                    "minutes": 45,
                    "note": "復元テスト",
                    "created_at": STAMP,
                }
            ],
            "habits": [
                {
                    "id": 8,
                    "name": "読書",
                    "is_active": True,
                    "archived_at": None,
                    "created_at": STAMP,
                    "updated_at": STAMP,
                }
            ],
            "habit_active_periods": [
                {
                    "id": 6,
                    "habit_id": 8,
                    "started_on": "2026-07-01",
                    "ended_on": None,
                    "created_at": STAMP,
                }
            ],
            "habit_schedule_periods": [
                {
                    "id": 7,
                    "habit_id": 8,
                    "schedule_type": "weekdays",
                    "weekdays": [0, 1, 2, 3, 4, 5, 6],
                    "started_on": "2026-07-01",
                    "ended_on": None,
                    "created_at": STAMP,
                }
            ],
            "habit_completions": [
                {
                    "id": 9,
                    "habit_id": 8,
                    "completed_on": "2026-07-01",
                    "created_at": STAMP,
                }
            ],
        },
    }


def make_v1_payload() -> dict:
    current = make_v5_payload()
    tables = ("tasks", "daily_memos", "time_entries")
    return {
        "schema_version": 1,
        "application": current["application"],
        "exported_at": current["exported_at"],
        "record_counts": {
            table_name: current["record_counts"][table_name]
            for table_name in tables
        },
        "data": {
            table_name: copy.deepcopy(current["data"][table_name])
            for table_name in tables
        },
    }


def make_v2_payload(*, invalid_completion: bool = False) -> dict:
    current = make_v5_payload()
    habit = copy.deepcopy(current["data"]["habits"][0])
    habit.pop("archived_at")
    habit["is_active"] = False
    habit["updated_at"] = (
        "2026-07-03T00:00:00Z"
        if invalid_completion
        else "2026-07-10T00:00:00Z"
    )
    completion = copy.deepcopy(current["data"]["habit_completions"][0])
    completion["completed_on"] = "2026-07-05"
    tables = (
        "tasks",
        "daily_memos",
        "time_entries",
        "habits",
        "habit_completions",
    )
    data = {
        "tasks": copy.deepcopy(current["data"]["tasks"]),
        "daily_memos": copy.deepcopy(current["data"]["daily_memos"]),
        "time_entries": copy.deepcopy(current["data"]["time_entries"]),
        "habits": [habit],
        "habit_completions": [completion],
    }
    return {
        "schema_version": 2,
        "application": current["application"],
        "exported_at": current["exported_at"],
        "record_counts": {
            table_name: len(data[table_name]) for table_name in tables
        },
        "data": data,
    }


def write_payload(path: Path, payload: dict) -> Path:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return path


def export_database(path: Path) -> dict:
    engine = create_engine(
        f"sqlite:///{path.as_posix()}",
        connect_args={"check_same_thread": False},
    )
    session_factory = sessionmaker(
        autocommit=False,
        autoflush=False,
        bind=engine,
    )
    with session_factory() as db:
        payload = build_backup_payload(
            db,
            exported_at=datetime(2026, 7, 31, tzinfo=timezone.utc),
        )
    engine.dispose()
    return payload


def test_restore_v5_to_new_database_preserves_all_data(tmp_path: Path):
    payload = make_v5_payload()
    backup = write_payload(tmp_path / "backup.json", payload)
    database = tmp_path / "restored.db"

    result = restore_backup_file(backup, database)

    assert result.database_path == database.resolve()
    assert result.source_schema_version == 5
    assert result.record_counts == payload["record_counts"]
    assert result.safety_copy_path is None
    restored = export_database(database)
    assert restored["data"] == payload["data"]

    engine = create_engine(f"sqlite:///{database.as_posix()}")
    session_factory = sessionmaker(bind=engine)
    with session_factory() as db:
        assert db.scalar(select(AppSetting)) is None
    engine.dispose()


def test_restore_v1_keeps_habit_tables_empty(tmp_path: Path):
    backup = write_payload(tmp_path / "v1.json", make_v1_payload())
    database = tmp_path / "v1.db"

    result = restore_backup_file(backup, database)

    assert result.source_schema_version == 1
    restored = export_database(database)
    assert restored["record_counts"]["tasks"] == 1
    assert restored["record_counts"]["habits"] == 0
    assert restored["record_counts"]["habit_active_periods"] == 0
    assert restored["record_counts"]["habit_schedule_periods"] == 0
    assert restored["record_counts"]["habit_completions"] == 0


def test_normalize_v2_adds_archive_and_periods():
    normalized = normalize_backup_payload(make_v2_payload())

    habit = normalized["data"]["habits"][0]
    assert habit["archived_at"] == "2026-07-10T00:00:00Z"
    assert normalized["data"]["habit_active_periods"] == [
        {
            "id": 1,
            "habit_id": 8,
            "started_on": "2026-07-01",
            "ended_on": "2026-07-10",
            "created_at": STAMP,
        }
    ]
    assert (
        normalized["data"]["habit_schedule_periods"][0]["weekdays"]
        == list(range(7))
    )
    assert normalized["data"]["habit_schedule_periods"][0]["ended_on"] is None


def test_prepare_rejects_legacy_backup_that_cannot_be_upgraded(tmp_path: Path):
    backup = write_payload(
        tmp_path / "invalid-legacy.json",
        make_v2_payload(invalid_completion=True),
    )

    with pytest.raises(
        BackupRestoreInputError,
        match="現在形式へ安全に変換",
    ):
        prepare_backup_for_restore(backup)


def test_existing_empty_database_is_copied_before_replace(tmp_path: Path):
    backup = write_payload(tmp_path / "backup.json", make_v5_payload())
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

    assert (
        result.safety_copy_path
        == tmp_path / "home_panel.pre-restore-20260804T000000Z.db"
    )
    assert result.safety_copy_path.read_bytes() == previous_bytes
    assert export_database(database)["data"] == make_v5_payload()["data"]


def test_non_empty_database_is_rejected_without_changes(tmp_path: Path):
    backup = write_payload(tmp_path / "backup.json", make_v5_payload())
    database = tmp_path / "existing.db"
    engine = create_engine(f"sqlite:///{database.as_posix()}")
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine)
    with session_factory() as db:
        db.add(Task(title="既存タスク"))
        db.commit()
    engine.dispose()
    previous_bytes = database.read_bytes()

    with pytest.raises(DestinationNotEmptyError, match="tasks=1"):
        restore_backup_file(backup, database)

    assert database.read_bytes() == previous_bytes
    assert not list(tmp_path.glob("*.pre-restore-*.db"))


def test_database_with_unknown_table_is_rejected(tmp_path: Path):
    backup = write_payload(tmp_path / "backup.json", make_v5_payload())
    database = tmp_path / "unknown.db"
    engine = create_engine(f"sqlite:///{database.as_posix()}")
    with engine.begin() as connection:
        connection.execute(
            text("CREATE TABLE private_data (id INTEGER PRIMARY KEY)")
        )
    engine.dispose()

    with pytest.raises(BackupRestoreInputError, match="private_data"):
        restore_backup_file(backup, database)


def test_corrupted_destination_is_rejected(tmp_path: Path):
    backup = write_payload(tmp_path / "backup.json", make_v5_payload())
    database = tmp_path / "corrupted.db"
    database.write_text("not sqlite", encoding="utf-8")

    with pytest.raises(BackupRestoreInputError, match="安全に確認"):
        restore_backup_file(backup, database)


def test_invalid_backup_does_not_create_destination(tmp_path: Path):
    payload = make_v5_payload()
    payload["record_counts"]["tasks"] = 99
    backup = write_payload(tmp_path / "invalid.json", payload)
    database = tmp_path / "should-not-exist.db"

    with pytest.raises(BackupRestoreInputError, match="検証に失敗"):
        restore_backup_file(backup, database)

    assert not database.exists()


def test_expected_sha256_mismatch_does_not_create_destination(tmp_path: Path):
    backup = write_payload(tmp_path / "backup.json", make_v5_payload())
    database = tmp_path / "should-not-exist.db"

    with pytest.raises(BackupRestoreInputError, match="SHA-256が一致"):
        restore_backup_file(
            backup,
            database,
            expected_sha256="0" * 64,
        )

    assert not database.exists()


def test_backup_file_cannot_be_destination(tmp_path: Path):
    backup = write_payload(tmp_path / "backup.json", make_v5_payload())

    with pytest.raises(BackupRestoreInputError, match="バックアップファイル自身"):
        restore_backup_file(backup, backup)


def test_temporary_failure_keeps_existing_file_and_cleans_temp(
    tmp_path: Path,
    monkeypatch,
):
    backup = write_payload(tmp_path / "backup.json", make_v5_payload())
    database = tmp_path / "empty.db"
    database.write_bytes(b"")

    def fail_build(_temporary_path: Path, _payload: dict) -> None:
        raise RuntimeError("テスト用失敗")

    monkeypatch.setattr(
        backup_restore,
        "build_temporary_database",
        fail_build,
    )

    with pytest.raises(RuntimeError, match="テスト用失敗"):
        restore_backup_file(backup, database)

    assert database.read_bytes() == b""
    assert not list(tmp_path.glob(".empty.db.restore-*.tmp"))
    assert not list(tmp_path.glob("*.pre-restore-*.db"))


def test_run_cli_restores_and_prints_digest(tmp_path: Path, capsys):
    backup = write_payload(tmp_path / "backup.json", make_v5_payload())
    digest = hashlib.sha256(backup.read_bytes()).hexdigest()
    database = tmp_path / "cli.db"

    result = run_cli(
        [
            str(backup),
            "--database",
            str(database),
            "--expected-sha256",
            digest.upper(),
        ]
    )

    captured = capsys.readouterr()
    assert result == 0
    assert "バックアップを復元しました" in captured.out
    assert "入力スキーマ: v5" in captured.out
    assert f"SHA-256: {digest}" in captured.out
    assert database.exists()


def test_run_cli_rejects_non_empty_destination(tmp_path: Path, capsys):
    backup = write_payload(tmp_path / "backup.json", make_v5_payload())
    database = tmp_path / "existing.db"
    engine = create_engine(f"sqlite:///{database.as_posix()}")
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine)
    with session_factory() as db:
        db.add(Task(title="既存"))
        db.commit()
    engine.dispose()

    result = run_cli([str(backup), "--database", str(database)])

    assert result == 2
    assert "既存データ" in capsys.readouterr().err
