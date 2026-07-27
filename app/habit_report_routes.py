from __future__ import annotations

import re
from datetime import date, timedelta
from pathlib import Path

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.db import get_db
from app.habit_report import build_daily_report, build_period_report

BASE_DIR = Path(__file__).resolve().parent
DATE_PATTERN = re.compile(r"\d{4}-\d{2}-\d{2}\Z")
MONTH_PATTERN = re.compile(r"\d{4}-\d{2}\Z")
WEEKDAY_LABELS = ("月", "火", "水", "木", "金", "土", "日")

router = APIRouter(prefix="/habits", tags=["habit-reports"])
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


def parse_date(value: str) -> date | None:
    if not DATE_PATTERN.fullmatch(value):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def parse_month(value: str) -> date | None:
    if not MONTH_PATTERN.fullmatch(value):
        return None
    try:
        return date.fromisoformat(f"{value}-01")
    except ValueError:
        return None


def get_week_start(target_date: date) -> date:
    return target_date - timedelta(days=target_date.weekday())


def get_next_month_start(month_start: date) -> date:
    if month_start.month == 12:
        return date(month_start.year + 1, 1, 1)
    return date(month_start.year, month_start.month + 1, 1)


def get_previous_month_start(month_start: date) -> date | None:
    if month_start == date.min:
        return None
    if month_start.month == 1:
        return date(month_start.year - 1, 12, 1)
    return date(month_start.year, month_start.month - 1, 1)


def get_month_end(month_start: date) -> date:
    return get_next_month_start(month_start) - timedelta(days=1)


def render_daily_report(
    request: Request,
    db: Session,
    selected_date: date,
    error_message: str | None = None,
    status_code: int = status.HTTP_200_OK,
) -> HTMLResponse:
    today = date.today()
    report = build_daily_report(db, selected_date)
    return templates.TemplateResponse(
        "habit_history.html",
        {
            "request": request,
            "today": today,
            "selected_date": selected_date,
            "previous_date": selected_date - timedelta(days=1) if selected_date > date.min else None,
            "next_date": selected_date + timedelta(days=1) if selected_date < today else None,
            "error_message": error_message,
            **report,
        },
        status_code=status_code,
    )


def render_weekly_report(
    request: Request,
    db: Session,
    selected_date: date,
    error_message: str | None = None,
    status_code: int = status.HTTP_200_OK,
) -> HTMLResponse:
    today = date.today()
    week_start = get_week_start(selected_date)
    week_end = week_start + timedelta(days=6)
    current_week_start = get_week_start(today)
    report = build_period_report(db, week_start, week_end, today)
    daily_summaries = [
        {**summary, "weekday": WEEKDAY_LABELS[summary["date"].weekday()]}
        for summary in report["daily_summaries"]
    ]

    return templates.TemplateResponse(
        "habit_weekly.html",
        {
            "request": request,
            "today": today,
            "week_start": week_start,
            "week_end": week_end,
            "previous_week_start": week_start - timedelta(days=7)
            if week_start >= date.min + timedelta(days=7)
            else None,
            "next_week_start": week_start + timedelta(days=7)
            if week_start < current_week_start
            else None,
            "daily_summaries": daily_summaries,
            "error_message": error_message,
            **{key: value for key, value in report.items() if key != "daily_summaries"},
        },
        status_code=status_code,
    )


def render_monthly_report(
    request: Request,
    db: Session,
    selected_month: date,
    error_message: str | None = None,
    status_code: int = status.HTTP_200_OK,
) -> HTMLResponse:
    today = date.today()
    month_start = selected_month.replace(day=1)
    month_end = get_month_end(month_start)
    current_month_start = today.replace(day=1)
    report = build_period_report(db, month_start, month_end, today)

    return templates.TemplateResponse(
        "habit_monthly.html",
        {
            "request": request,
            "today": today,
            "month_start": month_start,
            "month_end": month_end,
            "previous_month_start": get_previous_month_start(month_start),
            "next_month_start": get_next_month_start(month_start)
            if month_start < current_month_start
            else None,
            "leading_blank_days": month_start.weekday(),
            "weekday_labels": WEEKDAY_LABELS,
            "error_message": error_message,
            **report,
        },
        status_code=status_code,
    )


@router.get("/history", response_class=HTMLResponse)
def habit_history(
    request: Request,
    target_date: str | None = None,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    today = date.today()
    selected_date = today
    if target_date is not None:
        parsed_date = parse_date(target_date)
        if parsed_date is None:
            return render_daily_report(
                request,
                db,
                today,
                "日付はYYYY-MM-DD形式で指定してください。",
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        if parsed_date > today:
            return render_daily_report(
                request,
                db,
                today,
                "未来の日付は習慣履歴に指定できません。",
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        selected_date = parsed_date
    return render_daily_report(request, db, selected_date)


@router.get("/weekly", response_class=HTMLResponse)
def habit_weekly(
    request: Request,
    target_date: str | None = None,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    today = date.today()
    selected_date = today
    if target_date is not None:
        parsed_date = parse_date(target_date)
        if parsed_date is None:
            return render_weekly_report(
                request,
                db,
                today,
                "日付はYYYY-MM-DD形式で指定してください。",
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        if parsed_date > today:
            return render_weekly_report(
                request,
                db,
                today,
                "未来の日付は習慣の週次集計に指定できません。",
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        selected_date = parsed_date
    return render_weekly_report(request, db, selected_date)


@router.get("/monthly", response_class=HTMLResponse)
def habit_monthly(
    request: Request,
    target_month: str | None = None,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    today = date.today()
    current_month_start = today.replace(day=1)
    selected_month = current_month_start
    if target_month is not None:
        parsed_month = parse_month(target_month)
        if parsed_month is None:
            return render_monthly_report(
                request,
                db,
                current_month_start,
                "月はYYYY-MM形式で指定してください。",
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        if parsed_month > current_month_start:
            return render_monthly_report(
                request,
                db,
                current_month_start,
                "未来の月は習慣の月次集計に指定できません。",
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        selected_month = parsed_month
    return render_monthly_report(request, db, selected_month)
