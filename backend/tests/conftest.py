import os
import tempfile

os.environ.setdefault(
    "DATABASE_URL", "sqlite:///" + os.path.join(tempfile.gettempdir(), "ov_rootcause_test.db")
)

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.clearing_codes import sync_clearing_codes  # noqa: E402
from app.db import SessionLocal, engine, get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Base  # noqa: E402


@pytest.fixture()
def db():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    session = SessionLocal()
    sync_clearing_codes(session)
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def client(db):
    def _get_db():
        yield db

    app.dependency_overrides[get_db] = _get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
