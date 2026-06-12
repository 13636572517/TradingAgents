# server/database.py
import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./tradingagents.db")

connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}

_is_mysql = DATABASE_URL.startswith("mysql")
engine = create_engine(
    DATABASE_URL,
    connect_args=connect_args,
    pool_pre_ping=True,
    pool_recycle=1800 if _is_mysql else -1,
)
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
    # Lightweight migrations: add columns if they don't exist yet
    _migrate_add_column("users", "is_admin", "BOOLEAN NOT NULL DEFAULT 0")
    _migrate_add_column("analyses", "owner_id", "INT NULL")
    _migrate_add_column("app_settings", "max_api_calls", "INT NOT NULL DEFAULT 60")
    _migrate_add_column("app_settings", "tickflow_api_key", "TEXT")
    _migrate_add_column("analysis_strategies", "extraction_method",  "VARCHAR(10) DEFAULT 'regex'")
    _migrate_add_column("analysis_strategies", "confidence",         "VARCHAR(10)")
    _migrate_add_column("analysis_strategies", "stop_loss_basis",    "VARCHAR(50)")
    _migrate_add_column("analysis_strategies", "target_price_basis", "VARCHAR(50)")
    _migrate_add_column("analysis_strategies", "extraction_note",    "TEXT")


def _migrate_add_column(table: str, column: str, column_def: str) -> None:
    """Idempotently add a column to an existing table (SQLite-safe)."""
    from sqlalchemy import text, inspect as sa_inspect
    insp = sa_inspect(engine)
    existing_cols = [c["name"] for c in insp.get_columns(table)]
    if column not in existing_cols:
        with engine.connect() as conn:
            conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {column_def}"))
            conn.commit()
