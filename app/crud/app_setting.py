import json
from typing import Any

from sqlalchemy.orm import Session

from app.models.app_setting import AppSetting


def get_json_setting(db: Session, key: str) -> Any | None:
    setting = db.get(AppSetting, key)
    if setting is None:
        return None

    try:
        return json.loads(setting.value)
    except (TypeError, json.JSONDecodeError):
        return None


def upsert_json_setting(db: Session, key: str, value: Any) -> AppSetting:
    serialized = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    setting = db.get(AppSetting, key)
    if setting is None:
        setting = AppSetting(key=key, value=serialized)
        db.add(setting)
    else:
        setting.value = serialized

    db.commit()
    db.refresh(setting)
    return setting


def delete_setting(db: Session, key: str) -> bool:
    setting = db.get(AppSetting, key)
    if setting is None:
        return False

    db.delete(setting)
    db.commit()
    return True
