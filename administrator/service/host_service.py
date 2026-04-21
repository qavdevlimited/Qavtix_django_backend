# administrator/service/host_service.py

import logging
from decimal import Decimal
from django.db.models import Count, Sum, Avg, Q, Min, Max, F
from django.db.models.functions import TruncMonth, TruncDay
from django.utils import timezone
from datetime import timedelta

from host.models import Host, VerifiedBadge
from transactions.models import Withdrawal
from django.db.models import (
    Count, Sum, Avg, Q, Min, Max, F,
    OuterRef, Subquery, IntegerField,IntegerField, DecimalField 
)
from django.db.models.functions import Coalesce
logger = logging.getLogger(__name__)


def _pct_change(current, previous):
    if not previous:
        return 100.0 if current else 0.0
    return round(((float(current) - float(previous)) / float(previous)) * 100, 2)


def _get_since(date_range):
    now = timezone.now()
    if date_range == "day":
        return now - timedelta(days=1), now
    elif date_range == "week":
        return now - timedelta(weeks=1), now
    elif date_range == "year":
        return now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0), now
    else:  # month default
        return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0), now


# ─────────────────────────────────────────────────────────────────────────────
# Host Cards
# ─────────────────────────────────────────────────────────────────────────────

class AdminHostCardService:

    @staticmethod
    def get_cards(date_range="month"):
        from host.models import Host
        from transactions.models import Order, OrderTicket
        from attendee.models import AffliateEarnings

        now          = timezone.now()
        since, until = _get_since(date_range)
        period_len   = until - since
        prev_since   = since - period_len

        # Total hosts (sellers) — all time
        total_hosts = Host.objects.count()

        # New this period
        new_this_period = Host.objects.filter(registration_date__gte=since).count()
        prev_new        = Host.objects.filter(
            registration_date__gte=prev_since, registration_date__lt=since
        ).count()
        new_growth = _pct_change(new_this_period, prev_new)

        # Tickets sold this period
        tickets_sold = (
            OrderTicket.objects
            .filter(
                order__status="completed",
                order__created_at__gte=since,
                order__created_at__lt=until,
            )
            .aggregate(t=Sum("quantity"))["t"] or 0
        )
        prev_tickets = (
            OrderTicket.objects
            .filter(
                order__status="completed",
                order__created_at__gte=prev_since,
                order__created_at__lt=since,
            )
            .aggregate(t=Sum("quantity"))["t"] or 0
        )
        tickets_growth = _pct_change(tickets_sold, prev_tickets)

        # Commission paid out (affiliate earnings paid in period)
        commission_paid = (
            Withdrawal.objects
            .filter(status="paid", created_at__gte=since.date())
            .aggregate(t=Sum("amount"))["t"] or Decimal("0")
        )
        prev_commission = (
            Withdrawal.objects
            .filter(
                status="paid",
                created_at__gte=prev_since.date(),
                created_at__lt=since.date(),
            )
            .aggregate(t=Sum("amount"))["t"] or Decimal("0")
        )
        commission_growth = _pct_change(float(commission_paid), float(prev_commission))

        return {
            "total_hosts":        total_hosts,
            "new_this_period":    new_this_period,
            "new_growth":         new_growth,
            "tickets_sold":       tickets_sold,
            "tickets_growth":     tickets_growth,
            "commission_paid":    int(commission_paid),
            "commission_growth":  commission_growth,
        }


# ─────────────────────────────────────────────────────────────────────────────
# Host List
# ─────────────────────────────────────────────────────────────────────────────

class AdminHostListService:

    @staticmethod
    def get_hosts(
        status=None,
        search=None,
        min_events=None,
        max_events=None,
        min_revenue=None,
        max_revenue=None,
        verified=None,
    ):
        from host.models import Host
        from transactions.models import Order

        qs = (
            Host.objects
            .select_related("user")
            .prefetch_related("subscriptions")
            .annotate(
                event_count=Count("hoster", distinct=True),
                total_revenue=Sum(
                    "hoster__order__total_amount",
                    filter=Q(hoster__order__status="completed"),
                ),
            )
        )

        # Status — uses user.is_active
        if status == "active":
            qs = qs.filter(user__is_active=True)
        elif status in ("suspended", "banned"):
            qs = qs.filter(user__is_active=False)

        # Verified filter
        if verified is not None:
            qs = qs.filter(verified=verified)

        # Event count range
        if min_events is not None:
            qs = qs.filter(event_count__gte=min_events)
        if max_events is not None:
            qs = qs.filter(event_count__lte=max_events)

        # Revenue range
        if min_revenue is not None:
            qs = qs.filter(total_revenue__gte=min_revenue)
        if max_revenue is not None:
            qs = qs.filter(total_revenue__lte=max_revenue)

        # Search
        if search:
            qs = qs.filter(
                Q(full_name__icontains=search)         |
                Q(business_name__icontains=search)     |
                Q(user__email__icontains=search)       |
                Q(phone_number__icontains=search)
            )

        return qs.order_by("-registration_date")

    @staticmethod
    def get_host_status(host):
        if not host.user.is_active:
            return "suspended"
        if host.verified:
            return "verified"
        return "active"


