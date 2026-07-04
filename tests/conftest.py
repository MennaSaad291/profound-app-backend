"""
conftest.py — shared pytest fixtures for all backend API tests.

Uses an in-memory SQLite database so tests are isolated from the real
Neon/Postgres database and run without any network access.
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database import Base, get_db
from main import app

# ── In-memory SQLite test DB ──────────────────────────────────────────────────
TEST_DATABASE_URL = "sqlite:///./test_profound.db"

engine = create_engine(
    TEST_DATABASE_URL,
    connect_args={"check_same_thread": False}
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


# Apply the DB override once for the whole test session
app.dependency_overrides[get_db] = override_get_db


@pytest.fixture(scope="session", autouse=True)
def create_tables():
    """Create all tables once before any test runs."""
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture(scope="function")
def client():
    """Return a fresh TestClient for each test."""
    return TestClient(app)


@pytest.fixture(scope="function")
def db():
    """Return a test DB session that is rolled back after each test."""
    connection = engine.connect()
    transaction = connection.begin()
    session = TestingSessionLocal(bind=connection)
    yield session
    session.close()
    transaction.rollback()
    connection.close()


# ── Convenience: register + login helpers ────────────────────────────────────

def register_and_login(client, email: str = "test@university.edu",
                       password: str = "TestPass123") -> dict:
    """
    Plain helper — NOT a fixture.
    Call directly in tests: user = register_and_login(client, 'x@uni.edu')
    Accessible because pytest.ini sets pythonpath = tests .
    """
    client.post("/register", json={
        "full_name": "Test Professor",
        "email": email,
        "password": password
    })
    resp = client.post("/login", json={"email": email, "password": password})
    assert resp.status_code == 200, f"Login failed: {resp.text}"
    return resp.json()["user"]
