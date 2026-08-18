import copy

from app.backup_validate import validate_backup_payload


def valid_v7_payload() -> dict:
    return {
        "schema_version": 7,
        "application": "home-panel-py",
        "exported_at": "2026-08-18T00:00:00Z",
        "record_counts": {
            "tasks": 1,
            "daily_memos": 0,
            "time_entries": 0,
            "habits": 0,
            "habit_active_periods": 0,
            "habit_schedule_periods": 0,
            "habit_completions": 0,
            "daily_time_goal_periods": 2,
        },
        "data": {
            "tasks": [
                {
                    "id": 1,
                    "title": "v7確認",
                    "is_done": False,
                    "due_date": None,
                    "priority": "medium",
                    "created_at": "2026-08-01T00:00:00Z",
                    "updated_at": "2026-08-01T00:00:00Z",
                }
            ],
            "daily_memos": [],
            "time_entries": [],
            "habits": [],
            "habit_active_periods": [],
            "habit_schedule_periods": [],
            "habit_completions": [],
            "daily_time_goal_periods": [
                {
                    "id": 1,
                    "goal_minutes": 60,
                    "started_on": "2026-08-01",
                    "ended_on": "2026-08-09",
                    "created_at": "2026-08-01T00:00:00Z",
                },
                {
                    "id": 2,
                    "goal_minutes": 120,
                    "started_on": "2026-08-10",
                    "ended_on": None,
                    "created_at": "2026-08-10T00:00:00Z",
                },
            ],
        },
    }


def test_v7_goal_history_is_valid():
    assert validate_backup_payload(valid_v7_payload()) == []


def test_v7_goal_history_allows_unconfigured_gaps():
    payload = valid_v7_payload()
    payload["data"]["daily_time_goal_periods"][0]["ended_on"] = "2026-08-05"

    assert validate_backup_payload(payload) == []


def test_v7_goal_history_rejects_invalid_minutes_and_bool():
    for invalid in (0, 1441, True):
        payload = valid_v7_payload()
        payload["data"]["daily_time_goal_periods"][0]["goal_minutes"] = invalid

        errors = validate_backup_payload(payload)

        assert any("goal_minutes" in error and "1〜1440" in error for error in errors)


def test_v7_goal_history_rejects_duplicate_start_date():
    payload = valid_v7_payload()
    payload["data"]["daily_time_goal_periods"][1]["started_on"] = "2026-08-01"

    errors = validate_backup_payload(payload)

    assert any("開始日が重複" in error for error in errors)


def test_v7_goal_history_rejects_overlapping_periods():
    payload = valid_v7_payload()
    payload["data"]["daily_time_goal_periods"][0]["ended_on"] = "2026-08-12"

    errors = validate_backup_payload(payload)

    assert any("適用期間が重複" in error for error in errors)


def test_v7_goal_history_rejects_period_after_open_period():
    payload = valid_v7_payload()
    first = payload["data"]["daily_time_goal_periods"][0]
    second = payload["data"]["daily_time_goal_periods"][1]
    first["ended_on"] = None
    second["started_on"] = "2026-08-15"

    errors = validate_backup_payload(payload)

    assert any("適用期間が重複" in error for error in errors)


def test_v7_goal_history_rejects_record_count_mismatch():
    payload = valid_v7_payload()
    payload["record_counts"]["daily_time_goal_periods"] = 1

    errors = validate_backup_payload(payload)

    assert any(
        "record_counts.daily_time_goal_periods" in error
        and "配列件数と一致" in error
        for error in errors
    )


def test_v7_goal_history_rejects_unknown_fields():
    payload = valid_v7_payload()
    payload["data"]["daily_time_goal_periods"][0]["unexpected"] = "x"

    errors = validate_backup_payload(payload)

    assert any("unexpected" in error and "未知の項目" in error for error in errors)


def test_v6_payload_remains_supported_without_goal_history():
    payload = valid_v7_payload()
    payload["schema_version"] = 6
    payload["data"].pop("daily_time_goal_periods")
    payload["record_counts"].pop("daily_time_goal_periods")

    assert validate_backup_payload(payload) == []


def test_validation_does_not_mutate_v7_payload():
    payload = valid_v7_payload()
    before = copy.deepcopy(payload)

    validate_backup_payload(payload)

    assert payload == before
