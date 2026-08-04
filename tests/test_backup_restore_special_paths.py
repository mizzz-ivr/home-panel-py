import json
import os
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.engine import URL
from sqlalchemy.orm import sessionmaker

from app.backup_restore import restore_backup_file
from app.models.task import Task


@pytest.mark.skipif(os.name == "nt", reason="Windowsではファイル名に?を使用できない")
def test_restore_supports_question_mark_in_database_path(tmp_path: Path):
    payload = {
        "schema_version": 1,
        "application": "home-panel-py",
        "exported_at": "2026-08-04T00:00:00Z",
        "record_counts": {
            "tasks": 1,
            "daily_memos": 0,
            "time_entries": 0,
        },
        "data": {
            "tasks": [
                {
                    "id": 1,
                    "title": "特殊パス",
                    "is_done": False,
                    "created_at": "2026-08-04T00:00:00Z",
                    "updated_at": "2026-08-04T00:00:00Z",
                }
            ],
            "daily_memos": [],
            "time_entries": [],
        },
    }
    backup = tmp_path / "backup.json"
    backup.write_text(
        json.dumps(payload, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    destination = tmp_path / "restored?copy.db"

    result = restore_backup_file(backup, destination)

    assert result.database_path == destination.resolve()
    assert destination.is_file()
    assert destination.stat().st_size > 0
    assert not (tmp_path / "restored").exists()

    engine = create_engine(URL.create("sqlite", database=str(destination)))
    session_factory = sessionmaker(bind=engine)
    with session_factory() as db:
        task = db.scalar(select(Task))
        assert task is not None
        assert task.title == "特殊パス"
    engine.dispose()
