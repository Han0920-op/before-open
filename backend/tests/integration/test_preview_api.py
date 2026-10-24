from collections.abc import Callable
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.entities import IdempotencyRecord, SceneVersion, SimulationRun

from .conftest import DatabaseCase
from .test_business_api import setup_scene


@pytest.mark.parametrize(
    "kind,label,metric,result",
    [
        ("retail_perishable", "low", "result_cents", -11700),
        ("retail_durable", "base", "cash_change_cents", -5000),
        ("appointment_service", "base", "simplified_result_cents", 32000),
    ],
)
def test_preview_has_no_version_claim_or_database_writes(
    client: TestClient,
    database: DatabaseCase,
    scene_data: Callable[[str], dict[str, Any]],
    kind: str,
    label: str,
    metric: str,
    result: int,
) -> None:
    raw = scene_data(kind)
    project, version = setup_scene(client, raw)
    with Session(database.engine) as db:
        keys = db.scalar(select(func.count()).select_from(IdempotencyRecord))
    for _ in range(3):
        response = client.post(
            f"/api/v1/projects/{project}/preview", json={"scene": raw, "scenario_label": label}
        )
        assert response.status_code == 200
        data = response.json()["data"]
        assert "scene_version_id" not in data
        assert data["result"][metric] == result
        assert data["input_snapshot"]["original_idea"] == raw["original_idea"]
    with Session(database.engine) as db:
        assert db.scalar(select(func.count()).select_from(SceneVersion)) == 1
        assert db.scalar(select(func.count()).select_from(SimulationRun)) == 0
        assert db.scalar(select(func.count()).select_from(IdempotencyRecord)) == keys
        assert db.get(SceneVersion, version) is not None


def test_preview_enforces_ownership_csrf_and_source(
    client: TestClient,
    api: FastAPI,
    scene_data: Callable[[str], dict[str, Any]],
) -> None:
    raw = scene_data("retail_perishable")
    project, _ = setup_scene(client, raw)
    with TestClient(api) as other:
        csrf = other.get("/api/v1/session").json()["data"]["csrf_token"]
        assert (
            other.post(
                f"/api/v1/projects/{project}/preview", json={"scene": raw, "scenario_label": "low"}
            ).status_code
            == 403
        )
        assert (
            other.post(
                f"/api/v1/projects/{project}/preview",
                json={"scene": raw, "scenario_label": "low"},
                headers={"X-CSRF-Token": csrf},
            ).status_code
            == 404
        )
    raw["fields"]["unit_price_cents"] = {
        "value": 900,
        "source": "derived",
        "derived_from": ["fake"],
    }
    rejected = client.post(
        f"/api/v1/projects/{project}/preview", json={"scene": raw, "scenario_label": "low"}
    )
    assert rejected.status_code == 422 and rejected.json()["error"]["code"] == "SOURCE_FORBIDDEN"


def test_preview_keeps_unknowns_uncomputed(
    client: TestClient,
    scene_data: Callable[[str], dict[str, Any]],
) -> None:
    raw = scene_data("retail_perishable")
    project, _ = setup_scene(client, raw)
    raw["fields"]["unit_cost_cents"] = {"value": None, "source": "unknown"}
    response = client.post(
        f"/api/v1/projects/{project}/preview", json={"scene": raw, "scenario_label": "low"}
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "SIMULATION_NOT_READY"
