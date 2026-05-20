# tests/test_server_analyses.py
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from server.database import Base, get_db
from server.models import Analysis  # noqa: F401 — registers model with Base metadata

# Use in-memory SQLite for tests — StaticPool ensures all connections share
# the same in-memory database so create_all and subsequent sessions see the same DB.
TEST_DB_URL = "sqlite://"
test_engine = create_engine(
    TEST_DB_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)


@pytest.fixture(autouse=True)
def setup_db():
    Base.metadata.create_all(bind=test_engine)
    yield
    Base.metadata.drop_all(bind=test_engine)


@pytest.fixture
def client():
    # Import app here so server.main exists before fixture runs
    from server.main import app

    def override_get_db():
        db = TestSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def test_create_analysis_returns_201(client):
    resp = client.post("/api/analyses", json={
        "ticker": "600519.SS",
        "trade_date": "2024-05-10",
        "analysts": ["fundamentals", "sentiment"],
        "depth": 1,
    })
    assert resp.status_code == 201
    data = resp.json()
    assert data["ticker"] == "600519.SS"
    assert data["status"] == "pending"
    assert "id" in data


def test_list_analyses_empty(client):
    resp = client.get("/api/analyses")
    assert resp.status_code == 200
    assert resp.json()["items"] == []
    assert resp.json()["total"] == 0


def test_list_analyses_returns_created(client):
    client.post("/api/analyses", json={
        "ticker": "AAPL",
        "trade_date": "2024-05-10",
        "analysts": ["fundamentals"],
        "depth": 1,
    })
    resp = client.get("/api/analyses")
    assert resp.json()["total"] == 1
    assert resp.json()["items"][0]["ticker"] == "AAPL"


def test_get_analysis_by_id(client):
    create_resp = client.post("/api/analyses", json={
        "ticker": "NVDA",
        "trade_date": "2024-05-10",
        "analysts": ["fundamentals"],
        "depth": 1,
    })
    analysis_id = create_resp.json()["id"]
    resp = client.get(f"/api/analyses/{analysis_id}")
    assert resp.status_code == 200
    assert resp.json()["id"] == analysis_id


def test_get_analysis_not_found(client):
    resp = client.get("/api/analyses/nonexistent-id")
    assert resp.status_code == 404


def test_delete_analysis(client):
    create_resp = client.post("/api/analyses", json={
        "ticker": "TSLA",
        "trade_date": "2024-05-10",
        "analysts": ["fundamentals"],
        "depth": 1,
    })
    analysis_id = create_resp.json()["id"]
    del_resp = client.delete(f"/api/analyses/{analysis_id}")
    assert del_resp.status_code == 204
    assert client.get(f"/api/analyses/{analysis_id}").status_code == 404


def test_notification_count_zero_when_all_seen(client):
    resp = client.get("/api/notifications/count")
    assert resp.status_code == 200
    assert resp.json()["unseen"] == 0
