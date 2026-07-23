"""Test fixtures. DEMO_MODE is forced before any app import so the whole
suite runs offline — mock Zendesk, deterministic keyword extraction."""
import os

os.environ["DEMO_MODE"] = "true"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


@pytest.fixture()
def client():
    from app import state
    from app.main import app
    from app.security import limiter

    state.reset_all()
    limiter._buckets.clear()
    with TestClient(app) as c:
        yield c
    state.reset_all()
    limiter._buckets.clear()
