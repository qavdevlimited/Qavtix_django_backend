# administrator/service/user_detail_service.py

import logging
from decimal import Decimal
from django.db.models import Count, Sum, Min, Max, Q
from django.utils import timezone
from django.contrib.auth import get_user_model
from rest_framework import request

from attendee.models import AffliateEarnings
from events.models import EventMedia
from transactions.models import Withdrawal
from django.db import models

logger = logging.getLogger(__name__)
User = get_user_model()


def _get_date_range(filter_type):
    """Returns (since, until) tuple based on filter type."""
    now   = timezone.now()
    until = now

    if filter_type == "day":
        since = now - timezone.timedelta(days=1)
    elif filter_type == "week":
        since = now - timezone.timedelta(weeks=1)
    elif filter_type == "month":
        since = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    elif filter_type == "year":
        since = now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
    else:
        since = now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)

    return since, until


def _pct_change(current, previous):
    if not previous:
        return 100.0 if current else 0.0
    return round(((float(current) - float(previous)) / float(previous)) * 100, 2)


class UserDetailCardService:
    """
    4 KPI cards for the admin user detail page.
    Filterable by date range: day | week | month | year
    Compares against the previous equivalent period.
    """

    @staticmethod
    def get_cards(user_id, date_range="month"):
        from transactions.models import Order, OrderTicket, Refund

        since, until = _get_date_range(date_range)
        period_len   = until - since
        prev_since   = since - period_len
        prev_until   = since

        def _orders(start, end, status="completed"):
            return Order.objects.filter(
                user_id=user_id,
                status=status,
                created_at__gte=start,
                created_at__lt=end,
            )

        # ── Total spent ───────────────────────────────────────────────────────
        curr_spent = _orders(since, until).aggregate(t=Sum("total_amount"))["t"] or Decimal("0")
        prev_spent = _orders(prev_since, prev_until).aggregate(t=Sum("total_amount"))["t"] or Decimal("0")

        # ── Tickets bought ────────────────────────────────────────────────────
        curr_tickets = (
            OrderTicket.objects
            .filter(order__user_id=user_id, order__status="completed",
                    order__created_at__gte=since, order__created_at__lt=until)
            .aggregate(t=Sum("quantity"))["t"] or 0
        )
        prev_tickets = (
            OrderTicket.objects
            .filter(order__user_id=user_id, order__status="completed",
                    order__created_at__gte=prev_since, order__created_at__lt=prev_until)
            .aggregate(t=Sum("quantity"))["t"] or 0
        )

        # ── Refund count ──────────────────────────────────────────────────────
        curr_refunds = _orders(since, until, status="refunded").count()
        prev_refunds = _orders(prev_since, prev_until, status="refunded").count()

        # ── Last order value ──────────────────────────────────────────────────
        last_order = (
            Order.objects
            .filter(user_id=user_id, status="completed")
            .order_by("-created_at")
            .values_list("total_amount", flat=True)
            .first()
        )
        prev_last_order = (
            Order.objects
            .filter(user_id=user_id, status="completed", created_at__lt=since)
            .order_by("-created_at")
            .values_list("total_amount", flat=True)
            .first()
        )

        return {
            "total_spent":             curr_spent,
            "total_spent_change":      _pct_change(curr_spent, prev_spent),
            "tickets_bought":          curr_tickets,
            "tickets_bought_change":   _pct_change(curr_tickets, prev_tickets),
            "refund_count":            curr_refunds,
            "refund_count_change":     _pct_change(curr_refunds, prev_refunds),
            "last_order_value":        last_order or Decimal("0"),
            "last_order_value_change": _pct_change(last_order or 0, prev_last_order or 0),
        }


class UserDetailSpendChartService:
    """
    Net spend chart for admin user detail page.
    Returns daily spend points for the selected period.
    """

    @staticmethod
    def get_chart(user_id, date_range="month"):
        from transactions.models import Order
        from django.db.models.functions import TruncDay, TruncWeek, TruncMonth

        since, until = _get_date_range(date_range)

        if date_range in ("day", "week"):
            trunc_fn = TruncDay("created_at")
            fmt      = "%d %b"
        elif date_range == "month":
            trunc_fn = TruncDay("created_at")
            fmt      = "%-d"
        else:  # year
            trunc_fn = TruncMonth("created_at")
            fmt      = "%b"

        qs = (
            Order.objects
            .filter(
                user_id=user_id,
                status="completed",
                created_at__gte=since,
                created_at__lt=until,
            )
            .annotate(period=trunc_fn)
            .values("period")
            .annotate(amount=Sum("total_amount"))
            .order_by("period")
        )

        return [
            {
                "label":  row["period"].strftime(fmt),
                "amount": row["amount"] or Decimal("0"),
            }
            for row in qs if row["period"]
        ]


