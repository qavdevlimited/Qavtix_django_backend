from decimal import Decimal
from django.db.models import Sum, Q
from django.utils.timezone import now as tnow,timedelta
from transactions.models import Order, Withdrawal
from datetime import date, timedelta
from django.core import signing
from django.utils import timezone


MONTH_NAMES = [
    "", "Jan", "Feb", "Mar", "Apr", "May", "Jun",
    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"
]


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
    since = tnow() - _period_delta(date_range)
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


def _next_friday(from_date: date) -> date:
    """Return the nearest upcoming Friday (including today if it is Friday)."""
    days_ahead = (4 - from_date.weekday()) % 7   # Friday = weekday 4
    if days_ahead == 0:
        days_ahead = 7   # already Friday → return next Friday
    return from_date + timedelta(days=days_ahead)


def _apply_date_range(qs, date_range: str, field: str = "created_at"):
    """Filter a queryset to a rolling time window."""
    if not date_range:
        return qs
    now = now()
    delta_map = {"day": timedelta(days=1), "week": timedelta(weeks=1), "month": timedelta(days=30)}
    delta = delta_map.get(date_range)
    if delta is None:
        return qs
    return qs.filter(**{f"{field}__gte": now - delta})


def _host_revenue(host, date_range=None):
    """
    Sum of total_amount from completed orders for this host.
    Fees are already included in total_amount; we return the gross.
    """
    qs = Order.objects.filter(event__host=host, status="completed")
    if date_range:
        qs = _apply_date_range(qs, date_range)
    return qs.aggregate(total=Sum("total_amount"))["total"] or Decimal("0.00")


def _host_payouts(host_user, date_range=None):
    """
    Sum of approved/paid withdrawals for the host user.
    Pending and rejected withdrawals are excluded.
    """
    qs = Withdrawal.objects.filter(
        user=host_user,
        status__in=("approved", "paid"),
    )
    if date_range:
        qs = _apply_date_range(qs, date_range)
    return qs.aggregate(total=Sum("amount"))["total"] or Decimal("0.00")


def _available_balance(host, host_user):
    """
    Available balance = total completed revenue
                      - all non-rejected withdrawals (pending + approved + paid).

    We exclude rejected so a failed request doesn't lock funds.
    Pending is included so the host can't double-request before approval.
    """
    total_revenue = Order.objects.filter(
        event__host=host, status="completed"
    ).aggregate(total=Sum("total_amount"))["total"] or Decimal("0.00")

    total_claimed = Withdrawal.objects.filter(
        user=host_user,
    ).exclude(status="rejected").aggregate(
        total=Sum("amount")
    )["total"] or Decimal("0.00")

    return max(total_revenue - total_claimed, Decimal("0.00"))



def _get_host(request):
    return getattr(request.user, "host_profile", None)


def _apply_day_range(qs, date_range, field="created_at"):
    now = timezone.now()
    delta = {
        "day":   timedelta(days=1),
        "week":  timedelta(weeks=1),
        "month": timedelta(days=30),
    }
    d = delta.get(date_range)
    return qs.filter(**{f"{field}__gte": now - d}) if d else qs


#  For CHECKIN SYSTEM
# ── QR Token helpers ───────────────────────────────────────────────────────────

SIGNER = signing.TimestampSigner(salt="qavtix-checkin")

# Separator that won't appear in UUIDs or integers
_SEP = "|"


def generate_checkin_token(issued_ticket_id: str, owner_id: int) -> str:
    """
    Produces a signed token binding the ticket to its CURRENT owner.

    Payload signed: "<issued_ticket_id>|<owner_id>"

    If the ticket is transferred or resold, the new owner's ID is different
    so this token becomes invalid — the previous owner's QR screenshot is
    useless. The new owner's ticket listing will return a fresh token.

    Embed this string in a QR code on the frontend.
    """
    payload = f"{issued_ticket_id}{_SEP}{owner_id}"
    return SIGNER.sign(payload)


def verify_checkin_token(token: str, max_age_days: int = 365) -> tuple[str, int]:
    """
    Verifies the signature and returns (issued_ticket_id, owner_id).
    Raises signing.BadSignature for ANY failure — bad signature,
    expired token, wrong format, missing separator, etc.
    This way the caller only needs to catch one exception type.
    """
    try:
        payload = SIGNER.unsign(token, max_age=60 * 60 * 24 * max_age_days)
        issued_ticket_id, owner_id = payload.split(_SEP, 1)
        return issued_ticket_id, int(owner_id)
    except (signing.BadSignature, signing.SignatureExpired):
        raise
    except Exception:
        # Covers ValueError (missing separator), malformed payload, etc.
        raise signing.BadSignature("Invalid token format.")