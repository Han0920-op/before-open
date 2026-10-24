import pytest
from pydantic import ValidationError

from app.schemas.provenance import SourceField
from app.schemas.scene import Money


@pytest.mark.parametrize("value", [-1, 1.5, True, "100", 10**9 + 1])
def test_strict_money(value: object) -> None:
    with pytest.raises(ValidationError):
        SourceField[Money].model_validate({"value": value, "source": "user_input"})


@pytest.mark.parametrize("value", [0, 1, 10**9])
def test_valid_money(value: int) -> None:
    assert SourceField[Money](value=value, source="user_input").value == value


@pytest.mark.parametrize(
    "data",
    [
        {"value": None, "source": "demo_assumption"},
        {"value": 1, "source": "unknown"},
        {"value": 1, "source": "verified_external"},
        {"value": 1, "source": "user_observation"},
        {"value": 1, "source": "derived"},
        {"value": 1, "source": "user_input", "observation_id": "fake"},
        {"value": 1, "source": "demo_assumption", "derived_from": ["x"]},
        {"value": None, "source": "unknown", "evidence": {}},
        {"value": 1, "source": "demo_assumption", "verified": True},
    ],
)
def test_invalid_source_combinations(data: object) -> None:
    with pytest.raises(ValidationError):
        SourceField[Money].model_validate(data)


def test_unknown_stays_null_on_roundtrip() -> None:
    unknown = SourceField[Money](value=None, source="unknown")
    assert SourceField[Money].model_validate_json(unknown.model_dump_json()) == unknown
    assert unknown.value is None


def test_evidence_and_references_roundtrip() -> None:
    evidence = {
        "source_url": "https://example.com/source",
        "observed_at": "2026-10-24T12:00:00+08:00",
        "scope": "示例证据结构，不代表已做现实核验",
    }
    external = SourceField[Money].model_validate(
        {
            "value": 100,
            "source": "verified_external",
            "evidence": evidence,
        }
    )
    assert SourceField[Money].model_validate_json(external.model_dump_json()) == external
    observation = SourceField[Money](
        value=100, source="user_observation", observation_id="test-observation"
    )
    assert observation.source != "verified_external"
    derived = SourceField[Money](value=100, source="derived", derived_from=("fields.x",))
    assert derived.derived_from == ("fields.x",)


@pytest.mark.parametrize(
    "key,value",
    [
        ("source_url", "file:///etc/passwd"),
        ("observed_at", "2026-10-24T12:00:00"),
        ("scope", ""),
    ],
)
def test_external_evidence_requirements(key: str, value: str) -> None:
    evidence = {
        "source_url": "https://example.com",
        "observed_at": "2026-10-24T12:00:00Z",
        "scope": "example",
    }
    evidence[key] = value
    with pytest.raises(ValidationError):
        SourceField[Money].model_validate(
            {
                "value": 1,
                "source": "verified_external",
                "evidence": evidence,
            }
        )
