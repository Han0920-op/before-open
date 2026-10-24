import copy
import json
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from threading import Barrier
from typing import Any
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import func, inspect, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import DomainError
from app.main import create_app
from app.models.entities import (
    AgentRun,
    AnonymousSession,
    IdempotencyRecord,
    Project,
    SceneVersion,
    SimulationRun,
    ToolInvocation,
)
from app.schemas.simulation import SimulationSnapshot
from app.services import business
from app.simulation.runner import replay_snapshot

from .conftest import DatabaseCase


def post(client: TestClient, path: str, body: object, key: str | None = None) -> dict[str, Any]:
    response = client.post(
        "/api/v1" + path, json=body, headers={"Idempotency-Key": key or str(uuid4())}
    )
    assert response.status_code == 201, response.text
    assert response.json()["request_id"] == response.headers["X-Request-ID"]
    result: dict[str, Any] = response.json()["data"]
    return result


def setup_scene(client: TestClient, raw: dict[str, Any]) -> tuple[str, str]:
    project = post(
        client, "/projects", {"title": raw["title"], "original_idea": raw["original_idea"]}
    )
    version = post(
        client, f"/projects/{project['id']}/scene-confirm", {"scene": raw, "confirmed": True}
    )
    return project["id"], version["id"]


@pytest.mark.parametrize(
    "kind,label,metric,result",
    [
        ("retail_perishable", "low", "result_cents", -11700),
        ("retail_durable", "base", "cash_change_cents", -5000),
        ("appointment_service", "base", "simplified_result_cents", 32000),
    ],
)
def test_persist_and_reopen(
    client: TestClient,
    database: DatabaseCase,
    scene_data: Callable[[str], dict[str, Any]],
    kind: str,
    label: str,
    metric: str,
    result: int,
) -> None:
    project_id, version_id = setup_scene(client, scene_data(kind))
    first = post(
        client, f"/scene-versions/{version_id}/simulate", {"scenario_label": label}, "run-key"
    )
    again = post(
        client, f"/scene-versions/{version_id}/simulate", {"scenario_label": label}, "run-key"
    )
    assert again == first
    assert first["snapshot"]["result"][metric] == result
    assert replay_snapshot(SimulationSnapshot.model_validate(first["snapshot"]))
    other_app = create_app(database.settings)
    with TestClient(other_app, cookies=client.cookies) as reopened:
        detail = reopened.get(f"/api/v1/projects/{project_id}").json()["data"]
        assert detail["latest_version_id"] == version_id
        saved = reopened.get(f"/api/v1/simulation-runs/{first['id']}")
        assert saved.status_code == 200 and saved.json()["data"] == first
        assert (
            len(reopened.get(f"/api/v1/scene-versions/{version_id}/simulations").json()["data"])
            == 1
        )
    other_app.state.engine.dispose()


def test_branch_compare_and_parent_immutable(
    client: TestClient,
    scene_data: Callable[[str], dict[str, Any]],
) -> None:
    raw = scene_data("retail_perishable")
    project_id, parent = setup_scene(client, raw)
    branch = copy.deepcopy(raw)
    branch["fields"]["stock_qty"]["value"] = 10
    child = post(
        client, f"/scene-versions/{parent}/branches", {"scene": branch, "confirmed": True}, "branch"
    )
    assert child["parent_version_id"] == parent
    assert (
        client.get(f"/api/v1/scene-versions/{parent}").json()["data"]["scene"]["fields"][
            "stock_qty"
        ]["value"]
        == 30
    )
    body = {
        "left_version_id": parent,
        "right_version_id": child["id"],
        "left_scenario_label": "low",
        "right_scenario_label": "low",
    }
    compared = client.post(f"/api/v1/projects/{project_id}/compare", json=body)
    assert compared.status_code == 200
    data = compared.json()["data"]
    assert data["same_demand_assumption"] and data["same_period"]
    assert not data["same_calculation_inputs"]
    assert any(c["path"] == "fields.stock_qty.value" for c in data["changed_fields"])
    assert data["result_deltas"]["result_cents"] == 5200
    assert "fields.fixed_cost_cents.value" in data["unchanged_fields"]
    body["right_scenario_label"] = "high"
    assert not client.post(f"/api/v1/projects/{project_id}/compare", json=body).json()["data"][
        "same_demand_assumption"
    ]