class UserDetailOrderHistoryService:
    """
    Paginated event purchase history for admin user detail page.
    Filterable by quantity range, purchase date range, amount range.
    No N+1 — single optimised query.
    """

    @staticmethod
    def get_orders(
        user_id,
        qty_min=None,
        qty_max=None,
        date_from=None,
        date_to=None,
        min_amount=None,
        max_amount=None,
    ):
        from transactions.models import Order
        from django.db.models import OuterRef, Subquery, IntegerField
        from django.db.models.functions import Coalesce

        qs = (
            Order.objects
            .select_related(
                "event",
                "event__category",
            )
            .prefetch_related("tickets", "event__media")
            .filter(user_id=user_id)
        )

        if date_from:
            qs = qs.filter(created_at__date__gte=date_from)
        if date_to:
            qs = qs.filter(created_at__date__lte=date_to)
        if min_amount is not None:
            qs = qs.filter(total_amount__gte=min_amount)
        if max_amount is not None:
            qs = qs.filter(total_amount__lte=max_amount)

        # Annotate total quantity per order to allow qty filtering
        qs = qs.annotate(
            total_qty=Sum("tickets__quantity")
        )

        if qty_min is not None:
            qs = qs.filter(total_qty__gte=qty_min)
        if qty_max is not None:
            qs = qs.filter(total_qty__lte=qty_max)

        event_image_subq = (
            EventMedia.objects
            .filter(event=OuterRef("event_id"))
            .order_by("-is_featured", "id")   # Featured first, then oldest first
            .values("image_url")[:1]
        )

        qs = qs.annotate(
            featured_image=Subquery(event_image_subq, output_field=models.URLField())
        )

        return qs.order_by("-created_at")


class UserDetailProfileService:
    """
    Full profile card for admin user detail page.
    Includes attendee info, host info (if any), bank accounts,
    all-time purchases, wallet balance, activity dates.
    Single DB pass — no N+1.
    """

    @staticmethod
    def get_profile(user_id):
        from transactions.models import Order, IssuedTicket
        from payments.models import PayoutInformation

        try:
            user = (
                User.objects
                .select_related("attendee_profile", "host_profile")
                .prefetch_related("payout_accounts")
                .get(id=user_id)
            )
        except User.DoesNotExist:
            return None

        attendee = getattr(user, "attendee_profile", None)
        host     = getattr(user, "host_profile", None)

        # ── All-time purchase stats ───────────────────────────────────────────
        order_agg = Order.objects.filter(
            user=user, status="completed"
        ).aggregate(
            total_spent    = Sum("total_amount"),
            first_purchase = Min("created_at"),
            last_purchase  = Max("created_at"),
        )

        all_time_tickets = (
            IssuedTicket.objects
            .filter(owner=user, status__in=["active", "used", "resold"])
            .count()
        )

        # ── Bank accounts ─────────────────────────────────────────────────────
        bank_accounts = list(
            PayoutInformation.objects
            .filter(user=user)
            .values("id", "account_name", "account_number", "bank_name", "is_default")
        )

        # ── Account status ────────────────────────────────────────────────────
        from administrator.models import FlaggedUser
        is_flagged = FlaggedUser.objects.filter(user=user, is_active=True).exists()

        if not user.is_active:
            account_status = "suspended"
        elif is_flagged:
            account_status = "flagged"
        else:
            account_status = "active"

        #balance 
        total_earnings = (
                AffliateEarnings.objects
                .select_for_update()
                .filter(attendee=user.attendee_profile.id, status="paid")
                .aggregate(total=Sum("earning"))["total"]
                or Decimal("0.00")
            )

        total_withdrawn = (
            Withdrawal.objects
            .select_for_update()
            .filter(user=user)
            .exclude(status="rejected")
            .aggregate(total=Sum("amount"))["total"]
            or Decimal("0.00")
        )
        print(total_earnings,total_withdrawn  )

        available_balance = total_earnings - total_withdrawn


        return {
            # Identity
            "user_id":         user.id,
            "email":           user.email,
            "full_name":       attendee.full_name       if attendee else "",
            "phone_number":    attendee.phone_number    if attendee else "",
            "profile_picture": attendee.profile_picture if attendee else None,
            "dob":             attendee.dob             if attendee else None,
            "gender":          attendee.gender          if attendee else "",
            "date_joined":     user.date_joined,

            # Location
            "country": attendee.country if attendee else "",
            "state":   attendee.state   if attendee else "",
            "city":    attendee.city    if attendee else "",

            # Host info (if host)
            "is_host":      host is not None,
            "business_name":   host.business_name   if host else None,
            "business_type":   host.business_type   if host else None,
            "description":     host.description     if host else None,
            "relevant_links":  host.relevant_links  if host else [],

            # Stats
            "all_time_spend":   order_agg["total_spent"]    or Decimal("0"),
            "all_time_tickets": all_time_tickets,
            "first_purchase":   order_agg["first_purchase"],
            "last_purchase":    order_agg["last_purchase"],

            # Bank accounts
            "bank_accounts": bank_accounts,

            # Status
            "account_status": account_status,
            "is_active":      user.is_active,
            "wallet_balance": available_balance,
        }