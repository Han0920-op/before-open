"""Ground model extraction in exact original evidence; unknowns stay null."""

import json
import re
from decimal import Decimal
from pathlib import Path
from typing import Any

from app.agent.contracts import Extraction, Question
from app.agent.model import AgentFailure
from app.models.entities import Project
from app.schemas.scene import SceneSpec, ServiceScene
from app.simulation.runner import parse_scene

LABELS = {
    "budget_cents": ("这次手头可以投入多少钱？", "元"),
    "unit_price_cents": ("每份商品或每单服务，准备收多少钱？", "元"),
    "unit_cost_cents": ("每份商品或每单服务的成本是多少？", "元"),
    "fixed_cost_cents": ("这一次还有多少固定费用？没有请明确填0。", "元"),
    "stock_qty": ("这次准备多少份或多少件？", "份/件"),
    "demand_qty": ("这次先按多少需求来假设？这不是销量预测。", "份/件"),
    "minutes_per_job": ("完成一单要多少分钟？请包含必要的后期时间。", "分钟"),
    "available_minutes": ("这次总共可以用多少分钟提供服务？", "分钟"),
    "booked": ("先按多少预约来假设？", "单"),
    "cancelled": ("这组情景中有多少单取消？", "单"),
}
CONTEXT = {
    "budget_cents": r"预算|手头|我有|只有|投入|资金",
    "unit_price_cents": r"售价|单价|收费|卖.*元|每(?:单|份|件|次).*元",
    "unit_cost_cents": r"成本",
    "fixed_cost_cents": r"固定|摊位费|场地费",
    "stock_qty": r"备货|准备|制作",
    "demand_qty": r"需求|假设.*卖出",
    "minutes_per_job": r"每(?:单|次)|耗时|用时",
    "available_minutes": r"可用|能用|总共|只有",
    "booked": r"预约|已约",
    "cancelled": r"取消",
}
NUMBER = re.compile(r"-?\d+(?:\.\d+)?")


def grounded(extraction: Extraction, original: str) -> Extraction:
    if extraction.business_evidence not in original or not extraction.business_evidence:
        raise AgentFailure("UNSUPPORTED_EVIDENCE")
    seen: set[str] = set()
    for fact in extraction.numbers:
        if (
            fact.field in seen
            or fact.evidence not in original
            or not re.search(CONTEXT[fact.field], fact.evidence)
        ):
            raise AgentFailure("UNSUPPORTED_EVIDENCE")
        seen.add(fact.field)
        tokens = NUMBER.findall(fact.evidence)
        if len(tokens) != 1:
            raise AgentFailure("UNSUPPORTED_EVIDENCE")
        number = Decimal(tokens[0])
        if fact.field.endswith("_cents"):
            number *= 1 if re.search(r"\d(?:\.\d+)?\s*分(?:钱)?", fact.evidence) else 100
        elif "minutes" in fact.field:
            if "小时" in fact.evidence:
                number *= 60
            elif "分钟" not in fact.evidence:
                raise AgentFailure("UNSUPPORTED_EVIDENCE")
        if number < 0 or number != number.to_integral_value() or int(number) != fact.value:
            raise AgentFailure("UNSUPPORTED_EVIDENCE")
    seen_text: set[str] = set()
    for text in extraction.texts:
        if (
            text.field in seen_text
            or text.evidence not in original
            or text.value not in text.evidence
        ):
            raise AgentFailure("UNSUPPORTED_EVIDENCE")
        seen_text.add(text.field)
    return extraction


def template(kind: str) -> dict[str, Any]:
    if kind not in {"retail_perishable", "retail_durable", "appointment_service"}:
        raise AgentFailure("UNSUPPORTED_BUSINESS_TYPE")
    path = Path(__file__).resolve().parents[3] / "fixtures" / f"{kind}.json"
    result: dict[str, Any] = json.loads(path.read_text())
    return result


def build_scene(project: Project, extracted: Extraction) -> SceneSpec:
    raw = template(extracted.business_type)
    raw.update(
        title=project.title,
        original_idea=project.original_idea,
        period_note="本次预演；固定费用计入一次。不含税务、押金、退款等复杂项目。",
    )
    for key in raw["fields"]:
        raw["fields"][key] = {"value": None, "source": "unknown", "note": "尚未提供"}
    raw["location"] = {
        "location_type": "user_described",
        "description": "地点待确认",
        "source": "unknown",
        "verified": False,
    }
    raw["demand_scenarios"] = (
        []
        if extracted.business_type == "appointment_service"
        else [{"scenario_label": "base", "demand_qty": {"value": None, "source": "unknown"}}]
    )
    for fact in extracted.numbers:
        value = {"value": fact.value, "source": "user_input", "note": f"原文：{fact.evidence}"}
        if fact.field == "demand_qty" and extracted.business_type != "appointment_service":
            raw["demand_scenarios"][0]["demand_qty"] = value
        elif fact.field in raw["fields"]:
            raw["fields"][fact.field] = value
        else:
            raise AgentFailure("INVALID_SCENE")
    for text in extracted.texts:
        if text.field == "location":
            raw["location"].update(description=text.value, source="user_input")
    return parse_scene(raw)


def questions(scene: SceneSpec) -> tuple[Question, ...]:
    keys = [
        name
        for name in type(scene.fields).model_fields
        if getattr(scene.fields, name).value is None and name != "budget_cents"
    ]
    if not isinstance(scene, ServiceScene) and not scene.demand_scenarios[0].demand_qty.value:
        if scene.demand_scenarios[0].demand_qty.value is None:
            keys.append("demand_qty")
    return tuple(Question(field=key, text=LABELS[key][0], unit=LABELS[key][1]) for key in keys[:3])


def clarify(scene: SceneSpec, answers: dict[str, int], demo: bool) -> SceneSpec:
    raw = scene.model_dump(mode="json")
    defaults = template(scene.business_type)
    for key, value in answers.items():
        if key == "demand_qty" and not isinstance(scene, ServiceScene):
            field = raw["demand_scenarios"][0]["demand_qty"]
        elif key in raw["fields"]:
            field = raw["fields"][key]
        else:
            raise AgentFailure("INVALID_CLARIFICATION")
        if field["value"] is not None:
            raise AgentFailure("FACT_OVERWRITE_FORBIDDEN")
        field.update(value=value, source="user_input", note="用户明确填写的澄清答案")
    if demo:
        for key, field in raw["fields"].items():
            if field["value"] is None and defaults["fields"][key]["value"] is not None:
                raw["fields"][key] = defaults["fields"][key]
        if (
            not isinstance(scene, ServiceScene)
            and raw["demand_scenarios"][0]["demand_qty"]["value"] is None
        ):
            raw["demand_scenarios"][0]["demand_qty"] = defaults["demand_scenarios"][0]["demand_qty"]
    return parse_scene(raw)
