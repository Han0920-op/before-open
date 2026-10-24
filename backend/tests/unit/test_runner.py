import json
import subprocess
import sys
from collections.abc import Callable
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from app.schemas.scene import scene_adapter
from app.schemas.simulation import SimulationSnapshot
from app.simulation.runner import (
    SimulationError,
    parse_scene,
    replay_snapshot,
    run_demand_scenarios,
    simulate,
    validate_scene,
)

NOW = datetime(2026, 10, 24, 12, tzinfo=UTC)


@pytest.mark.parametrize(
    "kind,label,metric,expected",
    [
        ("retail_perishable", "low", "result_cents", -11700),
        ("retail_perishable", "high", "result_cents", 4500),
        ("retail_durable", "base", "cash_change_cents", -5000),
        ("appointment_service", "base", "simplified_result_cents", 32000),
    ],
)
def test_fixtures_via_runner_and_snapshot_roundtrip(
    scene_data: Callable[[str], dict[str, Any]],
    kind: str,
    label: str,
    metric: str,
    expected: int,
) -> None:
    raw = scene_data(kind)
    before = json.dumps(raw, sort_keys=True)
    run = simulate(raw, scene_version_id="demo-version", scenario_label=label, calculated_at=NOW)
    assert getattr(run.result, metric) == expected
    assert run.model_version == raw["simulation_model_version"]
    assert run.input_snapshot.business_type == kind
    restored = SimulationSnapshot.model_validate_json(run.model_dump_json())
    assert restored == run
    assert replay_snapshot(restored) == run
    assert (
        simulate(raw, scene_version_id="demo-version", scenario_label=label, calculated_at=NOW)
        == run
    )
    assert json.dumps(raw, sort_keys=True) == before
    # Each numeric result is traceable; an unknown budget gap remains unknown.
    values = run.result.model_dump(exclude={"business_type"})
    assert {p.field for p in run.provenance} == set(values)
    inputs = run.input_snapshot.model_dump()
    for provenance in run.provenance:
        assert provenance.source == ("unknown" if values[provenance.field] is None else "derived")
        assert provenance.derived_from
        for path in provenance.derived_from:
            node: Any = inputs
            for part in path.split("."):
                node = node[int(part)] if isinstance(node, (list, tuple)) else node[part]
            assert "source" in node
    assert all(
        f.source in {"demo_assumption", "unknown"}
        for f in (
            getattr(run.input_snapshot.fields, n)
            for n in type(run.input_snapshot.fields).model_fields
        )
    )


def test_batch_runs_and_price_does_not_change_demand(
    scene_data: Callable[[str], dict[str, Any]],
) -> None:
    raw = scene_data("retail_perishable")
    runs = run_demand_scenarios(raw, scene_version_id="demo-original", calculated_at=NOW)
    assert len(runs) == 3
    assert [getattr(r.result, "sold") for r in runs] == [12, 30, 30]
    raw["fields"]["unit_price_cents"]["value"] = 1000
    changed = run_demand_scenarios(raw, scene_version_id="demo-branch", calculated_at=NOW)
    assert [getattr(r.result, "sold") for r in changed] == [12, 30, 30]
    assert getattr(changed[0].result, "revenue_cents") == 12000
    assert getattr(runs[0].result, "revenue_cents") == 10800


def test_selected_ready_scenario_vs_incomplete_batch(
    scene_data: Callable[[str], dict[str, Any]],
) -> None:
    raw = scene_data("retail_perishable")
    raw["demand_scenarios"][1]["demand_qty"] = {"value": None, "source": "unknown"}
    assert validate_scene(raw, "low").ready
    assert not validate_scene(raw).ready
    with pytest.raises(SimulationError) as exc:
        run_demand_scenarios(raw, scene_version_id="demo", calculated_at=NOW)
    assert exc.value.code == "SIMULATION_NOT_READY"
    assert "demand_scenarios.1.demand_qty" in exc.value.validation.missing_fields


@pytest.mark.parametrize(
    "change,code",
    [
        ("missing_cost", "SIMULATION_NOT_READY"),
        ("missing_demand", "SIMULATION_NOT_READY"),
        ("empty_demand", "INVALID_SCENE"),
        ("bad_version", "INVALID_SCENE"),
        ("bad_label", "INVALID_SCENE"),
    ],
)
def test_runner_errors(
    scene_data: Callable[[str], dict[str, Any]],
    change: str,
    code: str,
) -> None:
    raw = scene_data("retail_perishable")
    label = "low"
    if change == "missing_cost":
        raw["fields"]["unit_cost_cents"] = {"value": None, "source": "unknown"}
    elif change == "missing_demand":
        raw["demand_scenarios"][0]["demand_qty"] = {"value": None, "source": "unknown"}
    elif change == "empty_demand":
        raw["demand_scenarios"] = []
        assert validate_scene(raw).missing_fields == ("demand_scenarios",)
    elif change == "bad_version":
        raw["simulation_model_version"] = "service-v1"
    else:
        label = "unknown-label"
    with pytest.raises(SimulationError) as exc:
        simulate(raw, scene_version_id="demo", scenario_label=label, calculated_at=NOW)
    assert exc.value.code == code
    assert not exc.value.validation.ready


