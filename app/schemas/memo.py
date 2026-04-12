from pydantic import BaseModel, Field


class DailyMemoUpdate(BaseModel):
    content: str = Field(default="", max_length=5000)
