import copy
import hashlib
import json
from datetime import date, datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.backup_export import build_backup_payload
from app.backup_validate import (
    MAX_BACKUP_FILE_SIZE,
    load_backup_file,
    run_cli,
    validate_backup_payload,
)
from app.db import Base
from app.models.memo import DailyMemo
from app.models.task import Task
from app.models.time_entry import TimeEntry


def valid_payload() -> dict:
    return {
        "schema_version": 1,
        "application": "home-panel-py",
        "exported_at": "2026-07-24T12:34:56Z",
        "record_counts": {
            "tasks": 1,
            "daily_memos": 1,
            "time_entries": 1,
        },
        "data": {
            "tasks": [
                {
                    "id": 1,
                    "title": "バックアップ確認",
                    "is_done": False,
                    "created_at": "2026-07-24T10:00:00Z",
                    "updated_at": "2026-07-24T11:00:00Z",
                }
            ],
            "daily_memos": [
                {
                    "id": 1,
                    "memo_date": "2026-07-24",
                    "content": "メモ",
                    "updated_at": "2026-07-24T11:00:00Z",
                }
            ],
            "time_entries": [
                {
                    "id": 1,
                    "entry_date": "2026-07-24",
                    "category": "個人開発",
                    "minutes": 90,
                    "note": "検証CLI",
                    "created_at": "2026-07-24T11:00:00Z",
                }
            ],
        },
    }


