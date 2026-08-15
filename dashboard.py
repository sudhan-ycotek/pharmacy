import datetime

from flask import Blueprint, render_template

from auth import current_user, login_required
from inventory import (
    daily_stock_received,
    expiring_soon_batches,
    low_stock_medicines,
    recent_batches,
    stock_received_this_month,
    total_stock_units,
)
from sales import daily_sales_totals, list_sales

bp = Blueprint("dashboard", __name__)

SPARK_DAYS = 7  # trailing days of history in each sparkline, in addition to today


def _last_n_days(n):
    today = datetime.date.today()
    return [(today - datetime.timedelta(days=i)).isoformat() for i in range(n, -1, -1)]


def _zero_fill(rows, fields, days=SPARK_DAYS):
    by_day = {r["day"]: r for r in rows}
    return [
        {f: (by_day[day][f] if day in by_day else 0) for f in fields}
        for day in _last_n_days(days)
    ]


def _sparkline_points(values, width=100, height=30, pad=3):
    if not values:
        return ""
    vmin, vmax = min(values), max(values)
    vrange = vmax - vmin
    n = len(values)
    pts = []
    for i, v in enumerate(values):
        x = pad if n == 1 else pad + (i / (n - 1)) * (width - 2 * pad)
        y = (height / 2) if vrange == 0 else (height - pad) - ((v - vmin) / vrange) * (height - 2 * pad)
        pts.append(f"{x:.1f},{y:.1f}")
    return " ".join(pts)


def _delta_badge(today_v, prev_v):
    diff = today_v - prev_v
    if diff > 0:
        return {"text": f"+{diff:g}", "class": "good"}
    if diff < 0:
        return {"text": f"{diff:g}", "class": "critical"}
    return {"text": "0", "class": "warn"}


@bp.route("/")
@login_required
def home():
    user = current_user()

    sales_series = _zero_fill(daily_sales_totals(days=SPARK_DAYS), ("revenue", "items_sold", "profit"))
    stock_series = _zero_fill(daily_stock_received(days=SPARK_DAYS), ("received",))

    revenue_values = [d["revenue"] for d in sales_series]
    items_values = [d["items_sold"] for d in sales_series]
    profit_values = [d["profit"] for d in sales_series]
    received_values = [d["received"] for d in stock_series]

    recent_sales = list_sales(user_id=None if user["role"] == "admin" else user["id"])
    month_received = stock_received_this_month()

    return render_template(
        "dashboard.html",
        low_stock=low_stock_medicines(),
        recent_stock=recent_batches(days=7),
        expiring_soon=expiring_soon_batches(days=30),
        recent_sales=recent_sales[:5],

        todays_total=revenue_values[-1],
        items_sold_today=items_values[-1],
        profit_today=profit_values[-1],
        total_stock=total_stock_units(),
        stock_received_this_month=month_received,

        revenue_spark=_sparkline_points(revenue_values),
        items_spark=_sparkline_points(items_values),
        profit_spark=_sparkline_points(profit_values),
        stock_spark=_sparkline_points(received_values),

        revenue_delta=_delta_badge(revenue_values[-1], revenue_values[-2]),
        items_delta=_delta_badge(items_values[-1], items_values[-2]),
        profit_delta=_delta_badge(profit_values[-1], profit_values[-2]),
        stock_delta_class="good" if month_received > 0 else "warn",
    )