# ─────────────────────────────────────────────────────────────────────────────
# Pending Verifications
# ─────────────────────────────────────────────────────────────────────────────

class AdminHostVerificationService:

    @staticmethod
    def get_pending(
        search=None,
        status=None,
        date_from=None,
        date_to=None,
    ):
        """
        Returns hosts who have not yet been verified.
        Hosts with all KYC fields filled are considered pending review.
        """
        from host.models import Host

        qs = (
            Host.objects
            .select_related("user")
            .filter(verified=False)
            .filter(
                # Only show hosts who have submitted KYC info
                registration_number__isnull=False,
            )
            .exclude(registration_number="")
        )

        if search:
            qs = qs.filter(
                Q(full_name__icontains=search)     |
                Q(business_name__icontains=search) |
                Q(user__email__icontains=search)
            )

        if status == "active":
            qs = qs.filter(user__is_active=True)
        elif status in ("suspended", "banned"):
            qs = qs.filter(user__is_active=False)

        if date_from:
            qs = qs.filter(registration_date__date__gte=date_from)
        if date_to:
            qs = qs.filter(registration_date__date__lte=date_to)

        return qs.order_by("-registration_date")

    @staticmethod
    def approve(host_id):
        from host.models import Host
        try:
            host = Host.objects.get(id=host_id)
            host.verified = True
            host.save(update_fields=["verified"])
            return True, host
        except Host.DoesNotExist:
            return False, None

    @staticmethod
    def decline(host_id):
        from host.models import Host
        try:
            host = Host.objects.get(id=host_id)
            # Mark as declined — keep user active but unverified
            # Store decline in metadata if needed
            host.verified = False
            host.save(update_fields=["verified"])
            return True, host
        except Host.DoesNotExist:
            return False, None


# ─────────────────────────────────────────────────────────────────────────────
# Host Detail — Cards
# ─────────────────────────────────────────────────────────────────────────────

class AdminHostDetailCardService:

    @staticmethod
    def get_cards(host_id, date_range="month"):
        from host.models import Host
        from transactions.models import Order, Withdrawal

        try:
            host = Host.objects.select_related("user").get(id=host_id)
        except Host.DoesNotExist:
            return None

        since, until = _get_since(date_range)

        completed_orders = Order.objects.filter(
            event__host=host, status="completed"
        )

        # All-time earnings
        all_time_earnings = (
            completed_orders.aggregate(t=Sum("total_amount"))["t"] or Decimal("0")
        )

        # All-time payouts (approved/paid withdrawals)
        all_time_payouts = (
            Withdrawal.objects
            .filter(user=host.user, status__in=["approved", "paid"])
            .aggregate(t=Sum("amount"))["t"] or Decimal("0")
        )

        # Current balance = earnings - payouts
        current_balance = all_time_earnings - all_time_payouts

        # Next payout date — earliest pending withdrawal created_at
        now = timezone.now()

        days_ahead = 4 - now.weekday()  # Friday = 4

        if days_ahead < 0:
            days_ahead += 7

        next_friday = now + timedelta(days=days_ahead)

        return {
            "all_time_earnings": int(all_time_earnings),
            "current_balance":   int(current_balance),
            "all_time_payouts":  int(all_time_payouts),
            "next_payout_date":  next_friday,
        }


# ─────────────────────────────────────────────────────────────────────────────
# Host Detail — Profile
# ─────────────────────────────────────────────────────────────────────────────

