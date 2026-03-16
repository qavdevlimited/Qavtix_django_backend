import calendar
from datetime import datetime, timedelta

from django.utils.timezone import make_aware, now
from django.db.models import Sum
from django.db.models.functions import ExtractMonth, ExtractDay

from .models import AffiliateLink, AffliateEarnings


def _aware_range(start_date, end_date):
    """Convert plain date objects to timezone-aware datetimes for DateTimeField filtering."""
    return (
        make_aware(datetime.combine(start_date, datetime.min.time())),
        make_aware(datetime.combine(end_date,   datetime.max.time())),
    )


def _pct_change(current, previous):
    if previous and previous > 0:
        return round((current - previous) / previous * 100, 2)
    return 0


def _build_graph(queryset, bucket_range, bucket_label):
    """Fill missing buckets with 0 and calculate change_pct vs previous bucket."""
    earnings_list = []
    prev = None
    for b in bucket_range:
        amount = next((x["total_earning"] for x in queryset if x["bucket"] == b), 0)
        change = _pct_change(amount, prev) if prev is not None else 0
        earnings_list.append({bucket_label: b, "earning": amount, "change_pct": round(change, 2)})
        prev = amount
    return earnings_list


def _get_stats(user, link_filter, earn_filter):
    """Fetch clicks, sales, earnings and conversion rate for a given period."""
    clicks = (
        AffiliateLink.objects
        .filter(user=user, **link_filter)
        .aggregate(total=Sum("clicks"))["total"] or 0
    )
    sales = (
        AffiliateLink.objects
        .filter(user=user, **link_filter)
        .aggregate(total=Sum("sales"))["total"] or 0
    )
    earnings = (
        AffliateEarnings.objects
        .filter(link__user=user, **earn_filter)
        .aggregate(total=Sum("earning"))["total"] or 0
    )
    conversion = (sales / clicks * 100) if clicks > 0 else 0
    return clicks, sales, earnings, round(conversion, 2)


# ── Filter builders ───────────────────────────────────────────────────────────

def _year_filters(selected_year):
    cur_start, cur_end = _aware_range(
        datetime(selected_year,     1,  1).date(),
        datetime(selected_year,     12, 31).date(),
    )
    prv_start, prv_end = _aware_range(
        datetime(selected_year - 1, 1,  1).date(),
        datetime(selected_year - 1, 12, 31).date(),
    )
    link_cur  = dict(created_at__gte=cur_start, created_at__lte=cur_end)
    link_prev = dict(created_at__gte=prv_start, created_at__lte=prv_end)
    earn_cur  = dict(created_at__year=selected_year)
    earn_prev = dict(created_at__year=selected_year - 1)

    graph_qs = (
        AffliateEarnings.objects
        .filter(created_at__year=selected_year)
        .annotate(bucket=ExtractMonth("created_at"))
        .values("bucket")
        .annotate(total_earning=Sum("earning"))
        .order_by("bucket")
    )
    return link_cur, link_prev, earn_cur, earn_prev, graph_qs, range(1, 13), "month"


def _month_filters(today):
    current_month, current_year = today.month, today.year
    if current_month == 1:
        prev_month, prev_year = 12, current_year - 1
    else:
        prev_month, prev_year = current_month - 1, current_year

    days_in_month      = calendar.monthrange(current_year, current_month)[1]
    days_in_prev_month = calendar.monthrange(prev_year, prev_month)[1]

    cur_start, cur_end = _aware_range(
        datetime(current_year, current_month, 1).date(),
        datetime(current_year, current_month, days_in_month).date(),
    )
    prv_start, prv_end = _aware_range(
        datetime(prev_year, prev_month, 1).date(),
        datetime(prev_year, prev_month, days_in_prev_month).date(),
    )
    link_cur  = dict(created_at__gte=cur_start, created_at__lte=cur_end)
    link_prev = dict(created_at__gte=prv_start, created_at__lte=prv_end)
    earn_cur  = dict(created_at__year=current_year, created_at__month=current_month)
    earn_prev = dict(created_at__year=prev_year,    created_at__month=prev_month)

    # Pull all earnings for the month with their day
    raw_earnings = (
        AffliateEarnings.objects
        .filter(created_at__year=current_year, created_at__month=current_month)
        .annotate(day=ExtractDay("created_at"))
        .values("day", "earning")
    )

    # Group into weeks: week 1 = days 1-7, week 2 = days 8-14, etc.
    def day_to_week(day):
        return (day - 1) // 7 + 1  # returns 1, 2, 3, or 4(+)

    week_totals = {}
    for row in raw_earnings:
        w = day_to_week(row["day"])
        week_totals[w] = week_totals.get(w, 0) + row["earning"]

    # Figure out how many weeks this month has
    total_weeks = (day_to_week(days_in_month))  # e.g. 4 or 5

    # Build graph_qs-compatible list so _build_graph works as-is
    graph_qs = [{"bucket": w, "total_earning": week_totals.get(w, 0)} for w in range(1, total_weeks + 1)]

    return link_cur, link_prev, earn_cur, earn_prev, graph_qs, range(1, total_weeks + 1), "week"

