from datetime import date, datetime
from pathlib import Path

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.habit_completion import (
    BulkCompletionUpdateStatus,
    CompletionUpdateResult,
    complete_all_expected_on,
    set_completion_on,
)
from app.models.habit import Habit, HabitCompletion

TARGET_DATE = date(2026, 7, 28)
LATEST_EDITABLE_DATE = date(2026, 7, 30)


def test_single_and_bulk_completion_use_legacy_fallback(tmp_path: Path):
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    created_at = datetime(2026, 7, 20)
    with session_factory() as db:
        first = Habit(
            name="旧形式の読書",
            created_at=created_at,
            updated_at=created_at,
        )
        second = Habit(
            name="旧形式の運動",
            created_at=created_at,
            updated_at=created_at,
        )
        db.add_all([first, second])
        db.commit()
        first_id = first.id
        second_id = second.id

        single_result = set_completion_on(
            db,
            first_id,
            TARGET_DATE,
            completed=True,
            latest_editable_date=LATEST_EDITABLE_DATE,
        )
        bulk_result = complete_all_expected_on(
            db,
            TARGET_DATE,
            latest_editable_date=LATEST_EDITABLE_DATE,
        )

        completion_count = int(
            db.scalar(
                select(func.count(HabitCompletion.id)).where(
                    HabitCompletion.completed_on == TARGET_DATE
                )
            )
            or 0
        )
        second_completion = db.scalar(
            select(HabitCompletion).where(
                HabitCompletion.habit_id == second_id,
                HabitCompletion.completed_on == TARGET_DATE,
            )
        )

    engine.dispose()

    assert single_result == CompletionUpdateResult.CREATED
    assert bulk_result.status == BulkCompletionUpdateStatus.UPDATED
    assert bulk_result.target_count == 2
    assert bulk_result.created_count == 1
    assert completion_count == 2
    assert second_completion is not None
