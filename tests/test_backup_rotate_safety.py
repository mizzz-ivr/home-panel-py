from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.engine import URL
from sqlalchemy.orm import sessionmaker

from app.backup_rotate import (
    LOCK_FILE_NAME,
    backup_directory_lock,
    create_verified_backup,
    prune_managed_backups,
    run_backup_rotation,
)
from app.db import Base
from app.models.task import Task


def create_database(path: Path) -> None:
    engine = create_engine(
        URL.create("sqlite", database=str(path)),
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    with session_factory() as db:
        db.add(Task(title="安全性テスト"))
        db.commit()
    engine.dispose()


def utc_datetime(day: int) -> datetime:
    return datetime(2026, 8, day, 3, 0, 0, tzinfo=timezone.utc)


@pytest.mark.skipif(os.name == "nt", reason="Windowsのシンボリックリンク権限差を除外")
def test_broken_symlink_name_is_not_overwritten(tmp_path: Path):
    database = tmp_path / "home_panel.db"
    backup_directory = tmp_path / "backups"
    create_database(database)
    backup_directory.mkdir()
    occupied = backup_directory / "home-panel-backup-20260801T030000Z.json"
    occupied.symlink_to(backup_directory / "missing-target.json")

    result = run_backup_rotation(
        database,
        backup_directory,
        exported_at=utc_datetime(1),
    )

    assert occupied.is_symlink()
    assert result.created.path.name == "home-panel-backup-20260801T030000Z-2.json"
    assert result.created.path.exists()


def test_invalid_datetime_filename_is_preserved_without_stopping_rotation(
    tmp_path: Path,
):
    database = tmp_path / "home_panel.db"
    backup_directory = tmp_path / "backups"
    create_database(database)
    backup_directory.mkdir()
    invalid_name = backup_directory / "home-panel-backup-20261340T256199Z.json"
    invalid_name.write_text("{}", encoding="utf-8")

    result = run_backup_rotation(
        database,
        backup_directory,
        keep_count=1,
        exported_at=utc_datetime(1),
    )

    assert invalid_name.exists()
    warning = next(item for item in result.retention.skipped if item.path == invalid_name)
    assert "実在しない" in warning.reason


def test_invalid_protected_backup_prevents_deleting_old_generations(tmp_path: Path):
    database = tmp_path / "home_panel.db"
    backup_directory = tmp_path / "backups"
    create_database(database)
    backup_directory.mkdir()
    old_backup = create_verified_backup(
        database,
        backup_directory,
        exported_at=utc_datetime(1),
    )
    new_backup = create_verified_backup(
        database,
        backup_directory,
        exported_at=utc_datetime(2),
    )
    new_backup.path.write_text("changed after validation", encoding="utf-8")

    result = prune_managed_backups(
        backup_directory,
        keep_count=1,
        protected_path=new_backup.path,
    )

    assert result.deleted == ()
    assert result.failed
    assert old_backup.path.exists()
    assert new_backup.path.exists()


@pytest.mark.skipif(os.name == "nt", reason="WindowsのファイルID差を除外")
def test_lock_cleanup_does_not_delete_replaced_lock(tmp_path: Path):
    backup_directory = tmp_path / "backups"
    backup_directory.mkdir()
    lock_path = backup_directory / LOCK_FILE_NAME

    with backup_directory_lock(backup_directory, acquired_at=utc_datetime(1)):
        lock_path.unlink()
        lock_path.write_text("replacement lock", encoding="utf-8")

    assert lock_path.read_text(encoding="utf-8") == "replacement lock"
