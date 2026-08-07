from datetime import date

from sqlalchemy import case, select
from sqlalchemy.orm import Session

from app.models.task import Task
from app.task_priority import DEFAULT_TASK_PRIORITY, is_valid_task_priority


def list_tasks(db: Session, *, today: date | None = None) -> list[Task]:
    current_date = today or date.today()
    due_order = case(
        (Task.is_done.is_(True), 4),
        (Task.due_date.is_(None), 3),
        (Task.due_date < current_date, 0),
        (Task.due_date == current_date, 1),
        else_=2,
    )
    priority_order = case(
        (Task.is_done.is_(True), 3),
        (Task.priority == "high", 0),
        (Task.priority == "medium", 1),
        else_=2,
    )
    active_due_date = case(
        (Task.is_done.is_(False), Task.due_date),
        else_=None,
    )
    stmt = select(Task).order_by(
        Task.is_done.asc(),
        due_order.asc(),
        priority_order.asc(),
        active_due_date.asc(),
        Task.created_at.desc(),
        Task.id.desc(),
    )
    return list(db.scalars(stmt).all())


def create_task(
    db: Session,
    title: str,
    *,
    due_date: date | None = None,
    priority: str = DEFAULT_TASK_PRIORITY,
) -> Task:
    if not is_valid_task_priority(priority):
        raise ValueError("優先度が不正です。")
    task = Task(title=title, due_date=due_date, priority=priority)
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


def get_task(db: Session, task_id: int) -> Task | None:
    return db.get(Task, task_id)


def update_task_details(
    db: Session,
    task_id: int,
    *,
    due_date: date | None,
    priority: str,
) -> Task | None:
    if not is_valid_task_priority(priority):
        raise ValueError("優先度が不正です。")
    task = get_task(db, task_id)
    if task is None:
        return None
    task.due_date = due_date
    task.priority = priority
    db.commit()
    db.refresh(task)
    return task


def toggle_task(db: Session, task_id: int) -> Task | None:
    task = get_task(db, task_id)
    if not task:
        return None
    task.is_done = not task.is_done
    db.commit()
    db.refresh(task)
    return task


def delete_task(db: Session, task_id: int) -> bool:
    task = get_task(db, task_id)
    if not task:
        return False
    db.delete(task)
    db.commit()
    return True
