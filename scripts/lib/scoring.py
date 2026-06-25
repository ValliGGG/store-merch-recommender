"""Pure scoring functions — unit-testable, no I/O.

Scoring model: units sold across the most-recent N orders (window defined
by config.scoring.recent_orders_window).  See the comment in config.yaml
for why we use order-id monotonicity instead of date-based recency buckets.
"""
from __future__ import annotations

from datetime import date, datetime, timezone


def cold_start_bonus(
    created_at_iso: str | None,
    weights: dict,
    today: date | None = None,
) -> float:
    """Boost newly-created products so they're not buried by zero-sales scores."""
    if not created_at_iso:
        return 0.0
    today = today or datetime.now(timezone.utc).date()
    try:
        created = datetime.fromisoformat(created_at_iso.replace("Z", "+00:00")).date()
    except ValueError:
        return 0.0
    days = (today - created).days
    window = int(weights["cold_start_window_days"])
    if days < 0 or days >= window:
        return 0.0
    return (window - days) * float(weights["cold_start_weight"])
