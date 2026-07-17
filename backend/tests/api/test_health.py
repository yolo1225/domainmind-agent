from fastapi.testclient import TestClient

from app.main import app
from app.core.config import settings


def test_health_response_shape():
    client = TestClient(app)
    response = client.get("/api/v1/health")

    assert response.status_code == 200
    body = response.json()
    assert body["schema_version"] == "1.0"
    assert body["data"]["status"] == "ok"
    assert body["error"] is None


def test_dependency_health_hides_key_and_reports_model_readiness(monkeypatch):
    monkeypatch.setattr("app.api.v1.health.check_database_connection", lambda: {"status": "ok"})
    monkeypatch.setattr(
        "app.api.v1.health.get_vector_store",
        lambda: type("Store", (), {"health_check": lambda self: {"status": "ok"}})(),
    )
    monkeypatch.setattr(settings, "openai_api_key", "secret-key")
    monkeypatch.setattr(settings, "primary_llm_model", "generation-model")
    monkeypatch.setattr(settings, "primary_review_model", "review-model-a")
    monkeypatch.setattr(settings, "secondary_review_model", "review-model-b")
    monkeypatch.setattr(settings, "allow_fixture_llm", False)

    response = TestClient(app).get("/api/v1/health/dependencies")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["ready_for_live_demo"] is True
    assert data["review_models_distinct"] is True
    assert "secret-key" not in response.text
