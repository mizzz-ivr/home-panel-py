from pydantic import BaseModel, Field


class TimeEntryCreate(BaseModel):
    minutes: int = Field(ge=1, le=1440)
    note: str = Field(default="", max_length=255)
