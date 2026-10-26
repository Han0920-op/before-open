from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.agent.model import AgentFailure, SharedModelBudget
from app.main import create_app
from app.models.entities import ProcessStep
from app.simulation.process import ledger, profile_for
from app.simulation.runner import simulate
from tests.integration.conftest import DatabaseCase
from tests.integration.test_business_api import setup_scene


def post(client: TestClient, path: str, body: object, key: str | None = None) -> dict[str, Any]:
    response = client.post(
        "/api/v1" + path, json=body, headers={"Idempotency-Key": key or str(uuid4())}
    )
    assert response.status_code in (200, 201), response.text
    result: dict[str, Any] = response.json()["data"]
    return result


@pytest.mark.parametrize("demand", [0, 1, 2, 12, 45, 1000000])
@pytest.mark.parametrize("stock", [0, 1, 30])
def test_process_conserves_and_reconciles(
    scene_data: Callable[[str], dict[str, Any]], demand: int, stock: int
) -> None:
    raw = scene_data("retail_perishable")
    raw["fields"]["stock_qty"]["value"] = stock
    raw["demand_scenarios"][0]["demand_qty"]["value"] = demand
    snapshot = simulate(
        raw, scene_version_id="test", scenario_label="low", calculated_at=datetime.now(UTC)
    )
    profile = profile_for(snapshot)
    assert sum(profile.demand_by_stage) == demand
    rows = ledger(snapshot, 3)
    assert sum(row.sold for row in rows) == min(stock, demand)
    assert rows[-1].after.remaining_stock + rows[-1].after.sold == stock
    assert sum(row.cash_out_cents for row in rows) == rows[-1].after.cash_out_cents
    assert sum(row.revenue_cents for row in rows) == rows[-1].after.revenue_cents
    for i in range(4):
        assert ledger(snapshot, i) == rows[: i + 1]


def start(
    client: TestClient, scene_data: Callable[[str], dict[str, Any]]
) -> tuple[str, dict[str, Any]]:
    _, version = setup_scene(client, scene_data("retail_perishable"))
    result = post(
        client,
        f"/scene-versions/{version}/process-runs",
        {"scenario_label": "low", "confirmed": True},
        "create-process",
    )
    return version, result


def test_complete_reload_and_fast_forward(
    client: TestClient, database: DatabaseCase, scene_data: Callable[[str], dict[str, Any]]
) -> None:
    version, run = start(client, scene_data)
    assert run["profile"]["demand_by_stage"] == [4, 4, 4]
    assert run["state"]["sold"] == 0 and run["calculation"] is None
    assert run["state"]["cash_out_cents"] == 22500
    run = post(client, f"/process-runs/{run['id']}/advance", {"expected_revision": 0})
    assert run["state"]["sold"] == 4 and run["state"]["remaining_stock"] == 26
    app = create_app(database.settings)
    try:
        with TestClient(app, cookies=client.cookies) as reopened:
            response = reopened.get(f"/api/v1/scene-versions/{version}/process-runs")
            assert response.json()["data"] == [run]
    finally:
        app.state.engine.dispose()
    run = post(
        client, f"/process-runs/{run['id']}/advance", {"expected_revision": 1, "action": "finish"}
    )
    assert len(run["steps"]) == 4 and run["status"] == "completed"
    assert run["calculation"]["result"]["result_cents"] == -11700
    assert run["state"]["remaining_stock"] == 18
    assert run["state"]["budget_balance_cents"] is None


def test_replay_conflict_and_confirmation(
    client: TestClient, scene_data: Callable[[str], dict[str, Any]]
) -> None:
    version, run = start(client, scene_data)
    same = post(
        client,
        f"/scene-versions/{version}/process-runs",
        {"scenario_label": "low", "confirmed": True},
        "create-process",
    )
    assert same == run
    path = f"/process-runs/{run['id']}/advance"
    body = {"expected_revision": 0, "action": "next"}
    first = post(client, path, body, "advance")
    assert post(client, path, body, "advance") == first
    conflict = client.post("/api/v1" + path, json=body, headers={"Idempotency-Key": "other"})
    assert conflict.status_code == 409
    assert len(client.get("/api/v1" + path.removesuffix("/advance")).json()["data"]["steps"]) == 2
    for value in (False, 1, "true"):
        response = client.post(
            f"/api/v1/scene-versions/{version}/process-runs",
            json={"scenario_label": "low", "confirmed": value},
            headers={"Idempotency-Key": str(uuid4())},
        )
        assert response.status_code == 422
    response = client.post(
        "/api/v1" + path, json={"expected_revision": True}, headers={"Idempotency-Key": "bool"}
    )
    assert response.status_code == 422


