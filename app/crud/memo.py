from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.memo import DailyMemo


def get_memo_by_date(db: Session, target_date: date) -> DailyMemo | None:
    stmt = select(DailyMemo).where(DailyMemo.memo_date == target_date)
    return db.scalar(stmt)


def get_today_memo(db: Session, today: date) -> DailyMemo | None:
    return get_memo_by_date(db, today)


def upsert_memo_by_date(db: Session, target_date: date, content: str) -> DailyMemo:
    memo = get_memo_by_date(db, target_date)
    if memo is None:
        memo = DailyMemo(memo_date=target_date, content=content)
        db.add(memo)
    else:
        memo.content = content
    db.commit()
    db.refresh(memo)
    return memo


def upsert_today_memo(db: Session, today: date, content: str) -> DailyMemo:
    return upsert_memo_by_date(db, today, content)
