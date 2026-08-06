from typing import Any

from sqlalchemy import MetaData, create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import declarative_base, sessionmaker

from app.migrations import migrate_home_panel_schema

DATABASE_URL = "sqlite:///./home_panel.db"

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},
)


class HomePanelMetaData(MetaData):
    """テーブル作成前に既存SQLiteの互換移行を実行する。"""

    def create_all(
        self,
        bind: Engine,
        tables: Any = None,
        checkfirst: bool = True,
    ) -> None:
        migrate_home_panel_schema(bind)
        super().create_all(bind=bind, tables=tables, checkfirst=checkfirst)


Base = declarative_base(metadata=HomePanelMetaData())
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