def test_service_cannot_run_retail_batch(scene_data: Callable[[str], dict[str, Any]]) -> None:
    with pytest.raises(SimulationError) as exc:
        run_demand_scenarios(
            scene_data("appointment_service"), scene_version_id="demo", calculated_at=NOW
        )
    assert exc.value.code == "UNSUPPORTED_BUSINESS_TYPE"


def test_nested_immutability_and_caller_mutation(
    scene_data: Callable[[str], dict[str, Any]],
) -> None:
    raw = scene_data("retail_perishable")
    run = simulate(raw, scene_version_id="demo", scenario_label="low", calculated_at=NOW)
    with pytest.raises(ValidationError):
        run.scene_version_id = "changed"
    with pytest.raises(ValidationError):
        run.input_snapshot.fields.unit_price_cents.value = 999
    assert isinstance(run.provenance, tuple)
    raw["fields"]["unit_price_cents"]["value"] = 999
    assert run.input_snapshot.fields.unit_price_cents.value == 900


def test_tampered_model_copy_and_snapshot_rejected(
    scene_data: Callable[[str], dict[str, Any]],
) -> None:
    scene = parse_scene(scene_data("retail_perishable"))
    tampered = scene.model_copy(update={"simulation_model_version": "fake"})
    assert not validate_scene(tampered).valid
    run = simulate(scene, scene_version_id="demo", scenario_label="low", calculated_at=NOW)
    data = run.model_dump(mode="json")
    data["result"]["result_cents"] = 999
    with pytest.raises(ValueError, match="recomputed"):
        replay_snapshot(SimulationSnapshot.model_validate(data))
    data = run.model_dump(mode="json")
    data["provenance"] = []
    with pytest.raises(ValueError, match="recomputed"):
        replay_snapshot(SimulationSnapshot.model_validate(data))


def test_time_and_identifiers(scene_data: Callable[[str], dict[str, Any]]) -> None:
    raw = scene_data("appointment_service")
    local_time = NOW.astimezone(timezone(timedelta(hours=8)))
    run = simulate(raw, scene_version_id="demo", scenario_label="base", calculated_at=local_time)
    assert run.calculated_at == NOW and run.calculated_at.utcoffset() == timedelta(0)
    with pytest.raises(ValidationError):
        simulate(
            raw,
            scene_version_id="demo",
            scenario_label="base",
            calculated_at=NOW.replace(tzinfo=None),
        )
    with pytest.raises(ValidationError):
        simulate(raw, scene_version_id="", scenario_label="base", calculated_at=NOW)


@pytest.mark.parametrize("kind", ["retail_perishable", "retail_durable", "appointment_service"])
def test_cli_runs_real_fixture(kind: str) -> None:
    backend = Path(__file__).resolve().parents[2]
    command = [
        sys.executable,
        "-m",
        "app.simulation",
        f"../fixtures/{kind}.json",
        "--scene-version-id",
        "demo",
        "--calculated-at",
        NOW.isoformat(),
    ]
    process = subprocess.run(command, cwd=backend, capture_output=True, text=True, check=True)
    output = json.loads(process.stdout)
    assert output
    for item in output:
        assert replay_snapshot(SimulationSnapshot.model_validate(item))


def test_exported_schema_is_current() -> None:
    schema_path = Path(__file__).resolve().parents[3] / "docs" / "scene.schema.json"
    assert json.loads(schema_path.read_text()) == scene_adapter.json_schema()


def test_cli_reports_incomplete_input_without_dumping_notes(
    scene_data: Callable[[str], dict[str, Any]],
    tmp_path: Path,
) -> None:
    raw = scene_data("retail_perishable")
    raw["fields"]["unit_cost_cents"] = {
        "value": None,
        "source": "unknown",
        "note": "private-test-note",
    }
    path = tmp_path / "incomplete.json"
    path.write_text(json.dumps(raw))
    command = [sys.executable, "-m", "app.simulation", str(path), "--scene-version-id", "demo"]
    process = subprocess.run(command, capture_output=True, text=True, check=False)
    assert process.returncode == 2
    assert not process.stdout
    assert json.loads(process.stderr)["code"] == "SIMULATION_NOT_READY"
    assert "private-test-note" not in process.stderr
    assert "Traceback" not in process.stderr
