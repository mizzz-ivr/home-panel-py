from __future__ import annotations

from .backup_restore_legacy_tests import *  # noqa: F401,F403


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
    assert restored["data"] == normalize_backup_payload(payload)["data"]

    engine = create_engine(f"sqlite:///{database.as_posix()}")
    session_factory = sessionmaker(bind=engine)
    with session_factory() as db:
        assert db.scalar(select(AppSetting)) is None
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
