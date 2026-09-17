"""
Test DB is SQLite in-memory, set before any app module is imported (app.db.session reads
DATABASE_URL once at import time). Tasks are exercised via Celery's `.apply()`, which always
runs a task synchronously in-process (no broker needed) - equivalent to task_always_eager for
a single call, without wiring a whole Celery test app.
"""
import os
import tempfile

# A file-backed SQLite DB (not `sqlite://` in-memory) so every thread's connection sees the
# same data - FastAPI runs sync endpoints in a worker thread, and in-memory SQLite is
# per-connection, so the API thread would otherwise see an empty, unrelated database.
_DB_PATH = os.path.join(tempfile.gettempdir(), "payment_gateway_test.db")
if os.path.exists(_DB_PATH):
    os.remove(_DB_PATH)
os.environ.setdefault("DATABASE_URL", f"sqlite:///{_DB_PATH}")
os.environ.setdefault("CELERY_BROKER_URL", "memory://")
os.environ.setdefault("CELERY_RESULT_BACKEND", "cache+memory://")

import pytest
from fastapi.testclient import TestClient

from app.db.base import Base
from app.db.session import SessionLocal, engine
from app.models.payments import Merchant


@pytest.fixture()
def db():
    Base.metadata.create_all(engine)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)


@pytest.fixture()
def merchant(db):
    m = Merchant(name="Test Merchant")
    db.add(m)
    db.commit()
    return m


@pytest.fixture()
def client(db, monkeypatch):
    # API tests exercise request handling + DB writes only - the actual task bodies are
    # covered directly (see test_*_task.py), so the .delay()/pipeline calls are stubbed out
    # here to avoid needing a real broker connection.
    import app.api.payments as payments_api
    import app.api.refunds as refunds_api

    monkeypatch.setattr(payments_api, "payment_pipeline", lambda payment_id: None)
    monkeypatch.setattr(refunds_api.process_refund, "delay", lambda refund_id: None)

    from app.main import app as fastapi_app
    return TestClient(fastapi_app)
