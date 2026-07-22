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


def list_entries_by_date(db: Session, target_date: date) -> list[TimeEntry]:
    stmt = (
        select(TimeEntry)
        .where(TimeEntry.entry_date == target_date)
        .order_by(TimeEntry.created_at.desc())
    )
    return list(db.scalars(stmt).all())


def list_today_entries(db: Session, today: date) -> list[TimeEntry]:
    return list_entries_by_date(db, today)


def get_total_minutes_by_date(db: Session, target_date: date) -> int:
    stmt = select(func.coalesce(func.sum(TimeEntry.minutes), 0)).where(
        TimeEntry.entry_date == target_date
    )
    return int(db.scalar(stmt) or 0)


def get_today_total_minutes(db: Session, today: date) -> int:
    return get_total_minutes_by_date(db, today)