class AdminHostDetailProfileService:

    @staticmethod
    def get_profile(host_id):
        from host.models import Host
        from payments.models import PayoutInformation
        from administrator.models import FlaggedUser

        try:
            host = (
                Host.objects
                .select_related("user")
                .prefetch_related("subscriptions__plan","gifted_badges")
                .get(id=host_id)
            )
        except Host.DoesNotExist:
            return None

        try:
            auto_payout_status = host.auto_payout.is_enabled
        except Exception:
            auto_payout_status = False

        bank_accounts = list(
            PayoutInformation.objects
            .filter(user=host.user)
            .values("id", "account_name", "account_number", "bank_name", "is_default")
        )

        is_flagged = FlaggedUser.objects.filter(
            user=host.user, is_active=True
        ).exists()

        if not host.user.is_active:
            account_status = "suspended"
        elif is_flagged:
            account_status = "flagged"
        elif host.verified:
            account_status = "verified"
        else:
            account_status = "active"

        is_subscribed = any(
            sub.status == "active"
            and sub.billing_cycle != "free"
            and sub.plan_slug != "free"   # extra safety
            and not sub.is_expired()
            for sub in host.subscriptions.all()
        )

        # Active verified badge check
        is_verified_badge = any(
            badge.is_active for badge in host.gifted_badges.all()
        )

        return {
            "host_id":             host.id,
            "full_name":           host.full_name,
            "email":               host.user.email,
            "phone_number":        host.phone_number,
            "profile_picture":     host.profile_picture,
            "profile_banner":      host.profile_banner,
            "business_name":       host.business_name,
            "business_type":       host.business_type,
            "description":         host.description,
            "registration_number": host.registration_number,
            "tax_id":              host.tax_id,
            "nin":                 host.nin,
            "country":             host.country,
            "state":               host.state,
            "city":                host.city,
            "followers":           host.followers,
            "verified":            host.verified,
            "relevant_links":      host.relevant_links,
            "date_joined":         host.registration_date,
            "bank_accounts":       bank_accounts,
            "account_status":      account_status,
            "is_subscribed":       is_subscribed,
            "is_verified":   is_verified_badge,
            "auto_payout": auto_payout_status,

        }


# ─────────────────────────────────────────────────────────────────────────────
# Host Detail — Events
# ─────────────────────────────────────────────────────────────────────────────

class AdminHostEventsService:

    @staticmethod
    def get_events(
        host_id,
        category=None,
        status=None,
        date_from=None,
        date_to=None,
        performance=None,   # high | low
        event_state=None,   # live | cancelled | ended
        search=None,
    ):
        from events.models import Event,Ticket
        from transactions.models import OrderTicket,Order
        

        qs = (
            Event.objects
            .select_related("category", "host", "event_location")
            .prefetch_related("media", "tickets")
            .filter(host_id=host_id)
            .annotate(

                revenue=Subquery(
                    Order.objects
                    .filter(
                        event=OuterRef("pk"),
                        status="completed"
                    )
                    .values("event")
                    .annotate(total=Sum("total_amount"))
                    .values("total"),
                    output_field=DecimalField(max_digits=10, decimal_places=2)
                ),

                total_listed=Subquery(
                    Ticket.objects
                    .filter(event=OuterRef("pk"))
                    .values("event")
                    .annotate(total=Sum("quantity"))
                    .values("total"),
                    output_field=IntegerField()
                ),
            )
            .annotate(
                tickets_sold=Subquery(
                    OrderTicket.objects
                    .filter(
                        order__event=OuterRef("pk"),
                        order__status="completed",
                    )
                    .values("order__event")
                    .annotate(total=Sum("quantity"))
                    .values("total"),
                    output_field=IntegerField(),
                )
            )
        )

        if category:
            qs = qs.filter(category_id=category)

        if status:
            qs = qs.filter(status__iexact=status)

        # Event state filter
        now = timezone.now()
        if event_state == "live":
            qs = qs.filter(start_datetime__lte=now, end_datetime__gte=now, status="active")
        elif event_state == "cancelled":
            qs = qs.filter(status="cancelled")
        elif event_state == "ended":
            qs = qs.filter(end_datetime__lt=now)

        if date_from:
            qs = qs.filter(start_datetime__date__gte=date_from)
        if date_to:
            qs = qs.filter(start_datetime__date__lte=date_to)

        if search:
            qs = qs.filter(title__icontains=search)


        qs = qs.annotate(
            tickets_sold=Coalesce(F("tickets_sold"), 0),
            total_listed=Coalesce(F("total_listed"), 0),
        )
        
        if performance == "fully_booked":
            return qs.filter(tickets_sold__gte=F("total_listed"))

        elif performance == "almost_full":
            return qs.filter(
                fill_rate__gte=0.8,
                fill_rate__lt=1
            )

        elif performance == "moderate_sales":
            return qs.filter(
                fill_rate__gte=0.5,
                fill_rate__lt=0.8
            )

        elif performance == "low_sales":
            return qs.filter(
                fill_rate__gt=0,
                fill_rate__lt=0.3
            )

        elif performance == "no_sales":
            return qs.filter(tickets_sold=0)

        return qs


