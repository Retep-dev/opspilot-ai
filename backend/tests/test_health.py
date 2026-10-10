from fastapi.testclient import TestClient

from app.main import app


def test_health() -> None:
    assert TestClient(app).get("/health").json() == {"status": "ok"}


def test_readiness_fails_closed_without_configuration() -> None:
    with TestClient(app) as client:
        assert client.get("/ready").status_code == 503
