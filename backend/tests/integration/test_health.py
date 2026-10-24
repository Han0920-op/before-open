from uuid import UUID

from fastapi.testclient import TestClient

from app.main import app


def test_health_contract() -> None:
    with TestClient(app) as client:
        first = client.get("/api/v1/health")
        second = client.get("/api/v1/health")
    assert first.status_code == 200
    assert first.json()["status"] == "ok"
    assert UUID(first.json()["request_id"])
    assert first.json()["request_id"] != second.json()["request_id"]


def test_openapi_exposes_health_contract() -> None:
    with TestClient(app) as client:
        response = client.get("/openapi.json")
    assert response.status_code == 200
    schema = response.json()
    operation = schema["paths"]["/api/v1/health"]["get"]
    assert operation["responses"]["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/HealthResponse"
    }
    assert set(schema["components"]["schemas"]["HealthResponse"]["required"]) == {
        "status",
        "request_id",
    }
