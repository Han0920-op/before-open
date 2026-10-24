from app.schemas.simulation import ServiceInput, ServiceResult


def calculate_service(data: ServiceInput) -> ServiceResult:
    capacity = data.available_minutes // data.minutes_per_job
    valid = data.booked - data.cancelled
    completed = min(capacity, valid)
    revenue = completed * data.unit_price_cents
    cost = completed * data.unit_cost_cents + data.fixed_cost_cents
    return ServiceResult(
        capacity=capacity,
        valid_bookings=valid,
        completed=completed,
        revenue_cents=revenue,
        cost_cents=cost,
        simplified_result_cents=revenue - cost,
        idle_minutes=data.available_minutes - completed * data.minutes_per_job,
    )
