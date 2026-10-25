from dataclasses import replace
from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.agent.contracts import Extraction, NumberFact, ToolPlan
from app.agent.model import AgentFailure, LangChainModel, ModelConnections
from app.agent.scenes import grounded
from app.core.config import Settings
from app.main import create_app
from app.models.entities import (
    AgentCheckpoint,
    AgentRun,
    SceneVersion,
    SimulationRun,
)
from tests.agent_cases.test_workflow import ScriptModel, agent_post
from tests.integration.conftest import DatabaseCase
from tests.integration.test_business_api import post


def project(client: TestClient) -> str:
    return str(
        post(
            client,
            "/projects",
            {"title": "测试", "original_idea": "我想卖冰粉，预算500元，备货200份。"},
        )["id"]
    )


def ready(client: TestClient, api: FastAPI, project_id: str) -> dict[str, Any]:
    api.state.agent_model_factory = lambda actor: ScriptModel()
    path = f"/projects/{project_id}"
    run = agent_post(client, path + "/scene-draft", {}, "draft")
    return agent_post(
        client,
        path + "/clarifications",
        {"run_id": run["id"], "use_demo_assumptions": True},
        "clarify",
    )


def test_missing_model_fails_honestly_and_manual_workflow_survives(
    client: TestClient, database: DatabaseCase
) -> None:
    pid = project(client)
    result = agent_post(client, f"/projects/{pid}/scene-draft", {}, "no-model")
    assert result["status"] == "failed" and result["error_code"] == "LLM_UNAVAILABLE"
    assert result["total_calls"] == 0 and not result["model_calls"]
    assert client.get(f"/api/v1/projects/{pid}").status_code == 200
    with Session(database.engine) as db:
        assert db.scalar(select(func.count()).select_from(SceneVersion)) == 0


def test_connection_is_owned_unverified_and_never_persisted(
    client: TestClient, api: FastAPI, database: DatabaseCase
) -> None:
    body = {
        "provider": "deepseek",
        "model": "deepseek-chat",
        "api_key": "test-key-never-persist-111",
        "authorize_paid_calls": True,
    }
    response = client.post("/api/v1/model-connection", json=body)
    assert response.status_code == 200
    assert response.json()["data"]["connected"] and not response.json()["data"]["verified"]
    assert str(body["api_key"]) not in response.text
    with TestClient(api) as other:
        assert other.get("/api/v1/session").status_code == 200
        assert not other.get("/api/v1/models").json()["data"]["connected"]
    with Session(database.engine) as db:
        assert db.scalar(select(func.count()).select_from(AgentRun)) == 0
    assert not client.post("/api/v1/model-connection/disconnect", json={}).json()["data"][
        "connected"
    ]


@pytest.mark.parametrize(
    "update",
    [
        {"authorize_paid_calls": False},
        {"model": "arbitrary-model"},
        {"provider": "arbitrary-provider"},
        {"base_url": "https://evil.example/v1"},
        {"authorize_paid_calls": 1},
        {"api_key": "short"},
    ],
)
def test_connection_rejects_unapproved_provider_or_calls(
    client: TestClient, update: dict[str, Any]
) -> None:
    body = {
        "provider": "deepseek",
        "model": "deepseek-chat",
        "api_key": "test-only-key-111",
        "authorize_paid_calls": True,
        **update,
    }
    assert client.post("/api/v1/model-connection", json=body).status_code == 422
    assert not client.get("/api/v1/models").json()["data"]["connected"]


def test_connection_expires(client: TestClient, api: FastAPI) -> None:
    client.post(
        "/api/v1/model-connection",
        json={
            "provider": "deepseek",
            "model": "deepseek-chat",
            "api_key": "test-only-key-111",
            "authorize_paid_calls": True,
        },
    )
    connections = api.state.model_connections
    for connection in connections._connections.values():
        connection.expires = 0
    assert not client.get("/api/v1/models").json()["data"]["connected"]


def test_unconfirmed_and_numeric_confirmation_cannot_publish(
    client: TestClient, api: FastAPI, database: DatabaseCase
) -> None:
    pid = project(client)
    run = ready(client, api, pid)
    for confirmation in [False, 1, "true", None]:
        response = client.post(
            f"/api/v1/projects/{pid}/agent-confirm",
            json={"run_id": run["id"], "confirmed": confirmation},
            headers={"Idempotency-Key": f"bad-{confirmation}"},
        )
        assert response.status_code == 422
    with Session(database.engine) as db:
        assert db.scalar(select(func.count()).select_from(SceneVersion)) == 0