# ─────────────────────────────────────────────────────────────────────────────
# Host Detail — Revenue / Ticket Chart
# ─────────────────────────────────────────────────────────────────────────────

class AdminHostChartService:

    @staticmethod
    def get_chart(host_id, chart_type="revenue", year=None, month=None):
        """
        chart_type: revenue | tickets
        year: int — defaults to current year
        month: int — if provided, returns daily breakdown for that month
        """
        from transactions.models import Order, OrderTicket
        from django.db.models.functions import TruncMonth, TruncDay

        now  = timezone.now()
        year = int(year) if year else now.year

        MONTH_NAMES = [
            "", "Jan", "Feb", "Mar", "Apr", "May", "Jun",
            "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"
        ]

        if month:
            # Daily breakdown for specific month
            month = int(month)
            base = Order.objects.filter(
                event__host_id=host_id,
                status="completed",
                created_at__year=year,
                created_at__month=month,
            )

            if chart_type == "revenue":
                qs = (
                    base
                    .annotate(period=TruncDay("created_at"))
                    .values("period")
                    .annotate(value=Sum("total_amount"))
                    .order_by("period")
                )
                return [
                    {
                        "label": row["period"].strftime("%-d"),
                        "value": float(row["value"] or 0),
                    }
                    for row in qs if row["period"]
                ]
            else:
                qs = (
                    OrderTicket.objects
                    .filter(
                        order__event__host_id=host_id,
                        order__status="completed",
                        order__created_at__year=year,
                        order__created_at__month=month,
                    )
                    .annotate(period=TruncDay("order__created_at"))
                    .values("period")
                    .annotate(value=Sum("quantity"))
                    .order_by("period")
                )
                return [
                    {
                        "label": row["period"].strftime("%-d"),
                        "value": row["value"] or 0,
                    }
                    for row in qs if row["period"]
                ]

        # Monthly breakdown for full year
        if chart_type == "revenue":
            qs = (
                Order.objects
                .filter(
                    event__host_id=host_id,
                    status="completed",
                    created_at__year=year,
                )
                .annotate(period=TruncMonth("created_at"))
                .values("period")
                .annotate(value=Sum("total_amount"))
                .order_by("period")
            )
            monthly = {i: 0.0 for i in range(1, 13)}
            for row in qs:
                if row["period"]:
                    monthly[row["period"].month] = float(row["value"] or 0)
        else:
            qs = (
                OrderTicket.objects
                .filter(
                    order__event__host_id=host_id,
                    order__status="completed",
                    order__created_at__year=year,
                )
                .annotate(period=TruncMonth("order__created_at"))
                .values("period")
                .annotate(value=Sum("quantity"))
                .order_by("period")
            )
            monthly = {i: 0 for i in range(1, 13)}
            for row in qs:
                if row["period"]:
                    monthly[row["period"].month] = row["value"] or 0

        return [
            {"label": MONTH_NAMES[m], "value": monthly[m]}
            for m in range(1, 13)
        ]


class AdminBadgeService:

    @staticmethod
    def gift_badge(host_id: int):
        try:
            host = Host.objects.get(id=host_id)
        except Host.DoesNotExist:
            return {"error": "Host not found"}

        # Check if already has active badge
        existing_badge = VerifiedBadge.objects.filter(
            host=host,
            is_active=True
        ).first()

        if existing_badge:
            return {
                "error": "Host already has an active verified badge"
            }

        # Optional: deactivate old badges (clean history)
        VerifiedBadge.objects.filter(host=host).update(is_active=False)

        # Create new badge
        badge = VerifiedBadge.objects.create(
            host=host,
            is_active=True
        )

        return {
            "success": True,
            "badge_id": badge.id,
            "host_id": host.id
        }