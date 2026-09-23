from datetime import datetime
from typing import List, Dict


def compute_base_health(weekly_sales: List[Dict]) -> int:
    """Compute base health from recent weekly sales using active days and items sold."""
    if not weekly_sales:
        return 0
    active_days = len({
        (s.get("submitted_at") or s.get("date") or "")[:10]
        for s in weekly_sales if (s.get("submitted_at") or s.get("date"))
    })
    items_sold = sum(float(x.get("quantity") or 0) for x in weekly_sales)
    days_score = active_days / 7.0
    items_score = min(items_sold, 35) / 35.0
    return min(100, int((days_score * 0.5 + items_score * 0.5) * 100))


def compute_change_pct(current_total: float, previous_total: float) -> float:
    if previous_total <= 0:
        return 100.0 if current_total > 0 else 0.0
    return ((current_total - previous_total) / previous_total) * 100.0


def adjust_health(base_health: int, change_pct: float, cap_points: int = 15) -> int:
    """Adjust base health by change percent but cap the adjustment in absolute points.

    The change_pct is translated to points roughly equal to percent (1% -> 1 point)
    then clamped to +/- cap_points and applied to base_health.
    """
    try:
        delta = int(round(change_pct))
    except Exception:
        delta = 0
    if delta > cap_points:
        delta = cap_points
    if delta < -cap_points:
        delta = -cap_points
    newh = base_health + delta
    if newh < 0:
        newh = 0
    if newh > 100:
        newh = 100
    return newh
