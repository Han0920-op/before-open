from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.agent.contracts import ExperimentDraft, Extraction, NumberFact, TextFact, ToolPlan
from app.models.entities import ExperimentTask, SceneVersion, SimulationRun
from tests.integration.conftest import DatabaseCase
from tests.integration.test_business_api import post


class ScriptModel:
    """Injected ONLY in tests; no production setting or endpoint can select it."""

    identity = "test-scripted-not-a-real-model"

    def extract(self, original: str) -> Extraction:
        return Extraction(
            business_type="retail_perishable",
            business_evidence="冰粉",
            numbers=(
                NumberFact(field="budget_cents", value=50000, evidence="预算500元"),
                NumberFact(field="stock_qty", value=200, evidence="备货200份"),
            ),
            texts=(TextFact(field="product", value="冰粉", evidence="冰粉"),),
        )

    def plan(self, scene: dict[str, object]) -> ToolPlan:
        return ToolPlan(tools=("calculate_retail", "check_budget"))

    def experiment(self, context: dict[str, object]) -> ExperimentDraft:
        return ExperimentDraft(
            question="测试草稿：价格接受度",
            method="征得同意后询问，不记录身份。",
            warnings=("测试数据，不是真实调研",),
        )


def agent_post(client: TestClient, path: str, body: object, key: str) -> dict[str, Any]:
    response = client.post("/api/v1" + path, json=body, headers={"Idempotency-Key": key})
    assert response.status_code == 200, response.text
    result: dict[str, Any] = response.json()["data"]
    return result


def test_confirm_interrupt_recovery_and_tools(
    client: TestClient, api: FastAPI, database: DatabaseCase
) -> None:
    api.state.agent_model_factory = lambda actor: ScriptModel()
    project = post(
        client,
        "/projects",
        {"title": "冰粉测试", "original_idea": "我想卖冰粉，预算500元，备货200份。"},
    )
    path = f"/projects/{project['id']}"
    draft = agent_post(client, path + "/scene-draft", {}, "draft")
    assert draft["status"] == "needs_input", draft
    assert 1 <= len(draft["questions"]) <= 3
    assert draft["scene"]["fields"]["budget_cents"]["value"] == 50000
    assert draft["scene"]["fields"]["unit_cost_cents"]["value"] is None
    with Session(database.engine) as db:
        assert db.scalar(select(func.count()).select_from(SceneVersion)) == 0
    ready = agent_post(
        client,
        path + "/clarifications",
        {"run_id": draft["id"], "use_demo_assumptions": True},
        "clarify",
    )
    assert ready["status"] == "needs_confirmation", ready
    assert ready["scene"]["fields"]["stock_qty"]["value"] == 200
    # A new graph instance resolves the persisted interrupt on each request.
    confirmed = agent_post(
        client, path + "/agent-confirm", {"run_id": draft["id"], "confirmed": True}, "confirm"
    )
    assert confirmed["status"] == "needs_choice", confirmed
    names = [t["tool_name"] for t in confirmed["tools"]]
    assert (
        "calculate_retail" in names and "check_budget" in names and "generate_risk_cards" in names
    )
    assert confirmed["scene_version_id"]
    duplicate = client.post(
        f"/api/v1{path}/agent-confirm",
        json={"run_id": draft["id"], "confirmed": True},
        headers={"Idempotency-Key": "second-confirm-intent"},
    )
    assert duplicate.status_code == 409
    assert (
        client.get(f"/api/v1{path}/agent-runs/{draft['id']}").json()["data"]["status"]
        == "needs_choice"
    )
    assert confirmed["proposed_actions"]
    action = confirmed["proposed_actions"][0]["id"]
    final = agent_post(
        client,
        path + f"/agent-runs/{draft['id']}/actions",
        {"action_id": action, "confirmed": True},
        "action",
    )
    assert final["status"] == "completed", final
    assert final["branch_version_id"] != final["scene_version_id"]
    assert "compare_versions" in [t["tool_name"] for t in final["tools"]]
    api.state.agent_model_factory = lambda actor: (
        None
    )  # No provider is needed to replay a completed action.
    repeated = agent_post(
        client,
        path + f"/agent-runs/{draft['id']}/actions",
        {"action_id": action, "confirmed": True},
        "repeat-completed-action",
    )
    assert repeated["branch_version_id"] == final["branch_version_id"]
    with Session(database.engine) as db:
        assert db.scalar(select(func.count()).select_from(SceneVersion)) == 2