def test_ownership_and_step_immutability(
    client: TestClient,
    api: FastAPI,
    database: DatabaseCase,
    scene_data: Callable[[str], dict[str, Any]],
) -> None:
    version, run = start(client, scene_data)
    with TestClient(api) as other:
        csrf = other.get("/api/v1/session").json()["data"]["csrf_token"]
        other.headers["X-CSRF-Token"] = csrf
        assert other.get(f"/api/v1/process-runs/{run['id']}").status_code == 404
        assert other.get(f"/api/v1/scene-versions/{version}/process-runs").status_code == 404
        assert (
            other.post(
                f"/api/v1/process-runs/{run['id']}/advance",
                json={"expected_revision": 0},
                headers={"Idempotency-Key": "cross"},
            ).status_code
            == 404
        )
    with Session(database.engine) as db:
        row = db.scalar(select(ProcessStep).where(ProcessStep.process_run_id == run["id"]))
        assert row is not None
        with pytest.raises(IntegrityError):
            db.execute(text("UPDATE process_steps SET sequence = 3 WHERE id = :id"), {"id": row.id})
            db.commit()
        db.rollback()


def test_concurrent_steps_are_not_double_charged(
    client: TestClient, api: FastAPI, scene_data: Callable[[str], dict[str, Any]]
) -> None:
    _, run = start(client, scene_data)
    cookie, csrf = client.cookies, client.headers["X-CSRF-Token"]

    def advance(index: int) -> int:
        with TestClient(api, cookies=cookie) as instance:
            return instance.post(
                f"/api/v1/process-runs/{run['id']}/advance",
                json={"expected_revision": 0},
                headers={"X-CSRF-Token": csrf, "Idempotency-Key": f"concurrent-{index}"},
            ).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(advance, range(2))) == [200, 409]
    current = client.get(f"/api/v1/process-runs/{run['id']}").json()["data"]
    assert current["state"]["sold"] == 4 and len(current["steps"]) == 2


def test_other_scene_types_remain_usable(
    client: TestClient, scene_data: Callable[[str], dict[str, Any]]
) -> None:
    for kind in ("retail_durable", "appointment_service"):
        _, version = setup_scene(client, scene_data(kind))
        response = client.post(
            f"/api/v1/scene-versions/{version}/process-runs",
            json={"scenario_label": "base", "confirmed": True},
            headers={"Idempotency-Key": str(uuid4())},
        )
        assert response.status_code == 422
        assert post(client, f"/scene-versions/{version}/simulate", {"scenario_label": "base"})


def test_shared_model_ceiling_is_atomic_and_bounded() -> None:
    budget = SharedModelBudget(3)

    def reserve(_: int) -> bool:
        try:
            budget.reserve("test")
            return True
        except AgentFailure as error:
            assert error.code == "SHARED_MODEL_LIMIT"
            return False

    with ThreadPoolExecutor(max_workers=6) as pool:
        assert sum(pool.map(reserve, range(20))) == 3
    assert not budget.available()
    with pytest.raises(AgentFailure, match="MODEL_INPUT_LIMIT"):
        SharedModelBudget(1).reserve("x" * 24001)


def test_assistant_status_exposes_no_configuration(client: TestClient, api: FastAPI) -> None:
    from dataclasses import replace

    response = client.get("/api/v1/assistant-status").json()["data"]
    assert not response["available"]
    api.state.settings = replace(
        api.state.settings,
        llm_enabled=True,
        llm_key="fixture-server-secret",
        llm_model="fixture-model",
    )
    status = client.get("/api/v1/assistant-status")
    assert status.json()["data"]["available"]
    assert "fixture" not in status.text and "api_key" not in status.text
    api.state.shared_model_budget = SharedModelBudget(0)
    assert not client.get("/api/v1/assistant-status").json()["data"]["available"]
