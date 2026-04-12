from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.memo import DailyMemo


def get_today_memo(db: Session, today: date) -> DailyMemo | None:
    stmt = select(DailyMemo).where(DailyMemo.memo_date == today)
    return db.scalar(stmt)


def upsert_today_memo(db: Session, today: date, content: str) -> DailyMemo:
    memo = get_today_memo(db, today)
    if memo is None:
        memo = DailyMemo(memo_date=today, content=content)
        db.add(memo)
    else:
        memo.content = content
    db.commit()
    db.refresh(memo)
    return memo
