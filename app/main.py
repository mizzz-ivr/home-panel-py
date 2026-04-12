from datetime import date
from pathlib import Path

from fastapi import Depends, FastAPI, Form, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app import models  # noqa: F401
from app.crud import memo as memo_crud
from app.crud import task as task_crud
from app.crud import time_entry as time_entry_crud
from app.db import Base, engine, get_db
from app.schemas.memo import DailyMemoUpdate
from app.schemas.task import TaskCreate
from app.schemas.time_entry import TimeEntryCreate

BASE_DIR = Path(__file__).resolve().parent

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

    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "today": today,
            "tasks": tasks,
            "memo_content": memo.content if memo else "",
            "entries": entries,
            "total_minutes": total_minutes,
            "error_message": error_message,
        },
        status_code=status_code,
    )


@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    return render_dashboard(request, db)


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
    db: Session = Depends(get_db),
):
    try:
        parsed_minutes = int(minutes)
    except ValueError:
        return render_dashboard(request, db, "時間は1〜1440分の整数で入力してください。")

    try:
        payload = TimeEntryCreate(minutes=parsed_minutes, note=note.strip())
    except ValidationError:
        return render_dashboard(request, db, "時間は1〜1440分の整数で入力してください。")

    time_entry_crud.add_time_entry(db, date.today(), payload.minutes, payload.note)
    return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)
