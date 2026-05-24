# server/database.py
import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./tradingagents.db")

connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}

engine = create_engine(DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    """FastAPI dependency that yields a DB session and closes it on exit."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """Create all tables and apply lightweight migrations. Call once on startup."""
    from server import models  # noqa: F401 — ensure models are registered
    Base.metadata.create_all(bind=engine)
    # Lightweight migration: add is_admin column if it doesn't exist yet
    _migrate_add_column("users", "is_admin", "BOOLEAN NOT NULL DEFAULT 0")


def _migrate_add_column(table: str, column: str, column_def: str) -> None:
    """Idempotently add a column to an existing table (SQLite-safe)."""
    from sqlalchemy import text, inspect as sa_inspect
    insp = sa_inspect(engine)
    existing_cols = [c["name"] for c in insp.get_columns(table)]
    if column not in existing_cols:
        with engine.connect() as conn:
            conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {column_def}"))
            conn.commit()
