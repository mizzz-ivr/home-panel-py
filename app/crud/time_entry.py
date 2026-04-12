from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.time_entry import TimeEntry


def add_time_entry(db: Session, today: date, minutes: int, note: str, category: str = "作業") -> TimeEntry:
    entry = TimeEntry(entry_date=today, minutes=minutes, note=note, category=category)
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry


def list_today_entries(db: Session, today: date) -> list[TimeEntry]:
    stmt = select(TimeEntry).where(TimeEntry.entry_date == today).order_by(TimeEntry.created_at.desc())
    return list(db.scalars(stmt).all())


def get_today_total_minutes(db: Session, today: date) -> int:
    stmt = select(func.coalesce(func.sum(TimeEntry.minutes), 0)).where(TimeEntry.entry_date == today)
    return int(db.scalar(stmt) or 0)