def test_user_facts_cannot_be_overwritten(client: TestClient, api: FastAPI) -> None:
    pid = project(client)
    run = ready(client, api, pid)
    rejected = agent_post(
        client,
        f"/projects/{pid}/clarifications",
        {"run_id": run["id"], "answers": {"budget_cents": 1}},
        "overwrite",
    )
    assert rejected["status"] == "failed"
    assert rejected["error_code"] == "FACT_OVERWRITE_FORBIDDEN"
    assert rejected["scene"]["fields"]["budget_cents"]["value"] == 50000


def test_tools_roll_back_on_bad_plan_and_retry_recovers(
    client: TestClient, api: FastAPI, database: DatabaseCase
) -> None:
    pid = project(client)
    run = ready(client, api, pid)

    class BadPlan(ScriptModel):
        def plan(self, scene: dict[str, object]) -> ToolPlan:
            return ToolPlan(tools=("calculate_retail", "calculate_service"))

    api.state.agent_model_factory = lambda actor: BadPlan()
    failed = agent_post(
        client,
        f"/projects/{pid}/agent-confirm",
        {"run_id": run["id"], "confirmed": True},
        "fail-tools",
    )
    assert failed["status"] == "failed"
    with Session(database.engine) as db:
        assert db.scalar(select(func.count()).select_from(SceneVersion)) == 0
        assert db.scalar(select(func.count()).select_from(SimulationRun)) == 0
    assert any(t["status"] == "rolled_back" for t in failed["tools"])
    api.state.agent_model_factory = lambda actor: ScriptModel()
    retried = agent_post(
        client, f"/projects/{pid}/agent-retry", {"run_id": run["id"], "confirmed": True}, "retry"
    )
    assert retried["status"] == "needs_choice", retried


def test_model_json_retry_is_bounded(client: TestClient, api: FastAPI) -> None:
    calls: list[int] = []

    class BadModel(ScriptModel):
        def extract(self, original: str) -> Extraction:
            calls.append(1)
            raise AgentFailure("INVALID_JSON")

    api.state.agent_model_factory = lambda actor: BadModel()
    pid = project(client)
    failed = agent_post(client, f"/projects/{pid}/scene-draft", {}, "invalid-json")
    assert failed["status"] == "failed" and len(calls) == 2
    assert failed["total_calls"] == 2 and len(failed["model_calls"]) == 2


def test_no_cross_user_agent_access(client: TestClient, api: FastAPI) -> None:
    pid = project(client)
    run = ready(client, api, pid)
    with TestClient(api) as other:
        csrf = other.get("/api/v1/session").json()["data"]["csrf_token"]
        other.headers["X-CSRF-Token"] = csrf
        assert other.get(f"/api/v1/projects/{pid}/agent-runs/{run['id']}").status_code == 404
        assert (
            other.post(
                f"/api/v1/projects/{pid}/agent-confirm",
                json={"run_id": run["id"], "confirmed": True},
                headers={"Idempotency-Key": "foreign"},
            ).status_code
            == 404
        )


def test_checkpoint_recovery_new_app_and_idempotency(
    client: TestClient, api: FastAPI, database: DatabaseCase
) -> None:
    pid = project(client)
    run = ready(client, api, pid)
    other_app = create_app(database.settings)
    other_app.state.agent_model_factory = lambda actor: ScriptModel()
    with TestClient(
        other_app, cookies=client.cookies, headers={"X-CSRF-Token": client.headers["X-CSRF-Token"]}
    ) as reopened:
        body = {"run_id": run["id"], "confirmed": True}
        first = agent_post(reopened, f"/projects/{pid}/agent-confirm", body, "confirm")
        second = agent_post(reopened, f"/projects/{pid}/agent-confirm", body, "confirm")
        assert first == second and first["status"] == "needs_choice"
    other_app.state.engine.dispose()
    with Session(database.engine) as db:
        assert db.scalar(select(func.count()).select_from(SceneVersion)) == 1
        assert (db.scalar(select(func.count()).select_from(AgentCheckpoint)) or 0) > 0


def test_dispatch_budget_is_enforced(client: TestClient, api: FastAPI) -> None:
    pid = project(client)
    api.state.settings = replace(api.state.settings, agent_max_calls=1)
    api.state.agent_model_factory = lambda actor: ScriptModel()
    failed = agent_post(client, f"/projects/{pid}/scene-draft", {}, "one-call")
    assert failed["status"] == "failed" and failed["error_code"] == "AGENT_CALL_LIMIT"
    assert failed["total_calls"] == 1


