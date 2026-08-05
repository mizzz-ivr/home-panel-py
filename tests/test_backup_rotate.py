from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.engine import URL
from sqlalchemy.orm import sessionmaker

from app import backup_rotate
from app.backup_rotate import (
    LOCK_FILE_NAME,
    BackupRotationInputError,
    create_verified_backup,
    run_backup_rotation,
    run_cli,
)
from app.backup_validate import load_backup_file, validate_backup_payload
from app.db import Base
from app.models.task import Task


def utc_datetime(day: int, second: int = 0) -> datetime:
    return datetime(2026, 8, day, 3, 0, second, tzinfo=timezone.utc)


def create_database(path: Path, *, title: str = "バックアップ対象") -> None:
    engine = create_engine(
        URL.create("sqlite", database=str(path)),
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    with session_factory() as db:
        db.add(Task(title=title))
        db.commit()
    engine.dispose()


def test_rotation_creates_verified_backup_and_removes_lock(tmp_path: Path):
    database = tmp_path / "home_panel.db"
    backup_directory = tmp_path / "backups"
    create_database(database)

    result = run_backup_rotation(
        database,
        backup_directory,
        keep_count=30,
        exported_at=utc_datetime(1),
    )

    assert result.created.path.name == "home-panel-backup-20260801T030000Z.json"
    assert len(result.created.sha256) == 64
    assert result.retention.deleted == ()
    assert result.retention.failed == ()
    assert not (backup_directory / LOCK_FILE_NAME).exists()

    payload, digest = load_backup_file(result.created.path)
    assert digest == result.created.sha256
    assert validate_backup_payload(payload) == []
    assert payload["data"]["tasks"][0]["title"] == "バックアップ対象"


def test_rotation_uses_numbered_name_for_same_second(tmp_path: Path):
    database = tmp_path / "home_panel.db"
    backup_directory = tmp_path / "backups"
    create_database(database)
    exported_at = utc_datetime(1)

    first = run_backup_rotation(
        database,
        backup_directory,
        exported_at=exported_at,
    )
    second = run_backup_rotation(
        database,
        backup_directory,
        exported_at=exported_at,
    )

    assert first.created.path.name == "home-panel-backup-20260801T030000Z.json"
    assert second.created.path.name == "home-panel-backup-20260801T030000Z-2.json"
    assert first.created.path.exists()
    assert second.created.path.exists()


def test_rotation_prunes_oldest_verified_backups(tmp_path: Path):
    database = tmp_path / "home_panel.db"
    backup_directory = tmp_path / "backups"
    create_database(database)

    first = run_backup_rotation(
        database,
        backup_directory,
        keep_count=2,
        exported_at=utc_datetime(1),
    )
    second = run_backup_rotation(
        database,
        backup_directory,
        keep_count=2,
        exported_at=utc_datetime(2),
    )
    third = run_backup_rotation(
        database,
        backup_directory,
        keep_count=2,
        exported_at=utc_datetime(3),
    )

    assert not first.created.path.exists()
    assert second.created.path.exists()
    assert third.created.path.exists()
    assert third.retention.deleted == (first.created.path,)


def test_invalid_matching_file_is_preserved_and_not_counted(tmp_path: Path):
    database = tmp_path / "home_panel.db"
    backup_directory = tmp_path / "backups"
    create_database(database)
    old = run_backup_rotation(
        database,
        backup_directory,
        keep_count=30,
        exported_at=utc_datetime(1),
    )
    invalid = backup_directory / "home-panel-backup-20260802T030000Z.json"
    invalid.write_text("not json", encoding="utf-8")

    latest = run_backup_rotation(
        database,
        backup_directory,
        keep_count=1,
        exported_at=utc_datetime(3),
    )

    assert not old.created.path.exists()
    assert invalid.exists()
    assert latest.created.path.exists()
    assert any(item.path == invalid for item in latest.retention.skipped)


def test_filename_timestamp_mismatch_is_preserved(tmp_path: Path):
    database = tmp_path / "home_panel.db"
    backup_directory = tmp_path / "backups"
    create_database(database)
    backup_directory.mkdir()
    original = create_verified_backup(
        database,
        backup_directory,
        exported_at=utc_datetime(2),
    )
    mismatched = backup_directory / "home-panel-backup-20260801T030000Z.json"
    original.path.rename(mismatched)

    result = run_backup_rotation(
        database,
        backup_directory,
        keep_count=1,
        exported_at=utc_datetime(3),
    )

    assert mismatched.exists()
    assert result.created.path.exists()
    warning = next(item for item in result.retention.skipped if item.path == mismatched)
    assert "exported_at" in warning.reason


def test_existing_lock_rejects_concurrent_execution(tmp_path: Path):
    database = tmp_path / "home_panel.db"
    backup_directory = tmp_path / "backups"
    create_database(database)
    backup_directory.mkdir()
    lock = backup_directory / LOCK_FILE_NAME
    lock.write_text("pid=123\n", encoding="utf-8")

    with pytest.raises(BackupRotationInputError, match="別のバックアップ処理"):
        run_backup_rotation(database, backup_directory, exported_at=utc_datetime(1))

    assert lock.exists()
    assert not list(backup_directory.glob("home-panel-backup-*.json"))


def test_lock_is_removed_when_backup_creation_fails(tmp_path: Path):
    backup_directory = tmp_path / "backups"

    with pytest.raises(BackupRotationInputError, match="DBが見つかりません"):
        run_backup_rotation(
            tmp_path / "missing.db",
            backup_directory,
            exported_at=utc_datetime(1),
        )

    assert not (backup_directory / LOCK_FILE_NAME).exists()


def test_created_file_is_removed_when_post_write_validation_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    database = tmp_path / "home_panel.db"
    backup_directory = tmp_path / "backups"
    create_database(database)
    monkeypatch.setattr(
        backup_rotate,
        "validate_backup_payload",
        lambda _payload: ["forced validation failure"],
    )

    with pytest.raises(backup_rotate.BackupRotationRuntimeError):
        run_backup_rotation(
            database,
            backup_directory,
            exported_at=utc_datetime(1),
        )

    assert not list(backup_directory.glob("home-panel-backup-*.json"))
    assert not (backup_directory / LOCK_FILE_NAME).exists()


def test_nonmatching_file_is_untouched(tmp_path: Path):
    database = tmp_path / "home_panel.db"
    backup_directory = tmp_path / "backups"
    create_database(database)
    backup_directory.mkdir()
    note = backup_directory / "README.txt"
    note.write_text("keep me", encoding="utf-8")

    run_backup_rotation(
        database,
        backup_directory,
        keep_count=1,
        exported_at=utc_datetime(1),
    )

    assert note.read_text(encoding="utf-8") == "keep me"


@pytest.mark.parametrize("keep_count", [0, -1, 3651])
def test_keep_count_out_of_range_is_rejected(
    tmp_path: Path,
    keep_count: int,
):
    with pytest.raises(BackupRotationInputError, match="--keep"):
        run_backup_rotation(
            tmp_path / "missing.db",
            tmp_path / "backups",
            keep_count=keep_count,
        )


def test_cli_creates_backup_and_prints_digest(tmp_path: Path, capsys):
    database = tmp_path / "home_panel.db"
    backup_directory = tmp_path / "backups"
    create_database(database, title="CLI対象")

    result = run_cli(
        [
            "--database",
            str(database),
            "--backup-dir",
            str(backup_directory),
            "--keep",
            "2",
        ]
    )

    captured = capsys.readouterr()
    assert result == 0
    assert "バックアップを作成しました" in captured.out
    assert "SHA-256:" in captured.out
    assert len(list(backup_directory.glob("home-panel-backup-*.json"))) == 1


def test_cli_returns_2_when_lock_exists(tmp_path: Path, capsys):
    database = tmp_path / "home_panel.db"
    backup_directory = tmp_path / "backups"
    create_database(database)
    backup_directory.mkdir()
    (backup_directory / LOCK_FILE_NAME).write_text("locked", encoding="utf-8")

    result = run_cli(
        [
            "--database",
            str(database),
            "--backup-dir",
            str(backup_directory),
        ]
    )

    assert result == 2
    assert "ロック" in capsys.readouterr().err


@pytest.mark.skipif(os.name == "nt", reason="Windowsでは?をファイル名に使用できない")
def test_question_mark_in_database_path_is_supported(tmp_path: Path):
    database = tmp_path / "home?panel.db"
    backup_directory = tmp_path / "backups"
    create_database(database, title="特殊パス")

    result = run_backup_rotation(
        database,
        backup_directory,
        exported_at=utc_datetime(1),
    )

    payload, _digest = load_backup_file(result.created.path)
    assert payload["data"]["tasks"][0]["title"] == "特殊パス"
    assert not (tmp_path / "home").exists()


@pytest.mark.skipif(os.name == "nt", reason="Windowsのシンボリックリンク権限差を除外")
def test_symlink_backup_directory_is_rejected(tmp_path: Path):
    database = tmp_path / "home_panel.db"
    real_directory = tmp_path / "real-backups"
    linked_directory = tmp_path / "linked-backups"
    create_database(database)
    real_directory.mkdir()
    linked_directory.symlink_to(real_directory, target_is_directory=True)

    with pytest.raises(BackupRotationInputError, match="シンボリックリンク"):
        run_backup_rotation(database, linked_directory, exported_at=utc_datetime(1))

    assert not list(real_directory.iterdir())
