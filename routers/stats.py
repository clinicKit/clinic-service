"""
routers/stats.py
Агрегация статистики за период для дашборда.
GET /stats/summary?period=this_month | last_month | this_week | all
"""

from datetime import datetime, timezone
from fastapi import APIRouter, Depends, Query
import aiosqlite

from database import get_db
from middleware.auth import get_current_user, CurrentUser
from models.schemas import StatsOut

router = APIRouter(prefix="/stats", tags=["stats"])


def _period_bounds(period: str):
    """Возвращает (start_iso, end_iso) UTC для указанного периода."""
    now = datetime.now(timezone.utc)
    if period == "this_week":
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        start = start.replace(day=now.day - now.weekday())
        end = now
    elif period == "last_month":
        first_this = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        last_prev = first_this.replace(day=1) - __import__("datetime").timedelta(days=1)
        start = last_prev.replace(day=1)
        end = first_this
    elif period == "all":
        start = datetime(2000, 1, 1, tzinfo=timezone.utc)
        end = now
    else:  # this_month (default)
        start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        end = now

    fmt = "%Y-%m-%dT%H:%M:%S"
    return start.strftime(fmt), end.strftime(fmt)


@router.get("/summary", response_model=StatsOut)
async def stats_summary(
    period: str = Query(default="this_month", description="this_month | last_month | this_week | all"),
    cu: CurrentUser = Depends(get_current_user),
    db: aiosqlite.Connection = Depends(get_db),
):
    start, end = _period_bounds(period)

    async with db.execute(
        """
        SELECT
            COUNT(*) AS total,
            SUM(CASE WHEN status = 'confirmed' THEN 1 ELSE 0 END) AS confirmed,
            SUM(CASE WHEN status = 'cancelled' THEN 1 ELSE 0 END) AS cancelled,
            SUM(CASE WHEN status = 'no_show'   THEN 1 ELSE 0 END) AS no_show
        FROM appointments
        WHERE clinic_id = ?
          AND start_time BETWEEN ? AND ?
        """,
        (cu.clinic_id, start, end),
    ) as cur:
        row = await cur.fetchone()

    total = row["total"] or 0
    confirmed = row["confirmed"] or 0
    cancelled = row["cancelled"] or 0
    no_show = row["no_show"] or 0

    # Явка = (total - cancelled - no_show) / total
    attended = total - cancelled - no_show
    rate = f"{(attended / total * 100):.1f}%" if total > 0 else "—"

    return StatsOut(
        total=total,
        confirmed=confirmed,
        cancelled=cancelled,
        no_show=no_show,
        rate=rate,
    )