def write_payload(path: Path, payload: dict) -> str:
    content = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    path.write_text(content, encoding="utf-8")
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def test_exporter_generated_payload_is_valid(tmp_path: Path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'source.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    stamp = datetime(2026, 7, 24, 1, 2, 3)
    with session_factory() as db:
        db.add(Task(title="タスク", created_at=stamp, updated_at=stamp))
        db.add(DailyMemo(memo_date=date(2026, 7, 24), content="メモ", updated_at=stamp))
        db.add(
            TimeEntry(
                entry_date=date(2026, 7, 24),
                category="作業",
                minutes=30,
                note="記録",
                created_at=stamp,
            )
        )
        db.commit()
        payload = build_backup_payload(db)
    engine.dispose()

    assert validate_backup_payload(payload) == []


def test_valid_payload_has_no_errors():
    assert validate_backup_payload(valid_payload()) == []


def test_cli_accepts_valid_backup_and_prints_counts_and_sha256(tmp_path: Path, capsys):
    backup = tmp_path / "backup.json"
    digest = write_payload(backup, valid_payload())

    result = run_cli([str(backup)])

    output = capsys.readouterr().out
    assert result == 0
    assert "バックアップは有効です" in output
    assert "ToDo=1、メモ=1、時間記録=1" in output
    assert digest in output


def test_cli_accepts_matching_expected_sha256(tmp_path: Path):
    backup = tmp_path / "backup.json"
    digest = write_payload(backup, valid_payload())

    assert run_cli([str(backup), "--expected-sha256", digest.upper()]) == 0


def test_cli_rejects_mismatched_expected_sha256(tmp_path: Path, capsys):
    backup = tmp_path / "backup.json"
    write_payload(backup, valid_payload())

    result = run_cli([str(backup), "--expected-sha256", "0" * 64])

    assert result == 2
    assert "SHA-256が一致しません" in capsys.readouterr().err


def test_cli_rejects_invalid_expected_sha256_format(tmp_path: Path, capsys):
    backup = tmp_path / "backup.json"
    write_payload(backup, valid_payload())

    result = run_cli([str(backup), "--expected-sha256", "not-a-hash"])

    assert result == 2
    assert "64桁の16進数" in capsys.readouterr().err


def test_cli_rejects_missing_file(tmp_path: Path, capsys):
    result = run_cli([str(tmp_path / "missing.json")])

    assert result == 2
    assert "ファイルが見つかりません" in capsys.readouterr().err


def test_cli_rejects_oversized_file(tmp_path: Path, capsys):
    backup = tmp_path / "large.json"
    with backup.open("wb") as file:
        file.truncate(MAX_BACKUP_FILE_SIZE + 1)

    result = run_cli([str(backup)])

    assert result == 2
    assert "大きすぎます" in capsys.readouterr().err


def test_cli_rejects_non_utf8_file(tmp_path: Path, capsys):
    backup = tmp_path / "invalid-utf8.json"
    backup.write_bytes(b"\xff\xfe")

    result = run_cli([str(backup)])

    assert result == 2
    assert "UTF-8" in capsys.readouterr().err


def test_cli_rejects_invalid_json(tmp_path: Path, capsys):
    backup = tmp_path / "invalid.json"
    backup.write_text('{"schema_version":', encoding="utf-8")

    result = run_cli([str(backup)])

    assert result == 2
    assert "JSONとして読み取れません" in capsys.readouterr().err


def test_cli_rejects_duplicate_json_keys(tmp_path: Path, capsys):
    backup = tmp_path / "duplicate.json"
    backup.write_text('{"schema_version":1,"schema_version":1}', encoding="utf-8")

    result = run_cli([str(backup)])

    assert result == 2
    assert "キーが重複" in capsys.readouterr().err


def test_load_backup_file_returns_digest(tmp_path: Path):
    backup = tmp_path / "backup.json"
    digest = write_payload(backup, valid_payload())

    payload, actual_digest = load_backup_file(backup)

    assert payload["application"] == "home-panel-py"
    assert actual_digest == digest


def test_validator_rejects_unsupported_schema_version():
    payload = valid_payload()
    payload["schema_version"] = 2

    errors = validate_backup_payload(payload)

    assert any("未対応のバージョン" in error for error in errors)


def test_validator_rejects_wrong_application_and_unknown_key():
    payload = valid_payload()
    payload["application"] = "other-app"
    payload["unexpected"] = True

    errors = validate_backup_payload(payload)

    assert any("$.application" in error for error in errors)
    assert any("$.unexpected" in error for error in errors)


def test_validator_rejects_record_count_mismatch():
    payload = valid_payload()
    payload["record_counts"]["tasks"] = 2

    errors = validate_backup_payload(payload)

    assert any("配列件数と一致しません" in error for error in errors)


def test_validator_rejects_duplicate_ids():
    payload = valid_payload()
    duplicated = copy.deepcopy(payload["data"]["tasks"][0])
    payload["data"]["tasks"].append(duplicated)
    payload["record_counts"]["tasks"] = 2

    errors = validate_backup_payload(payload)

    assert any("ID 1 が重複" in error for error in errors)


@pytest.mark.parametrize(
    ("field", "value", "expected"),
    [
        ("id", True, "1以上の整数"),
        ("title", "   ", "空白だけ"),
        ("is_done", 1, "真偽値"),
        ("created_at", "2026-07-24T10:00:00+09:00", "末尾Z"),
        ("updated_at", "2026-07-24T09:00:00Z", "created_at以降"),
    ],
)
def test_validator_rejects_invalid_task_fields(field: str, value, expected: str):
    payload = valid_payload()
    payload["data"]["tasks"][0][field] = value

    errors = validate_backup_payload(payload)

    assert any(expected in error for error in errors)


@pytest.mark.parametrize(
    ("field", "value", "expected"),
    [
        ("memo_date", "2026-02-30", "実在する日付"),
        ("content", "x" * 5001, "0〜5000文字"),
        ("updated_at", "invalid", "末尾Z"),
    ],
)
def test_validator_rejects_invalid_memo_fields(field: str, value, expected: str):
    payload = valid_payload()
    payload["data"]["daily_memos"][0][field] = value

    errors = validate_backup_payload(payload)

    assert any(expected in error for error in errors)


@pytest.mark.parametrize(
    ("field", "value", "expected"),
    [
        ("entry_date", "2026-13-01", "実在する日付"),
        ("category", "未定義", "学習・作業・個人開発・その他"),
        ("minutes", 0, "1〜1440"),
        ("minutes", True, "1〜1440"),
        ("note", "x" * 256, "0〜255文字"),
        ("created_at", "2026-07-24 10:00:00", "末尾Z"),
    ],
)
def test_validator_rejects_invalid_time_entry_fields(field: str, value, expected: str):
    payload = valid_payload()
    payload["data"]["time_entries"][0][field] = value

    errors = validate_backup_payload(payload)

    assert any(expected in error for error in errors)


def test_validator_reports_missing_data_array_without_crashing():
    payload = valid_payload()
    del payload["data"]["daily_memos"]

    errors = validate_backup_payload(payload)

    assert any("data.daily_memos" in error for error in errors)
