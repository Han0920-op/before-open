from collections.abc import Callable
from typing import Any

import pytest
from pydantic import ValidationError

from app.schemas.scene import scene_adapter
from app.simulation.runner import parse_scene, validate_scene


@pytest.mark.parametrize("kind", ["retail_perishable", "retail_durable", "appointment_service"])
def test_scene_json_roundtrip(
    scene_data: Callable[[str], dict[str, Any]],
    kind: str,
) -> None:
    scene = parse_scene(scene_data(kind))
    assert scene_adapter.validate_json(scene.model_dump_json()) == scene
    assert validate_scene(scene).ready


@pytest.mark.parametrize(
    "key,value",
    [
        ("business_type", "franchise"),
        ("simulation_model_version", "retail-durable-v1"),
        ("schema_version", "2.0"),
        ("currency", "USD"),
        ("extra", 1),
    ],
)
def test_bad_scene_contract(
    scene_data: Callable[[str], dict[str, Any]],
    key: str,
    value: object,
) -> None:
    raw = scene_data("retail_perishable")
    raw[key] = value
    validation = validate_scene(raw)
    assert not validation.valid and not validation.ready
    assert validation.errors


def test_unknowns_recomputed_without_silent_defaults(
    scene_data: Callable[[str], dict[str, Any]],
) -> None:
    raw = scene_data("retail_perishable")
    raw["fields"]["fixed_cost_cents"] = {"value": None, "source": "unknown"}
    raw["unknowns"] = ["misleading"]
    scene = parse_scene(raw)
    assert "fields.fixed_cost_cents" in scene.unknowns
    assert "misleading" not in scene.unknowns
    validation = validate_scene(scene, "low")
    assert validation.valid and not validation.ready
    assert validation.missing_fields == ("fields.fixed_cost_cents",)


def test_cross_business_fields_and_over_cancellation_rejected(
    scene_data: Callable[[str], dict[str, Any]],
) -> None:
    raw = scene_data("appointment_service")
    raw["fields"]["stock_qty"] = {"value": 1, "source": "demo_assumption"}
    assert not validate_scene(raw).valid
    raw = scene_data("appointment_service")
    raw["fields"]["cancelled"]["value"] = 7
    assert not validate_scene(raw).valid


def test_location_cannot_be_verified_by_boolean_alone(
    scene_data: Callable[[str], dict[str, Any]],
) -> None:
    raw = scene_data("retail_perishable")
    raw["location"]["verified"] = True
    with pytest.raises(ValidationError):
        parse_scene(raw)


def test_demand_labels_and_service_scenarios(
    scene_data: Callable[[str], dict[str, Any]],
) -> None:
    raw = scene_data("retail_perishable")
    raw["demand_scenarios"][1]["scenario_label"] = "low"
    assert not validate_scene(raw).valid
    service = scene_data("appointment_service")
    service["demand_scenarios"] = raw["demand_scenarios"]
    assert not validate_scene(service).valid


def test_adapter_exports_discriminated_json_schema() -> None:
    schema = scene_adapter.json_schema()
    assert schema["discriminator"]["propertyName"] == "business_type"
    assert len(schema["oneOf"]) == 3


def test_location_observation_requires_reference(
    scene_data: Callable[[str], dict[str, Any]],
) -> None:
    raw = scene_data("retail_perishable")
    raw["location"]["source"] = "user_observation"
    assert not validate_scene(raw).valid
    raw["location"]["observation_id"] = "test-only-reference"
    scene = parse_scene(raw)
    assert scene.location.source == "user_observation"
    assert not scene.location.verified
