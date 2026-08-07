from __future__ import annotations

import re
from datetime import date

from fastapi import APIRouter, Depends, Form, status
from fastapi.responses import RedirectResponse, Response
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.crud import task as task_crud
from app.db import get_db
from app.schemas.task import TaskCreate, TaskDetailsUpdate
from app.task_views import todo_dashboard_url

router = APIRouter(tags=["tasks"])
DATE_PATTERN = re.compile(r"\d{4}-\d{2}-\d{2}\Z")
NO_STORE_HEADERS = {
    "Cache-Control": "no-store",
    "X-Content-Type-Options": "nosniff",
}


def parse_optional_due_date(value: str) -> date | None:
    stripped = value.strip()
    if not stripped:
        return None
    if not DATE_PATTERN.fullmatch(stripped):
        raise ValueError("期限はYYYY-MM-DD形式で指定してください。")
    try:
        return date.fromisoformat(stripped)
    except ValueError as exc:
        raise ValueError("期限には実在する日付を指定してください。") from exc


def validation_error_response(message: str) -> Response:
    return Response(
        content=message,
        status_code=status.HTTP_400_BAD_REQUEST,
        media_type="text/plain; charset=utf-8",
        headers=NO_STORE_HEADERS,
    )


@router.post("/tasks/advanced")
def create_task_with_details(
    title: str = Form(...),
    due_date: str = Form(""),
    priority: str = Form("medium"),
    todo_view: str = Form("all"),
    show_card: str = Form(""),
    db: Session = Depends(get_db),
) -> Response:
    stripped_title = title.strip()
    if not stripped_title:
        return validation_error_response("タスク名を入力してください。")

    try:
        parsed_due_date = parse_optional_due_date(due_date)
        payload = TaskCreate(
            title=stripped_title,
            due_date=parsed_due_date,
            priority=priority,
        )
    except (ValueError, ValidationError):
        return validation_error_response(
            "タスク名、期限、優先度の入力内容を確認してください。"
        )

    task = task_crud.create_task(
        db,
        payload.title,
        due_date=payload.due_date,
        priority=payload.priority,
    )
    return RedirectResponse(
        url=todo_dashboard_url(todo_view, show_card=show_card, task_id=task.id),
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/tasks/{task_id}/details")
def update_task_details(
    task_id: int,
    due_date: str = Form(""),
    priority: str = Form(...),
    todo_view: str = Form("all"),
    show_card: str = Form(""),
    db: Session = Depends(get_db),
) -> Response:
    try:
        payload = TaskDetailsUpdate(
            due_date=parse_optional_due_date(due_date),
            priority=priority,
        )
    except (ValueError, ValidationError):
        return validation_error_response(
            "期限はYYYY-MM-DD形式、優先度は低・中・高から指定してください。"
        )

    task = task_crud.update_task_details(
        db,
        task_id,
        due_date=payload.due_date,
        priority=payload.priority,
    )
    if task is None:
        return Response(
            content="指定されたタスクが存在しません。",
            status_code=status.HTTP_404_NOT_FOUND,
            media_type="text/plain; charset=utf-8",
            headers=NO_STORE_HEADERS,
        )
    return RedirectResponse(
        url=todo_dashboard_url(todo_view, show_card=show_card, task_id=task.id),
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/tasks/{task_id}/toggle-view")
def toggle_task_in_view(
    task_id: int,
    todo_view: str = Form("all"),
    show_card: str = Form(""),
    db: Session = Depends(get_db),
) -> Response:
    task = task_crud.toggle_task(db, task_id)
    if task is None:
        return Response(
            content="指定されたタスクが存在しません。",
            status_code=status.HTTP_404_NOT_FOUND,
            media_type="text/plain; charset=utf-8",
            headers=NO_STORE_HEADERS,
        )
    return RedirectResponse(
        url=todo_dashboard_url(todo_view, show_card=show_card),
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/tasks/{task_id}/delete-view")
def delete_task_in_view(
    task_id: int,
    todo_view: str = Form("all"),
    show_card: str = Form(""),
    db: Session = Depends(get_db),
) -> Response:
    if not task_crud.delete_task(db, task_id):
        return Response(
            content="指定されたタスクが存在しません。",
            status_code=status.HTTP_404_NOT_FOUND,
            media_type="text/plain; charset=utf-8",
            headers=NO_STORE_HEADERS,
        )
    return RedirectResponse(
        url=todo_dashboard_url(todo_view, show_card=show_card),
        status_code=status.HTTP_303_SEE_OTHER,
    )
