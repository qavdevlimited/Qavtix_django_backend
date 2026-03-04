from django.utils.timezone import now,timedelta
from transactions.models import Order


def _pct_change(current, previous):
    """Return percentage change between two values. Returns 0 if no previous."""
    if not previous:
        return 0.0
    return round(((float(current) - float(previous)) / float(previous)) * 100, 2)


def _period_delta(date_range):
    if date_range == "day":
        return timedelta(days=1)
    if date_range == "week":
        return timedelta(weeks=1)
    return timedelta(days=30)     # default: month


def _host_orders(host):
    """All completed orders for events owned by this host."""
    return Order.objects.filter(
        event__host=host,
        status="completed",
    )



def _apply_date_range(qs, date_range, field="created_at"):
    """Filter a queryset to the chosen rolling window."""
    if not date_range:
        return qs
    since = now() - _period_delta(date_range)
    return qs.filter(**{f"{field}__gte": since})


def _base_orders(host, event_id=None, date_range=None, status="completed"):
    """
    Shared starting queryset used by both views.
    Optionally scoped to a single event and/or a rolling date window.
    """
    qs = Order.objects.filter(event__host=host, status=status)
    if event_id:
        qs = qs.filter(event_id=event_id)
    if date_range:
        qs = _apply_date_range(qs, date_range)
    return qs