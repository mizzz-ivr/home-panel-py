import re
from datetime import date, timedelta
from pathlib import Path

from fastapi import Depends, FastAPI, Form, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app import models  # noqa: F401
from app.crud import memo as memo_crud
from app.crud import task as task_crud
from app.crud import time_entry as time_entry_crud
from app.csv_export import build_time_entries_csv
from app.db import Base, engine, get_db
from app.schemas.memo import DailyMemoUpdate
from app.schemas.task import TaskCreate
from app.schemas.time_entry import TIME_ENTRY_CATEGORIES, TimeEntryCreate

BASE_DIR = Path(__file__).resolve().parent
HISTORY_DATE_PATTERN = re.compile(r"\d{4}-\d{2}-\d{2}\Z")
MONTH_PATTERN = re.compile(r"\d{4}-\d{2}\Z")
WEEKDAY_LABELS = ("月", "火", "水", "木", "金", "土", "日")

app = FastAPI(title="Home Panel")
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


@app.on_event("startup")
def on_startup() -> None:
    Base.metadata.create_all(bind=engine)


def render_dashboard(
    request: Request,
    db: Session,
    error_message: str | None = None,
    status_code: int = status.HTTP_200_OK,
) -> HTMLResponse:
    today = date.today()
    tasks = task_crud.list_tasks(db)
    memo = memo_crud.get_today_memo(db, today)
    entries = time_entry_crud.list_today_entries(db, today)
    total_minutes = time_entry_crud.get_today_total_minutes(db, today)
    category_totals = time_entry_crud.get_today_category_totals(db, today)

    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "today": today,
            "tasks": tasks,
            "memo_content": memo.content if memo else "",
            "entries": entries,
            "total_minutes": total_minutes,
            "category_totals": category_totals,
            "time_entry_categories": TIME_ENTRY_CATEGORIES,
            "error_message": error_message,
        },
        status_code=status_code,
    )


def render_history(
    request: Request,
    db: Session,
    selected_date: date,
    error_message: str | None = None,
    status_code: int = status.HTTP_200_OK,
) -> HTMLResponse:
    today = date.today()
    memo = memo_crud.get_memo_by_date(db, selected_date)
    entries = time_entry_crud.list_entries_by_date(db, selected_date)
    total_minutes = time_entry_crud.get_total_minutes_by_date(db, selected_date)
    category_totals = time_entry_crud.get_category_totals_by_date(db, selected_date)

    return templates.TemplateResponse(
        "history.html",
        {
            "request": request,
            "today": today,
            "selected_date": selected_date,
            "previous_date": selected_date - timedelta(days=1) if selected_date > date.min else None,
            "next_date": selected_date + timedelta(days=1) if selected_date < today else None,
            "memo_content": memo.content if memo and memo.content.strip() else None,
            "entries": entries,
            "total_minutes": total_minutes,
            "category_totals": category_totals,
            "entry_count": len(entries),
            "error_message": error_message,
        },
        status_code=status_code,
    )


def get_week_start(target_date: date) -> date:
    return target_date - timedelta(days=target_date.weekday())


def render_weekly(
    request: Request,
    db: Session,
    selected_date: date,
    error_message: str | None = None,
    status_code: int = status.HTTP_200_OK,
) -> HTMLResponse:
    today = date.today()
    week_start = get_week_start(selected_date)
    week_end = week_start + timedelta(days=6)
    effective_end = min(week_end, today)
    current_week_start = get_week_start(today)

    total_minutes, entry_count = time_entry_crud.get_range_summary(db, week_start, effective_end)
    category_totals = time_entry_crud.get_category_totals_between(db, week_start, effective_end)
    daily_totals = dict(time_entry_crud.get_daily_totals_between(db, week_start, effective_end))
    max_daily_minutes = max(daily_totals.values(), default=0)

    daily_summaries = []
    for offset in range(7):
        target_date = week_start + timedelta(days=offset)
        minutes = daily_totals.get(target_date, 0)
        daily_summaries.append(
            {
                "date": target_date,
                "weekday": WEEKDAY_LABELS[target_date.weekday()],
                "minutes": minutes,
                "is_future": target_date > today,
                "percentage": round(minutes / max_daily_minutes * 100) if max_daily_minutes else 0,
            }
        )

    previous_week_start = (
        week_start - timedelta(days=7)
        if week_start >= date.min + timedelta(days=7)
        else None
    )
    next_week_start = (
        week_start + timedelta(days=7)
        if week_start < current_week_start
        else None
    )

    return templates.TemplateResponse(
        "weekly.html",
        {
            "request": request,
            "today": today,
            "selected_date": selected_date,
            "week_start": week_start,
            "week_end": week_end,
            "effective_end": effective_end,
            "previous_week_start": previous_week_start,
            "next_week_start": next_week_start,
            "total_minutes": total_minutes,
            "entry_count": entry_count,
            "active_days": sum(1 for summary in daily_summaries if summary["minutes"] > 0),
            "category_totals": category_totals,
            "daily_summaries": daily_summaries,
            "error_message": error_message,
        },
        status_code=status_code,
    )


