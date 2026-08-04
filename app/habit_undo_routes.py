from __future__ import annotations

import re
from datetime import date

from fastapi import APIRouter, Depends, Form, status
from fastapi.responses import JSONResponse, RedirectResponse, Response
from sqlalchemy.orm import Session

from app.db import get_db
from app.habit_completion_undo import (
    UndoResultStatus,
    get_available_completion_undo,
    undo_completion_change,
    utc_now,
)

router = APIRouter(prefix="/completions", tags=["habit-completion-undo"])
DATE_PATTERN = re.compile(r"\d{4}-\d{2}-\d{2}\Z")

NO_STORE_HEADERS = {
    "Cache-Control": "no-store",
    "X-Content-Type-Options": "nosniff",
}


def parse_date(value: str) -> date | None:
    if not DATE_PATTERN.fullmatch(value):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


@router.get("/undo")
def get_completion_undo_status(
    target_date: str,
    db: Session = Depends(get_db),
) -> JSONResponse:
    parsed_date = parse_date(target_date)
    if parsed_date is None:
        return JSONResponse(
            {"detail": "日付はYYYY-MM-DD形式で指定してください。"},
            status_code=status.HTTP_400_BAD_REQUEST,
            headers=NO_STORE_HEADERS,
        )

    action = get_available_completion_undo(db, target_date=parsed_date)
    if action is None:
        return JSONResponse(
            {"available": False},
            headers=NO_STORE_HEADERS,
        )

    remaining_seconds = max(
        0,
        int((action.expires_at - utc_now()).total_seconds()),
    )
    return JSONResponse(
        {
            "available": True,
            "token": action.token,
            "target_date": action.target_date.isoformat(),
            "label": action.label,
            "expires_in_seconds": remaining_seconds,
        },
        headers=NO_STORE_HEADERS,
    )


@router.post("/undo")
def undo_completion(
    token: str = Form(...),
    db: Session = Depends(get_db),
) -> Response:
    if not 16 <= len(token) <= 128:
        return Response(
            content="Undoトークンが不正です。",
            status_code=status.HTTP_400_BAD_REQUEST,
            media_type="text/plain; charset=utf-8",
            headers=NO_STORE_HEADERS,
        )

    result = undo_completion_change(db, token)
    if result.status == UndoResultStatus.RESTORED and result.action is not None:
        return RedirectResponse(
            url=result.action.return_url,
            status_code=status.HTTP_303_SEE_OTHER,
            headers=NO_STORE_HEADERS,
        )

    response_map = {
        UndoResultStatus.NOT_FOUND: (
            status.HTTP_404_NOT_FOUND,
            "元に戻せる習慣操作がありません。",
        ),
        UndoResultStatus.INVALID_TOKEN: (
            status.HTTP_400_BAD_REQUEST,
            "Undoトークンが一致しません。",
        ),
        UndoResultStatus.EXPIRED: (
            status.HTTP_410_GONE,
            "Undoの有効期限が切れています。",
        ),
        UndoResultStatus.STATE_CHANGED: (
            status.HTTP_409_CONFLICT,
            "後続の変更があるため、古いUndoは実行できません。",
        ),
        UndoResultStatus.MISSING_HABIT: (
            status.HTTP_409_CONFLICT,
            "復元対象の習慣が存在しないため、Undoを実行できません。",
        ),
    }
    response_status, message = response_map[result.status]
    return Response(
        content=message,
        status_code=response_status,
        media_type="text/plain; charset=utf-8",
        headers=NO_STORE_HEADERS,
    )
