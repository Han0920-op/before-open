"""Pure, bounded process ledger; animation and the model never control the arithmetic."""

from app.schemas.process import ProcessProfile, ProcessState, ProcessStepView
from app.schemas.scene import PerishableScene
from app.schemas.simulation import PerishableResult, SimulationSnapshot


def profile_for(snapshot: SimulationSnapshot) -> ProcessProfile:
    scene = snapshot.input_snapshot
    if not isinstance(scene, PerishableScene):
        raise ValueError("process is currently available for perishable retail only")
    demand = next(
        s.demand_qty.value
        for s in scene.demand_scenarios
        if s.scenario_label == snapshot.scenario_label
    )
    assert demand is not None
    quotient, remainder = divmod(demand, 3)
    return ProcessProfile(
        demand_by_stage=(
            quotient + int(remainder > 0),
            quotient + int(remainder > 1),
            quotient,
        )
    )


def ledger(snapshot: SimulationSnapshot, revision: int) -> tuple[ProcessStepView, ...]:
    if not 0 <= revision <= 3:
        raise ValueError("unknown process revision")
    scene, result = snapshot.input_snapshot, snapshot.result
    assert isinstance(scene, PerishableScene) and isinstance(result, PerishableResult)
    stock, price = scene.fields.stock_qty.value, scene.fields.unit_price_cents.value
    assert stock is not None and price is not None
    profile = profile_for(snapshot)
    steps: list[ProcessStepView] = []
    seen, sold = 0, 0
    for i in range(revision + 1):
        demand = profile.demand_by_stage[i - 1] if i else 0
        sales = min(stock - sold, demand)
        sold += sales
        seen += demand
        revenue = sold * price
        budget = scene.fields.budget_cents.value
        state = ProcessState(
            revision=i,
            sold=sold,
            remaining_stock=stock - sold,
            demand_seen=seen,
            unserved=seen - sold,
            revenue_cents=revenue,
            cash_out_cents=result.cash_out_cents,
            budget_balance_cents=(budget - result.cash_out_cents + revenue)
            if budget is not None
            else None,
            summary=(
                "筹备完成，整批成本在本次推演台账记入一次，尚未售出。"
                if i == 0
                else f"第{i}阶段：假设需求{demand}份，售出{sales}份，库存剩{stock - sold}份。"
            ),
        )
        steps.append(
            ProcessStepView(
                sequence=i,
                demand=demand,
                sold=sales,
                revenue_cents=sales * price,
                cash_out_cents=result.cash_out_cents if i == 0 else 0,
                before=steps[-1].after if steps else None,
                after=state,
            )
        )
    if revision == 3:
        final = steps[-1].after
        if (
            final.sold,
            final.remaining_stock,
            final.revenue_cents,
            final.revenue_cents - final.cash_out_cents,
        ) != (result.sold, result.unsold, result.revenue_cents, result.result_cents):
            raise ValueError("process does not reconcile with the authoritative simulation")
    return tuple(steps)
