import csv
from datetime import date
from io import StringIO
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from app import habit_report_routes
from app.crud import habit as habit_crud
from app.db import Base, get_db
from app.main import app
from app.models.habit import HabitCompletion

FIXED_TODAY = date(2026, 7, 26)


class FixedDate(date):
    @classmethod
    def today(cls):
        return cls(FIXED_TODAY.year, FIXED_TODAY.month, FIXED_TODAY.day)


@pytest.fixture()
def client(tmp_path: Path, monkeypatch):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'test.db'}",
        connect_args={"check_same_thread": False},
    )
    session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    def override_get_db():
        with session_factory() as db:
            yield db

    monkeypatch.setattr(habit_report_routes, "date", FixedDate)
    app.dependency_overrides[get_db] = override_get_db
    app.state.testing_session_factory = session_factory
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
    del app.state.testing_session_factory
    engine.dispose()


def parse_csv_response(response) -> list[list[str]]:
    assert response.content.startswith(b"\xef\xbb\xbf")
    assert b"\r\n" in response.content
    text = response.content.decode("utf-8-sig")
    return list(csv.reader(StringIO(text, newline="")))


def create_habit_with_completions(
    client: TestClient,
    name: str,
    weekdays: tuple[int, ...],
    completion_dates: tuple[date, ...],
):
    session_factory = client.app.state.testing_session_factory
    with session_factory() as db:
        habit = habit_crud.create_habit(
            db,
            name,
            started_on=date(2026, 7, 20),
            weekdays=weekdays,
        )
        db.add_all(
            HabitCompletion(habit_id=habit.id, completed_on=completed_on)
            for completed_on in completion_dates
        )
        db.commit()
        return habit.id


def test_weekly_csv_exports_summary_daily_and_habit_sections(client: TestClient):
    habit_id = create_habit_with_completions(
        client,
        "  =SUM(1,1)",
        (0, 2, 4),
        (date(2026, 7, 20), date(2026, 7, 24)),
    )

    response = client.get("/habits/weekly.csv?target_date=2026-07-23")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert response.headers["content-disposition"] == (
        'attachment; filename="home-panel-habit-weekly-2026-07-20.csv"'
    )
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"

    rows = parse_csv_response(response)
    assert ["レポート種別", "習慣週次レポート"] in rows
    assert ["対象期間", "2026-07-20", "2026-07-26"] in rows
    assert ["集計終了日", "2026-07-26"] in rows
    assert ["達成数", "2"] in rows
    assert ["対象件数", "3"] in rows
    assert ["達成率（%）", "67"] in rows
    assert ["全習慣達成日", "2"] in rows
    assert ["2026-07-21", "火", "集計済み", "0", "0", "0"] in rows
    assert ["2026-07-22", "水", "集計済み", "0", "1", "0"] in rows
    assert [
        "'  =SUM(1,1)",
        "月・水・金",
        "2",
        "3",
        "67",
        "1",
        "利用中",
        "1",
        "1",
    ] in rows

    session_factory = client.app.state.testing_session_factory
    with session_factory() as db:
        completion_count = db.scalar(
            select(func.count(HabitCompletion.id)).where(
                HabitCompletion.habit_id == habit_id
            )
        )
    assert completion_count == 2


def test_monthly_csv_marks_future_days_without_counting_them(client: TestClient):
    create_habit_with_completions(
        client,
        "日記",
        tuple(range(7)),
        (date(2026, 7, 25),),
    )

    response = client.get("/habits/monthly.csv?target_month=2026-07")

    assert response.status_code == 200
    assert response.headers["content-disposition"] == (
        'attachment; filename="home-panel-habit-monthly-2026-07.csv"'
    )
    rows = parse_csv_response(response)
    assert ["レポート種別", "習慣月次レポート"] in rows
    assert ["対象期間", "2026-07-01", "2026-07-31"] in rows
    assert ["集計終了日", "2026-07-26"] in rows
    assert ["達成数", "1"] in rows
    assert ["対象件数", "7"] in rows
    assert ["達成率（%）", "14"] in rows
    assert ["2026-07-27", "月", "未到来", "", "", ""] in rows
    assert ["2026-07-31", "金", "未到来", "", "", ""] in rows


def test_empty_habit_csv_keeps_all_section_headers(client: TestClient):
    response = client.get("/habits/weekly.csv?target_date=2026-07-23")

    assert response.status_code == 200
    rows = parse_csv_response(response)
    assert ["達成数", "0"] in rows
    assert ["対象件数", "0"] in rows
    assert ["日別集計"] in rows
    assert ["習慣別集計"] in rows
    assert [
        "習慣名",
        "対象曜日",
        "達成日数",
        "対象日数",
        "達成率（%）",
        "最長連続回数",
        "現在状態",
        "有効期間数",
        "曜日設定期間数",
    ] in rows


@pytest.mark.parametrize(
    ("url", "message"),
    [
        ("/habits/weekly.csv?target_date=20260723", "YYYY-MM-DD"),
        ("/habits/weekly.csv?target_date=2026-02-30", "YYYY-MM-DD"),
        ("/habits/weekly.csv?target_date=2026-07-27", "未来の日付"),
        ("/habits/monthly.csv?target_month=202607", "YYYY-MM"),
        ("/habits/monthly.csv?target_month=2026-13", "YYYY-MM"),
        ("/habits/monthly.csv?target_month=2026-08", "未来の月"),
    ],
)
def test_habit_csv_rejects_invalid_or_future_periods(
    client: TestClient,
    url: str,
    message: str,
):
    response = client.get(url)

    assert response.status_code == 400
    assert response.headers["content-type"].startswith("text/plain")
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert message in response.text


def test_habit_report_pages_link_to_selected_csv(client: TestClient):
    weekly = client.get("/habits/weekly?target_date=2026-07-23")
    monthly = client.get("/habits/monthly?target_month=2026-07")

    assert weekly.status_code == 200
    assert monthly.status_code == 200
    assert 'href="/habits/weekly.csv?target_date=2026-07-20"' in weekly.text
    assert 'href="/habits/monthly.csv?target_month=2026-07"' in monthly.text
    assert "この週をCSV出力" in weekly.text
    assert "この月をCSV出力" in monthly.text
