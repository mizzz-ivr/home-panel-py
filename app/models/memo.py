from datetime import date, datetime

from sqlalchemy import Date, DateTime, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class DailyMemo(Base):
    __tablename__ = "daily_memos"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    memo_date: Mapped[date] = mapped_column(Date, unique=True, index=True, nullable=False)
    content: Mapped[str] = mapped_column(Text, default="", nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )
