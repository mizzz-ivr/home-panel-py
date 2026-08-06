from datetime import date

from pydantic import BaseModel, Field

from app.task_priority import DEFAULT_TASK_PRIORITY, TaskPriority


class TaskCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    due_date: date | None = None
    priority: TaskPriority = DEFAULT_TASK_PRIORITY


class TaskDetailsUpdate(BaseModel):
    due_date: date | None = None
    priority: TaskPriority
