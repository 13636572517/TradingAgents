# tests/test_auth.py
"""Auth system tests — use an in-memory SQLite DB via dependency override."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from server.database import Base, get_db
from server.main import app

# ── In-memory test DB ────────────────────────────────────────────────────────
_engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
_Session = sessionmaker(autocommit=False, autoflush=False, bind=_engine)


@pytest.fixture(autouse=True)
def reset_db():
    """Recreate all tables before each test, drop after."""
    Base.metadata.create_all(bind=_engine)
    yield
    Base.metadata.drop_all(bind=_engine)


@pytest.fixture
def db_session(reset_db):
    session = _Session()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture(autouse=True)
def override_db(db_session):
    app.dependency_overrides[get_db] = lambda: db_session
    yield
    app.dependency_overrides.clear()


client = TestClient(app, raise_server_exceptions=False)


# ── Task 2: User model ────────────────────────────────────────────────────────

@pytest.mark.unit
def test_user_model_create(db_session):
    from server.models import User
    user = User(username="alice", hashed_password="hashed_pw")
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    assert user.id is not None
    assert user.username == "alice"
    assert user.is_active is True
    assert user.created_at is not None
