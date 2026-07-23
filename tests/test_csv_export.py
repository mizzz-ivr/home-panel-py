import csv
from datetime import date, timedelta
from io import StringIO
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.crud import time_entry as time_entry_crud
from app.db import Base, get_db
from app.main import app


@pytest.fixture()
def client(tmp_path: Path):
    db_path = tmp_path / "test.db"
    test_engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
    )
    testing_session_local = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)
    Base.metadata.create_all(bind=test_engine)

    def override_get_db():
        db = testing_session_local()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    app.state.testing_session_factory = testing_session_local

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()
    del app.state.testing_session_factory


def previous_month_start(month_start: date) -> date:
    return (month_start - timedelta(days=1)).replace(day=1)


def next_month_start(month_start: date) -> date:
    if month_start.month == 12:
        return date(month_start.year + 1, 1, 1)
    return date(month_start.year, month_start.month + 1, 1)


def read_csv_rows(response) -> list[list[str]]:
    text = response.content.decode("utf-8-sig")
    return list(csv.reader(StringIO(text)))


def test_csv_export_downloads_selected_month_with_excel_compatible_headers(client: TestClient):
    target_month = previous_month_start(date.today().replace(day=1))
    first_day = target_month
    second_day = target_month + timedelta(days=1)
    session_factory = client.app.state.testing_session_factory

    with session_factory() as db:
        time_entry_crud.add_time_entry(db, first_day, 30, "設計,テスト", category="学習")
        time_entry_crud.add_time_entry(db, second_day, 45, "複数行\nメモ", category="個人開発")
        time_entry_crud.add_time_entry(db, second_day, 15, '  =HYPERLINK("https://example.com")', category="作業")

    response = client.get(
        "/exports/time-entries.csv",
        params={"target_month": target_month.strftime("%Y-%m")},
    )

    assert response.status_code == 200
    assert response.content.startswith(b"\xef\xbb\xbf")
    assert response.headers["content-type"].startswith("text/csv")
    assert response.headers["content-disposition"] == (
        f'attachment; filename="home-panel-time-entries-{target_month.strftime("%Y-%m")}.csv"'
    )
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"

    rows = read_csv_rows(response)
    assert rows[0] == ["日付", "カテゴリ", "時間（分）", "メモ", "登録日時"]
    assert rows[1][0:4] == [first_day.isoformat(), "学習", "30", "設計,テスト"]
    assert rows[2][0:4] == [second_day.isoformat(), "個人開発", "45", "複数行\nメモ"]
    assert rows[3][0:3] == [second_day.isoformat(), "作業", "15"]
    assert rows[3][3].startswith("'  =HYPERLINK")


def test_csv_export_contains_only_selected_month(client: TestClient):
    target_month = previous_month_start(date.today().replace(day=1))
    outside_month = next_month_start(target_month)
    session_factory = client.app.state.testing_session_factory

    with session_factory() as db:
        time_entry_crud.add_time_entry(db, target_month, 20, "対象月", category="作業")
        time_entry_crud.add_time_entry(db, outside_month, 90, "対象外", category="作業")

    response = client.get(
        "/exports/time-entries.csv",
        params={"target_month": target_month.strftime("%Y-%m")},
    )
    rows = read_csv_rows(response)

    assert len(rows) == 2
    assert rows[1][3] == "対象月"


def test_csv_export_empty_month_returns_header_only(client: TestClient):
    target_month = previous_month_start(previous_month_start(date.today().replace(day=1)))

    response = client.get(
        "/exports/time-entries.csv",
        params={"target_month": target_month.strftime("%Y-%m")},
    )

    assert response.status_code == 200
    assert read_csv_rows(response) == [["日付", "カテゴリ", "時間（分）", "メモ", "登録日時"]]


@pytest.mark.parametrize(
    "target_month",
    ["", "not-a-month", "202607", "2026-7", "2026-00", "2026-13", "2026-07-01"],
)
def test_csv_export_rejects_invalid_month(client: TestClient, target_month: str):
    response = client.get(
        "/exports/time-entries.csv",
        params={"target_month": target_month},
    )

    assert response.status_code == 400
    assert response.text == "月はYYYY-MM形式で指定してください。"
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"


def test_csv_export_rejects_future_month(client: TestClient):
    future_month = next_month_start(date.today().replace(day=1))

    response = client.get(
        "/exports/time-entries.csv",
        params={"target_month": future_month.strftime("%Y-%m")},
    )

    assert response.status_code == 400
    assert response.text == "未来の月はCSV出力に指定できません。"


def test_csv_export_defaults_to_current_month(client: TestClient):
    session_factory = client.app.state.testing_session_factory
    with session_factory() as db:
        time_entry_crud.add_time_entry(db, date.today(), 25, "今日の記録", category="学習")

    response = client.get("/exports/time-entries.csv")
    rows = read_csv_rows(response)

    assert response.status_code == 200
    assert rows[1][0:4] == [date.today().isoformat(), "学習", "25", "今日の記録"]


def test_csv_export_excludes_future_entries_in_current_month(client: TestClient):
    tomorrow = date.today() + timedelta(days=1)
    if tomorrow.month != date.today().month:
        pytest.skip("当月内に未来日がないためスキップ")

    session_factory = client.app.state.testing_session_factory
    with session_factory() as db:
        time_entry_crud.add_time_entry(db, tomorrow, 120, "未来の記録", category="作業")

    response = client.get("/exports/time-entries.csv")

    assert read_csv_rows(response) == [["日付", "カテゴリ", "時間（分）", "メモ", "登録日時"]]


def test_monthly_page_links_to_selected_month_csv(client: TestClient):
    target_month = previous_month_start(date.today().replace(day=1))

    response = client.get("/monthly", params={"target_month": target_month.strftime("%Y-%m")})

    assert response.status_code == 200
    assert (
        f'href="/exports/time-entries.csv?target_month={target_month.strftime("%Y-%m")}"'
        in response.text
    )
    assert "この月をCSV出力" in response.text
