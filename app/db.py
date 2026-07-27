from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from app.migrations import migrate_habit_schema

DATABASE_URL = "sqlite:///./home_panel.db"

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},
)
migrate_habit_schema(engine)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
