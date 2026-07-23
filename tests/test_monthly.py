from datetime import date, timedelta
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


def next_month_start(month_start: date) -> date:
    if month_start.month == 12:
        return date(month_start.year + 1, 1, 1)
    return date(month_start.year, month_start.month + 1, 1)


def previous_month_start(month_start: date) -> date:
    return (month_start - timedelta(days=1)).replace(day=1)


def test_monthly_defaults_to_current_month(client: TestClient):
    today = date.today()
    current_month = today.replace(day=1)

    response = client.get("/monthly")

    assert response.status_code == 200
    assert "学習・作業時間の月次集計" in response.text
    assert current_month.strftime("%Y年%m月") in response.text
    assert 'name="target_month"' in response.text
    assert "次の月" in response.text
    assert 'aria-disabled="true"' in response.text


def test_monthly_aggregates_entries_and_links_to_history(client: TestClient):
    target_month = previous_month_start(date.today().replace(day=1))
    first_day = target_month
    second_day = target_month + timedelta(days=1)
    session_factory = client.app.state.testing_session_factory

    with session_factory() as db:
        time_entry_crud.add_time_entry(db, first_day, 30, "月初の学習", category="学習")
        time_entry_crud.add_time_entry(db, second_day, 45, "開発作業", category="個人開発")
        time_entry_crud.add_time_entry(db, second_day, 15, "復習", category="学習")

    response = client.get("/monthly", params={"target_month": target_month.strftime("%Y-%m")})

    assert response.status_code == 200
    assert target_month.strftime("%Y年%m月") in response.text
    assert "90分" in response.text
    assert "3件" in response.text
    assert "45分" in response.text
    assert "2日間の平均" in response.text
    assert f'href="/history?target_date={first_day.isoformat()}"' in response.text
    assert f'href="/history?target_date={second_day.isoformat()}"' in response.text

    with session_factory() as db:
        total_minutes, entry_count = time_entry_crud.get_range_summary(
            db,
            target_month,
            next_month_start(target_month) - timedelta(days=1),
        )
        category_totals = dict(
            time_entry_crud.get_category_totals_between(
                db,
                target_month,
                next_month_start(target_month) - timedelta(days=1),
            )
        )
        daily_totals = dict(
            time_entry_crud.get_daily_totals_between(
                db,
                target_month,
                next_month_start(target_month) - timedelta(days=1),
            )
        )

    assert total_minutes == 90
    assert entry_count == 3
    assert category_totals == {"学習": 45, "個人開発": 45}
    assert daily_totals == {first_day: 30, second_day: 60}


@pytest.mark.parametrize(
    "target_month",
    ["", "not-a-month", "202607", "2026-7", "2026-00", "2026-13", "2026-07-01"],
)
def test_monthly_rejects_invalid_month(client: TestClient, target_month: str):
    response = client.get("/monthly", params={"target_month": target_month})

    assert response.status_code == 400
    assert "月はYYYY-MM形式で指定してください。" in response.text


def test_monthly_rejects_future_month(client: TestClient):
    future_month = next_month_start(date.today().replace(day=1))

    response = client.get("/monthly", params={"target_month": future_month.strftime("%Y-%m")})

    assert response.status_code == 400
    assert "未来の月は月次集計に指定できません。" in response.text


def test_monthly_handles_minimum_month(client: TestClient):
    response = client.get("/monthly", params={"target_month": "0001-01"})

    assert response.status_code == 200
    assert "前の月" in response.text
    assert 'aria-disabled="true"' in response.text


def test_monthly_empty_state(client: TestClient):
    current_month = date.today().replace(day=1)
    target_month = previous_month_start(previous_month_start(current_month))

    response = client.get("/monthly", params={"target_month": target_month.strftime("%Y-%m")})

    assert response.status_code == 200
    assert "この月のカテゴリ別集計はありません。" in response.text
    assert "0件" in response.text
    assert "0日間の平均" in response.text
    assert "記録なし" in response.text


def test_monthly_excludes_future_entries(client: TestClient):
    future_date = date.today() + timedelta(days=1)
    session_factory = client.app.state.testing_session_factory

    with session_factory() as db:
        time_entry_crud.add_time_entry(db, future_date, 120, "未来の記録", category="作業")

    response = client.get("/monthly")

    assert response.status_code == 200
    assert "120分" not in response.text
    assert "0件" in response.text


def test_dashboard_links_to_monthly_and_monthly_links_back(client: TestClient):
    dashboard_response = client.get("/")
    monthly_response = client.get("/monthly")

    assert 'href="/monthly"' in dashboard_response.text
    assert 'href="/history"' in monthly_response.text
    assert 'href="/weekly"' in monthly_response.text


def test_monthly_stylesheet_is_served(client: TestClient):
    response = client.get("/static/monthly.css")

    assert response.status_code == 200
    assert ".monthly-calendar" in response.text
    assert 'input[type="month"]' in response.text
