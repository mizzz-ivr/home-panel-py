from datetime import date, datetime

from sqlalchemy import Boolean, CheckConstraint, Date, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.task_priority import DEFAULT_TASK_PRIORITY


class Task(Base):
    __tablename__ = "tasks"
    __table_args__ = (
        CheckConstraint(
            "priority IN ('low', 'medium', 'high')",
            name="ck_tasks_priority",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    is_done: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    priority: Mapped[str] = mapped_column(
        String(10),
        default=DEFAULT_TASK_PRIORITY,
        nullable=False,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )
