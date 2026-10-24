import pytest
from pydantic import ValidationError

from app.schemas.simulation import RetailInput
from app.simulation.common import check_budget
from app.simulation.retail import calculate_durable, calculate_perishable


def retail(**updates: int | None) -> RetailInput:
    return RetailInput.model_validate(
        {
            "unit_price_cents": 900,
            "unit_cost_cents": 350,
            "stock_qty": 30,
            "demand_qty": 12,
            "fixed_cost_cents": 12000,
            "budget_cents": None,
            **updates,
        }
    )


@pytest.mark.parametrize("demand,sold,unsold,result", [(12, 12, 18, -11700), (45, 30, 0, 4500)])
def test_v4_ice(demand: int, sold: int, unsold: int, result: int) -> None:
    actual = calculate_perishable(retail(demand_qty=demand))
    assert (actual.sold, actual.unsold, actual.result_cents) == (sold, unsold, result)
    assert actual.cash_out_cents == 22500
    assert actual.budget_gap_cents is None


def test_v4_durable_inventory() -> None:
    result = calculate_durable(
        retail(
            unit_price_cents=1500,
            unit_cost_cents=600,
            stock_qty=20,
            demand_qty=8,
            fixed_cost_cents=5000,
        )
    )
    assert result.cash_change_cents == -5000
    assert result.simplified_period_profit_cents == 2200
    assert result.unsold == 12
    assert result.remaining_inventory_cost_cents == 7200


@pytest.mark.parametrize(
    "budget,gap", [(None, None), (0, 22500), (100, 22400), (22500, 0), (50000, 0)]
)
def test_budget(budget: int | None, gap: int | None) -> None:
    assert calculate_perishable(retail(budget_cents=budget)).budget_gap_cents == gap
    assert calculate_durable(retail(budget_cents=budget)).budget_gap_cents == gap


@pytest.mark.parametrize("stock,demand", [(0, 0), (0, 10), (30, 0), (30, 30), (30, 45)])
def test_stock_conservation_and_no_mutation(stock: int, demand: int) -> None:
    data = retail(stock_qty=stock, demand_qty=demand, fixed_cost_cents=0)
    before = data.model_dump_json()
    for result in (calculate_perishable(data), calculate_durable(data)):
        assert result.sold + result.unsold == stock
        assert result.sold == min(stock, demand)
        assert result.revenue_cents == result.sold * 900
        assert result.cash_out_cents == stock * 350
    durable = calculate_durable(data)
    assert (
        durable.simplified_period_profit_cents - durable.cash_change_cents
        == durable.remaining_inventory_cost_cents
    )
    assert before == data.model_dump_json()


def test_integer_cent_and_maximum_safe_results() -> None:
    assert (
        calculate_perishable(
            retail(
                unit_price_cents=1,
                unit_cost_cents=0,
                stock_qty=1,
                demand_qty=1,
                fixed_cost_cents=0,
            )
        ).result_cents
        == 1
    )
    data = retail(
        unit_price_cents=10**9,
        unit_cost_cents=10**9,
        stock_qty=10**6,
        demand_qty=10**6,
        fixed_cost_cents=10**9,
    )
    result = calculate_durable(data)
    assert result.revenue_cents == 10**15
    assert result.cash_change_cents == -(10**9)
    assert result.cash_out_cents < 2**53
    assert calculate_perishable(retail(unit_price_cents=0)).revenue_cents == 0


@pytest.mark.parametrize(
    "field,value",
    [
        ("stock_qty", -1),
        ("stock_qty", 10**6 + 1),
        ("demand_qty", True),
        ("unit_price_cents", 1.5),
        ("fixed_cost_cents", None),
        ("unit_cost_cents", "350"),
    ],
)
def test_bad_inputs(field: str, value: object) -> None:
    raw = retail().model_dump()
    raw[field] = value
    with pytest.raises(ValidationError):
        RetailInput.model_validate(raw)


@pytest.mark.parametrize("value", [-1, True, 0.5, "100", 10**9 + 1])
def test_budget_tool_rejects_invalid_parameters(value: object) -> None:
    with pytest.raises(ValidationError):
        check_budget(value, 100)  # type: ignore[arg-type]