def _week_filters(today):
    week_start      = today - timedelta(days=today.weekday())       # Monday
    week_end        = week_start + timedelta(days=6)                # Sunday
    prev_week_start = week_start - timedelta(weeks=1)
    prev_week_end   = week_end   - timedelta(weeks=1)

    cur_start, cur_end = _aware_range(week_start, week_end)
    prv_start, prv_end = _aware_range(prev_week_start, prev_week_end)

    link_cur  = dict(created_at__gte=cur_start, created_at__lte=cur_end)
    link_prev = dict(created_at__gte=prv_start, created_at__lte=prv_end)
    earn_cur  = dict(created_at__gte=week_start,      created_at__lte=week_end)
    earn_prev = dict(created_at__gte=prev_week_start, created_at__lte=prev_week_end)

    graph_qs = (
        AffliateEarnings.objects
        .filter(created_at__gte=week_start, created_at__lte=week_end)
        .annotate(bucket=ExtractDay("created_at"))
        .values("bucket")
        .annotate(total_earning=Sum("earning"))
        .order_by("bucket")
    )
    bucket_range = [(week_start + timedelta(days=i)).day for i in range(7)]
    return link_cur, link_prev, earn_cur, earn_prev, graph_qs, bucket_range, "day"


def _day_filters(today):
    yesterday = today - timedelta(days=1)

    cur_start, cur_end = _aware_range(today, today)
    prv_start, prv_end = _aware_range(yesterday, yesterday)

    link_cur  = dict(created_at__gte=cur_start, created_at__lte=cur_end)
    link_prev = dict(created_at__gte=prv_start, created_at__lte=prv_end)
    earn_cur  = dict(created_at=today)
    earn_prev = dict(created_at=yesterday)

    # DateField has no hours — show last 7 days as daily buckets
    last_7 = [(today - timedelta(days=i)).day for i in range(6, -1, -1)]
    graph_qs = (
        AffliateEarnings.objects
        .filter(created_at__gte=today - timedelta(days=6), created_at__lte=today)
        .annotate(bucket=ExtractDay("created_at"))
        .values("bucket")
        .annotate(total_earning=Sum("earning"))
        .order_by("bucket")
    )
    return link_cur, link_prev, earn_cur, earn_prev, graph_qs, last_7, "day"


# ── Main service entry point ──────────────────────────────────────────────────

def get_affiliate_dashboard(user, filter_by, year_param):
    today = now().date()

    if year_param or not filter_by:
        selected_year = int(year_param) if year_param else today.year
        link_cur, link_prev, earn_cur, earn_prev, graph_qs, bucket_range, bucket_label = _year_filters(selected_year)
        active_filter = f"year={selected_year}"

    elif filter_by == "month":
        link_cur, link_prev, earn_cur, earn_prev, graph_qs, bucket_range, bucket_label = _month_filters(today)
        active_filter = "month"

    elif filter_by == "week":
        link_cur, link_prev, earn_cur, earn_prev, graph_qs, bucket_range, bucket_label = _week_filters(today)
        active_filter = "week"

    elif filter_by == "day":
        link_cur, link_prev, earn_cur, earn_prev, graph_qs, bucket_range, bucket_label = _day_filters(today)
        active_filter = "day"

    else:
        return None, "Invalid filter. Use: month, week, day or ?year=YYYY"

    # Scope graph_qs to this user (only for real querysets, not pre-built lists)
    if hasattr(graph_qs, 'filter'):
        graph_qs = graph_qs.filter(link__user=user)

    earnings_graph = _build_graph(graph_qs, bucket_range, bucket_label)

    cur_clicks, cur_sales, cur_earnings, cur_conversion = _get_stats(user, link_cur, earn_cur)
    prv_clicks, prv_sales, prv_earnings, prv_conversion = _get_stats(user, link_prev, earn_prev)

    return {
        "filter":                     active_filter,
        "earnings_graph":             earnings_graph,
        "total_clicks":               cur_clicks,
        "total_clicks_change_pct":    _pct_change(cur_clicks,     prv_clicks),
        "total_sales":                cur_sales,
        "total_sales_change_pct":     _pct_change(cur_sales,      prv_sales),
        "conversion_rate":            cur_conversion,
        "conversion_rate_change_pct": _pct_change(cur_conversion, prv_conversion),
        "total_earnings":             cur_earnings,
        "total_earnings_change_pct":  _pct_change(cur_earnings,   prv_earnings),
    }, None