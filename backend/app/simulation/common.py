from pydantic import TypeAdapter

from app.schemas.scene import Money
from app.schemas.simulation import NonNegativeResult

_amount = TypeAdapter(NonNegativeResult)
_budget = TypeAdapter(Money)


def check_budget(budget_cents: int | None, cash_out_cents: int) -> int | None:
    """Unknown budget cannot be silently treated as zero."""
    cash_out = _amount.validate_python(cash_out_cents)
    if budget_cents is None:
        return None
    budget = _budget.validate_python(budget_cents)
    return max(0, cash_out - budget)
