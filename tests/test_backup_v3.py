from copy import deepcopy

from app.backup_validate import validate_backup_payload


def valid_v3_payload() -> dict:
    return {
        "schema_version": 3,
        "application": "home-panel-py",
        "exported_at": "2026-07-27T00:00:00Z",
        "record_counts": {
            "tasks": 0,
            "daily_memos": 0,
            "time_entries": 0,
            "habits": 1,
            "habit_completions": 0,
        },
        "data": {
            "tasks": [],
            "daily_memos": [],
            "time_entries": [],
            "habits": [
                {
                    "id": 1,
                    "name": "読書",
                    "is_active": True,
                    "archived_at": None,
                    "created_at": "2026-07-01T00:00:00Z",
                    "updated_at": "2026-07-01T00:00:00Z",
                }
            ],
            "habit_completions": [],
        },
    }


def test_active_habit_with_null_archived_at_is_valid():
    assert validate_backup_payload(valid_v3_payload()) == []


def test_archived_habit_with_archived_at_is_valid():
    payload = valid_v3_payload()
    habit = payload["data"]["habits"][0]
    habit["is_active"] = False
    habit["archived_at"] = "2026-07-10T00:00:00Z"
    habit["updated_at"] = "2026-07-20T00:00:00Z"

    assert validate_backup_payload(payload) == []


def test_archived_habit_requires_archived_at():
    payload = valid_v3_payload()
    payload["data"]["habits"][0]["is_active"] = False

    errors = validate_backup_payload(payload)

    assert any("archived_at" in error and "必須" in error for error in errors)


def test_active_habit_rejects_archived_at():
    payload = valid_v3_payload()
    payload["data"]["habits"][0]["archived_at"] = "2026-07-10T00:00:00Z"

    errors = validate_backup_payload(payload)

    assert any("アクティブな習慣ではnull" in error for error in errors)


def test_archived_at_must_be_after_creation_and_before_last_update():
    payload = valid_v3_payload()
    habit = payload["data"]["habits"][0]
    habit["is_active"] = False
    habit["archived_at"] = "2026-06-30T00:00:00Z"

    errors = validate_backup_payload(payload)
    assert any("archived_at: created_at以降" in error for error in errors)

    payload = deepcopy(valid_v3_payload())
    habit = payload["data"]["habits"][0]
    habit["is_active"] = False
    habit["archived_at"] = "2026-07-10T00:00:00Z"
    habit["updated_at"] = "2026-07-09T00:00:00Z"

    errors = validate_backup_payload(payload)
    assert any("updated_at: archived_at以降" in error for error in errors)
