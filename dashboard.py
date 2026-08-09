from flask import Blueprint, render_template

from auth import login_required
from inventory import count_medicines, low_stock_medicines, recent_batches
from sales import today_sales_total

bp = Blueprint("dashboard", __name__)


@bp.route("/")
@login_required
def home():
    return render_template(
        "dashboard.html",
        low_stock=low_stock_medicines(),
        todays_total=today_sales_total(),
        total_products=count_medicines(),
        recent_stock=recent_batches(days=7),
    )