@pytest.mark.parametrize(
    "kind,idea,quote,field,value,expected",
    [
        ("retail_durable", "想卖手工耳饰，预算300元。", "预算300元", "budget_cents", 30000, -5000),
        (
            "appointment_service",
            "预约摄影，每单收费120元。",
            "每单收费120元",
            "unit_price_cents",
            12000,
            32000,
        ),
    ],
)
def test_other_business_routes(
    client: TestClient,
    api: FastAPI,
    database: DatabaseCase,
    kind: Any,
    idea: str,
    quote: str,
    field: Any,
    value: int,
    expected: int,
) -> None:
    class OtherModel(ScriptModel):
        def extract(self, original: str) -> Extraction:
            return Extraction(
                business_type=kind,
                business_evidence="耳饰" if kind == "retail_durable" else "摄影",
                numbers=(NumberFact(field=field, value=value, evidence=quote),),
                texts=(),
            )

        def plan(self, scene: dict[str, object]) -> ToolPlan:
            return ToolPlan(
                tools=(
                    "validate_scene",
                    "calculate_service" if kind == "appointment_service" else "calculate_retail",
                )
            )

    api.state.agent_model_factory = lambda actor: OtherModel()
    pid = post(client, "/projects", {"title": "跨模型测试", "original_idea": idea})["id"]
    path = f"/projects/{pid}"
    run = agent_post(client, path + "/scene-draft", {}, "draft")
    assert run["scene"]["business_type"] == kind
    run = agent_post(
        client,
        path + "/clarifications",
        {"run_id": run["id"], "use_demo_assumptions": True},
        "clarify",
    )
    result = agent_post(
        client, path + "/agent-confirm", {"run_id": run["id"], "confirmed": True}, "confirm"
    )
    assert result["status"] == "needs_choice", result
    with Session(database.engine) as db:
        saved = db.scalar(select(SimulationRun))
        assert saved is not None
        field_name = (
            "simplified_result_cents" if kind == "appointment_service" else "cash_change_cents"
        )
        assert saved.output_json["result"][field_name] == expected


def test_unsupported_and_experiment_draft_are_honest(
    client: TestClient, api: FastAPI, database: DatabaseCase
) -> None:
    class Unsupported(ScriptModel):
        def extract(self, original: str) -> Extraction:
            return Extraction(
                business_type="unsupported", business_evidence="连锁加盟", numbers=(), texts=()
            )

    api.state.agent_model_factory = lambda actor: Unsupported()
    p = post(client, "/projects", {"title": "超范围", "original_idea": "我想做连锁加盟"})
    run = agent_post(client, f"/projects/{p['id']}/scene-draft", {}, "unsupported")
    assert run["status"] == "unsupported" and run["scene"] is None and not run["tools"]
    api.state.agent_model_factory = lambda actor: ScriptModel()
    p = post(
        client,
        "/projects",
        {"title": "冰粉", "original_idea": "我想卖冰粉，预算500元，备货200份。"},
    )
    path = f"/projects/{p['id']}"
    draft = agent_post(client, path + "/scene-draft", {}, "draft")
    agent_post(
        client,
        path + "/clarifications",
        {"run_id": draft["id"], "use_demo_assumptions": True},
        "clarify",
    )
    confirmed = agent_post(
        client, path + "/agent-confirm", {"run_id": draft["id"], "confirmed": True}, "confirm"
    )
    experiment = agent_post(
        client,
        path + "/experiment-draft",
        {"scene_version_id": confirmed["scene_version_id"], "scenario_label": "base"},
        "experiment",
    )
    assert experiment["status"] == "completed" and experiment["experiment_draft"]
    assert experiment["tools"][0]["tool_name"] == "draft_experiment"
    with Session(database.engine) as db:
        assert db.scalar(select(func.count()).select_from(ExperimentTask)) == 0