def test_all_resource_ownership(
    client: TestClient,
    api: FastAPI,
    scene_data: Callable[[str], dict[str, Any]],
) -> None:
    project, version = setup_scene(client, scene_data("retail_perishable"))
    run = post(client, f"/scene-versions/{version}/simulate", {"scenario_label": "low"})
    task = post(
        client,
        f"/projects/{project}/experiments",
        {"scene_version_id": version, "question": "问什么价格？", "method": "征得同意后询问"},
    )
    with TestClient(api) as stranger:
        csrf = stranger.get("/api/v1/session").json()["data"]["csrf_token"]
        stranger.headers["X-CSRF-Token"] = csrf
        assert stranger.get("/api/v1/projects").json()["data"] == []
        for path in [
            f"/projects/{project}",
            f"/projects/{project}/summary",
            f"/scene-versions/{version}",
            f"/scene-versions/{version}/simulations",
            f"/simulation-runs/{run['id']}",
            f"/experiments/{task['id']}",
            f"/projects/{project}/agent-runs/{uuid4()}",
        ]:
            assert stranger.get("/api/v1" + path).status_code == 404
        for path, body in [
            (
                f"/projects/{project}/scene-confirm",
                {"scene": scene_data("retail_perishable"), "confirmed": True},
            ),
            (
                f"/scene-versions/{version}/branches",
                {"scene": scene_data("retail_perishable"), "confirmed": True},
            ),
            (f"/scene-versions/{version}/simulate", {"scenario_label": "low"}),
            (f"/experiments/{task['id']}/observations", observation_body()),
        ]:
            assert (
                stranger.post(
                    "/api/v1" + path, json=body, headers={"Idempotency-Key": str(uuid4())}
                ).status_code
                == 404
            )


def observation_body() -> dict[str, Any]:
    return {
        "recorded_at": "2026-10-24T12:00:00Z",
        "sample_size": 3,
        "notes": "小样本自报，不是真实核验",
        "limitations": "非随机样本，不能代表市场",
        "observed_values": {"unit_price_cents": {"value": 900, "unit": "cents"}},
    }


