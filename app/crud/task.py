from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.task import Task


def list_tasks(db: Session) -> list[Task]:
    stmt = select(Task).order_by(Task.is_done.asc(), Task.created_at.desc())
    return list(db.scalars(stmt).all())


def create_task(db: Session, title: str) -> Task:
    task = Task(title=title)
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


def get_task(db: Session, task_id: int) -> Task | None:
    return db.get(Task, task_id)


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
