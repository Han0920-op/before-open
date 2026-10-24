import asyncio
import copy
import json
from collections.abc import AsyncIterator, Callable
from dataclasses import replace
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.main import create_app
from app.models.entities import ExperimentTask, Observation, SceneVersion, SimulationRun

from .conftest import DatabaseCase
from .test_business_api import observation_body, post, setup_scene


def test_no_database_health_is_not_readiness() -> None:
    with TestClient(create_app(Settings())) as client:
        assert client.get("/api/v1/health").status_code == 200
        ready = client.get("/api/v1/ready")
        assert ready.status_code == 503
        assert ready.json()["error"]["code"] == "DATABASE_UNAVAILABLE"


def test_secure_defaults_and_origin_configuration() -> None:
    assert Settings().cookie_secure
    assert "test-private-password" not in repr(Settings(database_url="test-private-password"))
    with pytest.raises(ValueError):
        Settings(allowed_origins=("*",))


def test_openapi_artifact_matches_generated_contract() -> None:
    path = Path(__file__).resolve().parents[3] / "docs" / "openapi.json"
    assert json.loads(path.read_text()) == create_app(Settings()).openapi()


def test_slow_request_body_times_out_before_any_write() -> None:
    async def run() -> None:
        async def body() -> AsyncIterator[bytes]:
            yield b"{"
            await asyncio.sleep(0.1)
            yield b"}"

        app = create_app(Settings(body_timeout=0.01))
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            response = await client.post("/api/v1/projects", content=body())
            assert response.status_code == 408
            assert response.json()["error"]["code"] == "REQUEST_TIMEOUT"

    asyncio.run(run())


def test_cors_secure_cookie_and_session_refresh(database: DatabaseCase) -> None:
    app = create_app(replace(database.settings, cookie_secure=True))
    with TestClient(app, base_url="https://testserver") as client:
        first = client.get("/api/v1/session")
        assert "Secure" in first.headers["set-cookie"]
        csrf = first.json()["data"]["csrf_token"]
        assert client.get("/api/v1/session").json()["data"]["csrf_token"] == csrf
        response = client.options(
            "/api/v1/projects",
            headers={
                "Origin": "https://frontend.example",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "X-CSRF-Token, Idempotency-Key",
            },
        )
        assert response.status_code == 200
        assert response.headers["Access-Control-Allow-Origin"] == "https://frontend.example"
        assert response.headers["Access-Control-Allow-Credentials"] == "true"
        assert "X-Request-ID" in response.headers
        denied = client.options(
            "/api/v1/projects",
            headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "POST"},
        )
        assert denied.status_code == 400
        assert "Access-Control-Allow-Origin" not in denied.headers
    app.state.engine.dispose()


def test_database_parent_and_task_must_belong_to_same_project(
    client: TestClient,
    database: DatabaseCase,
    scene_data: Callable[[str], dict[str, Any]],
) -> None:
    raw = scene_data("retail_perishable")
    first, parent = setup_scene(client, raw)
    second, _ = setup_scene(client, raw)
    with pytest.raises(IntegrityError), Session(database.engine) as db, db.begin():
        db.add(
            SceneVersion(
                project_id=second,
                parent_version_id=parent,
                schema_version="1.0",
                business_type="retail_perishable",
                scene_spec_json=raw,
            )
        )
        db.flush()
    with pytest.raises(IntegrityError), Session(database.engine) as db, db.begin():
        db.add(
            ExperimentTask(
                project_id=second,
                scene_version_id=parent,
                question="x",
                method_json={"description": "x"},
                warnings_json=[],
            )
        )
        db.flush()
    assert client.get(f"/api/v1/projects/{first}").status_code == 200


def test_saved_simulations_and_observations_cannot_be_deleted(
    client: TestClient,
    database: DatabaseCase,
    scene_data: Callable[[str], dict[str, Any]],
) -> None:
    project, version = setup_scene(client, scene_data("retail_perishable"))
    run = post(client, f"/scene-versions/{version}/simulate", {"scenario_label": "low"})
    task = post(
        client,
        f"/projects/{project}/experiments",
        {"scene_version_id": version, "question": "价格观察", "method": "经同意后询问"},
    )
    observation = post(client, f"/experiments/{task['id']}/observations", observation_body())
    for model, key in [(SimulationRun, run["id"]), (Observation, observation["id"])]:
        with pytest.raises(IntegrityError), database.engine.begin() as connection:
            connection.execute(delete(model).where(model.id == key))
    with Session(database.engine) as db:
        assert db.scalar(select(Observation).where(Observation.id == observation["id"])) is not None


def test_compare_different_projects_and_models_rejected(
    client: TestClient,
    scene_data: Callable[[str], dict[str, Any]],
) -> None:
    raw = scene_data("retail_perishable")
    first, a = setup_scene(client, raw)
    _, b = setup_scene(client, raw)
    body = {
        "left_version_id": a,
        "right_version_id": b,
        "left_scenario_label": "low",
        "right_scenario_label": "low",
    }
    mismatch = client.post(f"/api/v1/projects/{first}/compare", json=body)
    assert mismatch.status_code == 422
    assert mismatch.json()["error"]["code"] == "PROJECT_MISMATCH"
    service = scene_data("appointment_service")
    service["original_idea"] = raw["original_idea"]
    other = post(client, f"/projects/{first}/scene-confirm", {"scene": service, "confirmed": True})
    body["right_version_id"] = other["id"]
    body["right_scenario_label"] = "base"
    mismatch = client.post(f"/api/v1/projects/{first}/compare", json=body)
    assert mismatch.status_code == 422
    assert mismatch.json()["error"]["code"] == "INCOMPATIBLE_MODELS"


def test_incomplete_version_can_be_saved_but_not_simulated(
    client: TestClient,
    scene_data: Callable[[str], dict[str, Any]],
) -> None:
    raw = copy.deepcopy(scene_data("retail_perishable"))
    raw["fields"]["unit_cost_cents"] = {"value": None, "source": "unknown"}
    _, version = setup_scene(client, raw)
    response = client.post(
        f"/api/v1/scene-versions/{version}/simulate",
        json={"scenario_label": "low"},
        headers={"Idempotency-Key": "not-ready"},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "SIMULATION_NOT_READY"
    assert client.get(f"/api/v1/scene-versions/{version}/simulations").json()["data"] == []
