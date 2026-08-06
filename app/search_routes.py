from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.db import get_db
from app.global_search import SEARCH_RESULT_LIMIT_PER_CATEGORY, GlobalSearchResults, search_all
from app.task_routes import router as task_router

BASE_DIR = Path(__file__).resolve().parent
MIN_SEARCH_QUERY_LENGTH = 2
MAX_SEARCH_QUERY_LENGTH = 100
NO_STORE_HEADERS = {
    "Cache-Control": "no-store",
    "X-Content-Type-Options": "nosniff",
}

router = APIRouter(tags=["search"])
router.include_router(task_router)
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


def empty_results() -> GlobalSearchResults:
    return GlobalSearchResults((), (), (), ())


def render_search(
    request: Request,
    *,
    query: str,
    searched: bool,
    results: GlobalSearchResults,
    error_message: str | None = None,
    status_code: int = status.HTTP_200_OK,
) -> HTMLResponse:
    return templates.TemplateResponse(
        "search.html",
        {
            "request": request,
            "query": query,
            "searched": searched,
            "results": results,
            "error_message": error_message,
            "result_limit_per_category": SEARCH_RESULT_LIMIT_PER_CATEGORY,
        },
        status_code=status_code,
        headers=NO_STORE_HEADERS,
    )


@router.get("/search", response_class=HTMLResponse)
def global_search(
    request: Request,
    q: str | None = None,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    if q is None:
        return render_search(
            request,
            query="",
            searched=False,
            results=empty_results(),
        )

    query = q.strip()
    if not MIN_SEARCH_QUERY_LENGTH <= len(query) <= MAX_SEARCH_QUERY_LENGTH:
        return render_search(
            request,
            query=query,
            searched=False,
            results=empty_results(),
            error_message=(
                f"検索語は{MIN_SEARCH_QUERY_LENGTH}〜{MAX_SEARCH_QUERY_LENGTH}文字で入力してください。"
            ),
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    results = search_all(db, query)
    return render_search(
        request,
        query=query,
        searched=True,
        results=results,
    )
