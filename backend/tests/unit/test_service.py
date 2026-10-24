import pytest
from pydantic import ValidationError

from app.schemas.simulation import ServiceInput
from app.simulation.service import calculate_service


def service(**updates: int) -> ServiceInput:
    return ServiceInput.model_validate(
        {
            "unit_price_cents": 12000,
            "unit_cost_cents": 2000,
            "minutes_per_job": 90,
            "available_minutes": 360,
            "booked": 6,
            "cancelled": 1,
            "fixed_cost_cents": 8000,
            **updates,
        }
    )


def test_v4_photography() -> None:
    result = calculate_service(service())
    assert result.capacity == 4
    assert result.valid_bookings == 5
    assert result.completed == 4
    assert result.revenue_cents == 48000
    assert result.cost_cents == 16000
    assert result.simplified_result_cents == 32000
    assert result.idle_minutes == 0


@pytest.mark.parametrize(
    "booked,cancelled,minutes,completed,idle",
    [
        (0, 0, 360, 0, 360),
        (6, 6, 360, 0, 360),
        (6, 1, 0, 0, 0),
        (6, 1, 359, 3, 89),
        (1, 0, 360, 1, 270),
    ],
)
def test_capacity_edges(
    booked: int, cancelled: int, minutes: int, completed: int, idle: int
) -> None:
    data = service(booked=booked, cancelled=cancelled, available_minutes=minutes)
    before = data.model_dump_json()
    result = calculate_service(data)
    assert (result.completed, result.idle_minutes) == (completed, idle)
    assert result.completed <= min(result.capacity, result.valid_bookings)
    assert result.idle_minutes == minutes - completed * 90
    assert result.simplified_result_cents == completed * 10000 - 8000
    assert data.model_dump_json() == before


@pytest.mark.parametrize(
    "field,value",
    [
        ("minutes_per_job", 0),
        ("minutes_per_job", -1),
        ("minutes_per_job", 0.5),
        ("available_minutes", -1),
        ("booked", True),
        ("cancelled", 7),
        ("cancelled", -1),
        ("unit_price_cents", "12000"),
        ("booked", 10**6 + 1),
    ],
)
def test_bad_service_input(field: str, value: object) -> None:
    raw = service().model_dump()
    raw[field] = value
    with pytest.raises(ValidationError):
        ServiceInput.model_validate(raw)


def test_service_maximum_and_free_service() -> None:
    result = calculate_service(
        service(
            unit_price_cents=10**9,
            unit_cost_cents=0,
            minutes_per_job=1,
            available_minutes=10**6,
            booked=10**6,
            cancelled=0,
            fixed_cost_cents=0,
        )
    )
    assert result.completed == 10**6
    assert result.simplified_result_cents == 10**15 < 2**53
    assert result.idle_minutes == 0
    assert calculate_service(service(unit_price_cents=0)).simplified_result_cents == -16000
