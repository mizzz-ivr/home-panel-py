from pydantic import BaseModel, ConfigDict, field_validator


class HabitCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    name: str

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        if not value:
            raise ValueError("習慣名を入力してください。")
        if len(value) > 100:
            raise ValueError("習慣名は100文字以内で入力してください。")
        return value
