from fastapi.testclient import TestClient

from app.main import app


def test_health_response_shape():
    client = TestClient(app)
    response = client.get("/api/v1/health")

    assert response.status_code == 200
    body = response.json()
    assert body["schema_version"] == "1.0"
    assert body["data"]["status"] == "ok"
    assert body["error"] is None