def test_observation_references_and_summary(
    client: TestClient,
    scene_data: Callable[[str], dict[str, Any]],
) -> None:
    raw = scene_data("retail_perishable")
    project, version = setup_scene(client, raw)
    task = post(
        client,
        f"/projects/{project}/experiments",
        {"scene_version_id": version, "question": "接受的价格？", "method": "当面询问，不记录身份"},
    )
    observation = post(client, f"/experiments/{task['id']}/observations", observation_body(), "obs")
    assert observation["provenance"] == "user_observation"
    observed_scene = copy.deepcopy(raw)
    observed_scene["fields"]["unit_price_cents"] = {
        "value": 900,
        "source": "user_observation",
        "observation_id": observation["id"],
    }
    post(
        client, f"/scene-versions/{version}/branches", {"scene": observed_scene, "confirmed": True}
    )
    observed_scene["fields"]["unit_price_cents"]["value"] = 1000
    response = client.post(
        f"/api/v1/scene-versions/{version}/branches",
        json={"scene": observed_scene, "confirmed": True},
        headers={"Idempotency-Key": "wrong-value"},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "OBSERVATION_MISMATCH"
    other, other_version = setup_scene(client, raw)
    observed_scene["fields"]["unit_price_cents"]["value"] = 900
    assert (
        client.post(
            f"/api/v1/scene-versions/{other_version}/branches",
            json={"scene": observed_scene, "confirmed": True},
            headers={"Idempotency-Key": "foreign-observation"},
        ).status_code
        == 422
    )
    summary = client.get(f"/api/v1/projects/{project}/summary")
    assert summary.status_code == 200
    assert len(summary.json()["data"]["observations"]) == 1
    assert len(summary.json()["data"]["versions"]) == 2


@pytest.mark.parametrize("change", ["verified", "derived", "original", "false", "numeric_true"])
def test_confirmation_and_source_guards(
    client: TestClient,
    scene_data: Callable[[str], dict[str, Any]],
    change: str,
) -> None:
    raw = scene_data("retail_perishable")
    project, _ = setup_scene(client, raw)
    confirmed: Any = True
    if change == "verified":
        raw["fields"]["unit_price_cents"] = {
            "value": 900,
            "source": "verified_external",
            "evidence": {
                "source_url": "https://example.com",
                "observed_at": "2026-10-24T00:00:00Z",
                "scope": "untrusted claim",
            },
        }
    elif change == "derived":
        raw["fields"]["unit_price_cents"] = {
            "value": 900,
            "source": "derived",
            "derived_from": ["x"],
        }
    elif change == "original":
        raw["original_idea"] = "changed intent"
    elif change == "false":
        confirmed = False
    else:
        confirmed = 1
    response = client.post(
        f"/api/v1/projects/{project}/scene-confirm",
        json={"scene": raw, "confirmed": confirmed},
        headers={"Idempotency-Key": "invalid-confirm"},
    )
    assert response.status_code == 422
    assert len(client.get(f"/api/v1/projects/{project}").json()["data"]["versions"]) == 1


def test_failed_transaction_removes_idempotency_claim(
    client: TestClient,
    database: DatabaseCase,
    scene_data: Callable[[str], dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw = scene_data("retail_perishable")
    _, version = setup_scene(client, raw)
    original = business.create_run

    def fail(db: Session, row: SceneVersion, label: str) -> Any:
        original(db, row, label)
        raise DomainError(422, "TEST_FAILURE", "验证回滚")

    monkeypatch.setattr(business, "create_run", fail)
    response = client.post(
        f"/api/v1/scene-versions/{version}/simulate",
        json={"scenario_label": "low"},
        headers={"Idempotency-Key": "rollback-key"},
    )
    assert response.status_code == 422
    with Session(database.engine) as db:
        assert db.scalar(select(func.count()).select_from(SimulationRun)) == 0
        assert (
            db.scalar(
                select(func.count())
                .select_from(IdempotencyRecord)
                .where(IdempotencyRecord.key == "rollback-key")
            )
            == 0
        )
    monkeypatch.setattr(business, "create_run", original)
    post(client, f"/scene-versions/{version}/simulate", {"scenario_label": "low"}, "rollback-key")


def test_concurrent_idempotency_and_conflicts(
    client: TestClient,
    api: FastAPI,
    database: DatabaseCase,
    scene_data: Callable[[str], dict[str, Any]],
) -> None:
    raw = scene_data("retail_perishable")
    project, parent = setup_scene(client, raw)
    raw["fields"]["stock_qty"]["value"] = 10
    barrier = Barrier(4)

    def send(_: int) -> tuple[int, str]:
        with TestClient(api, cookies=client.cookies) as worker:
            barrier.wait(timeout=10)
            response = worker.post(
                f"/api/v1/scene-versions/{parent}/branches",
                json={"scene": raw, "confirmed": True},
                headers={
                    "X-CSRF-Token": client.headers["X-CSRF-Token"],
                    "Idempotency-Key": "parallel",
                },
            )
            return response.status_code, response.text

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(send, range(4)))
    assert all(status == 201 for status, _ in results), results
    assert len({json.loads(body)["data"]["id"] for _, body in results}) == 1
    assert len(client.get(f"/api/v1/projects/{project}").json()["data"]["versions"]) == 2
    raw["fields"]["stock_qty"]["value"] = 11
    conflict = client.post(
        f"/api/v1/scene-versions/{parent}/branches",
        json={"scene": raw, "confirmed": True},
        headers={"Idempotency-Key": "parallel"},
    )
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"


def test_database_immutability_and_migration_cycle(
    client: TestClient,
    database: DatabaseCase,
    scene_data: Callable[[str], dict[str, Any]],
) -> None:
    project, version = setup_scene(client, scene_data("retail_perishable"))
    with pytest.raises(IntegrityError), database.engine.begin() as connection:
        connection.execute(
            update(SceneVersion).where(SceneVersion.id == version).values(business_type="x")
        )
    with pytest.raises(IntegrityError), database.engine.begin() as connection:
        connection.execute(update(Project).where(Project.id == project).values(original_idea="x"))
    assert client.get(f"/api/v1/projects/{project}").status_code == 200
    # Only destroy this test's unique schema/file; never the actual development database.
    database.migrate("base", downgrade=True)
    assert "projects" not in inspect(database.engine).get_table_names()
    database.migrate("head")
    assert "projects" in inspect(database.engine).get_table_names()


def test_sessions_csrf_expiry_and_cookies(
    client: TestClient, api: FastAPI, database: DatabaseCase
) -> None:
    with TestClient(api) as anonymous:
        assert anonymous.get("/api/v1/projects").status_code == 401
        bootstrap = anonymous.get("/api/v1/session")
        assert "HttpOnly" in bootstrap.headers["set-cookie"]
        assert "SameSite=lax" in bootstrap.headers["set-cookie"]
        assert (
            anonymous.post(
                "/api/v1/projects",
                json={"title": "x", "original_idea": "x"},
                headers={"Idempotency-Key": "no-csrf"},
            ).status_code
            == 403
        )
        anonymous.cookies.set("before_open_session", "invalid", domain="testserver.local", path="/")
        assert anonymous.get("/api/v1/session").status_code == 401
    with Session(database.engine) as db, db.begin():
        db.execute(
            update(AnonymousSession).values(expires_at=datetime.now(UTC) - timedelta(days=1))
        )
    assert client.get("/api/v1/projects").status_code == 401


def test_origin_body_limit_rate_and_error_envelopes(database: DatabaseCase) -> None:
    app = create_app(replace(database.settings, body_limit=500, rate_limit=6))
    with TestClient(app) as client:
        response = client.get("/api/v1/session")
        csrf = response.json()["data"]["csrf_token"]
        client.headers["X-CSRF-Token"] = csrf
        assert (
            client.post(
                "/api/v1/projects",
                json={"title": "x", "original_idea": "x"},
                headers={"Origin": "https://evil.example", "Idempotency-Key": "origin"},
            ).status_code
            == 403
        )
        assert client.post("/api/v1/projects", content=b"x" * 501).status_code == 413
        missing = client.get("/missing")
        assert missing.status_code == 404
        assert missing.json()["request_id"] == missing.headers["X-Request-ID"]
        invalid = client.post("/api/v1/projects", json={"unexpected": "private-input"})
        assert invalid.status_code == 422 and "private-input" not in invalid.text
        assert client.get("/api/v1/health").status_code == 200
        assert client.get("/api/v1/health").status_code == 429
    app.state.engine.dispose()


def test_agent_storage_has_no_fabricated_execution(
    client: TestClient,
    database: DatabaseCase,
    scene_data: Callable[[str], dict[str, Any]],
) -> None:
    project, _ = setup_scene(client, scene_data("retail_perishable"))
    assert client.get(f"/api/v1/projects/{project}/agent-runs/{uuid4()}").status_code == 404
    with Session(database.engine) as db, db.begin():
        run = AgentRun(
            project_id=project,
            thread_id="test-only",
            stage="run_tools",
            status="completed",
            total_steps=1,
        )
        db.add(run)
        db.flush()
        run_id = run.id
        db.add(
            ToolInvocation(
                agent_run_id=run_id,
                tool_name="test_only",
                input_summary_json={},
                output_summary_json={},
                status="completed",
                duration_ms=1,
            )
        )
    response = client.get(f"/api/v1/projects/{project}/agent-runs/{run_id}")
    assert response.status_code == 200
    assert response.json()["data"]["tools"][0]["tool_name"] == "test_only"
