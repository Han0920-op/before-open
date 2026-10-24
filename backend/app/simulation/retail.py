from app.schemas.simulation import DurableResult, PerishableResult, RetailInput
from app.simulation.common import check_budget


def calculate_perishable(data: RetailInput) -> PerishableResult:
    sold = min(data.stock_qty, data.demand_qty)
    revenue = sold * data.unit_price_cents
    cash_out = data.stock_qty * data.unit_cost_cents + data.fixed_cost_cents
    return PerishableResult(
        sold=sold,
        unsold=data.stock_qty - sold,
        revenue_cents=revenue,
        cash_out_cents=cash_out,
        result_cents=revenue - cash_out,
        budget_gap_cents=check_budget(data.budget_cents, cash_out),
    )


def calculate_durable(data: RetailInput) -> DurableResult:
    sold = min(data.stock_qty, data.demand_qty)
    unsold = data.stock_qty - sold
    revenue = sold * data.unit_price_cents
    cash_out = data.stock_qty * data.unit_cost_cents + data.fixed_cost_cents
    return DurableResult(
        sold=sold,
        unsold=unsold,
        revenue_cents=revenue,
        cash_out_cents=cash_out,
        cash_change_cents=revenue - cash_out,
        simplified_period_profit_cents=(
            revenue - sold * data.unit_cost_cents - data.fixed_cost_cents
        ),
        remaining_inventory_cost_cents=unsold * data.unit_cost_cents,
        budget_gap_cents=check_budget(data.budget_cents, cash_out),
    )
