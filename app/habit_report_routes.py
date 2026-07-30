from __future__ import annotations

import re
from datetime import date, timedelta
from pathlib import Path

from fastapi import APIRouter, Depends, Form, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.crud import habit as habit_crud
from app.db import get_db
from app.habit_completion import (
    BulkCompletionUpdateStatus,
    CompletionUpdateResult,
    clear_all_completions_on,
    complete_all_expected_on,
    set_completion_on,
)
from app.habit_report import build_daily_report, build_period_report
from app.habit_report_csv import (
    build_csv_download_response,
    build_csv_error_response,
    build_habit_report_csv,
)
from app.habit_schedule import WEEKDAY_LABELS, format_schedule, mask_to_weekdays
from app.schemas.habit import HabitCreate

BASE_DIR = Path(__file__).resolve().parent
DATE_PATTERN = re.compile(r"\d{4}-\d{2}-\d{2}\Z")
MONTH_PATTERN = re.compile(r"\d{4}-\d{2}\Z")

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


def render_habit_management(
    request: Request,
    db: Session,
    error_message: str | None = None,
    status_code: int = status.HTTP_200_OK,
) -> HTMLResponse:
    active_habits = habit_crud.list_active_habits(db)
    archived_habits = habit_crud.list_archived_habits(db)
    schedule_masks = {
        habit.id: habit_crud.get_current_schedule_mask(db, habit.id)
        for habit in [*active_habits, *archived_habits]
    }
    return templates.TemplateResponse(
        "habit_manage.html",
        {
            "request": request,
            "active_habits": active_habits,
            "archived_habits": archived_habits,
            "active_count": habit_crud.count_active_habits(db),
            "max_active": habit_crud.MAX_ACTIVE_HABITS,
            "weekday_options": tuple(enumerate(WEEKDAY_LABELS)),
            "schedule_masks": schedule_masks,
            "schedule_weekdays": {
                habit_id: mask_to_weekdays(mask)
                for habit_id, mask in schedule_masks.items()
            },
            "schedule_labels": {
                habit_id: format_schedule(mask)
                for habit_id, mask in schedule_masks.items()
            },
            "error_message": error_message,
        },
        status_code=status_code,
    )


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
            "previous_date": selected_date - timedelta(days=1)
            if selected_date > date.min
            else None,
            "next_date": selected_date + timedelta(days=1)
            if selected_date < today
            else None,
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


