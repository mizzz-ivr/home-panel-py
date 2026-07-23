from enum import Enum

from pydantic import BaseModel, Field


class TimeEntryCategory(str, Enum):
    STUDY = "学習"
    WORK = "作業"
    PERSONAL_DEVELOPMENT = "個人開発"
    OTHER = "その他"


TIME_ENTRY_CATEGORIES = tuple(category.value for category in TimeEntryCategory)


class TimeEntryCreate(BaseModel):
    category: TimeEntryCategory = TimeEntryCategory.WORK
    minutes: int = Field(ge=1, le=1440)
    note: str = Field(default="", max_length=255)