def get_month_start(target_date: date) -> date:
    return target_date.replace(day=1)


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


def render_monthly(
    request: Request,
    db: Session,
    selected_month: date,
    error_message: str | None = None,
    status_code: int = status.HTTP_200_OK,
) -> HTMLResponse:
    today = date.today()
    month_start = get_month_start(selected_month)
    month_end = get_month_end(month_start)
    effective_end = min(month_end, today)
    current_month_start = get_month_start(today)

    total_minutes, entry_count = time_entry_crud.get_range_summary(db, month_start, effective_end)
    category_totals = time_entry_crud.get_category_totals_between(db, month_start, effective_end)
    daily_totals = dict(time_entry_crud.get_daily_totals_between(db, month_start, effective_end))
    max_daily_minutes = max(daily_totals.values(), default=0)

    daily_summaries = []
    days_in_month = (month_end - month_start).days + 1
    for offset in range(days_in_month):
        target_date = month_start + timedelta(days=offset)
        minutes = daily_totals.get(target_date, 0)
        daily_summaries.append(
            {
                "date": target_date,
                "minutes": minutes,
                "is_future": target_date > today,
                "is_today": target_date == today,
                "percentage": round(minutes / max_daily_minutes * 100) if max_daily_minutes else 0,
            }
        )

    active_days = sum(1 for summary in daily_summaries if summary["minutes"] > 0)
    previous_month_start = get_previous_month_start(month_start)
    next_month_start = (
        get_next_month_start(month_start)
        if month_start < current_month_start
        else None
    )

    return templates.TemplateResponse(
        "monthly.html",
        {
            "request": request,
            "today": today,
            "month_start": month_start,
            "month_end": month_end,
            "effective_end": effective_end,
            "previous_month_start": previous_month_start,
            "next_month_start": next_month_start,
            "total_minutes": total_minutes,
            "entry_count": entry_count,
            "active_days": active_days,
            "average_minutes": round(total_minutes / active_days) if active_days else 0,
            "category_totals": category_totals,
            "daily_summaries": daily_summaries,
            "leading_blank_days": month_start.weekday(),
            "weekday_labels": WEEKDAY_LABELS,
            "error_message": error_message,
        },
        status_code=status_code,
    )


def parse_history_date(value: str) -> date | None:
    if not HISTORY_DATE_PATTERN.fullmatch(value):
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


@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    return render_dashboard(request, db)