@pytest.mark.parametrize(
    "field,evidence,value",
    [
        ("budget_cents", "预算500元", 50000),
        ("unit_price_cents", "每单收费99元", 9900),
        ("unit_cost_cents", "成本350分", 350),
        ("minutes_per_job", "每单1.5小时", 90),
        ("available_minutes", "可用4小时", 240),
        ("stock_qty", "备货30份", 30),
    ],
)
def test_exact_quote_and_unit_conversion(field: Any, evidence: str, value: int) -> None:
    extracted = Extraction(
        business_type="retail_perishable",
        business_evidence="冰粉",
        numbers=(NumberFact(field=field, value=value, evidence=evidence),),
        texts=(),
    )
    assert grounded(extracted, "冰粉，" + evidence) == extracted


@pytest.mark.parametrize(
    "evidence,value",
    [
        ("不存在的预算", 50000),
        ("预算500元", 500),
        ("成本500元", 50000),
        ("预算500元和300元", 50000),
    ],
)
def test_unsupported_evidence_is_never_a_fact(evidence: str, value: int) -> None:
    extracted = Extraction(
        business_type="retail_perishable",
        business_evidence="冰粉",
        numbers=(NumberFact(field="budget_cents", value=value, evidence=evidence),),
        texts=(),
    )
    with pytest.raises(AgentFailure):
        grounded(extracted, "冰粉，预算500元和300元，成本500元")


def test_source_upgrade_or_code_cannot_fit_model_contract() -> None:
    with pytest.raises(ValidationError):
        NumberFact.model_validate(
            {
                "field": "budget_cents",
                "value": 50000,
                "evidence": "预算500元",
                "source": "verified_external",
            }
        )
    with pytest.raises(ValidationError):
        ToolPlan.model_validate({"tools": ["shell", "sql"]})
    with pytest.raises(AgentFailure):
        LangChainModel(key="test-only-key", model="test", base_url="http://evil.example")


def test_transport_marks_verified_only_after_structured_success() -> None:
    connections = ModelConnections()
    conn = connections.connect("test-owner", "deepseek", "deepseek-chat", "private-test-key")
    model = connections.resolve("test-owner", Settings())
    assert isinstance(model, LangChainModel) and not conn.verified
    client = MagicMock()
    client.with_structured_output.return_value.invoke.return_value = {
        "business_type": "unsupported",
        "business_evidence": "融资",
        "numbers": [],
        "texts": [],
    }
    model.client = client
    parsed = model.extract("想做融资")
    assert parsed.business_type == "unsupported" and conn.verified
    assert "private-test-key" not in str(
        client.with_structured_output.return_value.invoke.call_args
    )


def test_remote_plain_http_connection_is_refused(api: FastAPI) -> None:
    with TestClient(api, base_url="http://testserver", client=("203.0.113.1", 5000)) as remote:
        csrf = remote.get("/api/v1/session").json()["data"]["csrf_token"]
        response = remote.post(
            "/api/v1/model-connection",
            json={
                "provider": "deepseek",
                "model": "deepseek-chat",
                "api_key": "private-test-key",
                "authorize_paid_calls": True,
            },
            headers={"X-CSRF-Token": csrf},
        )
        assert response.status_code == 400 and response.json()["error"]["code"] == "HTTPS_REQUIRED"


def test_existing_confirmed_user_values_are_never_replaced(
    client: TestClient,
    api: FastAPI,
    scene_data: Any,
) -> None:
    pid = project(client)
    scene = scene_data("retail_perishable")
    scene["original_idea"] = "我想卖冰粉，预算500元，备货200份。"
    scene["fields"]["budget_cents"] = {
        "value": 10000,
        "source": "user_input",
        "note": "用户已明确改为此预算",
    }
    scene["fields"]["stock_qty"] = {"value": 4, "source": "user_input", "note": "已确认的新备货量"}
    parent = post(client, f"/projects/{pid}/scene-confirm", {"scene": scene, "confirmed": True})
    api.state.agent_model_factory = lambda actor: ScriptModel()
    run = agent_post(client, f"/projects/{pid}/scene-draft", {}, "preserve-seed")
    assert run["scene"]["fields"]["budget_cents"]["value"] == 10000
    assert run["scene"]["fields"]["stock_qty"]["value"] == 4
    assert run["status"] == "needs_confirmation"
    confirmed = agent_post(
        client,
        f"/projects/{pid}/agent-confirm",
        {"run_id": run["id"], "confirmed": True},
        "seed-confirm",
    )
    assert confirmed["status"] == "needs_choice", confirmed
    new = client.get(f"/api/v1/scene-versions/{confirmed['scene_version_id']}").json()["data"]
    assert new["parent_version_id"] == parent["id"]