@router.get("/manage", response_class=HTMLResponse)
def habit_management(
    request: Request,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    return render_habit_management(request, db)


@router.post("/{habit_id}/rename")
def rename_habit(
    request: Request,
    habit_id: int,
    name: str = Form(...),
    db: Session = Depends(get_db),
):
    habit = habit_crud.get_habit(db, habit_id)
    if habit is None:
        return render_habit_management(
            request,
            db,
            "指定された習慣が存在しません。",
            status_code=status.HTTP_404_NOT_FOUND,
        )

    try:
        payload = HabitCreate(name=name)
    except ValidationError:
        return render_habit_management(
            request,
            db,
            "習慣名は1〜100文字で入力してください。",
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    duplicate = habit_crud.find_active_habit_by_name(
        db,
        payload.name,
        exclude_habit_id=habit_id,
    )
    if duplicate is not None:
        return render_habit_management(
            request,
            db,
            "同じ名前のアクティブな習慣が既にあります。",
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    habit_crud.rename_habit(db, habit_id, payload.name)
    return RedirectResponse(url="/habits/manage", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/{habit_id}/schedule")
def update_habit_schedule(
    request: Request,
    habit_id: int,
    weekdays: list[int] | None = Form(None),
    db: Session = Depends(get_db),
):
    if habit_crud.get_habit(db, habit_id) is None:
        return render_habit_management(
            request,
            db,
            "指定された習慣が存在しません。",
            status_code=status.HTTP_404_NOT_FOUND,
        )

    try:
        habit_crud.update_habit_schedule(db, habit_id, weekdays or [])
    except habit_crud.HabitScheduleConflictError as exc:
        return render_habit_management(
            request,
            db,
            str(exc),
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    except ValueError:
        return render_habit_management(
            request,
            db,
            "対象曜日を月曜日〜日曜日から1つ以上選択してください。",
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    return RedirectResponse(url="/habits/manage", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/{habit_id}/restore")
def restore_habit(
    request: Request,
    habit_id: int,
    db: Session = Depends(get_db),
):
    habit = habit_crud.get_habit(db, habit_id)
    if habit is None or habit.is_active:
        return render_habit_management(
            request,
            db,
            "指定された習慣が存在しないか、既に再開されています。",
            status_code=status.HTTP_404_NOT_FOUND,
        )
    if habit_crud.count_active_habits(db) >= habit_crud.MAX_ACTIVE_HABITS:
        return render_habit_management(
            request,
            db,
            f"アクティブな習慣は最大{habit_crud.MAX_ACTIVE_HABITS}件です。",
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    if habit_crud.find_active_habit_by_name(db, habit.name) is not None:
        return render_habit_management(
            request,
            db,
            "同じ名前のアクティブな習慣があるため再開できません。",
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    habit_crud.restore_habit(db, habit_id)
    return RedirectResponse(url="/habits/manage", status_code=status.HTTP_303_SEE_OTHER)


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


@router.post("/completions/bulk")
def update_habit_completions_bulk(
    request: Request,
    target_date: str = Form(...),
    action: str = Form(...),
    db: Session = Depends(get_db),
) -> Response:
    today = date.today()
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
            "未来の日付の達成状態は一括変更できません。",
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    if action == "complete_expected":
        result = complete_all_expected_on(
            db,
            parsed_date,
            latest_editable_date=today,
        )
    elif action == "clear_all":
        result = clear_all_completions_on(
            db,
            parsed_date,
            latest_editable_date=today,
        )
    else:
        return render_daily_report(
            request,
            db,
            parsed_date,
            "一括操作が不正です。",
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    if result.status == BulkCompletionUpdateStatus.FUTURE_DATE:
        return render_daily_report(
            request,
            db,
            today,
            "未来の日付の達成状態は一括変更できません。",
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    return RedirectResponse(
        url=f"/habits/history?target_date={parsed_date.isoformat()}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/{habit_id}/completion")
def update_habit_completion(
    request: Request,
    habit_id: int,
    target_date: str = Form(...),
    completed: str = Form(...),
    db: Session = Depends(get_db),
) -> Response:
    today = date.today()
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
            "未来の日付の達成状態は変更できません。",
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    if completed not in {"true", "false"}:
        return render_daily_report(
            request,
            db,
            parsed_date,
            "達成状態が不正です。",
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    result = set_completion_on(
        db,
        habit_id,
        parsed_date,
        completed=completed == "true",
        latest_editable_date=today,
    )
    if result == CompletionUpdateResult.NOT_FOUND:
        return render_daily_report(
            request,
            db,
            parsed_date,
            "指定された習慣が存在しません。",
            status_code=status.HTTP_404_NOT_FOUND,
        )
    if result == CompletionUpdateResult.NOT_EXPECTED:
        return render_daily_report(
            request,
            db,
            parsed_date,
            "この日は習慣の有効期間または対象曜日の範囲外です。",
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    if result == CompletionUpdateResult.FUTURE_DATE:
        return render_daily_report(
            request,
            db,
            today,
            "未来の日付の達成状態は変更できません。",
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    return RedirectResponse(
        url=f"/habits/history?target_date={parsed_date.isoformat()}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


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


@router.get("/weekly.csv")
def export_habit_weekly_csv(
    target_date: str | None = None,
    db: Session = Depends(get_db),
) -> Response:
    today = date.today()
    selected_date = today
    if target_date is not None:
        parsed_date = parse_date(target_date)
        if parsed_date is None:
            return build_csv_error_response("日付はYYYY-MM-DD形式で指定してください。")
        if parsed_date > today:
            return build_csv_error_response(
                "未来の日付は習慣の週次CSV出力に指定できません。"
            )
        selected_date = parsed_date

    week_start = get_week_start(selected_date)
    week_end = week_start + timedelta(days=6)
    report = build_period_report(db, week_start, week_end, today)
    csv_content = build_habit_report_csv("週次", week_start, week_end, report)
    filename = f"home-panel-habit-weekly-{week_start.isoformat()}.csv"
    return build_csv_download_response(csv_content, filename)


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


@router.get("/monthly.csv")
def export_habit_monthly_csv(
    target_month: str | None = None,
    db: Session = Depends(get_db),
) -> Response:
    today = date.today()
    current_month_start = today.replace(day=1)
    selected_month = current_month_start
    if target_month is not None:
        parsed_month = parse_month(target_month)
        if parsed_month is None:
            return build_csv_error_response("月はYYYY-MM形式で指定してください。")
        if parsed_month > current_month_start:
            return build_csv_error_response(
                "未来の月は習慣の月次CSV出力に指定できません。"
            )
        selected_month = parsed_month

    month_start = selected_month.replace(day=1)
    month_end = get_month_end(month_start)
    report = build_period_report(db, month_start, month_end, today)
    csv_content = build_habit_report_csv("月次", month_start, month_end, report)
    filename = f"home-panel-habit-monthly-{month_start.strftime('%Y-%m')}.csv"
    return build_csv_download_response(csv_content, filename)