@app.get("/history", response_class=HTMLResponse)
def history(
    request: Request,
    target_date: str | None = None,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    today = date.today()
    selected_date = today

    if target_date is not None:
        parsed_date = parse_history_date(target_date)
        if parsed_date is None:
            return render_history(
                request,
                db,
                today,
                "日付はYYYY-MM-DD形式で指定してください。",
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        selected_date = parsed_date
        if selected_date > today:
            return render_history(
                request,
                db,
                today,
                "未来の日付は履歴として表示できません。",
                status_code=status.HTTP_400_BAD_REQUEST,
            )

    return render_history(request, db, selected_date)


@app.get("/weekly", response_class=HTMLResponse)
def weekly(
    request: Request,
    target_date: str | None = None,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    today = date.today()
    selected_date = today

    if target_date is not None:
        parsed_date = parse_history_date(target_date)
        if parsed_date is None:
            return render_weekly(
                request,
                db,
                today,
                "日付はYYYY-MM-DD形式で指定してください。",
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        selected_date = parsed_date
        if selected_date > today:
            return render_weekly(
                request,
                db,
                today,
                "未来の日付は週次集計の基準日に指定できません。",
                status_code=status.HTTP_400_BAD_REQUEST,
            )

    return render_weekly(request, db, selected_date)


@app.get("/monthly", response_class=HTMLResponse)
def monthly(
    request: Request,
    target_month: str | None = None,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    today = date.today()
    current_month_start = get_month_start(today)
    selected_month = current_month_start

    if target_month is not None:
        parsed_month = parse_month(target_month)
        if parsed_month is None:
            return render_monthly(
                request,
                db,
                current_month_start,
                "月はYYYY-MM形式で指定してください。",
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        selected_month = parsed_month
        if selected_month > current_month_start:
            return render_monthly(
                request,
                db,
                current_month_start,
                "未来の月は月次集計に指定できません。",
                status_code=status.HTTP_400_BAD_REQUEST,
            )

    return render_monthly(request, db, selected_month)


@app.get("/exports/time-entries.csv")
def export_time_entries_csv(
    target_month: str | None = None,
    db: Session = Depends(get_db),
) -> Response:
    today = date.today()
    current_month_start = get_month_start(today)
    selected_month = current_month_start

    if target_month is not None:
        parsed_month = parse_month(target_month)
        if parsed_month is None:
            return Response(
                content="月はYYYY-MM形式で指定してください。",
                status_code=status.HTTP_400_BAD_REQUEST,
                media_type="text/plain; charset=utf-8",
                headers={
                    "Cache-Control": "no-store",
                    "X-Content-Type-Options": "nosniff",
                },
            )

        selected_month = parsed_month
        if selected_month > current_month_start:
            return Response(
                content="未来の月はCSV出力に指定できません。",
                status_code=status.HTTP_400_BAD_REQUEST,
                media_type="text/plain; charset=utf-8",
                headers={
                    "Cache-Control": "no-store",
                    "X-Content-Type-Options": "nosniff",
                },
            )

    month_end = get_month_end(selected_month)
    effective_end = min(month_end, today)
    entries = time_entry_crud.list_entries_between(db, selected_month, effective_end)
    csv_content = build_time_entries_csv(entries)
    filename = f"home-panel-time-entries-{selected_month.strftime('%Y-%m')}.csv"

    return Response(
        content=csv_content,
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


@app.post("/tasks")
def create_task(
    request: Request,
    title: str = Form(...),
    db: Session = Depends(get_db),
):
    stripped = title.strip()
    if not stripped:
        return render_dashboard(request, db, "タスク名を入力してください。")

    try:
        payload = TaskCreate(title=stripped)
    except ValidationError:
        return render_dashboard(request, db, "タスク名が不正です。")

    task_crud.create_task(db, payload.title)
    return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)


@app.post("/tasks/{task_id}/toggle")
def toggle_task(request: Request, task_id: int, db: Session = Depends(get_db)):
    result = task_crud.toggle_task(db, task_id)
    if result is None:
        return render_dashboard(
            request,
            db,
            "指定されたタスクが存在しません。",
            status_code=status.HTTP_404_NOT_FOUND,
        )
    return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)


@app.post("/tasks/{task_id}/delete")
def delete_task(request: Request, task_id: int, db: Session = Depends(get_db)):
    deleted = task_crud.delete_task(db, task_id)
    if not deleted:
        return render_dashboard(
            request,
            db,
            "指定されたタスクが存在しません。",
            status_code=status.HTTP_404_NOT_FOUND,
        )
    return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)


@app.get("/memo/today")
def get_today_memo(db: Session = Depends(get_db)):
    today = date.today()
    memo = memo_crud.get_today_memo(db, today)
    return {"memo_date": str(today), "content": memo.content if memo else ""}


@app.post("/memo/today")
def save_today_memo(request: Request, content: str = Form(""), db: Session = Depends(get_db)):
    try:
        payload = DailyMemoUpdate(content=content)
    except ValidationError:
        return render_dashboard(
            request,
            db,
            "メモ内容は5000文字以内で入力してください。",
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    memo_crud.upsert_today_memo(db, date.today(), payload.content)
    return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)


@app.post("/time-entries")
def add_time_entry(
    request: Request,
    minutes: str = Form(...),
    note: str = Form(""),
    category: str = Form("作業"),
    db: Session = Depends(get_db),
):
    if category not in TIME_ENTRY_CATEGORIES:
        return render_dashboard(
            request,
            db,
            "カテゴリは学習・作業・個人開発・その他から選択してください。",
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    try:
        parsed_minutes = int(minutes)
    except ValueError:
        return render_dashboard(request, db, "時間は1〜1440分の整数で入力してください。")

    try:
        payload = TimeEntryCreate(category=category, minutes=parsed_minutes, note=note.strip())
    except ValidationError:
        return render_dashboard(request, db, "時間は1〜1440分の整数で入力してください。")

    time_entry_crud.add_time_entry(
        db,
        date.today(),
        payload.minutes,
        payload.note,
        category=payload.category.value,
    )
    return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)
