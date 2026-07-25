from pydantic import BaseModel, Field


class DashboardPreferencesUpdate(BaseModel):
    order: list[str] = Field(min_length=1)
    hidden: list[str] = Field(default_factory=list)
